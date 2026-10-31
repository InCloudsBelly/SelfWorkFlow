import { createHash } from "node:crypto";
import { lstat, realpath } from "node:fs/promises";
import path from "node:path";
import {
  canonicalPersonalJson,
  personalHash,
} from "./personal-wiki-lifecycle.js";
import type {
  PersonalCandidateBinding,
  PersonalC7Gateway,
  PersonalReviewPreparationResult,
  PersonalReviewSubmissionResult,
  PersonalWikiLifecycle,
} from "./personal-wiki-lifecycle.js";
import type { PersonalPagePlan } from "./personal-run-store.js";
import { readMarkdownPages, snapshotMarkdownTree } from "./snapshot.js";
import { canConnectWikiPlan } from "./validation.js";

export const OFFICIAL_PERSONAL_LIFECYCLE_TOOLS = [
  "openwiki_begin",
  "openwiki_submit_plan",
  "openwiki_next_page",
  "openwiki_inspect_page_claims",
  "openwiki_submit_page",
  "openwiki_finish",
] as const;

type PersonalLifecycleOwner = Pick<
  PersonalWikiLifecycle,
  | "begin"
  | "finish"
  | "inspectPageClaims"
  | "nextPage"
  | "submitPage"
  | "submitPlan"
>;

export class OfficialLifecycleAdapter {
  constructor(private readonly owner: PersonalLifecycleOwner) {}

  begin(input: unknown): Promise<unknown> {
    return this.owner.begin(input);
  }

  submitPlan(input: unknown): Promise<unknown> {
    return this.owner.submitPlan(input);
  }

  nextPage(input: unknown): Promise<unknown> {
    return this.owner.nextPage(input);
  }

  inspectPageClaims(input: unknown): Promise<unknown> {
    return this.owner.inspectPageClaims(input);
  }

  submitPage(input: unknown): Promise<unknown> {
    return this.owner.submitPage(input);
  }

  finish(input: unknown): Promise<unknown> {
    return this.owner.finish(input);
  }
}

type ExternalUpdatePort = {
  begin(input: unknown): Promise<unknown>;
  finalize(input: unknown): Promise<unknown>;
  recoverStartup?(): Promise<unknown>;
  status?(): Promise<{ readonly transactionId: string } | null>;
  recoverUncommittedStart?(
    input: unknown,
    verifyUnboundStart: () => Promise<boolean>,
  ): Promise<void>;
};

export class C7PersonalGateway implements PersonalC7Gateway {
  private readonly externalUpdate: ExternalUpdatePort;
  private readonly createExternalUpdate:
    | ((wikiRoot: string, runtimeRoot: string) => ExternalUpdatePort)
    | undefined;
  private readonly runServices = new Map<string, ExternalUpdatePort>();

  constructor(options: {
    createExternalUpdate?(
      wikiRoot: string,
      runtimeRoot: string,
    ): ExternalUpdatePort;
    externalUpdate: ExternalUpdatePort;
  }) {
    this.externalUpdate = options.externalUpdate;
    this.createExternalUpdate = options.createExternalUpdate;
  }

  async start(input: {
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
    readonly verifyUnboundStart?: () => Promise<boolean>;
  }): Promise<PersonalCandidateBinding> {
    const confirmedWikiPaths = [
      ...input.pages.map((page) => page.path),
      ...(input.deletePages ?? []),
    ];
    if (confirmedWikiPaths.length === 0) {
      throw codedGatewayError("invalid_input");
    }
    const service = this.serviceFor(
      input.runId,
      input.wikiRoot,
      `${input.wikiRoot}.selfopenwiki`,
    );
    const request = {
      action: "start" as const,
      confirmedByUser: input.confirmedByUser,
      confirmedWikiPaths,
      expectedWikiRevision: input.markdownWikiRevision ?? input.wikiRevision,
      instruction: "Run the adapted personal OpenWiki page lifecycle.",
      materials: [
        {
          content: canonicalPersonalJson({
            protocol: "selfopenwiki:personal-c7-binding-v1",
            claimBindings: input.pages.map((page) => ({
              claimsHash: personalHash(page.issueClaims ?? []),
              path: page.path,
            })),
            requestedSkills: input.requestedSkills ?? [],
            compatibilityManifestHash: input.compatibilityManifestHash ?? null,
            skillAggregateHash: input.skillAggregateHash,
            sourceConfirmationHash:
              input.sourceConfirmation === undefined
                ? null
                : hashCanonical(input.sourceConfirmation),
            sourceManifestId: input.sourceManifestId ?? null,
          }),
          id: "selfopenwiki-personal-adapter-binding",
          source: "self-openwiki",
        },
      ],
      requestId: input.runId,
      ...(input.sourceManifestId === undefined ||
      input.sourceConfirmation === undefined
        ? {}
        : {
            sourceConfirmation: input.sourceConfirmation,
            sourceManifestId: input.sourceManifestId,
          }),
    };
    try {
      await recoverPersonalExternalService(service);
    } catch (error) {
      if (
        error === null ||
        typeof error !== "object" ||
        !("code" in error) ||
        error.code !== "restore_required" ||
        !input.verifyUnboundStart ||
        !service.recoverUncommittedStart
      )
        throw error;
      await service.recoverUncommittedStart(request, input.verifyUnboundStart);
      await recoverPersonalExternalService(service);
    }
    // Issued bindings and terminal replay retain the original recovery path.
    if ((await service.status?.()) == null)
      await assertPersonalPlanNavigation(input);
    const output = await service.begin(request);
    try {
      return await this.candidateFromOutput(
        output,
        path.resolve(`${input.wikiRoot}.selfopenwiki`),
      );
    } catch (error) {
      await abortMalformedCandidate(service, output);
      throw error;
    }
  }

  async resumeRepair(input: {
    readonly bindingHash: string;
    readonly runId: string;
    readonly runtimeRoot?: string;
    readonly transactionId: string;
    readonly wikiRoot?: string;
  }): Promise<PersonalCandidateBinding> {
    const service = this.serviceFor(
      input.runId,
      input.wikiRoot,
      input.runtimeRoot,
    );
    await recoverPersonalExternalService(service);
    const output = await service.begin({
      action: "resume",
      bindingHash: input.bindingHash,
      transactionId: input.transactionId,
    });
    if (input.runtimeRoot === undefined) {
      throw codedGatewayError("upstream_incompatible");
    }
    return this.candidateFromOutput(output, path.resolve(input.runtimeRoot));
  }

  async recoverRepair(input: {
    readonly candidate: PersonalCandidateBinding;
    readonly runId: string;
    readonly runtimeRoot: string;
    readonly wikiRoot: string;
  }): Promise<PersonalCandidateBinding | null> {
    const service = this.serviceFor(
      input.runId,
      input.wikiRoot,
      input.runtimeRoot,
    );
    await recoverPersonalExternalService(service);
    // The C7 owner alone verifies its persisted predecessor/successor relation.
    const output = await service.begin({
      action: "resume",
      bindingHash: input.candidate.candidateBindingHash,
      transactionId: input.candidate.transactionId,
    });
    if (!isRecord(output) || output.ok !== true)
      throw codedGatewayError("upstream_incompatible");
    if (
      [
        "external_review_resumed",
        "needs_clarification",
        "published",
        "published_with_follow_up",
      ].includes(String(output.status))
    )
      return null;
    if (
      output.status !== "external_update_resumed" ||
      !isRecord(output.workPackage)
    )
      throw codedGatewayError("upstream_incompatible");
    const work = output.workPackage;
    if (
      work.transactionId !== input.candidate.transactionId ||
      work.beforeWikiRevision !== input.candidate.wikiRevision
    )
      throw codedGatewayError("restore_required");
    if (
      work.generation === input.candidate.generation &&
      work.bindingHash === input.candidate.candidateBindingHash
    )
      return null;
    if (
      work.generation !== input.candidate.generation + 1 ||
      work.bindingHash === input.candidate.candidateBindingHash
    )
      throw codedGatewayError("restore_required");
    return this.candidateFromOutput(output, path.resolve(input.runtimeRoot));
  }

  private async candidateFromOutput(
    output: unknown,
    expectedRuntimeRoot: string,
  ): Promise<PersonalCandidateBinding> {
    if (
      !isRecord(output) ||
      output.ok !== true ||
      !isRecord(output.workPackage) ||
      typeof output.status !== "string"
    ) {
      throw codedGatewayError("upstream_incompatible");
    }
    const workPackage = output.workPackage;
    const candidate = isRecord(workPackage.candidate)
      ? workPackage.candidate
      : undefined;
    if (
      typeof workPackage.transactionId !== "string" ||
      !isGeneration(workPackage.generation) ||
      typeof workPackage.bindingHash !== "string" ||
      typeof workPackage.beforeWikiRevision !== "string" ||
      candidate === undefined ||
      typeof candidate.rootPath !== "string" ||
      !isHash(workPackage.bindingHash) ||
      !isHash(workPackage.beforeWikiRevision) ||
      !pathIsAbsolute(candidate.rootPath)
    ) {
      throw codedGatewayError("upstream_incompatible");
    }
    const canonicalCandidateRoot = await assertPersonalCandidateRoot(
      candidate.rootPath,
      expectedRuntimeRoot,
    ).catch(() => {
      throw codedGatewayError("upstream_incompatible");
    });
    const candidateRootHash = await snapshotMarkdownTree(canonicalCandidateRoot)
      .then((snapshot) => snapshot.rootHash)
      .catch(() => {
        throw codedGatewayError("upstream_incompatible");
      });
    return {
      candidateBindingHash: workPackage.bindingHash,
      candidateRoot: canonicalCandidateRoot,
      candidateRootHash,
      generation: workPackage.generation,
      transactionId: workPackage.transactionId,
      wikiRevision: workPackage.beforeWikiRevision,
    };
  }

  async prepareReview(input: {
    readonly candidateReceipt: unknown;
    readonly runId: string;
    readonly runtimeRoot?: string;
    readonly wikiRoot?: string;
  }): Promise<PersonalReviewPreparationResult> {
    if (!isRecord(input.candidateReceipt)) {
      throw codedGatewayError("invalid_input");
    }
    const receipt = input.candidateReceipt;
    const output = await this.serviceFor(
      input.runId,
      input.wikiRoot,
      input.runtimeRoot,
    ).finalize({
      action: "prepare_review",
      bindingHash: receipt.bindingHash,
      candidateReceipt: receipt,
      transactionId: receipt.transactionId,
    });
    if (
      isRecord(output) &&
      (output.status === "external_review_ready" ||
        output.status === "external_review_resumed") &&
      typeof output.reviewPackageHash === "string" &&
      typeof output.candidateReceiptHash === "string" &&
      typeof output.candidateRootHash === "string" &&
      "reviewPackage" in output
    ) {
      return {
        candidateReceiptHash: output.candidateReceiptHash,
        candidateRootHash: output.candidateRootHash,
        kind: "review_ready",
        reviewPackage: output.reviewPackage,
        reviewPackageHash: output.reviewPackageHash,
      };
    }
    if (
      isRecord(output) &&
      output.status === "needs_clarification" &&
      Array.isArray(output.issues) &&
      Array.isArray(output.questions)
    ) {
      return {
        kind: "needs_clarification",
        issues: output.issues,
        questions: output.questions.filter(
          (question): question is string => typeof question === "string",
        ),
      };
    }
    throw codedGatewayError("upstream_incompatible");
  }

  async readCompletion(input: {
    readonly candidate: PersonalCandidateBinding;
    readonly expectedAfterWikiHash: string;
    readonly reviewReceipt?: unknown;
    readonly runId: string;
    readonly runtimeRoot: string;
    readonly wikiRoot: string;
  }): Promise<Extract<PersonalReviewSubmissionResult, { kind: "complete" }>> {
    const service = this.serviceFor(
      input.runId,
      input.wikiRoot,
      input.runtimeRoot,
    );
    const output =
      input.reviewReceipt === undefined
        ? await service.begin({
            action: "resume",
            bindingHash: input.candidate.candidateBindingHash,
            transactionId: input.candidate.transactionId,
          })
        : await service.finalize({
            action: "submit_review",
            bindingHash: input.candidate.candidateBindingHash,
            transactionId: input.candidate.transactionId,
            reviewReceipt: input.reviewReceipt,
          });
    if (
      !isRecord(output) ||
      output.ok !== true ||
      output.published !== true ||
      (output.status !== "published" &&
        output.status !== "published_with_follow_up") ||
      output.transactionId !== input.candidate.transactionId ||
      output.generation !== input.candidate.generation ||
      output.bindingHash !== input.candidate.candidateBindingHash ||
      output.wikiRevision !== input.expectedAfterWikiHash ||
      output.candidateRootHash !== input.expectedAfterWikiHash ||
      typeof output.reviewReceiptHash !== "string"
    ) {
      throw codedGatewayError("restore_required");
    }
    return {
      kind: "complete",
      beforeWikiHash: input.candidate.wikiRevision,
      afterWikiHash: input.expectedAfterWikiHash,
      reviewReceiptHash: output.reviewReceiptHash,
      runReceiptHash: hashCanonical(output),
      wikiRevision: output.wikiRevision,
      ...(Array.isArray(output.followUp) ? { followUp: output.followUp } : {}),
    };
  }

  async submitReview(input: {
    readonly beforeWikiHash?: string;
    readonly reviewReceipt: unknown;
    readonly runId: string;
    readonly runtimeRoot?: string;
    readonly wikiRoot?: string;
  }): Promise<PersonalReviewSubmissionResult> {
    if (!isRecord(input.reviewReceipt)) {
      throw codedGatewayError("invalid_input");
    }
    const receipt = input.reviewReceipt;
    const output = await this.serviceFor(
      input.runId,
      input.wikiRoot,
      input.runtimeRoot,
    ).finalize({
      action: "submit_review",
      bindingHash: receipt.bindingHash,
      reviewReceipt: receipt,
      transactionId: receipt.transactionId,
    });
    if (
      isRecord(output) &&
      (output.status === "published" ||
        output.status === "published_with_follow_up") &&
      typeof output.wikiRevision === "string" &&
      typeof output.reviewReceiptHash === "string"
    ) {
      return {
        afterWikiHash: output.wikiRevision,
        beforeWikiHash: input.beforeWikiHash ?? output.candidateRootHash,
        kind: "complete",
        ...(output.status === "published_with_follow_up" &&
        Array.isArray(output.followUp)
          ? { followUp: output.followUp }
          : {}),
        reviewReceiptHash: output.reviewReceiptHash,
        runReceiptHash: hashCanonical(output),
        wikiRevision: output.wikiRevision,
      };
    }
    if (
      isRecord(output) &&
      output.status === "repair_ready" &&
      Array.isArray(output.issues)
    ) {
      return { kind: "repair_ready", issues: output.issues };
    }
    if (
      isRecord(output) &&
      output.status === "needs_clarification" &&
      Array.isArray(output.issues) &&
      Array.isArray(output.questions)
    ) {
      return {
        kind: "needs_clarification",
        issues: output.issues,
        questions: output.questions.filter(
          (question): question is string => typeof question === "string",
        ),
      };
    }
    throw codedGatewayError("upstream_incompatible");
  }

  private serviceFor(
    runId: string,
    wikiRoot?: string,
    runtimeRoot?: string,
  ): ExternalUpdatePort {
    const existing = this.runServices.get(runId);
    if (existing !== undefined) return existing;
    if (
      this.createExternalUpdate !== undefined &&
      wikiRoot !== undefined &&
      runtimeRoot !== undefined
    ) {
      const service = this.createExternalUpdate(wikiRoot, runtimeRoot);
      this.runServices.set(runId, service);
      return service;
    }
    return this.externalUpdate;
  }
}

function hashCanonical(value: unknown): string {
  const hasher = createHash("sha256");
  hasher.update("selfopenwiki:personal-c7-receipt-v1\0", "utf8");
  hasher.update(canonicalPersonalJson(value), "utf8");
  return `sha256:${hasher.digest("hex")}`;
}

async function assertPersonalPlanNavigation(
  input: Parameters<PersonalC7Gateway["start"]>[0],
): Promise<void> {
  const snapshot = await snapshotMarkdownTree(input.wikiRoot);
  const existingPaths = new Set(
    snapshot.files.map((file) => file.relativePath),
  );
  const plannedPaths = new Set(input.pages.map((page) => page.path));
  if (![...plannedPaths].some((page) => !existingPaths.has(page))) return;
  const deletedPaths = new Set(input.deletePages ?? []);
  const current = await readMarkdownPages(
    input.wikiRoot,
    [...existingPaths].filter(
      (page) => !plannedPaths.has(page) && !deletedPaths.has(page),
    ),
    input.markdownWikiRevision ?? input.wikiRevision,
    { maxFileBytes: 2 * 1024 * 1024, maxTotalBytes: 50 * 1024 * 1024 },
  );
  const contents = new Map(
    current.knowledge.map((page) => [
      page.sourceId.slice("selfopenwiki:".length),
      page.content,
    ]),
  );
  if (
    !canConnectWikiPlan(
      contents,
      existingPaths,
      plannedPaths,
      input.deletePages ?? [],
    )
  ) {
    throw new C7PersonalGatewayError(
      "invalid_input",
      "The new pages cannot be reached from quickstart.md within this plan. Include quickstart.md or a reachable topic index in pages, then resubmit the plan in the same run; no candidate has been created.",
    );
  }
}

class C7PersonalGatewayError extends Error {
  constructor(
    readonly code:
      | "invalid_input"
      | "restore_required"
      | "upstream_incompatible",
    message: string,
  ) {
    super(message);
    this.name = "C7PersonalGatewayError";
  }
}

function codedGatewayError(
  code: "invalid_input" | "restore_required" | "upstream_incompatible",
): C7PersonalGatewayError {
  return new C7PersonalGatewayError(
    code,
    `C7 personal gateway failed: ${code}.`,
  );
}

async function recoverPersonalExternalService(
  service: ExternalUpdatePort,
): Promise<void> {
  if (service.recoverStartup === undefined) return;
  const result = await service.recoverStartup();
  if (
    isRecord(result) &&
    result.status === "external_startup_restore_required"
  ) {
    throw codedGatewayError("restore_required");
  }
}

function isHash(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[a-f0-9]{64}$/u.test(value);
}

function isGeneration(value: unknown): value is 1 | 2 | 3 {
  return value === 1 || value === 2 || value === 3;
}

function pathIsAbsolute(value: string): boolean {
  return /^[A-Za-z]:[\\/]/u.test(value) || value.startsWith("\\\\");
}

async function assertPersonalCandidateRoot(
  candidateRoot: string,
  expectedRuntimeRoot: string,
): Promise<string> {
  if (!pathIsAbsolute(candidateRoot) || !pathIsAbsolute(expectedRuntimeRoot)) {
    throw new Error("Candidate and runtime roots must be absolute.");
  }
  const candidateStat = await lstat(candidateRoot);
  if (candidateStat.isSymbolicLink() || !candidateStat.isDirectory()) {
    throw new Error("The C7 candidate root must be a real directory.");
  }
  const canonicalCandidate = await realpath(candidateRoot);
  const canonicalRuntime = await realpath(expectedRuntimeRoot).catch(() =>
    path.resolve(expectedRuntimeRoot),
  );
  const relative = path.relative(canonicalRuntime, canonicalCandidate);
  if (
    relative === "" ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new Error("The C7 candidate root is outside the personal runtime.");
  }
  let current = path.parse(canonicalCandidate).root;
  for (const segment of path
    .relative(current, canonicalCandidate)
    .split(path.sep)
    .filter(Boolean)) {
    current = path.join(current, segment);
    if ((await lstat(current)).isSymbolicLink()) {
      throw new Error("The C7 candidate root contains a link or junction.");
    }
  }
  return canonicalCandidate;
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null;
}

async function abortMalformedCandidate(
  service: ExternalUpdatePort,
  output: unknown,
): Promise<void> {
  if (typeof service.finalize !== "function") return;
  if (!isRecord(output) || !isRecord(output.workPackage)) return;
  const transactionId = output.workPackage.transactionId;
  const bindingHash = output.workPackage.bindingHash;
  if (typeof transactionId !== "string" || !isHash(bindingHash)) {
    return;
  }
  await service
    .finalize({
      action: "abort",
      bindingHash,
      confirmedByUser: true,
      transactionId,
    })
    .catch(() => undefined);
}
