import { createHash } from "node:crypto";
import { lstat, open, readFile, readdir, rename, rm } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { modelSelectionSchema } from "./contracts.js";
import {
  assertMarkdownTreeVersion,
  copyMarkdownTree,
  snapshotMarkdownTree,
} from "./snapshot.js";
import type { TransactionPathSecurity } from "./transaction.js";
import {
  computeSkillPackage,
  verifySelectedC7Skills,
  type SelectedC7Skill,
  type SelectedC7Skills,
} from "./skills.js";
import { hashSourceSnapshotTree } from "./sources.js";
import {
  isExternalWikiPublishPlan,
  moveRootGitPoliciesIfPresent,
  parseExternalWikiPublishPlan,
  type ExternalWikiPublishPlan,
} from "./publish.js";

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const changeSchema = z.strictObject({
  afterHash: hashSchema.optional(),
  beforeHash: hashSchema.optional(),
  operation: z.enum(["added", "deleted", "modified", "renamed"]),
  path: z.string().min(1).max(32_768),
  previousPath: z.string().min(1).max(32_768).optional(),
});
const markerSchema = z.strictObject({
  afterRootHash: hashSchema,
  planHash: hashSchema,
  runId: z.string().regex(/^run-[A-Za-z0-9._:-]{8,160}$/u),
  version: z.literal(1),
});
const reviewCompleteSchema = z.strictObject({
  completedAt: z.string().datetime({ offset: true }),
  rootHash: hashSchema,
  version: z.literal(1),
});
const reviewSkillSchema = z.strictObject({
  category: z.enum(["base", "specialized"]),
  description: z.string().min(1),
  files: z.array(
    z.strictObject({
      hash: hashSchema,
      relativePath: z.string().min(1),
      size: z.number().int().nonnegative(),
    }),
  ),
  id: z.string().regex(/^[a-z0-9][a-z0-9-]*$/u),
  loadOrder: z.enum(["base_always_first", "request_order"]),
  packageHash: hashSchema,
  title: z.string().min(1),
  verified: z.literal(true),
});
const supersedesSchema = z.strictObject({
  reviewedRootHash: hashSchema,
  runId: z.string().regex(/^run-[A-Za-z0-9._:-]{8,160}$/u),
});
const planV3Schema = z.strictObject({
  afterPath: z.string().refine(path.isAbsolute),
  afterRootHash: hashSchema,
  backupPath: z.string().refine(path.isAbsolute),
  beforeRootHash: hashSchema,
  changes: z.array(changeSchema),
  createdAt: z.string().datetime({ offset: true }),
  formalWikiPath: z.string().refine(path.isAbsolute),
  generation: z.number().int().min(1),
  model: modelSelectionSchema,
  publishPath: z.string().refine(path.isAbsolute),
  reviewInstructionHash: hashSchema,
  reviewInstructionPath: z.string().refine(path.isAbsolute),
  reviewPending: z.literal(true),
  reviewSkills: z.array(reviewSkillSchema).min(1),
  reviewSkillsPath: z.string().refine(path.isAbsolute),
  reviewSourcesPath: z.string().refine(path.isAbsolute).nullable(),
  runId: z.string().regex(/^run-[A-Za-z0-9._:-]{8,160}$/u),
  skillAggregateHash: hashSchema,
  sourceManifestHash: hashSchema.nullable(),
  sourceTreeHash: hashSchema.nullable(),
  supersedes: supersedesSchema.nullable(),
  version: z.literal(3),
});

export type WikiRecoveryResult = {
  readonly recoveryState: "clean" | "restore_failed" | "review_pending";
  readonly reviewObligation?: RecoveredReviewObligation;
  readonly reviewPending: boolean;
  readonly reviewReady?: boolean;
  readonly runId: string;
};

export type RecoveredReviewObligation = {
  readonly candidateId: string;
  readonly generation: number;
  readonly instruction: string;
  readonly journalPath: string;
  readonly model: z.infer<typeof modelSelectionSchema>;
  readonly publishedRootHash: string;
  readonly selectedSkills: SelectedC7Skills;
  readonly sourceManifestHash: string | null;
  readonly sourceSnapshot?: {
    readonly manifestHash: string;
    readonly snapshotPath: string;
    readonly snapshotTreeHash: string;
  };
};

export class WikiRecoveryService {
  private readonly formalWikiPath: string;
  private readonly runtimeDir: string;
  private readonly security: TransactionPathSecurity;
  private readonly externalRecovery?: {
    recover(transactionId: string): Promise<void>;
  };

  constructor(options: {
    formalWikiPath: string;
    runtimeDir: string;
    security: TransactionPathSecurity;
    externalRecovery?: {
      recover(transactionId: string): Promise<void>;
    };
  }) {
    if (
      !path.isAbsolute(options.formalWikiPath) ||
      !path.isAbsolute(options.runtimeDir)
    ) {
      throw new Error("invalid recovery paths");
    }
    this.formalWikiPath = options.formalWikiPath;
    this.runtimeDir = options.runtimeDir;
    this.security = options.security;
    this.externalRecovery = options.externalRecovery;
  }

  async recoverRun(runId: string): Promise<WikiRecoveryResult> {
    if (!/^run-[A-Za-z0-9._:-]{8,160}$/u.test(runId)) {
      throw new Error("invalid recovery run id");
    }
    const journalPath = path.join(this.runtimeDir, "recovery", runId);
    try {
      const { bytes: planBytes, value: planValue } = await readJsonFile(
        path.join(journalPath, "plan.json"),
      );
      if (isExternalWikiPublishPlan(planValue)) {
        return this.recoverExternalRun(
          runId,
          journalPath,
          planBytes,
          parseExternalWikiPublishPlan(planValue),
        );
      }
      const plan = planV3Schema.parse(planValue);
      assertPlanPaths(plan, journalPath, this.formalWikiPath, runId);
      const before = await snapshotMarkdownTree(plan.backupPath);
      const after = await snapshotMarkdownTree(plan.afterPath);
      if (
        before.rootHash !== plan.beforeRootHash ||
        after.rootHash !== plan.afterRootHash
      ) {
        throw new Error("recovery snapshot mismatch");
      }

      const markerPath = path.join(journalPath, "commit.marker");
      if (await regularFileExists(markerPath)) {
        const marker = markerSchema.parse(
          (await readJsonFile(markerPath)).value,
        );
        if (
          marker.runId !== runId ||
          marker.afterRootHash !== plan.afterRootHash ||
          marker.planHash !== hashBytes(planBytes)
        ) {
          throw new Error("recovery marker mismatch");
        }
        await assertMarkdownTreeVersion(this.formalWikiPath, after);
        const reviewCompletePath = path.join(journalPath, "review.complete");
        if (await regularFileExists(reviewCompletePath)) {
          const completed = reviewCompleteSchema.parse(
            (await readJsonFile(reviewCompletePath)).value,
          );
          if (completed.rootHash !== plan.afterRootHash) {
            throw new Error("review completion mismatch");
          }
          await rm(journalPath, { force: true, recursive: true });
          return {
            recoveryState: "clean",
            reviewPending: false,
            runId,
          };
        }
        try {
          const reviewObligation = await loadReviewObligation(
            plan,
            journalPath,
          );
          return {
            recoveryState: "review_pending",
            reviewObligation,
            reviewPending: true,
            reviewReady: true,
            runId,
          };
        } catch {
          await persistRecoveryAttention(
            journalPath,
            this.security,
            "The exact review snapshots are unavailable or invalid.",
          );
          return {
            recoveryState: "review_pending",
            reviewPending: true,
            reviewReady: false,
            runId,
          };
        }
      }

      const displacedPath = path.join(journalPath, "displaced");
      if (await directoryExists(displacedPath)) {
        const displaced = await snapshotMarkdownTree(displacedPath);
        if (displaced.rootHash !== before.rootHash) {
          throw new Error("displaced tree mismatch");
        }
        if (await directoryExists(this.formalWikiPath)) {
          const current = await snapshotMarkdownTree(this.formalWikiPath);
          if (current.rootHash === before.rootHash) {
            await assertMarkdownTreeVersion(this.formalWikiPath, before);
            await moveRootGitPoliciesIfPresent(displacedPath, this.formalWikiPath);
            await rm(journalPath, { force: true, recursive: true });
            return { recoveryState: "clean", reviewPending: false, runId };
          }
          if (current.rootHash !== after.rootHash) {
            throw new Error("The formal Wiki drifted before rollback.");
          }
          await moveRootGitPoliciesIfPresent(this.formalWikiPath, displacedPath);
          await rm(this.formalWikiPath, { force: true, recursive: true });
        }
        await rename(displacedPath, this.formalWikiPath);
      } else if (!(await directoryExists(this.formalWikiPath))) {
        await copyMarkdownTree(plan.backupPath, this.formalWikiPath, before);
        await secureCopiedTree(this.formalWikiPath, before, this.security);
      }
      await assertMarkdownTreeVersion(this.formalWikiPath, before);
      await rm(journalPath, { force: true, recursive: true });
      return { recoveryState: "clean", reviewPending: false, runId };
    } catch {
      return { recoveryState: "restore_failed", reviewPending: true, runId };
    }
  }

  private async recoverExternalRun(
    runId: string,
    journalPath: string,
    planBytes: Buffer,
    plan: ExternalWikiPublishPlan,
  ): Promise<WikiRecoveryResult> {
    try {
      if (
        this.externalRecovery === undefined ||
        plan.runId !== runId ||
        path.basename(journalPath) !== runId
      ) {
        throw new Error("external recovery binding unavailable");
      }
      const marker = markerSchema.parse(
        (await readJsonFile(path.join(journalPath, "commit.marker"))).value,
      );
      if (
        marker.runId !== runId ||
        marker.afterRootHash !== plan.candidateRootHash ||
        marker.planHash !== hashBytes(planBytes)
      ) {
        throw new Error("external recovery marker mismatch");
      }
      await assertMarkdownTreeVersion(
        this.formalWikiPath,
        await snapshotMarkdownTree(path.join(journalPath, "after")),
      );
      const formal = await snapshotMarkdownTree(this.formalWikiPath);
      if (formal.rootHash !== plan.candidateRootHash) {
        throw new Error("external recovery formal Wiki mismatch");
      }
      await this.externalRecovery.recover(plan.transactionId);
      return { recoveryState: "clean", reviewPending: false, runId };
    } catch {
      return { recoveryState: "restore_failed", reviewPending: false, runId };
    }
  }

  async recoverAll(): Promise<readonly WikiRecoveryResult[]> {
    const recoveryRoot = path.join(this.runtimeDir, "recovery");
    let entries;
    try {
      entries = await readdir(recoveryRoot, { withFileTypes: true });
    } catch (error) {
      if (hasErrorCode(error, "ENOENT")) return [];
      throw error;
    }
    const runIds = entries
      .map((entry) => {
        if (
          !entry.isDirectory() ||
          entry.isSymbolicLink() ||
          !/^run-[A-Za-z0-9._:-]{8,160}$/u.test(entry.name)
        ) {
          throw new Error("The recovery directory contains an invalid entry.");
        }
        return entry.name;
      })
      .sort();
    let descriptors: RecoveryDescriptor[];
    try {
      descriptors = await Promise.all(
        runIds.map((runId) => this.readDescriptor(runId)),
      );
      await this.pruneCommittedSuccessors(descriptors);
    } catch {
      return runIds.map((runId) => ({
        recoveryState: "restore_failed",
        reviewPending: true,
        runId,
      }));
    }
    const removed = new Set(
      descriptors
        .filter((descriptor) => descriptor.removed)
        .map((descriptor) => descriptor.runId),
    );
    const results: WikiRecoveryResult[] = [];
    for (const descriptor of descriptors
      .filter((candidate) => !removed.has(candidate.runId))
      .sort((left, right) => right.plan.generation - left.plan.generation)) {
      results.push(await this.recoverRun(descriptor.runId));
    }
    return results;
  }

  private async readDescriptor(runId: string): Promise<RecoveryDescriptor> {
    const journalPath = path.join(this.runtimeDir, "recovery", runId);
    const { bytes, value } = await readJsonFile(
      path.join(journalPath, "plan.json"),
    );
    const plan = planV3Schema.parse(value);
    assertPlanPaths(plan, journalPath, this.formalWikiPath, runId);
    let marker: z.infer<typeof markerSchema> | undefined;
    const markerPath = path.join(journalPath, "commit.marker");
    if (await regularFileExists(markerPath)) {
      marker = markerSchema.parse((await readJsonFile(markerPath)).value);
      if (
        marker.runId !== runId ||
        marker.afterRootHash !== plan.afterRootHash ||
        marker.planHash !== hashBytes(bytes)
      ) {
        throw new Error("recovery marker mismatch");
      }
    }
    return { journalPath, marker, plan, removed: false, runId };
  }

  private async pruneCommittedSuccessors(
    descriptors: RecoveryDescriptor[],
  ): Promise<void> {
    const byRunId = new Map(
      descriptors.map((descriptor) => [descriptor.runId, descriptor]),
    );
    const claimed = new Set<string>();
    for (const successor of [...descriptors].sort(
      (left, right) => left.plan.generation - right.plan.generation,
    )) {
      const supersedes = successor.plan.supersedes;
      if (supersedes === null) continue;
      if (claimed.has(supersedes.runId)) {
        throw new Error("multiple successor journals claim one predecessor");
      }
      claimed.add(supersedes.runId);
      const predecessor = byRunId.get(supersedes.runId);
      if (predecessor === undefined) continue;
      if (successor.marker === undefined) continue;
      if (
        predecessor.marker === undefined ||
        predecessor.plan.afterRootHash !== supersedes.reviewedRootHash ||
        successor.plan.beforeRootHash !== supersedes.reviewedRootHash ||
        successor.plan.generation <= predecessor.plan.generation
      ) {
        throw new Error("invalid committed successor chain");
      }
      await rm(predecessor.journalPath, {
        force: true,
        maxRetries: 20,
        recursive: true,
        retryDelay: 25,
      });
      predecessor.removed = true;
    }
  }
}

type RecoveryPlan = z.infer<typeof planV3Schema>;
type RecoveryDescriptor = {
  readonly journalPath: string;
  readonly marker?: z.infer<typeof markerSchema>;
  readonly plan: RecoveryPlan;
  removed: boolean;
  readonly runId: string;
};

function assertPlanPaths(
  plan: RecoveryPlan,
  journalPath: string,
  formalWikiPath: string,
  runId: string,
): void {
  const expected = {
    afterPath: path.join(journalPath, "after"),
    backupPath: path.join(journalPath, "before"),
    formalWikiPath,
    publishPath: path.join(journalPath, "publish"),
    reviewInstructionPath: path.join(journalPath, "review", "instruction.md"),
    reviewSkillsPath: path.join(journalPath, "review", "skills"),
    reviewSourcesPath: path.join(journalPath, "review", "sources"),
  };
  if (
    plan.runId !== runId ||
    !pathsEqual(plan.afterPath, expected.afterPath) ||
    !pathsEqual(plan.backupPath, expected.backupPath) ||
    !pathsEqual(plan.formalWikiPath, expected.formalWikiPath) ||
    !pathsEqual(plan.publishPath, expected.publishPath) ||
    !pathsEqual(plan.reviewInstructionPath, expected.reviewInstructionPath) ||
    !pathsEqual(plan.reviewSkillsPath, expected.reviewSkillsPath) ||
    (plan.reviewSourcesPath !== null &&
      !pathsEqual(plan.reviewSourcesPath, expected.reviewSourcesPath)) ||
    (plan.sourceManifestHash === null) !== (plan.sourceTreeHash === null) ||
    (plan.sourceTreeHash === null) !== (plan.reviewSourcesPath === null)
  ) {
    throw new Error("recovery plan path mismatch");
  }
}

async function loadReviewObligation(
  plan: RecoveryPlan,
  journalPath: string,
): Promise<RecoveredReviewObligation> {
  const instructionBytes = await readFile(plan.reviewInstructionPath);
  if (hashBytes(instructionBytes) !== plan.reviewInstructionHash) {
    throw new Error("review instruction mismatch");
  }
  const instruction = instructionBytes.toString("utf8");
  if (
    instruction.length === 0 ||
    instruction.includes("\0") ||
    Buffer.byteLength(instruction, "utf8") > 1024 * 1024
  ) {
    throw new Error("review instruction invalid");
  }

  const skills: SelectedC7Skill[] = [];
  for (const expected of plan.reviewSkills) {
    const skillPath = containedPath(plan.reviewSkillsPath, expected.id);
    const computed = await computeSkillPackage(skillPath);
    if (
      computed.packageHash !== expected.packageHash ||
      computed.files.length !== expected.files.length ||
      computed.files.some((file, index) => {
        const bound = expected.files[index];
        return (
          bound === undefined ||
          file.relativePath !== bound.relativePath ||
          file.hash !== bound.hash ||
          file.size !== bound.size
        );
      })
    ) {
      throw new Error("review Skill snapshot mismatch");
    }
    skills.push({ ...expected, files: computed.files });
  }
  const selectedSkills = {
    aggregateHash: plan.skillAggregateHash,
    skills,
  };
  verifySelectedC7Skills(selectedSkills);

  let sourceSnapshot: RecoveredReviewObligation["sourceSnapshot"];
  if (
    plan.reviewSourcesPath !== null &&
    plan.sourceManifestHash !== null &&
    plan.sourceTreeHash !== null
  ) {
    if (
      (await hashSourceSnapshotTree(plan.reviewSourcesPath)) !==
      plan.sourceTreeHash
    ) {
      throw new Error("review source snapshot mismatch");
    }
    sourceSnapshot = {
      manifestHash: plan.sourceManifestHash,
      snapshotPath: plan.reviewSourcesPath,
      snapshotTreeHash: plan.sourceTreeHash,
    };
  }
  return {
    candidateId: plan.runId,
    generation: plan.generation,
    instruction,
    journalPath,
    model: plan.model,
    publishedRootHash: plan.afterRootHash,
    selectedSkills,
    sourceManifestHash: plan.sourceManifestHash,
    ...(sourceSnapshot ? { sourceSnapshot } : {}),
  };
}

async function persistRecoveryAttention(
  journalPath: string,
  security: TransactionPathSecurity,
  message: string,
): Promise<void> {
  const filePath = path.join(journalPath, "attention.json");
  if (await regularFileExists(filePath)) return;
  const handle = await open(filePath, "wx", 0o600);
  try {
    await handle.writeFile(
      `${JSON.stringify({ code: "review_snapshot_unavailable", message, version: 1 })}\n`,
      "utf8",
    );
    await handle.sync();
  } finally {
    await handle.close();
  }
  await security.securePrivatePath({ directory: false, targetPath: filePath });
}

function containedPath(root: string, relativePath: string): string {
  const segments = relativePath.replace(/\\/gu, "/").split("/");
  if (
    path.isAbsolute(relativePath) ||
    segments.some(
      (segment) => segment === "" || segment === "." || segment === "..",
    )
  ) {
    throw new Error("invalid recovery snapshot path");
  }
  const candidate = path.resolve(root, ...segments);
  const relative = path.relative(root, candidate);
  if (
    relative === "" ||
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new Error("recovery snapshot path escapes root");
  }
  return candidate;
}

async function secureCopiedTree(
  root: string,
  snapshot: Awaited<ReturnType<typeof snapshotMarkdownTree>>,
  security: TransactionPathSecurity,
): Promise<void> {
  await security.securePrivatePath({ directory: true, targetPath: root });
  const directories = new Set<string>();
  for (const file of snapshot.files) {
    const filePath = path.join(root, ...file.relativePath.split("/"));
    await security.securePrivatePath({
      directory: false,
      targetPath: filePath,
    });
    let directory = path.dirname(filePath);
    while (!pathsEqual(directory, root)) {
      directories.add(directory);
      directory = path.dirname(directory);
    }
  }
  for (const directory of directories) {
    await security.securePrivatePath({
      directory: true,
      targetPath: directory,
    });
  }
}

async function readJsonFile(
  filePath: string,
): Promise<{ bytes: Buffer; value: unknown }> {
  const stat = await lstat(filePath);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("invalid file");
  const bytes = await readFile(filePath);
  return { bytes, value: JSON.parse(bytes.toString("utf8")) };
}

async function regularFileExists(filePath: string): Promise<boolean> {
  try {
    const stat = await lstat(filePath);
    return stat.isFile() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

async function directoryExists(directoryPath: string): Promise<boolean> {
  try {
    const stat = await lstat(directoryPath);
    return stat.isDirectory() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

function pathsEqual(left: string, right: string): boolean {
  return process.platform === "win32"
    ? path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase()
    : path.resolve(left) === path.resolve(right);
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function hasErrorCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === code
  );
}
