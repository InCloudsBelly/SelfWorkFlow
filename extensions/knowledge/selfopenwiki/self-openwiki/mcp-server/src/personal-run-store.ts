import { randomUUID } from "node:crypto";
import { lstat, mkdir, open, readFile, rename, rm } from "node:fs/promises";
import path from "node:path";
import { withC7Locks } from "./config.js";
import { toolInputSchemas } from "./contracts.js";
import { readPersonalCandidateMarker } from "./personal-candidate-marker.js";
import { snapshotMarkdownTree } from "./snapshot.js";
import type {
  PersonalCandidateBinding,
  PersonalRunBeginInput,
  PersonalRunBeginResult,
  PersonalRunStore,
} from "./personal-wiki-lifecycle.js";
import type { PersonalClaimsSnapshot } from "./personal-claims.js";
import {
  canonicalPersonalJson,
  personalHash,
} from "./personal-wiki-lifecycle.js";

export type PersonalRunPhase =
  | "planning"
  | "queued"
  | "writing"
  | "review"
  | "complete";

export type PersonalPagePlan = {
  readonly path: string;
  readonly purpose: string;
  readonly relatedPages?: readonly string[];
  readonly seedPaths?: readonly string[];
  readonly title: string;
  readonly instructions?: readonly string[];
  readonly issueClaims?: readonly unknown[];
};

export type PersonalPageJob = PersonalPagePlan & {
  readonly claimDecisions?: readonly unknown[];
  readonly claimDecisionHash?: string;
  readonly claimSource?: "authoritative" | "planned" | "none";
  readonly claimsHash?: string;
  readonly issueClaims: readonly unknown[];
  readonly jobId: string;
  readonly pageContentHash?: string;
  readonly status: "accepted" | "assigned" | "pending";
};

export type PersonalRunState = PersonalRunBeginInput & {
  readonly createdAt: string;
  readonly candidate?: PersonalCandidateBinding;
  readonly generation: 1 | 2 | 3;
  readonly mode: "init" | "update";
  readonly deletePages: readonly string[];
  readonly jobs: readonly PersonalPageJob[];
  readonly planHash: string | null;
  readonly phase: PersonalRunPhase;
  readonly queueHash: string | null;
  readonly runId: string;
  readonly version: 1;
};

type ActivePointer = {
  readonly runId: string;
  readonly version: 1;
};

export class PersonalRunStoreError extends Error {
  constructor(
    readonly code: "busy" | "invalid_state",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "PersonalRunStoreError";
  }
}

type RunAbortLookup = (run: PersonalRunState) => Promise<boolean>;

export class FilePersonalRunStore implements PersonalRunStore {
  private readonly createRunId: () => string;
  private readonly now: () => Date;
  private readonly runtimeRoot: string;
  private readonly isRunAborted: RunAbortLookup | undefined;

  constructor(options: {
    runtimeRoot: string;
    createRunId?(): string;
    now?(): Date;
    isRunAborted?: RunAbortLookup;
  }) {
    if (!path.isAbsolute(options.runtimeRoot)) {
      throw new PersonalRunStoreError(
        "invalid_state",
        "The personal run runtime root must be absolute.",
      );
    }
    this.createRunId = options.createRunId ?? randomUUID;
    this.now = options.now ?? (() => new Date());
    this.runtimeRoot = path.resolve(options.runtimeRoot);
    this.isRunAborted = options.isRunAborted;
  }

  async begin(input: PersonalRunBeginInput): Promise<PersonalRunBeginResult> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      assertBeginInput(input, this.runtimeRoot);
      await mkdir(this.runsRoot(), { mode: 0o700, recursive: true });
      const active = await this.readActivePointer();
      if (active !== null) {
        const state = await this.read(active.runId);
        if (state.phase === "complete") {
          await this.writeLastCompleted(state);
          await rm(path.join(this.runtimeRoot, "active.json"), { force: true });
          if (
            input.mode === "update" &&
            input.force !== true &&
            sameBinding(state, input)
          ) {
            return { status: "noop" };
          }
        } else if (await this.isRunAborted?.(state)) {
          // The C7 tombstone survives a crash after abort and preserves the old run evidence.
          await rm(path.join(this.runtimeRoot, "active.json"), { force: true });
        } else if (sameBinding(state, input)) {
          return { runId: state.runId, status: "resuming" };
        } else {
          const refreshed = refreshPlanningRules(state, input);
          if (refreshed !== null) {
            await this.writeState(refreshed);
            return { runId: state.runId, status: "resuming" };
          }
          throw new PersonalRunStoreError(
            "invalid_state",
            "The active personal Wiki run is bound to a different Wiki or Skill revision; its candidate was retained.",
          );
        }
      }

      if (input.mode === "update" && input.force !== true) {
        const completed = await this.readLastCompleted();
        if (completed !== null && sameBinding(completed, input)) {
          return { status: "noop" };
        }
      }

      const runId = this.createRunId();
      if (!isUuid(runId)) {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal run identifier is invalid.",
        );
      }
      const state: PersonalRunState = {
        ...input,
        createdAt: this.now().toISOString(),
        generation: 1,
        phase: "planning",
        deletePages: [],
        jobs: [],
        planHash: null,
        queueHash: null,
        runId,
        version: 1,
      };
      await this.writeState(state);
      await this.writeActivePointer({ runId, version: 1 });
      return { runId, status: "planning" };
    });
  }

  async submitPlan(input: {
    runId: string;
    pages: readonly PersonalPagePlan[];
    deletePages?: readonly string[];
    claimSnapshots?: Readonly<Record<string, PersonalClaimsSnapshot>>;
  }): Promise<{
    readonly pageCount: number;
    readonly planHash: string;
    readonly queueHash: string;
  }> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      const state = await this.read(input.runId);
      const deletePages = [...(input.deletePages ?? [])];
      assertPagePlan(input.pages, deletePages);
      const planHash = personalHash({
        deletePages,
        pages: input.pages,
        runId: input.runId,
      });
      if (state.planHash !== null) {
        if (state.planHash !== planHash) {
          throw new PersonalRunStoreError(
            "invalid_state",
            "The personal Wiki plan cannot be replaced after queue creation.",
          );
        }
        return {
          pageCount: state.jobs.length,
          planHash,
          queueHash: state.queueHash!,
        };
      }
      if (state.phase !== "planning") {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal Wiki run is not accepting a plan.",
        );
      }
      const jobs = input.pages.map((page) => {
        const snapshot = input.claimSnapshots?.[page.path];
        const issueClaims = snapshot?.claims ?? page.issueClaims ?? [];
        return {
          ...page,
          claimSource:
            snapshot?.source === "authoritative"
              ? ("authoritative" as const)
              : issueClaims.length > 0
                ? ("planned" as const)
                : ("none" as const),
          claimsHash: personalHash(issueClaims),
          issueClaims,
          jobId: randomUUID(),
          status: "pending" as const,
        };
      });
      const queueHash = personalHash(
        jobs.map(({ jobId: _jobId, status: _status, ...page }) => page),
      );
      await this.writeState({
        ...state,
        deletePages,
        jobs,
        phase: jobs.length === 0 ? "review" : "queued",
        planHash,
        queueHash,
      });
      return { pageCount: jobs.length, planHash, queueHash };
    });
  }

  async attachCandidate(
    runId: string,
    candidate: PersonalCandidateBinding,
  ): Promise<void> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      const state = await this.read(runId);
      if (state.candidate !== undefined) {
        if (
          canonicalPersonalJson(state.candidate) !==
          canonicalPersonalJson(candidate)
        ) {
          throw new PersonalRunStoreError(
            "invalid_state",
            "The personal Wiki C7 candidate binding cannot be replaced.",
          );
        }
        return;
      }
      await this.writeState({ ...state, candidate });
    });
  }

  async rollbackPlan(runId: string, planHash: string): Promise<void> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      const state = await this.read(runId);
      if (
        state.planHash !== planHash ||
        state.candidate !== undefined ||
        state.jobs.some((job) => job.status !== "pending")
      ) {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal Wiki plan cannot be rolled back after candidate work begins.",
        );
      }
      await this.writeState({
        ...state,
        deletePages: [],
        jobs: [],
        phase: "planning",
        planHash: null,
        queueHash: null,
      });
    });
  }

  async nextPage(runId: string): Promise<PersonalPageJob | null> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      const state = await this.read(runId);
      if (state.planHash === null) {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal Wiki run has no accepted plan.",
        );
      }
      const existing = state.jobs.find((job) => job.status === "assigned");
      if (existing !== undefined) return existing;
      const index = state.jobs.findIndex((job) => job.status === "pending");
      if (index < 0) return null;
      const job = { ...state.jobs[index]!, status: "assigned" as const };
      const jobs = [...state.jobs];
      jobs[index] = job;
      await this.writeState({ ...state, jobs, phase: "writing" });
      return job;
    });
  }

  async inspectClaims(
    runId: string,
    jobId: string,
  ): Promise<{ readonly claims: readonly unknown[]; readonly jobId: string }> {
    const state = await this.read(runId);
    const job = state.jobs.find((candidate) => candidate.jobId === jobId);
    if (job === undefined || job.status === "pending") {
      throw new PersonalRunStoreError(
        "invalid_state",
        "The personal Wiki PageJob is not assigned.",
      );
    }
    return { claims: job.issueClaims, jobId };
  }

  async readJob(runId: string, jobId: string): Promise<PersonalPageJob | null> {
    const state = await this.read(runId);
    return state.jobs.find((job) => job.jobId === jobId) ?? null;
  }

  async acceptPage(input: {
    readonly claimDecisions?: readonly unknown[];
    readonly claimDecisionHash: string;
    readonly jobId: string;
    readonly pageContentHash: string;
    readonly runId: string;
  }): Promise<{ readonly remainingPages: number }> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      const state = await this.read(input.runId);
      const index = state.jobs.findIndex((job) => job.jobId === input.jobId);
      if (index < 0) {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal Wiki PageJob does not exist.",
        );
      }
      const current = state.jobs[index]!;
      if (current.status === "accepted") {
        if (
          current.pageContentHash !== input.pageContentHash ||
          current.claimDecisionHash !== input.claimDecisionHash
        ) {
          throw new PersonalRunStoreError(
            "invalid_state",
            "The accepted personal Wiki PageJob cannot be replaced.",
          );
        }
        return {
          remainingPages: state.jobs.filter((job) => job.status === "pending")
            .length,
        };
      }
      if (current.status !== "assigned") {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal Wiki PageJob is not assigned to the caller.",
        );
      }
      const jobs = [...state.jobs];
      jobs[index] = {
        ...current,
        ...(input.claimDecisions === undefined
          ? {}
          : { claimDecisions: input.claimDecisions }),
        claimDecisionHash: input.claimDecisionHash,
        pageContentHash: input.pageContentHash,
        status: "accepted",
      };
      const remainingPages = jobs.filter(
        (job) => job.status === "pending",
      ).length;
      await this.writeState({
        ...state,
        jobs,
        phase: remainingPages === 0 ? "review" : "writing",
      });
      return { remainingPages };
    });
  }

  async setPhase(runId: string, phase: "review" | "complete"): Promise<void> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      const state = await this.read(runId);
      if (
        phase === "review" &&
        state.jobs.some((job) => job.status !== "accepted")
      ) {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal Wiki run cannot enter review before every PageJob is accepted.",
        );
      }
      if (phase === "complete" && state.phase !== "review") {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal Wiki run cannot complete outside its review phase.",
        );
      }
      await this.writeState({ ...state, phase });
      if (phase === "complete") {
        const completed = { ...state, phase };
        await this.writeLastCompleted(completed);
        await rm(path.join(this.runtimeRoot, "active.json"), { force: true });
      }
    });
  }

  async setWikiRevision(runId: string, wikiRevision: string): Promise<void> {
    return this.setWikiRevisions(runId, {
      markdownWikiRevision: wikiRevision,
      wikiRevision,
    });
  }

  async setWikiRevisions(
    runId: string,
    revisions: { markdownWikiRevision: string; wikiRevision: string },
  ): Promise<void> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      if (
        !/^sha256:[a-f0-9]{64}$/u.test(revisions.markdownWikiRevision) ||
        !/^sha256:[a-f0-9]{64}$/u.test(revisions.wikiRevision)
      ) {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The completed personal Wiki revision is invalid.",
        );
      }
      const state = await this.read(runId);
      await this.writeState({
        ...state,
        markdownWikiRevision: revisions.markdownWikiRevision,
        wikiRevision: revisions.wikiRevision,
      });
    });
  }

  async beginSuccessor(
    runId: string,
    candidate: PersonalCandidateBinding,
    repairPages?: readonly string[],
  ): Promise<{ readonly queueHash: string }> {
    return withPersonalLocks(this.runtimeRoot, async () => {
      const state = await this.read(runId);
      if (
        state.candidate === undefined ||
        state.planHash === null ||
        state.queueHash === null ||
        state.phase !== "review" ||
        state.jobs.some((job) => job.status !== "accepted") ||
        candidate.generation !== state.generation + 1 ||
        candidate.transactionId !== state.candidate?.transactionId ||
        candidate.wikiRevision !== state.candidate?.wikiRevision ||
        candidate.candidateBindingHash ===
          state.candidate?.candidateBindingHash ||
        candidate.candidateRoot === state.candidate?.candidateRoot
      ) {
        throw new PersonalRunStoreError(
          "invalid_state",
          "The personal Wiki repair successor binding is invalid.",
        );
      }
      const reopen = repairPageClosure(state.jobs, repairPages);
      const snapshot =
        reopen.size < state.jobs.length
          ? await snapshotMarkdownTree(candidate.candidateRoot)
          : undefined;
      const hashes = new Map(
        snapshot?.files.map((file) => [file.relativePath, file.hash]),
      );
      const jobs: PersonalPageJob[] = [];
      for (const job of state.jobs) {
        if (
          !reopen.has(job.path) &&
          job.claimDecisions !== undefined &&
          job.pageContentHash !== undefined &&
          job.claimDecisionHash !== undefined
        ) {
          const marker = await readPersonalCandidateMarker(
            path.join(
              state.runtimeRoot,
              "page-markers",
              state.runId,
              `${job.jobId}.json`,
            ),
          );
          if (marker !== null) {
            if (
              marker.state !== "accepted" ||
              marker.runId !== state.runId ||
              marker.jobId !== job.jobId ||
              marker.pagePath !== job.path ||
              marker.pagePathHash !== personalHash(job.path) ||
              marker.transactionId !== state.candidate.transactionId ||
              marker.generation > state.generation ||
              !isWithinPath(state.runtimeRoot, marker.candidateRoot) ||
              (marker.generation === state.generation &&
                (marker.candidateRoot !== state.candidate.candidateRoot ||
                  marker.candidateBindingHash !==
                    state.candidate.candidateBindingHash)) ||
              marker.pageContentHash !== job.pageContentHash ||
              marker.claimDecisionHash !== job.claimDecisionHash ||
              personalStoredClaimDecisionHash(state.runId, job) !==
                job.claimDecisionHash ||
              hashes.get(job.path) !== job.pageContentHash
            ) {
              throw new PersonalRunStoreError(
                "invalid_state",
                "An unchanged repair page failed its durable acceptance checks.",
              );
            }
            jobs.push(job);
            continue;
          }
        }
        const {
          claimDecisionHash: _claimDecisionHash,
          claimDecisions: _claimDecisions,
          pageContentHash: _pageContentHash,
          status: _status,
          ...page
        } = job;
        jobs.push({ ...page, status: "pending" });
      }
      // Stable job IDs keep historical markers attributable after cold restart.
      const queueHash = personalHash(
        jobs.map(({ jobId: _jobId, status: _status, ...page }) => page),
      );
      await this.writeState({
        ...state,
        candidate,
        generation: candidate.generation,
        jobs,
        phase: "queued",
        queueHash,
      });
      return { queueHash };
    });
  }

  async read(runId: string): Promise<PersonalRunState> {
    if (!isUuid(runId)) {
      throw new PersonalRunStoreError(
        "invalid_state",
        "The personal run identifier is invalid.",
      );
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(
        await readFile(path.join(this.runsRoot(), runId, "state.json"), "utf8"),
      );
    } catch (error) {
      throw new PersonalRunStoreError(
        "invalid_state",
        "The personal Wiki run state is missing or unreadable.",
        { cause: error },
      );
    }
    if (!isRunState(parsed, this.runtimeRoot) || parsed.runId !== runId) {
      throw new PersonalRunStoreError(
        "invalid_state",
        "The personal Wiki run state is invalid.",
      );
    }
    await assertStatePathSafety(parsed);
    return parsed;
  }

  // Read-only: the C7 transaction owner holds operation/wiki locks while calling.
  async verifyUnboundStart(
    runId: string,
    expectedStateHash: string,
  ): Promise<boolean> {
    const active = await this.readActivePointer();
    if (active?.runId !== runId) return false;
    const state = await this.read(runId);
    return (
      state.generation === 1 &&
      state.phase === "queued" &&
      state.candidate === undefined &&
      state.planHash !== null &&
      state.queueHash !== null &&
      state.jobs.length > 0 &&
      state.jobs.every((job) => job.status === "pending") &&
      personalHash(state) === expectedStateHash
    );
  }

  private runsRoot(): string {
    return path.join(this.runtimeRoot, "runs");
  }

  private async readActivePointer(): Promise<ActivePointer | null> {
    try {
      const value = JSON.parse(
        await readFile(path.join(this.runtimeRoot, "active.json"), "utf8"),
      ) as unknown;
      if (!isActivePointer(value)) {
        throw new Error("invalid active pointer");
      }
      return value;
    } catch (error) {
      if (isMissing(error)) return null;
      throw new PersonalRunStoreError(
        "invalid_state",
        "The personal Wiki active run pointer is missing or invalid.",
        { cause: error },
      );
    }
  }

  private async readLastCompleted(): Promise<PersonalRunState | null> {
    try {
      const value = JSON.parse(
        await readFile(
          path.join(this.runtimeRoot, "last-complete.json"),
          "utf8",
        ),
      ) as unknown;
      if (!isRunState(value) || value.phase !== "complete") {
        throw new Error("invalid completed personal run");
      }
      return value;
    } catch (error) {
      if (isMissing(error)) return null;
      throw new PersonalRunStoreError(
        "invalid_state",
        "The personal Wiki completed-run marker is invalid.",
        { cause: error },
      );
    }
  }

  private async writeState(state: PersonalRunState): Promise<void> {
    await atomicWrite(
      path.join(this.runsRoot(), state.runId, "state.json"),
      `${canonicalPersonalJson(state)}\n`,
    );
  }

  private async writeActivePointer(pointer: ActivePointer): Promise<void> {
    await atomicWrite(
      path.join(this.runtimeRoot, "active.json"),
      `${canonicalPersonalJson(pointer)}\n`,
    );
  }

  private async writeLastCompleted(state: PersonalRunState): Promise<void> {
    await atomicWrite(
      path.join(this.runtimeRoot, "last-complete.json"),
      `${canonicalPersonalJson({ ...state, phase: "complete" })}\n`,
    );
  }
}

export class PersonalRunStoreRouter implements PersonalRunStore {
  private readonly stores = new Map<string, FilePersonalRunStore>();

  constructor(
    private readonly options: {
      isRunAborted?: RunAbortLookup;
    } = {},
  ) {}

  bindRoot(runtimeRoot: string): void {
    const store = new FilePersonalRunStore({ runtimeRoot, ...this.options });
    const canonicalRoot = path.resolve(runtimeRoot);
    if (!this.stores.has(canonicalRoot)) {
      this.stores.set(canonicalRoot, store);
    }
  }

  async begin(input: PersonalRunBeginInput): Promise<PersonalRunBeginResult> {
    this.bindRoot(input.runtimeRoot);
    return this.stores.get(path.resolve(input.runtimeRoot))!.begin(input);
  }

  async read(runId: string): Promise<PersonalRunState> {
    return this.requireStore(runId).then((store) => store.read(runId));
  }

  async verifyUnboundStart(runId: string, expectedStateHash: string) {
    return (await this.requireStore(runId)).verifyUnboundStart(
      runId,
      expectedStateHash,
    );
  }

  submitPlan(input: {
    readonly runId: string;
    readonly pages: readonly PersonalPagePlan[];
    readonly deletePages?: readonly string[];
    readonly claimSnapshots?: Readonly<Record<string, PersonalClaimsSnapshot>>;
  }): Promise<Awaited<ReturnType<FilePersonalRunStore["submitPlan"]>>> {
    return this.requireStore(input.runId).then((store) =>
      store.submitPlan(input),
    );
  }

  async attachCandidate(runId: string, candidate: PersonalCandidateBinding) {
    return (await this.requireStore(runId)).attachCandidate(runId, candidate);
  }

  async beginSuccessor(runId: string, candidate: PersonalCandidateBinding, repairPages?: readonly string[]) {
    return (await this.requireStore(runId)).beginSuccessor(runId, candidate, repairPages);
  }

  async rollbackPlan(runId: string, planHash: string) {
    return (await this.requireStore(runId)).rollbackPlan(runId, planHash);
  }

  async nextPage(runId: string) {
    return (await this.requireStore(runId)).nextPage(runId);
  }

  async inspectClaims(runId: string, jobId: string) {
    return (await this.requireStore(runId)).inspectClaims(runId, jobId);
  }

  async readJob(runId: string, jobId: string) {
    return (await this.requireStore(runId)).readJob(runId, jobId);
  }

  acceptPage(input: {
    readonly claimDecisions?: readonly unknown[];
    readonly claimDecisionHash: string;
    readonly jobId: string;
    readonly pageContentHash: string;
    readonly runId: string;
  }) {
    return this.requireStore(input.runId).then((store) =>
      store.acceptPage(input),
    );
  }

  async setPhase(runId: string, phase: "review" | "complete") {
    return (await this.requireStore(runId)).setPhase(runId, phase);
  }

  async setWikiRevision(runId: string, wikiRevision: string) {
    return (await this.requireStore(runId)).setWikiRevision(
      runId,
      wikiRevision,
    );
  }

  async setWikiRevisions(
    runId: string,
    revisions: { markdownWikiRevision: string; wikiRevision: string },
  ) {
    return (await this.requireStore(runId)).setWikiRevisions(runId, revisions);
  }

  private async requireStore(runId: string): Promise<FilePersonalRunStore> {
    for (const store of this.stores.values()) {
      try {
        await store.read(runId);
        return store;
      } catch {
        // Try the next explicitly bound Wiki root.
      }
    }
    throw new PersonalRunStoreError(
      "invalid_state",
      "Call personal begin before continuing this run.",
    );
  }
}

function repairPageClosure(
  jobs: readonly PersonalPageJob[],
  pages?: readonly string[],
): Set<string> {
  const all = new Set(jobs.map((job) => job.path));
  if (!pages?.length || pages.some((page) => !all.has(page))) return all;
  const changed = new Set(pages);
  let expanded = true;
  while (expanded) {
    expanded = false;
    for (const job of jobs) {
      for (const related of job.relatedPages ?? []) {
        if (
          !all.has(related) ||
          (!changed.has(job.path) && !changed.has(related))
        )
          continue;
        for (const page of [job.path, related]) {
          if (!changed.has(page)) {
            changed.add(page);
            expanded = true;
          }
        }
      }
    }
  }
  return changed;
}

export function personalStoredClaimDecisionHash(
  runId: string,
  job: PersonalPageJob,
): string | null {
  if (job.claimDecisions === undefined) return null;
  const claims: unknown[] = [];
  const confirmedClaimIds: string[] = [];
  const retractedClaimIds: string[] = [];
  let phase = 0;
  for (const decision of job.claimDecisions) {
    if (
      isRecord(decision) &&
      (decision.action === "confirm" || decision.action === "retract")
    ) {
      if (Object.keys(decision).length !== 2 || typeof decision.id !== "string")
        return null;
      if (decision.action === "confirm") {
        if (phase > 1) return null;
        phase = 1;
        confirmedClaimIds.push(decision.id);
      } else {
        phase = 2;
        retractedClaimIds.push(decision.id);
      }
    } else {
      if (phase !== 0) return null;
      claims.push(decision);
    }
  }
  const payload = { claims, confirmedClaimIds, retractedClaimIds };
  if (
    !toolInputSchemas.openwiki_submit_page.safeParse({
      runId,
      jobId: job.jobId,
      ...payload,
    }).success
  )
    return null;
  return personalHash(payload);
}

function assertBeginInput(
  input: PersonalRunBeginInput,
  runtimeRoot: string,
): void {
  if (
    !path.isAbsolute(input.wikiRoot) ||
    !path.isAbsolute(input.runtimeRoot) ||
    path.resolve(input.runtimeRoot) !== runtimeRoot ||
    `${path.resolve(input.wikiRoot)}.selfopenwiki` !== runtimeRoot
  ) {
    throw new PersonalRunStoreError(
      "invalid_state",
      "The personal run root binding is invalid.",
    );
  }
}

function refreshPlanningRules(
  state: PersonalRunState,
  input: PersonalRunBeginInput,
): PersonalRunState | null {
  if (
    state.phase !== "planning" ||
    state.planHash !== null ||
    state.queueHash !== null ||
    state.jobs.length !== 0 ||
    state.deletePages.length !== 0 ||
    state.candidate !== undefined
  ) {
    return null;
  }
  // Lifecycle supplies these identities from the current trusted registry.
  // No source, Wiki revision, Skill selection or frozen C7 binding can change.
  const refreshed: PersonalRunState = {
    ...state,
    skillAggregateHash: input.skillAggregateHash,
    ...(input.compatibilityManifestHash === undefined
      ? {}
      : { compatibilityManifestHash: input.compatibilityManifestHash }),
  };
  return sameBinding(refreshed, input) ? refreshed : null;
}

function sameBinding(
  state: PersonalRunState,
  input: PersonalRunBeginInput,
): boolean {
  return (
    state.mode === input.mode &&
    state.wikiRoot === input.wikiRoot &&
    state.runtimeRoot === input.runtimeRoot &&
    state.wikiRevision === input.wikiRevision &&
    (state.markdownWikiRevision ?? state.wikiRevision) ===
      (input.markdownWikiRevision ?? input.wikiRevision) &&
    state.language === input.language &&
    state.skillAggregateHash === input.skillAggregateHash &&
    state.compatibilityManifestHash === input.compatibilityManifestHash &&
    canonicalPersonalJson(state.skillIds) ===
      canonicalPersonalJson(input.skillIds) &&
    canonicalPersonalJson(state.requestedSkills) ===
      canonicalPersonalJson(input.requestedSkills) &&
    state.sourceManifestId === input.sourceManifestId &&
    state.sourceConfirmation === input.sourceConfirmation
  );
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(
    value,
  );
}

function withPersonalLocks<T>(
  runtimeRoot: string,
  operation: () => Promise<T>,
): Promise<T> {
  return withC7Locks(runtimeRoot, ["operation", "wiki"], operation);
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isActivePointer(value: unknown): value is ActivePointer {
  return (
    typeof value === "object" &&
    value !== null &&
    "version" in value &&
    value.version === 1 &&
    "runId" in value &&
    typeof value.runId === "string" &&
    isUuid(value.runId)
  );
}

function isRunState(
  value: unknown,
  expectedRuntimeRoot?: string,
): value is PersonalRunState {
  if (!isRecord(value)) return false;
  if (
    !hasOnlyKeys(value, [
      "candidate",
      "compatibilityManifestHash",
      "createdAt",
      "deletePages",
      "force",
      "generation",
      "jobs",
      "language",
      "markdownWikiRevision",
      "mode",
      "phase",
      "planHash",
      "queueHash",
      "requestedSkills",
      "runId",
      "runtimeRoot",
      "skillAggregateHash",
      "skillIds",
      "sourceConfirmation",
      "sourceManifestId",
      "version",
      "wikiRevision",
      "wikiRoot",
    ]) ||
    value.version !== 1 ||
    !isGeneration(value.generation) ||
    typeof value.runId !== "string" ||
    !isUuid(value.runId) ||
    (value.mode !== "init" && value.mode !== "update") ||
    !["planning", "queued", "writing", "review", "complete"].includes(
      value.phase as string,
    ) ||
    !isAbsoluteDirectoryPath(value.wikiRoot) ||
    !isAbsoluteDirectoryPath(value.runtimeRoot) ||
    (expectedRuntimeRoot !== undefined &&
      path.resolve(value.runtimeRoot) !== path.resolve(expectedRuntimeRoot)) ||
    path.resolve(`${value.wikiRoot}.selfopenwiki`) !==
      path.resolve(value.runtimeRoot) ||
    !isHash(value.wikiRevision) ||
    (value.markdownWikiRevision !== undefined &&
      !isHash(value.markdownWikiRevision)) ||
    !isHash(value.skillAggregateHash) ||
    !isSkillIdArray(value.skillIds) ||
    !isSkillIdArray(value.requestedSkills) ||
    !Array.isArray(value.deletePages) ||
    value.deletePages.length > 2_048 ||
    value.deletePages.some(
      (page) => typeof page !== "string" || !isPersonalPagePath(page),
    ) ||
    !Array.isArray(value.jobs) ||
    value.jobs.length > 2_048 ||
    value.jobs.some((job) => !isPersonalPageJob(job)) ||
    (value.planHash !== null && !isHash(value.planHash)) ||
    (value.queueHash !== null && !isHash(value.queueHash)) ||
    typeof value.createdAt !== "string" ||
    Number.isNaN(Date.parse(value.createdAt))
  ) {
    return false;
  }
  if (
    value.compatibilityManifestHash !== undefined &&
    !isHash(value.compatibilityManifestHash)
  ) {
    return false;
  }
  if (
    (value.sourceManifestId !== undefined &&
      !isBoundedId(value.sourceManifestId)) ||
    (value.sourceConfirmation !== undefined &&
      !isBoundedText(value.sourceConfirmation, 512)) ||
    (value.language !== undefined && !isBoundedText(value.language, 32))
  ) {
    return false;
  }
  return (
    value.candidate === undefined ||
    isCandidateBinding(value.candidate, value.runtimeRoot)
  );
}

function isPersonalPageJob(value: unknown): value is PersonalPageJob {
  if (!isRecord(value)) return false;
  return (
    hasOnlyKeys(value, [
      "claimDecisionHash",
      "claimDecisions",
      "claimSource",
      "claimsHash",
      "instructions",
      "issueClaims",
      "jobId",
      "pageContentHash",
      "path",
      "purpose",
      "relatedPages",
      "seedPaths",
      "status",
      "title",
    ]) &&
    isPersonalPagePlan(value) &&
    Array.isArray(value.issueClaims) &&
    value.issueClaims.length <= 256 &&
    value.issueClaims.every(isPersonalClaim) &&
    typeof value.jobId === "string" &&
    isUuid(value.jobId) &&
    ["accepted", "assigned", "pending"].includes(value.status as string) &&
    (value.claimDecisions === undefined ||
      (Array.isArray(value.claimDecisions) &&
        value.claimDecisions.length <= 256 &&
        value.claimDecisions.every(isBoundedJson))) &&
    (value.claimDecisionHash === undefined ||
      isHash(value.claimDecisionHash)) &&
    (value.claimSource === undefined ||
      (typeof value.claimSource === "string" &&
        ["authoritative", "planned", "none"].includes(value.claimSource))) &&
    (value.claimsHash === undefined || isHash(value.claimsHash)) &&
    (value.pageContentHash === undefined || isHash(value.pageContentHash))
  );
}

function isPersonalPagePlan(value: Record<string, unknown>): boolean {
  return (
    typeof value.path === "string" &&
    isPersonalPagePath(value.path) &&
    isBoundedText(value.title, 512) &&
    isBoundedText(value.purpose, 4_096) &&
    (value.relatedPages === undefined ||
      (Array.isArray(value.relatedPages) &&
        value.relatedPages.length <= 64 &&
        value.relatedPages.every(
          (page) => typeof page === "string" && isPersonalPagePath(page),
        ))) &&
    (value.seedPaths === undefined ||
      (Array.isArray(value.seedPaths) &&
        value.seedPaths.length <= 128 &&
        value.seedPaths.every((page) => isBoundedText(page, 1_024)))) &&
    (value.instructions === undefined ||
      (Array.isArray(value.instructions) &&
        value.instructions.length <= 64 &&
        value.instructions.every((instruction) =>
          isBoundedText(instruction, 8_192),
        )))
  );
}

function isPersonalClaim(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    hasOnlyKeys(value, ["evidence", "id", "statement"]) &&
    (value.id === undefined || isBoundedId(value.id)) &&
    isBoundedText(value.statement, 4_096) &&
    Array.isArray(value.evidence) &&
    value.evidence.length >= 1 &&
    value.evidence.length <= 64 &&
    value.evidence.every(
      (entry) =>
        isRecord(entry) &&
        Object.keys(entry).length === 1 &&
        isBoundedText(entry.resource, 1_024) &&
        /^(?:repo|wiki):\/\/[A-Za-z0-9._~:/#?\[\]@!$&'()*+,;=%-]+$/u.test(
          entry.resource,
        ),
    )
  );
}

function isCandidateBinding(
  value: unknown,
  runtimeRoot: string,
): value is PersonalCandidateBinding {
  if (!isRecord(value)) return false;
  const candidateRoot =
    typeof value.candidateRoot === "string"
      ? path.resolve(value.candidateRoot)
      : "";
  return (
    hasOnlyKeys(value, [
      "candidateBindingHash",
      "candidateRoot",
      "candidateRootHash",
      "generation",
      "transactionId",
      "wikiRevision",
    ]) &&
    isHash(value.candidateBindingHash) &&
    isAbsoluteDirectoryPath(value.candidateRoot) &&
    isWithinPath(runtimeRoot, candidateRoot) &&
    candidateRoot !== path.resolve(runtimeRoot) &&
    isHash(value.candidateRootHash) &&
    isGeneration(value.generation) &&
    isBoundedId(value.transactionId) &&
    isHash(value.wikiRevision)
  );
}

function isGeneration(value: unknown): value is 1 | 2 | 3 {
  return value === 1 || value === 2 || value === 3;
}

function isHash(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[a-f0-9]{64}$/u.test(value);
}

function isBoundedId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/u.test(value)
  );
}

function isBoundedText(value: unknown, maxLength: number): value is string {
  return (
    typeof value === "string" &&
    value.trim() === value &&
    value.length > 0 &&
    value.length <= maxLength &&
    !value.includes("\u0000")
  );
}

function isSkillIdArray(value: unknown): value is readonly string[] {
  return (
    Array.isArray(value) &&
    value.length <= 33 &&
    value.every(
      (item) =>
        typeof item === "string" && /^[a-z][a-z0-9-]{0,127}$/u.test(item),
    ) &&
    new Set(value).size === value.length
  );
}

function isBoundedJson(value: unknown, depth = 0): boolean {
  if (depth > 8) return false;
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return typeof value !== "string" || value.length <= 16_384;
  }
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) {
    return (
      value.length <= 256 &&
      value.every((item) => isBoundedJson(item, depth + 1))
    );
  }
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  return (
    keys.length <= 32 &&
    keys.every((key) => key.length <= 128 && !key.includes("\u0000")) &&
    keys.every((key) => isBoundedJson(value[key], depth + 1))
  );
}

function isAbsoluteDirectoryPath(value: unknown): value is string {
  return (
    typeof value === "string" &&
    path.isAbsolute(value) &&
    value === path.resolve(value)
  );
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  const keys = new Set(allowed);
  return Object.keys(value).every((key) => keys.has(key));
}

function isWithinPath(root: string, candidate: string): boolean {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return (
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative))
  );
}

async function assertStatePathSafety(state: PersonalRunState): Promise<void> {
  if (state.candidate === undefined) return;
  const candidateRoot = path.resolve(state.candidate.candidateRoot);
  let current = path.resolve(state.runtimeRoot);
  const segments = path
    .relative(current, candidateRoot)
    .split(path.sep)
    .filter(Boolean);
  for (let index = 0; index < segments.length; index += 1) {
    current = path.join(current, segments[index]!);
    try {
      const stat = await lstat(current);
      if (
        stat.isSymbolicLink() ||
        (index === segments.length - 1 && !stat.isDirectory())
      ) {
        throw new Error("candidate root is not a regular directory");
      }
    } catch (error) {
      if (isMissing(error)) return;
      throw new PersonalRunStoreError(
        "invalid_state",
        "The personal Wiki candidate root is not a safe directory.",
        { cause: error },
      );
    }
  }
}

function assertPagePlan(
  pages: readonly PersonalPagePlan[],
  deletePages: readonly string[],
): void {
  const paths = [...pages.map((page) => page.path), ...deletePages];
  const normalizedPaths = paths.map((value) =>
    value.normalize("NFC").toLocaleLowerCase("en-US"),
  );
  if (
    new Set(normalizedPaths).size !== normalizedPaths.length ||
    pages.some((page) => !isPersonalPagePath(page.path)) ||
    deletePages.some((page) => !isPersonalPagePath(page))
  ) {
    throw new PersonalRunStoreError(
      "invalid_state",
      "The personal Wiki PageJob paths are invalid or overlapping.",
    );
  }
}

function isPersonalPagePath(value: string): boolean {
  const isUnsafeWindowsPathSegment = (segment: string): boolean => {
    if (
      [...segment].some(
        (character) =>
          character.charCodeAt(0) < 0x20 ||
          character.charCodeAt(0) === 0x7f ||
          '<>:"/\\|?*'.includes(character),
      )
    ) {
      return true;
    }
    if (/[. ]$/u.test(segment)) return true;
    const stem = segment.split(".", 1)[0]!.toUpperCase();
    return /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/u.test(stem);
  };
  return (
    value.trim() === value &&
    value.length > 0 &&
    value.toLowerCase().endsWith(".md") &&
    !value.includes("\\") &&
    !value.startsWith("/") &&
    !value
      .split("/")
      .some(
        (segment) =>
          segment === "" ||
          segment === "." ||
          segment === ".." ||
          isUnsafeWindowsPathSegment(segment),
      )
  );
}

async function atomicWrite(filePath: string, content: string): Promise<void> {
  const directory = path.dirname(filePath);
  await mkdir(directory, { mode: 0o700, recursive: true });
  const temporaryPath = path.join(
    directory,
    `.${path.basename(filePath)}.${randomUUID()}.tmp`,
  );
  try {
    const handle = await open(temporaryPath, "wx", 0o600);
    try {
      await handle.writeFile(content, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporaryPath, filePath);
  } catch (error) {
    await rm(temporaryPath, { force: true }).catch(() => undefined);
    throw error;
  }
}
