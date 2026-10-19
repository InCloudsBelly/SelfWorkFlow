import { createHash } from "node:crypto";
import { lstat, open, readdir, realpath } from "node:fs/promises";
import path from "node:path";
import { snapshotMarkdownTree } from "./snapshot.js";

type FileIdentity = {
  readonly birthtimeMs: number;
  readonly dev: number;
  readonly ino: number;
};

type BoundDirectory = {
  readonly absolutePath: string;
  readonly identity: FileIdentity;
};

export type PersonalWikiSnapshot = {
  readonly claims: readonly {
    readonly hash: string;
    readonly relativePath: string;
    readonly size: number;
  }[];
  readonly markdownRootHash: string;
  readonly rootHash: string;
};

/**
 * Snapshots a personal Wiki's Markdown plus its adapter-owned Claim sidecars.
 * C7's transaction snapshot remains Markdown-only; this boundary is the
 * personal repository revision used for begin/no-op and final CAS binding.
 */
export async function snapshotPersonalWiki(
  root: string,
): Promise<PersonalWikiSnapshot> {
  const rootDirectory = await bindDirectory(root);
  const canonicalRoot = rootDirectory.absolutePath;
  const markdown = await snapshotMarkdownTree(canonicalRoot);
  await assertDirectoryChain([rootDirectory]);
  const claimsDirectory = path.join(canonicalRoot, ".claims");
  const claimsStat = await lstat(claimsDirectory).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (
    claimsStat !== null &&
    (claimsStat.isSymbolicLink() || !claimsStat.isDirectory())
  ) {
    throw new Error("Personal Wiki Claim state must be a regular directory.");
  }
  const claims =
    claimsStat === null
      ? []
      : await collectClaimFiles(canonicalRoot, ".claims", [
          rootDirectory,
          await bindDirectoryEntry(claimsDirectory),
        ]);
  await assertDirectoryChain([rootDirectory]);
  claims.sort((left, right) =>
    left.relativePath < right.relativePath
      ? -1
      : left.relativePath > right.relativePath
        ? 1
        : 0,
  );
  const rootHash = hashPersonalTree({
    claims,
    markdownRootHash: markdown.rootHash,
  });
  return { claims, markdownRootHash: markdown.rootHash, rootHash };
}

async function collectClaimFiles(
  root: string,
  relativeDirectory: string,
  directories: readonly BoundDirectory[],
): Promise<Array<PersonalWikiSnapshot["claims"][number]>> {
  const directory = path.join(root, relativeDirectory);
  await assertDirectoryChain(directories);
  const entries = await readdir(directory, { withFileTypes: true });
  await assertDirectoryChain(directories);
  entries.sort((left, right) => (left.name < right.name ? -1 : 1));
  const files: Array<PersonalWikiSnapshot["claims"][number]> = [];
  for (const entry of entries) {
    const relativePath = relativeDirectory
      ? path.join(relativeDirectory, entry.name)
      : entry.name;
    const absolutePath = path.join(root, relativePath);
    const stat = await lstat(absolutePath);
    if (entry.isSymbolicLink() || stat.isSymbolicLink()) {
      throw new Error("Personal Wiki Claim state cannot contain links.");
    }
    if (entry.isDirectory() && stat.isDirectory()) {
      const child = await bindDirectoryEntry(absolutePath);
      files.push(
        ...(await collectClaimFiles(root, relativePath, [
          ...directories,
          child,
        ])),
      );
      continue;
    }
    if (
      !entry.isFile() ||
      !stat.isFile() ||
      path.extname(entry.name).toLowerCase() !== ".json"
    ) {
      throw new Error("Personal Wiki Claim state can contain only JSON files.");
    }
    const bytes = await readBoundFile(absolutePath, stat, directories);
    files.push({
      hash: hashBytes(bytes),
      relativePath: relativePath.split(path.sep).join("/"),
      size: bytes.byteLength,
    });
  }
  return files;
}

async function bindDirectory(root: string): Promise<BoundDirectory> {
  const before = await lstat(root);
  if (!before.isDirectory() || before.isSymbolicLink()) {
    throw new Error("Personal Wiki Claim state must be a regular directory.");
  }
  const canonicalRoot = await realpath(root);
  const [afterPath, canonical] = await Promise.all([
    lstat(root),
    lstat(canonicalRoot),
  ]);
  if (
    !afterPath.isDirectory() ||
    afterPath.isSymbolicLink() ||
    !canonical.isDirectory() ||
    canonical.isSymbolicLink() ||
    !sameFileIdentity(before, afterPath) ||
    !sameFileIdentity(before, canonical)
  ) {
    throw new Error(
      "Personal Wiki Claim state changed while it was inspected.",
    );
  }
  return { absolutePath: canonicalRoot, identity: canonical };
}

async function bindDirectoryEntry(directory: string): Promise<BoundDirectory> {
  const before = await lstat(directory);
  if (!before.isDirectory() || before.isSymbolicLink()) {
    throw new Error("Personal Wiki Claim state cannot contain links.");
  }
  const canonical = await realpath(directory);
  const [afterPath, canonicalStat] = await Promise.all([
    lstat(directory),
    lstat(canonical),
  ]);
  if (
    !afterPath.isDirectory() ||
    afterPath.isSymbolicLink() ||
    !canonicalStat.isDirectory() ||
    canonicalStat.isSymbolicLink() ||
    !sameFileIdentity(before, afterPath) ||
    !sameFileIdentity(before, canonicalStat) ||
    !samePath(canonical, directory)
  ) {
    throw new Error(
      "Personal Wiki Claim state cannot contain redirected paths.",
    );
  }
  return { absolutePath: directory, identity: canonicalStat };
}

async function readBoundFile(
  filePath: string,
  expected: FileIdentity,
  directories: readonly BoundDirectory[],
): Promise<Buffer> {
  const handle = await open(filePath, "r");
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || !sameFileIdentity(expected, opened)) {
      throw new Error("Personal Wiki Claim state changed before it was read.");
    }
    await assertDirectoryChain(directories);
    await assertBoundFilePath(filePath, opened);
    const bytes = await handle.readFile();
    const after = await handle.stat();
    if (!after.isFile() || !sameFileIdentity(opened, after)) {
      throw new Error("Personal Wiki Claim state changed while it was read.");
    }
    await assertBoundFilePath(filePath, opened);
    await assertDirectoryChain(directories);
    return bytes;
  } finally {
    await handle.close();
  }
}

async function assertBoundFilePath(
  filePath: string,
  expected: FileIdentity,
): Promise<void> {
  const stat = await lstat(filePath);
  if (
    !stat.isFile() ||
    stat.isSymbolicLink() ||
    !sameFileIdentity(expected, stat)
  ) {
    throw new Error("Personal Wiki Claim state changed while it was read.");
  }
}

async function assertDirectoryChain(
  directories: readonly BoundDirectory[],
): Promise<void> {
  for (const directory of directories) {
    const stat = await lstat(directory.absolutePath);
    if (
      !stat.isDirectory() ||
      stat.isSymbolicLink() ||
      !sameFileIdentity(directory.identity, stat)
    ) {
      throw new Error("Personal Wiki Claim directory changed.");
    }
  }
}

function sameFileIdentity(left: FileIdentity, right: FileIdentity): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.birthtimeMs === right.birthtimeMs
  );
}

function samePath(left: string, right: string): boolean {
  const normalize = (value: string) =>
    path.normalize(value).replace(/[\\/]+$/u, "");
  return process.platform === "win32"
    ? normalize(left).toLowerCase() === normalize(right).toLowerCase()
    : normalize(left) === normalize(right);
}

function hashPersonalTree(value: unknown): string {
  const hasher = createHash("sha256");
  hasher.update("selfopenwiki:personal-wiki-tree-v1\0", "utf8");
  hasher.update(canonicalJson(value), "utf8");
  return `sha256:${hasher.digest("hex")}`;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}
