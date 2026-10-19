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
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { AsyncLocalStorage } from "node:async_hooks";
import { z } from "zod";
import { modelSelectionSchema } from "./contracts.js";

export const C7_LOCK_ORDER = [
  "operation",
  "credentials",
  "config",
  "wiki",
  "manifests",
] as const;

export type C7LockName = (typeof C7_LOCK_ORDER)[number];

type HeldLockScope = {
  active: boolean;
  readonly canonicalRoot: string;
  readonly heldLocks: readonly C7LockName[];
  readonly parent: HeldLockScope | null;
};

const heldLockContext = new AsyncLocalStorage<HeldLockScope>();
const lockOwnerSchema = z.strictObject({
  createdAt: z.string().datetime({ offset: true }),
  instanceId: z.string().uuid(),
  pid: z.number().int().positive(),
  version: z.literal(1),
});

const verifiedModelSchema = z.strictObject({
  ...modelSelectionSchema.shape,
  providerAccepted: z.literal(true),
  providerReportedModel: z.string().max(256).optional(),
  verifiedAt: z.string().datetime({ offset: true }),
});

export const runtimeConfigSchema = z
  .strictObject({
    defaultModel: modelSelectionSchema,
    generation: z.number().int().positive(),
    initialized: z.literal(true),
    provider: z.literal("openai-chatgpt"),
    schemaVersion: z.literal(1),
    verifiedModels: z.array(verifiedModelSchema).min(1).max(128),
  })
  .superRefine((config, context) => {
    const defaultIsVerified = config.verifiedModels.some(
      (candidate) =>
        candidate.model === config.defaultModel.model &&
        candidate.reasoningEffort === config.defaultModel.reasoningEffort,
    );
    if (!defaultIsVerified) {
      context.addIssue({
        code: "custom",
        message: "defaultModel must have a matching verified model record",
      });
    }
    const verifiedKeys = config.verifiedModels.map(
      (candidate) => `${candidate.model}\0${candidate.reasoningEffort}`,
    );
    if (new Set(verifiedKeys).size !== verifiedKeys.length) {
      context.addIssue({
        code: "custom",
        message: "verifiedModels must not contain duplicate model/effort pairs",
      });
    }
  });

const defaultsSchema = z.strictObject({
  provider: z.literal("openai-chatgpt"),
  recommendedModel: modelSelectionSchema,
  schemaVersion: z.literal(1),
});

export type RuntimeConfig = z.infer<typeof runtimeConfigSchema>;
export type VersionedRuntimeConfig = {
  config: RuntimeConfig;
  version: string;
};

export class C7ConfigError extends Error {
  constructor(
    readonly code:
      | "busy"
      | "invalid_config"
      | "setup_required"
      | "stale_version",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "C7ConfigError";
  }
}

export async function loadDefaults(
  defaultsPath: string,
): Promise<z.infer<typeof defaultsSchema>> {
  return parseJsonFile(defaultsPath, defaultsSchema, "repository defaults");
}

export async function readRuntimeConfig(
  configPath: string,
): Promise<VersionedRuntimeConfig> {
  assertAbsoluteFilePath(configPath, "runtime config");
  let bytes: Buffer;
  try {
    bytes = await readFile(configPath);
  } catch (error) {
    throw new C7ConfigError(
      "invalid_config",
      "C7 runtime config is missing or unreadable.",
      { cause: error },
    );
  }

  return {
    config: parseJsonBytes(bytes, runtimeConfigSchema, "runtime config"),
    version: versionBytes(bytes),
  };
}

export async function readRuntimeConfigState(configPath: string): Promise<{
  config?: RuntimeConfig;
  version: string;
}> {
  assertAbsoluteFilePath(configPath, "runtime config");
  return readCurrentState(configPath);
}

export async function writeRuntimeConfigAtomic(
  configPath: string,
  config: unknown,
  expectedVersion: string,
  hooks: {
    beforeRename?(): void | Promise<void>;
    securePrivatePath?(input: {
      directory: boolean;
      targetPath: string;
    }): Promise<unknown>;
  } = {},
): Promise<VersionedRuntimeConfig> {
  assertAbsoluteFilePath(configPath, "runtime config");
  const parsed = parseValue(config, runtimeConfigSchema, "runtime config");
  const runtimeDir = path.dirname(configPath);
  await mkdir(runtimeDir, { mode: 0o700, recursive: true });
  await hooks.securePrivatePath?.({
    directory: true,
    targetPath: runtimeDir,
  });

  return withC7Locks(runtimeDir, ["config"], async () => {
    const current = await readCurrentState(configPath);
    if (current.version !== expectedVersion) {
      throw new C7ConfigError(
        "stale_version",
        "C7 runtime config changed after it was read.",
      );
    }
    const expectedGeneration = current.config
      ? current.config.generation + 1
      : 1;
    if (parsed.generation !== expectedGeneration) {
      throw new C7ConfigError(
        "stale_version",
        `C7 runtime config generation must advance to ${expectedGeneration}.`,
      );
    }

    const bytes = Buffer.from(`${JSON.stringify(parsed, null, 2)}\n`, "utf8");
    const temporaryPath = path.join(
      runtimeDir,
      `.config.json.${randomUUID()}.tmp`,
    );

    try {
      const handle = await open(temporaryPath, "wx", 0o600);
      try {
        await handle.writeFile(bytes);
        await handle.sync();
      } finally {
        await handle.close();
      }

      await hooks.securePrivatePath?.({
        directory: false,
        targetPath: temporaryPath,
      });

      await hooks.beforeRename?.();
      await rename(temporaryPath, configPath);
    } catch (error) {
      await rm(temporaryPath, { force: true });
      throw error;
    }

    return { config: parsed, version: versionBytes(bytes) };
  });
}

export function resolveModelSelection(
  config: RuntimeConfig | undefined,
  override?: unknown,
): {
  selection: z.infer<typeof modelSelectionSchema>;
  source: "override" | "runtime_default";
} {
  if (!config) {
    throw new C7ConfigError(
      "setup_required",
      "OpenWiki setup must complete before selecting a runtime model.",
    );
  }

  if (override !== undefined) {
    return {
      selection: parseValue(override, modelSelectionSchema, "model override"),
      source: "override",
    };
  }

  return { selection: config.defaultModel, source: "runtime_default" };
}

export async function withC7Locks<T>(
  runtimeDir: string,
  locks: readonly C7LockName[],
  operation: () => Promise<T>,
): Promise<T> {
  const held = nearestActiveLockScope(heldLockContext.getStore());
  if (held === undefined) {
    await mkdir(runtimeDir, { mode: 0o700, recursive: true });
  }
  const runtimeRoot = await realpath(runtimeDir).catch((error) => {
    throw new C7ConfigError(
      "invalid_config",
      "C7 runtime lock root cannot be resolved.",
      { cause: error },
    );
  });
  if (held !== undefined && held.canonicalRoot !== runtimeRoot) {
    throw new C7ConfigError(
      "invalid_config",
      "C7 locks cannot be nested across runtime roots.",
    );
  }
  const alreadyHeld = held?.heldLocks ?? [];
  if (locks.length > 0 && locks.every((lock) => alreadyHeld.includes(lock))) {
    return operation();
  }
  assertLockOrder(locks, alreadyHeld);
  const lockRoot = path.join(runtimeRoot, "locks");
  await mkdir(lockRoot, { mode: 0o700, recursive: true });
  const acquired: string[] = [];
  const scope: HeldLockScope = {
    active: true,
    canonicalRoot: runtimeRoot,
    heldLocks: [...alreadyHeld, ...locks],
    parent: held ?? null,
  };

  try {
    for (const lock of locks) {
      const lockPath = path.join(lockRoot, `${lock}.lock`);
      const instanceId = randomUUID();
      const pendingPath = path.join(
        lockRoot,
        `${lock}.pending.${process.pid}.${instanceId}`,
      );
      try {
        await mkdir(pendingPath, { mode: 0o700 });
        await writeFile(
          path.join(pendingPath, "owner.json"),
          `${JSON.stringify({
            createdAt: new Date().toISOString(),
            instanceId,
            pid: process.pid,
            version: 1,
          })}\n`,
          { encoding: "utf8", flag: "wx", mode: 0o600 },
        );
        await rename(pendingPath, lockPath);
      } catch (error) {
        await rm(pendingPath, { force: true, recursive: true }).catch(
          () => undefined,
        );
        if (await directoryExists(lockPath)) {
          throw new C7ConfigError("busy", `C7 ${lock} lock is already held.`, {
            cause: error,
          });
        }
        throw error;
      }
      acquired.push(lockPath);
    }

    return await heldLockContext.run(scope, operation);
  } finally {
    scope.active = false;
    for (const lockPath of acquired.reverse()) {
      await rm(lockPath, { force: true, recursive: true });
    }
  }
}

/**
 * Remove locks whose strictly parsed owner process is no longer alive. A
 * malformed owner or an ownership file that changes while read fails closed.
 */
export async function recoverStaleC7Locks(
  runtimeDir: string,
): Promise<readonly C7LockName[]> {
  if (!path.isAbsolute(runtimeDir)) {
    throw new C7ConfigError(
      "invalid_config",
      "C7 runtime directory must be absolute during lock recovery.",
    );
  }
  const lockRoot = path.join(runtimeDir, "locks");
  let entries;
  try {
    entries = await readdir(lockRoot, { withFileTypes: true });
  } catch (error) {
    if (hasErrorCode(error, "ENOENT")) return [];
    throw error;
  }
  const recovered: C7LockName[] = [];
  for (const entry of entries.sort((left, right) =>
    left.name < right.name ? -1 : 1,
  )) {
    const finalMatch =
      /^(operation|credentials|config|wiki|manifests)\.lock$/u.exec(entry.name);
    const pendingMatch =
      /^(operation|credentials|config|wiki|manifests)\.pending\.(\d+)\.([a-f0-9-]{36})$/u.exec(
        entry.name,
      );
    if (
      (!finalMatch && !pendingMatch) ||
      !entry.isDirectory() ||
      entry.isSymbolicLink()
    ) {
      throw new C7ConfigError(
        "invalid_config",
        "The C7 lock directory contains an invalid entry.",
      );
    }
    const match = finalMatch ?? pendingMatch!;
    const lock = match[1] as C7LockName;
    const lockPath = path.join(lockRoot, entry.name);
    const ownerPath = path.join(lockPath, "owner.json");
    let owner;
    try {
      const before = await lstat(ownerPath);
      if (!before.isFile() || before.isSymbolicLink()) {
        throw new Error("invalid lock owner file");
      }
      const bytes = await readFile(ownerPath);
      const after = await lstat(ownerPath);
      if (
        before.dev !== after.dev ||
        before.ino !== after.ino ||
        before.size !== after.size ||
        before.mtimeMs !== after.mtimeMs
      ) {
        throw new Error("lock owner changed while read");
      }
      owner = lockOwnerSchema.parse(JSON.parse(bytes.toString("utf8")));
      if (
        pendingMatch &&
        (owner.pid !== Number(pendingMatch[2]) ||
          owner.instanceId !== pendingMatch[3])
      ) {
        throw new Error("pending lock owner does not match its path");
      }
    } catch (error) {
      if (
        pendingMatch &&
        Number.isSafeInteger(Number(pendingMatch[2])) &&
        !isProcessAlive(Number(pendingMatch[2]))
      ) {
        await rm(lockPath, { recursive: true });
        continue;
      }
      throw new C7ConfigError(
        "invalid_config",
        `C7 ${lock} lock ownership cannot be verified.`,
        { cause: error },
      );
    }
    if (isProcessAlive(owner.pid)) continue;
    if (pendingMatch) {
      await rm(lockPath, { recursive: true });
      continue;
    }
    const quarantinePath = path.join(
      lockRoot,
      `${lock}.stale.${owner.instanceId}.${randomUUID()}`,
    );
    await rename(lockPath, quarantinePath);
    const movedOwner = lockOwnerSchema.parse(
      JSON.parse(
        await readFile(path.join(quarantinePath, "owner.json"), "utf8"),
      ),
    );
    if (movedOwner.instanceId !== owner.instanceId) {
      await rename(quarantinePath, lockPath).catch(() => undefined);
      throw new C7ConfigError(
        "invalid_config",
        `C7 ${lock} lock changed during stale recovery.`,
      );
    }
    await rm(quarantinePath, { recursive: true });
    recovered.push(lock);
  }
  return recovered;
}

async function directoryExists(directoryPath: string): Promise<boolean> {
  try {
    const stat = await lstat(directoryPath);
    return stat.isDirectory() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

export async function inspectC7Locks(
  runtimeDir: string,
): Promise<readonly { held: boolean; name: C7LockName }[]> {
  if (!path.isAbsolute(runtimeDir)) {
    throw new C7ConfigError(
      "invalid_config",
      "C7 runtime directory must be absolute during lock inspection.",
    );
  }
  const lockRoot = path.join(runtimeDir, "locks");
  return Promise.all(
    C7_LOCK_ORDER.map(async (name) => {
      try {
        const stat = await lstat(path.join(lockRoot, `${name}.lock`));
        return {
          held: stat.isDirectory() && !stat.isSymbolicLink(),
          name,
        };
      } catch (error) {
        if (hasErrorCode(error, "ENOENT")) return { held: false, name };
        throw error;
      }
    }),
  );
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (hasErrorCode(error, "ESRCH")) return false;
    if (hasErrorCode(error, "EPERM")) return true;
    throw error;
  }
}

function nearestActiveLockScope(
  scope: HeldLockScope | undefined,
): HeldLockScope | undefined {
  let current = scope;
  while (current !== undefined && !current.active) {
    current = current.parent ?? undefined;
  }
  return current;
}

function assertLockOrder(
  locks: readonly C7LockName[],
  alreadyHeld: readonly C7LockName[],
): void {
  let previous =
    alreadyHeld.length === 0
      ? -1
      : C7_LOCK_ORDER.indexOf(alreadyHeld[alreadyHeld.length - 1]);
  for (const lock of locks) {
    const current = C7_LOCK_ORDER.indexOf(lock);
    if (current <= previous) {
      throw new C7ConfigError(
        "invalid_config",
        "C7 locks must be acquired once each in the fixed lock order.",
      );
    }
    previous = current;
  }
}

async function readCurrentState(configPath: string): Promise<{
  config?: RuntimeConfig;
  version: string;
}> {
  try {
    const bytes = await readFile(configPath);
    return {
      config: parseJsonBytes(bytes, runtimeConfigSchema, "runtime config"),
      version: versionBytes(bytes),
    };
  } catch (error) {
    if (hasErrorCode(error, "ENOENT")) {
      return { version: "missing" };
    }
    throw error;
  }
}

async function parseJsonFile<T>(
  filePath: string,
  schema: z.ZodType<T>,
  label: string,
): Promise<T> {
  assertAbsoluteFilePath(filePath, label);
  let bytes: Buffer;
  try {
    bytes = await readFile(filePath);
  } catch (error) {
    throw new C7ConfigError("invalid_config", `${label} is unreadable.`, {
      cause: error,
    });
  }
  return parseJsonBytes(bytes, schema, label);
}

function parseJsonBytes<T>(
  bytes: Buffer,
  schema: z.ZodType<T>,
  label: string,
): T {
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    throw new C7ConfigError("invalid_config", `${label} is not valid JSON.`, {
      cause: error,
    });
  }
  return parseValue(value, schema, label);
}

function parseValue<T>(value: unknown, schema: z.ZodType<T>, label: string): T {
  const parsed = schema.safeParse(value);
  if (!parsed.success) {
    throw new C7ConfigError(
      "invalid_config",
      `${label} does not match schema version 1.`,
    );
  }
  return parsed.data;
}

function assertAbsoluteFilePath(value: string, label: string): void {
  if (!path.isAbsolute(value)) {
    throw new C7ConfigError(
      "invalid_config",
      `${label} path must be absolute.`,
    );
  }
}

function versionBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function hasErrorCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === code
  );
}
