import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, expect, test } from "vitest";
import {
  PersonalWikiLifecycle,
  personalHash,
} from "../src/personal-wiki-lifecycle.js";
import { FilePersonalRunStore } from "../src/personal-run-store.js";
import {
  readPersonalCandidateMarker,
  writePersonalCandidateMarker,
} from "../src/personal-candidate-marker.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import { validateWikiCandidate } from "../src/validation.js";

const roots: string[] = [];
afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) => rm(root, { recursive: true, force: true })),
  );
});

async function fixture(related = false) {
  const wikiRoot = await mkdtemp(
    path.join(os.tmpdir(), "knowledge-incremental-"),
  );
  const runtimeRoot = `${wikiRoot}.selfopenwiki`;
  roots.push(wikiRoot, runtimeRoot);
  const pages = ["quickstart.md", "a.md", "b.md"];
  const content = (page: string) =>
    `---\ntype: concept\n---\n# ${page}\nOriginal content.\n`;
  for (const page of pages)
    await writeFile(path.join(wikiRoot, page), content(page));
  const wikiRevision = (await snapshotMarkdownTree(wikiRoot)).rootHash;
  const input = {
    mode: "update" as const,
    requestedSkills: [],
    skillIds: ["self-openwiki"],
    skillAggregateHash: personalHash("rules"),
    wikiRevision,
    wikiRoot,
    runtimeRoot,
  };
  const store = new FilePersonalRunStore({ runtimeRoot });
  const begun = await store.begin(input);
  if (begun.status !== "planning") throw new Error("expected new run");
  const runId = begun.runId;
  await store.submitPlan({
    runId,
    pages: pages.map((page) => ({
      path: page,
      title: page,
      purpose: `Explain ${page}`,
      ...(related && page === "b.md" ? { relatedPages: ["a.md"] } : {}),
      issueClaims:
        page === "quickstart.md"
          ? []
          : [
              {
                id: `claim-${page}`,
                statement: "Existing claim.",
                evidence: [{ resource: `wiki://${page}` }],
              },
            ],
    })),
  });
  const candidateRoot = path.join(runtimeRoot, "generation-1");
  await mkdir(candidateRoot, { recursive: true });
  await cp(wikiRoot, candidateRoot, { recursive: true });
  await store.attachCandidate(runId, {
    candidateRoot,
    candidateRootHash: (await snapshotMarkdownTree(candidateRoot)).rootHash,
    candidateBindingHash: personalHash("generation-1"),
    generation: 1,
    transactionId: "external-incremental-test",
    wikiRevision,
  });
  const lifecycle = () =>
    new PersonalWikiLifecycle({
      rootResolver: {
        resolve: async () => ({ wikiRoot, runtimeRoot, wikiRevision }),
      },
      skillAdapter: {
        resolve: async () => ({
          skillIds: input.skillIds,
          skillAggregateHash: input.skillAggregateHash,
        }),
      },
      runStore: new FilePersonalRunStore({ runtimeRoot }),
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });
  for (const page of pages) {
    const job = await store.nextPage(runId);
    if (job === null || job.path !== page) throw new Error("unexpected job");
    await lifecycle().submitPage({
      runId,
      jobId: job.jobId,
      ...(page === "quickstart.md"
        ? {}
        : { confirmedClaimIds: [`claim-${page}`] }),
    });
  }
  const statePath = path.join(runtimeRoot, "runs", runId, "state.json");
  const mutateState = async (change: (state: any) => void) => {
    const state = JSON.parse(await readFile(statePath, "utf8"));
    change(state);
    await writeFile(statePath, JSON.stringify(state));
  };
  const markerPath = (jobId: string) =>
    path.join(runtimeRoot, "page-markers", runId, `${jobId}.json`);
  const successor = async () => {
    const state = await store.read(runId);
    const generation = (state.generation + 1) as 2 | 3;
    const root = path.join(runtimeRoot, `generation-${generation}`);
    await cp(state.candidate!.candidateRoot, root, { recursive: true });
    return {
      ...state.candidate!,
      candidateRoot: root,
      generation,
      candidateBindingHash: personalHash(`generation-${generation}`),
      candidateRootHash: (await snapshotMarkdownTree(root)).rootHash,
    };
  };
  return {
    store,
    runId,
    input: { mode: "update" as const, wikiRoot },
    lifecycle,
    successor,
    mutateState,
    markerPath,
  };
}

test("repairs only the located page and survives two cold repair generations", async () => {
  const f = await fixture();
  const original = await f.store.read(f.runId);
  for (const page of ["a.md", "b.md"]) {
    const candidate = await f.successor();
    await f.store.beginSuccessor(f.runId, candidate, [page]);
    const state = await f.store.read(f.runId);
    expect(
      state.jobs
        .filter((job) => job.status === "pending")
        .map((job) => job.path),
    ).toEqual([page]);
    expect(state.jobs.map((job) => job.jobId)).toEqual(
      original.jobs.map((job) => job.jobId),
    );
    await expect(f.lifecycle().begin(f.input)).resolves.toMatchObject({
      status: "resuming",
    });
    const job = await f.store.nextPage(f.runId);
    expect(job?.path).toBe(page);
    await writeFile(
      path.join(candidate.candidateRoot, page),
      `---\ntype: concept\n---\n# Fixed ${page}\n`,
    );
    await f
      .lifecycle()
      .submitPage({
        runId: f.runId,
        jobId: job!.jobId,
        confirmedClaimIds: [`claim-${page}`],
      });
    expect(await f.store.nextPage(f.runId)).toBeNull();
    await expect(f.lifecycle().begin(f.input)).resolves.toMatchObject({
      status: "resuming",
    });
  }
});

test("reopens a page with missing durable Claim decisions instead of inheriting an incomplete receipt", async () => {
  const f = await fixture();
  await f.mutateState((state) => {
    delete state.jobs.find((job: any) => job.path === "b.md").claimDecisions;
  });
  await f.store.beginSuccessor(f.runId, await f.successor(), ["a.md"]);
  const state = await f.store.read(f.runId);
  expect(
    state.jobs.filter((job) => job.status === "pending").map((job) => job.path),
  ).toEqual(["a.md", "b.md"]);
});

test("fails closed on altered Claim decisions without switching the durable generation", async () => {
  const f = await fixture();
  await f.mutateState((state) => {
    state.jobs.find((job: any) => job.path === "b.md").claimDecisions = [];
  });
  await expect(
    f.store.beginSuccessor(f.runId, await f.successor(), ["a.md"]),
  ).rejects.toMatchObject({ code: "invalid_state" });
  expect((await f.store.read(f.runId)).generation).toBe(1);
});

test("unknown repair scope reopens all pages without accepting any historical marker", async () => {
  const f = await fixture();
  const original = await f.store.read(f.runId);
  await f.store.beginSuccessor(f.runId, await f.successor());
  expect((await f.store.read(f.runId)).jobs.map((job) => job.jobId)).toEqual(
    original.jobs.map((job) => job.jobId),
  );
  await expect(f.lifecycle().begin(f.input)).resolves.toMatchObject({
    status: "resuming",
  });
  expect(
    (await f.store.read(f.runId)).jobs.every((job) => job.status === "pending"),
  ).toBe(true);
});

test("repair scope includes related pages in either declared direction", async () => {
  const f = await fixture(true);
  await f.store.beginSuccessor(f.runId, await f.successor(), ["a.md"]);
  expect(
    (await f.store.read(f.runId)).jobs
      .filter((job) => job.status === "pending")
      .map((job) => job.path),
  ).toEqual(["a.md", "b.md"]);
});

test("future-generation markers cannot be treated as reusable history", async () => {
  const f = await fixture();
  await f.store.beginSuccessor(f.runId, await f.successor(), ["a.md"]);
  const state = await f.store.read(f.runId);
  const job = state.jobs.find((job) => job.path === "quickstart.md")!;
  const marker = await readPersonalCandidateMarker(f.markerPath(job.jobId));
  if (marker === null) throw new Error("expected marker");
  await writePersonalCandidateMarker(f.markerPath(job.jobId), {
    ...marker,
    generation: 3,
  });
  await expect(f.lifecycle().begin(f.input)).rejects.toMatchObject({
    code: "restore_required",
  });
});

test("changed candidate bytes cannot inherit an unchanged-page receipt", async () => {
  const f = await fixture();
  const candidate = await f.successor();
  await writeFile(
    path.join(candidate.candidateRoot, "b.md"),
    "---\ntype: concept\n---\nChanged outside the repair.\n",
  );
  await expect(
    f.store.beginSuccessor(f.runId, candidate, ["a.md"]),
  ).rejects.toMatchObject({ code: "invalid_state" });
  expect((await f.store.read(f.runId)).generation).toBe(1);
});

test.each(["binding", "page", "claim", "run"])(
  "rejects altered historical marker identity: %s",
  async (field) => {
    const f = await fixture();
    const state = await f.store.read(f.runId);
    const job = state.jobs.find((job) => job.path === "b.md")!;
    const marker = await readPersonalCandidateMarker(f.markerPath(job.jobId));
    if (marker === null) throw new Error("expected marker");
    await writePersonalCandidateMarker(f.markerPath(job.jobId), {
      ...marker,
      ...(field === "binding"
        ? { candidateBindingHash: personalHash("wrong") }
        : {}),
      ...(field === "page" ? { pageContentHash: personalHash("wrong") } : {}),
      ...(field === "claim"
        ? { claimDecisionHash: personalHash("wrong") }
        : {}),
      ...(field === "run"
        ? { runId: "11111111-1111-4111-8111-111111111111" }
        : {}),
    });
    await expect(
      f.store.beginSuccessor(f.runId, await f.successor(), ["a.md"]),
    ).rejects.toMatchObject({ code: "invalid_state" });
    expect((await f.store.read(f.runId)).generation).toBe(1);
  },
);

test("accepted retries remain page-local while final validation still rejects an invalid tree", async () => {
  const f = await fixture();
  const state = await f.store.read(f.runId);
  const job = state.jobs.find((job) => job.path === "a.md")!;
  await writeFile(
    path.join(state.candidate!.candidateRoot, "unassigned.bin"),
    "invalid",
  );
  await expect(
    f
      .lifecycle()
      .submitPage({
        runId: f.runId,
        jobId: job.jobId,
        confirmedClaimIds: ["claim-a.md"],
      }),
  ).resolves.toMatchObject({ status: "page_accepted" });
  const final = await validateWikiCandidate({
    candidateRoot: state.candidate!.candidateRoot,
  });
  expect(final.passed).toBe(false);
});
