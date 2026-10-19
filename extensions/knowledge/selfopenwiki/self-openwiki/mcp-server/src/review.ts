import { readFile } from "node:fs/promises";
import path from "node:path";
import type { ResultFailureStage } from "./contracts.js";
import type {
  ModelSelection,
  ModelVerificationEvidence,
} from "./model-verification.js";
import { C7ProcessError } from "./process.js";
import {
  C7RunResultError,
  parseReviewModelResult,
  readModelResultJson,
  REVIEW_RESULT_CONTRACT,
  type ReviewModelResult,
} from "./run-result.js";
import { assertMarkdownTreeVersion, snapshotMarkdownTree } from "./snapshot.js";
import type { SelectedC7Skills } from "./skills.js";
import type { C7TransactionFactory } from "./transaction.js";
import type { UpdateProcessRunner } from "./update.js";

export class C7ReviewError extends Error {
  constructor(
    readonly code: "review_failed",
    message: string,
    readonly failureStage?: ResultFailureStage,
  ) {
    super(message);
    this.name = "C7ReviewError";
  }
}

export class OpenWikiReviewService {
  private readonly formalWikiPath: string;
  private readonly processRunner: UpdateProcessRunner;
  private readonly transactions: C7TransactionFactory;
  private readonly waitBeforeRetry: (
    milliseconds: number,
    signal?: AbortSignal,
  ) => Promise<void>;

  constructor(options: {
    formalWikiPath: string;
    processRunner: UpdateProcessRunner;
    transactions: C7TransactionFactory;
    waitBeforeRetry?(milliseconds: number, signal?: AbortSignal): Promise<void>;
  }) {
    if (!path.isAbsolute(options.formalWikiPath)) {
      throw new C7ReviewError(
        "review_failed",
        "The review Wiki path is invalid.",
      );
    }
    this.formalWikiPath = options.formalWikiPath;
    this.processRunner = options.processRunner;
    this.transactions = options.transactions;
    this.waitBeforeRetry = options.waitBeforeRetry ?? waitForRetry;
  }

  async review(input: {
    candidateId: string;
    instruction: string;
    model: ModelVerificationEvidence;
    reviewedRootHash: string;
    reviewWikiPath?: string;
    selectedSkills: SelectedC7Skills;
    selection: ModelSelection;
    sourceManifestHash: string | null;
    sourceSnapshot?: {
      manifestHash: string;
      snapshotPath: string;
      snapshotTreeHash: string;
    };
    signal?: AbortSignal;
  }): Promise<ReviewModelResult & { model: ModelVerificationEvidence }> {
    const reviewBinding = {
      candidateId: input.candidateId,
      model: input.selection,
      reviewedRootHash: input.reviewedRootHash,
      skillAggregateHash: input.selectedSkills.aggregateHash,
      sourceManifestHash: input.sourceManifestHash,
      version: 1 as const,
    };
    assertExactModel(input.selection, input.model);
    const formalBefore = await snapshotMarkdownTree(this.formalWikiPath);
    const reviewWikiPath = input.reviewWikiPath ?? this.formalWikiPath;
    const candidateBefore = await snapshotMarkdownTree(reviewWikiPath);
    if (candidateBefore.rootHash !== input.reviewedRootHash) {
      throw reviewFailed();
    }

    let workspace:
      | Awaited<ReturnType<C7TransactionFactory["create"]>>
      | undefined;
    let result:
      | (ReviewModelResult & { model: ModelVerificationEvidence })
      | undefined;
    let failure: unknown;
    try {
      let processResult;
      for (let attempt = 0; ; attempt += 1) {
        workspace = await this.transactions.create({
          baseWiki: {
            path: reviewWikiPath,
            rootHash: input.reviewedRootHash,
          },
          operation: "review",
          requestMarkdown: renderReviewRequest(
            input.instruction,
            input.reviewWikiPath === undefined
              ? "published_recovery"
              : "candidate",
          ),
          reviewBinding,
          selection: input.selection,
          skills: input.selectedSkills,
          ...(input.sourceSnapshot
            ? { sourceSnapshot: input.sourceSnapshot }
            : {}),
        });
        await workspace.transitionStage("running");
        try {
          processResult = await this.processRunner.run({
            cwd: workspace.homePath,
            openWikiHome: workspace.homePath,
            operation: "review",
            policyPath: workspace.policyPath,
            selection: input.selection,
            signal: input.signal,
          });
          break;
        } catch (error) {
          if (!isTransientProviderFailure(error) || attempt >= 2) throw error;
          await workspace.transitionStage("failed");
          await workspace.finalizeCredentials();
          await workspace.cleanup();
          workspace = undefined;
          await this.waitBeforeRetry(
            retryDelayMilliseconds(error, attempt),
            input.signal,
          );
          await assertMarkdownTreeVersion(this.formalWikiPath, formalBefore);
          await assertMarkdownTreeVersion(reviewWikiPath, candidateBefore);
        }
      }
      assertExactModel(input.selection, processResult.model);
      await workspace.transitionStage("model_complete");
      await assertMarkdownTreeVersion(this.formalWikiPath, formalBefore);
      await assertMarkdownTreeVersion(reviewWikiPath, candidateBefore);
      const transactionBinding = (await readJson(
        path.join(workspace.homePath, "_c7-control", "in", "binding.json"),
      )) as { review?: unknown };
      const parsed = await this.readReviewResult({
        binding: transactionBinding.review,
        selection: input.selection,
        signal: input.signal,
        workspace,
      });
      result = { ...parsed, model: processResult.model };
      await workspace.transitionStage("completed");
    } catch (error) {
      failure = error;
      await workspace?.transitionStage("failed").catch(() => undefined);
    }

    if (workspace !== undefined) {
      try {
        await workspace.finalizeCredentials();
        await workspace.cleanup();
      } catch (error) {
        failure ??= error;
      }
    }
    if (failure instanceof C7ReviewError) throw failure;
    if (failure instanceof C7ProcessError) throw failure;
    if (failure instanceof C7RunResultError) {
      throw reviewFailed(failure.failureStage);
    }
    if (failure !== undefined || result === undefined) throw reviewFailed();
    return result;
  }

  private async readReviewResult(input: {
    binding: unknown;
    selection: ModelSelection;
    signal?: AbortSignal;
    workspace: Awaited<ReturnType<C7TransactionFactory["create"]>>;
  }): Promise<ReviewModelResult> {
    const resultPath = path.join(
      input.workspace.homePath,
      "_c7-control",
      "out",
      "result.json",
    );
    try {
      return parseReviewModelResult(
        await readModelResultJson(resultPath),
        input.binding,
      );
    } catch (error) {
      if (
        !(error instanceof C7RunResultError) ||
        error.failureStage === "result_binding_mismatch" ||
        input.workspace.resultFinalizer === null
      ) {
        throw error;
      }
    }

    const candidateBefore = await snapshotMarkdownTree(
      input.workspace.wikiPath,
    );
    const processResult = await this.processRunner.run({
      cwd: input.workspace.homePath,
      openWikiHome: input.workspace.homePath,
      operation: "query",
      policyPath: input.workspace.resultFinalizer.policyPath,
      requestFileName: input.workspace.resultFinalizer.requestFileName,
      selection: input.selection,
      signal: input.signal,
    });
    assertExactModel(input.selection, processResult.model);
    await assertMarkdownTreeVersion(input.workspace.wikiPath, candidateBefore);
    return parseReviewModelResult(
      await readModelResultJson(resultPath),
      input.binding,
    );
  }
}

function renderReviewRequest(
  instruction: string,
  context: "candidate" | "published_recovery",
): string {
  const targetDescription =
    context === "candidate"
      ? "the unpublished Wiki candidate against the original confirmed task, current candidate, confirmed source snapshot, and exact C7 Skill contract"
      : "the already-published exact-root recovery target against the original confirmed task, current Wiki, confirmed source snapshot, and exact C7 Skill contract";
  return [
    "# C7 independent read-only review",
    `Review ${targetDescription}. Do not treat Review as activation authority or as permission to change the target.`,
    "The Wiki and sources are read-only. Write only /_c7-control/out/result.json.",
    REVIEW_RESULT_CONTRACT,
    "## Original confirmed instruction",
    instruction,
  ].join("\n\n");
}

async function readJson(filePath: string): Promise<unknown> {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    throw reviewFailed();
  }
}

function assertExactModel(
  selection: ModelSelection,
  evidence: ModelVerificationEvidence,
): void {
  if (
    evidence.providerAccepted !== true ||
    evidence.requested.model !== selection.model ||
    evidence.requested.reasoningEffort !== selection.reasoningEffort ||
    evidence.sent.model !== selection.model ||
    evidence.sent.reasoningEffort !== selection.reasoningEffort
  ) {
    throw reviewFailed();
  }
}

function reviewFailed(failureStage?: ResultFailureStage): C7ReviewError {
  return new C7ReviewError(
    "review_failed",
    "The independent Wiki review did not complete with an exact bound result.",
    failureStage,
  );
}

function isTransientProviderFailure(
  error: unknown,
): error is C7ProcessError & { code: "provider_transient" } {
  return error instanceof C7ProcessError && error.code === "provider_transient";
}

function retryDelayMilliseconds(
  error: C7ProcessError,
  attempt: number,
): number {
  return Math.min(
    30_000,
    error.retryAfterMs ?? Math.min(2_000, 250 * 2 ** attempt),
  );
}

async function waitForRetry(
  milliseconds: number,
  signal?: AbortSignal,
): Promise<void> {
  if (signal?.aborted) {
    throw new C7ProcessError("aborted", "The OpenWiki process was cancelled.");
  }
  await new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(
        new C7ProcessError("aborted", "The OpenWiki process was cancelled."),
      );
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    signal?.addEventListener("abort", abort, { once: true });
  });
}
