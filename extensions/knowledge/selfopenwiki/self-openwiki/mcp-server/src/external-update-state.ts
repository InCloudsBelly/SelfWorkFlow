import { createHash, randomUUID } from "node:crypto";
import { lstat, mkdir, open, realpath, rename, rm } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { confirmedWikiPathsSchema, toolOutputSchemas } from "./contracts.js";
import { C7ConfigError, withC7Locks } from "./config.js";
import type { TransactionPathSecurity } from "./transaction.js";

export const EXTERNAL_UPDATE_STAGES = [
  "candidate_writable",
  "review_ready",
  "repair_ready",
  "attention",
  "publish_pending",
  "published",
  "aborted",
] as const;

export type ExternalUpdateStage = (typeof EXTERNAL_UPDATE_STAGES)[number];

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const idSchema = z
  .string()
  .min(8)
  .max(160)
  .regex(/^[A-Za-z0-9][A-Za-z0-9._:-]*$/u);
const absolutePathSchema = z.string().refine(path.isAbsolute);
const skillSchema = z
  .strictObject({
    id: z.string().regex(/^[a-z][a-z0-9-]{0,127}$/u),
    category: z.enum(["base", "specialized"]),
    loadOrder: z.enum(["base_always_first", "request_order"]),
    packageHash: hashSchema,
    rootPath: absolutePathSchema,
  })
  .superRefine((skill, context) => {
    if (
      (skill.category === "base") !==
      (skill.loadOrder === "base_always_first")
    ) {
      context.addIssue({ code: "custom", message: "invalid Skill order" });
    }
  });
const reviewSchema = z.strictObject({
  candidateRootHash: hashSchema,
  candidateReceiptHash: hashSchema,
  reviewPackageHash: hashSchema,
  reviewPackagePath: absolutePathSchema,
});
const failureSchema = z.strictObject({
  at: z.string().datetime({ offset: true }),
  code: z.enum([
    "host_cancelled",
    "host_timeout",
    "host_model_failure",
    "host_process_failure",
  ]),
  messageHash: hashSchema,
  phase: z.enum(["candidate_writer", "reviewer"]),
  retryable: z.boolean(),
});
export type ExternalUpdateFailure = z.infer<typeof failureSchema>;
export const EXTERNAL_UPDATE_FAILURE_CAP = 16;
export const EXTERNAL_TERMINAL_PAYLOAD_MAX_BYTES = 16 * 1024 * 1024;
export const EXTERNAL_TERMINAL_INDEX_MAX_BYTES = 64 * 1024 * 1024;

type ExternalFinalizeOutput = z.infer<
  (typeof toolOutputSchemas)["openwiki_finalize_external_update"]
>;
export type ExternalTerminalPayload = Extract<
  ExternalFinalizeOutput,
  {
    ok: true;
    status:
      | "published"
      | "published_with_follow_up"
      | "external_update_aborted";
  }
>;

const externalTerminalPayloadSchema = z
  .unknown()
  .transform((value, context) => {
    const parsed =
      toolOutputSchemas.openwiki_finalize_external_update.safeParse(value);
    if (
      !parsed.success ||
      !parsed.data.ok ||
      (parsed.data.status !== "published" &&
        parsed.data.status !== "published_with_follow_up" &&
        parsed.data.status !== "external_update_aborted")
    ) {
      context.addIssue({ code: "custom", message: "invalid terminal payload" });
      return z.NEVER;
    }
    return parsed.data as ExternalTerminalPayload;
  });

const externalUpdateStateSchema = z
  .strictObject({
    version: z.literal(1),
    transactionId: idSchema,
    requestId: idSchema,
    requestIdHash: hashSchema,
    inputHash: hashSchema,
    generation: z.number().int().min(1).max(3),
    stage: z.enum(EXTERNAL_UPDATE_STAGES),
    createdAt: z.string().datetime({ offset: true }),
    updatedAt: z.string().datetime({ offset: true }),
    beforeWikiRevision: hashSchema,
    sourceManifestHash: hashSchema.nullable(),
    sourceTreeHash: hashSchema.nullable(),
    skillAggregateHash: hashSchema,
    confirmedWikiPaths: confirmedWikiPathsSchema,
    requestPackageHash: hashSchema,
    workspaceId: idSchema,
    bindingHash: hashSchema,
    transactionRoot: absolutePathSchema,
    requestPackagePath: absolutePathSchema,
    hardRulePackagePath: absolutePathSchema,
    hardRulePackageHash: hashSchema,
    candidateResultContractPath: absolutePathSchema,
    candidateResultContractSchemaHash: hashSchema,
    candidateRoot: absolutePathSchema,
    sourceRoot: absolutePathSchema.nullable(),
    skills: z.array(skillSchema).min(1).max(33),
    failures: z.array(failureSchema).max(16),
    failureOverflowCount: z.number().int().nonnegative(),
    repairSuccessorGeneration: z.number().int().min(2).max(3).nullable(),
    repairPredecessorBindingHash: hashSchema.nullable(),
    review: reviewSchema.nullable(),
    terminalResultHash: hashSchema.nullable(),
    terminalPayload: externalTerminalPayloadSchema.nullable(),
  })
  .superRefine((state, context) => {
    if ((state.sourceRoot === null) !== (state.sourceManifestHash === null)) {
      context.addIssue({ code: "custom", message: "invalid source binding" });
    }
    if (
      (state.sourceTreeHash === null) !==
      (state.sourceManifestHash === null)
    ) {
      context.addIssue({
        code: "custom",
        message: "invalid source hash binding",
      });
    }
    if (state.skills[0]?.id !== "kg-c7-project-wiki") {
      context.addIssue({ code: "custom", message: "base Skill must be first" });
    }
    if (
      new Set(state.skills.map((skill) => skill.id)).size !==
      state.skills.length
    ) {
      context.addIssue({ code: "custom", message: "duplicate Skill" });
    }
    if (Date.parse(state.updatedAt) < Date.parse(state.createdAt)) {
      context.addIssue({ code: "custom", message: "invalid timestamp order" });
    }
    for (const candidate of ownedPaths(state)) {
      if (!isStrictDescendant(state.transactionRoot, candidate)) {
        context.addIssue({
          code: "custom",
          message: "external path escaped its transaction",
        });
        break;
      }
    }
    const requiresReview =
      state.stage === "review_ready" ||
      state.stage === "repair_ready" ||
      state.stage === "publish_pending";
    if (requiresReview !== (state.review !== null)) {
      context.addIssue({ code: "custom", message: "invalid Review state" });
    }
    if (
      (state.stage === "published" || state.stage === "aborted") !==
      (state.terminalResultHash !== null && state.terminalPayload !== null)
    ) {
      context.addIssue({ code: "custom", message: "invalid terminal state" });
    }
    if (
      state.terminalPayload !== null &&
      (state.terminalPayload.transactionId !== state.transactionId ||
        state.terminalPayload.generation !== state.generation ||
        state.terminalPayload.bindingHash !== state.bindingHash ||
        (state.stage === "aborted") !==
          (state.terminalPayload.status === "external_update_aborted") ||
        computeExternalTerminalResultHash(state.terminalPayload) !==
          state.terminalResultHash)
    ) {
      context.addIssue({
        code: "custom",
        message: "terminal payload mismatch",
      });
    }
  });

export type ExternalUpdateState = z.infer<typeof externalUpdateStateSchema>;
export type VersionedExternalUpdateState = {
  readonly state: ExternalUpdateState;
  readonly version: string;
};

export type ExternalUpdateStateTransition =
  | {
      readonly stage: "candidate_writable";
      readonly successor: {
        readonly generation: 2 | 3;
        readonly workspaceId: string;
        readonly bindingHash: string;
        readonly candidateRoot: string;
      };
    }
  | {
      readonly stage: "review_ready";
      readonly review: z.infer<typeof reviewSchema>;
    }
  | { readonly stage: "repair_ready" }
  | { readonly stage: "attention" }
  | { readonly stage: "publish_pending" }
  | {
      readonly stage: "published" | "aborted";
      readonly terminalPayload: unknown;
    };

export class C7ExternalUpdateStateError extends Error {
  constructor(
    readonly code:
      | "invalid_state"
      | "stale_state"
      | "transition_invalid"
      | "restore_required",
    message: string,
  ) {
    super(message);
    this.name = "C7ExternalUpdateStateError";
  }
}

const ALLOWED: Readonly<
  Record<ExternalUpdateStage, ReadonlySet<ExternalUpdateStage>>
> = {
  candidate_writable: new Set(["review_ready", "attention", "aborted"]),
  review_ready: new Set([
    "repair_ready",
    "attention",
    "publish_pending",
    "aborted",
  ]),
  repair_ready: new Set(["candidate_writable", "attention", "aborted"]),
  attention: new Set(["aborted"]),
  publish_pending: new Set(["published", "attention", "aborted"]),
  published: new Set(),
  aborted: new Set(),
};

const terminalTombstoneSchema = z
  .strictObject({
    version: z.literal(1),
    transactionId: idSchema,
    requestIdHash: hashSchema,
    inputHash: hashSchema,
    bindingHash: hashSchema,
    resultHash: hashSchema,
    status: z.enum([
      "published",
      "published_with_follow_up",
      "external_update_aborted",
    ]),
    finalWikiRevision: hashSchema,
    generation: z.number().int().min(1).max(3),
    completedAt: z.string().datetime({ offset: true }),
    payload: externalTerminalPayloadSchema,
  })
  .superRefine((tombstone, context) => {
    const payloadBytes = canonicalExternalTerminalPayloadBytes(
      tombstone.payload,
    );
    if (
      payloadBytes.byteLength > EXTERNAL_TERMINAL_PAYLOAD_MAX_BYTES ||
      tombstone.payload.transactionId !== tombstone.transactionId ||
      tombstone.payload.generation !== tombstone.generation ||
      tombstone.payload.bindingHash !== tombstone.bindingHash ||
      tombstone.payload.status !== tombstone.status ||
      computeExternalTerminalResultHash(tombstone.payload) !==
        tombstone.resultHash ||
      (tombstone.payload.status !== "external_update_aborted" &&
        tombstone.payload.wikiRevision !== tombstone.finalWikiRevision)
    ) {
      context.addIssue({ code: "custom", message: "invalid terminal binding" });
    }
  });
const terminalIndexSchema = z
  .strictObject({
    version: z.literal(1),
    evictedCount: z.number().int().nonnegative(),
    priorAggregateChainRoot: hashSchema.nullable(),
    retainedRootHash: hashSchema,
    tombstones: z.array(terminalTombstoneSchema).max(256),
  })
  .superRefine((index, context) => {
    if (index.retainedRootHash !== terminalRetainedRootHash(index.tombstones)) {
      context.addIssue({
        code: "custom",
        message: "invalid retained terminal root",
      });
    }
  });

export type ExternalUpdateTerminalTombstone = z.infer<
  typeof terminalTombstoneSchema
>;
export type ExternalUpdateTerminalIndex = z.infer<typeof terminalIndexSchema>;

export class ExternalUpdateTerminalStore {
  private readonly rootPath: string;
  private readonly security: TransactionPathSecurity;
  private readonly faultInjector: (
    point: "before_rename" | "after_rename",
  ) => void | Promise<void>;

  constructor(options: {
    rootPath: string;
    security: TransactionPathSecurity;
    faultInjector?(
      point: "before_rename" | "after_rename",
    ): void | Promise<void>;
  }) {
    if (!path.isAbsolute(options.rootPath)) throw invalidState();
    this.rootPath = path.resolve(options.rootPath);
    this.security = options.security;
    this.faultInjector = options.faultInjector ?? (() => undefined);
  }

  async read(): Promise<ExternalUpdateTerminalIndex> {
    return (await this.readVersioned()).index;
  }

  async find(
    transactionId: string,
  ): Promise<ExternalUpdateTerminalTombstone | null> {
    if (!idSchema.safeParse(transactionId).success) throw invalidState();
    const index = await this.read();
    return (
      index.tombstones.find(
        (tombstone) => tombstone.transactionId === transactionId,
      ) ?? null
    );
  }

  async findByRequestIdHash(
    requestIdHash: string,
  ): Promise<ExternalUpdateTerminalTombstone | null> {
    if (!hashSchema.safeParse(requestIdHash).success) throw invalidState();
    const index = await this.read();
    return (
      index.tombstones.find(
        (tombstone) => tombstone.requestIdHash === requestIdHash,
      ) ?? null
    );
  }

  async append(
    tombstone: ExternalUpdateTerminalTombstone,
  ): Promise<ExternalUpdateTerminalTombstone> {
    const lockRoot = await prepareCanonicalRuntime(
      path.dirname(this.rootPath),
      this.security,
    );
    for (let attempt = 1; attempt <= 40; attempt += 1) {
      let callbackEntered = false;
      try {
        return await withC7Locks(lockRoot, ["operation"], async () => {
          callbackEntered = true;
          return this.appendLocked(tombstone);
        });
      } catch (error) {
        if (callbackEntered) throw error;
        if (!(await isOperationLockAcquisitionContention(error, lockRoot))) {
          throw error;
        }
        if (attempt === 40) throw error;
        await delay(Math.min(5 + attempt, 25));
      }
    }
    throw invalidState();
  }

  private async appendLocked(
    tombstone: ExternalUpdateTerminalTombstone,
  ): Promise<ExternalUpdateTerminalTombstone> {
    const parsed = terminalTombstoneSchema.safeParse(tombstone);
    if (!parsed.success) throw invalidState();
    await mkdir(this.rootPath, { mode: 0o700, recursive: true });
    await this.security.securePrivatePath({
      directory: true,
      targetPath: this.rootPath,
    });
    const current = await this.readVersioned();
    const duplicate = current.index.tombstones.find(
      (candidate) => candidate.transactionId === parsed.data.transactionId,
    );
    if (duplicate !== undefined) {
      if (stableJson(duplicate) !== stableJson(parsed.data))
        throw invalidState();
      return duplicate;
    }
    const tombstones = [...current.index.tombstones, parsed.data];
    let evictedCount = current.index.evictedCount;
    let priorAggregateChainRoot = current.index.priorAggregateChainRoot;
    let nextCandidate = {
      version: 1,
      evictedCount,
      priorAggregateChainRoot,
      retainedRootHash: terminalRetainedRootHash(tombstones),
      tombstones,
    } as const;
    while (
      tombstones.length > 256 ||
      canonicalJsonBytes(nextCandidate).byteLength >
        EXTERNAL_TERMINAL_INDEX_MAX_BYTES
    ) {
      const evicted = tombstones.shift();
      if (evicted === undefined) throw invalidState();
      priorAggregateChainRoot = hashCanonical(
        "kg-c7:external-terminal-chain:v1",
        {
          priorAggregateChainRoot,
          tombstoneHash: hashCanonical(
            "kg-c7:external-terminal-tombstone:v1",
            evicted,
          ),
        },
      );
      evictedCount += 1;
      nextCandidate = {
        version: 1,
        evictedCount,
        priorAggregateChainRoot,
        retainedRootHash: terminalRetainedRootHash(tombstones),
        tombstones,
      };
    }
    const next = terminalIndexSchema.parse(nextCandidate);
    const bytes = canonicalJsonBytes(next);
    if (bytes.byteLength > EXTERNAL_TERMINAL_INDEX_MAX_BYTES) {
      throw invalidState();
    }
    const temporaryPath = `${this.indexPath()}.${randomUUID()}.tmp`;
    try {
      await writeExclusive(temporaryPath, bytes, this.security);
      await this.faultInjector("before_rename");
      const beforeRename = await this.readVersioned();
      if (beforeRename.version !== current.version) {
        throw new C7ExternalUpdateStateError(
          "stale_state",
          "The external terminal index changed before commit.",
        );
      }
      await rename(temporaryPath, this.indexPath());
      await this.faultInjector("after_rename");
    } catch (error) {
      await rm(temporaryPath, { force: true }).catch(() => undefined);
      throw error;
    }
    return parsed.data;
  }

  private indexPath(): string {
    return path.join(this.rootPath, "terminal-index.json");
  }

  private async readVersioned(): Promise<{
    index: ExternalUpdateTerminalIndex;
    version: string | null;
  }> {
    const indexPath = this.indexPath();
    let bytes: Buffer;
    try {
      const stat = await lstat(indexPath);
      if (!stat.isFile() || stat.isSymbolicLink()) throw invalidState();
      bytes = await readPrivateRegularFile(indexPath);
    } catch (error) {
      if (nodeCode(error) === "ENOENT") {
        return {
          index: {
            version: 1,
            evictedCount: 0,
            priorAggregateChainRoot: null,
            retainedRootHash: terminalRetainedRootHash([]),
            tombstones: [],
          },
          version: null,
        };
      }
      throw error;
    }
    let value: unknown;
    try {
      value = JSON.parse(bytes.toString("utf8"));
    } catch {
      throw invalidState();
    }
    const parsed = terminalIndexSchema.safeParse(value);
    if (!parsed.success) throw invalidState();
    if (
      canonicalJsonBytes(parsed.data).byteLength >
      EXTERNAL_TERMINAL_INDEX_MAX_BYTES
    ) {
      throw invalidState();
    }
    return { index: parsed.data, version: hashBytes(bytes) };
  }
}

export async function createExternalUpdateState(
  statePath: string,
  value: ExternalUpdateState,
  security: TransactionPathSecurity,
): Promise<VersionedExternalUpdateState> {
  const parsed = parseState(value);
  const location = deriveStateLocation(statePath);
  if (location.transactionId !== parsed.transactionId) throw invalidState();
  const lockRoot = await prepareCanonicalRuntime(location.runtimeDir, security);
  return withC7Locks(lockRoot, ["operation"], () =>
    createExternalUpdateStateRaw(statePath, parsed, security),
  );
}

async function createExternalUpdateStateRaw(
  statePath: string,
  value: ExternalUpdateState,
  security: TransactionPathSecurity,
): Promise<VersionedExternalUpdateState> {
  const parsed = parseState(value);
  if (
    path.resolve(statePath) !== path.join(parsed.transactionRoot, "state.json")
  ) {
    throw invalidState();
  }
  await mkdir(parsed.transactionRoot, { mode: 0o700, recursive: true });
  await security.securePrivatePath({
    directory: true,
    targetPath: parsed.transactionRoot,
  });
  const bytes = jsonBytes(parsed);
  await writeExclusive(statePath, bytes, security);
  return { state: parsed, version: hashBytes(bytes) };
}

export async function readExternalUpdateState(
  statePath: string,
): Promise<VersionedExternalUpdateState> {
  if (!path.isAbsolute(statePath)) throw invalidState();
  let bytes: Buffer;
  try {
    const stat = await lstat(statePath);
    if (!stat.isFile() || stat.isSymbolicLink()) throw invalidState();
    bytes = await readPrivateRegularFile(statePath);
  } catch {
    throw invalidState();
  }
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw invalidState();
  }
  const parsed = parseState(value);
  if (
    path.resolve(statePath) !== path.join(parsed.transactionRoot, "state.json")
  ) {
    throw invalidState();
  }
  return { state: parsed, version: hashBytes(bytes) };
}

export async function transitionExternalUpdateState(input: {
  statePath: string;
  expectedVersion: string;
  next: ExternalUpdateStateTransition;
  now: Date;
  security: TransactionPathSecurity;
}): Promise<VersionedExternalUpdateState> {
  const location = deriveStateLocation(input.statePath);
  const lockRoot = await prepareCanonicalRuntime(
    location.runtimeDir,
    input.security,
  );
  return withC7Locks(lockRoot, ["operation"], () =>
    transitionExternalUpdateStateRaw(input, location.transactionId),
  );
}

async function transitionExternalUpdateStateRaw(
  input: {
    statePath: string;
    expectedVersion: string;
    next: ExternalUpdateStateTransition;
    now: Date;
    security: TransactionPathSecurity;
  },
  pathTransactionId: string,
): Promise<VersionedExternalUpdateState> {
  if (
    !/^sha256:[a-f0-9]{64}$/u.test(input.expectedVersion) ||
    Number.isNaN(input.now.getTime())
  ) {
    throw transitionInvalid();
  }
  const current = await readExternalUpdateState(input.statePath);
  if (current.state.transactionId !== pathTransactionId) throw invalidState();
  if (current.version !== input.expectedVersion) {
    throw new C7ExternalUpdateStateError(
      "stale_state",
      "The external state changed after it was read.",
    );
  }
  if (!ALLOWED[current.state.stage].has(input.next.stage))
    throw transitionInvalid();
  if (input.now.getTime() < Date.parse(current.state.updatedAt))
    throw transitionInvalid();
  if (
    input.next.stage === "candidate_writable" &&
    (input.next.successor.generation !== current.state.generation + 1 ||
      !idSchema.safeParse(input.next.successor.workspaceId).success ||
      !hashSchema.safeParse(input.next.successor.bindingHash).success ||
      !isStrictDescendant(
        current.state.transactionRoot,
        input.next.successor.candidateRoot,
      ))
  ) {
    throw transitionInvalid();
  }
  const terminalPayload =
    input.next.stage === "published" || input.next.stage === "aborted"
      ? parseExternalTerminalPayload(input.next.terminalPayload)
      : null;
  if (
    terminalPayload !== null &&
    (input.next.stage === "aborted") !==
      (terminalPayload.status === "external_update_aborted")
  ) {
    throw transitionInvalid();
  }
  const next = parseState({
    ...current.state,
    ...(input.next.stage === "candidate_writable"
      ? {
          generation: input.next.successor.generation,
          workspaceId: input.next.successor.workspaceId,
          bindingHash: input.next.successor.bindingHash,
          candidateRoot: input.next.successor.candidateRoot,
          repairSuccessorGeneration: input.next.successor.generation,
          repairPredecessorBindingHash: current.state.bindingHash,
          failures: [],
          failureOverflowCount: 0,
        }
      : {}),
    stage: input.next.stage,
    updatedAt: input.now.toISOString(),
    review:
      input.next.stage === "review_ready"
        ? input.next.review
        : input.next.stage === "candidate_writable" ||
            input.next.stage === "published" ||
            input.next.stage === "aborted"
          ? null
          : current.state.review,
    terminalResultHash:
      input.next.stage === "published" || input.next.stage === "aborted"
        ? computeExternalTerminalResultHash(terminalPayload!)
        : null,
    terminalPayload,
  });
  const bytes = jsonBytes(next);
  await commitCas(
    input.statePath,
    input.expectedVersion,
    bytes,
    input.security,
  );
  return { state: next, version: hashBytes(bytes) };
}

export async function recordExternalUpdateFailure(input: {
  statePath: string;
  expectedVersion: string;
  failure: ExternalUpdateFailure;
  now: Date;
  security: TransactionPathSecurity;
}): Promise<VersionedExternalUpdateState> {
  const location = deriveStateLocation(input.statePath);
  const lockRoot = await prepareCanonicalRuntime(
    location.runtimeDir,
    input.security,
  );
  return withC7Locks(lockRoot, ["operation"], () =>
    recordExternalUpdateFailureRaw(input, location.transactionId),
  );
}

async function recordExternalUpdateFailureRaw(
  input: {
    statePath: string;
    expectedVersion: string;
    failure: ExternalUpdateFailure;
    now: Date;
    security: TransactionPathSecurity;
  },
  pathTransactionId: string,
): Promise<VersionedExternalUpdateState> {
  const current = await readExternalUpdateState(input.statePath);
  if (current.state.transactionId !== pathTransactionId) throw invalidState();
  if (current.version !== input.expectedVersion) {
    throw new C7ExternalUpdateStateError(
      "stale_state",
      "The external state changed after it was read.",
    );
  }
  if (
    (current.state.stage !== "candidate_writable" &&
      current.state.stage !== "review_ready") ||
    Number.isNaN(input.now.getTime()) ||
    input.now.getTime() < Date.parse(current.state.updatedAt)
  ) {
    throw transitionInvalid();
  }
  const parsedFailure = failureSchema.safeParse(input.failure);
  if (!parsedFailure.success) throw transitionInvalid();
  const hasCapacity =
    current.state.failures.length < EXTERNAL_UPDATE_FAILURE_CAP;
  const next = parseState({
    ...current.state,
    updatedAt: input.now.toISOString(),
    failures: hasCapacity
      ? [...current.state.failures, parsedFailure.data]
      : current.state.failures,
    failureOverflowCount:
      current.state.failureOverflowCount + (hasCapacity ? 0 : 1),
  });
  const bytes = jsonBytes(next);
  await commitCas(
    input.statePath,
    input.expectedVersion,
    bytes,
    input.security,
  );
  return { state: next, version: hashBytes(bytes) };
}

async function commitCas(
  statePath: string,
  expectedVersion: string,
  bytes: Uint8Array,
  security: TransactionPathSecurity,
): Promise<void> {
  const temporaryPath = `${statePath}.${randomUUID()}.tmp`;
  try {
    await writeExclusive(temporaryPath, bytes, security);
    const beforeRename = await readExternalUpdateState(statePath);
    if (beforeRename.version !== expectedVersion) {
      throw new C7ExternalUpdateStateError(
        "stale_state",
        "The external state changed before commit.",
      );
    }
    await rename(temporaryPath, statePath);
  } catch (error) {
    await rm(temporaryPath, { force: true }).catch(() => undefined);
    throw error;
  }
}

function parseState(value: unknown): ExternalUpdateState {
  const parsed = externalUpdateStateSchema.safeParse(value);
  if (!parsed.success) throw invalidState();
  return parsed.data;
}

function terminalRetainedRootHash(
  tombstones: readonly ExternalUpdateTerminalTombstone[],
): string {
  return hashCanonical("kg-c7:external-terminal-retained:v1", tombstones);
}

function deriveStateLocation(statePath: string): {
  runtimeDir: string;
  transactionId: string;
} {
  if (!path.isAbsolute(statePath) || path.resolve(statePath) !== statePath) {
    throw invalidState();
  }
  if (path.basename(statePath) !== "state.json") throw invalidState();
  const transactionRoot = path.dirname(statePath);
  const transactionId = path.basename(transactionRoot);
  if (!idSchema.safeParse(transactionId).success) throw invalidState();
  const updatesRoot = path.dirname(transactionRoot);
  if (path.basename(updatesRoot) !== "external-updates") throw invalidState();
  const runtimeDir = path.dirname(updatesRoot);
  if (runtimeDir === updatesRoot || path.dirname(runtimeDir) === runtimeDir) {
    throw invalidState();
  }
  return { runtimeDir, transactionId };
}

function ownedPaths(state: ExternalUpdateState): string[] {
  return [
    state.requestPackagePath,
    state.hardRulePackagePath,
    state.candidateResultContractPath,
    state.candidateRoot,
    ...(state.sourceRoot === null ? [] : [state.sourceRoot]),
    ...state.skills.map((skill) => skill.rootPath),
    ...(state.review === null ? [] : [state.review.reviewPackagePath]),
  ];
}

function isStrictDescendant(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

async function prepareCanonicalRuntime(
  runtimeDir: string,
  security: TransactionPathSecurity,
): Promise<string> {
  await mkdir(runtimeDir, { mode: 0o700, recursive: true });
  const canonical = await realpath(runtimeDir);
  const before = await lstat(canonical);
  if (!before.isDirectory() || before.isSymbolicLink()) throw invalidState();
  await security.securePrivatePath({ directory: true, targetPath: canonical });
  const after = await lstat(canonical);
  if (
    !after.isDirectory() ||
    after.isSymbolicLink() ||
    !sameFileIdentity(before, after)
  ) {
    throw invalidState();
  }
  return canonical;
}

async function readPrivateRegularFile(filePath: string): Promise<Buffer> {
  const before = await lstat(filePath);
  if (!before.isFile() || before.isSymbolicLink()) throw invalidState();
  const handle = await open(filePath, "r");
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || !sameFileIdentity(before, opened))
      throw invalidState();
    const bytes = await handle.readFile();
    const [afterHandle, afterPath] = await Promise.all([
      handle.stat(),
      lstat(filePath),
    ]);
    if (
      !afterPath.isFile() ||
      afterPath.isSymbolicLink() ||
      !sameFileIdentity(opened, afterHandle) ||
      !sameFileIdentity(opened, afterPath)
    ) {
      throw invalidState();
    }
    return bytes;
  } finally {
    await handle.close();
  }
}

function sameFileIdentity(
  left: { birthtimeMs: number; dev: number; ino: number },
  right: { birthtimeMs: number; dev: number; ino: number },
): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.birthtimeMs === right.birthtimeMs
  );
}

async function writeExclusive(
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

function jsonBytes(value: unknown): Buffer {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
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

function canonicalJsonBytes(value: unknown): Buffer {
  return Buffer.from(`${stableJson(value)}\n`, "utf8");
}

function hashCanonical(domain: string, value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(`${domain}\0`, "utf8")
    .update(stableJson(value), "utf8")
    .digest("hex")}`;
}

export function parseExternalTerminalPayload(
  value: unknown,
): ExternalTerminalPayload {
  const parsed = externalTerminalPayloadSchema.safeParse(value);
  if (!parsed.success) throw transitionInvalid();
  return parsed.data;
}

export function canonicalExternalTerminalPayloadBytes(
  value: ExternalTerminalPayload,
): Buffer {
  return Buffer.from(stableJson(value), "utf8");
}

export function computeExternalTerminalResultHash(
  value: ExternalTerminalPayload,
): string {
  const bytes = canonicalExternalTerminalPayloadBytes(value);
  if (bytes.byteLength > EXTERNAL_TERMINAL_PAYLOAD_MAX_BYTES) {
    throw transitionInvalid();
  }
  return `sha256:${createHash("sha256")
    .update("kg-c7:external-terminal-result:v1\0", "utf8")
    .update(bytes)
    .digest("hex")}`;
}

function nodeCode(error: unknown): unknown {
  return typeof error === "object" && error !== null && "code" in error
    ? error.code
    : undefined;
}

function invalidState(): C7ExternalUpdateStateError {
  return new C7ExternalUpdateStateError(
    "invalid_state",
    "The external transaction state is missing or invalid.",
  );
}

function transitionInvalid(): C7ExternalUpdateStateError {
  return new C7ExternalUpdateStateError(
    "transition_invalid",
    "The external transaction state transition is invalid.",
  );
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function isOperationLockAcquisitionContention(
  error: unknown,
  runtimeDir: string,
): Promise<boolean> {
  if (error instanceof C7ConfigError) return error.code === "busy";
  if (typeof error !== "object" || error === null) return false;
  const lockError = error as {
    code?: unknown;
    dest?: unknown;
    path?: unknown;
  };
  if (lockError.code !== "EPERM" && lockError.code !== "EACCES") return false;
  if (
    typeof lockError.path !== "string" ||
    typeof lockError.dest !== "string" ||
    !path.basename(lockError.path).startsWith("operation.pending.") ||
    path.basename(lockError.dest) !== "operation.lock" ||
    path.dirname(lockError.path).toLowerCase() !==
      path.dirname(lockError.dest).toLowerCase()
  ) {
    return false;
  }
  const [reportedLockRoot, expectedLockRoot] = await Promise.all([
    realpath(path.dirname(lockError.path)).catch(() => null),
    realpath(path.join(runtimeDir, "locks")).catch(() => null),
  ]);
  return (
    reportedLockRoot !== null &&
    expectedLockRoot !== null &&
    reportedLockRoot.toLowerCase() === expectedLockRoot.toLowerCase()
  );
}
