import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  mkdir,
  open,
  readFile,
  realpath,
  rename,
  rm,
} from "node:fs/promises";
import type { FileHandle } from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const repositoryRoot = path.resolve(import.meta.dirname, "..");
const openWikiRoot = path.resolve(repositoryRoot, "..", ".work", "openwiki");
const runtimeDir = path.join(repositoryRoot, "runtime");
const evidencePath = path.join(runtimeDir, "verified-capabilities.json");
const temporaryEvidencePath = path.join(
  runtimeDir,
  ".verified-capabilities.tmp",
);
const testReportPath = path.join(runtimeDir, "capability-test-report.json");

export async function runCapabilityVerification(): Promise<void> {
  const repositoryIdentity = await bindCanonicalDirectory(repositoryRoot);
  const runtimeIdentity = await bindRuntimeDirectory(
    runtimeDir,
    repositoryIdentity,
  );
  await assertBoundDirectory(repositoryRoot, repositoryIdentity);
  await assertBoundDirectory(runtimeDir, runtimeIdentity);
  await Promise.all([
    rm(evidencePath, { force: true }),
    rm(temporaryEvidencePath, { force: true }),
    rm(testReportPath, { force: true }),
    rm(path.join(repositoryRoot, "mcp-server", "dist"), {
      force: true,
      recursive: true,
    }),
    rm(path.join(repositoryRoot, "win32-helper", "dist"), {
      force: true,
      recursive: true,
    }),
  ]);

  try {
    if (process.platform !== "win32") {
      throw new Error(
        "The initial local-path capability verifier requires Windows.",
      );
    }
    await run("pnpm", ["--config.enable-pre-post-scripts=false", "run", "build"], openWikiRoot);
    await run(
      "pnpm",
      ["install", "--frozen-lockfile", "--ignore-scripts"],
      path.join(repositoryRoot, "mcp-server"),
    );
    await run("pnpm", ["--dir", "mcp-server", "build"], repositoryRoot);
    await run(
      "pnpm",
      ["--dir", "mcp-server", "build:win32-helper"],
      repositoryRoot,
    );
    await run(
      "pnpm",
      [
        "--dir",
        "mcp-server",
        "exec",
        "vitest",
        "run",
        "--maxWorkers=1",
        "--reporter=json",
        `--outputFile=${testReportPath}`,
      ],
      repositoryRoot,
    );
    const report = JSON.parse(await readFile(testReportPath, "utf8")) as {
      numFailedTestSuites?: unknown;
      numFailedTests?: unknown;
      success?: unknown;
    };
    if (
      report.success !== true ||
      report.numFailedTestSuites !== 0 ||
      report.numFailedTests !== 0
    ) {
      throw new Error(
        "The machine-readable Vitest report is not fully passing.",
      );
    }
    await run("node", ["scripts/validate-skills.mts"], repositoryRoot);
    await run(
      "node",
      ["agent-skills/self-openwiki/evals/run-eval.mjs"],
      repositoryRoot,
    );

    const capabilitiesModule = await import(
      `${pathToFileURL(path.join(repositoryRoot, "mcp-server", "dist", "capabilities.js")).href}?build=${randomUUID()}`
    );
    const contractsModule = await import(
      `${pathToFileURL(path.join(repositoryRoot, "mcp-server", "dist", "contracts.js")).href}?build=${randomUUID()}`
    );
    await capabilitiesModule.validateCapabilityMatrix({ repositoryRoot });
    const fingerprint = await capabilitiesModule.computeCapabilityFingerprint({
      openWikiRoot,
      repositoryRoot,
    });
    const evidence = {
      arch: process.arch,
      buildId: randomUUID(),
      fingerprint,
      generatedBy: "scripts/verify-capabilities.mts",
      node: process.version,
      platform: process.platform,
      reports: {
        build: "passed",
        skillEval: "passed",
        tests: "passed",
        win32Integration: "passed",
      },
      tools: contractsModule.TOOL_NAMES as readonly string[],
      verifiedAt: new Date().toISOString(),
      verifierVersion: 1,
      version: 1,
    };
    const evidenceBytes = Buffer.from(
      `${JSON.stringify(evidence, null, 2)}\n`,
      "utf8",
    );
    await activateVerifiedCapabilityEvidence({
      bytes: evidenceBytes,
      finalPath: evidencePath,
      repositoryRoot,
      runtimeDir,
      stagedPath: temporaryEvidencePath,
      runSmoke: async (environment) =>
        run(
          "node",
          ["mcp-server/scripts/smoke-mcp.mjs"],
          repositoryRoot,
          environment,
        ),
    });
    process.stderr.write(`Verified capabilities: ${evidence.buildId}\n`);
  } catch (error) {
    process.stderr.write(
      `Capability verification failed: ${error instanceof Error ? error.message : "unknown error"}\n`,
    );
    process.exitCode = 1;
  }
}

export async function activateVerifiedCapabilityEvidence(options: {
  bytes: Buffer;
  environment?: NodeJS.ProcessEnv;
  finalPath: string;
  repositoryRoot: string;
  runSmoke?: (environment: NodeJS.ProcessEnv) => Promise<void>;
  runtimeDir: string;
  stagedPath: string;
}): Promise<void> {
  const repositoryRoot = path.resolve(options.repositoryRoot);
  const expectedRuntime = path.join(repositoryRoot, "runtime");
  const runtime = path.resolve(options.runtimeDir);
  const stagedPath = path.resolve(options.stagedPath);
  const finalPath = path.resolve(options.finalPath);
  if (
    runtime !== expectedRuntime ||
    stagedPath !== path.join(runtime, ".verified-capabilities.tmp") ||
    finalPath !== path.join(runtime, "verified-capabilities.json")
  ) {
    throw new Error("The staged capability evidence path is invalid.");
  }
  if (options.bytes.byteLength > 1024 * 1024) {
    throw new Error("The staged capability evidence is too large.");
  }

  const repositoryIdentity = await bindCanonicalDirectory(repositoryRoot);
  const runtimeIdentity = await bindRuntimeDirectory(
    runtime,
    repositoryIdentity,
  );
  await assertBoundDirectory(repositoryRoot, repositoryIdentity);
  await assertBoundDirectory(runtime, runtimeIdentity);
  await rm(finalPath, { force: true });
  let handle: FileHandle | undefined;
  try {
    await assertBoundDirectory(repositoryRoot, repositoryIdentity);
    await assertBoundDirectory(runtime, runtimeIdentity);
    handle = await open(stagedPath, "wx+", 0o600);
    await handle.writeFile(options.bytes);
    await handle.sync();
    const initialPathStat = await lstat(stagedPath, { bigint: true });
    const initialHandleStat = await handle.stat({ bigint: true });
    assertRegularSameEvidence(
      initialPathStat,
      initialHandleStat,
      options.bytes.byteLength,
    );
    const expectedHash = sha256(options.bytes);
    const initialBytes = await readHandleBytes(
      handle,
      options.bytes.byteLength,
    );
    if (sha256(initialBytes) !== expectedHash) throw invalidStagedEvidence();

    const environment = {
      ...(options.environment ?? process.env),
      SELF_OPENWIKI_STAGED_CAPABILITY_EVIDENCE_PATH: stagedPath,
    };
    await (options.runSmoke ?? (async () => undefined))(environment);

    await assertBoundDirectory(repositoryRoot, repositoryIdentity);
    await assertBoundDirectory(runtime, runtimeIdentity);
    const afterHandleStat = await handle.stat({ bigint: true });
    const afterPathStat = await lstat(stagedPath, { bigint: true });
    assertRegularSameEvidence(
      initialHandleStat,
      afterHandleStat,
      options.bytes.byteLength,
    );
    assertRegularSameEvidence(
      initialHandleStat,
      afterPathStat,
      options.bytes.byteLength,
    );
    const afterBytes = await readHandleBytes(handle, options.bytes.byteLength);
    if (
      sha256(afterBytes) !== expectedHash ||
      !afterBytes.equals(options.bytes)
    ) {
      throw invalidStagedEvidence();
    }
    await assertBoundDirectory(repositoryRoot, repositoryIdentity);
    await assertBoundDirectory(runtime, runtimeIdentity);
    await rename(stagedPath, finalPath);
    await assertBoundDirectory(repositoryRoot, repositoryIdentity);
    await assertBoundDirectory(runtime, runtimeIdentity);
    const finalStat = await lstat(finalPath, { bigint: true });
    assertRegularSameEvidence(
      initialHandleStat,
      finalStat,
      options.bytes.byteLength,
    );
  } catch (error) {
    if (
      (await isStillBoundDirectory(repositoryRoot, repositoryIdentity)) &&
      (await isStillBoundDirectory(runtime, runtimeIdentity))
    ) {
      await Promise.all([
        rm(stagedPath, { force: true }),
        rm(finalPath, { force: true }),
      ]);
    }
    throw error;
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

type BoundDirectory = {
  canonicalPath: string;
  stat: BigIntStat;
};

async function bindCanonicalDirectory(
  targetPath: string,
): Promise<BoundDirectory> {
  const stat = (await lstat(targetPath, { bigint: true })) as BigIntStat;
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("The capability repository directory is invalid.");
  }
  const canonicalPath = await realpath(targetPath);
  const canonicalStat = (await lstat(canonicalPath, {
    bigint: true,
  })) as BigIntStat;
  if (
    !canonicalStat.isDirectory() ||
    canonicalStat.isSymbolicLink() ||
    !sameIdentity(stat, canonicalStat)
  ) {
    throw new Error("The capability repository directory is invalid.");
  }
  return { canonicalPath, stat: canonicalStat };
}

async function bindRuntimeDirectory(
  runtime: string,
  repository: BoundDirectory,
): Promise<BoundDirectory> {
  try {
    const existing = await bindCanonicalDirectory(runtime);
    if (
      path.dirname(existing.canonicalPath) !== repository.canonicalPath ||
      path.basename(existing.canonicalPath) !== "runtime"
    ) {
      throw new Error("The capability runtime directory is invalid.");
    }
    return existing;
  } catch (error) {
    if (!isMissing(error)) {
      throw new Error("The capability runtime directory is invalid.");
    }
  }
  await assertBoundDirectory(path.dirname(runtime), repository);
  await mkdir(runtime, { mode: 0o700 });
  const created = await bindCanonicalDirectory(runtime);
  if (
    path.dirname(created.canonicalPath) !== repository.canonicalPath ||
    path.basename(created.canonicalPath) !== "runtime"
  ) {
    throw new Error("The capability runtime directory is invalid.");
  }
  return created;
}

async function assertBoundDirectory(
  targetPath: string,
  expected: BoundDirectory,
): Promise<void> {
  try {
    const current = await bindCanonicalDirectory(targetPath);
    if (
      current.canonicalPath === expected.canonicalPath &&
      sameIdentity(current.stat, expected.stat)
    ) {
      return;
    }
  } catch {
    // Collapse filesystem detail into the bounded verifier error below.
  }
  throw new Error("The capability runtime directory is invalid.");
}

async function isStillBoundDirectory(
  targetPath: string,
  expected: BoundDirectory,
): Promise<boolean> {
  try {
    await assertBoundDirectory(targetPath, expected);
    return true;
  } catch {
    return false;
  }
}

function sameIdentity(left: BigIntStat, right: BigIntStat): boolean {
  return left.dev === right.dev && left.ino === right.ino;
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

function isDirectExecution(importMetaUrl: string, argvPath?: string): boolean {
  return (
    argvPath !== undefined &&
    path.resolve(argvPath) === path.resolve(fileURLToPath(importMetaUrl))
  );
}

if (isDirectExecution(import.meta.url, process.argv[1])) {
  await runCapabilityVerification();
}

async function run(
  command: string,
  args: readonly string[],
  cwd: string,
  environment: NodeJS.ProcessEnv = { ...process.env, CI: "true" },
) {
  const isWindowsBatch =
    process.platform === "win32" && ["npm", "pnpm", "yarn"].includes(command);
  const executable = isWindowsBatch
    ? (process.env.ComSpec ?? "C:\\Windows\\System32\\cmd.exe")
    : command;
  const batchCommand =
    command === "pnpm" ? "corepack pnpm@10.33.2" : `${command}.cmd`;
  const spawnArgs = isWindowsBatch
    ? ["/d", "/s", "/c", batchCommand, ...args]
    : [...args];
  const child = spawn(executable, spawnArgs, {
    cwd,
    env: environment,
    shell: false,
    stdio: ["ignore", "inherit", "inherit"],
    windowsHide: true,
  });
  const code = await new Promise<number | null>((resolve, reject) => {
    child.once("error", reject);
    child.once("close", resolve);
  });
  if (code !== 0) throw new Error(`${command} ${args.join(" ")} failed.`);
}

type BigIntStat = Awaited<ReturnType<FileHandle["stat"]>> & {
  dev: bigint;
  ino: bigint;
  size: bigint;
};

function assertRegularSameEvidence(
  expected: BigIntStat,
  actual: BigIntStat,
  size: number,
): void {
  if (
    !expected.isFile() ||
    expected.isSymbolicLink() ||
    !actual.isFile() ||
    actual.isSymbolicLink() ||
    expected.dev !== actual.dev ||
    expected.ino !== actual.ino ||
    expected.size !== BigInt(size) ||
    actual.size !== BigInt(size)
  ) {
    throw invalidStagedEvidence();
  }
}

async function readHandleBytes(
  handle: FileHandle,
  size: number,
): Promise<Buffer> {
  const bytes = Buffer.alloc(size);
  let offset = 0;
  while (offset < size) {
    const { bytesRead } = await handle.read(
      bytes,
      offset,
      size - offset,
      offset,
    );
    if (bytesRead === 0) throw invalidStagedEvidence();
    offset += bytesRead;
  }
  return bytes;
}

function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function invalidStagedEvidence(): Error {
  return new Error("The staged capability evidence changed or is invalid.");
}
