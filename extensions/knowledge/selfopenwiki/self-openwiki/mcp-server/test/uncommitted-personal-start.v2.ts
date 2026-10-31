import { createHash, randomUUID } from "node:crypto";
import {
  cp,
  link,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { OpenWikiExternalUpdateService } from "../src/external-update.js";
import { ExternalUpdateTransactionOwner } from "../src/external-update-transaction.js";
import { C7PersonalGateway } from "../src/official-lifecycle-adapter.js";
import { FilePersonalRunStore } from "../src/personal-run-store.js";
import { PersonalWikiLifecycle } from "../src/personal-wiki-lifecycle.js";
import { snapshotPersonalWiki } from "../src/personal-wiki-snapshot.js";
import { aggregateSkillHash, computeSkillPackageHash } from "../src/skills.js";

const roots: string[] = [];
afterEach(async () => {
  vi.restoreAllMocks();
  for (const root of roots.splice(0)) {
    if (
      path.dirname(root) !== (await realpath(os.tmpdir())) ||
      !path.basename(root).startsWith("personal-uncommitted-")
    )
      throw new Error("Unexpected cleanup target");
    await rm(root, { recursive: true, force: true });
  }
});

describe("uncommitted personal candidate initialization", () => {
  test("recovers an empty Wiki initialization while retaining the empty candidate baseline", async () => {
    const f = await fixture(false, false, false, true);
    await f.makeUncommitted();
    const before = await tree(f.orphanRoot!);
    await expect(f.lifecycle.submitPlan(f.plan)).resolves.toMatchObject({
      status: "plan_accepted",
    });
    const retained = (await readdir(path.join(f.runtimeRoot, "tmp"))).find(
      (name) => name.startsWith("uncommitted-start-"),
    );
    expect(await tree(path.join(f.runtimeRoot, "tmp", retained!))).toEqual(
      before,
    );
    expect(await tree(f.wikiRoot)).toEqual({});
    await expect(
      f.lifecycle.nextPage({ runId: f.runId }),
    ).resolves.toMatchObject({ ok: true });
  });
  test("retains a known initialization and rebuilds a usable PageJob from verified inputs", async () => {
    const f = await fixture();
    await f.makeUncommitted();
    const before = await tree(f.orphanRoot!);
    const formal = await tree(f.wikiRoot);
    const state = await f.store.read(f.runId);
    await expect(f.lifecycle.submitPlan(f.plan)).resolves.toMatchObject({
      ok: true,
      status: "plan_accepted",
    });
    const resumed = await f.store.read(f.runId);
    expect(resumed.planHash).toBe(state.planHash);
    expect(resumed.queueHash).toBe(state.queueHash);
    expect(resumed.candidate?.transactionId).not.toBe(f.orphanId);
    const job = (await f.lifecycle.nextPage({ runId: f.runId })) as {
      ok: boolean;
      candidate: { rootPath: string };
    };
    expect(job.ok).toBe(true);
    expect(
      await readFile(path.join(job.candidate.rootPath, "index.md"), "utf8"),
    ).toBe("# Initial\n");
    const retained = await readdir(path.join(f.runtimeRoot, "tmp"));
    const quarantines = retained.filter((name) =>
      name.startsWith("uncommitted-start-"),
    );
    expect(quarantines).toHaveLength(1);
    expect(
      await tree(path.join(f.runtimeRoot, "tmp", quarantines[0]!)),
    ).toEqual(before);
    expect(await tree(f.wikiRoot)).toEqual(formal);
  });

  test.each([
    [
      "edited candidate",
      "generations/1/candidate/index.md",
      "# Authored content\n",
    ],
    ["hidden control file", "generations/1/candidate/.gitignore", "private\n"],
    ["claims directory", "generations/1/candidate/.claims/index.json", "{}\n"],
    ["unexpected immutable file", "immutable/unowned.txt", "unknown\n"],
    [
      "modified skill",
      "immutable/skills/000-kg-c7-project-wiki/SKILL.md",
      "# Changed\n",
    ],
    ["changed request", "immutable/request.json", "{}\n"],
    ["changed hard rules", "immutable/hard-rules.md", "unknown\n"],
    [
      "changed result contract",
      "immutable/candidate-result-contract.json",
      "{}\n",
    ],
  ])(
    "rejects %s without clearing the accepted plan or changing either tree",
    async (_name, relative, content) => {
      const f = await fixture();
      await f.makeUncommitted();
      const target = path.join(f.orphanRoot!, relative);
      await mkdir(path.dirname(target), { recursive: true });
      await writeFile(target, content);
      const before = await tree(f.orphanRoot!);
      const formal = await tree(f.wikiRoot);
      const state = await f.store.read(f.runId);
      await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
        code: "restore_required",
      });
      expect(await f.store.read(f.runId)).toEqual(state);
      expect(await tree(f.orphanRoot!)).toEqual(before);
      expect(await tree(f.wikiRoot)).toEqual(formal);
    },
  );

  test("does not recover an orphan during first plan acceptance", async () => {
    const f = await fixture();
    await f.makeUncommitted();
    const accepted = await f.store.read(f.runId);
    await f.store.rollbackPlan(f.runId, accepted.planHash!);
    const state = await f.store.read(f.runId);
    const orphan = await tree(f.orphanRoot!);
    const formal = await tree(f.wikiRoot);
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
      code: "restore_required",
    });
    expect(await f.store.read(f.runId)).toEqual(state);
    expect(await tree(f.orphanRoot!)).toEqual(orphan);
    expect(await tree(f.wikiRoot)).toEqual(formal);
  });

  test("refuses a terminal for the same request under a different transaction", async () => {
    const f = await fixture();
    await f.makeUncommitted(true);
    const state = await f.store.read(f.runId);
    const orphan = await tree(f.orphanRoot!);
    const formal = await tree(f.wikiRoot);
    const terminals = await readFile(
      path.join(f.runtimeRoot, "external-updates", "terminal-index.json"),
      "utf8",
    );
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
      code: "restore_required",
    });
    expect(await f.store.read(f.runId)).toEqual(state);
    expect(await tree(f.orphanRoot!)).toEqual(orphan);
    expect(await tree(f.wikiRoot)).toEqual(formal);
    expect(
      await readFile(
        path.join(f.runtimeRoot, "external-updates", "terminal-index.json"),
        "utf8",
      ),
    ).toBe(terminals);
  });

  test.each([
    "recovery/run-unknown123/commit.marker",
    "attention/run-unknown123/attention.json",
    "transactions/transaction-unknown123/state.json",
    "personal-finalization.json",
    "personal-finalization.json.tmp-unknown123",
    "personal-claims-finalization.json",
    "personal-claims-finalization.json.tmp-unknown123",
    "tmp/recovery-unknown123/commit.marker",
    "tmp/unknown/review-receipt.json",
    "tmp/unknown/candidate-receipt.json.atomic.tmp",
    "tmp/unknown/terminal-index.json.atomic.tmp",
    "tmp/unknown/review-package.json",
  ])("refuses unrelated recovery evidence at %s", async (relative) => {
    const f = await fixture();
    await f.makeUncommitted();
    const evidence = path.join(f.runtimeRoot, relative);
    await mkdir(path.dirname(evidence), { recursive: true });
    await writeFile(evidence, "{}\n");
    const state = await f.store.read(f.runId);
    const orphan = await tree(f.orphanRoot!);
    const formal = await tree(f.wikiRoot);
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
      code: "restore_required",
    });
    expect(await f.store.read(f.runId)).toEqual(state);
    expect(await tree(f.orphanRoot!)).toEqual(orphan);
    expect(await tree(f.wikiRoot)).toEqual(formal);
    expect(await readFile(evidence, "utf8")).toBe("{}\n");
  });

  test("keeps an already issued binding when only the personal attachment was interrupted", async () => {
    const f = await fixture();
    const active = await f.transactions.readActive();
    expect(active).not.toBeNull();
    await expect(f.lifecycle.submitPlan(f.plan)).resolves.toMatchObject({
      ok: true,
      status: "plan_accepted",
    });
    expect((await f.store.read(f.runId)).candidate?.candidateBindingHash).toBe(
      active!.state.bindingHash,
    );
    await expect(lstat(path.join(f.runtimeRoot, "tmp"))).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  test("does not quarantine an unknown second initialization", async () => {
    const f = await fixture();
    await f.makeUncommitted();
    const unknown = path.join(
      f.runtimeRoot,
      "external-updates",
      "external-unknown123",
    );
    await mkdir(unknown);
    const state = await f.store.read(f.runId);
    const before = await tree(path.join(f.runtimeRoot, "external-updates"));
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
      code: "restore_required",
    });
    expect(await f.store.read(f.runId)).toEqual(state);
    expect(await tree(path.join(f.runtimeRoot, "external-updates"))).toEqual(
      before,
    );
  });

  test("serializes two retries into the same issued candidate", async () => {
    const f = await fixture();
    await f.makeUncommitted();
    const results = await Promise.allSettled([
      f.lifecycle.submitPlan(f.plan),
      f.lifecycle.submitPlan(f.plan),
    ]);
    expect(results.some((result) => result.status === "fulfilled")).toBe(true);
    const state = await f.store.read(f.runId);
    expect(state.candidate).toBeDefined();
    const active = await f.transactions.readActive();
    expect(active?.state.bindingHash).toBe(
      state.candidate!.candidateBindingHash,
    );
    const dirs = (
      await readdir(path.join(f.runtimeRoot, "external-updates"), {
        withFileTypes: true,
      })
    ).filter((item) => item.isDirectory());
    expect(dirs).toHaveLength(1);
  });

  test.each([
    "extra empty directory",
    "missing required package",
    "multiple hard links",
  ])("rejects %s with the queued plan intact", async (kind) => {
    const f = await fixture();
    await f.makeUncommitted();
    if (kind === "extra empty directory")
      await mkdir(path.join(f.orphanRoot!, "immutable", "unexpected"));
    if (kind === "missing required package")
      await rm(path.join(f.orphanRoot!, "immutable", "hard-rules.md"));
    if (kind === "multiple hard links")
      await link(
        path.join(f.orphanRoot!, "generations", "1", "candidate", "index.md"),
        path.join(f.root, "alias.md"),
      );
    const before = await tree(f.orphanRoot!);
    const state = await f.store.read(f.runId);
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
      code: "restore_required",
    });
    expect(await f.store.read(f.runId)).toEqual(state);
    expect(await tree(f.orphanRoot!)).toEqual(before);
  });

  test("retains the isolated bytes after a subsequent start failure and safely retries", async () => {
    const f = await fixture();
    await f.makeUncommitted();
    const before = await tree(f.orphanRoot!);
    const state = await f.store.read(f.runId);
    vi.spyOn(f.external, "begin").mockRejectedValueOnce(
      new Error("New start interrupted"),
    );
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toThrow(
      "New start interrupted",
    );
    expect(await f.store.read(f.runId)).toEqual(state);
    const retained = (await readdir(path.join(f.runtimeRoot, "tmp"))).filter(
      (name) => name.startsWith("uncommitted-start-"),
    );
    expect(retained).toHaveLength(1);
    expect(await tree(path.join(f.runtimeRoot, "tmp", retained[0]!))).toEqual(
      before,
    );
    await expect(f.lifecycle.submitPlan(f.plan)).resolves.toMatchObject({
      status: "plan_accepted",
    });
  });

  test("rechecks the run proof after validation and refuses a changed active owner", async () => {
    const f = await fixture();
    await f.makeUncommitted();
    const original = f.store.verifyUnboundStart.bind(f.store);
    const pointer = path.join(f.runtimeRoot, "active.json");
    let count = 0;
    vi.spyOn(f.store, "verifyUnboundStart").mockImplementation(
      async (...args) => {
        if (++count === 3)
          await writeFile(
            pointer,
            JSON.stringify({
              version: 1,
              runId: "11111111-1111-4111-8111-111111111111",
            }),
          );
        return original(...args);
      },
    );
    const state = await f.store.read(f.runId);
    const before = await tree(f.orphanRoot!);
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
      code: "restore_required",
    });
    expect(await f.store.read(f.runId)).toEqual(state);
    expect(await tree(f.orphanRoot!)).toEqual(before);
    expect(JSON.parse(await readFile(pointer, "utf8")).runId).toBe(
      "11111111-1111-4111-8111-111111111111",
    );
  });

  test("accepts a verified state.json source in the real runtime tmp snapshot layout", async () => {
    const f = await fixture(true, true);
    await f.makeUncommitted();
    await expect(f.lifecycle.submitPlan(f.plan)).resolves.toMatchObject({
      status: "plan_accepted",
    });
    const active = await f.transactions.readActive();
    expect(
      await readFile(
        path.join(active!.state.sourceRoot!, "000000", "state.json"),
        "utf8",
      ),
    ).toBe("Source evidence\n");
  });

  test("recovers with fresh verified snapshot paths and retained source-named control files", async () => {
    const f = await fixture(true, true, true);
    await f.makeUncommitted();
    const before = await tree(f.orphanRoot!);
    vi.spyOn(f.external, "begin").mockRejectedValueOnce(
      new Error("New start interrupted"),
    );
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toThrow(
      "New start interrupted",
    );
    const retained = (await readdir(path.join(f.runtimeRoot, "tmp"))).filter(
      (name) => name.startsWith("uncommitted-start-"),
    );
    expect(retained).toHaveLength(1);
    expect(await tree(path.join(f.runtimeRoot, "tmp", retained[0]!))).toEqual(
      before,
    );
    await expect(f.lifecycle.submitPlan(f.plan)).resolves.toMatchObject({
      status: "plan_accepted",
    });
    const active = await f.transactions.readActive();
    expect(
      await readFile(
        path.join(active!.state.sourceRoot!, "000000/state.json"),
        "utf8",
      ),
    ).toBe("Source evidence\n");
    expect(await tree(path.join(f.runtimeRoot, "tmp", retained[0]!))).toEqual(
      before,
    );
  });

  test.each([false, true])(
    "accepts an intact retained initialization beside a new uncommitted start (empty Wiki: %s)",
    async (emptyWiki) => {
      const f = await fixture(true, true, true, emptyWiki);
      await f.makeUncommitted();
      const copy = path.join(
        f.runtimeRoot,
        "tmp",
        "uncommitted-start-previous",
      );
      await cp(f.orphanRoot!, copy, { recursive: true });
      const before = await tree(copy);
      await expect(f.lifecycle.submitPlan(f.plan)).resolves.toMatchObject({
        status: "plan_accepted",
      });
      expect(await tree(copy)).toEqual(before);
    },
  );

  test.each([
    "snapshot",
    "retained",
    "retained missing package",
    "retained missing candidate",
    "retained extra state",
  ])("preserves and rejects altered %s source copies", async (kind) => {
    const f = await fixture(true, true, true);
    await f.makeUncommitted();
    const temporary = path.join(f.runtimeRoot, "tmp");
    const copy =
      kind === "snapshot"
        ? path.join(temporary, "snapshot-stale")
        : path.join(temporary, "uncommitted-start-stale");
    const sourceRelative =
      kind === "snapshot"
        ? "000000/state.json"
        : "immutable/sources/000000/state.json";
    if (kind !== "snapshot") await cp(f.orphanRoot!, copy, { recursive: true });
    else
      await mkdir(path.dirname(path.join(copy, sourceRelative)), {
        recursive: true,
      });
    if (kind.endsWith("missing package"))
      await rm(path.join(copy, "immutable/request.json"));
    else if (kind.endsWith("missing candidate"))
      await rm(path.join(copy, "generations/1/candidate/index.md"));
    else if (kind.endsWith("extra state"))
      await writeFile(path.join(copy, "state.json"), "{}\n");
    else await writeFile(path.join(copy, sourceRelative), "Changed source\n");
    const before = await tree(copy);
    const state = await f.store.read(f.runId);
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
      code: "restore_required",
    });
    expect(await tree(copy)).toEqual(before);
    expect(await f.store.read(f.runId)).toEqual(state);
  });

  test("validates newly selected source bytes while retaining partial copies", async () => {
    const f = await fixture(true);
    await f.makeUncommitted();
    const source = path.join(
      f.orphanRoot!,
      "immutable",
      "sources",
      "evidence.md",
    );
    await writeFile(source, "Changed copy\n");
    const state = await f.store.read(f.runId);
    const before = await tree(f.orphanRoot!);
    await expect(f.lifecycle.submitPlan(f.plan)).rejects.toMatchObject({
      code: "restore_required",
    });
    expect(await f.store.read(f.runId)).toEqual(state);
    expect(await tree(f.orphanRoot!)).toEqual(before);
  });

  test("rebuilds a source-bound initialization without trusting the partial source tree", async () => {
    const f = await fixture(true);
    await f.makeUncommitted();
    await rm(path.join(f.orphanRoot!, "immutable", "sources", "evidence.md"));
    await expect(f.lifecycle.submitPlan(f.plan)).resolves.toMatchObject({
      status: "plan_accepted",
    });
    const active = await f.transactions.readActive();
    expect(
      await readFile(
        path.join(active!.state.sourceRoot!, "evidence.md"),
        "utf8",
      ),
    ).toBe("Source evidence\n");
  });
});

async function fixture(
  withSources = false,
  runtimeControlSource = false,
  freshSourceSnapshots = false,
  emptyWiki = false,
) {
  const root = await realpath(
    await mkdtemp(path.join(os.tmpdir(), "personal-uncommitted-")),
  );
  roots.push(root);
  const wikiRoot = path.join(root, "wiki");
  const runtimeRoot = `${wikiRoot}.selfopenwiki`;
  await mkdir(wikiRoot);
  if (!emptyWiki)
    await writeFile(path.join(wikiRoot, "index.md"), "# Initial\n");
  const policy = path.join(root, "sensitive.json");
  await writeFile(
    policy,
    await readFile(
      new URL("../../config/sensitive-files.json", import.meta.url),
    ),
  );
  const files = ["SKILL.md", "references/context.md"].map((relativePath) => {
    const bytes = Buffer.from("# Trusted base\n");
    return {
      relativePath,
      bytes,
      size: bytes.length,
      hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
    };
  });
  const skill = {
    id: "kg-c7-project-wiki",
    category: "base" as const,
    loadOrder: "base_always_first" as const,
    description: "Base",
    title: "Base",
    verified: true as const,
    files,
    packageHash: computeSkillPackageHash(files),
  };
  const selected = {
    skills: [skill],
    aggregateHash: aggregateSkillHash([skill]),
  };
  const sourceRoot = runtimeControlSource
    ? path.join(runtimeRoot, "tmp", "snapshot-fixture")
    : path.join(root, "source-snapshot");
  const sourceRelative = runtimeControlSource
    ? "000000/state.json"
    : "evidence.md";
  await mkdir(path.dirname(path.join(sourceRoot, sourceRelative)), {
    recursive: true,
  });
  await writeFile(path.join(sourceRoot, sourceRelative), "Source evidence\n");
  const { hashSourceSnapshotTree } = await import("../src/sources.js");
  const snapshotTreeHash = await hashSourceSnapshotTree(sourceRoot);
  const transactions = new ExternalUpdateTransactionOwner({
    formalWikiPath: wikiRoot,
    runtimeDir: runtimeRoot,
    security: { securePrivatePath: async () => undefined },
  });
  const external = Object.assign(
    new OpenWikiExternalUpdateService({
      sensitivePolicyPath: policy,
      skills: { select: () => selected },
      sources: {
        verify: async () => {
          const snapshotPath = freshSourceSnapshots
            ? path.join(runtimeRoot, "tmp", `snapshot-${randomUUID()}`)
            : sourceRoot;
          if (freshSourceSnapshots)
            await cp(sourceRoot, snapshotPath, { recursive: true });
          return {
            files: [],
            manifestHash: `sha256:${"c".repeat(64)}`,
            snapshotPath,
            snapshotTreeHash,
            cleanup: async () => undefined,
          };
        },
      },
      transactions,
    }),
    {
      recoverStartup: () =>
        transactions.recoverStartup({
          publish: async () => {
            throw new Error("This fixture must never publish");
          },
        }),
    },
  );
  const store = new FilePersonalRunStore({ runtimeRoot });
  const lifecycle = new PersonalWikiLifecycle({
    c7: new C7PersonalGateway({ externalUpdate: external }),
    runStore: store,
    rootResolver: {
      resolve: async () => {
        const snapshot = await snapshotPersonalWiki(wikiRoot);
        return {
          wikiRoot,
          runtimeRoot,
          wikiRevision: snapshot.rootHash,
          markdownWikiRevision: snapshot.markdownRootHash,
        };
      },
    },
    skillAdapter: {
      resolve: async () => ({
        skillAggregateHash: selected.aggregateHash,
        skillIds: [skill.id],
      }),
    },
    upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
  });
  const begun = (await lifecycle.begin({
    wikiRoot,
    mode: emptyWiki ? "init" : "update",
    ...(withSources
      ? {
          sourceManifestId: "source-fixture-123",
          sourceConfirmation: "confirmed fixture",
        }
      : {}),
  })) as { runId: string };
  const plan = {
    confirmedByUser: true as const,
    runId: begun.runId,
    pages: [
      {
        path: emptyWiki ? "quickstart.md" : "index.md",
        title: "Index",
        purpose: "Improve the existing page",
      },
    ],
  };
  vi.spyOn(store, "attachCandidate").mockRejectedValueOnce(
    new Error(
      "Simulated interruption before the personal candidate attachment",
    ),
  );
  await expect(lifecycle.submitPlan(plan)).rejects.toThrow(
    "Simulated interruption",
  );
  let orphanRoot: string | undefined;
  let orphanId: string | undefined;
  const result = {
    root,
    wikiRoot,
    runtimeRoot,
    store,
    lifecycle,
    transactions,
    external,
    runId: begun.runId,
    plan,
    get orphanRoot() {
      return orphanRoot;
    },
    get orphanId() {
      return orphanId;
    },
    async makeUncommitted(withPriorTerminal = false) {
      // Model the persisted pre-state crash window in a private fixture. No live ledger is edited.
      const active = await transactions.readActive();
      if (!active) throw new Error("Expected fixture initialization");
      orphanRoot = active.state.transactionRoot;
      orphanId = active.state.transactionId;
      if (withPriorTerminal) {
        const savedRoot = path.join(root, "saved-initialization");
        await cp(orphanRoot, savedRoot, { recursive: true });
        await transactions.completeTerminal({
          transactionId: active.state.transactionId,
          bindingHash: active.state.bindingHash,
          terminalPayload: {
            ok: true,
            status: "external_update_aborted",
            executionMode: "external_agent",
            authRequired: false,
            published: false,
            recovery: { action: "none" },
            transactionId: active.state.transactionId,
            bindingHash: active.state.bindingHash,
            generation: active.state.generation,
          },
        });
        orphanId = "external-other-uncommitted123";
        orphanRoot = path.join(runtimeRoot, "external-updates", orphanId);
        await cp(savedRoot, orphanRoot, { recursive: true });
      } else {
        await rm(path.join(runtimeRoot, "external-updates", "active.json"));
      }
      await rm(path.join(orphanRoot, "state.json"));
      await rm(
        path.join(
          orphanRoot,
          "immutable",
          "skills",
          "000-kg-c7-project-wiki",
          "references",
          "context.md",
        ),
      );
    },
  };
  return result;
}

async function tree(root: string): Promise<Record<string, string>> {
  const values: Record<string, string> = {};
  const walk = async (directory: string, prefix: string) => {
    for (const item of await readdir(directory, { withFileTypes: true })) {
      const relative = prefix + item.name;
      const full = path.join(directory, item.name);
      if (item.isDirectory()) {
        values[relative + "/"] = "directory";
        await walk(full, relative + "/");
      } else
        values[relative] = createHash("sha256")
          .update(await readFile(full))
          .digest("hex");
    }
  };
  await walk(root, "");
  return values;
}
