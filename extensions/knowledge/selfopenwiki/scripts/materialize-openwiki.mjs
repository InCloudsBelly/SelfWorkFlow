#!/usr/bin/env node
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  parse,
  relative,
  resolve,
  sep,
} from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const FROZEN_UPSTREAM_COMMIT =
  "d1c7fc75a6a906da258cd94dbcb1602f98516480";
export const OFFICIAL_UPSTREAM_URL =
  "https://github.com/langchain-ai/openwiki.git";
export const MANIFEST_DOMAIN = "selfopenwiki:openwiki-patch-manifest:v2";
export const MATERIALIZATION_MARKER = ".selfopenwiki-materialization.json";

const MAX_MANIFEST_BYTES = 1024 * 1024;
const MAX_PATCH_BYTES = 4 * 1024 * 1024;
const MAX_GIT_OUTPUT_BYTES = 4 * 1024 * 1024;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const COMMIT_PATTERN = /^[0-9a-f]{40}$/u;

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function normalizeForComparison(value) {
  const normalized = resolve(value).replace(/[\\/]+$/u, "");
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function isWithin(root, candidate) {
  const normalizedRoot = normalizeForComparison(root);
  const normalizedCandidate = normalizeForComparison(candidate);
  return (
    normalizedCandidate === normalizedRoot ||
    normalizedCandidate.startsWith(`${normalizedRoot}${sep}`)
  );
}

function assertAbsolute(value, label) {
  if (typeof value !== "string" || !isAbsolute(value)) {
    throw new Error(`${label} must be an absolute path.`);
  }
  return resolve(value);
}

function assertNoLinkAncestors(
  value,
  label,
  { allowMissingLeaf = false } = {},
) {
  const absolute = assertAbsolute(value, label);
  const root = parse(absolute).root;
  let current = root;
  const segments = relative(root, absolute).split(sep).filter(Boolean);
  for (let index = 0; index < segments.length; index += 1) {
    current = join(current, segments[index]);
    if (!existsSync(current)) {
      if (allowMissingLeaf && index === segments.length - 1) {
        return absolute;
      }
      throw new Error(`${label} has a missing ancestor: ${current}`);
    }
    if (lstatSync(current).isSymbolicLink()) {
      throw new Error(`${label} contains a link or junction: ${current}`);
    }
  }
  return absolute;
}

function canonicalDirectory(value, label) {
  const absolute = assertNoLinkAncestors(value, label);
  const linkStat = lstatSync(absolute);
  const followedStat = statSync(absolute);
  if (linkStat.isSymbolicLink() || !followedStat.isDirectory()) {
    throw new Error(`${label} must be a regular non-link directory.`);
  }
  return realpathSync.native(absolute);
}

function canonicalRegularFile(value, label, maxBytes) {
  const absolute = assertNoLinkAncestors(value, label);
  const linkStat = lstatSync(absolute);
  if (linkStat.isSymbolicLink() || !linkStat.isFile()) {
    throw new Error(`${label} must be a regular non-link file.`);
  }
  if (linkStat.size > maxBytes) {
    throw new Error(`${label} exceeds its byte limit.`);
  }
  return realpathSync.native(absolute);
}

function strictRelativePath(value, label) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.includes("\\") ||
    value.includes("\0") ||
    value.startsWith("/") ||
    value
      .split("/")
      .some((segment) => segment === "" || segment === "." || segment === "..")
  ) {
    throw new Error(`${label} must be a canonical repository-relative path.`);
  }
  return value;
}

function canonicalAffectedPaths(values) {
  if (!Array.isArray(values)) {
    throw new Error("patch affectedPaths must be an array.");
  }
  const paths = values.map((value) =>
    strictRelativePath(value, "affected path"),
  );
  const canonical = [...new Set(paths)].sort((left, right) =>
    left.localeCompare(right, "en"),
  );
  if (
    canonical.length !== paths.length ||
    canonical.some((value, index) => value !== paths[index])
  ) {
    throw new Error("patch affectedPaths must be unique and sorted.");
  }
  return canonical;
}

function extractAffectedPaths(patchBytes) {
  const paths = [];
  const text = patchBytes.toString("utf8");
  for (const match of text.matchAll(/^diff --git a\/(\S+) b\/(\S+)$/gmu)) {
    const left = strictRelativePath(match[1], "patch source path");
    const right = strictRelativePath(match[2], "patch target path");
    if (left !== right) {
      throw new Error(
        "renaming paths is outside the bounded OpenWiki patch contract.",
      );
    }
    paths.push(left);
  }
  return [...new Set(paths)].sort((left, right) =>
    left.localeCompare(right, "en"),
  );
}

function canonicalDescriptor(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("patch descriptor must be an object.");
  }
  if (!Number.isSafeInteger(value.order) || value.order < 1) {
    throw new Error("patch order must be a positive integer.");
  }
  const path = strictRelativePath(value.path, "patch path");
  if (!/^patches\/openwiki\/\d{4}-[a-z0-9-]+\.patch$/u.test(path)) {
    throw new Error("patch path is outside the canonical patch namespace.");
  }
  if (
    !Number.isSafeInteger(value.bytes) ||
    value.bytes < 1 ||
    value.bytes > MAX_PATCH_BYTES
  ) {
    throw new Error("patch length is invalid.");
  }
  if (typeof value.sha256 !== "string" || !SHA256_PATTERN.test(value.sha256)) {
    throw new Error("patch hash is invalid.");
  }
  return {
    order: value.order,
    path,
    bytes: value.bytes,
    sha256: value.sha256,
    affectedPaths: canonicalAffectedPaths(value.affectedPaths),
  };
}

function canonicalManifest(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("patch manifest must be an object.");
  }
  if (value.schemaVersion !== 2 || value.domain !== MANIFEST_DOMAIN) {
    throw new Error("patch manifest domain or schema is invalid.");
  }
  if (
    value.upstream === null ||
    typeof value.upstream !== "object" ||
    Array.isArray(value.upstream) ||
    value.upstream.url !== OFFICIAL_UPSTREAM_URL ||
    typeof value.upstream.commit !== "string" ||
    !COMMIT_PATTERN.test(value.upstream.commit)
  ) {
    throw new Error("patch manifest upstream binding is invalid.");
  }
  if (!Array.isArray(value.patches) || value.patches.length !== 0) {
    throw new Error("v2 patch manifest must contain zero patches.");
  }
  return {
    schemaVersion: 2,
    domain: MANIFEST_DOMAIN,
    upstream: {
      url: OFFICIAL_UPSTREAM_URL,
      commit: value.upstream.commit,
    },
    patches: [],
  };
}

export function canonicalManifestBytes(value) {
  return Buffer.from(
    `${JSON.stringify(canonicalManifest(value), null, 2)}\n`,
    "utf8",
  );
}

export function createPatchDescriptor(
  repositoryRoot,
  patchRelativePath,
  affectedPaths,
) {
  const canonicalRepositoryRoot = canonicalDirectory(
    repositoryRoot,
    "repository root",
  );
  const path = strictRelativePath(patchRelativePath, "patch path");
  const patchPath = canonicalRegularFile(
    join(canonicalRepositoryRoot, ...path.split("/")),
    "patch file",
    MAX_PATCH_BYTES,
  );
  if (
    !isWithin(join(canonicalRepositoryRoot, "patches", "openwiki"), patchPath)
  ) {
    throw new Error("patch file escapes patches/openwiki.");
  }
  const bytes = readFileSync(patchPath);
  const fileOrder = Number.parseInt(basename(path).slice(0, 4), 10);
  return canonicalDescriptor({
    order: fileOrder,
    path,
    bytes: bytes.length,
    sha256: sha256(bytes),
    affectedPaths,
  });
}

export function validateManifest(
  repositoryRoot,
  manifestPath,
  expectedUpstreamCommit = FROZEN_UPSTREAM_COMMIT,
) {
  const canonicalRepositoryRoot = canonicalDirectory(
    repositoryRoot,
    "repository root",
  );
  const canonicalManifestPath = canonicalRegularFile(
    manifestPath,
    "patch manifest",
    MAX_MANIFEST_BYTES,
  );
  const expectedManifestRoot = join(
    canonicalRepositoryRoot,
    "patches",
    "openwiki",
  );
  const exactManifestPath = join(expectedManifestRoot, "manifest.json");
  if (!isWithin(expectedManifestRoot, canonicalManifestPath)) {
    throw new Error("patch manifest escapes patches/openwiki.");
  }
  if (
    normalizeForComparison(canonicalManifestPath) !==
    normalizeForComparison(exactManifestPath)
  ) {
    throw new Error("patch manifest is not at the exact manifest owner path.");
  }
  const rawBytes = readFileSync(canonicalManifestPath);
  let parsed;
  try {
    parsed = JSON.parse(rawBytes.toString("utf8"));
  } catch {
    throw new Error("patch manifest is not valid JSON.");
  }
  const manifest = canonicalManifest(parsed);
  if (!rawBytes.equals(canonicalManifestBytes(manifest))) {
    throw new Error("patch manifest bytes are not canonical.");
  }
  if (manifest.upstream.commit !== expectedUpstreamCommit) {
    throw new Error(
      "patch manifest commit does not match the frozen upstream commit.",
    );
  }
  for (const descriptor of manifest.patches) {
    const patchPath = canonicalRegularFile(
      join(canonicalRepositoryRoot, ...descriptor.path.split("/")),
      `patch ${descriptor.order}`,
      MAX_PATCH_BYTES,
    );
    if (!isWithin(expectedManifestRoot, patchPath)) {
      throw new Error(`patch ${descriptor.order} escapes patches/openwiki.`);
    }
    const patchBytes = readFileSync(patchPath);
    if (patchBytes.length !== descriptor.bytes) {
      throw new Error(`patch ${descriptor.order} length drift.`);
    }
    if (sha256(patchBytes) !== descriptor.sha256) {
      throw new Error(`patch ${descriptor.order} hash drift.`);
    }
    const actualAffectedPaths = extractAffectedPaths(patchBytes);
    if (
      JSON.stringify(actualAffectedPaths) !==
      JSON.stringify(descriptor.affectedPaths)
    ) {
      throw new Error(`patch ${descriptor.order} affected-path drift.`);
    }
  }
  return {
    manifest,
    manifestHash: sha256(rawBytes),
    manifestPath: canonicalManifestPath,
  };
}

function git(cwd, args, { allowFailure = false } = {}) {
  const environment = { ...process.env };
  const rejectedGitEnvironment = new Set([
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_ASKPASS",
    "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PROXY_COMMAND",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_WORK_TREE",
  ]);
  for (const key of Object.keys(environment)) {
    if (
      rejectedGitEnvironment.has(key) ||
      /^GIT_CONFIG_(?:KEY|VALUE)_\d+$/u.test(key)
    ) {
      delete environment[key];
    }
  }
  const nullDevice = process.platform === "win32" ? "NUL" : "/dev/null";
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
      maxBuffer: MAX_GIT_OUTPUT_BYTES,
      shell: false,
      windowsHide: true,
      env: environment,
    },
  );
  if (result.error) {
    throw result.error;
  }
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

function validateSource(sourceRoot, expectedCommit) {
  const canonicalSourceRoot = canonicalDirectory(sourceRoot, "upstream source");
  const url = git(canonicalSourceRoot, ["remote", "get-url", "origin"]).stdout;
  if (url !== OFFICIAL_UPSTREAM_URL) {
    throw new Error(
      "upstream source URL does not match the official OpenWiki remote.",
    );
  }
  const commit = git(canonicalSourceRoot, ["rev-parse", "HEAD"]).stdout;
  if (commit !== expectedCommit) {
    throw new Error("upstream source commit does not match the frozen commit.");
  }
  if (
    git(canonicalSourceRoot, ["symbolic-ref", "-q", "HEAD"], {
      allowFailure: true,
    }).status !== 1
  ) {
    throw new Error("upstream source must use a detached HEAD.");
  }
  if (
    git(canonicalSourceRoot, ["status", "--porcelain", "--untracked-files=all"])
      .stdout !== ""
  ) {
    throw new Error("upstream source is dirty.");
  }
  return { canonicalSourceRoot, commit, url };
}

function assertSourceUnchanged(source) {
  const current = validateSource(source.canonicalSourceRoot, source.commit);
  if (current.url !== source.url) {
    throw new Error("upstream source URL changed during materialization.");
  }
}

function validatePatchApplicability(repositoryRoot, sourceRoot, manifest) {
  if (manifest.patches.length === 0) return;
  git(sourceRoot, [
    "apply",
    "--check",
    "--cached",
    ...manifest.patches.map((descriptor) =>
      join(repositoryRoot, ...descriptor.path.split("/")),
    ),
  ]);
}

function writeDurableExclusive(path, bytes) {
  const descriptor = openSync(path, "wx", 0o600);
  try {
    writeFileSync(descriptor, bytes);
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function waitForWindowsHandleRelease() {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
}

function removeOwnedPath(path, options = {}) {
  let lastError;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      rmSync(path, { ...options, force: true });
      return;
    } catch (error) {
      lastError = error;
      if (
        !(error instanceof Error) ||
        !("code" in error) ||
        !["EBUSY", "EPERM", "EACCES", "ENOTEMPTY"].includes(error.code)
      ) {
        throw error;
      }
      waitForWindowsHandleRelease();
    }
  }
  throw lastError;
}

function renameOwnedPath(source, target) {
  let lastError;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      renameSync(source, target);
      return;
    } catch (error) {
      lastError = error;
      if (
        !(error instanceof Error) ||
        !("code" in error) ||
        !["EBUSY", "EPERM", "EACCES"].includes(error.code)
      ) {
        throw error;
      }
      waitForWindowsHandleRelease();
    }
  }
  throw lastError;
}

function markerBytes(manifest, manifestHash, candidateRoot) {
  const affectedFiles = [
    ...new Set(manifest.patches.flatMap((patch) => patch.affectedPaths)),
  ]
    .sort((left, right) => left.localeCompare(right, "en"))
    .map((path) => {
      const file = canonicalRegularFile(
        join(candidateRoot, ...path.split("/")),
        `generated ${path}`,
        MAX_PATCH_BYTES,
      );
      if (!isWithin(candidateRoot, file)) {
        throw new Error(`generated affected path escapes checkout: ${path}`);
      }
      const bytes = readFileSync(file);
      return { path, bytes: bytes.length, sha256: sha256(bytes) };
    });
  const marker = {
    schemaVersion: 1,
    domain: "selfopenwiki:openwiki-materialization:v1",
    upstreamCommit: manifest.upstream.commit,
    manifestHash,
    affectedFiles,
  };
  return Buffer.from(`${JSON.stringify(marker, null, 2)}\n`, "utf8");
}

function parseNullSeparatedPaths(
  value,
  label,
  { allowDirectorySuffix = false } = {},
) {
  if (value === "") return [];
  if (!value.endsWith("\0")) {
    throw new Error(`${label} output is not NUL terminated.`);
  }
  const rawPaths = value.slice(0, -1).split("\0");
  if (rawPaths.some((path) => path.length === 0)) {
    throw new Error(`${label} output contains an empty path.`);
  }
  const paths = rawPaths.map((path) => {
    const normalized =
      allowDirectorySuffix && path.endsWith("/") ? path.slice(0, -1) : path;
    return strictRelativePath(normalized, label);
  });
  if (new Set(paths).size !== paths.length) {
    throw new Error(`${label} output contains duplicate paths.`);
  }
  return paths.sort((left, right) => left.localeCompare(right, "en"));
}

function ignoredGeneratedPathsAreAllowed(canonicalGeneratedRoot) {
  const ignoredPaths = parseNullSeparatedPaths(
    git(canonicalGeneratedRoot, [
      "ls-files",
      "--others",
      "--ignored",
      "--exclude-standard",
      "--directory",
      "-z",
    ]).stdout,
    "generated ignored path",
    { allowDirectorySuffix: true },
  );
  const allowedRoots = ["dist", "node_modules"];
  for (const ignoredPath of ignoredPaths) {
    const allowedRoot = allowedRoots.find(
      (root) => ignoredPath === root || ignoredPath.startsWith(`${root}/`),
    );
    if (allowedRoot === undefined) return false;
    const rootPath = join(canonicalGeneratedRoot, allowedRoot);
    const rootStat = lstatSync(rootPath);
    if (rootStat.isSymbolicLink() || !rootStat.isDirectory()) return false;
  }
  return true;
}

export function verifyGeneratedRoot(
  generatedRoot,
  expectedCommit,
  manifest,
  manifestHash,
) {
  if (!existsSync(generatedRoot)) {
    return false;
  }
  const canonicalGeneratedRoot = canonicalDirectory(
    generatedRoot,
    "generated checkout",
  );
  if (
    git(canonicalGeneratedRoot, ["rev-parse", "HEAD"], { allowFailure: true })
      .stdout !== expectedCommit
  ) {
    return false;
  }
  if (
    git(canonicalGeneratedRoot, ["symbolic-ref", "-q", "HEAD"], {
      allowFailure: true,
    }).status !== 1
  ) {
    return false;
  }
  if (
    git(canonicalGeneratedRoot, ["remote", "get-url", "origin"], {
      allowFailure: true,
    }).stdout !== OFFICIAL_UPSTREAM_URL
  ) {
    return false;
  }
  const markerPath = join(canonicalGeneratedRoot, MATERIALIZATION_MARKER);
  if (!existsSync(markerPath)) {
    return false;
  }
  try {
    const markerFile = canonicalRegularFile(
      markerPath,
      "materialization marker",
      MAX_MANIFEST_BYTES,
    );
    const actualMarkerBytes = readFileSync(markerFile);
    if (
      !actualMarkerBytes.equals(
        markerBytes(manifest, manifestHash, canonicalGeneratedRoot),
      )
    ) {
      return false;
    }

    const changedPaths = parseNullSeparatedPaths(
      git(canonicalGeneratedRoot, ["diff", "--name-only", "-z", "HEAD"])
        .stdout,
      "generated changed path",
    );
    const untrackedPaths = parseNullSeparatedPaths(
      git(canonicalGeneratedRoot, [
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
      ]).stdout,
      "generated untracked path",
    );
    const actualPaths = [...new Set([...changedPaths, ...untrackedPaths])].sort(
      (left, right) => left.localeCompare(right, "en"),
    );
    const expectedPaths = [
      ...new Set([
        ...manifest.patches.flatMap((patch) => patch.affectedPaths),
        MATERIALIZATION_MARKER,
      ]),
    ].sort((left, right) => left.localeCompare(right, "en"));
    if (JSON.stringify(actualPaths) !== JSON.stringify(expectedPaths)) {
      return false;
    }
    if (!ignoredGeneratedPathsAreAllowed(canonicalGeneratedRoot)) {
      return false;
    }
  } catch {
    return false;
  }
  return true;
}

function writeJournal(path, manifestHash, phase) {
  const journal = {
    schemaVersion: 1,
    domain: "selfopenwiki:openwiki-materialization-journal:v1",
    manifestHash,
    phase,
  };
  writeDurableExclusive(
    path,
    Buffer.from(`${JSON.stringify(journal, null, 2)}\n`, "utf8"),
  );
}

function canonicalLockBytes(pid) {
  return Buffer.from(
    `${JSON.stringify({
      domain: "selfopenwiki:openwiki-materialization-lock:v1",
      pid,
      schemaVersion: 1,
    })}\n`,
    "utf8",
  );
}

function processIsAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ESRCH") {
      return false;
    }
    return true;
  }
}

function acquireMaterializationLock(lockPath) {
  const bytes = canonicalLockBytes(process.pid);
  try {
    writeDurableExclusive(lockPath, bytes);
    return;
  } catch (error) {
    if (
      !(error instanceof Error) ||
      !("code" in error) ||
      error.code !== "EEXIST"
    ) {
      throw error;
    }
  }

  const canonicalLockPath = canonicalRegularFile(
    lockPath,
    "materialization lock",
    MAX_MANIFEST_BYTES,
  );
  const existingBytes = readFileSync(canonicalLockPath);
  let existing;
  try {
    existing = JSON.parse(existingBytes.toString("utf8"));
  } catch {
    throw new Error("materialization lock is invalid; refusing to replace it.");
  }
  if (
    !existingBytes.equals(canonicalLockBytes(existing?.pid)) ||
    existing?.domain !== "selfopenwiki:openwiki-materialization-lock:v1" ||
    existing?.schemaVersion !== 1 ||
    !Number.isSafeInteger(existing?.pid) ||
    existing.pid < 1
  ) {
    throw new Error("materialization lock is invalid; refusing to replace it.");
  }
  if (processIsAlive(existing.pid)) {
    throw new Error("OpenWiki materialization is already running.");
  }
  if (!readFileSync(canonicalLockPath).equals(existingBytes)) {
    throw new Error(
      "materialization lock changed during stale-owner recovery.",
    );
  }
  removeOwnedPath(canonicalLockPath);
  writeDurableExclusive(lockPath, bytes);
}

function readJournal(path, manifestHash) {
  const journalPath = canonicalRegularFile(
    path,
    "materialization journal",
    MAX_MANIFEST_BYTES,
  );
  const journal = JSON.parse(readFileSync(journalPath, "utf8"));
  if (
    journal?.schemaVersion !== 1 ||
    journal?.domain !== "selfopenwiki:openwiki-materialization-journal:v1" ||
    journal?.manifestHash !== manifestHash ||
    !["target-displaced", "candidate-adopted"].includes(journal?.phase)
  ) {
    throw new Error("materialization journal is conflicting or invalid.");
  }
  return journal;
}

function reconcileAdoption({
  generatedRoot,
  candidateRoot,
  backupRoot,
  journalPath,
  expectedCommit,
  manifest,
  manifestHash,
}) {
  if (!existsSync(journalPath)) {
    if (!existsSync(generatedRoot) && existsSync(backupRoot)) {
      renameOwnedPath(backupRoot, generatedRoot);
    } else if (existsSync(backupRoot)) {
      if (
        verifyGeneratedRoot(
          generatedRoot,
          expectedCommit,
          manifest,
          manifestHash,
        )
      ) {
        removeOwnedPath(backupRoot, { recursive: true });
      } else {
        throw new Error(
          "unowned last-good backup conflicts with generated checkout.",
        );
      }
    }
    return null;
  }
  const journal = readJournal(journalPath, manifestHash);
  if (journal.phase === "target-displaced") {
    if (existsSync(generatedRoot)) {
      if (
        !existsSync(candidateRoot) &&
        verifyGeneratedRoot(
          generatedRoot,
          expectedCommit,
          manifest,
          manifestHash,
        )
      ) {
        removeOwnedPath(backupRoot, { recursive: true });
        removeOwnedPath(journalPath);
        return { status: "reused", manifestHash };
      }
      throw new Error(
        "materialization target unexpectedly exists during recovery.",
      );
    }
    if (
      existsSync(candidateRoot) &&
      verifyGeneratedRoot(
        candidateRoot,
        expectedCommit,
        manifest,
        manifestHash,
      )
    ) {
      renameOwnedPath(candidateRoot, generatedRoot);
      removeOwnedPath(backupRoot, { recursive: true });
      removeOwnedPath(journalPath);
      return { status: "materialized", manifestHash };
    }
    if (existsSync(backupRoot)) {
      renameOwnedPath(backupRoot, generatedRoot);
    }
    removeOwnedPath(candidateRoot, { recursive: true });
    removeOwnedPath(journalPath);
    return null;
  }
  if (
    !verifyGeneratedRoot(
      generatedRoot,
      expectedCommit,
      manifest,
      manifestHash,
    )
  ) {
    throw new Error("adopted generated checkout does not match its journal.");
  }
  removeOwnedPath(candidateRoot, { recursive: true });
  removeOwnedPath(backupRoot, { recursive: true });
  removeOwnedPath(journalPath);
  return { status: "reused", manifestHash };
}

function ensureWorkRoot(repositoryRoot, generatedRoot) {
  const workRoot = join(repositoryRoot, ".work");
  const requestedParent = dirname(generatedRoot);
  if (
    basename(generatedRoot).toLowerCase() !== "openwiki" ||
    basename(requestedParent).toLowerCase() !== ".work" ||
    normalizeForComparison(
      canonicalDirectory(dirname(requestedParent), "generated work parent"),
    ) !== normalizeForComparison(repositoryRoot)
  ) {
    throw new Error("generated checkout must be exactly .work/openwiki.");
  }
  if (!existsSync(workRoot)) {
    mkdirSync(workRoot, { recursive: false, mode: 0o700 });
  }
  const canonicalWorkRoot = canonicalDirectory(workRoot, "generated work root");
  if (!isWithin(repositoryRoot, canonicalWorkRoot)) {
    throw new Error("generated work root escapes repository root.");
  }
  return join(canonicalWorkRoot, basename(generatedRoot));
}

export function materializeOpenWiki({
  repositoryRoot,
  sourceRoot,
  generatedRoot,
  manifestPath,
  expectedUpstreamCommit = FROZEN_UPSTREAM_COMMIT,
  faultAt,
}) {
  if (!COMMIT_PATTERN.test(expectedUpstreamCommit)) {
    throw new Error("expected upstream commit is invalid.");
  }
  const canonicalRepositoryRoot = canonicalDirectory(
    repositoryRoot,
    "repository root",
  );
  const source = validateSource(sourceRoot, expectedUpstreamCommit);
  if (!isWithin(canonicalRepositoryRoot, source.canonicalSourceRoot)) {
    throw new Error("upstream source escapes repository root.");
  }
  const exactSourceRoot = canonicalDirectory(
    join(canonicalRepositoryRoot, "upstream", "openwiki"),
    "exact upstream source",
  );
  if (
    normalizeForComparison(source.canonicalSourceRoot) !==
    normalizeForComparison(exactSourceRoot)
  ) {
    throw new Error("upstream source is not at upstream/openwiki.");
  }
  const validated = validateManifest(
    canonicalRepositoryRoot,
    manifestPath,
    expectedUpstreamCommit,
  );
  const requestedGeneratedRoot = assertAbsolute(
    generatedRoot,
    "generated checkout",
  );
  const resolvedGeneratedRoot = ensureWorkRoot(
    canonicalRepositoryRoot,
    requestedGeneratedRoot,
  );
  assertNoLinkAncestors(resolvedGeneratedRoot, "generated checkout", {
    allowMissingLeaf: true,
  });
  const candidateRoot = `${resolvedGeneratedRoot}.candidate`;
  const backupRoot = `${resolvedGeneratedRoot}.last-good`;
  const journalPath = `${resolvedGeneratedRoot}.materialization-journal.json`;
  const lockPath = `${resolvedGeneratedRoot}.materialization-lock`;
  acquireMaterializationLock(lockPath);
  try {
    const reconciled = reconcileAdoption({
      generatedRoot: resolvedGeneratedRoot,
      candidateRoot,
      backupRoot,
      journalPath,
      expectedCommit: expectedUpstreamCommit,
      manifest: validated.manifest,
      manifestHash: validated.manifestHash,
    });
    if (!reconciled && !existsSync(journalPath)) {
      removeOwnedPath(candidateRoot, { recursive: true });
    }
    validatePatchApplicability(
      canonicalRepositoryRoot,
      source.canonicalSourceRoot,
      validated.manifest,
    );
    if (reconciled) {
      return reconciled;
    }
    if (
      verifyGeneratedRoot(
        resolvedGeneratedRoot,
        expectedUpstreamCommit,
        validated.manifest,
        validated.manifestHash,
      )
    ) {
      removeOwnedPath(candidateRoot, { recursive: true });
      return { status: "reused", manifestHash: validated.manifestHash };
    }
    mkdirSync(candidateRoot, { recursive: false, mode: 0o700 });
    removeOwnedPath(candidateRoot, { recursive: true });
    git(canonicalRepositoryRoot, [
      "clone",
      "--no-hardlinks",
      "--no-checkout",
      source.canonicalSourceRoot,
      candidateRoot,
    ]);
    git(candidateRoot, [
      "remote",
      "set-url",
      "origin",
      OFFICIAL_UPSTREAM_URL,
    ]);
    git(candidateRoot, ["checkout", "--detach", expectedUpstreamCommit]);
    writeDurableExclusive(
      join(candidateRoot, MATERIALIZATION_MARKER),
      markerBytes(validated.manifest, validated.manifestHash, candidateRoot),
    );
    if (
      !verifyGeneratedRoot(
        candidateRoot,
        expectedUpstreamCommit,
        validated.manifest,
        validated.manifestHash,
      )
    ) {
      throw new Error(
        "generated checkout verification failed before adoption.",
      );
    }
    if (existsSync(resolvedGeneratedRoot)) {
      if (existsSync(backupRoot)) {
        throw new Error("last-good backup already exists before adoption.");
      }
      renameOwnedPath(resolvedGeneratedRoot, backupRoot);
      writeJournal(journalPath, validated.manifestHash, "target-displaced");
      if (faultAt === "after-backup-rename") {
        throw new Error("injected adoption response loss");
      }
    }
    renameOwnedPath(candidateRoot, resolvedGeneratedRoot);
    if (faultAt === "after-candidate-rename") {
      throw new Error("injected candidate-rename response loss");
    }
    if (existsSync(journalPath)) {
      removeOwnedPath(journalPath);
      writeJournal(journalPath, validated.manifestHash, "candidate-adopted");
    }
    removeOwnedPath(backupRoot, { recursive: true });
    removeOwnedPath(journalPath);
    return { status: "materialized", manifestHash: validated.manifestHash };
  } finally {
    removeOwnedPath(lockPath);
    assertSourceUnchanged(source);
    if (!existsSync(journalPath)) {
      removeOwnedPath(candidateRoot, { recursive: true });
    }
  }
}

export function parseUpdateCommit(args) {
  if (
    args.length !== 1 ||
    typeof args[0] !== "string" ||
    !COMMIT_PATTERN.test(args[0])
  ) {
    throw new Error(
      "Update-Upstream requires one explicit 40-character commit.",
    );
  }
  return args[0];
}

function parseCliArgs(args, repositoryRoot) {
  if (args.includes("--help")) {
    if (args.length !== 1) {
      throw new Error("--help cannot be combined with other arguments.");
    }
    return { help: true };
  }
  if (
    args.length !== 0 &&
    (args.length !== 2 ||
      args[0] !== "--repository-root" ||
      args[1].startsWith("--"))
  ) {
    throw new Error(
      `unknown or incomplete materializer argument: ${args[0] ?? "<missing>"}`,
    );
  }
  const selectedRepositoryRoot =
    args.length === 0
      ? repositoryRoot
      : assertAbsolute(args[1], "repository root argument");
  return {
    repositoryRoot: selectedRepositoryRoot,
    sourceRoot: join(selectedRepositoryRoot, "upstream", "openwiki"),
    generatedRoot: join(selectedRepositoryRoot, ".work", "openwiki"),
    manifestPath: join(
      selectedRepositoryRoot,
      "patches",
      "openwiki",
      "manifest.json",
    ),
  };
}

function isMainModule() {
  return (
    process.argv[1] !== undefined &&
    pathToFileURL(resolve(process.argv[1])).href === import.meta.url
  );
}

if (isMainModule()) {
  try {
    const scriptRepositoryRoot = fileURLToPath(new URL("..", import.meta.url));
    const options = parseCliArgs(process.argv.slice(2), scriptRepositoryRoot);
    if (options.help) {
      process.stdout.write(
        "Usage: node scripts/materialize-openwiki.mjs [--repository-root ABSOLUTE_PATH]\n",
      );
    } else {
      process.stdout.write(`${JSON.stringify(materializeOpenWiki(options))}\n`);
    }
  } catch (error) {
    process.stderr.write(
      `${error instanceof Error ? error.message : String(error)}\n`,
    );
    process.exitCode = 1;
  }
}
