import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
} from "node:fs/promises";
import path from "node:path";
import { parseDocument } from "yaml";
import { toolInputSchemas } from "./contracts.js";
import type {
  PersonalClaimsResolver,
  PersonalClaimsSnapshot,
} from "./personal-claims.js";
import {
  createPersonalClaimsPayload,
  hashPersonalClaimsBytes,
  inspectPersonalClaimsSidecar,
  isValidPersonalEvidenceResource,
  personalClaimsSidecarPath,
  removePersonalClaims,
  writePersonalClaims,
} from "./personal-claims.js";
import { withC7Locks } from "./config.js";
import {
  transitionPersonalCandidateMarker,
  readPersonalCandidateMarker,
  writePersonalCandidateMarker,
} from "./personal-candidate-marker.js";
import { C7SnapshotError, snapshotMarkdownTree } from "./snapshot.js";
import { snapshotPersonalWiki } from "./personal-wiki-snapshot.js";
import type {
  PersonalPageJob,
  PersonalPagePlan,
} from "./personal-run-store.js";

export type PersonalRootBinding = {
  readonly wikiRoot: string;
  readonly runtimeRoot: string;
  readonly wikiRevision: string;
  readonly markdownWikiRevision?: string;
};

export type PersonalSkillBinding = {
  readonly compatibilityManifestHash?: string;
  readonly skillAggregateHash: string;
  readonly skillIds: readonly string[];
};

export type PersonalRunBeginInput = PersonalRootBinding &
  PersonalSkillBinding & {
    readonly force?: boolean;
    readonly language?: string;
    readonly mode: "init" | "update";
    readonly requestedSkills: readonly string[];
    readonly skillIds: readonly string[];
    readonly sourceConfirmation?: string;
    readonly sourceManifestId?: string;
  };

export type PersonalRunBeginResult =
  | { readonly runId: string; readonly status: "planning" | "resuming" }
  | { readonly status: "noop" };

export type PersonalCandidateBinding = {
  readonly candidateBindingHash: string;
  readonly candidateRoot: string;
  readonly candidateRootHash: string;
  readonly generation: 1 | 2 | 3;
  readonly transactionId: string;
  readonly wikiRevision: string;
};

export type PersonalReviewPreparationResult =
  | {
      readonly kind: "needs_clarification";
      readonly issues: readonly unknown[];
      readonly questions: readonly string[];
    }
  | {
      readonly kind: "review_ready";
      readonly candidateReceiptHash: string;
      readonly candidateRootHash: string;
      readonly reviewPackage: unknown;
      readonly reviewPackageHash: string;
    };

export type PersonalReviewSubmissionResult =
  | {
      readonly kind: "publish_pending";
    }
  | {
      readonly kind: "repair_ready";
      readonly issues: readonly unknown[];
    }
  | {
      readonly kind: "needs_clarification";
      readonly issues: readonly unknown[];
      readonly questions: readonly string[];
    }
  | {
      readonly kind: "complete";
      readonly afterWikiHash: string;
      readonly beforeWikiHash: string;
      readonly followUp?: readonly unknown[];
      readonly reviewReceiptHash: string;
      readonly runReceiptHash: string;
      readonly wikiRevision: string;
    };

export type PersonalRunRecord = {
  readonly runId: string;
  readonly wikiRoot: string;
  readonly runtimeRoot: string;
  readonly wikiRevision: string;
  readonly markdownWikiRevision?: string;
  readonly skillAggregateHash: string;
  readonly compatibilityManifestHash?: string;
  readonly sourceConfirmation?: string;
  readonly sourceManifestId?: string;
  readonly requestedSkills?: readonly string[];
  readonly candidate?: PersonalCandidateBinding;
  readonly deletePages?: readonly string[];
  readonly skillIds?: readonly string[];
  readonly jobs?: readonly PersonalPageJob[];
  readonly planHash?: string | null;
  readonly queueHash?: string | null;
  readonly phase?: string;
};

type PersonalClaimsFinalizationOperation =
  | {
      readonly action: "write";
      readonly afterClaimsHash: string;
      readonly claims: readonly unknown[];
      readonly desiredSidecarHash: string;
      readonly desiredSidecarSize: number;
      readonly expectedSidecarHash: string | null;
      readonly pageHash: string;
      readonly pagePath: string;
    }
  | {
      readonly action: "delete";
      readonly afterClaimsHash: string;
      readonly desiredSidecarHash: null;
      readonly expectedSidecarHash: string | null;
      readonly pagePath: string;
    };

type PersonalClaimsFinalizationJournal = {
  readonly afterWikiHash: string;
  readonly baselineClaimsHash: string;
  readonly bindingHash: string;
  readonly applyingOperation?: number;
  readonly completedOperations: readonly number[];
  readonly currentClaimsHash: string;
  readonly expectedFinalClaimsHash: string;
  readonly generation: 1 | 2 | 3;
  readonly operations: readonly PersonalClaimsFinalizationOperation[];
  readonly reviewReceiptInputHash: string;
  readonly runId: string;
  readonly runtimeRoot: string;
  readonly status: "prepared" | "applying";
  readonly transactionId: string;
  readonly type: "selfopenwiki:personal-claims-finalization-v1";
  readonly version: 1;
};

export type PersonalClaimsFinalizationRecovery = {
  readonly journal: PersonalClaimsFinalizationJournal;
  readonly snapshot: Awaited<ReturnType<typeof snapshotPersonalWiki>>;
};

export interface PersonalRootResolver {
  resolve(wikiRoot: string): Promise<PersonalRootBinding>;
}

export interface PersonalSkillAdapter {
  resolve(requestedSkills: readonly string[]): Promise<PersonalSkillBinding>;
}

export interface PersonalRunStore {
  bindRoot?(runtimeRoot: string): void;
  begin(input: PersonalRunBeginInput): Promise<PersonalRunBeginResult>;
  read?(runId: string): Promise<PersonalRunRecord>;
  submitPlan?(input: {
    readonly runId: string;
    readonly pages: readonly PersonalPagePlan[];
    readonly requestedSkills?: readonly string[];
    readonly deletePages?: readonly string[];
    readonly claimSnapshots?: Readonly<Record<string, PersonalClaimsSnapshot>>;
  }): Promise<{
    readonly pageCount: number;
    readonly planHash: string;
    readonly queueHash: string;
  }>;
  rollbackPlan?(runId: string, planHash: string): Promise<void>;
  beginSuccessor?(
    runId: string,
    candidate: PersonalCandidateBinding,
  ): Promise<{ readonly queueHash: string }>;
  attachCandidate?(
    runId: string,
    candidate: PersonalCandidateBinding,
  ): Promise<void>;
  nextPage?(runId: string): Promise<PersonalPageJob | null>;
  inspectClaims?(
    runId: string,
    jobId: string,
  ): Promise<{ readonly claims: readonly unknown[]; readonly jobId: string }>;
  readJob?(runId: string, jobId: string): Promise<PersonalPageJob | null>;
  acceptPage?(input: {
    readonly claimDecisions?: readonly unknown[];
    readonly claimDecisionHash: string;
    readonly jobId: string;
    readonly pageContentHash: string;
    readonly runId: string;
  }): Promise<{ readonly remainingPages: number }>;
  setPhase?(runId: string, phase: "review" | "complete"): Promise<void>;
  setWikiRevision?(runId: string, wikiRevision: string): Promise<void>;
  setWikiRevisions?(
    runId: string,
    revisions: { markdownWikiRevision: string; wikiRevision: string },
  ): Promise<void>;
}

export interface PersonalC7Gateway {
  readCompletion?(input: {
    readonly candidate: PersonalCandidateBinding;
    readonly expectedAfterWikiHash: string;
    readonly reviewReceipt?: unknown;
    readonly runId: string;
    readonly runtimeRoot: string;
    readonly wikiRoot: string;
  }): Promise<Extract<PersonalReviewSubmissionResult, { kind: "complete" }>>;
  start(input: {
    readonly confirmedByUser: true;
    readonly deletePages?: readonly string[];
    readonly pages: readonly PersonalPagePlan[];
    readonly requestedSkills?: readonly string[];
    readonly runId: string;
    readonly skillAggregateHash: string;
    readonly compatibilityManifestHash?: string;
    readonly sourceConfirmation?: string;
    readonly sourceManifestId?: string;
    readonly markdownWikiRevision?: string;
    readonly wikiRevision: string;
    readonly wikiRoot: string;
  }): Promise<PersonalCandidateBinding>;
  resumeRepair?(input: {
    readonly bindingHash: string;
    readonly runId: string;
    readonly runtimeRoot?: string;
    readonly transactionId: string;
    readonly wikiRoot?: string;
  }): Promise<PersonalCandidateBinding>;
  prepareReview?(input: {
    readonly candidateReceipt: unknown;
    readonly runId: string;
    readonly runtimeRoot?: string;
    readonly wikiRoot?: string;
  }): Promise<PersonalReviewPreparationResult>;
  submitReview?(input: {
    readonly beforeWikiHash?: string;
    readonly reviewReceipt: unknown;
    readonly runId: string;
    readonly runtimeRoot?: string;
    readonly wikiRoot?: string;
  }): Promise<PersonalReviewSubmissionResult>;
}

export class PersonalWikiLifecycle {
  private readonly rootResolver: PersonalRootResolver;
  private readonly runStore: PersonalRunStore;
  private readonly skillAdapter: PersonalSkillAdapter;
  private readonly c7: PersonalC7Gateway | undefined;
  private readonly upstreamCommit: string;
  private readonly claimsResolver: PersonalClaimsResolver | undefined;

  constructor(options: {
    rootResolver: PersonalRootResolver;
    runStore: PersonalRunStore;
    skillAdapter: PersonalSkillAdapter;
    c7?: PersonalC7Gateway;
    claimsResolver?: PersonalClaimsResolver;
    upstreamCommit: string;
  }) {
    if (!/^[a-f0-9]{40}$/u.test(options.upstreamCommit)) {
      throw new Error("The OpenWiki upstream commit must be a full SHA-1.");
    }
    this.rootResolver = options.rootResolver;
    this.runStore = options.runStore;
    this.skillAdapter = options.skillAdapter;
    this.c7 = options.c7;
    this.claimsResolver = options.claimsResolver;
    this.upstreamCommit = options.upstreamCommit;
  }

  async begin(inputValue: unknown): Promise<unknown> {
    const parsed = toolInputSchemas.openwiki_begin.parse(inputValue);
    const language = validatePersonalLanguage(parsed.language);
    const root = await this.rootResolver.resolve(parsed.wikiRoot);
    const skills = await this.skillAdapter.resolve(parsed.skills ?? []);
    // Cold-start recovery reads the previous run before begin registers its store.
    this.runStore.bindRoot?.(root.runtimeRoot);
    let currentRoot = root;
    const result = await withC7Locks(
      root.runtimeRoot,
      ["operation", "wiki"],
      async () => {
        if (
          this.claimsResolver !== undefined &&
          this.runStore.read !== undefined &&
          this.runStore.setWikiRevisions !== undefined &&
          this.runStore.setPhase !== undefined
        ) {
          const recovered = await recoverPersonalClaimsFinalization(
            root.runtimeRoot,
            root.wikiRoot,
          );
          if (recovered !== null) {
            const state = await this.runStore.read(recovered.journal.runId);
            if (
              state.runId !== recovered.journal.runId ||
              state.wikiRoot !== root.wikiRoot ||
              state.runtimeRoot !== root.runtimeRoot ||
              state.candidate?.transactionId !==
                recovered.journal.transactionId ||
              state.candidate?.generation !== recovered.journal.generation ||
              state.candidate?.candidateBindingHash !==
                recovered.journal.bindingHash
            ) {
              throw codedPersonalError("restore_required");
            }
            await this.runStore.setWikiRevisions(state.runId, {
              markdownWikiRevision: recovered.snapshot.markdownRootHash,
              wikiRevision: recovered.snapshot.rootHash,
            });
            await this.runStore.setPhase(state.runId, "complete");
            currentRoot = {
              ...root,
              markdownWikiRevision: recovered.snapshot.markdownRootHash,
              wikiRevision: recovered.snapshot.rootHash,
            };
            await removePersonalClaimsFinalization(root.runtimeRoot);
            await removePersonalFinalizationMarker(root.runtimeRoot);
          }
        }
        const started = await this.runStore.begin({
          ...(parsed.force === undefined ? {} : { force: parsed.force }),
          ...(language === undefined ? {} : { language }),
          mode: parsed.mode,
          requestedSkills: parsed.skills ?? [],
          skillIds: skills.skillIds,
          ...(skills.compatibilityManifestHash === undefined
            ? {}
            : { compatibilityManifestHash: skills.compatibilityManifestHash }),
          runtimeRoot: currentRoot.runtimeRoot,
          skillAggregateHash: skills.skillAggregateHash,
          ...(parsed.sourceConfirmation === undefined
            ? {}
            : { sourceConfirmation: parsed.sourceConfirmation }),
          ...(parsed.sourceManifestId === undefined
            ? {}
            : { sourceManifestId: parsed.sourceManifestId }),
          markdownWikiRevision:
            currentRoot.markdownWikiRevision ?? currentRoot.wikiRevision,
          wikiRevision: currentRoot.wikiRevision,
          wikiRoot: currentRoot.wikiRoot,
        });
        if (started.status === "resuming") {
          if (
            this.runStore.read === undefined ||
            this.runStore.readJob === undefined ||
            this.runStore.acceptPage === undefined
          ) {
            throw codedPersonalError("restore_required");
          }
          await reconcileCandidateRecovery(
            await this.runStore.read(started.runId),
            this.runStore,
          );
        }
        return started;
      },
    );
    const common = {
      ok: true,
      protocol: "selfopenwiki:personal-openwiki-v1",
      recovery: { action: "none" },
      runtimeRoot: root.runtimeRoot,
      skillAggregateHash: skills.skillAggregateHash,
      status: result.status,
      upstreamCommit: this.upstreamCommit,
      wikiRevision: currentRoot.wikiRevision,
      wikiRoot: currentRoot.wikiRoot,
    };
    return result.status === "noop"
      ? common
      : {
          ...common,
          binding: {
            markdownWikiRevision:
              currentRoot.markdownWikiRevision ?? currentRoot.wikiRevision,
            runtimeRoot: root.runtimeRoot,
            skillAggregateHash: skills.skillAggregateHash,
            upstreamCommit: this.upstreamCommit,
            wikiRevision: currentRoot.wikiRevision,
            wikiRoot: currentRoot.wikiRoot,
          },
          runId: result.runId,
        };
  }

  async submitPlan(inputValue: unknown): Promise<unknown> {
    const parsed = toolInputSchemas.openwiki_submit_plan.parse(inputValue);
    if (
      this.runStore.submitPlan === undefined ||
      this.runStore.read === undefined ||
      this.runStore.attachCandidate === undefined ||
      this.c7 === undefined
    ) {
      throw codedPersonalError("capability_unverified");
    }
    const stateBeforePlan = await this.runStore.read(parsed.runId);
    const claimSnapshots: Record<string, PersonalClaimsSnapshot> = {};
    if (this.claimsResolver !== undefined) {
      for (const page of parsed.pages) {
        claimSnapshots[page.path] = await this.claimsResolver.load(
          stateBeforePlan.wikiRoot,
          page.path,
        );
      }
    }
    const plan = await this.runStore.submitPlan({
      ...parsed,
      ...(this.claimsResolver === undefined ? {} : { claimSnapshots }),
    });
    let state = await this.runStore.read(parsed.runId);
    let candidate: PersonalCandidateBinding;
    try {
      candidate =
        state.candidate ??
        (await this.c7.start({
          confirmedByUser: parsed.confirmedByUser,
          deletePages: parsed.deletePages,
          pages: state.jobs ?? parsed.pages,
          runId: parsed.runId,
          requestedSkills: state.requestedSkills,
          skillAggregateHash: state.skillAggregateHash,
          compatibilityManifestHash: state.compatibilityManifestHash,
          sourceConfirmation: state.sourceConfirmation,
          sourceManifestId: state.sourceManifestId,
          markdownWikiRevision:
            state.markdownWikiRevision ?? state.wikiRevision,
          wikiRevision: state.markdownWikiRevision ?? state.wikiRevision,
          wikiRoot: state.wikiRoot,
        }));
    } catch (error) {
      await this.runStore.rollbackPlan?.(parsed.runId, plan.planHash);
      throw error;
    }
    if (state.candidate === undefined) {
      await this.runStore.attachCandidate(parsed.runId, candidate);
      state = await this.runStore.read(parsed.runId);
    }
    const binding = personalBinding(
      parsed.runId,
      plan.planHash,
      plan.queueHash,
      candidate,
    );
    return {
      binding,
      ok: true,
      pageCount: plan.pageCount,
      planHash: plan.planHash,
      protocol: "selfopenwiki:personal-openwiki-v1",
      queueHash: plan.queueHash,
      recovery: { action: "none" },
      runId: parsed.runId,
      status: "plan_accepted",
    };
  }

  async nextPage(inputValue: unknown): Promise<unknown> {
    const parsed = toolInputSchemas.openwiki_next_page.parse(inputValue);
    if (
      this.runStore.nextPage === undefined ||
      this.runStore.read === undefined
    ) {
      throw codedPersonalError("capability_unverified");
    }
    const state = await this.runStore.read(parsed.runId);
    if (
      state.candidate === undefined ||
      state.planHash === undefined ||
      state.planHash === null ||
      state.queueHash === undefined ||
      state.queueHash === null
    ) {
      throw codedPersonalError("invalid_state");
    }
    const job = await this.runStore.nextPage(parsed.runId);
    const binding = personalBinding(
      parsed.runId,
      state.planHash,
      state.queueHash,
      state.candidate,
    );
    if (job === null) {
      return {
        binding,
        nextAction: "finish",
        ok: true,
        protocol: "selfopenwiki:personal-openwiki-v1",
        recovery: { action: "none" },
        remainingPages: 0,
        runId: parsed.runId,
        status: "queue_complete",
      };
    }
    return {
      binding,
      candidate: {
        pagePath: job.path,
        permissions: ["read", "list", "write"],
        rootPath: state.candidate.candidateRoot,
      },
      issueClaims: job.issueClaims,
      jobId: job.jobId,
      ok: true,
      path: job.path,
      protocol: "selfopenwiki:personal-openwiki-v1",
      purpose: job.purpose,
      recovery: { action: "none" },
      relatedPages: job.relatedPages ?? [],
      runId: parsed.runId,
      seedPaths: job.seedPaths ?? [],
      status: "page_pending",
      title: job.title,
    };
  }

  async inspectPageClaims(inputValue: unknown): Promise<unknown> {
    const parsed =
      toolInputSchemas.openwiki_inspect_page_claims.parse(inputValue);
    if (
      this.runStore.inspectClaims === undefined ||
      this.runStore.read === undefined
    ) {
      throw codedPersonalError("capability_unverified");
    }
    const state = await this.runStore.read(parsed.runId);
    if (
      state.candidate === undefined ||
      state.planHash === undefined ||
      state.planHash === null ||
      state.queueHash === undefined ||
      state.queueHash === null
    ) {
      throw codedPersonalError("invalid_state");
    }
    const result = await this.runStore.inspectClaims(
      parsed.runId,
      parsed.jobId,
    );
    if (result.jobId !== parsed.jobId)
      throw codedPersonalError("invalid_state");
    const authoritative = await this.authoritativeClaimsForJob(
      state,
      parsed.jobId,
    );
    const claims = authoritative ?? result.claims;
    return {
      binding: personalBinding(
        parsed.runId,
        state.planHash,
        state.queueHash,
        state.candidate,
      ),
      claims,
      claimsHash: personalHash(claims),
      jobId: parsed.jobId,
      ok: true,
      protocol: "selfopenwiki:personal-openwiki-v1",
      recovery: { action: "none" },
      runId: parsed.runId,
      status: "claims_inspected",
    };
  }

  async submitPage(inputValue: unknown): Promise<unknown> {
    const parsed = toolInputSchemas.openwiki_submit_page.parse(inputValue);
    if (
      this.runStore.read === undefined ||
      this.runStore.readJob === undefined ||
      this.runStore.acceptPage === undefined
    ) {
      throw codedPersonalError("capability_unverified");
    }
    const state = await this.runStore.read(parsed.runId);
    if (
      state.candidate === undefined ||
      state.planHash === undefined ||
      state.planHash === null ||
      state.queueHash === undefined ||
      state.queueHash === null
    ) {
      throw codedPersonalError("invalid_state");
    }
    const candidateBinding = state.candidate;
    const planHash = state.planHash;
    const queueHash = state.queueHash;
    const job = await this.runStore.readJob(parsed.runId, parsed.jobId);
    if (
      job === null ||
      (job.status !== "assigned" && job.status !== "accepted")
    ) {
      throw codedPersonalError("invalid_state");
    }
    const pagePath = containedCandidatePath(
      candidateBinding.candidateRoot,
      job.path,
    );
    return withC7Locks(state.runtimeRoot, ["operation", "wiki"], async () => {
      const bytes = await readStableWikiPage(
        candidateBinding.candidateRoot,
        pagePath,
      );
      validateOkfPage(bytes);
      const pageContentHash = hashBytes(bytes);
      const confirmedClaimIds = parsed.confirmedClaimIds ?? [];
      const retractedClaimIds = parsed.retractedClaimIds ?? [];
      if (
        new Set([...confirmedClaimIds, ...retractedClaimIds]).size !==
        confirmedClaimIds.length + retractedClaimIds.length
      ) {
        throw codedPersonalError("invalid_input");
      }
      const claimDecisionHash = personalHash({
        claims: parsed.claims ?? [],
        confirmedClaimIds,
        retractedClaimIds,
      });
      const authoritativeClaims = await this.authoritativeClaimsForJob(
        state,
        parsed.jobId,
      );
      const decisionJob =
        authoritativeClaims === undefined
          ? job
          : { ...job, issueClaims: authoritativeClaims };
      validateClaimDecisions(decisionJob, parsed.claims ?? [], [
        ...confirmedClaimIds,
        ...retractedClaimIds,
      ]);
      await validatePersonalClaimEvidence(state, parsed.claims ?? []);
      const candidateRootHash = await snapshotPersonalCandidate(
        candidateBinding.candidateRoot,
      );
      const markerPath = path.join(
        state.runtimeRoot,
        "page-markers",
        state.runId,
        `${parsed.jobId}.json`,
      );
      if (job.status === "accepted") {
        const marker = await readPersonalCandidateMarker(markerPath);
        if (
          marker === null ||
          marker.state !== "accepted" ||
          marker.pageContentHash !== pageContentHash ||
          marker.claimDecisionHash !== claimDecisionHash
        ) {
          throw codedPersonalError("invalid_state");
        }
        return {
          binding: personalBinding(
            parsed.runId,
            planHash,
            queueHash,
            candidateBinding,
          ),
          candidateBindingHash: candidateBinding.candidateBindingHash,
          claimDecisionHash,
          jobId: parsed.jobId,
          ok: true,
          pageContentHash,
          protocol: "selfopenwiki:personal-openwiki-v1",
          recovery: { action: "none" },
          remainingPages:
            state.jobs?.filter((entry) => entry.status === "pending").length ??
            0,
          runId: parsed.runId,
          status: "page_accepted",
        };
      }
      const now = new Date().toISOString();
      await writePersonalCandidateMarker(markerPath, {
        candidateBindingHash: candidateBinding.candidateBindingHash,
        candidateRoot: candidateBinding.candidateRoot,
        candidateRootHash,
        claimDecisionHash,
        createdAt: now,
        generation: candidateBinding.generation,
        jobId: parsed.jobId,
        pageContentHash,
        pagePath: job.path,
        pagePathHash: personalHash(job.path),
        runId: parsed.runId,
        state: "candidate_written",
        transactionId: candidateBinding.transactionId,
        type: "selfopenwiki:candidate-page-marker-v1",
        updatedAt: now,
        version: 1,
        writerExecutionId: `personal-writer-${parsed.runId}`,
      });
      const accepted = await this.runStore.acceptPage!({
        claimDecisions: [
          ...(parsed.claims ?? []),
          ...confirmedClaimIds.map((id) => ({ action: "confirm", id })),
          ...retractedClaimIds.map((id) => ({ action: "retract", id })),
        ],
        claimDecisionHash,
        jobId: parsed.jobId,
        pageContentHash,
        runId: parsed.runId,
      });
      await transitionPersonalCandidateMarker(
        markerPath,
        "accepted",
        new Date().toISOString(),
      );
      return {
        binding: personalBinding(
          parsed.runId,
          planHash,
          queueHash,
          candidateBinding,
        ),
        candidateBindingHash: candidateBinding.candidateBindingHash,
        claimDecisionHash,
        jobId: parsed.jobId,
        ok: true,
        pageContentHash,
        protocol: "selfopenwiki:personal-openwiki-v1",
        recovery: { action: "none" },
        remainingPages: accepted.remainingPages,
        runId: parsed.runId,
        status: "page_accepted",
      };
    });
  }

  async finish(inputValue: unknown): Promise<unknown> {
    const parsed = toolInputSchemas.openwiki_finish.parse(inputValue);
    if (this.runStore.read === undefined) {
      throw codedPersonalError("capability_unverified");
    }
    const state = await this.runStore.read(parsed.runId);
    if (
      state.candidate === undefined ||
      state.planHash === undefined ||
      state.planHash === null ||
      state.queueHash === undefined ||
      state.queueHash === null ||
      state.jobs === undefined ||
      state.jobs.some((job) => job.status !== "accepted")
    ) {
      throw codedPersonalError("invalid_state");
    }
    if (
      state.phase === "review" &&
      parsed.reviewReceipt !== undefined &&
      await this.recoverPublishedPersonalRun(state, parsed.reviewReceipt)
    ) {
      return this.finish(parsed);
    }
    if (state.phase === "complete") {
      const receipt = parsed.reviewReceipt;
      if (
        parsed.candidateReceipt !== undefined ||
        (receipt !== undefined &&
          (receipt.transactionId !== state.candidate.transactionId ||
            receipt.generation !== state.candidate.generation ||
            receipt.bindingHash !== state.candidate.candidateBindingHash))
      ) {
        throw codedPersonalError("invalid_state");
      }
      if (this.c7?.readCompletion === undefined) {
        throw codedPersonalError("capability_unverified");
      }
      const completed = await this.c7.readCompletion({
        candidate: state.candidate,
        expectedAfterWikiHash: state.markdownWikiRevision ?? state.wikiRevision,
        ...(receipt === undefined ? {} : { reviewReceipt: receipt }),
        runId: parsed.runId,
        runtimeRoot: state.runtimeRoot,
        wikiRoot: state.wikiRoot,
      });
      await withC7Locks(state.runtimeRoot, ["operation", "wiki"], async () => {
        const journal = await readPersonalClaimsFinalization(state.runtimeRoot);
        const marker = await readPersonalFinalizationMarker(state.runtimeRoot);
        if (journal?.runId !== state.runId && marker?.runId !== state.runId) return;
        if (
          marker === null || marker.status !== "published" ||
          marker.reviewReceiptHash !== completed.reviewReceiptHash ||
          marker.afterWikiHash !== completed.afterWikiHash ||
          [journal, marker].some((record) => record !== null && (
            record.runId !== state.runId ||
            record.transactionId !== state.candidate!.transactionId ||
            record.generation !== state.candidate!.generation ||
            record.bindingHash !== state.candidate!.candidateBindingHash
          )) ||
          (journal !== null && (
            journal.reviewReceiptInputHash !== marker.reviewReceiptInputHash ||
            journal.afterWikiHash !== completed.afterWikiHash ||
            journal.completedOperations.length !== journal.operations.length
          ))
        ) throw codedPersonalError("restore_required");
        const final = await snapshotPersonalWiki(state.wikiRoot);
        if (
          final.rootHash !== state.wikiRevision ||
          final.markdownRootHash !== completed.afterWikiHash ||
          (journal !== null && personalHash(final.claims) !== journal.expectedFinalClaimsHash)
        ) throw codedPersonalError("restore_required");
        await removePersonalClaimsFinalization(state.runtimeRoot);
        await removePersonalFinalizationMarker(state.runtimeRoot);
      });
      return {
        afterWikiHash: completed.afterWikiHash,
        beforeWikiHash: completed.beforeWikiHash,
        binding: personalBinding(parsed.runId, state.planHash, state.queueHash, state.candidate),
        ok: true,
        protocol: "selfopenwiki:personal-openwiki-v1",
        published: true,
        recovery: { action: "none" },
        generation: state.candidate.generation,
        reviewReceiptHash: completed.reviewReceiptHash,
        runId: parsed.runId,
        runReceiptHash: completed.runReceiptHash,
        status: "complete",
        transactionId: state.candidate.transactionId,
        wikiRevision: state.wikiRevision,
        ...(completed.followUp === undefined ? {} : { followUp: completed.followUp }),
      };
    }
    if (
      parsed.candidateReceipt === undefined &&
      parsed.reviewReceipt === undefined
    ) {
      return {
        binding: personalBinding(
          parsed.runId,
          state.planHash,
          state.queueHash,
          state.candidate,
        ),
        nextAction: "submit_candidate_receipt",
        ok: true,
        protocol: "selfopenwiki:personal-openwiki-v1",
        recovery: { action: "none" },
        generation: state.candidate.generation,
        runId: parsed.runId,
        status: "review_required",
        transactionId: state.candidate.transactionId,
      };
    }
    if (
      parsed.candidateReceipt !== undefined &&
      parsed.reviewReceipt === undefined
    ) {
      if (
        this.c7?.prepareReview === undefined ||
        parsed.candidateReceipt.transactionId !==
          state.candidate.transactionId ||
        parsed.candidateReceipt.generation !== state.candidate.generation ||
        parsed.candidateReceipt.bindingHash !==
          state.candidate.candidateBindingHash
      ) {
        throw codedPersonalError("invalid_state");
      }
      const prepared = await this.c7.prepareReview({
        candidateReceipt: parsed.candidateReceipt,
        runId: parsed.runId,
        runtimeRoot: state.runtimeRoot,
        wikiRoot: state.wikiRoot,
      });
      await this.runStore.setPhase?.(parsed.runId, "review");
      if (prepared.kind === "needs_clarification") {
        return {
          binding: personalBinding(
            parsed.runId,
            state.planHash,
            state.queueHash,
            state.candidate,
          ),
          candidateRetained: true,
          issues: prepared.issues,
          nextAction: "clarify",
          ok: true,
          protocol: "selfopenwiki:personal-openwiki-v1",
          published: false,
          questions: prepared.questions,
          recovery: { action: "none" },
          generation: state.candidate.generation,
          runId: parsed.runId,
          status: "needs_clarification",
          transactionId: state.candidate.transactionId,
        };
      }
      return {
        binding: personalBinding(
          parsed.runId,
          state.planHash,
          state.queueHash,
          state.candidate,
        ),
        nextAction: "submit_review_receipt",
        ok: true,
        protocol: "selfopenwiki:personal-openwiki-v1",
        recovery: { action: "none" },
        generation: state.candidate.generation,
        candidateReceiptHash: prepared.candidateReceiptHash,
        candidateRootHash: prepared.candidateRootHash,
        reviewPackage: prepared.reviewPackage,
        reviewPackageHash: prepared.reviewPackageHash,
        runId: parsed.runId,
        status: "review_required",
        transactionId: state.candidate.transactionId,
      };
    }
    if (
      this.c7?.submitReview === undefined ||
      parsed.reviewReceipt === undefined
    ) {
      throw codedPersonalError("capability_unverified");
    }
    const reviewReceipt = parsed.reviewReceipt;
    if (
      reviewReceipt.transactionId !== state.candidate.transactionId ||
      reviewReceipt.generation !== state.candidate.generation ||
      reviewReceipt.bindingHash !== state.candidate.candidateBindingHash
    ) {
      throw codedPersonalError("invalid_state");
    }
    let personalWikiRevision: string | undefined;
    const beforeWikiHash = state.markdownWikiRevision ?? state.wikiRevision;
    const submitted =
      this.claimsResolver !== undefined && state.jobs !== undefined
        ? await withC7Locks(
            state.runtimeRoot,
            ["operation", "wiki"],
            async () => {
              const before = await snapshotPersonalWiki(state.wikiRoot);
              if (
                before.markdownRootHash !== beforeWikiHash ||
                (state.markdownWikiRevision !== undefined &&
                  before.rootHash !== state.wikiRevision)
              ) {
                throw codedPersonalError("wiki_conflict");
              }
              const reviewReceiptInputHash = personalHash(reviewReceipt);
              const existingMarker = await readPersonalFinalizationMarker(
                state.runtimeRoot,
              );
              if (
                existingMarker !== null &&
                (existingMarker.runId !== state.runId ||
                  existingMarker.transactionId !==
                    state.candidate!.transactionId ||
                  existingMarker.generation !== state.candidate!.generation ||
                  existingMarker.bindingHash !==
                    state.candidate!.candidateBindingHash ||
                  existingMarker.reviewReceiptInputHash !==
                    reviewReceiptInputHash)
              ) {
                throw codedPersonalError("invalid_state");
              }
              const claimsJournal = await preparePersonalClaimsFinalization(
                state,
                before.markdownRootHash,
                reviewReceipt.candidateRootHash,
                personalHash(before.claims),
                reviewReceiptInputHash,
              );
              await writePersonalClaimsFinalization(claimsJournal);
              await writePersonalFinalizationMarker(state.runtimeRoot, {
                bindingHash: state.candidate!.candidateBindingHash,
                generation: state.candidate!.generation,
                reviewReceiptInputHash,
                runId: state.runId,
                status: "prepared",
                transactionId: state.candidate!.transactionId,
                type: "selfopenwiki:personal-finalization-v1",
                version: 1,
              });
              const result = await this.c7!.submitReview!({
                beforeWikiHash,
                reviewReceipt,
                runId: parsed.runId,
                runtimeRoot: state.runtimeRoot,
                wikiRoot: state.wikiRoot,
              });
              if (result.kind !== "complete") {
                await removePersonalClaimsFinalization(state.runtimeRoot);
                await removePersonalFinalizationMarker(state.runtimeRoot);
                return result;
              }
              if (
                result.beforeWikiHash !== beforeWikiHash ||
                result.afterWikiHash !== claimsJournal.afterWikiHash
              ) {
                throw codedPersonalError("wiki_conflict");
              }
              const after = await snapshotPersonalWiki(state.wikiRoot);
              if (
                after.markdownRootHash !== result.afterWikiHash ||
                personalHash(after.claims) !== claimsJournal.baselineClaimsHash
              ) {
                throw codedPersonalError("wiki_conflict");
              }
              await writePersonalFinalizationMarker(state.runtimeRoot, {
                afterWikiHash: result.afterWikiHash,
                bindingHash: state.candidate!.candidateBindingHash,
                generation: state.candidate!.generation,
                reviewReceiptHash: result.reviewReceiptHash,
                reviewReceiptInputHash,
                runId: state.runId,
                status: "published",
                transactionId: state.candidate!.transactionId,
                type: "selfopenwiki:personal-finalization-v1",
                version: 1,
              });
              const finalSnapshot = await applyPersonalClaimsFinalization(
                claimsJournal,
                state.wikiRoot,
              );
              personalWikiRevision = finalSnapshot.rootHash;
              if (this.runStore.setWikiRevisions !== undefined) {
                await this.runStore.setWikiRevisions(parsed.runId, {
                  markdownWikiRevision: result.afterWikiHash,
                  wikiRevision: personalWikiRevision,
                });
              } else {
                await this.runStore.setWikiRevision?.(
                  parsed.runId,
                  personalWikiRevision,
                );
              }
              await this.runStore.setPhase?.(parsed.runId, "complete");
              await removePersonalClaimsFinalization(state.runtimeRoot);
              await removePersonalFinalizationMarker(state.runtimeRoot);
              return result;
            },
          )
        : await this.c7.submitReview({
            beforeWikiHash,
            reviewReceipt,
            runId: parsed.runId,
            runtimeRoot: state.runtimeRoot,
            wikiRoot: state.wikiRoot,
          });
    if (submitted.kind === "complete" && this.claimsResolver === undefined) {
      if (this.runStore.setWikiRevisions !== undefined) {
        const finalSnapshot = await snapshotPersonalWiki(state.wikiRoot);
        if (finalSnapshot.markdownRootHash !== submitted.afterWikiHash) {
          throw codedPersonalError("wiki_conflict");
        }
        await this.runStore.setWikiRevisions(parsed.runId, {
          markdownWikiRevision: submitted.afterWikiHash,
          wikiRevision: finalSnapshot.rootHash,
        });
      } else {
        await this.runStore.setWikiRevision?.(
          parsed.runId,
          submitted.wikiRevision,
        );
      }
      await this.runStore.setPhase?.(parsed.runId, "complete");
    }
    const binding = personalBinding(
      parsed.runId,
      state.planHash,
      state.queueHash,
      state.candidate,
    );
    if (submitted.kind === "publish_pending") {
      return {
        binding,
        ok: true,
        protocol: "selfopenwiki:personal-openwiki-v1",
        recovery: { action: "restore" },
        generation: state.candidate.generation,
        runId: parsed.runId,
        status: "publish_pending",
        transactionId: state.candidate.transactionId,
      };
    }
    if (submitted.kind === "repair_ready") {
      if (state.candidate.generation >= 3) {
        return {
          binding,
          candidateRetained: true,
          issues: submitted.issues,
          nextAction: "clarify",
          ok: true,
          protocol: "selfopenwiki:personal-openwiki-v1",
          published: false,
          questions: [
            "The personal Wiki repair limit was reached; clarify the remaining review issues or abort.",
          ],
          recovery: { action: "none" },
          generation: state.candidate.generation,
          runId: parsed.runId,
          status: "needs_clarification",
          transactionId: state.candidate.transactionId,
        };
      }
      if (
        this.c7?.resumeRepair !== undefined &&
        this.runStore.beginSuccessor !== undefined
      ) {
        const successor = await this.c7.resumeRepair({
          bindingHash: state.candidate.candidateBindingHash,
          runId: parsed.runId,
          runtimeRoot: state.runtimeRoot,
          transactionId: state.candidate.transactionId,
          wikiRoot: state.wikiRoot,
        });
        const next = await this.runStore.beginSuccessor(
          parsed.runId,
          successor,
        );
        return {
          binding: personalBinding(
            parsed.runId,
            state.planHash,
            next.queueHash,
            successor,
          ),
          issues: submitted.issues,
          nextAction: "resume",
          ok: true,
          protocol: "selfopenwiki:personal-openwiki-v1",
          recovery: { action: "none" },
          generation: successor.generation,
          runId: parsed.runId,
          status: "repair_ready",
          transactionId: successor.transactionId,
        };
      }
      return {
        binding,
        issues: submitted.issues,
        nextAction: "resume",
        ok: true,
        protocol: "selfopenwiki:personal-openwiki-v1",
        recovery: { action: "none" },
        generation: state.candidate.generation,
        runId: parsed.runId,
        status: "repair_ready",
        transactionId: state.candidate.transactionId,
      };
    }
    if (submitted.kind === "needs_clarification") {
      return {
        binding,
        candidateRetained: true,
        issues: submitted.issues,
        nextAction: "clarify",
        ok: true,
        protocol: "selfopenwiki:personal-openwiki-v1",
        published: false,
        questions: submitted.questions,
        recovery: { action: "none" },
        generation: state.candidate.generation,
        runId: parsed.runId,
        status: "needs_clarification",
        transactionId: state.candidate.transactionId,
      };
    }
    return {
      afterWikiHash: submitted.afterWikiHash,
      beforeWikiHash: submitted.beforeWikiHash,
      binding,
      ok: true,
      protocol: "selfopenwiki:personal-openwiki-v1",
      published: true,
      recovery: { action: "none" },
      generation: state.candidate.generation,
      reviewReceiptHash: submitted.reviewReceiptHash,
      runId: parsed.runId,
      runReceiptHash: submitted.runReceiptHash,
      status: "complete",
      transactionId: state.candidate.transactionId,
      wikiRevision: personalWikiRevision ?? submitted.wikiRevision,
      ...(submitted.followUp === undefined
        ? {}
        : { followUp: submitted.followUp }),
    };
  }

  private async recoverPublishedPersonalRun(
    state: PersonalRunRecord,
    reviewReceipt: unknown,
  ): Promise<boolean> {
    const candidate = state.candidate;
    const readCompletion = this.c7?.readCompletion?.bind(this.c7);
    if (
      candidate === undefined || this.claimsResolver === undefined ||
      readCompletion === undefined || this.runStore.setWikiRevisions === undefined ||
      this.runStore.setPhase === undefined
    ) return false;
    return withC7Locks(state.runtimeRoot, ["operation", "wiki"], async () => {
      const journal = await readPersonalClaimsFinalization(state.runtimeRoot);
      if (journal === null || journal.runId !== state.runId) return false;
      const marker = await readPersonalFinalizationMarker(state.runtimeRoot);
      const receiptHash = personalHash(reviewReceipt);
      if (
        marker === null ||
        [journal, marker].some((record) =>
          record.runId !== state.runId ||
          record.transactionId !== candidate.transactionId ||
          record.generation !== candidate.generation ||
          record.bindingHash !== candidate.candidateBindingHash ||
          record.reviewReceiptInputHash !== receiptHash
        )
      ) throw codedPersonalError("invalid_state");
      const current = await snapshotPersonalWiki(state.wikiRoot);
      if (
        marker.status === "prepared" &&
        journal.status === "prepared" &&
        journal.completedOperations.length === 0 &&
        current.markdownRootHash === candidate.wikiRevision &&
        current.rootHash === state.wikiRevision
      ) return false;
      if (current.markdownRootHash !== journal.afterWikiHash) {
        throw codedPersonalError("wiki_conflict");
      }
      // A matching Markdown tree alone is not publication authority.
      const completed = await readCompletion({
        candidate, expectedAfterWikiHash: journal.afterWikiHash, reviewReceipt,
        runId: state.runId, runtimeRoot: state.runtimeRoot, wikiRoot: state.wikiRoot,
      });
      await writePersonalFinalizationMarker(state.runtimeRoot, {
        afterWikiHash: completed.afterWikiHash,
        bindingHash: candidate.candidateBindingHash,
        generation: candidate.generation,
        reviewReceiptHash: completed.reviewReceiptHash,
        reviewReceiptInputHash: receiptHash,
        runId: state.runId,
        status: "published",
        transactionId: candidate.transactionId,
        type: "selfopenwiki:personal-finalization-v1",
        version: 1,
      });
      const recovered = await recoverPersonalClaimsFinalization(state.runtimeRoot, state.wikiRoot);
      if (recovered === null) throw codedPersonalError("restore_required");
      await this.runStore.setWikiRevisions!(state.runId, {
        markdownWikiRevision: recovered.snapshot.markdownRootHash,
        wikiRevision: recovered.snapshot.rootHash,
      });
      await this.runStore.setPhase!(state.runId, "complete");
      await removePersonalClaimsFinalization(state.runtimeRoot);
      await removePersonalFinalizationMarker(state.runtimeRoot);
      return true;
    });
  }

  private async authoritativeClaimsForJob(
    state: PersonalRunRecord,
    jobId: string,
  ): Promise<readonly unknown[] | undefined> {
    if (
      this.claimsResolver === undefined ||
      this.runStore.readJob === undefined
    ) {
      return undefined;
    }
    const job = await this.runStore.readJob(state.runId, jobId);
    if (job === null) throw codedPersonalError("invalid_state");
    const snapshot = await this.claimsResolver.load(state.wikiRoot, job.path);
    if (snapshot.source !== "authoritative") {
      if (job.claimSource === "authoritative") {
        throw codedPersonalError("validation_failed");
      }
      return undefined;
    }
    if (
      job.claimSource === "authoritative" &&
      personalHash(job.issueClaims) !== personalHash(snapshot.claims)
    ) {
      throw codedPersonalError("validation_failed");
    }
    await validatePersonalClaimEvidence(state, snapshot.claims);
    return snapshot.claims;
  }
}

async function preparePersonalClaimsFinalization(
  state: PersonalRunRecord,
  beforeWikiHash: string,
  afterWikiHash: string,
  baselineClaimsHash: string,
  reviewReceiptInputHash: string,
): Promise<PersonalClaimsFinalizationJournal> {
  const existing = await readPersonalClaimsFinalization(state.runtimeRoot);
  if (existing !== null) {
    if (
      existing.runId !== state.runId ||
      existing.transactionId !== state.candidate?.transactionId ||
      existing.generation !== state.candidate?.generation ||
      existing.bindingHash !== state.candidate?.candidateBindingHash ||
      existing.afterWikiHash !== afterWikiHash ||
      existing.reviewReceiptInputHash !== reviewReceiptInputHash
    ) {
      throw codedPersonalError("invalid_state");
    }
    return existing;
  }
  if (state.jobs === undefined || state.candidate === undefined) {
    throw codedPersonalError("invalid_state");
  }
  const baseline = await snapshotPersonalWiki(state.wikiRoot);
  if (
    baseline.markdownRootHash !== beforeWikiHash ||
    personalHash(baseline.claims) !== baselineClaimsHash
  ) {
    throw codedPersonalError("wiki_conflict");
  }
  const candidateSnapshot = await snapshotMarkdownTree(
    state.candidate.candidateRoot,
  );
  if (candidateSnapshot.rootHash !== afterWikiHash) {
    throw codedPersonalError("wiki_conflict");
  }
  const operations: PersonalClaimsFinalizationOperation[] = [];
  let expectedClaims = baseline.claims;
  for (const job of state.jobs) {
    if (job.status !== "accepted") {
      throw codedPersonalError("invalid_state");
    }
    const pagePath = containedCandidatePath(
      state.candidate.candidateRoot,
      job.path,
    );
    const pageBytes = await readStableWikiPage(
      state.candidate.candidateRoot,
      pagePath,
    );
    const payload = createPersonalClaimsPayload(
      reconcilePersonalClaims(job),
      pageBytes,
    );
    const operation = {
      action: "write",
      claims: reconcilePersonalClaims(job),
      desiredSidecarHash: payload.hash,
      desiredSidecarSize: payload.bytes.byteLength,
      expectedSidecarHash: await inspectPersonalClaimsSidecar(
        state.wikiRoot,
        job.path,
      ),
      pageHash: hashPersonalClaimsBytes(pageBytes),
      pagePath: job.path,
    } as const;
    const afterClaims = expectedClaimDescriptors(expectedClaims, [operation]);
    operations.push({
      ...operation,
      afterClaimsHash: personalHash(afterClaims),
    });
    expectedClaims = afterClaims;
  }
  for (const pagePath of state.deletePages ?? []) {
    const operation = {
      action: "delete",
      desiredSidecarHash: null,
      expectedSidecarHash: await inspectPersonalClaimsSidecar(
        state.wikiRoot,
        pagePath,
      ),
      pagePath,
    } as const;
    const afterClaims = expectedClaimDescriptors(expectedClaims, [operation]);
    operations.push({
      ...operation,
      afterClaimsHash: personalHash(afterClaims),
    });
    expectedClaims = afterClaims;
  }
  return {
    afterWikiHash,
    baselineClaimsHash,
    bindingHash: state.candidate.candidateBindingHash,
    completedOperations: [],
    currentClaimsHash: baselineClaimsHash,
    expectedFinalClaimsHash: personalHash(expectedClaims),
    generation: state.candidate.generation,
    operations,
    reviewReceiptInputHash,
    runId: state.runId,
    runtimeRoot: state.runtimeRoot,
    status: "prepared",
    transactionId: state.candidate.transactionId,
    type: "selfopenwiki:personal-claims-finalization-v1",
    version: 1,
  };
}

async function applyPersonalClaimsFinalization(
  journal: PersonalClaimsFinalizationJournal,
  wikiRoot: string,
): Promise<Awaited<ReturnType<typeof snapshotPersonalWiki>>> {
  let current: PersonalClaimsFinalizationJournal = {
    ...journal,
    status: "applying",
  };
  await writePersonalClaimsFinalization(current);
  for (const [index, operation] of current.operations.entries()) {
    if (current.completedOperations.includes(index)) continue;
    if (
      current.applyingOperation !== undefined &&
      current.applyingOperation !== index
    ) {
      throw codedPersonalError("restore_required");
    }
    if (current.applyingOperation === undefined) {
      current = { ...current, applyingOperation: index };
      await writePersonalClaimsFinalization(current);
    }
    const before = await snapshotPersonalWiki(wikiRoot);
    if (before.markdownRootHash !== current.afterWikiHash) {
      throw codedPersonalError("wiki_conflict");
    }
    const beforeClaimsHash = personalHash(before.claims);
    let applied = before;
    if (beforeClaimsHash !== operation.afterClaimsHash) {
      if (beforeClaimsHash !== current.currentClaimsHash) {
        throw codedPersonalError("wiki_conflict");
      }
      await applyPersonalClaimsFinalizationOperation(
        wikiRoot,
        operation,
        current.afterWikiHash,
        current.currentClaimsHash,
      );
      applied = await snapshotPersonalWiki(wikiRoot);
    }
    if (
      applied.markdownRootHash !== current.afterWikiHash ||
      personalHash(applied.claims) !== operation.afterClaimsHash
    ) {
      throw codedPersonalError("wiki_conflict");
    }
    const { applyingOperation: _applyingOperation, ...checkpoint } = current;
    current = {
      ...checkpoint,
      completedOperations: [
        ...new Set([...current.completedOperations, index]),
      ].sort((left, right) => left - right),
      currentClaimsHash: operation.afterClaimsHash,
    };
    await writePersonalClaimsFinalization(current);
  }
  const final = await snapshotPersonalWiki(wikiRoot);
  if (
    final.markdownRootHash !== current.afterWikiHash ||
    personalHash(final.claims) !== current.expectedFinalClaimsHash ||
    personalHash(final.claims) !== current.currentClaimsHash
  ) {
    throw codedPersonalError("wiki_conflict");
  }
  return final;
}

export async function recoverPersonalClaimsFinalization(
  runtimeRoot: string,
  wikiRoot: string,
): Promise<PersonalClaimsFinalizationRecovery | null> {
  const journal = await readPersonalClaimsFinalization(runtimeRoot);
  if (journal === null) return null;
  let marker = await readPersonalFinalizationMarker(runtimeRoot);
  if (
    journal.status === "prepared" &&
    (marker === null || marker.status === "prepared")
  ) {
    const current = await snapshotPersonalWiki(wikiRoot);
    if (current.markdownRootHash === journal.afterWikiHash) {
      await writePersonalFinalizationMarker(runtimeRoot, {
        afterWikiHash: journal.afterWikiHash,
        bindingHash: journal.bindingHash,
        generation: journal.generation,
        ...(marker?.reviewReceiptHash === undefined
          ? {}
          : { reviewReceiptHash: marker.reviewReceiptHash }),
        reviewReceiptInputHash: journal.reviewReceiptInputHash,
        runId: journal.runId,
        status: "published",
        transactionId: journal.transactionId,
        type: "selfopenwiki:personal-finalization-v1",
        version: 1,
      });
      marker = await readPersonalFinalizationMarker(runtimeRoot);
    }
  }
  if (marker === null && journal.status === "prepared") {
    await writePersonalFinalizationMarker(runtimeRoot, {
      bindingHash: journal.bindingHash,
      generation: journal.generation,
      reviewReceiptInputHash: journal.reviewReceiptInputHash,
      runId: journal.runId,
      status: "prepared",
      transactionId: journal.transactionId,
      type: "selfopenwiki:personal-finalization-v1",
      version: 1,
    });
    return null;
  }
  if (
    marker === null ||
    marker.runId !== journal.runId ||
    marker.transactionId !== journal.transactionId ||
    marker.generation !== journal.generation ||
    marker.bindingHash !== journal.bindingHash ||
    (marker.status === "published" &&
      marker.afterWikiHash !== journal.afterWikiHash) ||
    (marker.status === "prepared" && journal.status !== "prepared")
  ) {
    throw codedPersonalError("restore_required");
  }
  if (marker.status === "prepared") return null;
  const snapshot = await applyPersonalClaimsFinalization(journal, wikiRoot);
  const applied = await readPersonalClaimsFinalization(runtimeRoot);
  if (applied === null) throw codedPersonalError("restore_required");
  return { journal: applied, snapshot };
}

async function applyPersonalClaimsFinalizationOperation(
  wikiRoot: string,
  operation: PersonalClaimsFinalizationOperation,
  expectedMarkdownHash: string,
  expectedClaimsHash: string,
): Promise<void> {
  const before = await snapshotPersonalWiki(wikiRoot);
  if (
    before.markdownRootHash !== expectedMarkdownHash ||
    personalHash(before.claims) !== expectedClaimsHash
  ) {
    throw codedPersonalError("wiki_conflict");
  }
  if (operation.action === "delete") {
    const current = await inspectPersonalClaimsSidecar(
      wikiRoot,
      operation.pagePath,
    );
    if (current === operation.desiredSidecarHash) return;
    if (current !== operation.expectedSidecarHash) {
      throw codedPersonalError("wiki_conflict");
    }
    await removePersonalClaims(wikiRoot, operation.pagePath);
    if (
      (await inspectPersonalClaimsSidecar(wikiRoot, operation.pagePath)) !==
      null
    ) {
      throw codedPersonalError("validation_failed");
    }
    return;
  }
  const pagePath = containedWikiPagePath(wikiRoot, operation.pagePath);
  const pageIdentity = await capturePathIdentity(wikiRoot, pagePath).catch(
    () => {
      throw codedPersonalError("wiki_conflict");
    },
  );
  const pageBytes = await readStableWikiPage(wikiRoot, pagePath).catch(() => {
    throw codedPersonalError("wiki_conflict");
  });
  if (hashPersonalClaimsBytes(pageBytes) !== operation.pageHash) {
    throw codedPersonalError("wiki_conflict");
  }
  const current = await inspectPersonalClaimsSidecar(
    wikiRoot,
    operation.pagePath,
  );
  if (current === operation.desiredSidecarHash) return;
  if (current !== operation.expectedSidecarHash) {
    throw codedPersonalError("wiki_conflict");
  }
  await writePersonalClaims(
    wikiRoot,
    operation.pagePath,
    operation.claims,
    pageBytes,
  );
  const afterPageIdentity = await capturePathIdentity(wikiRoot, pagePath).catch(
    () => {
      throw codedPersonalError("wiki_conflict");
    },
  );
  if (!samePathIdentity(pageIdentity, afterPageIdentity)) {
    throw codedPersonalError("wiki_conflict");
  }
  if (
    (await inspectPersonalClaimsSidecar(wikiRoot, operation.pagePath)) !==
    operation.desiredSidecarHash
  ) {
    throw codedPersonalError("validation_failed");
  }
}

function expectedClaimDescriptors(
  baseline: readonly {
    readonly hash: string;
    readonly relativePath: string;
    readonly size: number;
  }[],
  operations: readonly (
    | {
        readonly action: "write";
        readonly desiredSidecarHash: string;
        readonly desiredSidecarSize: number;
        readonly pagePath: string;
      }
    | {
        readonly action: "delete";
        readonly desiredSidecarHash: null;
        readonly pagePath: string;
      }
  )[],
) {
  const expected = new Map(
    baseline.map((entry) => [entry.relativePath, entry]),
  );
  for (const operation of operations) {
    const relativePath = personalClaimsSidecarPath(operation.pagePath);
    if (operation.action === "delete") {
      expected.delete(relativePath);
    } else {
      expected.set(relativePath, {
        hash: operation.desiredSidecarHash,
        relativePath,
        size: operation.desiredSidecarSize,
      });
    }
  }
  return [...expected.values()].sort((left, right) =>
    left.relativePath < right.relativePath
      ? -1
      : left.relativePath > right.relativePath
        ? 1
        : 0,
  );
}

async function readPersonalClaimsFinalization(
  runtimeRoot: string,
): Promise<PersonalClaimsFinalizationJournal | null> {
  const journalPath = path.join(
    runtimeRoot,
    "personal-claims-finalization.json",
  );
  const stat = await lstat(journalPath).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (stat === null) return null;
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw codedPersonalError("restore_required");
  }
  let value: unknown;
  try {
    value = JSON.parse(await readFile(journalPath, "utf8"));
  } catch {
    throw codedPersonalError("restore_required");
  }
  if (
    !isPersonalClaimsFinalizationJournal(value) ||
    !sameRuntimePath(value.runtimeRoot, runtimeRoot)
  ) {
    throw codedPersonalError("restore_required");
  }
  return value;
}

async function writePersonalClaimsFinalization(
  journal: PersonalClaimsFinalizationJournal,
): Promise<void> {
  const journalPath = path.join(
    path.resolve(journal.runtimeRoot),
    "personal-claims-finalization.json",
  );
  const temporaryPath = `${journalPath}.${randomMarkerToken()}.tmp`;
  try {
    await mkdir(path.dirname(journalPath), { mode: 0o700, recursive: true });
    const existing = await lstat(journalPath).catch((error: unknown) => {
      if (isMissing(error)) return null;
      throw error;
    });
    if (
      existing?.isSymbolicLink() ||
      (existing !== null && !existing.isFile())
    ) {
      throw codedPersonalError("restore_required");
    }
    const handle = await open(temporaryPath, "wx", 0o600);
    try {
      await handle.writeFile(`${canonicalPersonalJson(journal)}\n`, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporaryPath, journalPath);
  } catch (error) {
    await rm(temporaryPath, { force: true }).catch(() => undefined);
    if (isPersonalLifecycleError(error)) throw error;
    throw codedPersonalError("restore_required");
  }
}

async function removePersonalClaimsFinalization(
  runtimeRoot: string,
): Promise<void> {
  const journalPath = path.join(
    runtimeRoot,
    "personal-claims-finalization.json",
  );
  const stat = await lstat(journalPath).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (stat === null) return;
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw codedPersonalError("restore_required");
  }
  await rm(journalPath, { force: false });
}

function isPersonalClaimsFinalizationJournal(
  value: unknown,
): value is PersonalClaimsFinalizationJournal {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "afterWikiHash",
      "applyingOperation",
      "baselineClaimsHash",
      "bindingHash",
      "completedOperations",
      "currentClaimsHash",
      "expectedFinalClaimsHash",
      "generation",
      "operations",
      "reviewReceiptInputHash",
      "runId",
      "runtimeRoot",
      "status",
      "transactionId",
      "type",
      "version",
    ]) ||
    !isHash(value.afterWikiHash) ||
    (value.applyingOperation !== undefined &&
      (typeof value.applyingOperation !== "number" ||
        !Number.isSafeInteger(value.applyingOperation) ||
        value.applyingOperation < 0)) ||
    !isHash(value.baselineClaimsHash) ||
    !isHash(value.bindingHash) ||
    !isHash(value.currentClaimsHash) ||
    !isHash(value.expectedFinalClaimsHash) ||
    !isGeneration(value.generation) ||
    !isUuid(value.runId) ||
    typeof value.runtimeRoot !== "string" ||
    !path.isAbsolute(value.runtimeRoot) ||
    typeof value.reviewReceiptInputHash !== "string" ||
    !isHash(value.reviewReceiptInputHash) ||
    typeof value.transactionId !== "string" ||
    value.transactionId.length === 0 ||
    (value.status !== "prepared" && value.status !== "applying") ||
    value.type !== "selfopenwiki:personal-claims-finalization-v1" ||
    value.version !== 1 ||
    !Array.isArray(value.operations) ||
    !Array.isArray(value.completedOperations)
  ) {
    return false;
  }
  const operations = value.operations;
  if (!operations.every(isPersonalClaimsFinalizationOperation)) return false;
  const completed = value.completedOperations;
  if (
    !completed.every(
      (entry) =>
        Number.isSafeInteger(entry) && entry >= 0 && entry < operations.length,
    ) ||
    new Set(completed).size !== completed.length
  ) {
    return false;
  }
  if (
    value.applyingOperation !== undefined &&
    completed.includes(value.applyingOperation)
  ) {
    return false;
  }
  return true;
}

function isPersonalClaimsFinalizationOperation(
  value: unknown,
): value is PersonalClaimsFinalizationOperation {
  if (!isRecord(value) || typeof value.pagePath !== "string") return false;
  try {
    personalClaimsSidecarPath(value.pagePath);
  } catch {
    return false;
  }
  if (
    !isHashOrNull(value.expectedSidecarHash) ||
    (value.action !== "write" && value.action !== "delete")
  ) {
    return false;
  }
  if (value.action === "delete") {
    return (
      hasOnlyKeys(value, [
        "action",
        "afterClaimsHash",
        "desiredSidecarHash",
        "expectedSidecarHash",
        "pagePath",
      ]) &&
      isHash(value.afterClaimsHash) &&
      value.desiredSidecarHash === null
    );
  }
  return (
    hasOnlyKeys(value, [
      "action",
      "afterClaimsHash",
      "claims",
      "desiredSidecarHash",
      "desiredSidecarSize",
      "expectedSidecarHash",
      "pageHash",
      "pagePath",
    ]) &&
    Array.isArray(value.claims) &&
    isHash(value.afterClaimsHash) &&
    isHash(value.desiredSidecarHash) &&
    typeof value.desiredSidecarSize === "number" &&
    Number.isSafeInteger(value.desiredSidecarSize) &&
    value.desiredSidecarSize > 0 &&
    isHash(value.pageHash)
  );
}

function isHashOrNull(value: unknown): value is string | null {
  return value === null || isHash(value);
}

function sameRuntimePath(left: string, right: string): boolean {
  const normalize = (value: string) => path.normalize(path.resolve(value));
  return process.platform === "win32"
    ? normalize(left).toLowerCase() === normalize(right).toLowerCase()
    : normalize(left) === normalize(right);
}

type PersonalFinalizationMarker = {
  readonly afterWikiHash?: string;
  readonly bindingHash: string;
  readonly generation: 1 | 2 | 3;
  readonly reviewReceiptHash?: string;
  readonly reviewReceiptInputHash: string;
  readonly runId: string;
  readonly status: "prepared" | "published";
  readonly transactionId: string;
  readonly type: "selfopenwiki:personal-finalization-v1";
  readonly version: 1;
};

async function readPersonalFinalizationMarker(
  runtimeRoot: string,
): Promise<PersonalFinalizationMarker | null> {
  const markerPath = path.join(runtimeRoot, "personal-finalization.json");
  const stat = await lstat(markerPath).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw codedPersonalError("invalid_state");
  });
  if (stat === null) return null;
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw codedPersonalError("invalid_state");
  }
  let value: unknown;
  try {
    value = JSON.parse(await readFile(markerPath, "utf8"));
  } catch (error) {
    throw codedPersonalError("invalid_state");
  }
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "afterWikiHash",
      "bindingHash",
      "generation",
      "reviewReceiptHash",
      "reviewReceiptInputHash",
      "runId",
      "status",
      "transactionId",
      "type",
      "version",
    ]) ||
    value.type !== "selfopenwiki:personal-finalization-v1" ||
    value.version !== 1 ||
    !isUuid(value.runId) ||
    typeof value.transactionId !== "string" ||
    typeof value.bindingHash !== "string" ||
    typeof value.reviewReceiptInputHash !== "string" ||
    (value.status !== "prepared" && value.status !== "published") ||
    !isGeneration(value.generation) ||
    (value.afterWikiHash !== undefined && !isHash(value.afterWikiHash)) ||
    (value.reviewReceiptHash !== undefined && !isHash(value.reviewReceiptHash))
  ) {
    throw codedPersonalError("invalid_state");
  }
  return value as PersonalFinalizationMarker;
}

async function writePersonalFinalizationMarker(
  runtimeRoot: string,
  marker: PersonalFinalizationMarker,
): Promise<void> {
  const markerPath = path.join(runtimeRoot, "personal-finalization.json");
  const temporaryPath = `${markerPath}.${randomMarkerToken()}.tmp`;
  try {
    await mkdir(runtimeRoot, { mode: 0o700, recursive: true });
    const existing = await lstat(markerPath).catch((error: unknown) => {
      if (isMissing(error)) return null;
      throw error;
    });
    if (
      existing?.isSymbolicLink() ||
      (existing !== null && !existing.isFile())
    ) {
      throw codedPersonalError("invalid_state");
    }
    const handle = await open(temporaryPath, "wx", 0o600);
    try {
      await handle.writeFile(`${canonicalPersonalJson(marker)}\n`, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporaryPath, markerPath);
  } catch (error) {
    await rm(temporaryPath, { force: true }).catch(() => undefined);
    if (isPersonalLifecycleError(error)) throw error;
    throw codedPersonalError("invalid_state");
  }
}

async function removePersonalFinalizationMarker(
  runtimeRoot: string,
): Promise<void> {
  const markerPath = path.join(runtimeRoot, "personal-finalization.json");
  const stat = await lstat(markerPath).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (stat === null) return;
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw codedPersonalError("invalid_state");
  }
  await rm(markerPath, { force: false });
}

function randomMarkerToken(): string {
  return randomUUID();
}

function isPersonalLifecycleError(
  value: unknown,
): value is Error & { code: string } {
  return (
    value instanceof Error &&
    typeof (value as { code?: unknown }).code === "string"
  );
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  const allowed = new Set(keys);
  return Object.keys(value).every((key) => allowed.has(key));
}

function isHash(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[a-f0-9]{64}$/u.test(value);
}

function isGeneration(value: unknown): value is 1 | 2 | 3 {
  return value === 1 || value === 2 || value === 3;
}

function isUuid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(
      value,
    )
  );
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

function reconcilePersonalClaims(job: PersonalPageJob): readonly unknown[] {
  const current = job.issueClaims.map((claim) => clonePersonalClaim(claim));
  const byId = new Map<string, Record<string, unknown>>();
  for (const claim of current) {
    if (typeof claim.id === "string") byId.set(claim.id, claim);
  }
  const decisions = job.claimDecisions ?? [];
  for (const decision of decisions) {
    if (!isRecord(decision)) continue;
    const action = decision.action;
    const id = typeof decision.id === "string" ? decision.id : undefined;
    if (action === "confirm" && id !== undefined) continue;
    if (action === "retract" && id !== undefined) {
      byId.delete(id);
      continue;
    }
    if (action === "update" || action === "add" || "statement" in decision) {
      const candidate = clonePersonalClaim(decision);
      const candidateId =
        typeof candidate.id === "string" && candidate.id.length > 0
          ? candidate.id
          : `personal-claim-${personalHash({
              evidence: candidate.evidence,
              statement: candidate.statement,
            }).slice(7, 31)}`;
      byId.set(candidateId, { ...candidate, id: candidateId });
    }
  }
  return [...byId.values()].sort((left, right) =>
    String(left.id).localeCompare(String(right.id)),
  );
}

function clonePersonalClaim(value: unknown): Record<string, unknown> {
  if (!isRecord(value) || typeof value.statement !== "string") {
    throw codedPersonalError("validation_failed");
  }
  const evidence = Array.isArray(value.evidence)
    ? value.evidence.map((entry) => {
        if (!isRecord(entry) || typeof entry.resource !== "string") {
          throw codedPersonalError("validation_failed");
        }
        return { resource: entry.resource };
      })
    : [];
  return {
    ...(typeof value.id === "string" ? { id: value.id } : {}),
    evidence,
    statement: value.statement,
  };
}

function containedWikiPagePath(root: string, relativePath: string): string {
  const candidate = path.resolve(root, ...relativePath.split("/"));
  const relative = path.relative(path.resolve(root), candidate);
  if (
    relative === "" ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw codedPersonalError("validation_failed");
  }
  return candidate;
}

function personalBinding(
  runId: string,
  planHash: string,
  queueHash: string,
  candidate: PersonalCandidateBinding,
) {
  return {
    candidateBindingHash: candidate.candidateBindingHash,
    candidateRootHash: candidate.candidateRootHash,
    generation: candidate.generation,
    planHash,
    queueHash,
    runId,
    transactionId: candidate.transactionId,
    wikiRevision: candidate.wikiRevision,
  };
}

function codedPersonalError(
  code:
    | "capability_unverified"
    | "invalid_input"
    | "invalid_state"
    | "source_manifest_invalid"
    | "validation_failed"
    | "wiki_conflict"
    | "restore_required",
) {
  return Object.assign(new Error(code), { code });
}

export function personalHash(value: unknown): string {
  const hasher = createHash("sha256");
  hasher.update("selfopenwiki:personal-canonical-v1\0", "utf8");
  hasher.update(canonicalPersonalJson(value), "utf8");
  return `sha256:${hasher.digest("hex")}`;
}

export function canonicalPersonalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalPersonalJson).join(",")}]`;
  }
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map(
        (key) => `${JSON.stringify(key)}:${canonicalPersonalJson(record[key])}`,
      )
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function hashBytes(bytes: Uint8Array): string {
  const hasher = createHash("sha256");
  hasher.update(bytes);
  return `sha256:${hasher.digest("hex")}`;
}

function validatePersonalLanguage(
  language: string | undefined,
): string | undefined {
  if (language === undefined) return undefined;
  try {
    const [canonical] = Intl.getCanonicalLocales(language);
    const primary = new Intl.Locale(canonical).language;
    const displayName = new Intl.DisplayNames(["en"], {
      type: "language",
    }).of(primary);
    if (displayName && displayName.toLowerCase() !== primary.toLowerCase()) {
      return canonical;
    }
  } catch {
    // Fall through to the bounded protocol error below.
  }
  throw codedPersonalError("invalid_input");
}

function containedCandidatePath(root: string, relativePath: string): string {
  const candidate = path.resolve(root, ...relativePath.split("/"));
  const relative = path.relative(path.resolve(root), candidate);
  if (
    relative === "" ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw codedPersonalError("validation_failed");
  }
  return candidate;
}

async function assertCandidatePagePath(
  candidateRoot: string,
  pagePath: string,
): Promise<void> {
  const root = await realpath(candidateRoot).catch(() => {
    throw codedPersonalError("validation_failed");
  });
  const parent = await realpath(path.dirname(pagePath)).catch(() => {
    throw codedPersonalError("validation_failed");
  });
  if (!isContainedCanonicalPath(root, parent)) {
    throw codedPersonalError("validation_failed");
  }
  const target = await realpath(pagePath).catch(() => {
    throw codedPersonalError("validation_failed");
  });
  if (!isContainedCanonicalPath(root, target)) {
    throw codedPersonalError("validation_failed");
  }
}

async function readStableWikiPage(
  wikiRoot: string,
  pagePath: string,
): Promise<Buffer> {
  await assertCandidatePagePath(wikiRoot, pagePath);
  const before = await capturePathIdentity(wikiRoot, pagePath);
  const handle = await open(pagePath, "r").catch(() => {
    throw codedPersonalError("validation_failed");
  });
  try {
    const opened = await handle.stat();
    if (
      !opened.isFile() ||
      opened.isSymbolicLink() ||
      !sameFileIdentity(before.file, opened)
    ) {
      throw codedPersonalError("validation_failed");
    }
    const bytes = await handle.readFile();
    const after = await capturePathIdentity(wikiRoot, pagePath);
    if (
      !samePathIdentity(before, after) ||
      !sameFileIdentity(after.file, opened)
    ) {
      throw codedPersonalError("validation_failed");
    }
    return bytes;
  } catch (error) {
    if (error instanceof Error && "code" in error) throw error;
    throw codedPersonalError("validation_failed");
  } finally {
    await handle.close();
  }
}

type CandidatePathIdentity = {
  readonly file: Awaited<ReturnType<typeof lstat>>;
  readonly chain: readonly Awaited<ReturnType<typeof lstat>>[];
};

async function capturePathIdentity(
  candidateRoot: string,
  pagePath: string,
): Promise<CandidatePathIdentity> {
  const root = path.resolve(candidateRoot);
  const target = path.resolve(pagePath);
  const relative = path.relative(root, target);
  if (
    relative === "" ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw codedPersonalError("validation_failed");
  }
  const chain: Array<Awaited<ReturnType<typeof lstat>>> = [];
  let current = root;
  for (const segment of relative.split(path.sep)) {
    current = path.join(current, segment);
    const stat = await lstat(current).catch(() => {
      throw codedPersonalError("validation_failed");
    });
    if (stat.isSymbolicLink()) throw codedPersonalError("validation_failed");
    chain.push(stat);
  }
  const file = chain.at(-1);
  if (file === undefined || !file.isFile()) {
    throw codedPersonalError("validation_failed");
  }
  return { chain, file };
}

function samePathIdentity(
  left: CandidatePathIdentity,
  right: CandidatePathIdentity,
): boolean {
  return (
    left.chain.length === right.chain.length &&
    left.chain.every((stat, index) =>
      sameFileIdentity(stat, right.chain[index]!),
    )
  );
}

function sameFileIdentity(
  left: Awaited<ReturnType<typeof lstat>>,
  right: Awaited<ReturnType<typeof lstat>>,
): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.size === right.size &&
    left.mtimeMs === right.mtimeMs
  );
}

function isContainedCanonicalPath(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function validateClaimDecisions(
  job: PersonalPageJob,
  claims: readonly unknown[],
  sparseIds: readonly string[],
): void {
  const existingIds = new Set(
    job.issueClaims.flatMap((claim) =>
      isRecord(claim) && typeof claim.id === "string" ? [claim.id] : [],
    ),
  );
  if (new Set(sparseIds).size !== sparseIds.length) {
    throw codedPersonalError("invalid_input");
  }
  if (sparseIds.some((id) => !existingIds.has(id))) {
    throw codedPersonalError("invalid_input");
  }
  const proposedIds = new Set<string>();
  for (const claim of claims) {
    if (!isRecord(claim) || typeof claim.id !== "string") continue;
    if (!existingIds.has(claim.id) || proposedIds.has(claim.id)) {
      throw codedPersonalError("invalid_input");
    }
    proposedIds.add(claim.id);
  }
}

async function validatePersonalClaimEvidence(
  state: PersonalRunRecord,
  claims: readonly unknown[],
): Promise<void> {
  for (const claim of claims) {
    if (!isRecord(claim) || !Array.isArray(claim.evidence)) {
      throw codedPersonalError("invalid_input");
    }
    for (const evidence of claim.evidence) {
      if (!isRecord(evidence) || typeof evidence.resource !== "string") {
        throw codedPersonalError("invalid_input");
      }
      const resource = evidence.resource;
      const match = /^(repo|wiki):\/\/(.+)$/u.exec(resource);
      if (match === null || !isValidPersonalEvidenceResource(resource)) {
        throw codedPersonalError("invalid_input");
      }
      const reference = match[2]!.split("#", 1)[0]!;
      if (
        reference.length === 0 ||
        reference.includes("\\") ||
        reference.startsWith("/") ||
        path.posix.normalize(reference) !== reference ||
        reference
          .split("/")
          .some((segment) => segment === ".." || segment === "") ||
        reference.toLowerCase().includes(".git") ||
        reference.startsWith(".claims/")
      ) {
        throw codedPersonalError("validation_failed");
      }
      if (match[1] === "repo") {
        if (
          state.sourceManifestId === undefined ||
          state.sourceConfirmation === undefined
        ) {
          throw codedPersonalError("source_manifest_invalid");
        }
        continue;
      }
      const page = path.resolve(state.wikiRoot, ...reference.split("/"));
      const relative = path.relative(path.resolve(state.wikiRoot), page);
      if (
        relative === "" ||
        relative.startsWith(`..${path.sep}`) ||
        path.isAbsolute(relative)
      ) {
        throw codedPersonalError("validation_failed");
      }
      const stat = await lstat(page).catch(() => null);
      if (stat === null || stat.isSymbolicLink() || !stat.isFile()) {
        throw codedPersonalError("validation_failed");
      }
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function reconcileCandidateRecovery(
  state: PersonalRunRecord,
  store: Pick<PersonalRunStore, "acceptPage" | "readJob">,
): Promise<void> {
  if (state.candidate === undefined || state.jobs === undefined) return;
  const markerRoot = path.join(state.runtimeRoot, "page-markers", state.runId);
  let entries;
  try {
    entries = await readdir(markerRoot, { withFileTypes: true });
  } catch (error) {
    if (
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === "ENOENT" &&
      state.jobs.every((job) => job.status !== "accepted")
    ) {
      return;
    }
    throw codedPersonalError("restore_required");
  }
  const markerJobs = new Set<string>();
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
    const marker = await readPersonalCandidateMarker(
      path.join(markerRoot, entry.name),
    ).catch(() => {
      throw codedPersonalError("restore_required");
    });
    if (marker === null) throw codedPersonalError("restore_required");
    const job = state.jobs.find(
      (candidate) => candidate.jobId === marker.jobId,
    );
    if (
      job === undefined ||
      job.path !== marker.pagePath ||
      marker.runId !== state.runId ||
      marker.generation !== state.candidate.generation ||
      marker.transactionId !== state.candidate.transactionId ||
      marker.candidateBindingHash !== state.candidate.candidateBindingHash ||
      marker.candidateRoot !== state.candidate.candidateRoot ||
      marker.pagePathHash !== personalHash(marker.pagePath)
    ) {
      throw codedPersonalError("restore_required");
    }
    markerJobs.add(marker.jobId);
    if (
      job.pageContentHash !== undefined &&
      job.pageContentHash !== marker.pageContentHash
    ) {
      throw codedPersonalError("restore_required");
    }
    if (
      job.claimDecisionHash !== undefined &&
      job.claimDecisionHash !== marker.claimDecisionHash
    ) {
      throw codedPersonalError("restore_required");
    }
    if (marker.state === "candidate_written") {
      if (job.status !== "assigned" && job.status !== "accepted") {
        throw codedPersonalError("restore_required");
      }
      if (job.status === "assigned") {
        await store.acceptPage!({
          claimDecisionHash: marker.claimDecisionHash,
          jobId: marker.jobId,
          pageContentHash: marker.pageContentHash,
          runId: marker.runId,
        });
      }
      await transitionPersonalCandidateMarker(
        path.join(markerRoot, entry.name),
        "accepted",
        new Date().toISOString(),
      );
    } else if (job.status !== "accepted") {
      throw codedPersonalError("restore_required");
    }
  }
  if (
    state.jobs.some(
      (job) => job.status === "accepted" && !markerJobs.has(job.jobId),
    )
  ) {
    throw codedPersonalError("restore_required");
  }
}

function validateOkfPage(bytes: Uint8Array): void {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw codedPersonalError("validation_failed");
  }
  if (text.includes("\u0000")) throw codedPersonalError("validation_failed");
  const lines = text.split(/\r?\n/u);
  if (lines[0] !== "---") throw codedPersonalError("validation_failed");
  const end = lines.findIndex((line, index) => index > 0 && line === "---");
  if (end < 0) throw codedPersonalError("validation_failed");
  const document = parseDocument(lines.slice(1, end).join("\n"), {
    strict: true,
  });
  if (document.errors.length > 0) throw codedPersonalError("validation_failed");
  const fields = document.toJS() as unknown;
  if (fields === null || typeof fields !== "object" || Array.isArray(fields)) {
    throw codedPersonalError("validation_failed");
  }
  const record = fields as Record<string, unknown>;
  for (const key of ["type", "title", "description"]) {
    if (
      key in record &&
      (typeof record[key] !== "string" || record[key].trim() === "")
    ) {
      throw codedPersonalError("validation_failed");
    }
  }
  if (typeof record.type !== "string" || record.type.trim() === "") {
    throw codedPersonalError("validation_failed");
  }
  if (
    "tags" in record &&
    (!Array.isArray(record.tags) ||
      record.tags.some((tag) => typeof tag !== "string" || tag.trim() === ""))
  ) {
    throw codedPersonalError("validation_failed");
  }
  if (
    "status" in record &&
    !["draft", "stable", "provisional", "deprecated"].includes(String(record.status))
  ) {
    throw codedPersonalError("validation_failed");
  }
  if ("sources" in record && !Array.isArray(record.sources)) {
    throw codedPersonalError("validation_failed");
  }
}

async function snapshotPersonalCandidate(root: string): Promise<string> {
  try {
    return (await snapshotMarkdownTree(root)).rootHash;
  } catch (error) {
    if (error instanceof C7SnapshotError) {
      throw codedPersonalError("validation_failed");
    }
    throw error;
  }
}
