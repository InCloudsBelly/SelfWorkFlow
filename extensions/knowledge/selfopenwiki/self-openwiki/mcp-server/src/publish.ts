import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  rm,
  rmdir,
} from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { ModelSelection } from "./model-verification.js";
import { hashSourceSnapshotTree } from "./sources.js";
import {
  assertMarkdownTreeVersion,
  copyMarkdownTree,
  snapshotMarkdownTree,
  type MarkdownTreeSnapshot,
} from "./snapshot.js";
import type { TransactionPathSecurity } from "./transaction.js";
import {
  applyStablePublication,
  prepareStablePublication,
  StablePublicationError,
  verifyStablePublication,
} from "./stable-publication.js";
import {
  aggregateSkillHash,
  verifySelectedC7Skills,
  type SelectedC7Skills,
} from "./skills.js";

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const externalPublishPlanSchema = z.strictObject({
  version: z.union([z.literal(4), z.literal(5)]),
  executionMode: z.literal("external_agent"),
  runId: z.string().regex(/^run-external-[a-f0-9]{64}$/u),
  transactionId: z
    .string()
    .min(8)
    .max(160)
    .regex(/^[A-Za-z0-9][A-Za-z0-9._:-]*$/u),
  generation: z.number().int().min(1).max(3),
  bindingHash: hashSchema,
  inputHash: hashSchema,
  beforeRootHash: hashSchema,
  candidateRootHash: hashSchema,
  requestPackageHash: hashSchema,
  candidateReceiptHash: hashSchema,
  reviewPackageHash: hashSchema,
  reviewReceiptHash: hashSchema,
  sourceManifestHash: hashSchema.nullable(),
  sourceTreeHash: hashSchema.nullable(),
  skillAggregateHash: hashSchema,
  orderedSkillPackages: z
    .array(
      z.strictObject({
        id: z.string().regex(/^[a-z0-9][a-z0-9-]*$/u),
        packageHash: hashSchema,
      }),
    )
    .min(1)
    .max(33),
  hardRulePackageHash: hashSchema,
  candidateResultContractSchemaHash: hashSchema,
  reviewResultContractSchemaHash: hashSchema,
  confirmedWikiPathsHash: hashSchema,
  reviewCompletedBeforePublish: z.literal(true),
});

export type ExternalWikiPublishPlan = z.infer<typeof externalPublishPlanSchema>;

export function isExternalWikiPublishPlan(
  value: unknown,
): value is ExternalWikiPublishPlan {
  return externalPublishPlanSchema.safeParse(value).success;
}

export type WikiChange = {
  readonly afterHash?: string;
  readonly beforeHash?: string;
  readonly operation: "added" | "deleted" | "modified" | "renamed";
  readonly path: string;
  readonly previousPath?: string;
};

export type WikiPublishResult = {
  readonly after: MarkdownTreeSnapshot;
  readonly before: MarkdownTreeSnapshot;
  readonly changes: readonly WikiChange[];
  readonly generation: number;
  readonly journalPath: string;
  readonly planHash: string;
  readonly runId: string;
};

export class C7PublishError extends Error {
  constructor(
    readonly code:
      | "publish_failed"
      | "restore_failed"
      | "restore_required"
      | "wiki_changed",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "C7PublishError";
  }
}

export class WikiPublisher {
  private readonly fault: (point: PublishFaultPoint) => Promise<void> | void;
  private readonly formalWikiPath: string;
  private readonly now: () => Date;
  private readonly runtimeDir: string;
  private readonly security: TransactionPathSecurity;

  constructor(options: {
    fault?(point: PublishFaultPoint): Promise<void> | void;
    formalWikiPath: string;
    now?(): Date;
    runtimeDir: string;
    security: TransactionPathSecurity;
  }) {
    if (
      !path.isAbsolute(options.formalWikiPath) ||
      !path.isAbsolute(options.runtimeDir) ||
      (!isWithin(options.runtimeDir, options.formalWikiPath) &&
        !pathsEqual(
          options.runtimeDir,
          `${path.resolve(options.formalWikiPath)}.selfopenwiki`,
        ))
    ) {
      throw new C7PublishError(
        "publish_failed",
        "The Wiki publisher paths are invalid.",
      );
    }
    this.fault = options.fault ?? (() => undefined);
    this.formalWikiPath = options.formalWikiPath;
    this.now = options.now ?? (() => new Date());
    this.runtimeDir = options.runtimeDir;
    this.security = options.security;
  }

  async publish(input: {
    after: MarkdownTreeSnapshot;
    before: MarkdownTreeSnapshot;
    binding: {
      model: ModelSelection;
      skillAggregateHash: string;
      sourceManifestHash: string | null;
      sourceTreeHash: string | null;
    };
    candidateWikiPath: string;
    review: {
      instruction: string;
      selectedSkills: SelectedC7Skills;
      sourceSnapshotPath?: string;
    };
    runId: string;
    supersedes?: {
      journalPath: string;
      reviewedRootHash: string;
      runId: string;
    };
  }): Promise<WikiPublishResult> {
    assertPublishInput(input);
    if (input.supersedes !== undefined) {
      await this.assertSupersededJournal(input.supersedes, input.before);
    }
    const journalPath = path.join(this.runtimeDir, "recovery", input.runId);
    const backupPath = path.join(journalPath, "before");
    const afterPath = path.join(journalPath, "after");
    const publishPath = path.join(journalPath, "publish");
    const displacedPath = path.join(journalPath, "displaced");
    const markerPath = path.join(journalPath, "commit.marker");
    const reviewPath = path.join(journalPath, "review");
    const reviewInstructionPath = path.join(reviewPath, "instruction.md");
    const reviewSkillsPath = path.join(reviewPath, "skills");
    const reviewSourcesPath = path.join(reviewPath, "sources");
    const changes = diffMarkdownSnapshots(input.before, input.after);
    const generation = await this.allocateGeneration();
    let planHash = "";
    let formalDisplaced = false;

    try {
      await assertTree(input.candidateWikiPath, input.after, "candidate");
      await assertTree(this.formalWikiPath, input.before, "formal");
      await mkdir(path.dirname(journalPath), { mode: 0o700, recursive: true });
      await this.security.securePrivatePath({
        directory: true,
        targetPath: path.dirname(journalPath),
      });
      await mkdir(journalPath, { mode: 0o700 });
      await this.security.securePrivatePath({
        directory: true,
        targetPath: journalPath,
      });
      await copyMarkdownTree(this.formalWikiPath, backupPath, input.before);
      await copyMarkdownTree(input.candidateWikiPath, afterPath, input.after);
      await copyMarkdownTree(input.candidateWikiPath, publishPath, input.after);
      await Promise.all(
        [backupPath, afterPath, publishPath].map((tree) =>
          secureTree(tree, this.security),
        ),
      );
      await mkdir(reviewPath, { mode: 0o700 });
      await this.security.securePrivatePath({
        directory: true,
        targetPath: reviewPath,
      });
      await writePrivateFile(
        reviewInstructionPath,
        Buffer.from(input.review.instruction, "utf8"),
        this.security,
      );
      await writeSelectedSkillSnapshots(
        reviewSkillsPath,
        input.review.selectedSkills,
        this.security,
      );
      if (
        input.binding.sourceTreeHash !== null &&
        input.review.sourceSnapshotPath !== undefined
      ) {
        await copyBoundSourceTree(
          input.review.sourceSnapshotPath,
          reviewSourcesPath,
          input.binding.sourceTreeHash,
          this.security,
        );
      }
      const planBytes = jsonBytes({
        afterPath,
        afterRootHash: input.after.rootHash,
        backupPath,
        beforeRootHash: input.before.rootHash,
        changes,
        createdAt: this.now().toISOString(),
        formalWikiPath: this.formalWikiPath,
        generation,
        model: input.binding.model,
        publishPath,
        reviewInstructionHash: hashBytes(
          Buffer.from(input.review.instruction, "utf8"),
        ),
        reviewInstructionPath,
        reviewPending: true,
        reviewSkills: input.review.selectedSkills.skills.map((skill) => ({
          category: skill.category,
          description: skill.description,
          files: skill.files.map((file) => ({
            hash: file.hash,
            relativePath: file.relativePath,
            size: file.size,
          })),
          id: skill.id,
          loadOrder: skill.loadOrder,
          packageHash: skill.packageHash,
          title: skill.title,
          verified: true,
        })),
        reviewSkillsPath,
        reviewSourcesPath:
          input.binding.sourceTreeHash === null ? null : reviewSourcesPath,
        runId: input.runId,
        skillAggregateHash: input.binding.skillAggregateHash,
        sourceManifestHash: input.binding.sourceManifestHash,
        sourceTreeHash: input.binding.sourceTreeHash,
        supersedes:
          input.supersedes === undefined
            ? null
            : {
                reviewedRootHash: input.supersedes.reviewedRootHash,
                runId: input.supersedes.runId,
              },
        version: 3,
      });
      planHash = hashBytes(planBytes);
      await writePrivateFileAtomic(
        path.join(journalPath, "plan.json"),
        planBytes,
        this.security,
      );
      await this.fault("after_plan");

      await assertTree(this.formalWikiPath, input.before, "formal");
      await assertTree(input.candidateWikiPath, input.after, "candidate");
      await rename(this.formalWikiPath, displacedPath);
      formalDisplaced = true;
      await this.fault("after_displace");
      await rename(publishPath, this.formalWikiPath);
      await moveGitMetadataIfPresent(displacedPath, this.formalWikiPath);
      await movePersonalClaimsIfPresent(displacedPath, this.formalWikiPath);
      await this.fault("after_install");
      await assertTree(this.formalWikiPath, input.after, "formal");
      await writePrivateFileAtomic(
        markerPath,
        jsonBytes({
          afterRootHash: input.after.rootHash,
          planHash,
          runId: input.runId,
          version: 1,
        }),
        this.security,
        () => this.fault("before_marker_rename"),
      );
      await this.fault("after_marker");
      return {
        after: input.after,
        before: input.before,
        changes,
        generation,
        journalPath,
        planHash,
        runId: input.runId,
      };
    } catch (error) {
      if (await regularFileExists(markerPath)) {
        try {
          await assertCommitMarker(markerPath, {
            afterRootHash: input.after.rootHash,
            planHash,
            runId: input.runId,
          });
          await assertTree(this.formalWikiPath, input.after, "formal");
          return {
            after: input.after,
            before: input.before,
            changes,
            generation,
            journalPath,
            planHash,
            runId: input.runId,
          };
        } catch {
          throw new C7PublishError(
            "restore_failed",
            "The committed Wiki tree no longer matches the recovery marker.",
          );
        }
      }

      if (!formalDisplaced) {
        if (isWikiChanged(error)) {
          throw new C7PublishError(
            "wiki_changed",
            "The formal or candidate Wiki changed before publication.",
          );
        }
        throw new C7PublishError(
          "publish_failed",
          "The Wiki publication failed before changing the formal tree.",
          { cause: error },
        );
      }

      try {
        await restoreBeforeTree({
          after: input.after,
          before: input.before,
          displacedPath,
          formalWikiPath: this.formalWikiPath,
        });
      } catch {
        throw new C7PublishError(
          "restore_failed",
          "The Wiki publication failed and the before tree could not be restored.",
        );
      }
      if (isWikiChanged(error)) {
        throw new C7PublishError(
          "wiki_changed",
          "The formal or candidate Wiki changed before publication.",
        );
      }
      throw new C7PublishError(
        "publish_failed",
        "The Wiki publication failed before its commit marker.",
        { cause: error },
      );
    }
  }

  async publishExternal(input: {
    after: MarkdownTreeSnapshot;
    before: MarkdownTreeSnapshot;
    candidateWikiPath: string;
    plan: unknown;
  }): Promise<WikiPublishResult> {
    const plan = parseExternalWikiPublishPlan(input.plan);
    assertExternalPublishInput(input, plan);
    const journalPath = path.join(this.runtimeDir, "recovery", plan.runId);
    const initializingPath = `${journalPath}.initializing`;
    const initializingQuarantinePath = `${initializingPath}.cleanup`;
    const backupPath = path.join(journalPath, "before");
    const afterPath = path.join(journalPath, "after");
    const publishPath = path.join(journalPath, "publish");
    const displacedPath = path.join(journalPath, "displaced");
    const markerPath = path.join(journalPath, "commit.marker");
    const changes = diffMarkdownSnapshots(input.before, input.after);
    const planBytes = canonicalJsonBytes(plan);
    const planHash = hashBytes(planBytes);
    let formalDisplaced = false;
    let stableChanged = false;
    const stable = {
      ...input,
      plan,
      planHash,
      journalPath,
      formalWikiPath: this.formalWikiPath,
      security: this.security,
    };

    try {
      await assertTree(input.candidateWikiPath, input.after, "candidate");
      await mkdir(path.dirname(journalPath), { mode: 0o700, recursive: true });
      await this.security.securePrivatePath({
        directory: true,
        targetPath: path.dirname(journalPath),
      });
      const [existingJournal, existingInitializing, existingQuarantine] =
        await Promise.all([
          inspectJournalDirectory(journalPath),
          inspectJournalDirectory(initializingPath),
          inspectJournalDirectory(initializingQuarantinePath),
        ]);
      if (
        (existingJournal && (existingInitializing || existingQuarantine)) ||
        (existingInitializing && existingQuarantine)
      ) {
        throw new C7PublishError(
          "restore_required",
          "The external publication has conflicting journal roots.",
        );
      }
      if (!existingJournal) {
        await assertTree(this.formalWikiPath, input.before, "formal");
        if (existingInitializing) {
          await this.security.securePrivatePath({
            directory: true,
            targetPath: initializingPath,
          });
          await rename(initializingPath, initializingQuarantinePath);
        }
        if (existingInitializing || existingQuarantine) {
          await this.security.securePrivatePath({
            directory: true,
            targetPath: initializingQuarantinePath,
          });
          await removePrivateTreeWithoutFollowingLinks(
            initializingQuarantinePath,
          );
        }
        await mkdir(initializingPath, { mode: 0o700 });
        await this.security.securePrivatePath({
          directory: true,
          targetPath: initializingPath,
        });
        await this.fault("after_external_init_mkdir");
        const initializingBackupPath = path.join(initializingPath, "before");
        const initializingAfterPath = path.join(initializingPath, "after");
        const initializingPublishPath = path.join(initializingPath, "publish");
        await copyMarkdownTree(
          this.formalWikiPath,
          initializingBackupPath,
          input.before,
        );
        await copyMarkdownTree(
          input.candidateWikiPath,
          initializingAfterPath,
          input.after,
        );
        await copyMarkdownTree(
          input.candidateWikiPath,
          initializingPublishPath,
          input.after,
        );
        await Promise.all(
          [
            initializingBackupPath,
            initializingAfterPath,
            initializingPublishPath,
          ].map((tree) => secureTree(tree, this.security)),
        );
        await this.fault("after_external_init_trees");
        await writePrivateFileAtomic(
          path.join(initializingPath, "plan.json"),
          planBytes,
          this.security,
        );
        await this.fault("after_external_init_plan");
        await verifyCompleteInitializingExternalJournal({
          after: input.after,
          before: input.before,
          initializingPath,
          planBytes,
        });
        await rename(initializingPath, journalPath);
      } else {
        await this.security.securePrivatePath({
          directory: true,
          targetPath: journalPath,
        });
        await assertTree(backupPath, input.before, "backup");
        await assertTree(afterPath, input.after, "after");
        const planPath = path.join(journalPath, "plan.json");
        const modeExists = await regularFileExists(
          path.join(journalPath, "stable-root.json"),
        );
        if (await regularFileExists(planPath)) {
          const existingPlan = await readFile(planPath);
          if (!existingPlan.equals(planBytes)) {
            let retained: ExternalWikiPublishPlan;
            try {
              retained = parseExternalWikiPublishPlan(
                JSON.parse(existingPlan.toString("utf8")),
              );
            } catch {
              throw new C7PublishError(
                "restore_required",
                "The retained external plan is invalid.",
              );
            }
            if (
              plan.version === 5 &&
              retained.version === 4 &&
              !modeExists &&
              existingPlan.equals(canonicalJsonBytes(retained)) &&
              canonicalJsonBytes({ ...retained, version: 5 }).equals(planBytes)
            ) {
              const formal = await snapshotMarkdownTree(
                this.formalWikiPath,
              ).catch(() => null);
              if (
                (await regularFileExists(markerPath)) ||
                (await directoryExists(displacedPath)) ||
                formal?.rootHash !== input.before.rootHash
              ) {
                // A v4 marker or exchanged tree remains owned by its original
                // protocol. Never relabel an in-flight root swap as stable.
                return await this.publishExternal({ ...input, plan: retained });
              }
              await verifyCompleteInitializingExternalJournal({
                after: input.after,
                before: input.before,
                initializingPath: journalPath,
                planBytes: existingPlan,
              });
              await writePrivateFileAtomic(planPath, planBytes, this.security);
            } else {
              throw new C7PublishError(
                "restore_required",
                "The existing external publication plan conflicts with recovery.",
              );
            }
          }
        } else {
          if (
            modeExists ||
            (await regularFileExists(markerPath)) ||
            (await directoryExists(displacedPath))
          )
            throw invalidInitializingJournal();
          await assertTree(this.formalWikiPath, input.before, "formal");
          await assertTree(publishPath, input.after, "publish");
          if (
            (await readdir(journalPath)).sort().join(",") !==
            "after,before,publish"
          )
            throw invalidInitializingJournal();
          await writePrivateFileAtomic(planPath, planBytes, this.security);
        }
        if (
          plan.version === 4 &&
          (modeExists ||
            (await regularFileExists(
              path.join(journalPath, "stable-root.json.tmp"),
            )))
        )
          throw invalidInitializingJournal();
        if (await regularFileExists(markerPath)) {
          if (plan.version === 5) await verifyStablePublication(stable);
          await assertCommitMarker(markerPath, {
            afterRootHash: input.after.rootHash,
            planHash,
            runId: plan.runId,
          });
          await assertTree(this.formalWikiPath, input.after, "formal");
          return {
            after: input.after,
            before: input.before,
            changes,
            generation: plan.generation,
            journalPath,
            planHash,
            runId: plan.runId,
          };
        }
        if (plan.version === 4)
          await reconcileUnmarkedExternalJournal({
            after: input.after,
            before: input.before,
            displacedPath,
            formalWikiPath: this.formalWikiPath,
            fault: this.fault,
            publishPath,
          });
      }
      await this.fault("after_plan");

      if (plan.version === 5) {
        stableChanged = await prepareStablePublication(stable);
        await this.fault("after_stable_mode");
        await assertTree(input.candidateWikiPath, input.after, "candidate");
        let firstChange = true;
        await applyStablePublication({
          ...stable,
          target: "after",
          onChange: async () => {
            stableChanged = true;
            if (firstChange) {
              firstChange = false;
              await this.fault("after_displace");
            }
          },
        });
      } else {
        await assertTree(this.formalWikiPath, input.before, "formal");
        await assertTree(input.candidateWikiPath, input.after, "candidate");
        await rename(this.formalWikiPath, displacedPath);
        formalDisplaced = true;
        await this.fault("after_displace");
        await rename(publishPath, this.formalWikiPath);
        await moveGitMetadataIfPresent(displacedPath, this.formalWikiPath);
        await movePersonalClaimsIfPresent(displacedPath, this.formalWikiPath);
      }
      await this.fault("after_install");
      await assertTree(this.formalWikiPath, input.after, "formal");
      await writePrivateFileAtomic(
        markerPath,
        jsonBytes({
          afterRootHash: input.after.rootHash,
          planHash,
          runId: plan.runId,
          version: 1,
        }),
        this.security,
        () => this.fault("before_marker_rename"),
      );
      await this.fault("after_marker");
      return {
        after: input.after,
        before: input.before,
        changes,
        generation: plan.generation,
        journalPath,
        planHash,
        runId: plan.runId,
      };
    } catch (error) {
      if (await regularFileExists(markerPath)) {
        try {
          if (plan.version === 5) await verifyStablePublication(stable);
          await assertCommitMarker(markerPath, {
            afterRootHash: input.after.rootHash,
            planHash,
            runId: plan.runId,
          });
          await assertTree(this.formalWikiPath, input.after, "formal");
          return {
            after: input.after,
            before: input.before,
            changes,
            generation: plan.generation,
            journalPath,
            planHash,
            runId: plan.runId,
          };
        } catch {
          throw new C7PublishError(
            "restore_failed",
            "The committed external Wiki tree no longer matches its marker.",
          );
        }
      }
      if (!formalDisplaced) {
        if (stableChanged) {
          try {
            await applyStablePublication({ ...stable, target: "before" });
          } catch (restoreError) {
            throw new C7PublishError(
              "restore_failed",
              "The stable publication could not restore the before tree.",
              { cause: restoreError },
            );
          }
        }
        if (error instanceof StablePublicationError)
          throw new C7PublishError(error.code, error.message, { cause: error });
        if (
          error instanceof C7PublishError &&
          error.code === "restore_required"
        ) {
          throw error;
        }
        if (isWikiChanged(error)) {
          throw new C7PublishError(
            "wiki_changed",
            "The formal or candidate Wiki changed before publication.",
          );
        }
        throw new C7PublishError(
          "publish_failed",
          "The external Wiki publication failed before changing the formal tree.",
          { cause: error },
        );
      }
      try {
        await restoreBeforeTree({
          after: input.after,
          before: input.before,
          displacedPath,
          formalWikiPath: this.formalWikiPath,
        });
      } catch {
        throw new C7PublishError(
          "restore_failed",
          "The external Wiki publication failed and the before tree could not be restored.",
        );
      }
      if (isWikiChanged(error)) {
        throw new C7PublishError(
          "wiki_changed",
          "The formal or candidate Wiki changed before publication.",
        );
      }
      throw new C7PublishError(
        "publish_failed",
        "The external Wiki publication failed before its commit marker.",
        { cause: error },
      );
    }
  }

  async completeReview(input: {
    expectedRootHash: string;
    journalPath: string;
  }): Promise<void> {
    const recoveryRoot = path.join(this.runtimeDir, "recovery");
    if (
      !isWithin(recoveryRoot, input.journalPath) ||
      !/^sha256:[a-f0-9]{64}$/u.test(input.expectedRootHash) ||
      !(await regularFileExists(path.join(input.journalPath, "commit.marker")))
    ) {
      throw new C7PublishError(
        "restore_required",
        "The review completion binding is invalid.",
      );
    }
    const current = await snapshotMarkdownTree(this.formalWikiPath);
    if (current.rootHash !== input.expectedRootHash) {
      throw new C7PublishError(
        "restore_required",
        "The formal Wiki changed before review completion.",
      );
    }
    await rm(path.join(this.runtimeDir, "attention"), {
      force: true,
      maxRetries: 20,
      recursive: true,
      retryDelay: 25,
    });
    await writePrivateFile(
      path.join(input.journalPath, "review.complete"),
      jsonBytes({
        completedAt: this.now().toISOString(),
        rootHash: input.expectedRootHash,
        version: 1,
      }),
      this.security,
    );
    await rm(input.journalPath, {
      force: true,
      maxRetries: 20,
      recursive: true,
      retryDelay: 25,
    });
  }

  async completeReviewWithAttention(input: {
    expectedRootHash: string;
    issues: readonly {
      code: string;
      message: string;
      page?: string;
      severity: "blocking" | "minor" | "provisional";
    }[];
    journalPath: string;
  }): Promise<void> {
    const recoveryRoot = path.join(this.runtimeDir, "recovery");
    if (
      !isWithin(recoveryRoot, input.journalPath) ||
      !/^sha256:[a-f0-9]{64}$/u.test(input.expectedRootHash) ||
      input.issues.length === 0 ||
      input.issues.length > 256 ||
      input.issues.some(
        (issue) =>
          !/^[a-z][a-z0-9_]{0,127}$/u.test(issue.code) ||
          issue.message.trim() === "" ||
          issue.message.length > 4096 ||
          !["blocking", "minor", "provisional"].includes(issue.severity) ||
          (issue.page !== undefined &&
            (issue.page.length === 0 || issue.page.length > 32_768)),
      )
    ) {
      throw new C7PublishError(
        "restore_required",
        "The semantic review attention binding is invalid.",
      );
    }
    const planPath = path.join(input.journalPath, "plan.json");
    const markerPath = path.join(input.journalPath, "commit.marker");
    const planBytes = await readFile(planPath);
    const plan = parseJsonRecord(planBytes);
    if (
      plan.afterRootHash !== input.expectedRootHash ||
      typeof plan.runId !== "string" ||
      typeof plan.generation !== "number" ||
      !Number.isSafeInteger(plan.generation) ||
      plan.generation < 1
    ) {
      throw new C7PublishError(
        "restore_required",
        "The semantic review attention plan is invalid.",
      );
    }
    await assertCommitMarker(markerPath, {
      afterRootHash: input.expectedRootHash,
      planHash: hashBytes(planBytes),
      runId: plan.runId,
    });
    const current = await snapshotMarkdownTree(this.formalWikiPath);
    if (current.rootHash !== input.expectedRootHash) {
      throw new C7PublishError(
        "restore_required",
        "The formal Wiki changed before semantic review attention was recorded.",
      );
    }
    const attentionRoot = path.join(this.runtimeDir, "attention");
    await mkdir(attentionRoot, { mode: 0o700, recursive: true });
    await this.security.securePrivatePath({
      directory: true,
      targetPath: attentionRoot,
    });
    await writePrivateFileAtomic(
      path.join(attentionRoot, `${plan.generation}-${plan.runId}.json`),
      jsonBytes({
        createdAt: this.now().toISOString(),
        generation: plan.generation,
        issues: input.issues,
        rootHash: input.expectedRootHash,
        runId: plan.runId,
        version: 1,
      }),
      this.security,
    );
    await rm(input.journalPath, {
      force: true,
      maxRetries: 20,
      recursive: true,
      retryDelay: 25,
    });
  }

  private async allocateGeneration(): Promise<number> {
    const generationPath = path.join(
      this.runtimeDir,
      "publication-generation.json",
    );
    let current = 0;
    try {
      const value = parseJsonRecord(await readFile(generationPath));
      if (
        value.version !== 1 ||
        typeof value.generation !== "number" ||
        !Number.isSafeInteger(value.generation) ||
        value.generation < 1 ||
        Object.keys(value).sort().join(",") !== "generation,version"
      ) {
        throw new Error("invalid publication generation");
      }
      current = value.generation;
    } catch (error) {
      if (!hasErrorCode(error, "ENOENT")) throw error;
    }
    const generation = current + 1;
    await writePrivateFileAtomic(
      generationPath,
      jsonBytes({ generation, version: 1 }),
      this.security,
    );
    return generation;
  }

  async completeSupersededReview(input: {
    journalPath: string;
    reviewedRootHash: string;
    successorBeforeRootHash: string;
  }): Promise<void> {
    const recoveryRoot = path.join(this.runtimeDir, "recovery");
    if (
      !isWithin(recoveryRoot, input.journalPath) ||
      input.reviewedRootHash !== input.successorBeforeRootHash ||
      !/^sha256:[a-f0-9]{64}$/u.test(input.reviewedRootHash)
    ) {
      throw new C7PublishError(
        "restore_required",
        "The superseded review binding is invalid.",
      );
    }
    const planPath = path.join(input.journalPath, "plan.json");
    const markerPath = path.join(input.journalPath, "commit.marker");
    if (
      !(await regularFileExists(planPath)) ||
      !(await regularFileExists(markerPath))
    ) {
      throw new C7PublishError(
        "restore_required",
        "The superseded review journal is incomplete.",
      );
    }
    const planBytes = await readFile(planPath);
    const plan = parseJsonRecord(planBytes);
    const marker = parseJsonRecord(await readFile(markerPath));
    if (
      plan.afterRootHash !== input.reviewedRootHash ||
      marker.afterRootHash !== input.reviewedRootHash ||
      marker.planHash !== hashBytes(planBytes)
    ) {
      throw new C7PublishError(
        "restore_required",
        "The superseded review journal binding does not match.",
      );
    }
    await rm(input.journalPath, {
      force: true,
      maxRetries: 20,
      recursive: true,
      retryDelay: 25,
    });
  }

  private async assertSupersededJournal(
    supersedes: {
      journalPath: string;
      reviewedRootHash: string;
      runId: string;
    },
    before: MarkdownTreeSnapshot,
  ): Promise<void> {
    const expectedPath = path.join(
      this.runtimeDir,
      "recovery",
      supersedes.runId,
    );
    if (
      !pathsEqual(expectedPath, supersedes.journalPath) ||
      supersedes.reviewedRootHash !== before.rootHash ||
      !/^run-[A-Za-z0-9._:-]{8,160}$/u.test(supersedes.runId)
    ) {
      throw new C7PublishError(
        "restore_required",
        "The autonomous repair predecessor binding is invalid.",
      );
    }
    const planBytes = await readFile(path.join(expectedPath, "plan.json"));
    const plan = parseJsonRecord(planBytes);
    const marker = parseJsonRecord(
      await readFile(path.join(expectedPath, "commit.marker")),
    );
    if (
      plan.afterRootHash !== supersedes.reviewedRootHash ||
      plan.runId !== supersedes.runId ||
      marker.afterRootHash !== supersedes.reviewedRootHash ||
      marker.runId !== supersedes.runId ||
      marker.planHash !== hashBytes(planBytes)
    ) {
      throw new C7PublishError(
        "restore_required",
        "The autonomous repair predecessor journal does not match.",
      );
    }
  }
}

export async function inspectPersistedReviewAttention(input: {
  formalWikiPath: string;
  runtimeDir: string;
}): Promise<"attention" | "clean" | "restore_failed"> {
  const attentionRoot = path.join(input.runtimeDir, "attention");
  let entries;
  try {
    entries = await readdir(attentionRoot, { withFileTypes: true });
  } catch (error) {
    return hasErrorCode(error, "ENOENT") ? "clean" : "restore_failed";
  }
  if (entries.length === 0) return "clean";
  try {
    const records: Array<{ generation: number; rootHash: string }> = [];
    for (const entry of entries) {
      if (
        !entry.isFile() ||
        entry.isSymbolicLink() ||
        !/^\d+-run-[A-Za-z0-9._:-]{8,160}\.json$/u.test(entry.name)
      ) {
        throw new Error("invalid attention entry");
      }
      const value = parseJsonRecord(
        await readFile(path.join(attentionRoot, entry.name)),
      );
      if (
        value.version !== 1 ||
        typeof value.generation !== "number" ||
        !Number.isSafeInteger(value.generation) ||
        value.generation < 1 ||
        typeof value.rootHash !== "string" ||
        !/^sha256:[a-f0-9]{64}$/u.test(value.rootHash) ||
        typeof value.runId !== "string" ||
        !/^run-[A-Za-z0-9._:-]{8,160}$/u.test(value.runId) ||
        typeof value.createdAt !== "string" ||
        Number.isNaN(Date.parse(value.createdAt)) ||
        !isAttentionIssues(value.issues) ||
        Object.keys(value).sort().join(",") !==
          "createdAt,generation,issues,rootHash,runId,version" ||
        entry.name !== `${value.generation}-${value.runId}.json`
      ) {
        throw new Error("invalid attention record");
      }
      records.push({
        generation: value.generation,
        rootHash: value.rootHash,
      });
    }
    records.sort((left, right) => right.generation - left.generation);
    if (
      new Set(records.map((record) => record.generation)).size !==
      records.length
    ) {
      throw new Error("duplicate attention generation");
    }
    const current = await snapshotMarkdownTree(input.formalWikiPath);
    return current.rootHash === records[0]!.rootHash
      ? "attention"
      : "restore_failed";
  } catch {
    return "restore_failed";
  }
}

function isAttentionIssues(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.length <= 256 &&
    value.every((candidate) => {
      if (
        typeof candidate !== "object" ||
        candidate === null ||
        Array.isArray(candidate)
      ) {
        return false;
      }
      const issue = candidate as Record<string, unknown>;
      const keys = Object.keys(issue).sort().join(",");
      return (
        (keys === "code,message,severity" ||
          keys === "code,message,page,severity") &&
        typeof issue.code === "string" &&
        /^[a-z][a-z0-9_]{0,127}$/u.test(issue.code) &&
        typeof issue.message === "string" &&
        issue.message.trim() !== "" &&
        issue.message.length <= 4096 &&
        (issue.severity === "blocking" ||
          issue.severity === "minor" ||
          issue.severity === "provisional") &&
        (issue.page === undefined ||
          (typeof issue.page === "string" &&
            issue.page.length > 0 &&
            issue.page.length <= 32_768))
      );
    })
  );
}

type PublishFaultPoint =
  | "after_stable_mode"
  | "after_displace"
  | "after_external_init_mkdir"
  | "after_external_init_plan"
  | "after_external_init_trees"
  | "after_install"
  | "after_marker"
  | "after_plan"
  | "after_recover_move_after_to_publish"
  | "after_recover_restore_before"
  | "before_marker_rename";

async function inspectJournalDirectory(targetPath: string): Promise<boolean> {
  const stat = await lstat(targetPath).catch((error) => {
    if (hasErrorCode(error, "ENOENT")) return null;
    throw new C7PublishError(
      "restore_required",
      "The external publication journal cannot be inspected.",
    );
  });
  if (stat === null) return false;
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new C7PublishError(
      "restore_required",
      "The external publication journal root is invalid.",
    );
  }
  return true;
}

async function removePrivateTreeWithoutFollowingLinks(
  rootPath: string,
): Promise<void> {
  let entries;
  try {
    entries = await readdir(rootPath, { withFileTypes: true });
  } catch (error) {
    if (hasErrorCode(error, "ENOENT")) return;
    throw new C7PublishError(
      "restore_required",
      "The quarantined external journal cannot be removed safely.",
    );
  }
  for (const entry of entries) {
    const candidate = path.join(rootPath, entry.name);
    const stat = await lstat(candidate).catch((error) => {
      if (hasErrorCode(error, "ENOENT")) return null;
      throw new C7PublishError(
        "restore_required",
        "The quarantined external journal cannot be inspected safely.",
      );
    });
    if (stat === null) continue;
    if (stat.isSymbolicLink() || !stat.isDirectory()) {
      await rm(candidate, { force: true });
      continue;
    }
    await removePrivateTreeWithoutFollowingLinks(candidate);
  }
  await rmdir(rootPath).catch((error) => {
    if (!hasErrorCode(error, "ENOENT")) {
      throw new C7PublishError(
        "restore_required",
        "The quarantined external journal cannot be removed safely.",
      );
    }
  });
}

async function verifyCompleteInitializingExternalJournal(input: {
  after: MarkdownTreeSnapshot;
  before: MarkdownTreeSnapshot;
  initializingPath: string;
  planBytes: Buffer;
}): Promise<void> {
  let entries;
  try {
    entries = await readdir(input.initializingPath, { withFileTypes: true });
  } catch {
    throw invalidInitializingJournal();
  }
  const isPlanScratch = (name: string) =>
    /^plan\.json\.[a-f0-9-]{36}\.tmp$/u.test(name);
  if (
    entries
      .filter((entry) => !isPlanScratch(entry.name))
      .map((entry) => entry.name)
      .sort()
      .join(",") !== "after,before,plan.json,publish" ||
    entries.some(
      (entry) =>
        entry.isSymbolicLink() ||
        (entry.name === "plan.json" || isPlanScratch(entry.name)
          ? !entry.isFile()
          : !entry.isDirectory()),
    )
  ) {
    throw invalidInitializingJournal();
  }
  await Promise.all([
    assertTree(
      path.join(input.initializingPath, "before"),
      input.before,
      "before",
    ),
    assertTree(
      path.join(input.initializingPath, "after"),
      input.after,
      "after",
    ),
    assertTree(
      path.join(input.initializingPath, "publish"),
      input.after,
      "publish",
    ),
  ]);
  const retainedPlan = await readFile(
    path.join(input.initializingPath, "plan.json"),
  );
  if (!retainedPlan.equals(input.planBytes)) throw invalidInitializingJournal();
}

function invalidInitializingJournal(): C7PublishError {
  return new C7PublishError(
    "restore_required",
    "The initializing external journal conflicts with recovery.",
  );
}

async function reconcileUnmarkedExternalJournal(input: {
  after: MarkdownTreeSnapshot;
  before: MarkdownTreeSnapshot;
  displacedPath: string;
  fault(point: PublishFaultPoint): Promise<void> | void;
  formalWikiPath: string;
  publishPath: string;
}): Promise<void> {
  const [formalExists, displacedExists, publishExists] = await Promise.all([
    directoryExists(input.formalWikiPath),
    directoryExists(input.displacedPath),
    directoryExists(input.publishPath),
  ]);
  if (formalExists && !displacedExists && publishExists) {
    await assertTree(input.formalWikiPath, input.before, "formal");
    await assertTree(input.publishPath, input.after, "publish");
    return;
  }
  if (!formalExists && displacedExists && publishExists) {
    await assertTree(input.displacedPath, input.before, "displaced");
    await assertTree(input.publishPath, input.after, "publish");
    await rename(input.displacedPath, input.formalWikiPath);
    return;
  }
  if (formalExists && displacedExists && !publishExists) {
    await assertTree(input.formalWikiPath, input.after, "formal");
    await assertTree(input.displacedPath, input.before, "displaced");
    await moveGitMetadataIfPresent(input.displacedPath, input.formalWikiPath);
    await rename(input.formalWikiPath, input.publishPath);
    await input.fault("after_recover_move_after_to_publish");
    await rename(input.displacedPath, input.formalWikiPath);
    await input.fault("after_recover_restore_before");
    return;
  }
  throw new C7PublishError(
    "restore_required",
    "The unmarked external publication journal is incomplete or conflicts with recovery.",
  );
}

async function restoreBeforeTree(input: {
  after: MarkdownTreeSnapshot;
  before: MarkdownTreeSnapshot;
  displacedPath: string;
  formalWikiPath: string;
}): Promise<void> {
  if (await directoryExists(input.displacedPath)) {
    if (await directoryExists(input.formalWikiPath)) {
      const current = await snapshotMarkdownTree(input.formalWikiPath);
      if (current.rootHash === input.before.rootHash) {
        await assertMarkdownTreeVersion(input.formalWikiPath, input.before);
        return;
      }
      if (current.rootHash !== input.after.rootHash) {
        throw new Error("The formal Wiki drifted during rollback.");
      }
      await moveGitMetadataIfPresent(input.formalWikiPath, input.displacedPath);
      await movePersonalClaimsIfPresent(
        input.formalWikiPath,
        input.displacedPath,
      );
      await rm(input.formalWikiPath, { force: true, recursive: true });
    }
    await rename(input.displacedPath, input.formalWikiPath);
  }
  await assertMarkdownTreeVersion(input.formalWikiPath, input.before);
}

export function diffMarkdownSnapshots(
  before: MarkdownTreeSnapshot,
  after: MarkdownTreeSnapshot,
): WikiChange[] {
  const beforeByPath = new Map(
    before.files.map((file) => [file.relativePath, file]),
  );
  const afterByPath = new Map(
    after.files.map((file) => [file.relativePath, file]),
  );
  const removed = before.files.filter(
    (file) => !afterByPath.has(file.relativePath),
  );
  const added = after.files.filter(
    (file) => !beforeByPath.has(file.relativePath),
  );
  const removedByHash = groupByHash(removed);
  const addedByHash = groupByHash(added);
  const renamedBefore = new Set<string>();
  const renamedAfter = new Set<string>();
  const changes: WikiChange[] = [];
  for (const [hash, oldFiles] of removedByHash) {
    const newFiles = addedByHash.get(hash);
    if (oldFiles.length === 1 && newFiles?.length === 1) {
      const oldFile = oldFiles[0]!;
      const newFile = newFiles[0]!;
      renamedBefore.add(oldFile.relativePath);
      renamedAfter.add(newFile.relativePath);
      changes.push({
        afterHash: hash,
        beforeHash: hash,
        operation: "renamed",
        path: newFile.relativePath,
        previousPath: oldFile.relativePath,
      });
    }
  }
  for (const oldFile of removed) {
    if (!renamedBefore.has(oldFile.relativePath)) {
      changes.push({
        beforeHash: oldFile.hash,
        operation: "deleted",
        path: oldFile.relativePath,
      });
    }
  }
  for (const newFile of added) {
    if (!renamedAfter.has(newFile.relativePath)) {
      changes.push({
        afterHash: newFile.hash,
        operation: "added",
        path: newFile.relativePath,
      });
    }
  }
  for (const oldFile of before.files) {
    const newFile = afterByPath.get(oldFile.relativePath);
    if (newFile !== undefined && newFile.hash !== oldFile.hash) {
      changes.push({
        afterHash: newFile.hash,
        beforeHash: oldFile.hash,
        operation: "modified",
        path: oldFile.relativePath,
      });
    }
  }
  return changes.sort((left, right) => {
    const leftKey = `${left.path}\0${left.operation}`;
    const rightKey = `${right.path}\0${right.operation}`;
    return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
  });
}

function groupByHash(
  files: MarkdownTreeSnapshot["files"],
): Map<string, MarkdownTreeSnapshot["files"][number][]> {
  const grouped = new Map<string, MarkdownTreeSnapshot["files"][number][]>();
  for (const file of files) {
    const values = grouped.get(file.hash) ?? [];
    values.push(file);
    grouped.set(file.hash, values);
  }
  return grouped;
}

async function secureTree(
  root: string,
  security: TransactionPathSecurity,
): Promise<void> {
  await security.securePrivatePath({ directory: true, targetPath: root });
  const snapshot = await snapshotMarkdownTree(root);
  const directories = new Set<string>();
  for (const file of snapshot.files) {
    const filePath = path.join(root, ...file.relativePath.split("/"));
    let directory = path.dirname(filePath);
    while (directory !== root && isWithin(root, directory)) {
      directories.add(directory);
      directory = path.dirname(directory);
    }
    await security.securePrivatePath({
      directory: false,
      targetPath: filePath,
    });
  }
  for (const directory of [...directories].sort()) {
    await security.securePrivatePath({
      directory: true,
      targetPath: directory,
    });
  }
}

async function writePrivateFile(
  filePath: string,
  bytes: Uint8Array,
  security: TransactionPathSecurity,
): Promise<void> {
  const handle = await open(filePath, "wx", 0o600);
  try {
    await handle.writeFile(bytes);
    await handle.sync();
  } finally {
    await handle.close();
  }
  await security.securePrivatePath({ directory: false, targetPath: filePath });
}

async function writePrivateFileAtomic(
  filePath: string,
  bytes: Uint8Array,
  security: TransactionPathSecurity,
  beforeRename?: () => Promise<void> | void,
): Promise<void> {
  const temporaryPath = `${filePath}.${randomUUID()}.tmp`;
  try {
    await writePrivateFile(temporaryPath, bytes, security);
    await beforeRename?.();
    await rename(temporaryPath, filePath);
  } catch (error) {
    await rm(temporaryPath, { force: true });
    throw error;
  }
}

async function assertCommitMarker(
  markerPath: string,
  expected: { afterRootHash: string; planHash: string; runId: string },
): Promise<void> {
  const marker = parseJsonRecord(await readFile(markerPath));
  if (
    marker.version !== 1 ||
    marker.afterRootHash !== expected.afterRootHash ||
    marker.planHash !== expected.planHash ||
    marker.runId !== expected.runId ||
    Object.keys(marker).sort().join(",") !==
      "afterRootHash,planHash,runId,version"
  ) {
    throw new Error("The Wiki commit marker is incomplete or invalid.");
  }
}

async function assertTree(
  root: string,
  expected: MarkdownTreeSnapshot,
  _label: string,
): Promise<void> {
  await assertMarkdownTreeVersion(root, expected);
}

function assertPublishInput(input: {
  after: MarkdownTreeSnapshot;
  before: MarkdownTreeSnapshot;
  binding: {
    model: ModelSelection;
    skillAggregateHash: string;
    sourceManifestHash: string | null;
    sourceTreeHash: string | null;
  };
  candidateWikiPath: string;
  review: {
    instruction: string;
    selectedSkills: SelectedC7Skills;
    sourceSnapshotPath?: string;
  };
  runId: string;
  supersedes?: {
    journalPath: string;
    reviewedRootHash: string;
    runId: string;
  };
}): void {
  try {
    verifySelectedC7Skills(input.review.selectedSkills);
  } catch {
    throw new C7PublishError(
      "publish_failed",
      "The Wiki review Skill snapshots are invalid.",
    );
  }
  if (
    !path.isAbsolute(input.candidateWikiPath) ||
    !/^run-[A-Za-z0-9._:-]{8,160}$/u.test(input.runId) ||
    !/^sha256:[a-f0-9]{64}$/u.test(input.binding.skillAggregateHash) ||
    input.binding.skillAggregateHash !==
      input.review.selectedSkills.aggregateHash ||
    (input.binding.sourceManifestHash !== null &&
      !/^sha256:[a-f0-9]{64}$/u.test(input.binding.sourceManifestHash)) ||
    (input.binding.sourceTreeHash !== null &&
      !/^sha256:[a-f0-9]{64}$/u.test(input.binding.sourceTreeHash)) ||
    (input.binding.sourceManifestHash === null) !==
      (input.binding.sourceTreeHash === null) ||
    (input.binding.sourceTreeHash === null) !==
      (input.review.sourceSnapshotPath === undefined) ||
    (input.review.sourceSnapshotPath !== undefined &&
      !path.isAbsolute(input.review.sourceSnapshotPath)) ||
    input.review.instruction.length === 0 ||
    Buffer.byteLength(input.review.instruction, "utf8") > 1024 * 1024 ||
    input.review.instruction.includes("\0")
  ) {
    throw new C7PublishError(
      "publish_failed",
      "The Wiki publication binding is invalid.",
    );
  }
  if (
    input.supersedes !== undefined &&
    (!path.isAbsolute(input.supersedes.journalPath) ||
      !/^run-[A-Za-z0-9._:-]{8,160}$/u.test(input.supersedes.runId) ||
      !/^sha256:[a-f0-9]{64}$/u.test(input.supersedes.reviewedRootHash))
  ) {
    throw new C7PublishError(
      "publish_failed",
      "The autonomous repair predecessor binding is invalid.",
    );
  }
}

export function parseExternalWikiPublishPlan(
  value: unknown,
): ExternalWikiPublishPlan {
  const parsed = externalPublishPlanSchema.safeParse(value);
  if (!parsed.success) {
    throw new C7PublishError(
      "publish_failed",
      "The external publication plan is invalid.",
    );
  }
  const plan = parsed.data;
  if (
    (plan.sourceManifestHash === null) !== (plan.sourceTreeHash === null) ||
    aggregateSkillHash(
      plan.orderedSkillPackages.map((skill) => ({
        ...skill,
        category: "base" as const,
        description: skill.id,
        files: [],
        loadOrder: "base_always_first" as const,
        title: skill.id,
        verified: true as const,
      })),
    ) !== plan.skillAggregateHash ||
    computeExternalPublishRunId(plan) !== plan.runId
  ) {
    throw new C7PublishError(
      "publish_failed",
      "The external publication plan binding is invalid.",
    );
  }
  return plan;
}

export function computeExternalPublishRunId(input: {
  bindingHash: string;
  generation: number;
  reviewReceiptHash: string;
  transactionId: string;
}): string {
  const bytes = Buffer.from(
    stableJson({
      bindingHash: input.bindingHash,
      generation: input.generation,
      reviewReceiptHash: input.reviewReceiptHash,
      transactionId: input.transactionId,
    }),
    "utf8",
  );
  return `run-external-${createHash("sha256")
    .update("kg-c7:external-publish-run:v1\0", "utf8")
    .update(bytes)
    .digest("hex")}`;
}

export function computeConfirmedWikiPathsHash(
  confirmedWikiPaths: readonly string[],
): string {
  return `sha256:${createHash("sha256")
    .update("kg-c7:external-confirmed-wiki-paths:v1\0", "utf8")
    .update(stableJson(confirmedWikiPaths), "utf8")
    .digest("hex")}`;
}

function assertExternalPublishInput(
  input: {
    after: MarkdownTreeSnapshot;
    before: MarkdownTreeSnapshot;
    candidateWikiPath: string;
  },
  plan: ExternalWikiPublishPlan,
): void {
  if (
    !path.isAbsolute(input.candidateWikiPath) ||
    plan.beforeRootHash !== input.before.rootHash ||
    plan.candidateRootHash !== input.after.rootHash
  ) {
    throw new C7PublishError(
      "publish_failed",
      "The external publication snapshots do not match the plan.",
    );
  }
}

function hasErrorCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === code
  );
}

async function writeSelectedSkillSnapshots(
  root: string,
  selected: SelectedC7Skills,
  security: TransactionPathSecurity,
): Promise<void> {
  verifySelectedC7Skills(selected);
  await mkdir(root, { mode: 0o700 });
  await security.securePrivatePath({ directory: true, targetPath: root });
  for (const skill of selected.skills) {
    const skillRoot = containedPath(root, skill.id);
    await mkdir(skillRoot, { mode: 0o700 });
    await security.securePrivatePath({
      directory: true,
      targetPath: skillRoot,
    });
    for (const file of skill.files) {
      const destination = containedPath(skillRoot, file.relativePath);
      await mkdir(path.dirname(destination), { mode: 0o700, recursive: true });
      await security.securePrivatePath({
        directory: true,
        targetPath: path.dirname(destination),
      });
      await writePrivateFile(destination, file.bytes, security);
    }
  }
}

async function copyBoundSourceTree(
  sourceRoot: string,
  destinationRoot: string,
  expectedHash: string,
  security: TransactionPathSecurity,
): Promise<void> {
  if ((await hashSourceSnapshotTree(sourceRoot)) !== expectedHash) {
    throw new Error("The review source snapshot does not match its binding.");
  }
  await mkdir(destinationRoot, { mode: 0o700 });
  await security.securePrivatePath({
    directory: true,
    targetPath: destinationRoot,
  });
  await copyRegularDirectory(sourceRoot, destinationRoot, security);
  if (
    (await hashSourceSnapshotTree(sourceRoot)) !== expectedHash ||
    (await hashSourceSnapshotTree(destinationRoot)) !== expectedHash
  ) {
    throw new Error("The review source snapshot changed while copied.");
  }
}

async function copyRegularDirectory(
  sourceRoot: string,
  destinationRoot: string,
  security: TransactionPathSecurity,
): Promise<void> {
  const sourceStat = await lstat(sourceRoot);
  if (!sourceStat.isDirectory() || sourceStat.isSymbolicLink()) {
    throw new Error("Review snapshots require regular directories.");
  }
  const entries = await readdir(sourceRoot, { withFileTypes: true });
  for (const entry of entries) {
    const source = path.join(sourceRoot, entry.name);
    const destination = path.join(destinationRoot, entry.name);
    const stat = await lstat(source);
    if (entry.isSymbolicLink() || stat.isSymbolicLink()) {
      throw new Error("Review snapshots cannot contain links.");
    }
    if (entry.isDirectory() && stat.isDirectory()) {
      await mkdir(destination, { mode: 0o700 });
      await security.securePrivatePath({
        directory: true,
        targetPath: destination,
      });
      await copyRegularDirectory(source, destination, security);
    } else if (entry.isFile() && stat.isFile()) {
      await writePrivateFile(destination, await readFile(source), security);
    } else {
      throw new Error("Review snapshots require regular files.");
    }
  }
}

function containedPath(root: string, relativePath: string): string {
  const segments = relativePath.replace(/\\/gu, "/").split("/");
  if (
    path.isAbsolute(relativePath) ||
    segments.some(
      (segment) => segment === "" || segment === "." || segment === "..",
    )
  ) {
    throw new Error("A review snapshot path is invalid.");
  }
  const candidate = path.resolve(root, ...segments);
  if (!isWithin(root, candidate) || pathsEqual(root, candidate)) {
    throw new Error("A review snapshot path escapes its root.");
  }
  return candidate;
}

function pathsEqual(left: string, right: string): boolean {
  return process.platform === "win32"
    ? path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase()
    : path.resolve(left) === path.resolve(right);
}

async function directoryExists(targetPath: string): Promise<boolean> {
  try {
    const stat = await lstat(targetPath);
    return stat.isDirectory() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

async function moveGitMetadataIfPresent(
  sourceRoot: string,
  targetRoot: string,
): Promise<void> {
  await moveGitMetadataEntry(sourceRoot, targetRoot, ".git");
  await moveRootGitPoliciesIfPresent(sourceRoot, targetRoot);
}

export async function moveRootGitPoliciesIfPresent(
  sourceRoot: string,
  targetRoot: string,
): Promise<void> {
  for (const name of [".gitignore", ".gitattributes"]) {
    await moveGitMetadataEntry(sourceRoot, targetRoot, name);
  }
}

async function moveGitMetadataEntry(
  sourceRoot: string,
  targetRoot: string,
  name: string,
): Promise<void> {
  const sourcePath = path.join(sourceRoot, name);
  const targetPath = path.join(targetRoot, name);
  const sourceStat = await lstat(sourcePath).catch((error: unknown) => {
    if (hasErrorCode(error, "ENOENT")) return null;
    throw error;
  });
  if (sourceStat === null) return;
  if (
    sourceStat.isSymbolicLink() ||
    (!sourceStat.isFile() && (name !== ".git" || !sourceStat.isDirectory()))
  ) {
    throw new Error("Git metadata must be a regular file or directory.");
  }
  const targetStat = await lstat(targetPath).catch((error: unknown) => {
    if (hasErrorCode(error, "ENOENT")) return null;
    throw error;
  });
  if (targetStat !== null) {
    throw new Error("Git metadata exists in both Wiki roots.");
  }
  await rename(sourcePath, targetPath);
}

async function movePersonalClaimsIfPresent(
  sourceRoot: string,
  targetRoot: string,
): Promise<void> {
  const sourcePath = path.join(sourceRoot, ".claims");
  const targetPath = path.join(targetRoot, ".claims");
  const sourceStat = await lstat(sourcePath).catch((error: unknown) => {
    if (hasErrorCode(error, "ENOENT")) return null;
    throw error;
  });
  if (sourceStat === null) return;
  if (sourceStat.isSymbolicLink() || !sourceStat.isDirectory()) {
    throw new Error("Personal Claim metadata must be a regular directory.");
  }
  const targetStat = await lstat(targetPath).catch((error: unknown) => {
    if (hasErrorCode(error, "ENOENT")) return null;
    throw error;
  });
  if (targetStat !== null) {
    throw new Error("Personal Claim metadata exists in both Wiki roots.");
  }
  await rename(sourcePath, targetPath);
}

async function regularFileExists(targetPath: string): Promise<boolean> {
  try {
    const stat = await lstat(targetPath);
    return stat.isFile() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

function isWithin(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative === "" ||
    (relative !== ".." &&
      !relative.startsWith(`..${path.sep}`) &&
      !path.isAbsolute(relative))
  );
}

function isWikiChanged(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === "wiki_changed"
  );
}

function jsonBytes(value: unknown): Buffer {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function canonicalJsonBytes(value: unknown): Buffer {
  return Buffer.from(`${stableJson(value)}\n`, "utf8");
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function parseJsonRecord(bytes: Uint8Array): Record<string, unknown> {
  const value = JSON.parse(Buffer.from(bytes).toString("utf8")) as unknown;
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new C7PublishError(
      "restore_required",
      "The publication journal is invalid.",
    );
  }
  return value as Record<string, unknown>;
}
