import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test } from "vitest";
import {
  FilePersonalRunStore,
  type PersonalRunState,
} from "../src/personal-run-store.js";
import {
  ExternalUpdateTerminalStore,
  computeExternalTerminalResultHash,
} from "../src/external-update-state.js";
import { ExternalUpdateTransactionOwner } from "../src/external-update-transaction.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("durable personal Wiki run store", () => {
  test("refreshes trusted rule identities before a plan or candidate exists", async () => {
    const root = await mkdtemp(
      path.join(os.tmpdir(), "personal-planning-refresh-"),
    );
    const runtimeRoot = `${root}.selfopenwiki`;
    tempDirs.push(root, runtimeRoot);
    const input = {
      mode: "update" as const,
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      compatibilityManifestHash: hash("c"),
      wikiRevision: hash("a"),
      wikiRoot: root,
      runtimeRoot,
    };
    const store = new FilePersonalRunStore({ runtimeRoot });
    const begun = await store.begin(input);
    if (begun.status !== "planning") throw new Error("expected a new run");
    const refreshed = {
      ...input,
      skillAggregateHash: hash("d"),
      compatibilityManifestHash: hash("e"),
    };
    const rehydrated = new FilePersonalRunStore({ runtimeRoot });
    await expect(rehydrated.begin(refreshed)).resolves.toEqual({
      runId: begun.runId,
      status: "resuming",
    });
    await expect(rehydrated.read(begun.runId)).resolves.toMatchObject({
      ...refreshed,
      phase: "planning",
      planHash: null,
      queueHash: null,
      jobs: [],
    });
    expect((await rehydrated.read(begun.runId)).candidate).toBeUndefined();
  });

  test.each([
    "source",
    "confirmation",
    "wiki",
    "markdown",
    "skill-ids",
    "requested-skills",
    "language",
    "mode",
    "plan",
    "candidate",
  ])("does not refresh changed scope or frozen work: %s", async (scenario) => {
    const root = await mkdtemp(
      path.join(os.tmpdir(), "personal-refresh-reject-"),
    );
    const runtimeRoot = `${root}.selfopenwiki`;
    tempDirs.push(root, runtimeRoot);
    const input = {
      mode: "update" as const,
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      sourceManifestId: "source-12345678",
      sourceConfirmation: "confirm-source:original",
      wikiRoot: root,
      runtimeRoot,
    };
    const store = new FilePersonalRunStore({ runtimeRoot });
    const begun = await store.begin(input);
    if (begun.status !== "planning") throw new Error("expected a new run");
    if (scenario === "plan") {
      await store.submitPlan({
        runId: begun.runId,
        pages: [
          { path: "guide.md", title: "Guide", purpose: "Explain the guide." },
        ],
      });
    } else if (scenario === "candidate") {
      await store.attachCandidate(begun.runId, {
        transactionId: "external-12345678",
        generation: 1,
        candidateBindingHash: hash("c"),
        candidateRoot: path.join(runtimeRoot, "candidate"),
        candidateRootHash: hash("d"),
        wikiRevision: hash("a"),
      });
    }
    const before = await store.read(begun.runId);
    const changed = {
      ...input,
      skillAggregateHash: hash("e"),
      ...(scenario === "source"
        ? {
            sourceManifestId: "source-87654321",
            sourceConfirmation: "confirm-source:other",
          }
        : {}),
      ...(scenario === "confirmation"
        ? { sourceConfirmation: "confirm-source:other" }
        : {}),
      ...(scenario === "wiki" ? { wikiRevision: hash("f") } : {}),
      ...(scenario === "markdown" ? { markdownWikiRevision: hash("f") } : {}),
      ...(scenario === "skill-ids" ? { skillIds: ["another-skill"] } : {}),
      ...(scenario === "requested-skills"
        ? { requestedSkills: ["another-skill"] }
        : {}),
      ...(scenario === "language" ? { language: "en" } : {}),
      ...(scenario === "mode" ? { mode: "init" as const } : {}),
    };
    await expect(
      new FilePersonalRunStore({ runtimeRoot }).begin(changed),
    ).rejects.toMatchObject({ code: "invalid_state" });
    await expect(store.read(begun.runId)).resolves.toEqual(before);
  });

  test.each(["matching", "wrong-binding", "wrong-generation"])(
    "uses only a matching durable abort after rehydration: %s",
    async (scenario) => {
      const root = await mkdtemp(path.join(os.tmpdir(), "personal-abort-"));
      const runtimeRoot = `${root}.selfopenwiki`;
      tempDirs.push(root, runtimeRoot);
      const input = {
        mode: "update" as const,
        force: true,
        requestedSkills: [],
        skillIds: ["self-openwiki"],
        skillAggregateHash: hash("b"),
        wikiRevision: hash("a"),
        wikiRoot: root,
        runtimeRoot,
      };
      const terminal = new ExternalUpdateTerminalStore({
        rootPath: path.join(runtimeRoot, "external-updates"),
        security: { securePrivatePath: async () => {} },
      });
      const owner = new ExternalUpdateTransactionOwner({
        formalWikiPath: root,
        runtimeDir: runtimeRoot,
        security: { securePrivatePath: async () => {} },
      });
      const isRunAborted = (run: PersonalRunState) =>
        owner.isRequestAborted(
          run.runId,
          run.candidate === undefined
            ? undefined
            : {
                transactionId: run.candidate.transactionId,
                bindingHash: run.candidate.candidateBindingHash,
                generation: run.candidate.generation,
              },
        );
      const store = new FilePersonalRunStore({
        runtimeRoot,
        isRunAborted,
      });
      const begun = await store.begin(input);
      if (begun.status !== "planning") throw new Error("expected a new run");
      const candidate = {
        transactionId: "external-12345678",
        generation: 1 as const,
        candidateBindingHash: hash("c"),
        candidateRoot: path.join(runtimeRoot, "candidate"),
        candidateRootHash: hash("d"),
        wikiRevision: hash("a"),
      };
      await store.attachCandidate(begun.runId, candidate);
      const payload = {
        authRequired: false as const,
        executionMode: "external_agent" as const,
        ok: true as const,
        status: "external_update_aborted" as const,
        published: false as const,
        recovery: { action: "none" as const },
        transactionId: candidate.transactionId,
        generation: scenario === "wrong-generation" ? 2 : 1,
        bindingHash:
          scenario === "wrong-binding"
            ? hash("x")
            : candidate.candidateBindingHash,
      };
      await terminal.append({
        version: 1,
        transactionId: candidate.transactionId,
        generation: payload.generation,
        requestIdHash: `sha256:${createHash("sha256")
          .update("kg-c7:external-request-id:v1\0")
          .update(
            JSON.stringify(
              scenario === "wrong-generation" ? "another-request" : begun.runId,
            ),
          )
          .digest("hex")}`,
        inputHash: hash("f"),
        bindingHash: payload.bindingHash,
        resultHash: computeExternalTerminalResultHash(payload),
        status: payload.status,
        finalWikiRevision: hash("a"),
        completedAt: "2026-10-14T06:00:00.000Z",
        payload,
      });
      const next = await new FilePersonalRunStore({
        runtimeRoot,
        isRunAborted,
      }).begin(input);
      if (scenario === "matching") {
        expect(next.status).toBe("planning");
        expect("runId" in next && next.runId).not.toBe(begun.runId);
      } else {
        expect(next).toEqual({ runId: begun.runId, status: "resuming" });
      }
      expect((await store.read(begun.runId)).candidate).toEqual(candidate);
    },
  );

  test("persists a run and resumes the same binding after rehydration", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-run-"));
    tempDirs.push(root);
    const runtimeRoot = `${root}.selfopenwiki`;
    const runId = "11111111-1111-4111-8111-111111111111";
    const input = {
      mode: "update" as const,
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot: root,
      runtimeRoot,
    };
    const store = new FilePersonalRunStore({
      createRunId: () => runId,
      now: () => new Date("2026-09-10T10:00:00.000Z"),
      runtimeRoot,
    });

    await expect(store.begin(input)).resolves.toEqual({
      runId,
      status: "planning",
    });
    const rehydrated = new FilePersonalRunStore({ runtimeRoot });
    await expect(rehydrated.begin(input)).resolves.toEqual({
      runId,
      status: "resuming",
    });
    await expect(rehydrated.read(runId)).resolves.toMatchObject({
      mode: "update",
      phase: "planning",
      runId,
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot: root,
    });
  });

  test("creates an ordered PageJob queue and resumes an assigned job idempotently", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-plan-"));
    tempDirs.push(root);
    const runtimeRoot = `${root}.selfopenwiki`;
    const runId = "22222222-2222-4222-8222-222222222222";
    const store = new FilePersonalRunStore({
      createRunId: () => runId,
      runtimeRoot,
    });
    await store.begin({
      mode: "update",
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot: root,
      runtimeRoot,
    });

    const plan = {
      pages: [
        {
          path: "guide.md",
          purpose: "Explain the guide.",
          title: "Guide",
        },
        {
          path: "index.md",
          purpose: "Link the Wiki.",
          title: "Index",
        },
      ],
      runId,
    };
    await expect(store.submitPlan(plan)).resolves.toMatchObject({
      pageCount: 2,
      planHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
      queueHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
    });
    const first = await store.nextPage(runId);
    if (first === null) throw new Error("expected a first PageJob");
    expect(first).toMatchObject({
      jobId: expect.any(String),
      path: "guide.md",
    });
    await expect(store.nextPage(runId)).resolves.toEqual(first);
    await expect(store.inspectClaims(runId, first.jobId)).resolves.toEqual({
      claims: [],
      jobId: first.jobId,
    });
    await expect(store.readJob(runId, first.jobId)).resolves.toEqual(first);
    await expect(
      store.acceptPage({
        claimDecisionHash: hash("f"),
        jobId: first.jobId,
        pageContentHash: hash("g"),
        runId,
      }),
    ).resolves.toEqual({ remainingPages: 1 });
    await expect(store.nextPage(runId)).resolves.toMatchObject({
      path: "index.md",
      status: "assigned",
    });
    await expect(store.read(runId)).resolves.toMatchObject({
      phase: "writing",
    });
  });

  test("persists planned issue Claims and rejects Windows path collisions", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-claims-"));
    tempDirs.push(root);
    const runtimeRoot = `${root}.selfopenwiki`;
    const runId = "33333333-3333-4333-8333-333333333333";
    const store = new FilePersonalRunStore({
      createRunId: () => runId,
      runtimeRoot,
    });
    await store.begin({
      mode: "update",
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot: root,
      runtimeRoot,
    });

    const claim = {
      evidence: [{ resource: "wiki://source.md" }],
      id: "claim-12345678",
      statement: "The guide exists.",
    };
    await expect(
      store.submitPlan({
        pages: [
          {
            issueClaims: [claim],
            path: "Guide.md",
            purpose: "Guide.",
            title: "Guide",
          },
        ],
        runId,
      }),
    ).resolves.toMatchObject({ pageCount: 1 });
    const job = await store.nextPage(runId);
    expect(job?.issueClaims).toEqual([claim]);

    const cases = [
      ["GUIDE.md", "case collision"],
      ["CON.md", "reserved device"],
      ["docs/guide.md:stream", "ADS"],
      ["docs/guide\u0001.md", "control"],
    ] as const;
    for (const [pagePath, label] of cases) {
      const isolatedRoot = await mkdtemp(
        path.join(os.tmpdir(), "personal-path-"),
      );
      tempDirs.push(isolatedRoot);
      const isolatedRuntimeRoot = `${isolatedRoot}.selfopenwiki`;
      const isolatedRunId = "44444444-4444-4444-8444-444444444444";
      const isolatedStore = new FilePersonalRunStore({
        createRunId: () => isolatedRunId,
        runtimeRoot: isolatedRuntimeRoot,
      });
      await isolatedStore.begin({
        mode: "update",
        requestedSkills: [],
        skillIds: ["self-openwiki"],
        skillAggregateHash: hash("b"),
        wikiRevision: hash("a"),
        wikiRoot: isolatedRoot,
        runtimeRoot: isolatedRuntimeRoot,
      });
      await expect(
        isolatedStore.submitPlan({
          pages:
            label === "case collision"
              ? [
                  { path: "guide.md", purpose: "Guide.", title: "Guide" },
                  { path: pagePath, purpose: "Guide.", title: "Guide" },
                ]
              : [{ path: pagePath, purpose: "Guide.", title: "Guide" }],
          runId: isolatedRunId,
        }),
        label,
      ).rejects.toMatchObject({ code: "invalid_state" });
    }
  });

  test("rolls a planning record back when candidate creation fails", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-rollback-"));
    tempDirs.push(root);
    const runtimeRoot = `${root}.selfopenwiki`;
    const runId = "55555555-5555-4555-8555-555555555555";
    const store = new FilePersonalRunStore({
      createRunId: () => runId,
      runtimeRoot,
    });
    await store.begin({
      mode: "update",
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot: root,
      runtimeRoot,
    });
    const plan = await store.submitPlan({
      pages: [{ path: "index.md", purpose: "Index.", title: "Index" }],
      runId,
    });
    await store.rollbackPlan(runId, plan.planHash);
    await expect(store.read(runId)).resolves.toMatchObject({
      jobs: [],
      phase: "planning",
      planHash: null,
      queueHash: null,
    });
  });

  test("returns a proven update noop after the same run is completed", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-noop-"));
    tempDirs.push(root);
    const runtimeRoot = `${root}.selfopenwiki`;
    const runId = "66666666-6666-4666-8666-666666666666";
    const input = {
      mode: "update" as const,
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot: root,
      runtimeRoot,
    };
    const store = new FilePersonalRunStore({
      createRunId: () => runId,
      runtimeRoot,
    });
    await store.begin(input);
    const plan = await store.submitPlan({
      pages: [{ path: "index.md", purpose: "Index.", title: "Index" }],
      runId,
    });
    const job = await store.nextPage(runId);
    if (job === null) throw new Error("expected a PageJob");
    await store.acceptPage({
      claimDecisionHash: hash("c"),
      jobId: job.jobId,
      pageContentHash: hash("d"),
      runId,
    });
    await store.setPhase(runId, "complete");
    const rehydrated = new FilePersonalRunStore({ runtimeRoot });
    await expect(rehydrated.begin(input)).resolves.toEqual({ status: "noop" });
    expect(plan.pageCount).toBe(1);
  });

  test("replays a completed active run after terminal cleanup is interrupted", async () => {
    const root = await mkdtemp(
      path.join(os.tmpdir(), "personal-terminal-replay-"),
    );
    tempDirs.push(root);
    const runtimeRoot = `${root}.selfopenwiki`;
    const runId = "12121212-1212-4121-8121-121212121212";
    const input = {
      mode: "update" as const,
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot: root,
      runtimeRoot,
    };
    const store = new FilePersonalRunStore({
      createRunId: () => runId,
      runtimeRoot,
    });
    await store.begin(input);
    await store.submitPlan({
      pages: [{ path: "index.md", purpose: "Index.", title: "Index" }],
      runId,
    });
    const job = await store.nextPage(runId);
    if (job === null) throw new Error("expected PageJob");
    await store.acceptPage({
      claimDecisionHash: hash("c"),
      jobId: job.jobId,
      pageContentHash: hash("d"),
      runId,
    });
    await store.setPhase(runId, "complete");
    const state = await readFile(
      path.join(runtimeRoot, "runs", runId, "state.json"),
      "utf8",
    );
    await rm(path.join(runtimeRoot, "last-complete.json"));
    await writeFile(
      path.join(runtimeRoot, "active.json"),
      JSON.stringify({ runId, version: 1 }),
      "utf8",
    );
    await expect(
      new FilePersonalRunStore({ runtimeRoot }).begin(input),
    ).resolves.toEqual({ status: "noop" });
    await expect(
      readFile(path.join(runtimeRoot, "last-complete.json"), "utf8"),
    ).resolves.toContain('"phase":"complete"');
    expect(state).toContain('"phase":"complete"');
  });

  test("requeues accepted pages under a new repair generation", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-successor-"));
    tempDirs.push(root);
    const runtimeRoot = `${root}.selfopenwiki`;
    const runId = "77777777-7777-4777-8777-777777777777";
    const store = new FilePersonalRunStore({
      createRunId: () => runId,
      runtimeRoot,
    });
    await store.begin({
      mode: "update",
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot: root,
      runtimeRoot,
    });
    await store.submitPlan({
      pages: [{ path: "index.md", purpose: "Index.", title: "Index" }],
      runId,
    });
    const first = await store.nextPage(runId);
    if (first === null) throw new Error("expected a PageJob");
    await store.acceptPage({
      claimDecisionHash: hash("c"),
      jobId: first.jobId,
      pageContentHash: hash("d"),
      runId,
    });
    const oldCandidate = {
      candidateBindingHash: hash("e"),
      candidateRoot: path.join(runtimeRoot, "generation-1"),
      candidateRootHash: hash("f"),
      generation: 1 as const,
      transactionId: "external-12345678",
      wikiRevision: hash("a"),
    };
    await store.attachCandidate(runId, oldCandidate);
    const nextCandidate = {
      ...oldCandidate,
      candidateBindingHash: hash("a"),
      candidateRoot: path.join(runtimeRoot, "generation-2"),
      candidateRootHash: hash("b"),
      generation: 2 as const,
    };
    await expect(store.beginSuccessor(runId, nextCandidate)).resolves.toEqual({
      queueHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
    });
    const next = await store.nextPage(runId);
    expect(next).toMatchObject({ path: "index.md", status: "assigned" });
    await expect(store.read(runId)).resolves.toMatchObject({
      candidate: nextCandidate,
      generation: 2,
      phase: "writing",
    });
    expect(next?.jobId).toBe(first.jobId);
  });
});

function hash(character: string): string {
  return `sha256:${createHash("sha256").update(character).digest("hex")}`;
}
