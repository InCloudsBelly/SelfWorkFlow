import { lstat, open, readdir, rm } from "node:fs/promises";
import type { Dirent } from "node:fs";
import path from "node:path";
import { readTransactionState } from "./transaction-state.js";

export type TransactionRecoveryResult = {
  readonly cleanedHomes: number;
  readonly cleanedTransactions: number;
  readonly state: "clean" | "restore_failed";
};

export async function recoverAbandonedTransactions(
  runtimeDir: string,
  options: {
    afterScrub?(envPath: string): Promise<void> | void;
    isProcessAlive?(pid: number): boolean;
  } = {},
): Promise<TransactionRecoveryResult> {
  if (!path.isAbsolute(runtimeDir)) {
    return { cleanedHomes: 0, cleanedTransactions: 0, state: "restore_failed" };
  }
  const transactionRoot = path.join(runtimeDir, "transactions");
  const tempRoot = path.join(runtimeDir, "temp");
  const referencedHomes = new Set<string>();
  let cleanedTransactions = 0;
  let cleanedHomes = 0;
  try {
    for (const entry of await readDirectories(transactionRoot)) {
      if (!/^run-[A-Za-z0-9._:-]{8,160}$/u.test(entry.name)) {
        throw new Error("invalid transaction directory name");
      }
      const transactionDir = path.join(transactionRoot, entry.name);
      const { state } = await readTransactionState(
        path.join(transactionDir, "state.json"),
      );
      const expectedPolicyPath = path.join(transactionDir, "run-policy.json");
      const expectedWikiPath = path.join(state.homePath, "openwiki");
      if (
        state.runId !== entry.name ||
        !pathsEqual(state.policyPath, expectedPolicyPath) ||
        !pathsEqual(state.wikiPath, expectedWikiPath) ||
        !isStrictChild(tempRoot, state.homePath) ||
        !path.basename(state.homePath).startsWith("openwiki-smoke-") ||
        (options.isProcessAlive ?? isProcessAlive)(state.pid)
      ) {
        throw new Error("invalid or live abandoned transaction");
      }
      referencedHomes.add(normalizePath(state.homePath));
      if (await directoryExists(state.homePath)) {
        await scrubAndRemoveHome(state.homePath, options.afterScrub);
        cleanedHomes += 1;
      }
      await rm(transactionDir, {
        force: true,
        maxRetries: 20,
        recursive: true,
        retryDelay: 25,
      });
      cleanedTransactions += 1;
    }

    for (const entry of await readDirectories(tempRoot)) {
      if (!entry.name.startsWith("openwiki-smoke-")) {
        throw new Error("unexpected temporary Home entry");
      }
      const homePath = path.join(tempRoot, entry.name);
      if (referencedHomes.has(normalizePath(homePath))) continue;
      await scrubAndRemoveHome(homePath, options.afterScrub);
      cleanedHomes += 1;
    }
    return { cleanedHomes, cleanedTransactions, state: "clean" };
  } catch {
    return { cleanedHomes, cleanedTransactions, state: "restore_failed" };
  }
}

async function readDirectories(root: string): Promise<Dirent[]> {
  let entries;
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch (error) {
    if (hasErrorCode(error, "ENOENT")) return [];
    throw error;
  }
  for (const entry of entries) {
    const candidate = path.join(root, entry.name);
    const stat = await lstat(candidate);
    if (!entry.isDirectory() || entry.isSymbolicLink() || !stat.isDirectory()) {
      throw new Error("runtime recovery roots require regular directories");
    }
  }
  return entries;
}

async function scrubAndRemoveHome(
  homePath: string,
  afterScrub?: (envPath: string) => Promise<void> | void,
): Promise<void> {
  const stat = await lstat(homePath);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("temporary Home is not a regular directory");
  }
  const envPath = path.join(homePath, ".env");
  try {
    const envStat = await lstat(envPath);
    if (!envStat.isFile() || envStat.isSymbolicLink()) {
      throw new Error("managed env is not a regular file");
    }
    const handle = await open(envPath, "r+");
    try {
      await handle.truncate(0);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await afterScrub?.(envPath);
  } catch (error) {
    if (!hasErrorCode(error, "ENOENT")) throw error;
  }
  await rm(homePath, {
    force: true,
    maxRetries: 20,
    recursive: true,
    retryDelay: 25,
  });
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return !hasErrorCode(error, "ESRCH");
  }
}

async function directoryExists(candidate: string): Promise<boolean> {
  try {
    const stat = await lstat(candidate);
    return stat.isDirectory() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

function isStrictChild(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

function pathsEqual(left: string, right: string): boolean {
  return normalizePath(left) === normalizePath(right);
}

function normalizePath(value: string): string {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

function hasErrorCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === code
  );
}
