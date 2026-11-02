import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterEach, expect, test, vi } from "vitest";
import {
  createLiveWikiPolicy,
  LiveWikiPolicy,
  type WikiPolicySnapshot,
} from "../src/live-policy.js";
import * as capabilities from "../src/capabilities.js";
import * as personal from "../src/personal-skill-adapter.js";
import * as skillRegistry from "../src/skills.js";
import { createC7McpServer } from "../src/server.js";
import { computeSkillPackage, loadC7SkillRegistry } from "../src/skills.js";

const cleanup: Array<() => Promise<unknown>> = [];
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
afterEach(async () => {
  vi.restoreAllMocks();
  for (const close of cleanup.splice(0).reverse()) await close();
});

test("rejects a changed materialized HEAD on the next live admission and recovers", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "wiki-live-identity-"));
  cleanup.push(() => rm(root, { force: true, recursive: true }));
  const moduleRoot = path.join(root, "module");
  const repositoryRoot = path.join(moduleRoot, "self-openwiki");
  const openWikiRoot = path.join(moduleRoot, ".work", "openwiki");
  await mkdir(path.join(repositoryRoot, "config"), { recursive: true });
  await mkdir(path.join(moduleRoot, "patches", "openwiki"), {
    recursive: true,
  });
  await mkdir(openWikiRoot, { recursive: true });
  const execute = promisify(execFile);
  const git = (...args: string[]) =>
    execute("git", ["-C", openWikiRoot, ...args], { windowsHide: true });
  const pin = personal.PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT;
  await git("init", "--initial-branch=main");
  await git(
    "fetch",
    "--no-tags",
    path.resolve(import.meta.dirname, "../../../upstream/openwiki"),
    pin,
  );
  await git("update-ref", "--no-deref", "HEAD", pin);
  const patchManifest = Buffer.from("fixture patch manifest\n");
  await writeFile(
    path.join(moduleRoot, "patches", "openwiki", "manifest.json"),
    patchManifest,
  );
  const marker = Buffer.from(
    JSON.stringify({
      schemaVersion: 1,
      domain: "selfopenwiki:openwiki-materialization:v1",
      upstreamCommit: pin,
      manifestHash: createHash("sha256").update(patchManifest).digest("hex"),
      affectedFiles: [],
    }),
  );
  await writeFile(
    path.join(openWikiRoot, ".selfopenwiki-materialization.json"),
    marker,
  );
  const markerHash = `sha256:${createHash("sha256").update(marker).digest("hex")}`;
  for (const name of [
    "defaults.json",
    "sensitive-files.json",
    "personal-openwiki-compatibility.json",
  ])
    await writeFile(path.join(repositoryRoot, "config", name), "fixture");
  const evidencePath = path.join(root, "evidence.json");
  await writeFile(evidencePath, "fixture");
  const fingerprint = {
    buildHash: "build",
    contractsHash: "contracts",
    dependencyHash: "dependency",
    matrixHash: "matrix",
    moduleHasherHash: "hasher",
    codeHash: "code",
    skillHash: "skill",
    testHash: "test",
    verifierHash: "verifier",
  };
  const gate = {
    fingerprint,
    isToolVerified: () => true,
    records: () => [],
  } as unknown as capabilities.RuntimeCapabilityGate;
  vi.spyOn(capabilities, "loadRuntimeCapabilityGate").mockResolvedValue(gate);
  vi.spyOn(personal, "loadPersonalCompatibilityManifest").mockResolvedValue({
    build: {
      generatedMarkerHash: markerHash,
      parentSourceManifestHash: "same",
    },
    skill: { packageHash: `sha256:${"a".repeat(64)}` },
    upstream: { commit: pin },
  } as unknown as personal.PersonalCompatibilityManifest);
  vi.spyOn(personal, "assertPersonalCompatibility").mockResolvedValue(
    undefined,
  );
  vi.spyOn(personal, "computeModuleSourceManifestHash").mockResolvedValue(
    "same",
  );
  vi.spyOn(skillRegistry, "loadC7SkillRegistry").mockResolvedValue({
    list: () => [{ packageHash: `sha256:${"b".repeat(64)}` }],
    select: () => ({}),
  } as unknown as skillRegistry.C7SkillRegistry);
  const policy = await createLiveWikiPolicy({
    repositoryRoot,
    openWikiRoot,
    evidencePath,
    capabilityGate: gate,
  });
  const invoke = policy.wrap({ invoke: async () => ({ ok: true }) }).invoke;
  expect(await invoke("openwiki_list_skills", {})).toMatchObject({ ok: true });
  await git(
    "-c",
    "user.name=Fixture",
    "-c",
    "user.email=fixture@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "commit",
    "--allow-empty",
    "-m",
    "Drift",
  );
  expect(await invoke("openwiki_list_skills", {})).toMatchObject({
    ok: false,
    error: { code: "capability_unverified" },
  });
  await git("update-ref", "--no-deref", "HEAD", pin);
  expect(await invoke("openwiki_list_skills", {})).toMatchObject({ ok: true });
}, 30_000);

test("the same MCP connection loads a verified replacement Skill on its next call", async () => {
  const fixture = await connectPolicy();
  const before = await fixture.list();
  const selected = fixture.policy.skills.select([]);
  await fixture.publish("# New implementation and reproduction rules\n");
  const after = await fixture.list();

  expect(before.skills[0].packageHash).not.toBe(after.skills[0].packageHash);
  expect(
    fixture.policy.skills.select([]).skills[0].files[0].bytes.toString(),
  ).toBe("# New implementation and reproduction rules\n");
  expect(selected.skills[0].files[0].bytes.toString()).toBe(
    "# Initial rules\n",
  );
});

test("rejects an untrusted replacement and recovers on the next verified generation", async () => {
  const fixture = await connectPolicy();
  await fixture.tamper();
  expect(await fixture.list()).toMatchObject({
    ok: false,
    error: { code: "capability_unverified" },
  });
  expect(fixture.policy.capabilities.records()).toEqual([]);
  await fixture.publish("# Verified repair\n");
  expect(await fixture.list()).toMatchObject({ ok: true });
});

test("refuses changed module files before a new verification marker exists", async () => {
  const fixture = await connectPolicy();
  await fixture.changeUnverifiedSource();
  expect(await fixture.list()).toMatchObject({
    ok: false,
    error: { code: "capability_unverified" },
  });
  await fixture.publish("# Verified replacement\n");
  expect(await fixture.list()).toMatchObject({ ok: true });
});

test("keeps status diagnostic when module validation throws", async () => {
  const fixture = await connectPolicy();
  fixture.setValidationFailure(true);
  expect(await fixture.list()).toMatchObject({
    ok: false,
    error: { code: "capability_unverified" },
  });
  expect(await fixture.status()).toMatchObject({
    ok: true,
    recovery: {
      message: expect.stringContaining("validation could not complete"),
    },
  });
  fixture.setValidationFailure(false);
  expect(await fixture.list()).toMatchObject({ ok: true });
});

test("retries a transient replacement-load failure without another marker change", async () => {
  const fixture = await connectPolicy();
  fixture.setLoadFailure(true);
  await fixture.publish("# Replacement after transient error\n");
  expect(await fixture.list()).toMatchObject({
    ok: false,
    error: { code: "capability_unverified" },
  });
  fixture.setLoadFailure(false);
  expect(await fixture.list()).toMatchObject({ ok: true });
});

test("reports missing verification and requests reconnect for changed executables", async () => {
  const fixture = await connectPolicy();
  await fixture.removeEvidence();
  expect(await fixture.list()).toMatchObject({
    ok: false,
    error: { code: "capability_unverified" },
  });
  fixture.changeExecutable();
  await fixture.publish("# New executable rules\n");
  expect(await fixture.list()).toMatchObject({
    ok: false,
    recovery: { message: expect.stringContaining("Reconnect this MCP server") },
  });
});

test("recovers when the same verification marker is restored", async () => {
  const fixture = await connectPolicy();
  const marker = await fixture.readEvidence();
  await fixture.removeEvidence();
  expect(await fixture.list()).toMatchObject({
    ok: false,
    error: { code: "capability_unverified" },
  });
  await fixture.restoreEvidence(marker);
  expect(await fixture.list()).toMatchObject({ ok: true });
});

test("defers refresh until in-flight calls finish and coalesces concurrent refresh", async () => {
  const fixture = await connectPolicy();
  const before = await fixture.list();
  const hold = fixture.holdNextCall();
  const running = fixture.list();
  await hold.started;
  await fixture.publish("# Next generation\n");
  expect(await fixture.list()).toMatchObject({
    ok: false,
    error: { code: "capability_unverified" },
  });
  hold.release();
  expect((await running).skills).toEqual(before.skills);
  const loads = fixture.loads();
  const results = await Promise.all([fixture.list(), fixture.list()]);
  expect(fixture.loads()).toBe(loads + 1);
  expect(results[0].skills).toEqual(results[1].skills);
  expect(results[0].skills).not.toEqual(before.skills);
});

test("rejects a newly verified executable while an old call remains active", async () => {
  const fixture = await connectPolicy();
  const originalEvidence = await fixture.readEvidence();
  const hold = fixture.holdNextCall();
  const running = fixture.list();
  await hold.started;
  fixture.changeExecutable();
  await fixture.publishEvidenceOnly();
  expect(await fixture.list()).toMatchObject({
    ok: false,
    recovery: { message: expect.stringContaining("Reconnect this MCP server") },
  });
  hold.release();
  expect(await running).toMatchObject({ ok: true });
  fixture.resetExecutable();
  await fixture.restoreEvidence(originalEvidence);
  expect(await fixture.list()).toMatchObject({ ok: true });
});

async function connectPolicy() {
  const root = await mkdtemp(path.join(os.tmpdir(), "wiki-live-policy-"));
  cleanup.push(() => rm(root, { force: true, recursive: true }));
  const packageRoot = path.join(root, "base");
  const manifestPath = path.join(root, "trusted.json");
  const markerPath = path.join(root, "verified.json");
  await mkdir(packageRoot);
  let generation = 0;
  const publish = async (text: string) => {
    await writeFile(path.join(packageRoot, "SKILL.md"), text);
    const computed = await computeSkillPackage(packageRoot);
    await writeFile(
      manifestPath,
      JSON.stringify({
        version: 1,
        baseSkill: {
          id: "kg-c7-project-wiki",
          path: "base",
          packageHash: computed.packageHash,
          title: "Base",
          description: "Test rules",
        },
        specializedSkills: [],
      }),
    );
    await writeFile(markerPath, String(++generation));
  };
  await publish("# Initial rules\n");
  const gate = { isToolVerified: () => true, records: () => [] };
  const readVersion = () => readFile(markerPath, "utf8").catch(() => null);
  let restartBinding = "same-executable";
  let loadCount = 0;
  let failValidation = false;
  let failLoad = false;
  let hold: { started(): void; wait: Promise<void> } | undefined;
  const load = async (): Promise<WikiPolicySnapshot> => {
    loadCount++;
    if (failLoad) throw new Error("Transient policy load failure");
    const skills = await loadC7SkillRegistry(manifestPath, root);
    return {
      capabilities: gate,
      moduleSourceHash: skills.list()[0].packageHash,
      skills,
      personalSkill: {
        resolve: async () => ({ skillIds: [], skillAggregateHash: "unused" }),
      },
      restartBinding,
    };
  };
  const policy = new LiveWikiPolicy({
    initial: await load(),
    version: await readVersion(),
    readVersion,
    load,
    validateCurrent: async (snapshot) => {
      if (failValidation) throw new Error("Transient validation failure");
      if (restartBinding !== "same-executable") return "restart_required";
      return (
        (await computeSkillPackage(packageRoot)).packageHash ===
        snapshot.skills.list()[0].packageHash
      );
    },
  });
  const server = createC7McpServer({
    capabilityGate: gate,
    runtime: policy.wrap({
      invoke: async () => {
        if (hold) {
          const pending = hold;
          hold = undefined;
          pending.started();
          await pending.wait;
        }
        return {
          ok: true,
          status: "skills_listed",
          recovery: { action: "none" },
          skills: policy.skills.list(),
        };
      },
    }),
  });
  const client = new Client({ name: "live-policy-test", version: "1" });
  const [clientTransport, serverTransport] =
    InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  cleanup.push(() => client.close());
  return {
    policy,
    publish,
    publishEvidenceOnly: () => writeFile(markerPath, String(++generation)),
    setValidationFailure: (value: boolean) => {
      failValidation = value;
    },
    setLoadFailure: (value: boolean) => {
      failLoad = value;
    },
    loads: () => loadCount,
    removeEvidence: () => rm(markerPath),
    readEvidence: () => readFile(markerPath, "utf8"),
    restoreEvidence: (bytes: string) => writeFile(markerPath, bytes),
    changeExecutable: () => {
      restartBinding = "new-executable";
    },
    resetExecutable: () => {
      restartBinding = "same-executable";
    },
    changeUnverifiedSource: () =>
      writeFile(path.join(packageRoot, "SKILL.md"), "# Unverified source\n"),
    tamper: async () => {
      await writeFile(
        path.join(packageRoot, "SKILL.md"),
        "# Untrusted replacement\n",
      );
      await writeFile(markerPath, String(++generation));
    },
    holdNextCall: () => {
      const started = deferred();
      const wait = deferred();
      hold = { started: started.resolve, wait: wait.promise };
      return { started: started.promise, release: wait.resolve };
    },
    list: async () => {
      const result = await client.callTool({
        name: "openwiki_list_skills",
        arguments: {},
      });
      return JSON.parse((result.content as Array<{ text: string }>)[0].text);
    },
    status: () =>
      policy
        .wrap({
          invoke: async () => ({ ok: true, recovery: { action: "none" } }),
        })
        .invoke("openwiki_status", {}),
  };
}
