import { createHash } from "node:crypto";
import { once } from "node:events";
import { watch } from "node:fs";
import {
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { bootstrapC7Runtime } from "../src/bootstrap.js";
import * as capabilitiesModule from "../src/capabilities.js";
import type { RuntimeCapabilityGate } from "../src/capabilities.js";
import { toolOutputSchemas } from "../src/contracts.js";
import { OpenWikiExternalUpdateService } from "../src/external-update.js";
import { ExternalUpdateTransactionOwner } from "../src/external-update-transaction.js";
import { C7PersonalGateway } from "../src/official-lifecycle-adapter.js";
import { FilePersonalClaimsResolver } from "../src/personal-claims.js";
import { FilePersonalRunStore } from "../src/personal-run-store.js";
import { PersonalWikiLifecycle } from "../src/personal-wiki-lifecycle.js";
import { snapshotPersonalWiki } from "../src/personal-wiki-snapshot.js";
import { WikiPublisher } from "../src/publish.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type SelectedC7Skills,
} from "../src/skills.js";

const roots: string[] = [];
afterEach(async () => {
  vi.restoreAllMocks();
  for (const root of roots.splice(0))
    await rm(root, { recursive: true, force: true });
});

describe("completed personal Wiki runs", () => {
  test("publishes two reviewed runs while a formal directory watcher remains open", async () => {
    const fixture = await createFixture();
    const watched = path.join(fixture.wikiRoot, "rendering");
    const git = path.join(fixture.wikiRoot, ".git");
    await mkdir(watched);
    await mkdir(git);
    await writeFile(path.join(git, "HEAD"), "ref: refs/heads/main\n");
    const directories = [fixture.wikiRoot, watched, git];
    const identities = () =>
      Promise.all(
        directories.map(async (directory) => {
          const identity = await stat(directory, { bigint: true });
          return { dev: identity.dev, ino: identity.ino };
        }),
      );
    const before = await identities();
    const watcher = watch(watched);
    try {
      const first = await completeChange(
        fixture,
        fixture.lifecycle(),
        "First watched revision",
      );
      const second = await completeChange(
        fixture,
        fixture.lifecycle(),
        "Second watched revision",
      );
      expect(first.completed.published).toBe(true);
      expect(second.completed.published).toBe(true);
      expect(second.completed.afterWikiHash).not.toBe(
        first.completed.afterWikiHash,
      );
      expect(await identities()).toEqual(before);
      expect(await readFile(path.join(git, "HEAD"), "utf8")).toBe(
        "ref: refs/heads/main\n",
      );
      expect(await snapshotPersonalWiki(fixture.wikiRoot)).toMatchObject({
        rootHash: second.completed.wikiRevision,
      });
    } finally {
      const closed = once(watcher, "close");
      watcher.close();
      await closed;
    }
  }, 30_000);

  test("replays a completed personal run across restart, another active run and later publication", async () => {
    const fixture = await createFixture();
    const first = await completeChange(
      fixture,
      fixture.lifecycle(),
      "First revision",
    );
    const restarted = fixture.lifecycle();
    await expect(restarted.finish({ runId: first.runId })).resolves.toEqual(
      first.completed,
    );
    await expect(
      restarted.finish({ runId: first.runId, reviewReceipt: first.receipt }),
    ).resolves.toEqual(first.completed);

    const second = await completeChange(
      fixture,
      restarted,
      "Later revision",
      async () => {
        const pointer = path.join(
          fixture.runtimeRoot,
          "external-updates",
          "active.json",
        );
        const before = await readFile(pointer);
        await expect(
          fixture.lifecycle().finish({ runId: first.runId }),
        ).resolves.toEqual(first.completed);
        await expect(
          fixture
            .lifecycle()
            .finish({ runId: first.runId, reviewReceipt: first.receipt }),
        ).resolves.toEqual(first.completed);
        expect(await readFile(pointer)).toEqual(before);
      },
    );
    expect(second.completed.afterWikiHash).not.toBe(
      first.completed.afterWikiHash,
    );
    const after = await snapshotPersonalWiki(fixture.wikiRoot);
    await expect(
      fixture.lifecycle().finish({ runId: first.runId }),
    ).resolves.toEqual(first.completed);
    await expect(
      fixture
        .lifecycle()
        .finish({ runId: first.runId, reviewReceipt: first.receipt }),
    ).resolves.toEqual(first.completed);
    await expect(
      fixture.lifecycle().finish({
        runId: first.runId,
        reviewReceipt: {
          ...first.receipt,
          reviewerExecutionId: "conflicting-reviewer",
        },
      }),
    ).rejects.toMatchObject({ code: "transaction_state_invalid" });
    await expect(
      fixture.lifecycle().finish({
        runId: first.runId,
        reviewReceipt: { ...first.receipt, generation: 2 },
      }),
    ).rejects.toMatchObject({ code: "invalid_state" });
    expect(await snapshotPersonalWiki(fixture.wikiRoot)).toEqual(after);
  });

  test("retries completion after a crash following durable complete without publishing twice", async () => {
    const fixture = await createFixture();
    const store = new FilePersonalRunStore({
      runtimeRoot: fixture.runtimeRoot,
    });
    const setPhase = store.setPhase.bind(store);
    store.setPhase = async (runId, phase) => {
      await setPhase(runId, phase);
      if (phase === "complete")
        throw new Error("process loss after durable complete");
    };
    await expect(
      completeChange(fixture, fixture.lifecycle(store), "Committed revision"),
    ).rejects.toThrow("process loss after durable complete");
    const state = JSON.parse(
      await readFile(
        path.join(fixture.runtimeRoot, "last-complete.json"),
        "utf8",
      ),
    );
    const before = await snapshotPersonalWiki(fixture.wikiRoot);
    const result = toolOutputSchemas.openwiki_finish.parse(
      await fixture.lifecycle().finish({ runId: state.runId }),
    );
    expect(result).toMatchObject({
      status: "complete",
      published: true,
      wikiRevision: before.rootHash,
    });
    expect(await snapshotPersonalWiki(fixture.wikiRoot)).toEqual(before);
    for (const name of [
      "personal-finalization.json",
      "personal-claims-finalization.json",
    ]) {
      await expect(
        readFile(path.join(fixture.runtimeRoot, name), "utf8"),
      ).rejects.toMatchObject({ code: "ENOENT" });
    }
  });

  test("does not invent completion when the authoritative terminal is unavailable", async () => {
    const fixture = await createFixture();
    const first = await completeChange(
      fixture,
      fixture.lifecycle(),
      "Published revision",
    );
    await rm(
      path.join(fixture.runtimeRoot, "external-updates", "terminal-index.json"),
    );
    const before = await snapshotPersonalWiki(fixture.wikiRoot);
    await expect(
      fixture.lifecycle().finish({ runId: first.runId }),
    ).rejects.toMatchObject({ code: "restore_required" });
    expect(await snapshotPersonalWiki(fixture.wikiRoot)).toEqual(before);
  });

  test("preserves another run's pending publication and personal journals during historical replay", async () => {
    const fixture = await createFixture();
    const first = await completeChange(
      fixture,
      fixture.lifecycle(),
      "Published revision",
    );
    await expect(
      completeChange(
        fixture,
        fixture.lifecycle(undefined, (point) => {
          if (point === "after_plan")
            throw new Error("publication interrupted");
        }),
        "Pending revision",
      ),
    ).rejects.toMatchObject({ code: "publish_failed" });
    const files = [
      "active.json",
      "external-updates/active.json",
      "personal-finalization.json",
      "personal-claims-finalization.json",
    ];
    const before = await Promise.all(
      files.map((name) => readFile(path.join(fixture.runtimeRoot, name))),
    );
    await expect(
      fixture.lifecycle().finish({ runId: first.runId }),
    ).resolves.toEqual(first.completed);
    await expect(
      fixture
        .lifecycle()
        .finish({ runId: first.runId, reviewReceipt: first.receipt }),
    ).resolves.toEqual(first.completed);
    expect(
      await Promise.all(
        files.map((name) => readFile(path.join(fixture.runtimeRoot, name))),
      ),
    ).toEqual(before);
  });

  test("cold bootstrap finishes an existing run in the configured Wiki root without begin", async () => {
    const fixture = await createFixture();
    const first = await completeChange(
      fixture,
      fixture.lifecycle(),
      "Published revision",
    );
    const bootstrapped = await bootstrapFixture(fixture);
    await expect(
      bootstrapped.runtime.invoke("openwiki_finish", { runId: first.runId }),
    ).resolves.toEqual(first.completed);
    await expect(
      readFile(path.join(fixture.runtimeRoot, "active.json"), "utf8"),
    ).rejects.toMatchObject({ code: "ENOENT" });
  }, 20_000);

  test.each([false, true])(
    "cold bootstrap hands published Markdown back to pending personal Claims and completion (revision checkpoint failure: %s)",
    async (failAfterRevision) => {
      const fixture = await createFixture();
      await expect(
        completeChange(
          fixture,
          fixture.lifecycle(undefined, (point) => {
            if (point === "after_plan")
              throw new Error("publication interrupted");
          }),
          "Pending revision",
        ),
      ).rejects.toMatchObject({ code: "publish_failed" });
      const { runId } = JSON.parse(
        await readFile(path.join(fixture.runtimeRoot, "active.json"), "utf8"),
      );
      const state = await new FilePersonalRunStore({
        runtimeRoot: fixture.runtimeRoot,
      }).read(runId);
      const receipt = JSON.parse(
        await readFile(
          path.join(
            fixture.runtimeRoot,
            "external-updates",
            state.candidate!.transactionId,
            "generations",
            String(state.candidate!.generation),
            "review-receipt.json",
          ),
          "utf8",
        ),
      );
      let bootstrapped = await bootstrapFixture(fixture);
      const afterMarkdown = await snapshotPersonalWiki(fixture.wikiRoot);
      expect(afterMarkdown.markdownRootHash).toBe(receipt.candidateRootHash);
      const rejected = await bootstrapped.runtime.invoke("openwiki_finish", {
        runId,
        reviewReceipt: {
          ...receipt,
          reviewerExecutionId: "conflicting-reviewer",
        },
      });
      expect(rejected).toMatchObject({ ok: false });
      expect(await snapshotPersonalWiki(fixture.wikiRoot)).toEqual(
        afterMarkdown,
      );
      if (failAfterRevision) {
        const persist = FilePersonalRunStore.prototype.setWikiRevisions;
        const checkpoint = vi
          .spyOn(FilePersonalRunStore.prototype, "setWikiRevisions")
          .mockImplementation(async function (
            this: FilePersonalRunStore,
            checkpointRunId,
            revisions,
          ) {
            await persist.call(this, checkpointRunId, revisions);
            throw new Error("process loss after revision checkpoint");
          });
        await expect(
          bootstrapped.runtime.invoke("openwiki_finish", {
            runId,
            reviewReceipt: receipt,
          }),
        ).resolves.toMatchObject({ ok: false });
        const halfway = await new FilePersonalRunStore({
          runtimeRoot: fixture.runtimeRoot,
        }).read(runId);
        expect(halfway.phase).toBe("review");
        expect(halfway.wikiRevision).toBe(
          (await snapshotPersonalWiki(fixture.wikiRoot)).rootHash,
        );
        checkpoint.mockRestore();
        bootstrapped = await bootstrapFixture(fixture);
      }
      const result = toolOutputSchemas.openwiki_finish.parse(
        await bootstrapped.runtime.invoke("openwiki_finish", {
          runId,
          reviewReceipt: receipt,
        }),
      );
      expect(result).toMatchObject({
        status: "complete",
        published: true,
        afterWikiHash: receipt.candidateRootHash,
      });
      const final = await snapshotPersonalWiki(fixture.wikiRoot);
      expect(result).toMatchObject({ wikiRevision: final.rootHash });
      expect(final.rootHash).not.toBe(afterMarkdown.rootHash);
      expect(
        (
          await new FilePersonalRunStore({
            runtimeRoot: fixture.runtimeRoot,
          }).read(runId)
        ).phase,
      ).toBe("complete");
      await expect(
        bootstrapped.runtime.invoke("openwiki_finish", { runId }),
      ).resolves.toEqual(result);
      for (const name of [
        "active.json",
        "personal-finalization.json",
        "personal-claims-finalization.json",
      ]) {
        await expect(
          readFile(path.join(fixture.runtimeRoot, name), "utf8"),
        ).rejects.toMatchObject({ code: "ENOENT" });
      }
    },
    30_000,
  );
});

async function bootstrapFixture(
  fixture: Awaited<ReturnType<typeof createFixture>>,
) {
  vi.spyOn(capabilitiesModule, "loadRuntimeCapabilityGate").mockResolvedValue({
    isToolVerified: (name: string) =>
      [
        "openwiki_begin",
        "openwiki_submit_plan",
        "openwiki_next_page",
        "openwiki_inspect_page_claims",
        "openwiki_submit_page",
        "openwiki_finish",
        "openwiki_begin_external_update",
        "openwiki_finalize_external_update",
      ].includes(name),
    records: () => [],
    failureReason: null,
  } as unknown as RuntimeCapabilityGate);
  const repositoryRoot = path.resolve(import.meta.dirname, "../..");
  return bootstrapC7Runtime({
    repositoryRoot,
    openWikiRoot: path.resolve(repositoryRoot, "../.work/openwiki"),
    runtimeDir: fixture.runtimeRoot,
    wikiRoot: fixture.wikiRoot,
  });
}

async function createFixture() {
  const root = await realpath(
    await mkdtemp(path.join(os.tmpdir(), "personal-completion-")),
  );
  roots.push(root);
  const wikiRoot = path.join(root, "wiki");
  const runtimeRoot = `${wikiRoot}.selfopenwiki`;
  await mkdir(wikiRoot, { recursive: true });
  await writeFile(path.join(wikiRoot, "index.md"), page("Initial revision"));
  await writeFile(
    path.join(wikiRoot, "quickstart.md"),
    page("Quickstart\n\n[Home](./index.md)."),
  );
  const sensitivePolicyPath = path.join(root, "sensitive-files.json");
  await writeFile(
    sensitivePolicyPath,
    JSON.stringify({
      version: 1,
      contentPatterns: [],
      rejectedBaseNames: [],
      rejectedNamePrefixes: [],
      rejectedPathSegments: [],
      rejectedSuffixes: [],
    }),
  );
  const bytes = Buffer.from("# Base Skill\n");
  const file = {
    bytes,
    hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
    relativePath: "SKILL.md",
    size: bytes.length,
  };
  const skill = {
    category: "base" as const,
    description: "Base Wiki rules",
    files: [file],
    id: "kg-c7-project-wiki",
    loadOrder: "base_always_first" as const,
    packageHash: computeSkillPackageHash([file]),
    title: "Base",
    verified: true as const,
  };
  const selected: SelectedC7Skills = {
    aggregateHash: aggregateSkillHash([skill]),
    skills: [skill],
  };
  const security = { securePrivatePath: async () => undefined };
  return {
    wikiRoot,
    runtimeRoot,
    lifecycle(
      store = new FilePersonalRunStore({ runtimeRoot }),
      fault?: ConstructorParameters<typeof WikiPublisher>[0]["fault"],
    ) {
      const transactions = new ExternalUpdateTransactionOwner({
        formalWikiPath: wikiRoot,
        runtimeDir: runtimeRoot,
        security,
      });
      const externalUpdate = new OpenWikiExternalUpdateService({
        sensitivePolicyPath,
        skills: { select: () => selected },
        sources: {
          verify: async () => {
            throw new Error("No source manifest was selected.");
          },
        },
        transactions,
        publisher: new WikiPublisher({
          formalWikiPath: wikiRoot,
          runtimeDir: runtimeRoot,
          security,
          fault,
        }),
      });
      return new PersonalWikiLifecycle({
        c7: new C7PersonalGateway({ externalUpdate }),
        claimsResolver: new FilePersonalClaimsResolver(),
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
        runStore: store,
        skillAdapter: {
          resolve: async () => ({
            skillAggregateHash: selected.aggregateHash,
            skillIds: [skill.id],
          }),
        },
        upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
      });
    },
  };
}

async function completeChange(
  fixture: Awaited<ReturnType<typeof createFixture>>,
  lifecycle: PersonalWikiLifecycle,
  title: string,
  whileActive?: () => Promise<void>,
) {
  const begun = toolOutputSchemas.openwiki_begin.parse(
    await lifecycle.begin({
      wikiRoot: fixture.wikiRoot,
      mode: "update",
      force: true,
    }),
  );
  if (!begun.ok || !("runId" in begun))
    throw new Error("Expected a new personal run.");
  const runId = begun.runId;
  const plan = toolOutputSchemas.openwiki_submit_plan.parse(
    await lifecycle.submitPlan({
      runId,
      confirmedByUser: true,
      pages: [{ path: "index.md", purpose: "Refresh the home page.", title }],
    }),
  );
  if (!plan.ok) throw new Error("Expected an accepted plan.");
  const job = toolOutputSchemas.openwiki_next_page.parse(
    await lifecycle.nextPage({ runId }),
  );
  if (!job.ok || job.status !== "page_pending")
    throw new Error("Expected a page job.");
  await writeFile(path.join(job.candidate.rootPath, job.path), page(title));
  await lifecycle.submitPage({ runId, jobId: job.jobId, claims: [] });
  const prepared = toolOutputSchemas.openwiki_finish.parse(
    await lifecycle.finish({
      runId,
      candidateReceipt: {
        type: "external_candidate_receipt",
        version: 1,
        transactionId: plan.binding.transactionId,
        generation: plan.binding.generation,
        bindingHash: plan.binding.candidateBindingHash,
        writerExecutionId: `writer-${runId}`,
        classification: "minor",
        issues: [],
        questions: [],
        summary: "The requested page is ready.",
      },
    }),
  );
  if (
    !prepared.ok ||
    prepared.status !== "review_required" ||
    !("reviewPackageHash" in prepared)
  )
    throw new Error("Expected an independent review package.");
  const receipt = {
    type: "external_review_receipt" as const,
    version: 1 as const,
    transactionId: prepared.transactionId,
    generation: prepared.generation,
    bindingHash: plan.binding.candidateBindingHash,
    candidateRootHash: prepared.candidateRootHash,
    candidateReceiptHash: prepared.candidateReceiptHash,
    reviewPackageHash: prepared.reviewPackageHash,
    reviewerExecutionId: `reviewer-${runId}`,
    verdict: "pass" as const,
    issues: [],
  };
  await whileActive?.();
  const completed = toolOutputSchemas.openwiki_finish.parse(
    await lifecycle.finish({ runId, reviewReceipt: receipt }),
  );
  if (!completed.ok || completed.status !== "complete")
    throw new Error("Expected published completion.");
  return { runId, receipt, completed };
}

function page(title: string) {
  return `---\ntype: Guide\n---\n\n# ${title}\n`;
}
