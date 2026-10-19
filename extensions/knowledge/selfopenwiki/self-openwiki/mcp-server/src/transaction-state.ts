import type { ModelSelection } from "./model-verification.js";
import type { TransactionPathSecurity } from "./transaction.js";

export const C7_TRANSACTION_STAGES = [
  "prepared",
  "running",
  "model_complete",
  "validated",
  "publish_pending",
  "published_review_pending",
  "reviewing",
  "repairing",
  "completed",
  "attention",
  "failed",
  "restore_failed",
] as const;

export type C7TransactionStage = (typeof C7_TRANSACTION_STAGES)[number];

export type C7TransactionState = {
  readonly beforeWikiRootHash: string;
  readonly createdAt: string;
  readonly generation: number;
  readonly homePath: string;
  readonly model: ModelSelection;
  readonly operation: "query" | "repair" | "review" | "update";
  readonly pid: number;
  readonly policyPath: string;
  readonly reviewRequired: boolean;
  readonly runId: string;
  readonly skillAggregateHash: string;
  readonly sourceManifestHash: string | null;
  readonly stage: C7TransactionStage;
  readonly updatedAt: string;
  readonly version: 1;
  readonly wikiPath: string;
};

export type VersionedTransactionState = {
  readonly state: C7TransactionState;
  readonly version: string;
};

export class C7TransactionStateError extends Error {
  constructor(
    readonly code: "invalid_state" | "stale_state" | "transition_invalid",
    message: string,
  ) {
    super(message);
    this.name = "C7TransactionStateError";
  }
}

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const stageSchema = z.enum(C7_TRANSACTION_STAGES);
const transactionStateSchema = z
  .strictObject({
    beforeWikiRootHash: hashSchema,
    createdAt: z.string().datetime({ offset: true }),
    generation: z.number().int().positive(),
    homePath: z.string().refine(path.isAbsolute),
    model: modelSelectionSchema,
    operation: z.enum(["query", "repair", "review", "update"]),
    pid: z.number().int().positive(),
    policyPath: z.string().refine(path.isAbsolute),
    reviewRequired: z.boolean(),
    runId: z.string().regex(/^run-[A-Za-z0-9._:-]{8,160}$/u),
    skillAggregateHash: hashSchema,
    sourceManifestHash: hashSchema.nullable(),
    stage: stageSchema,
    updatedAt: z.string().datetime({ offset: true }),
    version: z.literal(1),
    wikiPath: z.string().refine(path.isAbsolute),
  })
  .superRefine((state, context) => {
    const mutating =
      state.operation === "update" || state.operation === "repair";
    if (state.reviewRequired !== mutating) {
      context.addIssue({
        code: "custom",
        message: "reviewRequired does not match operation",
      });
    }
    if (!isWithin(state.homePath, state.wikiPath)) {
      context.addIssue({
        code: "custom",
        message: "wikiPath must stay inside homePath",
      });
    }
    if (isWithin(state.homePath, state.policyPath)) {
      context.addIssue({
        code: "custom",
        message: "policyPath must stay outside homePath",
      });
    }
    if (Date.parse(state.updatedAt) < Date.parse(state.createdAt)) {
      context.addIssue({
        code: "custom",
        message: "updatedAt precedes createdAt",
      });
    }
  });

const ALLOWED_TRANSITIONS: Readonly<
  Record<C7TransactionStage, ReadonlySet<C7TransactionStage>>
> = {
  attention: new Set(),
  completed: new Set(),
  failed: new Set(),
  model_complete: new Set(["validated", "completed", "failed"]),
  prepared: new Set(["running", "failed"]),
  publish_pending: new Set([
    "published_review_pending",
    "failed",
    "restore_failed",
  ]),
  published_review_pending: new Set(["completed", "attention"]),
  repairing: new Set(["reviewing", "attention", "failed"]),
  restore_failed: new Set(),
  reviewing: new Set([
    "completed",
    "repairing",
    "attention",
    "failed",
    "publish_pending",
  ]),
  running: new Set(["model_complete", "failed"]),
  validated: new Set(["reviewing", "completed", "failed"]),
};

export async function readTransactionState(
  statePath: string,
): Promise<VersionedTransactionState> {
  if (!path.isAbsolute(statePath)) throw invalidState();
  let bytes: Buffer;
  try {
    bytes = await readFile(statePath);
  } catch {
    throw invalidState();
  }
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw invalidState();
  }
  const parsed = transactionStateSchema.safeParse(value);
  if (!parsed.success) throw invalidState();
  return { state: parsed.data, version: hashBytes(bytes) };
}

export async function transitionTransactionState(
  statePath: string,
  expectedVersion: string,
  nextStage: C7TransactionStage,
  now: Date,
  security: TransactionPathSecurity,
): Promise<VersionedTransactionState> {
  if (
    !/^sha256:[a-f0-9]{64}$/u.test(expectedVersion) ||
    !stageSchema.safeParse(nextStage).success ||
    Number.isNaN(now.getTime())
  ) {
    throw new C7TransactionStateError(
      "transition_invalid",
      "The transaction state transition is invalid.",
    );
  }
  const current = await readTransactionState(statePath);
  if (current.version !== expectedVersion) {
    throw new C7TransactionStateError(
      "stale_state",
      "The transaction state changed after it was read.",
    );
  }
  if (!ALLOWED_TRANSITIONS[current.state.stage].has(nextStage)) {
    throw new C7TransactionStateError(
      "transition_invalid",
      "The transaction state transition is not allowed.",
    );
  }
  if (now.getTime() < Date.parse(current.state.updatedAt)) {
    throw new C7TransactionStateError(
      "transition_invalid",
      "The transaction state timestamp cannot move backward.",
    );
  }
  const next = transactionStateSchema.parse({
    ...current.state,
    generation: current.state.generation + 1,
    stage: nextStage,
    updatedAt: now.toISOString(),
  });
  const bytes = Buffer.from(`${JSON.stringify(next, null, 2)}\n`, "utf8");
  const temporaryPath = `${statePath}.${randomUUID()}.tmp`;
  try {
    const handle = await open(temporaryPath, "wx", 0o600);
    try {
      await handle.writeFile(bytes);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await security.securePrivatePath({
      directory: false,
      targetPath: temporaryPath,
    });
    const beforeRename = await readTransactionState(statePath);
    if (beforeRename.version !== expectedVersion) {
      throw new C7TransactionStateError(
        "stale_state",
        "The transaction state changed before commit.",
      );
    }
    await rename(temporaryPath, statePath);
  } catch (error) {
    await rm(temporaryPath, { force: true });
    throw error;
  }
  return { state: next, version: hashBytes(bytes) };
}

function invalidState(): C7TransactionStateError {
  return new C7TransactionStateError(
    "invalid_state",
    "The transaction state is missing or invalid.",
  );
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
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
import { createHash, randomUUID } from "node:crypto";
import { open, readFile, rename, rm } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { modelSelectionSchema } from "./contracts.js";
