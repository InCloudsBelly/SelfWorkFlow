#!/usr/bin/env node
import { createHash, randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdtempSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  OFFICIAL_UPSTREAM_URL,
  canonicalManifestBytes,
  materializeOpenWiki,
  parseUpdateCommit,
  verifyGeneratedRoot,
  validateManifest,
} from "./materialize-openwiki.mjs";
import { computeParentSourceManifestSync } from "./parent-source-manifest.mjs";

const TAG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$/u;
const COMMIT_PATTERN = /^[0-9a-f]{40}$/u;
const UPDATE_JOURNAL_DOMAIN = "selfopenwiki:upstream-update-journal:v1";
const UPDATE_JOURNAL_PATH = ".selfopenwiki-upstream-update-journal.json";
const UPDATE_LOCK_PATH = ".selfopenwiki-upstream-update.lock";
const COMPATIBILITY_PATHS = [
  "patches/openwiki/manifest.json",
  "scripts/materialize-openwiki.mjs",
  "scripts/build-win32-helper.mjs",
  "scripts/update-upstream.mjs",
  "test/repository-contract.test.mjs",
  "test/materialize-openwiki.test.mjs",
  "test/update-upstream.v2.test.mjs",
  "README.md",
  "docs/specs/2026-09-10-selfopenwiki-v2-openwiki-integration-design.md",
  "docs/testing/2026-09-10-selfopenwiki-v2-test-design.md",
  "docs/plans/2026-09-10-selfopenwiki-v2-implementation-plan.md",
  "self-openwiki/config/personal-openwiki-compatibility.json",
  "self-openwiki/config/capability-matrix.json",
  "self-openwiki/agent-skills/self-openwiki/SKILL.md",
  "self-openwiki/agent-skills/self-openwiki/references/mcp-contract.md",
  "self-openwiki/agent-skills/self-openwiki/references/migration-v2.md",
  "self-openwiki/mcp-server/src/personal-skill-adapter.ts",
  "self-openwiki/mcp-server/src/contracts.ts",
  "self-openwiki/mcp-server/src/runtime.ts",
  "self-openwiki/mcp-server/src/server.ts",
  "self-openwiki/mcp-server/src/bootstrap.ts",
  "self-openwiki/mcp-server/src/official-lifecycle-adapter.ts",
  "self-openwiki/mcp-server/src/personal-candidate-marker.ts",
  "self-openwiki/mcp-server/src/personal-claims.ts",
  "self-openwiki/mcp-server/src/personal-run-store.ts",
  "self-openwiki/mcp-server/src/personal-wiki-snapshot.ts",
  "self-openwiki/mcp-server/src/personal-wiki-lifecycle.ts",
  "self-openwiki/mcp-server/src/personal-wiki-root.ts",
  "self-openwiki/mcp-server/scripts/personal-tool-bindings.mjs",
  "self-openwiki/mcp-server/test/runtime.c7.ts",
  "self-openwiki/mcp-server/test/personal-lifecycle.v2.ts",
  "self-openwiki/mcp-server/test/personal-compatibility.v2.ts",
  "self-openwiki/mcp-server/test/mcp-surface.v2.ts",
  "self-openwiki/mcp-server/test/official-lifecycle-adapter.v2.ts",
  "self-openwiki/mcp-server/test/personal-candidate-marker.v2.ts",
  "self-openwiki/mcp-server/test/personal-claims.v2.ts",
  "self-openwiki/mcp-server/test/personal-root.v2.ts",
  "self-openwiki/mcp-server/test/personal-run-store.v2.ts",
  "self-openwiki/mcp-server/test/skill-adaptation.v2.ts",
];
const ADAPTER_SOURCE_PATHS = [
  "mcp-server/src/contracts.ts",
  "mcp-server/src/external-update-state.ts",
  "mcp-server/src/external-update-transaction.ts",
  "mcp-server/src/official-lifecycle-adapter.ts",
  "mcp-server/src/personal-candidate-marker.ts",
  "mcp-server/src/personal-claims.ts",
  "mcp-server/src/personal-run-store.ts",
  "mcp-server/src/personal-wiki-snapshot.ts",
  "mcp-server/src/personal-skill-adapter.ts",
  "mcp-server/src/personal-wiki-lifecycle.ts",
  "mcp-server/src/personal-wiki-root.ts",
  "mcp-server/src/publish.ts",
  "mcp-server/src/recovery.ts",
  "mcp-server/src/runtime.ts",
  "mcp-server/src/server.ts",
  "mcp-server/src/transaction.ts",
  "mcp-server/src/transaction-recovery.ts",
];

function parseTag(args) {
  if (
    args.length !== 2 ||
    args[0] !== "--tag" ||
    typeof args[1] !== "string" ||
    !TAG_PATTERN.test(args[1]) ||
    args[1].includes("..") ||
    args[1].includes("//") ||
    args[1].endsWith("/") ||
    args[1].endsWith(".lock") ||
    args[1].includes("@{")
  ) {
    throw new Error(
      "Update-Upstream requires one explicit 40-character commit or --tag <reviewed-tag>.",
    );
  }
  return args[1];
}

export function resolveRemoteTag(tag, remoteUrl = OFFICIAL_UPSTREAM_URL) {
  const tagRef = `refs/tags/${tag}`;
  const peeledRef = `${tagRef}^{}`;
  const result = spawnSync(
    "git",
    ["ls-remote", "--exit-code", remoteUrl, tagRef, peeledRef],
    {
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
      windowsHide: true,
    },
  );
  if (result.error || result.status !== 0) {
    throw new Error(
      `The reviewed upstream tag could not be resolved remotely: ${tag}.`,
    );
  }
  const refs = new Map();
  for (const line of result.stdout.trim().split(/\r?\n/u).filter(Boolean)) {
    const [object, ref] = line.split(/\s+/u);
    if (/^[0-9a-f]{40}$/u.test(object) && ref !== undefined) {
      refs.set(ref, object);
    }
  }
  const tagObject = refs.get(tagRef);
  const peeledCommit = refs.get(peeledRef);
  if (tagObject === undefined || peeledCommit === undefined) {
    throw new Error(
      `The upstream tag must resolve to an annotated tag and peeled commit: ${tag}.`,
    );
  }
  return { tagObject, peeledCommit };
}

export function createUpstreamUpdatePlan(args, options = {}) {
  let commit;
  let selection;
  if (args.length === 1 && !args[0].startsWith("--")) {
    commit = parseUpdateCommit(args);
  } else {
    const tag = parseTag(args);
    const resolved = (options.resolveTag ?? resolveRemoteTag)(tag);
    if (
      !resolved ||
      !/^[0-9a-f]{40}$/u.test(resolved.tagObject) ||
      !/^[0-9a-f]{40}$/u.test(resolved.peeledCommit)
    ) {
      throw new Error("The reviewed upstream tag resolution is invalid.");
    }
    commit = resolved.peeledCommit;
    selection = {
      kind: "tag",
      name: tag,
      remote: OFFICIAL_UPSTREAM_URL,
      tagObject: resolved.tagObject,
      peeledCommit: resolved.peeledCommit,
    };
  }
  return {
    schemaVersion: 1,
    domain: "selfopenwiki:manual-upstream-update-plan:v1",
    commit,
    ...(selection === undefined ? {} : { selection }),
    actions: [
      "review-official-commit",
      "refresh-gitlink",
      "refresh-zero-patch-manifest",
      "adapt-personal-skill",
      "refresh-capability-evidence",
      "review-and-confirm-new-contract",
    ],
    automaticRemoteSelection: false,
    mutatesRepository: false,
  };
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map((item) => canonicalize(item));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort((left, right) => Buffer.from(left).compare(Buffer.from(right)))
        .map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function canonicalJsonBytes(value) {
  return Buffer.from(`${JSON.stringify(canonicalize(value))}\n`, "utf8");
}

function sha256(bytes) {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function isWithin(root, candidate) {
  const rootPath = resolve(root);
  const candidatePath = resolve(candidate);
  const suffix = relative(rootPath, candidatePath);
  return suffix === "" || (!suffix.startsWith(`..${sep}`) && suffix !== "..");
}

function atomicWriteFile(filePath, bytes, mode = 0o600) {
  mkdirSync(resolve(filePath, ".."), { recursive: true, mode: 0o700 });
  assertNoReparsePath(resolve(filePath, ".."), filePath, {
    allowMissingLeaf: true,
  });
  const temporaryPath = `${filePath}.${randomUUID()}.tmp`;
  const descriptor = openSync(temporaryPath, "wx", mode);
  try {
    writeFileSync(descriptor, bytes);
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
  try {
    assertNoReparsePath(resolve(filePath, ".."), filePath, {
      allowMissingLeaf: true,
    });
    renameSync(temporaryPath, filePath);
  } catch (error) {
    rmSync(temporaryPath, { force: true });
    throw error;
  }
}

function hashFile(repositoryRoot, relativePath) {
  return sha256(readFileSync(join(repositoryRoot, ...relativePath.split("/"))));
}

function journalPath(repositoryRoot) {
  return join(repositoryRoot, UPDATE_JOURNAL_PATH);
}

function writeUpdateJournal(filePath, journal) {
  atomicWriteFile(filePath, canonicalJsonBytes(journal));
}

function readUpdateJournal(filePath) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(filePath, "utf8"));
  } catch (error) {
    throw new Error("The interrupted upstream update journal is unreadable.", {
      cause: error,
    });
  }
  if (
    parsed === null ||
    typeof parsed !== "object" ||
    parsed.schemaVersion !== 1 ||
    parsed.domain !== UPDATE_JOURNAL_DOMAIN ||
    typeof parsed.sourceCommit !== "string" ||
    !COMMIT_PATTERN.test(parsed.sourceCommit) ||
    typeof parsed.targetCommit !== "string" ||
    !COMMIT_PATTERN.test(parsed.targetCommit) ||
    typeof parsed.transactionRelative !== "string" ||
    !Array.isArray(parsed.files) ||
    typeof parsed.generatedExisted !== "boolean" ||
    typeof parsed.generatedBackupRelative !== "string" ||
    parsed.gitlink === null ||
    typeof parsed.gitlink !== "object" ||
    parsed.gitlink.mode !== "160000" ||
    typeof parsed.gitlink.commit !== "string" ||
    !COMMIT_PATTERN.test(parsed.gitlink.commit)
  ) {
    throw new Error("The interrupted upstream update journal is invalid.");
  }
  if (
    ![
      "prepared",
      "backup",
      "manifest",
      "bindings",
      "source",
      "generated",
      "compatibility",
      "verified",
      "gitlink",
      "adopted",
    ].includes(parsed.state) ||
    !/^\.work\/\.selfopenwiki-upstream-update-[^/]+$/u.test(
      parsed.transactionRelative,
    ) ||
    parsed.generatedBackupRelative !==
      `${parsed.transactionRelative}/generated`
  ) {
    throw new Error("The interrupted upstream update journal paths are invalid.");
  }
  const seen = new Set();
  for (const entry of parsed.files) {
    if (
      entry === null ||
      typeof entry !== "object" ||
      typeof entry.path !== "string" ||
      !COMPATIBILITY_PATHS.includes(entry.path) ||
      seen.has(entry.path) ||
      typeof entry.bytes !== "string" ||
      !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u.test(entry.bytes) ||
      !Number.isSafeInteger(entry.mode) ||
      entry.mode < 0 ||
      entry.mode > 0o777 ||
      typeof entry.byteLength !== "number" ||
      entry.byteLength !== Buffer.from(entry.bytes, "base64").byteLength ||
      typeof entry.byteHash !== "string" ||
      entry.byteHash !== sha256(Buffer.from(entry.bytes, "base64"))
    ) {
      throw new Error("The interrupted upstream update journal file entry is invalid.");
    }
    seen.add(entry.path);
  }
  return parsed;
}

function ownedUpdatePath(repositoryRoot, relativePath) {
  const candidate = resolve(repositoryRoot, ...relativePath.split("/"));
  if (!isWithin(join(repositoryRoot, ".work"), candidate)) {
    throw new Error("The upstream update journal points outside .work.");
  }
  assertNoReparsePath(repositoryRoot, candidate, { allowMissingLeaf: true });
  return candidate;
}

function restoreJournalFiles(repositoryRoot, journal) {
  for (const entry of journal.files) {
    if (!COMPATIBILITY_PATHS.includes(entry.path)) {
      throw new Error(
        "The interrupted upstream update journal file entry is invalid.",
      );
    }
    const absolutePath = resolve(repositoryRoot, ...entry.path.split("/"));
    if (!isWithin(repositoryRoot, absolutePath)) {
      throw new Error(
        "The interrupted upstream update journal escapes the repository.",
      );
    }
    assertNoReparsePath(repositoryRoot, absolutePath, { allowMissingLeaf: true });
    atomicWriteFile(
      absolutePath,
      Buffer.from(entry.bytes, "base64"),
      entry.mode,
    );
    chmodSync(absolutePath, entry.mode);
  }
}

function removeGeneratedUpdateArtifacts(generatedRoot) {
  for (const ownedPath of [
    generatedRoot,
    `${generatedRoot}.candidate`,
    `${generatedRoot}.last-good`,
    `${generatedRoot}.materialization-journal.json`,
    `${generatedRoot}.materialization-lock`,
  ]) {
    assertNoReparsePath(resolve(generatedRoot, ".."), ownedPath, {
      allowMissingLeaf: true,
    });
    if (existsSync(ownedPath))
      rmSync(ownedPath, { recursive: true, force: true });
  }
}

function recoverInterruptedUpdate(repositoryRoot) {
  const currentJournalPath = journalPath(repositoryRoot);
  if (!existsSync(currentJournalPath)) return;
  const journal = readUpdateJournal(currentJournalPath);
  const transactionRoot = ownedUpdatePath(
    repositoryRoot,
    journal.transactionRelative,
  );
  const generatedBackup = ownedUpdatePath(
    repositoryRoot,
    journal.generatedBackupRelative,
  );
  if (journal.state === "adopted") {
    assertNoReparsePath(repositoryRoot, transactionRoot);
    rmSync(transactionRoot, { recursive: true, force: true });
    assertNoReparsePath(repositoryRoot, currentJournalPath);
    rmSync(currentJournalPath, { force: true });
    return;
  }
  const sourceRoot = join(repositoryRoot, "upstream", "openwiki");
  const currentSourceCommit = runGit(sourceRoot, ["rev-parse", "HEAD"]).stdout;
  const sourceStatus = runGit(sourceRoot, [
    "status",
    "--porcelain",
    "--untracked-files=all",
  ]).stdout;
  if (sourceStatus !== "") {
    throw new Error(
      "An interrupted upstream update requires manual Submodule recovery.",
    );
  }
  if (currentSourceCommit !== journal.sourceCommit) {
    throw new Error(
      "An interrupted upstream update requires manual Submodule recovery; the active Submodule will not be checked out or reset.",
    );
  }
  restoreJournalFiles(repositoryRoot, journal);
  const generatedRoot = join(repositoryRoot, ".work", "openwiki");
  const manifestPath = join(
    repositoryRoot,
    "patches",
    "openwiki",
    "manifest.json",
  );
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const manifestHash = sha256(canonicalManifestBytes(manifest));
  const generatedRootIsRecoverable =
    journal.generatedExisted &&
    !existsSync(generatedBackup) &&
    verifyGeneratedRoot(
      generatedRoot,
      journal.sourceCommit,
      manifest,
      manifestHash,
    );
  if (journal.generatedExisted) {
    if (!existsSync(generatedBackup) && !generatedRootIsRecoverable) {
      throw new Error("The interrupted upstream generated backup is missing.");
    }
    if (existsSync(generatedBackup)) {
      removeGeneratedUpdateArtifacts(generatedRoot);
      assertNoReparsePath(repositoryRoot, generatedBackup);
      assertNoReparsePath(repositoryRoot, generatedRoot, { allowMissingLeaf: true });
      renameSync(generatedBackup, generatedRoot);
    }
  } else {
    removeGeneratedUpdateArtifacts(generatedRoot);
  }
  restoreGitlink(repositoryRoot, journal.gitlink);
  assertNoReparsePath(repositoryRoot, transactionRoot);
  rmSync(transactionRoot, { recursive: true, force: true });
  assertNoReparsePath(repositoryRoot, currentJournalPath);
  rmSync(currentJournalPath, { force: true });
}

function updateJournalState(repositoryRoot, journal, state) {
  const next = { ...journal, state };
  writeUpdateJournal(journalPath(repositoryRoot), next);
  return next;
}

function computeAdapterSetHash(repositoryRoot) {
  const entries = ADAPTER_SOURCE_PATHS.map((relativePath) => {
    const bytes = readFileSync(
      join(repositoryRoot, ...relativePath.split("/")),
    );
    return {
      bytes,
      digest: createHash("sha256").update(bytes).digest(),
      relativePath,
    };
  }).sort((left, right) =>
    Buffer.from(left.relativePath, "utf8").compare(
      Buffer.from(right.relativePath, "utf8"),
    ),
  );
  const hasher = createHash("sha256");
  hasher.update("selfopenwiki-adapter-set-v1\0", "utf8");
  for (const entry of entries) {
    const pathBytes = Buffer.from(entry.relativePath, "utf8");
    const pathLength = Buffer.alloc(4);
    pathLength.writeUInt32BE(pathBytes.byteLength, 0);
    hasher.update(pathLength);
    hasher.update(pathBytes);
    hasher.update(entry.digest);
    const byteLength = Buffer.alloc(8);
    byteLength.writeBigUInt64BE(BigInt(entry.bytes.byteLength), 0);
    hasher.update(byteLength);
  }
  return `sha256:${hasher.digest("hex")}`;
}

function runGit(cwd, args, { allowFailure = false } = {}) {
  const environment = { ...process.env };
  const nullDevice = process.platform === "win32" ? "NUL" : "/dev/null";
  for (const key of [
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_ASKPASS",
    "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PROXY_COMMAND",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_WORK_TREE",
  ]) {
    delete environment[key];
  }
  Object.assign(environment, {
    GIT_CONFIG_COUNT: "0",
    GIT_CONFIG_GLOBAL: nullDevice,
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_SYSTEM: nullDevice,
    GIT_OPTIONAL_LOCKS: "0",
    GIT_TERMINAL_PROMPT: "0",
  });
  const result = spawnSync(
    "git",
    ["-c", `core.hooksPath=${nullDevice}`, ...args],
    {
      cwd,
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
      shell: false,
      windowsHide: true,
      env: environment,
    },
  );
  if (result.error) throw result.error;
  if (result.status !== 0 && !allowFailure) {
    const detail = `${result.stderr ?? ""}${result.stdout ?? ""}`.trim();
    throw new Error(`git ${args[0]} failed${detail ? `: ${detail}` : "."}`);
  }
  return {
    status: result.status,
    stdout: (result.stdout ?? "").trim(),
    stderr: (result.stderr ?? "").trim(),
  };
}

function runCommand(command, args, cwd) {
  const windowsCorepack = process.platform === "win32" && command === "corepack";
  const executable = windowsCorepack
    ? process.env.ComSpec ?? "cmd.exe"
    : command;
  const executableArgs = windowsCorepack
    ? ["/d", "/s", "/c", "corepack.cmd", ...args]
    : args;
  const result = spawnSync(executable, executableArgs, {
    cwd,
    encoding: "utf8",
    maxBuffer: 8 * 1024 * 1024,
    shell: false,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = `${result.stderr ?? ""}${result.stdout ?? ""}`.trim();
    throw new Error(
      `${command} ${args[0] ?? ""} failed${detail ? `: ${detail}` : "."}`,
    );
  }
}

function runCommandOutput(command, args, cwd) {
  const windowsCorepack = process.platform === "win32" && command === "corepack";
  const executable = windowsCorepack
    ? process.env.ComSpec ?? "cmd.exe"
    : command;
  const executableArgs = windowsCorepack
    ? ["/d", "/s", "/c", "corepack.cmd", ...args]
    : args;
  const result = spawnSync(executable, executableArgs, {
    cwd,
    encoding: "utf8",
    maxBuffer: 8 * 1024 * 1024,
    shell: false,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = `${result.stderr ?? ""}${result.stdout ?? ""}`.trim();
    throw new Error(
      `${command} ${args[0] ?? ""} failed${detail ? `: ${detail}` : "."}`,
    );
  }
  return result.stdout ?? "";
}

export function updateCompatibilityManifest(repositoryRoot, generatedRoot, commit) {
  const compatibilityPath = join(
    repositoryRoot,
    "self-openwiki",
    "config",
    "personal-openwiki-compatibility.json",
  );
  const manifest = JSON.parse(readFileSync(compatibilityPath, "utf8"));
  const packageJson = JSON.parse(
    readFileSync(join(generatedRoot, "package.json"), "utf8"),
  );
  manifest.upstream.commit = commit;
  manifest.upstream.packageVersion = packageJson.version;
  if (manifest.skill !== null && typeof manifest.skill === "object") {
    manifest.skill.packageHash = computeSkillPackageHashSync(
      join(repositoryRoot, "self-openwiki", "agent-skills", "self-openwiki"),
    );
  }
  manifest.build.adapterSetHash = computeAdapterSetHash(
    join(repositoryRoot, "self-openwiki"),
  );
  manifest.build.generatedMarkerHash = sha256(
    readFileSync(join(generatedRoot, ".selfopenwiki-materialization.json")),
  );
  manifest.build.lockfileHash = hashFile(
    join(repositoryRoot, "self-openwiki"),
    "mcp-server/pnpm-lock.yaml",
  );
  manifest.build.parentCommit = runGit(repositoryRoot, [
    "rev-parse",
    "HEAD",
  ]).stdout;
  manifest.build.parentSourceManifestHash = computeParentSourceManifestSync(
    repositoryRoot,
  ).hash;
  if (manifest.toolBindings !== undefined) {
    runCommand(
      "corepack",
      ["pnpm@10.33.2", "--dir", join(repositoryRoot, "self-openwiki", "mcp-server"), "run", "build"],
      join(repositoryRoot, "self-openwiki", "mcp-server"),
    );
    const bindingsOutput = runCommandOutput(
      process.execPath,
      [
        join(
          repositoryRoot,
          "self-openwiki",
          "mcp-server",
          "scripts",
          "personal-tool-bindings.mjs",
        ),
      ],
      join(repositoryRoot, "self-openwiki", "mcp-server"),
    ).trim();
    const toolBindings = JSON.parse(bindingsOutput);
    if (
      toolBindings === null ||
      typeof toolBindings !== "object" ||
      Array.isArray(toolBindings) ||
      Object.keys(toolBindings).length !== 6
    ) {
      throw new Error("The personal tool binding generator returned invalid data.");
    }
    manifest.toolBindings = toolBindings;
  }
  atomicWriteFile(compatibilityPath, canonicalJsonBytes(manifest));
}

function computeSkillPackageHashSync(skillRoot) {
  const files = [];
  collectSkillFilesSync(skillRoot, "", files);
  files.sort((left, right) =>
    left.relativePath < right.relativePath
      ? -1
      : left.relativePath > right.relativePath
        ? 1
        : 0,
  );
  const packageHasher = createHash("sha256");
  packageHasher.update("kg-c7-skill-package-v1\0", "utf8");
  for (const file of files) {
    const pathBytes = Buffer.from(file.relativePath, "utf8");
    packageHasher.update(String(pathBytes.byteLength), "ascii");
    packageHasher.update(":", "ascii");
    packageHasher.update(pathBytes);
    packageHasher.update("\0", "ascii");
    packageHasher.update(String(file.bytes.byteLength), "ascii");
    packageHasher.update("\0", "ascii");
    packageHasher.update(file.bytes);
    packageHasher.update("\0", "ascii");
  }
  return `sha256:${packageHasher.digest("hex")}`;
}

function collectSkillFilesSync(root, relativeDirectory, files) {
  const directory = relativeDirectory === "" ? root : join(root, relativeDirectory);
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const relativePath = relativeDirectory
      ? join(relativeDirectory, entry.name)
      : entry.name;
    const normalizedPath = relativePath.split(sep).join("/");
    const absolutePath = join(root, relativePath);
    const stats = lstatSync(absolutePath);
    if (entry.isSymbolicLink() || stats.isSymbolicLink()) {
      throw new Error(`Skill packages cannot contain links: ${normalizedPath}`);
    }
    if (entry.isDirectory() && stats.isDirectory()) {
      collectSkillFilesSync(root, relativePath, files);
      continue;
    }
    if (!entry.isFile() || !stats.isFile()) {
      throw new Error(`Skill packages can contain only regular files: ${normalizedPath}`);
    }
    files.push({ bytes: readFileSync(absolutePath), relativePath: normalizedPath });
  }
}

function captureFile(repositoryRoot, relativePath) {
  const absolutePath = join(repositoryRoot, ...relativePath.split("/"));
  assertNoReparsePath(repositoryRoot, absolutePath);
  if (!existsSync(absolutePath)) {
    throw new Error(
      `Upstream update binding file is missing: ${relativePath}.`,
    );
  }
  const stats = lstatSync(absolutePath);
  if (!stats.isFile() || stats.isSymbolicLink()) {
    throw new Error(
      `Upstream update binding file is not a regular file: ${relativePath}.`,
    );
  }
  return {
    bytes: readFileSync(absolutePath),
    mode: stats.mode & 0o777,
    relativePath,
  };
}

function replaceCommitBindings(repositoryRoot, previousCommit, nextCommit) {
  let changedFiles = 0;
  let changedReferences = 0;
  for (const relativePath of COMPATIBILITY_PATHS) {
    if (relativePath === "patches/openwiki/manifest.json") continue;
    const absolutePath = join(repositoryRoot, ...relativePath.split("/"));
    assertNoReparsePath(repositoryRoot, absolutePath);
    const before = readFileSync(absolutePath, "utf8");
    const occurrences = before.split(previousCommit).length - 1;
    if (occurrences === 0) continue;
    const after = before.split(previousCommit).join(nextCommit);
    atomicWriteFile(absolutePath, Buffer.from(after, "utf8"));
    changedFiles += 1;
    changedReferences += occurrences;
  }
  return { changedFiles, changedReferences };
}

function assertNoReparsePath(root, candidate, options = {}) {
  const canonicalRoot = resolve(root);
  const absoluteCandidate = resolve(candidate);
  if (!isWithin(canonicalRoot, absoluteCandidate)) {
    throw new Error("The updater path escapes its declared root.");
  }
  const suffix = relative(canonicalRoot, absoluteCandidate);
  const segments = suffix === "" ? [] : suffix.split(sep);
  let current = canonicalRoot;
  for (let index = -1; index < segments.length; index += 1) {
    if (index >= 0) current = join(current, segments[index]);
    let stats;
    try {
      stats = lstatSync(current);
    } catch (error) {
      if (
        options.allowMissingLeaf === true &&
        index === segments.length - 1 &&
        error?.code === "ENOENT"
      ) {
        return;
      }
      throw error;
    }
    if (stats.isSymbolicLink()) {
      throw new Error("The updater refuses symbolic-link or junction paths.");
    }
    if (index < segments.length - 1 && !stats.isDirectory()) {
      throw new Error("The updater path contains a non-directory ancestor.");
    }
  }
}

function readGitlink(repositoryRoot) {
  const line = runGit(repositoryRoot, [
    "ls-files",
    "-s",
    "--",
    "upstream/openwiki",
  ]).stdout;
  const match = /^(160000) ([0-9a-f]{40}) 0\tupstream\/openwiki$/u.exec(line);
  if (!match)
    throw new Error("The parent upstream/openwiki gitlink is invalid.");
  return { mode: match[1], commit: match[2], line };
}

function restoreGitlink(repositoryRoot, snapshot) {
  runGit(repositoryRoot, [
    "update-index",
    "--cacheinfo",
    `${snapshot.mode},${snapshot.commit},${upstreamGitlinkIndexPath(repositoryRoot)}`,
  ]);
}

function upstreamGitlinkIndexPath(repositoryRoot) {
  // update-index cacheinfo paths are root-relative even when cwd is a module.
  return `${runGit(repositoryRoot, ["rev-parse", "--show-prefix"]).stdout}upstream/openwiki`;
}

function assertNoUnmergedParentPaths(repositoryRoot) {
  if (runGit(repositoryRoot, ["ls-files", "-u", "--"]).stdout !== "") {
    throw new Error("The parent repository has unresolved index conflicts.");
  }
}

function defaultVerify(generatedRoot) {
  runCommand(
    "corepack",
    [
      "pnpm@10.33.2",
      "--dir",
      generatedRoot,
      "install",
      "--frozen-lockfile",
      "--ignore-scripts",
    ],
    generatedRoot,
  );
  runCommand(
    "corepack",
    ["pnpm@10.33.2", "--dir", generatedRoot, "run", "build"],
    generatedRoot,
  );
  const repositoryRoot = resolve(generatedRoot, "..", "..");
  const mcpRoot = join(repositoryRoot, "self-openwiki", "mcp-server");
  runCommand(
    "corepack",
    ["pnpm@10.33.2", "--dir", mcpRoot, "install", "--frozen-lockfile", "--ignore-scripts"],
    mcpRoot,
  );
  runCommand(
    "corepack",
    ["pnpm@10.33.2", "--dir", mcpRoot, "run", "build"],
    mcpRoot,
  );
  runCommand(
    "corepack",
    ["pnpm@10.33.2", "--dir", mcpRoot, "exec", "vitest", "run", "--maxWorkers=1"],
    mcpRoot,
  );
  runCommand(
    process.execPath,
    [join(repositoryRoot, "self-openwiki", "scripts", "validate-skills.mts")],
    repositoryRoot,
  );
  runCommand(
    process.execPath,
    [join(repositoryRoot, "self-openwiki", "agent-skills", "self-openwiki", "evals", "run-eval.mjs")],
    repositoryRoot,
  );
}

export function applyUpstreamUpdate(args, options = {}) {
  if (options.confirmed !== true) {
    throw new Error(
      "Applying an upstream update requires explicit confirmation.",
    );
  }
  const repositoryRoot = resolve(
    options.repositoryRoot ?? fileURLToPath(new URL("..", import.meta.url)),
  );
  const lockHandle = acquireUpdateLock(repositoryRoot);
  try {
    return applyUpstreamUpdateLocked(args, options, repositoryRoot);
  } finally {
    closeSync(lockHandle);
    if (!existsSync(journalPath(repositoryRoot))) {
      rmSync(join(repositoryRoot, UPDATE_LOCK_PATH), { force: true });
    }
  }
}

function applyUpstreamUpdateLocked(args, options, repositoryRoot) {
  const plan = createUpstreamUpdatePlan(args, options);
  recoverInterruptedUpdate(repositoryRoot);
  const sourceRoot = join(repositoryRoot, "upstream", "openwiki");
  const generatedRoot = join(repositoryRoot, ".work", "openwiki");
  const manifestPath = join(
    repositoryRoot,
    "patches",
    "openwiki",
    "manifest.json",
  );
  const sourceCommit = runGit(sourceRoot, ["rev-parse", "HEAD"]).stdout;
  if (!COMMIT_PATTERN.test(sourceCommit)) {
    throw new Error("The current upstream source commit is invalid.");
  }
  if (
    runGit(sourceRoot, ["remote", "get-url", "origin"]).stdout !==
    OFFICIAL_UPSTREAM_URL
  ) {
    throw new Error(
      "upstream source URL does not match the official OpenWiki remote.",
    );
  }
  if (
    runGit(sourceRoot, ["status", "--porcelain", "--untracked-files=all"])
      .stdout !== ""
  ) {
    throw new Error("upstream source is dirty; refusing to update it.");
  }
  assertNoUnmergedParentPaths(repositoryRoot);
  validateManifest(repositoryRoot, manifestPath, sourceCommit);
  const oldGitlink = readGitlink(repositoryRoot);
  if (oldGitlink.commit !== sourceCommit && sourceCommit !== plan.commit) {
    throw new Error(
      "The Submodule worktree differs from the parent gitlink; resolve that selection before updating.",
    );
  }
  if (options.fetch !== false) {
    runGit(sourceRoot, ["fetch", "--no-tags", "origin", plan.commit]);
  }
  if (
    runGit(sourceRoot, ["cat-file", "-e", `${plan.commit}^{commit}`], {
      allowFailure: true,
    }).status !== 0
  ) {
    throw new Error(
      "The selected upstream commit is not available in the Submodule.",
    );
  }

  const snapshots = [...new Set(COMPATIBILITY_PATHS)].map((path) =>
    captureFile(repositoryRoot, path),
  );
  const sourceState = { commit: sourceCommit, gitlink: oldGitlink };
  const hadGeneratedRoot = existsSync(generatedRoot);
  mkdirSync(join(repositoryRoot, ".work"), { recursive: true, mode: 0o700 });
  const transactionRoot = mkdtempSync(
    join(repositoryRoot, ".work", ".selfopenwiki-upstream-update-"),
  );
  const generatedBackup = join(transactionRoot, "generated");
  const journal = {
    schemaVersion: 1,
    domain: UPDATE_JOURNAL_DOMAIN,
    state: "prepared",
    sourceCommit,
    targetCommit: plan.commit,
    gitlink: oldGitlink,
    transactionRelative: relative(repositoryRoot, transactionRoot).replaceAll(
      sep,
      "/",
    ),
    generatedExisted: hadGeneratedRoot,
    generatedBackupRelative: relative(
      repositoryRoot,
      generatedBackup,
    ).replaceAll(sep, "/"),
    files: snapshots.map((snapshot) => ({
      byteHash: sha256(snapshot.bytes),
      byteLength: snapshot.bytes.byteLength,
      path: snapshot.relativePath,
      bytes: snapshot.bytes.toString("base64"),
      mode: snapshot.mode,
    })),
  };
  let staged = false;
  try {
    writeUpdateJournal(journalPath(repositoryRoot), journal);
    if (hadGeneratedRoot) {
      renameSync(generatedRoot, generatedBackup);
    }
    updateJournalState(repositoryRoot, journal, "backup");
    updateJournalState(repositoryRoot, journal, "manifest");
    atomicWriteFile(
      manifestPath,
      canonicalManifestBytes({
        schemaVersion: 2,
        domain: "selfopenwiki:openwiki-patch-manifest:v2",
        upstream: { url: OFFICIAL_UPSTREAM_URL, commit: plan.commit },
        patches: [],
      }),
    );
    const bindingUpdate = replaceCommitBindings(
      repositoryRoot,
      sourceCommit,
      plan.commit,
    );
    updateJournalState(repositoryRoot, journal, "bindings");
    if (sourceCommit !== plan.commit) {
      runGit(sourceRoot, ["checkout", "--detach", plan.commit]);
    }
    updateJournalState(repositoryRoot, journal, "source");
    const materialize = options.materialize ?? materializeOpenWiki;
    materialize({
      repositoryRoot,
      sourceRoot,
      generatedRoot,
      manifestPath,
      expectedUpstreamCommit: plan.commit,
    });
    updateJournalState(repositoryRoot, journal, "generated");
    if (options.stageGitlink !== false) {
      runGit(repositoryRoot, [
        "update-index",
        "--cacheinfo",
        `160000,${plan.commit},${upstreamGitlinkIndexPath(repositoryRoot)}`,
      ]);
      staged = true;
      updateJournalState(repositoryRoot, journal, "gitlink");
    }
    updateCompatibilityManifest(repositoryRoot, generatedRoot, plan.commit);
    updateJournalState(repositoryRoot, journal, "compatibility");
    (options.verify ?? defaultVerify)(generatedRoot, repositoryRoot);
    updateJournalState(repositoryRoot, journal, "verified");
    updateJournalState(repositoryRoot, journal, "adopted");
    rmSync(transactionRoot, { recursive: true, force: true });
    rmSync(journalPath(repositoryRoot), { force: true });
    return {
      schemaVersion: 1,
      domain: "selfopenwiki:manual-upstream-update-result:v1",
      status: "adopted",
      commit: plan.commit,
      previousCommit: sourceState.commit,
      stagedGitlink: staged,
      changedBindingFiles: bindingUpdate.changedFiles,
      changedBindingReferences: bindingUpdate.changedReferences,
      skillAdaptation: "personal-skill-retained-and-verified",
      generated: "verified",
    };
  } catch (error) {
    let rollbackError;
    try {
      if (existsSync(journalPath(repositoryRoot))) {
        recoverInterruptedUpdate(repositoryRoot);
      }
    } catch (restoreError) {
      rollbackError = restoreError;
    }
    if (rollbackError) {
      throw new Error(
        `Upstream update failed and durable rollback requires manual recovery: ${rollbackError instanceof Error ? rollbackError.message : String(rollbackError)}`,
        { cause: error },
      );
    }
    throw new Error(
      `Upstream update rolled back: ${error instanceof Error ? error.message : String(error)}`,
      { cause: error },
    );
  }
}

function acquireUpdateLock(repositoryRoot) {
  const lockPath = join(repositoryRoot, UPDATE_LOCK_PATH);
  let handle;
  try {
    handle = openSync(lockPath, "wx", 0o600);
    writeFileSync(
      handle,
      `${canonicalJsonBytes({
        domain: "selfopenwiki:upstream-update-lock-v1",
        pid: process.pid,
        startedAt: new Date().toISOString(),
      }).toString("utf8")}\n`,
      "utf8",
    );
    fsyncSync(handle);
    return handle;
  } catch (error) {
    if (handle !== undefined) closeSync(handle);
    if (error?.code === "EEXIST") {
      if (canSafelyTakeoverInterruptedUpdate(repositoryRoot)) {
        rmSync(lockPath, { force: true });
        return acquireUpdateLock(repositoryRoot);
      }
      throw new Error(
        "Another upstream update is already mutating this SelfOpenWiki repository; recover or remove the lock only after confirming that process is stopped.",
        { cause: error },
      );
    }
    throw error;
  }
}

function canSafelyTakeoverInterruptedUpdate(repositoryRoot) {
  const currentJournalPath = journalPath(repositoryRoot);
  if (!existsSync(currentJournalPath)) return false;
  const lockPath = join(repositoryRoot, UPDATE_LOCK_PATH);
  let owner;
  try {
    owner = JSON.parse(readFileSync(lockPath, "utf8"));
    if (
      owner?.domain !== "selfopenwiki:upstream-update-lock-v1" ||
      !Number.isSafeInteger(owner.pid) ||
      owner.pid <= 0 ||
      typeof owner.startedAt !== "string"
    ) {
      return false;
    }
    readUpdateJournal(currentJournalPath);
  } catch {
    return false;
  }
  try {
    process.kill(owner.pid, 0);
    return false;
  } catch (error) {
    return error?.code === "ESRCH";
  }
}

function parseCliArgs(args) {
  const apply = args.includes("--apply");
  const filtered = args.filter((value) => value !== "--apply");
  let repositoryRoot;
  const selection = [];
  for (let index = 0; index < filtered.length; index += 1) {
    const value = filtered[index];
    if (value === "--repository-root") {
      if (repositoryRoot !== undefined || filtered[index + 1] === undefined) {
        throw new Error("--repository-root requires one absolute path.");
      }
      repositoryRoot = resolve(filtered[index + 1]);
      index += 1;
    } else {
      selection.push(value);
    }
  }
  if (selection.length === 0) {
    throw new Error(
      "Update-Upstream requires one explicit 40-character commit or --tag <reviewed-tag>.",
    );
  }
  return { apply, repositoryRoot, selection };
}

function isMainModule() {
  return (
    process.argv[1] !== undefined &&
    pathToFileURL(resolve(process.argv[1])).href === import.meta.url
  );
}

if (isMainModule()) {
  try {
    const options = parseCliArgs(process.argv.slice(2));
    if (options.apply) {
      process.stdout.write(
        `${JSON.stringify(
          applyUpstreamUpdate(options.selection, {
            confirmed: true,
            repositoryRoot: options.repositoryRoot,
          }),
          null,
          2,
        )}\n`,
      );
      process.stderr.write(
        "Upstream update adopted after OpenWiki materialization, SelfOpenWiki lifecycle tests, and Skill validation.\n",
      );
    } else {
      const plan = createUpstreamUpdatePlan(options.selection);
      process.stdout.write(`${JSON.stringify(plan, null, 2)}\n`);
      process.stderr.write(
        "Review plan only: this helper never follows a branch or changes the gitlink automatically.\n",
      );
    }
  } catch (error) {
    process.stderr.write(
      `${error instanceof Error ? error.message : String(error)}\n`,
    );
    process.exitCode = 1;
  }
}
