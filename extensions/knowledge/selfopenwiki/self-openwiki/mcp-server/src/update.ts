import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  resolveModelSelection,
  withC7Locks,
  type RuntimeConfig,
} from "./config.js";
import {
  internalUpdateOutputSchema,
  modelSelectionSchema,
  resultFailureStageSchema,
  toolInputSchemas,
  toolOutputSchemas,
  type ResultFailureStage,
} from "./contracts.js";
import type {
  ModelVerificationEvidence,
  ModelSelection,
} from "./model-verification.js";
import { type WikiChange, type WikiPublisher } from "./publish.js";
import { C7ProcessError, sanitizeDiagnostic } from "./process.js";
import {
  C7RunResultError,
  parseUpdateModelResult,
  readModelResultJson,
  UPDATE_RESULT_CONTRACT,
  type ReviewModelResult,
  type UpdateModelResult,
} from "./run-result.js";
import {
  assertSourceContentNotSensitive,
  loadSensitiveFilePolicy,
  SensitiveSourceError,
} from "./sensitive-files.js";
import {
  composeSkillContract,
  type C7SkillRegistry,
  type SelectedC7Skills,
} from "./skills.js";
import { assertMarkdownTreeVersion, snapshotMarkdownTree } from "./snapshot.js";
import type { SourceManifestStore } from "./sources.js";
import type {
  C7TransactionFactory,
  C7TransactionOperation,
  C7TransactionWorkspace,
} from "./transaction.js";
import {
  normalizeWikiCandidate,
  validateWikiCandidate,
  type WikiValidationCheck,
  type WikiValidationResult,
} from "./validation.js";

export type UpdateProcessRunner = {
  run(input: {
    cwd: string;
    openWikiHome: string;
    operation: C7TransactionOperation;
    policyPath: string;
    requestFileName?: "request.md" | "result-finalizer.md";
    selection: ModelSelection;
    signal?: AbortSignal;
  }): Promise<{
    model: ModelVerificationEvidence;
    stderr: string;
    stdout: string;
  }>;
};

export type UpdateReviewer = {
  review(input: {
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
  }): Promise<ReviewModelResult & { model: ModelVerificationEvidence }>;
};

export class C7UpdateError extends Error {
  constructor(
    readonly code:
      | "confirmation_required"
      | "invalid_input"
      | "process_failure"
      | "source_rejected",
    message: string,
    readonly failureStage?: ResultFailureStage,
    readonly diagnostic?: string,
  ) {
    super(message);
    this.name = "C7UpdateError";
  }
}

class C7UpdateConflictError extends Error {
  constructor(readonly actualRevision: string) {
    super("The formal Wiki changed after the update was confirmed.");
    this.name = "C7UpdateConflictError";
  }
}

export class OpenWikiUpdateService {
  private readonly config: RuntimeConfig;
  private readonly formalWikiPath: string;
  private readonly processRunner: UpdateProcessRunner;
  private readonly publisher: WikiPublisher;
  private readonly reviewer: UpdateReviewer;
  private readonly runtimeDir: string;
  private readonly sensitivePolicyPath: string;
  private readonly skills: C7SkillRegistry;
  private readonly sources: Pick<SourceManifestStore, "verify">;
  private readonly transactions: C7TransactionFactory;
  private readonly waitBeforeRetry: (
    milliseconds: number,
    signal?: AbortSignal,
  ) => Promise<void>;

  constructor(options: {
    config: RuntimeConfig;
    formalWikiPath: string;
    processRunner: UpdateProcessRunner;
    publisher: WikiPublisher;
    reviewer: UpdateReviewer;
    runtimeDir: string;
    sensitivePolicyPath: string;
    skills: C7SkillRegistry;
    sources: Pick<SourceManifestStore, "verify">;
    transactions: C7TransactionFactory;
    waitBeforeRetry?(milliseconds: number, signal?: AbortSignal): Promise<void>;
  }) {
    if (
      !path.isAbsolute(options.formalWikiPath) ||
      !path.isAbsolute(options.runtimeDir) ||
      !path.isAbsolute(options.sensitivePolicyPath)
    ) {
      throw new C7UpdateError(
        "invalid_input",
        "The update service paths are invalid.",
      );
    }
    this.config = options.config;
    this.formalWikiPath = options.formalWikiPath;
    this.processRunner = options.processRunner;
    this.publisher = options.publisher;
    this.reviewer = options.reviewer;
    this.runtimeDir = options.runtimeDir;
    this.sensitivePolicyPath = options.sensitivePolicyPath;
    this.skills = options.skills;
    this.sources = options.sources;
    this.transactions = options.transactions;
    this.waitBeforeRetry = options.waitBeforeRetry ?? waitForRetry;
  }

  async update(inputValue: unknown, signal?: AbortSignal): Promise<unknown> {
    assertConfirmed(inputValue);
    const parsed = toolInputSchemas.openwiki_update.safeParse(inputValue);
    if (!parsed.success) {
      throw new C7UpdateError(
        "invalid_input",
        "The update request is invalid.",
      );
    }
    const input = parsed.data;
    const policy = await loadSensitiveFilePolicy(this.sensitivePolicyPath);
    try {
      assertSourceContentNotSensitive(input.instruction, policy);
      for (const material of input.materials ?? []) {
        assertSourceContentNotSensitive(material.content, policy);
      }
    } catch (error) {
      if (error instanceof SensitiveSourceError) {
        throw new C7UpdateError(
          "source_rejected",
          "The update contains credential-like material and was rejected.",
        );
      }
      throw error;
    }

    const selection = resolveModelSelection(
      this.config,
      input.modelOverride,
    ).selection;
    const selected = this.skills.select(input.skills ?? []);
    const confirmedRequestMarkdown = renderUpdateRequest(input, selected);
    const sourceSnapshot =
      input.sourceManifestId === undefined
        ? undefined
        : await this.sources.verify({
            confirmation: input.sourceConfirmation!,
            sourceManifestId: input.sourceManifestId,
          });
    let updateOutcome: unknown;
    let updateFailure: unknown;
    let baseWikiRevision: string | null = null;
    try {
      updateOutcome = await withC7Locks(this.runtimeDir, ["operation"], () =>
        withC7Locks(this.runtimeDir, ["credentials", "wiki"], async () => {
          baseWikiRevision = (await snapshotMarkdownTree(this.formalWikiPath))
            .rootHash;
          if (baseWikiRevision !== input.expectedWikiRevision) {
            return buildConflict({
              actualRevision: baseWikiRevision,
              selected,
              selection,
              sourceManifestHash: sourceSnapshot?.manifestHash,
            });
          }
          let workspace: C7TransactionWorkspace | undefined;
          let outcome: unknown;
          let published = false;
          let reviewStarted = false;
          let publishedChanges: readonly WikiChange[] = [];
          let validation: WikiValidationResult = failedValidation(
            "transaction",
            "The update transaction did not complete validation.",
          );
          let model: ModelVerificationEvidence | undefined;
          try {
            let processResult;
            for (let attempt = 0; ; attempt += 1) {
              workspace = await this.transactions.create({
                ...(input.confirmedWikiPaths
                  ? { confirmedWikiPaths: input.confirmedWikiPaths }
                  : {}),
                operation: "update",
                requestMarkdown: confirmedRequestMarkdown,
                selection,
                skills: selected,
                ...(sourceSnapshot
                  ? {
                      sourceSnapshot: {
                        manifestHash: sourceSnapshot.manifestHash,
                        snapshotPath: sourceSnapshot.snapshotPath,
                        snapshotTreeHash: sourceSnapshot.snapshotTreeHash,
                      },
                    }
                  : {}),
              });
              if (workspace.beforeWiki.rootHash !== baseWikiRevision) {
                throw new C7UpdateConflictError(workspace.beforeWiki.rootHash);
              }
              await workspace.transitionStage("running");
              try {
                processResult = await this.processRunner.run({
                  cwd: workspace.homePath,
                  openWikiHome: workspace.homePath,
                  operation: "update",
                  policyPath: workspace.policyPath,
                  selection,
                  signal,
                });
                break;
              } catch (error) {
                if (!isTransientProviderFailure(error) || attempt >= 2) {
                  throw error;
                }
                await workspace.transitionStage("failed");
                await workspace.finalizeCredentials();
                await workspace.cleanup();
                workspace = undefined;
                await this.waitBeforeRetry(
                  retryDelayMilliseconds(error, attempt),
                  signal,
                );
                const currentFormal = await snapshotMarkdownTree(
                  this.formalWikiPath,
                );
                if (currentFormal.rootHash !== baseWikiRevision) {
                  throw new C7UpdateConflictError(currentFormal.rootHash);
                }
              }
            }
            assertExactModelEvidence(selection, processResult.model);
            model = processResult.model;
            await workspace.transitionStage("model_complete");
            const binding = await readJson(
              path.join(
                workspace.homePath,
                "_c7-control",
                "in",
                "binding.json",
              ),
            );
            const modelResult = await this.readUpdateResult({
              binding,
              selection,
              signal,
              workspace,
            });
            if (modelResult.classification === "blocking") {
              validation = failedValidation(
                "semantic_readiness",
                "The model identified a blocking information gap.",
              );
              await workspace.transitionStage("completed");
              outcome = buildNeedsClarification({
                model,
                questions: modelResult.questions,
                selected,
                sourceManifestHash: sourceSnapshot?.manifestHash,
                validation,
              });
            } else {
              await this.normalizeCandidate(workspace.wikiPath);
              validation = await validateWikiCandidate({
                ...(input.confirmedWikiPaths
                  ? { allowedChangedPaths: input.confirmedWikiPaths }
                  : {}),
                beforeSnapshot: workspace.beforeWiki,
                candidateRoot: workspace.wikiPath,
                forbiddenContentHashes: sourceSnapshot?.files.map(
                  (file) => file.hash,
                ),
                ...(sourceSnapshot
                  ? { forbiddenSourceRoot: sourceSnapshot.snapshotPath }
                  : {}),
                requireProvisionalMarker:
                  modelResult.classification === "provisional",
              });
              if (!validation.passed || validation.snapshot === undefined) {
                await workspace.transitionStage("failed");
                outcome = buildFailed({
                  model,
                  selected,
                  selection,
                  sourceManifestHash: sourceSnapshot?.manifestHash,
                  validation,
                });
              } else {
                await workspace.transitionStage("validated");
                await workspace.transitionStage("reviewing");
                reviewStarted = true;
                let currentCandidate = {
                  modelResult,
                  runId: workspace.runId,
                  snapshot: validation.snapshot,
                  wikiPath: workspace.wikiPath,
                };
                const repairWorkspaces: C7TransactionWorkspace[] = [];
                let repairRounds = 0;
                let reviewRounds = 0;
                try {
                  for (;;) {
                    const review = await this.reviewer.review({
                      candidateId: currentCandidate.runId,
                      instruction: confirmedRequestMarkdown,
                      model,
                      reviewedRootHash: currentCandidate.snapshot.rootHash,
                      reviewWikiPath: currentCandidate.wikiPath,
                      selectedSkills: selected,
                      selection,
                      sourceManifestHash: sourceSnapshot?.manifestHash ?? null,
                      ...(sourceSnapshot
                        ? {
                            sourceSnapshot: {
                              manifestHash: sourceSnapshot.manifestHash,
                              snapshotPath: sourceSnapshot.snapshotPath,
                              snapshotTreeHash: sourceSnapshot.snapshotTreeHash,
                            },
                          }
                        : {}),
                      signal,
                    });
                    reviewRounds += 1;
                    assertExactModelEvidence(selection, review.model);

                    if (review.verdict === "auto_fixable" && repairRounds < 2) {
                      await workspace.transitionStage("repairing");
                      const repaired = await this.runRepair({
                        candidateWikiPath: currentCandidate.wikiPath,
                        ...(input.confirmedWikiPaths
                          ? { confirmedWikiPaths: input.confirmedWikiPaths }
                          : {}),
                        expectedBeforeRootHash:
                          currentCandidate.snapshot.rootHash,
                        instruction: confirmedRequestMarkdown,
                        issues: review.issues,
                        selected,
                        selection,
                        signal,
                        sourceSnapshot,
                      });
                      if (repaired.blocking !== undefined) {
                        outcome = buildCandidateClarification({
                          issues: repaired.blocking.issues,
                          model,
                          questions: repaired.blocking.questions,
                          reviewRounds,
                          selected,
                          sourceManifestHash: sourceSnapshot?.manifestHash,
                          validation,
                        });
                        await workspace.transitionStage("attention");
                        break;
                      }
                      repairRounds += 1;
                      repairWorkspaces.push(repaired.workspace);
                      currentCandidate = {
                        modelResult: repaired.modelResult,
                        runId: repaired.workspace.runId,
                        snapshot: repaired.validation.snapshot!,
                        wikiPath: repaired.workspace.wikiPath,
                      };
                      validation = repaired.validation;
                      await workspace.transitionStage("reviewing");
                      continue;
                    }

                    if (
                      review.verdict === "requires_user" ||
                      review.verdict === "auto_fixable"
                    ) {
                      outcome = buildCandidateClarification({
                        issues: review.issues,
                        model,
                        questions: review.issues.map((issue) => issue.message),
                        reviewRounds,
                        selected,
                        sourceManifestHash: sourceSnapshot?.manifestHash,
                        validation,
                      });
                      await workspace.transitionStage("attention");
                      break;
                    }

                    if (
                      currentCandidate.modelResult.classification === "blocking"
                    ) {
                      throw new C7UpdateError(
                        "process_failure",
                        "A blocking repair result cannot enter review.",
                      );
                    }
                    await workspace.transitionStage("publish_pending");
                    const publication = await this.publisher.publish({
                      after: currentCandidate.snapshot,
                      before: workspace.beforeWiki,
                      binding: {
                        model: selection,
                        skillAggregateHash: selected.aggregateHash,
                        sourceManifestHash:
                          sourceSnapshot?.manifestHash ?? null,
                        sourceTreeHash:
                          sourceSnapshot?.snapshotTreeHash ?? null,
                      },
                      candidateWikiPath: currentCandidate.wikiPath,
                      review: {
                        instruction: confirmedRequestMarkdown,
                        selectedSkills: selected,
                        ...(sourceSnapshot
                          ? {
                              sourceSnapshotPath: sourceSnapshot.snapshotPath,
                            }
                          : {}),
                      },
                      runId: currentCandidate.runId,
                    });
                    published = true;
                    publishedChanges = publication.changes;
                    await workspace.transitionStage("published_review_pending");
                    await this.publisher.completeReview({
                      expectedRootHash: publication.after.rootHash,
                      journalPath: publication.journalPath,
                    });
                    outcome = buildReviewedOutcome({
                      changes: publishedChanges,
                      initialClassification:
                        currentCandidate.modelResult.classification,
                      initialIssues: currentCandidate.modelResult.issues,
                      model,
                      review,
                      reviewRounds,
                      selected,
                      sourceManifestHash: sourceSnapshot?.manifestHash,
                      validation,
                    });
                    await workspace.transitionStage("completed");
                    break;
                  }
                } finally {
                  let repairCleanupFailure: unknown;
                  for (const repairWorkspace of repairWorkspaces) {
                    try {
                      await repairWorkspace.finalizeCredentials();
                    } catch (error) {
                      repairCleanupFailure ??= error;
                    }
                    try {
                      await repairWorkspace.cleanup();
                    } catch (error) {
                      repairCleanupFailure ??= error;
                    }
                  }
                  if (repairCleanupFailure !== undefined) {
                    throw repairCleanupFailure;
                  }
                }
              }
            }
          } catch (error) {
            if (workspace !== undefined) {
              await workspace
                .transitionStage(published ? "attention" : "failed")
                .catch(() => undefined);
            }
            outcome =
              error instanceof C7UpdateConflictError
                ? buildConflict({
                    actualRevision: error.actualRevision,
                    selected,
                    selection,
                    sourceManifestHash: sourceSnapshot?.manifestHash,
                  })
                : published
                  ? buildPostPublicationTechnicalFailure({
                      changes: publishedChanges,
                      failure: error,
                      model,
                      selected,
                      selection,
                      sourceManifestHash: sourceSnapshot?.manifestHash,
                      validation,
                    })
                  : reviewStarted
                    ? buildReviewTechnicalFailure({
                        changes: [],
                        failure: error,
                        model,
                        selected,
                        selection,
                        sourceManifestHash: sourceSnapshot?.manifestHash,
                        validation,
                      })
                    : buildFailed({
                        failure: error,
                        model,
                        selected,
                        selection,
                        sourceManifestHash: sourceSnapshot?.manifestHash,
                        validation,
                      });
          }

          let finalizationFailed = false;
          if (workspace !== undefined) {
            try {
              await workspace.finalizeCredentials();
            } catch {
              finalizationFailed = true;
            }
            try {
              await workspace.cleanup();
            } catch {
              finalizationFailed = true;
            }
          }
          if (finalizationFailed) {
            outcome = published
              ? buildPostPublicationTechnicalFailure({
                  changes: publishedChanges,
                  model,
                  selected,
                  selection,
                  sourceManifestHash: sourceSnapshot?.manifestHash,
                  validation,
                })
              : reviewStarted
                ? buildReviewTechnicalFailure({
                    changes: [],
                    model,
                    selected,
                    selection,
                    sourceManifestHash: sourceSnapshot?.manifestHash,
                    validation,
                  })
                : buildFailed({
                    model,
                    selected,
                    selection,
                    sourceManifestHash: sourceSnapshot?.manifestHash,
                    validation,
                  });
          }
          return outcome;
        }),
      );
    } catch (error) {
      updateFailure = error;
    }
    let sourceCleanupFailed = false;
    try {
      await sourceSnapshot?.cleanup();
    } catch {
      sourceCleanupFailed = true;
    }
    if (updateFailure !== undefined) throw updateFailure;
    if (baseWikiRevision === null) {
      throw new C7UpdateError(
        "process_failure",
        "The update did not capture a Wiki revision.",
      );
    }
    updateOutcome = attachBaseWikiRevision(updateOutcome, baseWikiRevision);
    if (sourceCleanupFailed) return buildSourceCleanupFailure(updateOutcome);
    return updateOutcome;
  }

  private async runRepair(input: {
    candidateWikiPath: string;
    confirmedWikiPaths?: readonly string[];
    instruction: string;
    expectedBeforeRootHash: string;
    issues: readonly ReviewModelResult["issues"][number][];
    selected: SelectedC7Skills;
    selection: ModelSelection;
    signal?: AbortSignal;
    sourceSnapshot?: Awaited<ReturnType<SourceManifestStore["verify"]>>;
  }): Promise<
    | {
        blocking: {
          issues: readonly ReviewModelResult["issues"][number][];
          questions: readonly string[];
        };
      }
    | {
        blocking?: never;
        modelResult: UpdateModelResult;
        validation: WikiValidationResult;
        workspace: C7TransactionWorkspace;
      }
  > {
    let workspace: C7TransactionWorkspace | undefined;
    let failure: unknown;
    let result:
      | {
          blocking: {
            issues: readonly ReviewModelResult["issues"][number][];
            questions: readonly string[];
          };
        }
      | {
          blocking?: never;
          modelResult: UpdateModelResult;
          validation: WikiValidationResult;
          workspace: C7TransactionWorkspace;
        }
      | undefined;
    const reviewPaths = repairPaths(input.issues);
    const allowedChangedPaths = intersectRepairPaths(
      reviewPaths,
      input.confirmedWikiPaths,
    );
    if (allowedChangedPaths === undefined || allowedChangedPaths.length === 0) {
      return {
        blocking: {
          issues: input.issues,
          questions: input.issues.map((issue) => issue.message),
        },
      };
    }
    try {
      let processResult;
      for (let attempt = 0; ; attempt += 1) {
        workspace = await this.transactions.create({
          baseWiki: {
            path: input.candidateWikiPath,
            rootHash: input.expectedBeforeRootHash,
          },
          confirmedWikiPaths: allowedChangedPaths,
          operation: "repair",
          requestMarkdown: renderRepairRequest(input.instruction, input.issues),
          selection: input.selection,
          skills: input.selected,
          ...(input.sourceSnapshot
            ? {
                sourceSnapshot: {
                  manifestHash: input.sourceSnapshot.manifestHash,
                  snapshotPath: input.sourceSnapshot.snapshotPath,
                  snapshotTreeHash: input.sourceSnapshot.snapshotTreeHash,
                },
              }
            : {}),
        });
        if (workspace.beforeWiki.rootHash !== input.expectedBeforeRootHash) {
          throw new C7UpdateError(
            "process_failure",
            "The reviewed Wiki changed before autonomous repair started.",
          );
        }
        await workspace.transitionStage("running");
        try {
          processResult = await this.processRunner.run({
            cwd: workspace.homePath,
            openWikiHome: workspace.homePath,
            operation: "repair",
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
          const currentCandidate = await snapshotMarkdownTree(
            input.candidateWikiPath,
          );
          if (currentCandidate.rootHash !== input.expectedBeforeRootHash) {
            throw new C7UpdateError(
              "process_failure",
              "The reviewed Wiki changed before autonomous repair retry.",
            );
          }
        }
      }
      assertExactModelEvidence(input.selection, processResult.model);
      await workspace.transitionStage("model_complete");
      const binding = await readJson(
        path.join(workspace.homePath, "_c7-control", "in", "binding.json"),
      );
      const modelResult = await this.readUpdateResult({
        binding,
        selection: input.selection,
        signal: input.signal,
        workspace,
      });
      if (modelResult.classification === "blocking") {
        await workspace.transitionStage("completed");
        result = { blocking: modelResult };
      } else {
        await this.normalizeCandidate(workspace.wikiPath);
        const validation = await validateWikiCandidate({
          allowedChangedPaths,
          beforeSnapshot: workspace.beforeWiki,
          candidateRoot: workspace.wikiPath,
          forbiddenContentHashes: input.sourceSnapshot?.files.map(
            (file) => file.hash,
          ),
          ...(input.sourceSnapshot
            ? { forbiddenSourceRoot: input.sourceSnapshot.snapshotPath }
            : {}),
          requireProvisionalMarker:
            modelResult.classification === "provisional",
        });
        if (!validation.passed || validation.snapshot === undefined) {
          throw new C7UpdateError(
            "process_failure",
            "The autonomous repair did not pass deterministic validation.",
          );
        }
        await workspace.transitionStage("validated");
        result = { modelResult, validation, workspace };
      }
    } catch (error) {
      failure = error;
      await workspace?.transitionStage("failed").catch(() => undefined);
    }
    if (
      workspace !== undefined &&
      (result === undefined || !("workspace" in result))
    ) {
      try {
        await workspace.finalizeCredentials();
        await workspace.cleanup();
      } catch (error) {
        failure ??= error;
      }
    }
    if (failure !== undefined || result === undefined) throw failure;
    return result;
  }

  private async readUpdateResult(input: {
    binding: unknown;
    selection: ModelSelection;
    signal?: AbortSignal;
    workspace: C7TransactionWorkspace;
  }): Promise<UpdateModelResult> {
    const resultPath = path.join(
      input.workspace.homePath,
      "_c7-control",
      "out",
      "result.json",
    );
    try {
      return parseUpdateModelResult(
        await readModelResultJson(resultPath),
        input.binding,
      );
    } catch (error) {
      if (
        !(error instanceof C7RunResultError) ||
        ![
          "result_json_invalid",
          "result_missing",
          "result_schema_invalid",
        ].includes(error.failureStage) ||
        input.workspace.resultFinalizer === null
      ) {
        throw error;
      }
    }

    try {
      await normalizeWikiCandidate(input.workspace.wikiPath);
    } catch {
      throw candidateNormalizationFailure();
    }
    let candidateBefore;
    try {
      candidateBefore = await snapshotMarkdownTree(input.workspace.wikiPath);
    } catch {
      throw finalizerFailure("result-finalizer-candidate-snapshot");
    }
    const finalizer = input.workspace.resultFinalizer;
    let processResult;
    try {
      processResult = await this.processRunner.run({
        cwd: input.workspace.homePath,
        openWikiHome: input.workspace.homePath,
        operation: "query",
        policyPath: finalizer.policyPath,
        requestFileName: finalizer.requestFileName,
        selection: input.selection,
        signal: input.signal,
      });
    } catch (error) {
      throw finalizerFailure("result-finalizer-process", error);
    }
    try {
      assertExactModelEvidence(input.selection, processResult.model);
    } catch {
      throw finalizerFailure("result-finalizer-model-evidence");
    }
    try {
      await assertMarkdownTreeVersion(
        input.workspace.wikiPath,
        candidateBefore,
      );
    } catch {
      throw finalizerFailure("result-finalizer-candidate-integrity");
    }
    return parseUpdateModelResult(
      await readModelResultJson(resultPath),
      input.binding,
    );
  }

  private async normalizeCandidate(candidateRoot: string): Promise<void> {
    try {
      await normalizeWikiCandidate(candidateRoot);
    } catch {
      throw candidateNormalizationFailure();
    }
  }
}

function repairPaths(
  issues: readonly ReviewModelResult["issues"][number][],
): readonly string[] | undefined {
  const paths: string[] = [];
  const seen = new Set<string>();
  for (const issue of issues) {
    if (issue.page === undefined) return undefined;
    const candidate = issue.page.replace(/\\/gu, "/");
    if (
      path.posix.isAbsolute(candidate) ||
      path.posix.normalize(candidate) !== candidate ||
      !candidate.toLowerCase().endsWith(".md") ||
      candidate.split("/").some((segment) => segment === "..")
    ) {
      return undefined;
    }
    if (!seen.has(candidate)) {
      seen.add(candidate);
      paths.push(candidate);
    }
  }
  return paths.length === 0 ? undefined : paths;
}

function intersectRepairPaths(
  reviewPaths: readonly string[] | undefined,
  confirmedWikiPaths: readonly string[] | undefined,
): readonly string[] | undefined {
  if (reviewPaths === undefined) return undefined;
  if (confirmedWikiPaths === undefined) return reviewPaths;
  const confirmed = new Set(confirmedWikiPaths);
  return reviewPaths.filter((candidate) => confirmed.has(candidate));
}

function renderUpdateRequest(
  input: ReturnType<typeof toolInputSchemas.openwiki_update.parse>,
  selected: SelectedC7Skills,
): string {
  const materials = (input.materials ?? []).map((material) =>
    [
      `### Material ${JSON.stringify(material.id)}`,
      ...(material.source
        ? [`Source label: ${JSON.stringify(material.source)}`]
        : []),
      "```text",
      material.content.replace(/```/gu, "` ` `"),
      "```",
    ].join("\n"),
  );
  return [
    "# C7 bound update transaction",
    "Update only /openwiki from the current Wiki and confirmed evidence. Do not expand the confirmed task, sources, model, or Skill set.",
    "Write one strict update_result JSON object to /_c7-control/out/result.json.",
    UPDATE_RESULT_CONTRACT,
    "## Confirmed user instruction",
    input.instruction,
    ...(materials.length > 0 ? ["## Ephemeral materials", ...materials] : []),
    "## Mandatory C7 Skill contract",
    composeSkillContract(selected.skills),
  ].join("\n\n");
}

function renderRepairRequest(
  instruction: string,
  issues: readonly ReviewModelResult["issues"][number][],
): string {
  return [
    "# C7 bounded autonomous repair",
    "Repair only the reviewed Wiki issues within the original confirmed instruction, source manifest, selected Skills, and existing page scope. Do not add sources, change model, or expand the task.",
    "Write one strict update_result JSON object to /_c7-control/out/result.json.",
    UPDATE_RESULT_CONTRACT,
    "## Original confirmed instruction",
    instruction,
    "## Review issues",
    JSON.stringify(issues, null, 2),
  ].join("\n\n");
}

function attachBaseWikiRevision(
  outcome: unknown,
  baseWikiRevision: string,
): unknown {
  const parsed = internalUpdateOutputSchema.parse(outcome);
  return toolOutputSchemas.openwiki_update.parse({
    ...parsed,
    baseWikiRevision,
  });
}

function buildConflict(input: {
  actualRevision: string;
  selected: SelectedC7Skills;
  selection: ModelSelection;
  sourceManifestHash?: string;
}): unknown {
  return toolOutputSchemas.openwiki_update.parse({
    baseWikiRevision: input.actualRevision,
    changes: [],
    failure: {
      code: "wiki_conflict",
      message: "The formal Wiki changed after the update was confirmed.",
      retryable: true,
    },
    model: {
      providerAccepted: false,
      requested: input.selection,
      sent: null,
    },
    ok: true,
    published: false,
    questions: [],
    recovery: { action: "retry" },
    recoveryState: "clean",
    review: { rounds: 0, status: "not_run" },
    selectedSkills: input.selected.skills.map((skill) => ({
      id: skill.id,
      packageHash: skill.packageHash,
    })),
    skillAggregateHash: input.selected.aggregateHash,
    ...(input.sourceManifestHash
      ? { sourceManifestHash: input.sourceManifestHash }
      : {}),
    status: "conflict",
    validation: {
      checks: [
        {
          id: "wiki_revision",
          message: "The expected Wiki revision is stale.",
          status: "failed",
        },
      ],
      passed: false,
    },
  });
}

function buildReviewedOutcome(input: {
  changes: readonly WikiChange[];
  initialClassification: "minor" | "provisional";
  initialIssues: readonly ReviewModelResult["issues"][number][];
  model: ModelVerificationEvidence;
  review: ReviewModelResult & { model: ModelVerificationEvidence };
  reviewRounds: number;
  selected: SelectedC7Skills;
  sourceManifestHash?: string;
  validation: WikiValidationResult;
}): unknown {
  const common = commonOutput(input);
  if (input.review.verdict === "pass") {
    if (input.initialClassification === "provisional") {
      const followUp = input.initialIssues.filter(
        (issue) => issue.severity === "provisional",
      );
      return internalUpdateOutputSchema.parse({
        ...common,
        followUp,
        published: true,
        review: {
          issues: followUp,
          rounds: input.reviewRounds,
          status: "follow_up",
        },
        status: "published_with_follow_up",
      });
    }
    return internalUpdateOutputSchema.parse({
      ...common,
      published: true,
      review: { rounds: input.reviewRounds, status: "passed" },
      status: "published",
    });
  }
  if (input.review.verdict === "follow_up") {
    const followUp = input.review.issues.filter(
      (issue) => issue.severity === "provisional",
    );
    return internalUpdateOutputSchema.parse({
      ...common,
      followUp,
      published: true,
      review: {
        issues: input.review.issues,
        rounds: input.reviewRounds,
        status: "follow_up",
      },
      status: "published_with_follow_up",
    });
  }
  return internalUpdateOutputSchema.parse({
    ...common,
    issues: input.review.issues,
    published: true,
    recovery: { action: "resolve_attention" },
    recoveryState: "attention",
    review: {
      issues: input.review.issues,
      rounds: input.reviewRounds,
      status: "requires_attention",
    },
    status: "review_requires_attention",
  });
}

function buildCandidateClarification(input: {
  issues: readonly ReviewModelResult["issues"][number][];
  model: ModelVerificationEvidence;
  questions: readonly string[];
  reviewRounds: number;
  selected: SelectedC7Skills;
  sourceManifestHash?: string;
  validation: WikiValidationResult;
}): unknown {
  return internalUpdateOutputSchema.parse({
    ...commonOutput({ ...input, changes: [] }),
    issues: input.issues,
    published: false,
    questions: input.questions,
    recovery: { action: "clarify" },
    review: {
      issues: input.issues,
      rounds: input.reviewRounds,
      status: "requires_attention",
    },
    status: "needs_clarification",
  });
}

function commonOutput(input: {
  changes: readonly WikiChange[];
  model: ModelVerificationEvidence;
  selected: SelectedC7Skills;
  sourceManifestHash?: string;
  validation: WikiValidationResult;
}) {
  return {
    changes: input.changes,
    model: input.model,
    ok: true as const,
    questions: [],
    recovery: { action: "none" as const },
    recoveryState: "clean" as const,
    selectedSkills: input.selected.skills.map((skill) => ({
      id: skill.id,
      packageHash: skill.packageHash,
    })),
    skillAggregateHash: input.selected.aggregateHash,
    ...(input.sourceManifestHash
      ? { sourceManifestHash: input.sourceManifestHash }
      : {}),
    validation: contractValidation(input.validation),
  };
}

function buildNeedsClarification(input: {
  model: ModelVerificationEvidence;
  questions: readonly string[];
  selected: SelectedC7Skills;
  sourceManifestHash?: string;
  validation: WikiValidationResult;
}): unknown {
  return internalUpdateOutputSchema.parse({
    ...commonOutput({ ...input, changes: [] }),
    published: false,
    questions: input.questions,
    recovery: { action: "clarify" },
    review: { rounds: 0, status: "not_run" },
    status: "needs_clarification",
  });
}

function buildFailed(input: {
  failure?: unknown;
  model?: ModelVerificationEvidence;
  selected: SelectedC7Skills;
  selection: ModelSelection;
  sourceManifestHash?: string;
  validation: WikiValidationResult;
}): unknown {
  const requested = input.model?.requested ?? input.selection;
  const details = resultFailureDetails(input.failure);
  const providerFailure = isProviderFailure(input.failure);
  return internalUpdateOutputSchema.parse({
    changes: [],
    failure: {
      code: providerFailure
        ? "provider_failure"
        : input.validation.checks.some(
              (check) =>
                check.id !== "transaction" && check.status === "failed",
            )
          ? "validation_failed"
          : "process_failure",
      ...(details ? { details } : {}),
      message: "The update failed before a Wiki publication was committed.",
      retryable:
        !(input.failure instanceof C7ProcessError) ||
        input.failure.code !== "provider_rejected",
    },
    model: input.model ?? {
      providerAccepted: false,
      requested,
      sent: null,
    },
    ok: true,
    published: false,
    questions: [],
    recovery: { action: "retry" },
    recoveryState: "clean",
    review: { rounds: 0, status: "not_run" },
    selectedSkills: input.selected.skills.map((skill) => ({
      id: skill.id,
      packageHash: skill.packageHash,
    })),
    skillAggregateHash: input.selected.aggregateHash,
    ...(input.sourceManifestHash
      ? { sourceManifestHash: input.sourceManifestHash }
      : {}),
    status: "failed",
    validation: contractValidation(input.validation),
  });
}

function buildReviewTechnicalFailure(input: {
  changes: readonly WikiChange[];
  failure?: unknown;
  model?: ModelVerificationEvidence;
  selected: SelectedC7Skills;
  selection: ModelSelection;
  sourceManifestHash?: string;
  validation: WikiValidationResult;
}): unknown {
  const model = input.model;
  if (model === undefined) {
    return buildFailed(input);
  }
  const details = resultFailureDetails(input.failure);
  const providerFailure = isProviderFailure(input.failure);
  return internalUpdateOutputSchema.parse({
    ...commonOutput({ ...input, changes: [], model }),
    failure: {
      code: providerFailure ? "provider_failure" : "process_failure",
      ...(details ? { details } : {}),
      message: "Mandatory review failed before Wiki publication.",
      retryable:
        !(input.failure instanceof C7ProcessError) ||
        input.failure.code !== "provider_rejected",
    },
    published: false,
    recovery: { action: "retry" },
    review: { rounds: 0, status: "technical_failure" },
    status: "failed",
  });
}

function buildPostPublicationTechnicalFailure(input: {
  changes: readonly WikiChange[];
  failure?: unknown;
  model?: ModelVerificationEvidence;
  selected: SelectedC7Skills;
  selection: ModelSelection;
  sourceManifestHash?: string;
  validation: WikiValidationResult;
}): unknown {
  const model = input.model;
  if (model === undefined) {
    throw new C7UpdateError(
      "process_failure",
      "A committed publication is missing its model evidence.",
    );
  }
  const details = resultFailureDetails(input.failure);
  const providerFailure = isProviderFailure(input.failure);
  return internalUpdateOutputSchema.parse({
    ...commonOutput({ ...input, model }),
    failure: {
      code: providerFailure ? "provider_failure" : "process_failure",
      ...(details ? { details } : {}),
      message:
        "The Wiki was published after Review, but publication finalization did not complete.",
      retryable:
        !(input.failure instanceof C7ProcessError) ||
        input.failure.code !== "provider_rejected",
    },
    issues: [],
    published: true,
    recovery: { action: "resolve_attention" },
    recoveryState: "review_pending",
    review: { rounds: 1, status: "technical_failure" },
    status: "review_requires_attention",
  });
}

function buildSourceCleanupFailure(outcome: unknown): unknown {
  const parsed = toolOutputSchemas.openwiki_update.safeParse(outcome);
  if (!parsed.success || parsed.data.ok !== true) {
    throw new C7UpdateError(
      "process_failure",
      "The update source snapshot could not be cleaned safely.",
    );
  }
  const result = parsed.data;
  const common = {
    baseWikiRevision: result.baseWikiRevision,
    changes: result.changes,
    model: result.model,
    ok: true as const,
    questions: [],
    recovery: { action: "resolve_attention" as const },
    recoveryState: result.published
      ? ("attention" as const)
      : ("clean" as const),
    selectedSkills: result.selectedSkills,
    skillAggregateHash: result.skillAggregateHash,
    ...(result.sourceManifestHash
      ? { sourceManifestHash: result.sourceManifestHash }
      : {}),
    validation: result.validation,
  };
  const failure = {
    code: "process_failure" as const,
    message:
      "The transaction completed, but its source snapshot cleanup failed.",
    retryable: true,
  };
  return result.published
    ? toolOutputSchemas.openwiki_update.parse({
        ...common,
        failure,
        issues: [],
        published: true,
        review: { rounds: 0, status: "technical_failure" },
        status: "review_requires_attention",
      })
    : toolOutputSchemas.openwiki_update.parse({
        ...common,
        changes: [],
        failure,
        published: false,
        recovery: { action: "retry" },
        review: { rounds: 0, status: "not_run" },
        status: "failed",
      });
}

function contractValidation(validation: WikiValidationResult) {
  return {
    checks: validation.checks.map((check) => ({
      id: check.id,
      ...(check.message ? { message: check.message } : {}),
      status: check.status,
    })),
    passed: validation.passed,
  };
}

function failedValidation(id: string, message: string): WikiValidationResult {
  const checks: WikiValidationCheck[] = [{ id, message, status: "failed" }];
  return { checks, passed: false };
}

async function readJson(filePath: string): Promise<unknown> {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    throw new C7UpdateError(
      "process_failure",
      "The OpenWiki update produced invalid structured output.",
    );
  }
}

function resultFailureDetails(error: unknown):
  | {
      diagnostic?: string;
      failureStage?: ResultFailureStage;
      providerStatusClass?: "4xx" | "5xx";
      retryAfterMs?: number;
    }
  | undefined {
  if (typeof error !== "object" || error === null) return undefined;
  const parsed = resultFailureStageSchema.safeParse(
    (error as { failureStage?: unknown }).failureStage,
  );
  const rawDiagnostic = (error as { diagnostic?: unknown }).diagnostic;
  const diagnostic =
    typeof rawDiagnostic === "string"
      ? sanitizeDiagnostic(rawDiagnostic).trim()
      : "";
  const providerStatusClass =
    error instanceof C7ProcessError ? error.providerStatusClass : undefined;
  const retryAfterMs =
    error instanceof C7ProcessError &&
    Number.isInteger(error.retryAfterMs) &&
    error.retryAfterMs! >= 0 &&
    error.retryAfterMs! <= 30_000
      ? error.retryAfterMs
      : undefined;
  if (
    !parsed.success &&
    diagnostic.length === 0 &&
    providerStatusClass === undefined &&
    retryAfterMs === undefined
  ) {
    return undefined;
  }
  return {
    ...(diagnostic.length > 0 ? { diagnostic } : {}),
    ...(parsed.success ? { failureStage: parsed.data } : {}),
    ...(providerStatusClass === undefined ? {} : { providerStatusClass }),
    ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
  };
}

function isProviderFailure(error: unknown): boolean {
  return (
    error instanceof C7ProcessError &&
    (error.code === "provider_rejected" || error.code === "provider_transient")
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

function finalizerFailure(stage: string, error?: unknown): C7UpdateError {
  const nested =
    typeof error === "object" &&
    error !== null &&
    typeof (error as { diagnostic?: unknown }).diagnostic === "string"
      ? (error as { diagnostic: string }).diagnostic.trim()
      : "";
  const diagnostic = sanitizeDiagnostic(
    nested.length > 0 ? `stage=${stage}; ${nested}` : `stage=${stage}`,
  );
  return new C7UpdateError(
    "process_failure",
    "The bounded update result finalizer failed.",
    undefined,
    diagnostic,
  );
}

function candidateNormalizationFailure(): C7UpdateError {
  return new C7UpdateError(
    "process_failure",
    "The candidate Wiki could not be normalized safely.",
    undefined,
    "stage=candidate-normalization",
  );
}

function assertExactModelEvidence(
  selection: ModelSelection,
  evidence: ModelVerificationEvidence,
): void {
  if (
    evidence.providerAccepted !== true ||
    modelSelectionSchema.safeParse(evidence.requested).success === false ||
    evidence.requested.model !== selection.model ||
    evidence.requested.reasoningEffort !== selection.reasoningEffort ||
    evidence.sent.model !== selection.model ||
    evidence.sent.reasoningEffort !== selection.reasoningEffort
  ) {
    throw new C7UpdateError(
      "process_failure",
      "The update model evidence did not match the selected model.",
    );
  }
}

function assertConfirmed(value: unknown): void {
  if (
    typeof value !== "object" ||
    value === null ||
    !("confirmedByUser" in value) ||
    (value as { confirmedByUser?: unknown }).confirmedByUser !== true
  ) {
    throw new C7UpdateError(
      "confirmation_required",
      "The update requires the explicit confirmedByUser guard.",
    );
  }
}
