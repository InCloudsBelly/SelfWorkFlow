import {
  appendFile,
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  symlink,
  truncate,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { afterEach, describe, expect, test } from "vitest";
import { TOOL_NAMES } from "../src/contracts.js";
import {
  computeCapabilityFingerprint,
  loadRuntimeCapabilityGate,
  validateCapabilityMatrix,
  type CapabilityFingerprint,
} from "../src/capabilities.js";

const tempDirs: string[] = [];
const repositoryRoot = path.resolve(import.meta.dirname, "../..");
const openWikiRoot = path.resolve(repositoryRoot, "..", ".work", "openwiki");
const verifierPath = path.join(
  repositoryRoot,
  "scripts",
  "verify-capabilities.mts",
);
const fingerprint = Object.fromEntries(
  [
    "buildHash",
    "codeHash",
    "contractsHash",
    "dependencyHash",
    "matrixHash",
    "moduleHasherHash",
    "skillHash",
    "testHash",
    "verifierHash",
  ].map((key, index) => [key, `sha256:${index.toString(16).repeat(64)}`]),
) as CapabilityFingerprint;

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("capability matrix and runtime evidence", () => {
  test("assigns the exact ordered external capability ids and anchors", async () => {
    const matrix = JSON.parse(
      await readFile(
        path.join(repositoryRoot, "config", "capability-matrix.json"),
        "utf8",
      ),
    ) as {
      tools: Array<{
        capabilities: string[];
        implementation: string;
        name: string;
        schema: string;
        tests: string[];
      }>;
    };

    expect(matrix.tools.map(({ name }) => name)).toEqual(TOOL_NAMES);
    expect(
      matrix.tools.filter(({ name }) =>
        [
          "openwiki_begin_external_update",
          "openwiki_finalize_external_update",
        ].includes(name),
      ),
    ).toEqual([
      {
        name: "openwiki_begin_external_update",
        implementation:
          "mcp-server/src/runtime.ts#openwiki_begin_external_update",
        schema: "mcp-server/src/contracts.ts#openwiki_begin_external_update",
        capabilities: ["update.external-agent.begin"],
        tests: [
          "mcp-server/test/contracts.c7.ts",
          "mcp-server/test/server.c7.ts",
          "mcp-server/test/runtime.c7.ts",
          "mcp-server/test/external-update.c7.ts",
          "mcp-server/test/external-update-transaction.c7.ts",
          "mcp-server/test/startup-rehydration.c7.ts",
        ],
      },
      {
        name: "openwiki_finalize_external_update",
        implementation:
          "mcp-server/src/runtime.ts#openwiki_finalize_external_update",
        schema: "mcp-server/src/contracts.ts#openwiki_finalize_external_update",
        capabilities: ["update.external-agent.reviewed-finalize"],
        tests: [
          "mcp-server/test/contracts.c7.ts",
          "mcp-server/test/server.c7.ts",
          "mcp-server/test/runtime.c7.ts",
          "mcp-server/test/external-update.c7.ts",
          "mcp-server/test/external-update-transaction.c7.ts",
          "mcp-server/test/publish.c7.ts",
          "mcp-server/test/recovery.c7.ts",
          "mcp-server/test/startup-rehydration.c7.ts",
        ],
      },
    ]);
  });

  test("matrix covers every tool with existing implementation, schema, and tests", async () => {
    await expect(
      validateCapabilityMatrix({ repositoryRoot }),
    ).resolves.toBeUndefined();
  });

  test("binds the dedicated C7 Vitest discovery configuration into evidence", async () => {
    const current = await computeCapabilityFingerprint({
      openWikiRoot,
      repositoryRoot,
    });
    const source = await readFile(
      path.join(repositoryRoot, "mcp-server", "src", "capabilities.ts"),
      "utf8",
    );

    expect(current.testHash).toMatch(/^sha256:[a-f0-9]{64}$/u);
    expect(source).toContain('"mcp-server/vitest.config.ts"');
  });

  test("enables all tools only for exact host-bound matching evidence", async () => {
    const evidencePath = await writeEvidence(fingerprint);
    const gate = await loadRuntimeCapabilityGate({
      computeFingerprint: async () => fingerprint,
      evidencePath,
      openWikiRoot,
      repositoryRoot,
    });

    expect(TOOL_NAMES.every((name) => gate.isToolVerified(name))).toBe(true);
    expect(gate.records().length).toBeGreaterThan(10);
    expect(gate.failureReason).toBeUndefined();
  });

  test.each(Object.keys(fingerprint) as Array<keyof CapabilityFingerprint>)(
    "fails closed when the evidence %s is stale",
    async (field) => {
      const evidencePath = await writeEvidence({
        ...fingerprint,
        [field]: `sha256:${"f".repeat(64)}`,
      });
      const stale = await loadRuntimeCapabilityGate({
        computeFingerprint: async () => fingerprint,
        evidencePath,
        openWikiRoot,
        repositoryRoot,
      });

      expect(TOOL_NAMES.some((name) => stale.isToolVerified(name))).toBe(false);
      expect(stale.failureReason).toBe(
        "Capability evidence is missing, invalid, or stale.",
      );
    },
  );

  test("fails closed when evidence is absent", async () => {
    const evidencePath = await writeEvidence(fingerprint);
    const missing = await loadRuntimeCapabilityGate({
      computeFingerprint: async () => fingerprint,
      evidencePath: path.join(path.dirname(evidencePath), "missing.json"),
      openWikiRoot,
      repositoryRoot,
    });

    expect(TOOL_NAMES.some((name) => missing.isToolVerified(name))).toBe(false);
    expect(missing.failureReason).toBe(
      "Capability evidence is missing, invalid, or stale.",
    );
  });
});

describe("staged capability evidence activation", () => {
  test("exposes a direct-execution guard and one private activation owner", async () => {
    const source = await readFile(verifierPath, "utf8");

    expect(source).toContain(
      "export async function activateVerifiedCapabilityEvidence",
    );
    expect(source).toContain("function isDirectExecution");
  });

  test("leaves failed activation cleanup to the root-bound activation owner", async () => {
    const source = await readFile(verifierPath, "utf8");
    const verificationOwner = source.slice(
      source.indexOf("async function runCapabilityVerification"),
      source.indexOf(
        "export async function activateVerifiedCapabilityEvidence",
      ),
    );

    expect(verificationOwner).not.toMatch(
      /catch \(error\) \{[\s\S]*rm\(evidencePath[\s\S]*rm\(temporaryEvidencePath/u,
    );
  });

  test("overwrites inherited staging environment and atomically activates the same bytes", async () => {
    const fixture = await activationFixture();
    let observedPath: string | undefined;

    await fixture.activate({
      environment: {
        SELF_OPENWIKI_STAGED_CAPABILITY_EVIDENCE_PATH:
          "D:\\attacker\\evidence.json",
      },
      runSmoke: async (environment) => {
        observedPath =
          environment.SELF_OPENWIKI_STAGED_CAPABILITY_EVIDENCE_PATH;
        expect(observedPath).toBe(fixture.stagedPath);
        expect(await readFile(observedPath!)).toEqual(fixture.bytes);
      },
    });

    expect(observedPath).toBe(fixture.stagedPath);
    expect(await readFile(fixture.finalPath)).toEqual(fixture.bytes);
    await expect(readFile(fixture.stagedPath)).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  test("rejects a staged path outside the exact repository runtime", async () => {
    const fixture = await activationFixture();

    await expect(
      fixture.activate({ stagedPath: path.join(fixture.root, "wrong.tmp") }),
    ).rejects.toThrow("staged capability evidence");
    await expect(readFile(fixture.finalPath)).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  test("rejects a staged evidence link", async () => {
    const fixture = await activationFixture();
    const target = path.join(fixture.root, "target.json");
    await writeFile(target, fixture.bytes);
    await symlink(target, fixture.stagedPath, "file");

    await expect(fixture.activate()).rejects.toThrow();
    await expect(readFile(fixture.finalPath)).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  test.runIf(process.platform === "win32")(
    "rejects a repository runtime junction before touching its external target",
    async () => {
      const fixture = await activationFixture();
      const externalRoot = await mkdtemp(
        path.join(os.tmpdir(), "c7-activation-external-"),
      );
      tempDirs.push(externalRoot);
      const sentinelPath = path.join(
        externalRoot,
        "verified-capabilities.json",
      );
      const sentinel = Buffer.from("external sentinel\n", "utf8");
      await writeFile(sentinelPath, sentinel);
      await rm(fixture.runtimeDir, { recursive: true });
      await symlink(externalRoot, fixture.runtimeDir, "junction");

      await expect(fixture.activate()).rejects.toThrow(
        "runtime directory is invalid",
      );
      await expect(readFile(sentinelPath)).resolves.toEqual(sentinel);
      await expect(
        readFile(path.join(externalRoot, ".verified-capabilities.tmp")),
      ).rejects.toMatchObject({ code: "ENOENT" });
    },
  );

  test.runIf(process.platform === "win32")(
    "rejects a runtime replaced by a junction during smoke without foreign cleanup",
    async () => {
      const fixture = await activationFixture();
      const externalRoot = await mkdtemp(
        path.join(os.tmpdir(), "c7-activation-external-"),
      );
      tempDirs.push(externalRoot);
      const sentinelPath = path.join(
        externalRoot,
        "verified-capabilities.json",
      );
      const sentinel = Buffer.from("external sentinel\n", "utf8");
      await writeFile(sentinelPath, sentinel);
      const displacedRuntime = path.join(fixture.root, "runtime-displaced");
      const displacedEvidence = path.join(fixture.root, "evidence-displaced");

      await expect(
        fixture.activate({
          runSmoke: async () => {
            await rename(fixture.stagedPath, displacedEvidence);
            await rename(fixture.runtimeDir, displacedRuntime);
            await symlink(externalRoot, fixture.runtimeDir, "junction");
          },
        }),
      ).rejects.toThrow("runtime directory is invalid");
      await expect(readFile(sentinelPath)).resolves.toEqual(sentinel);
      await expect(
        readFile(path.join(externalRoot, ".verified-capabilities.tmp")),
      ).rejects.toMatchObject({ code: "ENOENT" });
      await expect(readFile(displacedEvidence)).resolves.toEqual(fixture.bytes);
    },
  );

  test.each([
    {
      name: "growth",
      mutate: (stagedPath: string) => appendFile(stagedPath, "x"),
    },
    {
      name: "truncation",
      mutate: (stagedPath: string) => truncate(stagedPath, 1),
    },
    {
      name: "same-size hash drift",
      mutate: (stagedPath: string) =>
        writeFile(stagedPath, Buffer.alloc(128, 0x62)),
    },
    {
      name: "replacement",
      mutate: async (stagedPath: string, root: string) => {
        await rename(stagedPath, path.join(root, "displaced.json"));
        await writeFile(stagedPath, Buffer.alloc(128, 0x61));
      },
    },
  ])("rejects $name between smoke and activation", async ({ mutate }) => {
    const fixture = await activationFixture();

    await expect(
      fixture.activate({
        runSmoke: async () => mutate(fixture.stagedPath, fixture.root),
      }),
    ).rejects.toThrow("staged capability evidence");
    await expect(readFile(fixture.finalPath)).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  test("leaves no final evidence when smoke fails", async () => {
    const fixture = await activationFixture();

    await expect(
      fixture.activate({
        runSmoke: async () => {
          throw new Error("smoke failed");
        },
      }),
    ).rejects.toThrow("smoke failed");
    await expect(readFile(fixture.finalPath)).rejects.toMatchObject({
      code: "ENOENT",
    });
  });
});

async function writeEvidence(value: CapabilityFingerprint): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-capability-"));
  tempDirs.push(root);
  const evidencePath = path.join(root, "evidence.json");
  await writeFile(
    evidencePath,
    `${JSON.stringify({
      arch: process.arch,
      buildId: "00000000-0000-4000-8000-000000000000",
      fingerprint: value,
      generatedBy: "scripts/verify-capabilities.mts",
      node: process.version,
      platform: process.platform,
      reports: {
        build: "passed",
        skillEval: "passed",
        tests: "passed",
        win32Integration: "passed",
      },
      tools: TOOL_NAMES,
      verifiedAt: "2026-08-07T00:00:00.000Z",
      verifierVersion: 1,
      version: 1,
    })}\n`,
    "utf8",
  );
  return evidencePath;
}

async function activationFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-activation-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "c7-openwiki", "runtime");
  const repositoryRoot = path.dirname(runtimeDir);
  const stagedPath = path.join(runtimeDir, ".verified-capabilities.tmp");
  const finalPath = path.join(runtimeDir, "verified-capabilities.json");
  const bytes = Buffer.alloc(128, 0x61);
  await mkdir(runtimeDir, { recursive: true });
  const source = await readFile(verifierPath, "utf8");
  if (
    !source.includes(
      "export async function activateVerifiedCapabilityEvidence",
    ) ||
    !source.includes("function isDirectExecution")
  ) {
    throw new Error("verifier activation seam is missing");
  }
  const verifier = (await import(
    /* @vite-ignore */ pathToFileURL(verifierPath).href
  )) as {
    activateVerifiedCapabilityEvidence(options: {
      bytes: Buffer;
      environment?: NodeJS.ProcessEnv;
      finalPath: string;
      repositoryRoot: string;
      runSmoke?: (environment: NodeJS.ProcessEnv) => Promise<void>;
      runtimeDir: string;
      stagedPath: string;
    }): Promise<void>;
  };
  return {
    activate: (
      overrides: Partial<
        Parameters<typeof verifier.activateVerifiedCapabilityEvidence>[0]
      > = {},
    ) =>
      verifier.activateVerifiedCapabilityEvidence({
        bytes,
        finalPath,
        repositoryRoot,
        runtimeDir,
        runSmoke: async () => undefined,
        stagedPath,
        ...overrides,
      }),
    bytes,
    finalPath,
    root,
    runtimeDir,
    stagedPath,
  };
}
