import type { FileHandle } from "node:fs/promises";
import type { Stats } from "node:fs";

export type MarkdownTreeSnapshot = {
  readonly files: readonly {
    readonly hash: string;
    readonly relativePath: string;
    readonly size: number;
  }[];
  readonly rootHash: string;
};

type FileIdentity = {
  readonly birthtimeMs: number;
  readonly dev: number;
  readonly ino: number;
};

type BoundDirectory = {
  readonly absolutePath: string;
  readonly identity: FileIdentity;
};

export class C7SnapshotError extends Error {
  constructor(
    readonly code: "wiki_changed" | "wiki_invalid",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "C7SnapshotError";
  }
}

export async function snapshotMarkdownTree(
  root: string,
): Promise<MarkdownTreeSnapshot> {
  const rootDirectory = await bindMarkdownRoot(root);
  const files = await collectMarkdownFiles(rootDirectory, "", [rootDirectory]);
  files.sort((left, right) =>
    left.relativePath < right.relativePath
      ? -1
      : left.relativePath > right.relativePath
        ? 1
        : 0,
  );
  return { files, rootHash: hashTree(files) };
}

export async function readMarkdownPages(
  root: string,
  paths: readonly string[],
  expectedRevision?: string,
) {
  const directory = await bindMarkdownRoot(root);
  const capture = async () => {
    const files = await collectMarkdownFiles(directory, "", [directory], true);
    files.sort((a, b) =>
      a.relativePath < b.relativePath
        ? -1
        : a.relativePath > b.relativePath
          ? 1
          : 0,
    );
    return { files, rootHash: hashTree(files) };
  };
  const before = await capture();
  if (expectedRevision !== undefined && before.rootHash !== expectedRevision)
    throw changedWiki();
  const selected = paths.map((relativePath) => {
    const file = before.files.find(
      (item) => item.relativePath === relativePath,
    );
    if (!file)
      throw invalidWiki("Only existing formal Markdown pages can be read.");
    return file;
  });
  if (selected.some((file) => file.size > 262_144)) {
    throw invalidWiki("A Wiki page exceeds the 256 KiB read limit.");
  }
  if (selected.reduce((total, file) => total + file.size, 0) > 1_048_576) {
    throw invalidWiki(
      "The requested Wiki content exceeds the 1 MiB read limit.",
    );
  }
  const knowledge = [];
  for (const file of selected) {
    const bytes = await readBoundMarkdownFile(
      directory,
      file.relativePath,
      262_144,
    );
    if (bytes.byteLength !== file.size || hashBytes(bytes) !== file.hash)
      throw changedWiki();
    let content: string;
    try {
      content = new TextDecoder("utf-8", {
        fatal: true,
        ignoreBOM: true,
      }).decode(bytes);
    } catch {
      throw invalidWiki("The requested Wiki page is not valid UTF-8.");
    }
    knowledge.push({
      content,
      sourceId: `selfopenwiki:${file.relativePath}`,
      revision: before.rootHash,
      contentHash: file.hash,
      verificationStatus: "unverified" as const,
    });
  }
  if (!snapshotsEqual(before, await capture())) throw changedWiki();
  return {
    revision: before.rootHash,
    pages: before.files.map((file) => ({
      path: file.relativePath,
      size: file.size,
      contentHash: file.hash,
    })),
    knowledge,
  };
}

export async function copyMarkdownTree(
  sourceRoot: string,
  destinationRoot: string,
  expected: MarkdownTreeSnapshot,
): Promise<MarkdownTreeSnapshot> {
  assertSnapshotShape(expected);
  await assertMarkdownTreeVersion(sourceRoot, expected);
  const sourceDirectory = await bindMarkdownRoot(sourceRoot);
  assertAbsolute(destinationRoot);
  await mkdir(destinationRoot, { mode: 0o700, recursive: true });
  const emptyDestination = await snapshotMarkdownTree(destinationRoot);
  if (emptyDestination.files.length !== 0) {
    throw invalidWiki("The Wiki snapshot destination must be empty.");
  }

  for (const file of expected.files) {
    const destinationPath = containedPath(destinationRoot, file.relativePath);
    const bytes = await readBoundMarkdownFile(
      sourceDirectory,
      file.relativePath,
    );
    if (bytes.byteLength !== file.size || hashBytes(bytes) !== file.hash) {
      throw changedWiki();
    }
    await mkdir(path.dirname(destinationPath), {
      mode: 0o700,
      recursive: true,
    });
    const handle = await open(destinationPath, "wx", 0o600);
    try {
      await handle.writeFile(bytes);
      await handle.sync();
    } finally {
      await handle.close();
    }
  }

  await assertMarkdownTreeVersion(sourceRoot, expected);
  const copied = await snapshotMarkdownTree(destinationRoot);
  if (!snapshotsEqual(copied, expected)) {
    throw invalidWiki("The copied Wiki snapshot failed exact verification.");
  }
  return copied;
}

export async function assertMarkdownTreeVersion(
  root: string,
  expected: MarkdownTreeSnapshot,
): Promise<void> {
  assertSnapshotShape(expected);
  let current: MarkdownTreeSnapshot;
  try {
    current = await snapshotMarkdownTree(root);
  } catch (error) {
    if (error instanceof C7SnapshotError && error.code === "wiki_invalid") {
      throw changedWiki(error);
    }
    throw error;
  }
  if (!snapshotsEqual(current, expected)) throw changedWiki();
}

async function collectMarkdownFiles(
  root: BoundDirectory,
  relativeDirectory: string,
  directories: readonly BoundDirectory[],
  streamHashes = false,
): Promise<Array<MarkdownTreeSnapshot["files"][number]>> {
  const directory =
    relativeDirectory === ""
      ? root.absolutePath
      : path.join(root.absolutePath, relativeDirectory);
  await assertDirectoryChain(directories);
  const entries = await readdir(directory, { withFileTypes: true }).catch(
    (error: unknown) => {
      throw invalidWiki("The Wiki directory is unreadable.", error);
    },
  );
  await assertDirectoryChain(directories);
  entries.sort((left, right) => (left.name < right.name ? -1 : 1));
  const files: Array<MarkdownTreeSnapshot["files"][number]> = [];
  for (const entry of entries) {
    // A selected personal Wiki may itself be a Git worktree. Git metadata is
    // repository state, not Wiki content, and is deliberately excluded from
    // the content snapshot/publication surface.
    if (relativeDirectory === "" && entry.name === ".git") continue;
    // Personal OpenWiki Claim sidecars are control state owned by the
    // personal adapter. They are snapshotted by its dedicated root snapshot,
    // while the C7 Markdown transaction intentionally ignores them.
    if (relativeDirectory === "" && entry.name === ".claims") continue;
    if (relativeDirectory === "" && entry.name === ".selfopenwiki") {
      throw invalidWiki(
        "The Wiki root cannot contain the reserved personal runtime directory.",
      );
    }
    const relativePath =
      relativeDirectory === ""
        ? entry.name
        : path.join(relativeDirectory, entry.name);
    const normalizedPath = relativePath.split(path.sep).join("/");
    const absolutePath = path.join(root.absolutePath, relativePath);
    await assertDirectoryChain(directories);
    const stat = await lstat(absolutePath).catch((error: unknown) => {
      throw invalidWiki("A Wiki snapshot entry is unreadable.", error);
    });
    if (entry.isSymbolicLink() || stat.isSymbolicLink()) {
      throw invalidWiki(
        "Wiki snapshots cannot contain links or reparse paths.",
      );
    }
    // Root Git policies travel with the repository, outside knowledge revisions.
    if (
      relativeDirectory === "" &&
      (entry.name === ".gitignore" || entry.name === ".gitattributes")
    ) {
      if (!entry.isFile() || !stat.isFile()) {
        throw invalidWiki("Root Git policies must be regular files.");
      }
      continue;
    }
    if (entry.isDirectory() && stat.isDirectory()) {
      const child = { absolutePath, identity: stat };
      files.push(
        ...(await collectMarkdownFiles(
          root,
          relativePath,
          [...directories, child],
          streamHashes,
        )),
      );
      continue;
    }
    if (!entry.isFile() || !stat.isFile()) {
      throw invalidWiki("Wiki snapshots can contain only regular files.");
    }
    if (path.extname(entry.name).toLowerCase() !== ".md") {
      throw invalidWiki("The formal Wiki can contain only Markdown files.");
    }
    const metadata = streamHashes
      ? await withBoundRegularFile(
          absolutePath,
          stat,
          directories,
          async (handle, opened) => {
            const hasher = createHash("sha256");
            const buffer = Buffer.alloc(65_536);
            let offset = 0;
            while (offset < opened.size) {
              const result = await handle.read(
                buffer,
                0,
                Math.min(buffer.length, opened.size - offset),
                offset,
              );
              if (result.bytesRead === 0) throw changedWiki();
              hasher.update(buffer.subarray(0, result.bytesRead));
              offset += result.bytesRead;
            }
            const after = await handle.stat();
            if (after.size !== opened.size || after.mtimeMs !== opened.mtimeMs)
              throw changedWiki();
            return { hash: `sha256:${hasher.digest("hex")}`, size: offset };
          },
        )
      : await readBoundRegularFile(absolutePath, stat, directories).then(
          (bytes) => ({ hash: hashBytes(bytes), size: bytes.byteLength }),
        );
    files.push({ ...metadata, relativePath: normalizedPath });
  }
  await assertDirectoryChain(directories);
  return files;
}

async function bindMarkdownRoot(root: string): Promise<BoundDirectory> {
  assertAbsolute(root);
  const before = await lstat(root).catch((error: unknown) => {
    throw invalidWiki("The Wiki root is missing or unreadable.", error);
  });
  if (!before.isDirectory() || before.isSymbolicLink()) {
    throw invalidWiki("The Wiki root must be a regular non-link directory.");
  }
  const canonicalRoot = await realpath(root).catch((error: unknown) => {
    throw invalidWiki("The Wiki root is missing or unreadable.", error);
  });
  const [afterPath, canonical] = await Promise.all([
    lstat(root),
    lstat(canonicalRoot),
  ]).catch((error: unknown) => {
    throw invalidWiki("The Wiki root changed while it was inspected.", error);
  });
  if (
    !afterPath.isDirectory() ||
    afterPath.isSymbolicLink() ||
    !canonical.isDirectory() ||
    canonical.isSymbolicLink() ||
    !sameFileIdentity(before, afterPath) ||
    !sameFileIdentity(before, canonical)
  ) {
    throw invalidWiki("The Wiki root changed while it was inspected.");
  }
  return { absolutePath: canonicalRoot, identity: canonical };
}

async function readBoundMarkdownFile(
  root: BoundDirectory,
  relativePath: string,
  maxBytes?: number,
): Promise<Buffer> {
  const segments = relativePath.split("/");
  const directories: BoundDirectory[] = [root];
  let current = root.absolutePath;
  for (const segment of segments.slice(0, -1)) {
    await assertDirectoryChain(directories);
    current = path.join(current, segment);
    const stat = await lstat(current).catch((error: unknown) => {
      throw invalidWiki("A Wiki snapshot directory is unreadable.", error);
    });
    if (!stat.isDirectory() || stat.isSymbolicLink()) {
      throw invalidWiki(
        "Wiki snapshots cannot contain links or reparse paths.",
      );
    }
    directories.push({ absolutePath: current, identity: stat });
  }
  await assertDirectoryChain(directories);
  const filePath = containedPath(root.absolutePath, relativePath);
  const stat = await lstat(filePath).catch((error: unknown) => {
    throw invalidWiki("A Wiki snapshot file is unreadable.", error);
  });
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw invalidWiki("Wiki snapshots can contain only regular files.");
  }
  return readBoundRegularFile(filePath, stat, directories, maxBytes);
}

async function readBoundRegularFile(
  filePath: string,
  expected: FileIdentity,
  directories: readonly BoundDirectory[],
  maxBytes?: number,
): Promise<Buffer> {
  return withBoundRegularFile(
    filePath,
    expected,
    directories,
    async (handle, opened) => {
      if (maxBytes === undefined) return handle.readFile();
      if (opened.size > maxBytes)
        throw invalidWiki("A Wiki page exceeds the 256 KiB read limit.");
      const buffer = Buffer.alloc(maxBytes + 1);
      let offset = 0;
      while (offset < buffer.length) {
        const result = await handle.read(
          buffer,
          offset,
          buffer.length - offset,
          offset,
        );
        if (result.bytesRead === 0) break;
        offset += result.bytesRead;
      }
      if (offset > maxBytes)
        throw invalidWiki("A Wiki page exceeds the 256 KiB read limit.");
      return buffer.subarray(0, offset);
    },
  );
}

async function withBoundRegularFile<T>(
  filePath: string,
  expected: FileIdentity,
  directories: readonly BoundDirectory[],
  consume: (handle: FileHandle, opened: Stats) => Promise<T>,
): Promise<T> {
  const handle = await open(filePath, "r").catch((error: unknown) => {
    throw invalidWiki("A Wiki snapshot file is unreadable.", error);
  });
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || !sameFileIdentity(expected, opened)) {
      throw invalidWiki("A Wiki snapshot file changed before it was read.");
    }
    await assertDirectoryChain(directories);
    await assertBoundFilePath(filePath, opened);
    const value = await consume(handle, opened);
    const afterHandle = await handle.stat();
    if (!afterHandle.isFile() || !sameFileIdentity(opened, afterHandle)) {
      throw invalidWiki("A Wiki snapshot file changed while it was read.");
    }
    await assertBoundFilePath(filePath, opened);
    await assertDirectoryChain(directories);
    return value;
  } finally {
    await handle.close();
  }
}

async function assertBoundFilePath(
  filePath: string,
  expected: FileIdentity,
): Promise<void> {
  const stat = await lstat(filePath).catch((error: unknown) => {
    throw invalidWiki("A Wiki snapshot file changed while it was read.", error);
  });
  if (
    !stat.isFile() ||
    stat.isSymbolicLink() ||
    !sameFileIdentity(expected, stat)
  ) {
    throw invalidWiki("A Wiki snapshot file changed while it was read.");
  }
}

async function assertDirectoryChain(
  directories: readonly BoundDirectory[],
): Promise<void> {
  for (const directory of directories) {
    const stat = await lstat(directory.absolutePath).catch((error: unknown) => {
      throw invalidWiki("A Wiki snapshot directory changed.", error);
    });
    if (
      !stat.isDirectory() ||
      stat.isSymbolicLink() ||
      !sameFileIdentity(directory.identity, stat)
    ) {
      throw invalidWiki("A Wiki snapshot directory changed.");
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

function hashTree(files: MarkdownTreeSnapshot["files"]): string {
  const hasher = createHash("sha256");
  hasher.update("kg-c7-wiki-tree-v1\0", "utf8");
  for (const file of files) {
    const pathBytes = Buffer.from(file.relativePath, "utf8");
    hasher.update(String(pathBytes.byteLength), "ascii");
    hasher.update(":", "ascii");
    hasher.update(pathBytes);
    hasher.update("\0", "ascii");
    hasher.update(String(file.size), "ascii");
    hasher.update("\0", "ascii");
    hasher.update(file.hash, "ascii");
    hasher.update("\0", "ascii");
  }
  return `sha256:${hasher.digest("hex")}`;
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function snapshotsEqual(
  left: MarkdownTreeSnapshot,
  right: MarkdownTreeSnapshot,
): boolean {
  return (
    left.rootHash === right.rootHash &&
    left.files.length === right.files.length &&
    left.files.every((file, index) => {
      const other = right.files[index];
      return (
        other !== undefined &&
        file.relativePath === other.relativePath &&
        file.size === other.size &&
        file.hash === other.hash
      );
    })
  );
}

function assertSnapshotShape(snapshot: MarkdownTreeSnapshot): void {
  const sorted = [...snapshot.files].sort((left, right) =>
    left.relativePath < right.relativePath ? -1 : 1,
  );
  const valid =
    /^sha256:[a-f0-9]{64}$/u.test(snapshot.rootHash) &&
    snapshot.files.length === sorted.length &&
    snapshot.files.every((file, index) => {
      const normalized = file.relativePath.split("/");
      return (
        file === sorted[index] &&
        normalized.length > 0 &&
        normalized.every(
          (segment) => segment !== "" && segment !== "." && segment !== "..",
        ) &&
        file.relativePath.toLowerCase().endsWith(".md") &&
        Number.isSafeInteger(file.size) &&
        file.size >= 0 &&
        /^sha256:[a-f0-9]{64}$/u.test(file.hash)
      );
    }) &&
    hashTree(snapshot.files) === snapshot.rootHash;
  if (!valid) throw invalidWiki("The expected Wiki snapshot is invalid.");
}

function containedPath(root: string, relativePath: string): string {
  const candidate = path.resolve(root, ...relativePath.split("/"));
  const relative = path.relative(root, candidate);
  if (
    relative === "" ||
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw invalidWiki("A Wiki snapshot path escapes its root.");
  }
  return candidate;
}

function assertAbsolute(root: string): void {
  if (!path.isAbsolute(root)) {
    throw invalidWiki("The Wiki root path must be absolute.");
  }
}

function invalidWiki(message: string, cause?: unknown): C7SnapshotError {
  return new C7SnapshotError("wiki_invalid", message, { cause });
}

function changedWiki(cause?: unknown): C7SnapshotError {
  return new C7SnapshotError(
    "wiki_changed",
    "The formal Wiki changed after its version was captured.",
    { cause },
  );
}
import { createHash } from "node:crypto";
import { lstat, mkdir, open, readdir, realpath } from "node:fs/promises";
import path from "node:path";
