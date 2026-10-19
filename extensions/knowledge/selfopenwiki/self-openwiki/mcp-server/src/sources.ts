import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  link,
  mkdir,
  mkdtemp,
  open,
  readFile,
  readdir,
  rm,
} from "node:fs/promises";
import path from "node:path";
import { TextDecoder } from "node:util";
import ignore, { type Ignore } from "ignore";
import { z } from "zod";
import { withC7Locks } from "./config.js";
import {
  assertSourceContentNotSensitive,
  assertSourcePathNotSensitive,
  loadSensitiveFilePolicy,
  type SensitiveFilePolicy,
} from "./sensitive-files.js";
import type { StableCopyResult, StablePathInspection } from "./win32-helper.js";

const DEFAULT_EXCLUDED_DIRECTORIES = new Set([
  ".git",
  ".idea",
  ".vs",
  ".vscode",
  "binaries",
  "build",
  "coverage",
  "deriveddatacache",
  "dist",
  "intermediate",
  "node_modules",
  "obj",
  "saved",
]);
const SUPPORTED_EXTENSIONS = new Set([
  ".bat",
  ".c",
  ".cc",
  ".cfg",
  ".cmake",
  ".conf",
  ".cpp",
  ".cs",
  ".cxx",
  ".gradle",
  ".h",
  ".hlsl",
  ".hpp",
  ".ini",
  ".inl",
  ".java",
  ".js",
  ".json",
  ".jsonc",
  ".jsx",
  ".kt",
  ".mjs",
  ".md",
  ".markdown",
  ".ps1",
  ".py",
  ".rs",
  ".sh",
  ".target",
  ".toml",
  ".ts",
  ".tsx",
  ".txt",
  ".uplugin",
  ".uproject",
  ".usf",
  ".ush",
  ".xml",
  ".yaml",
  ".yml",
]);
const SUPPORTED_EXTENSIONLESS = new Set([
  ".editorconfig",
  ".gitattributes",
  ".gitignore",
  "agents.md",
  "cmakelists.txt",
  "license",
  "makefile",
  "readme",
]);
const utf8Decoder = new TextDecoder("utf-8", { fatal: true });
const utf16LeDecoder = new TextDecoder("utf-16le", { fatal: true });
const utf16BeDecoder = new TextDecoder("utf-16be", { fatal: true });

const preparedFileSchema = z.strictObject({
  canonicalPath: z.string().min(3).max(32_768),
  fileIndex: z.string().regex(/^[a-f0-9]{16}$/u),
  hash: z.string().regex(/^sha256:[a-f0-9]{64}$/u),
  lastWriteFileTime: z.string().regex(/^\d+$/u),
  requestedPath: z.string().min(3).max(32_768),
  risks: z.array(z.string().min(1).max(128)).max(32),
  size: z.number().int().nonnegative(),
  volumeSerial: z.number().int().nonnegative(),
});
const storedManifestSchema = z.strictObject({
  files: z.array(preparedFileSchema).min(1),
  manifestHash: z.string().regex(/^sha256:[a-f0-9]{64}$/u),
  sensitivePolicyHash: z.string().regex(/^sha256:[a-f0-9]{64}$/u),
  sensitivePolicyVersion: z.literal(1),
  sourceManifestId: z.string().regex(/^source-[a-f0-9-]{36}$/u),
  version: z.literal(1),
});

export type PreparedSourceFile = z.infer<typeof preparedFileSchema>;
export type StoredSourceManifest = z.infer<typeof storedManifestSchema>;

export interface StableSourceCopier {
  inspectPath(input: { sourcePath: string }): Promise<StablePathInspection>;
  inspectAndCopy(input: {
    destinationPath: string;
    maxBytes: number;
    sourcePath: string;
  }): Promise<StableCopyResult>;
  securePrivatePath(input: {
    directory: boolean;
    targetPath: string;
  }): Promise<unknown>;
}

export class C7SourceError extends Error {
  constructor(
    readonly code:
      | "source_rejected"
      | "source_too_large"
      | "source_changed"
      | "source_manifest_invalid"
      | "platform_unsupported"
      | "internal_error",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "C7SourceError";
  }
}

type SourceStoreOptions = {
  copier: StableSourceCopier;
  createId?(): string;
  limits?: {
    maxFileBytes?: number;
    maxFiles?: number;
    maxTotalBytes?: number;
  };
  policyPath: string;
  runtimeDir: string;
};

export class SourceManifestStore {
  private readonly copier: StableSourceCopier;
  private readonly createId: () => string;
  private readonly maxFileBytes: number;
  private readonly maxFiles: number;
  private readonly maxTotalBytes: number;
  private readonly policyPath: string;
  private readonly runtimeDir: string;

  constructor(options: SourceStoreOptions) {
    this.copier = options.copier;
    this.createId = options.createId ?? (() => `source-${randomUUID()}`);
    this.maxFileBytes = options.limits?.maxFileBytes ?? 5 * 1024 * 1024;
    this.maxFiles = options.limits?.maxFiles ?? 500;
    this.maxTotalBytes = options.limits?.maxTotalBytes ?? 50 * 1024 * 1024;
    this.policyPath = options.policyPath;
    this.runtimeDir = options.runtimeDir;
  }

  async prepare(paths: readonly string[]): Promise<{
    confirmation: string;
    files: readonly PreparedSourceFile[];
    manifestHash: string;
    sensitivePolicyHash: string;
    sensitivePolicyVersion: 1;
    sourceManifestId: string;
  }> {
    const policy = await loadSensitiveFilePolicy(this.policyPath);
    const candidates = await collectCandidates(paths, policy, this.copier);
    this.assertLimits(candidates);
    const temporaryRoot = await this.createTemporaryRoot("prepare");
    try {
      const files = await this.copyAndInspect(
        candidates,
        temporaryRoot,
        policy,
      );
      const sourceManifestId = this.createId();
      if (!/^source-[a-f0-9-]{36}$/u.test(sourceManifestId)) {
        throw new C7SourceError(
          "internal_error",
          "The source manifest identifier generator failed.",
        );
      }
      const manifestHash = computeManifestHash({
        files,
        sensitivePolicyHash: policy.hash,
        sensitivePolicyVersion: policy.version,
      });
      const manifest: StoredSourceManifest = {
        files,
        manifestHash,
        sensitivePolicyHash: policy.hash,
        sensitivePolicyVersion: policy.version,
        sourceManifestId,
        version: 1,
      };
      await this.writeManifest(manifest);
      return {
        confirmation: sourceConfirmation(sourceManifestId, manifestHash),
        files,
        manifestHash,
        sensitivePolicyHash: policy.hash,
        sensitivePolicyVersion: policy.version,
        sourceManifestId,
      };
    } finally {
      await removePrivateTree(temporaryRoot);
    }
  }

  async verify(input: {
    confirmation: string;
    sourceManifestId: string;
  }): Promise<{
    cleanup(): Promise<void>;
    files: readonly PreparedSourceFile[];
    manifestHash: string;
    snapshotPath: string;
    snapshotTreeHash: string;
  }> {
    const policy = await loadSensitiveFilePolicy(this.policyPath);
    const manifest = await this.readManifest(input.sourceManifestId);
    if (
      input.confirmation !==
        sourceConfirmation(manifest.sourceManifestId, manifest.manifestHash) ||
      manifest.sensitivePolicyHash !== policy.hash ||
      manifest.sensitivePolicyVersion !== policy.version ||
      manifest.manifestHash !==
        computeManifestHash({
          files: manifest.files,
          sensitivePolicyHash: manifest.sensitivePolicyHash,
          sensitivePolicyVersion: manifest.sensitivePolicyVersion,
        })
    ) {
      throw new C7SourceError(
        "source_manifest_invalid",
        "The source manifest confirmation or policy binding is invalid.",
      );
    }

    const snapshotPath = await this.createTemporaryRoot("snapshot");
    try {
      const candidates = manifest.files.map((file) => ({
        canonicalPath: file.canonicalPath,
        explicitIgnored: file.risks.includes("explicitly_ignored"),
        fileIndex: file.fileIndex,
        path: file.canonicalPath,
        size: file.size,
        volumeSerial: file.volumeSerial,
      }));
      const current = await this.copyAndInspect(
        candidates,
        snapshotPath,
        policy,
      );
      if (!sourceFilesEqual(manifest.files, current)) {
        throw new C7SourceError(
          "source_changed",
          "At least one confirmed source changed after user confirmation.",
        );
      }
      let cleaned = false;
      return {
        async cleanup() {
          if (cleaned) return;
          await removePrivateTree(snapshotPath);
          cleaned = true;
        },
        files: manifest.files,
        manifestHash: manifest.manifestHash,
        snapshotPath,
        snapshotTreeHash: await hashSourceSnapshotTree(snapshotPath),
      };
    } catch (error) {
      await removePrivateTree(snapshotPath);
      throw error;
    }
  }

  private assertLimits(candidates: readonly CandidateFile[]): void {
    if (candidates.length === 0) {
      throw new C7SourceError(
        "source_rejected",
        "No supported text, source, Markdown, JSON, or YAML files were selected.",
      );
    }
    const total = candidates.reduce((sum, file) => sum + file.size, 0);
    if (
      candidates.length > this.maxFiles ||
      candidates.some((file) => file.size > this.maxFileBytes) ||
      total > this.maxTotalBytes
    ) {
      throw new C7SourceError(
        "source_too_large",
        "The source selection must be narrowed or split into smaller batches.",
      );
    }
  }

  private async copyAndInspect(
    candidates: readonly CandidateFile[],
    destinationRoot: string,
    policy: SensitiveFilePolicy,
  ): Promise<PreparedSourceFile[]> {
    const files: PreparedSourceFile[] = [];
    const identities = new Set<string>();
    let totalBytes = 0;
    for (const [index, candidate] of candidates.entries()) {
      assertSourcePathNotSensitive(candidate.path, policy);
      const destinationDirectory = path.join(
        destinationRoot,
        index.toString().padStart(6, "0"),
      );
      await mkdir(destinationDirectory, { mode: 0o700 });
      await this.copier.securePrivatePath({
        directory: true,
        targetPath: destinationDirectory,
      });
      const destinationPath = path.join(
        destinationDirectory,
        safeSnapshotName(candidate.path),
      );
      let copied: StableCopyResult;
      try {
        copied = await this.copier.inspectAndCopy({
          destinationPath,
          maxBytes: this.maxFileBytes,
          sourcePath: candidate.path,
        });
        await this.copier.securePrivatePath({
          directory: false,
          targetPath: destinationPath,
        });
      } catch (error) {
        throw mapCopyError(error);
      }
      if (
        !pathsEqual(copied.canonicalPath, candidate.canonicalPath) ||
        copied.fileIndex !== candidate.fileIndex ||
        copied.volumeSerial !== candidate.volumeSerial
      ) {
        throw new C7SourceError(
          "source_changed",
          "A selected source identity changed before stable copy.",
        );
      }
      const identityKey = `${copied.volumeSerial}:${copied.fileIndex}`;
      if (identities.has(identityKey)) {
        throw new C7SourceError(
          "source_rejected",
          "Duplicate source file identities are not accepted.",
        );
      }
      identities.add(identityKey);
      totalBytes += copied.size;
      if (totalBytes > this.maxTotalBytes) {
        throw new C7SourceError(
          "source_too_large",
          "The copied source selection exceeds the configured total byte limit.",
        );
      }
      const bytes = await readFile(destinationPath);
      if (
        bytes.byteLength !== copied.size ||
        hashBytes(bytes) !== copied.hash
      ) {
        throw new C7SourceError(
          "source_changed",
          "A selected source copy failed its byte hash verification.",
        );
      }
      const text = decodeSupportedText(bytes, candidate.path);
      assertSourceContentNotSensitive(text, policy);
      files.push({
        canonicalPath: copied.canonicalPath,
        fileIndex: copied.fileIndex,
        hash: copied.hash,
        lastWriteFileTime: copied.lastWriteFileTime,
        requestedPath: candidate.path,
        risks: candidate.explicitIgnored ? ["explicitly_ignored"] : [],
        size: copied.size,
        volumeSerial: copied.volumeSerial,
      });
    }
    return files;
  }

  private async createTemporaryRoot(label: string): Promise<string> {
    const root = path.join(this.runtimeDir, "tmp");
    await mkdir(root, { mode: 0o700, recursive: true });
    const temporaryRoot = await mkdtemp(path.join(root, `${label}-`));
    await this.copier.securePrivatePath({
      directory: true,
      targetPath: temporaryRoot,
    });
    return temporaryRoot;
  }

  private async readManifest(
    sourceManifestId: string,
  ): Promise<StoredSourceManifest> {
    if (!/^source-[a-f0-9-]{36}$/u.test(sourceManifestId)) {
      throw new C7SourceError(
        "source_manifest_invalid",
        "The source manifest identifier is invalid.",
      );
    }
    let value: unknown;
    try {
      const stat = await lstat(this.manifestPath(sourceManifestId));
      if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("invalid");
      value = JSON.parse(
        await readFile(this.manifestPath(sourceManifestId), "utf8"),
      );
    } catch {
      throw new C7SourceError(
        "source_manifest_invalid",
        "The source manifest is missing or invalid.",
      );
    }
    const parsed = storedManifestSchema.safeParse(value);
    if (!parsed.success || parsed.data.sourceManifestId !== sourceManifestId) {
      throw new C7SourceError(
        "source_manifest_invalid",
        "The source manifest is missing or invalid.",
      );
    }
    return parsed.data;
  }

  private async writeManifest(manifest: StoredSourceManifest): Promise<void> {
    const directory = path.join(this.runtimeDir, "manifests");
    await mkdir(directory, { mode: 0o700, recursive: true });
    await this.copier.securePrivatePath({
      directory: true,
      targetPath: directory,
    });
    await withC7Locks(this.runtimeDir, ["manifests"], async () => {
      const finalPath = this.manifestPath(manifest.sourceManifestId);
      const temporaryPath = `${finalPath}.${randomUUID()}.tmp`;
      try {
        const handle = await open(temporaryPath, "wx", 0o600);
        try {
          await handle.writeFile(
            `${JSON.stringify(manifest, null, 2)}\n`,
            "utf8",
          );
          await handle.sync();
        } finally {
          await handle.close();
        }
        await this.copier.securePrivatePath({
          directory: false,
          targetPath: temporaryPath,
        });
        await link(temporaryPath, finalPath);
        await rm(temporaryPath, { force: true });
      } catch (error) {
        await rm(temporaryPath, { force: true });
        throw new C7SourceError(
          "internal_error",
          "The source manifest could not be committed.",
          { cause: error },
        );
      }
    });
  }

  private manifestPath(sourceManifestId: string): string {
    return path.join(this.runtimeDir, "manifests", `${sourceManifestId}.json`);
  }
}

type CandidateFile = {
  canonicalPath: string;
  explicitIgnored: boolean;
  fileIndex: string;
  path: string;
  size: number;
  volumeSerial: number;
};

type IgnoreContext = { basePath: string; rules: Ignore };

async function collectCandidates(
  paths: readonly string[],
  policy: SensitiveFilePolicy,
  copier: StableSourceCopier,
): Promise<CandidateFile[]> {
  if (paths.length === 0 || paths.length > 64) {
    throw new C7SourceError(
      "source_rejected",
      "Provide between one and 64 absolute local source paths.",
    );
  }
  const candidates: CandidateFile[] = [];
  const canonicalPaths = new Set<string>();
  const identities = new Set<string>();
  const requestedPaths = new Set<string>();
  for (const requested of paths) {
    assertLocalAbsolutePath(requested);
    assertSourcePathNotSensitive(requested, policy);
    const requestedKey = path.resolve(requested).toLowerCase();
    if (requestedPaths.has(requestedKey)) {
      throw new C7SourceError(
        "source_rejected",
        "Duplicate source path inputs are not accepted.",
      );
    }
    requestedPaths.add(requestedKey);
    const inspected = await inspectTrustedPath(copier, requested);
    if (!inspected.directory) {
      if (!isSupportedTextPath(requested)) {
        throw new C7SourceError(
          "source_rejected",
          "An explicitly requested file type is unsupported; PDF, DOCX, images, archives, and unknown binary files are not accepted.",
        );
      }
      addCandidate(candidates, canonicalPaths, identities, {
        canonicalPath: inspected.canonicalPath,
        explicitIgnored: isIgnored(
          inspected.canonicalPath,
          false,
          await loadAncestorIgnoreContexts(
            path.dirname(inspected.canonicalPath),
            copier,
          ),
        ),
        fileIndex: inspected.fileIndex,
        path: inspected.canonicalPath,
        size: inspected.size,
        volumeSerial: inspected.volumeSerial,
      });
      continue;
    }
    const ancestorContexts = await loadAncestorIgnoreContexts(
      path.dirname(inspected.canonicalPath),
      copier,
    );
    await walkDirectory(
      inspected.canonicalPath,
      ancestorContexts,
      candidates,
      canonicalPaths,
      identities,
      policy,
      copier,
    );
  }
  return candidates.sort((left, right) =>
    left.path.toLowerCase() < right.path.toLowerCase() ? -1 : 1,
  );
}

async function walkDirectory(
  directory: string,
  inheritedContexts: readonly IgnoreContext[],
  candidates: CandidateFile[],
  canonicalPaths: Set<string>,
  identities: Set<string>,
  policy: SensitiveFilePolicy,
  copier: StableSourceCopier,
): Promise<void> {
  const contexts = [...inheritedContexts];
  const entries = await readdir(directory, { withFileTypes: true });
  entries.sort((left, right) => (left.name < right.name ? -1 : 1));
  const inspectedEntries = new Map<string, StablePathInspection>();
  for (const entry of entries) {
    const candidatePath = path.join(directory, entry.name);
    assertSourcePathNotSensitive(candidatePath, policy);
    inspectedEntries.set(
      entry.name,
      await inspectTrustedPath(copier, candidatePath),
    );
  }
  const gitIgnoreEntry = entries.find(
    (entry) => entry.name.toLowerCase() === ".gitignore",
  );
  if (gitIgnoreEntry) {
    const gitIgnorePath = path.join(directory, gitIgnoreEntry.name);
    const inspected = inspectedEntries.get(gitIgnoreEntry.name);
    if (inspected && !inspected.directory) {
      contexts.push({
        basePath: directory,
        rules: ignore().add(await readFile(gitIgnorePath, "utf8")),
      });
    }
  }

  for (const entry of entries) {
    const candidatePath = path.join(directory, entry.name);
    const inspected = inspectedEntries.get(entry.name);
    if (!inspected) {
      throw new C7SourceError(
        "source_changed",
        "The source tree changed during trusted enumeration.",
      );
    }
    const lowerName = entry.name.toLowerCase();
    if (inspected.directory && DEFAULT_EXCLUDED_DIRECTORIES.has(lowerName)) {
      continue;
    }
    if (isIgnored(candidatePath, inspected.directory, contexts)) {
      continue;
    }
    if (inspected.directory) {
      await walkDirectory(
        inspected.canonicalPath,
        contexts,
        candidates,
        canonicalPaths,
        identities,
        policy,
        copier,
      );
    } else if (isSupportedTextPath(candidatePath)) {
      addCandidate(candidates, canonicalPaths, identities, {
        canonicalPath: inspected.canonicalPath,
        explicitIgnored: false,
        fileIndex: inspected.fileIndex,
        path: inspected.canonicalPath,
        size: inspected.size,
        volumeSerial: inspected.volumeSerial,
      });
    }
  }
}

async function inspectTrustedPath(
  copier: StableSourceCopier,
  sourcePath: string,
): Promise<StablePathInspection> {
  try {
    return await copier.inspectPath({ sourcePath });
  } catch (error) {
    throw mapCopyError(error);
  }
}

function addCandidate(
  candidates: CandidateFile[],
  canonicalPaths: Set<string>,
  identities: Set<string>,
  candidate: CandidateFile,
): void {
  const canonicalKey = normalizePath(candidate.canonicalPath);
  const identityKey = `${candidate.volumeSerial}:${candidate.fileIndex}`;
  if (canonicalPaths.has(canonicalKey) || identities.has(identityKey)) {
    throw new C7SourceError(
      "source_rejected",
      "Duplicate or aliased source files are not accepted.",
    );
  }
  canonicalPaths.add(canonicalKey);
  identities.add(identityKey);
  candidates.push(candidate);
}

async function loadAncestorIgnoreContexts(
  startDirectory: string,
  copier: StableSourceCopier,
): Promise<IgnoreContext[]> {
  const contexts: IgnoreContext[] = [];
  let directory = startDirectory;
  const visited = new Set<string>();
  for (;;) {
    const key = normalizePath(directory);
    if (visited.has(key)) {
      throw new C7SourceError(
        "source_rejected",
        "The source ancestor chain is cyclic.",
      );
    }
    visited.add(key);
    const directoryInspection = await inspectTrustedPath(copier, directory);
    if (!directoryInspection.directory) {
      throw new C7SourceError(
        "source_changed",
        "A source ancestor is no longer a directory.",
      );
    }
    const entries = await readdir(directory, { withFileTypes: true });
    const gitIgnore = entries.find(
      (entry) => entry.name.toLowerCase() === ".gitignore",
    );
    if (gitIgnore) {
      const gitIgnorePath = path.join(directory, gitIgnore.name);
      const inspection = await inspectTrustedPath(copier, gitIgnorePath);
      if (inspection.directory) {
        throw new C7SourceError(
          "source_rejected",
          "A .gitignore entry is not a regular file.",
        );
      }
      contexts.push({
        basePath: directory,
        rules: ignore().add(await readFile(gitIgnorePath, "utf8")),
      });
    }
    const repositoryRoot = entries.some(
      (entry) => entry.name.toLowerCase() === ".git" && entry.isDirectory(),
    );
    const parent = path.dirname(directory);
    if (repositoryRoot || normalizePath(parent) === key) break;
    directory = parent;
  }
  return contexts.reverse();
}

function isIgnored(
  candidatePath: string,
  directory: boolean,
  contexts: readonly IgnoreContext[],
): boolean {
  return contexts.some((context) => {
    const relative = path
      .relative(context.basePath, candidatePath)
      .split(path.sep)
      .join("/");
    return (
      relative !== "" &&
      !relative.startsWith("../") &&
      context.rules.ignores(directory ? `${relative}/` : relative)
    );
  });
}

function assertLocalAbsolutePath(value: string): void {
  if (
    !path.isAbsolute(value) ||
    (process.platform === "win32" && !/^[A-Za-z]:[\\/]/u.test(value)) ||
    value.startsWith("\\\\") ||
    /^\\\\[?.]\\/u.test(value) ||
    value.includes("\0") ||
    (process.platform === "win32" && value.slice(2).includes(":"))
  ) {
    throw new C7SourceError(
      "source_rejected",
      "Only absolute paths on fixed local disks are accepted.",
    );
  }
}

function isSupportedTextPath(filePath: string): boolean {
  const baseName = path.basename(filePath).toLowerCase();
  return (
    SUPPORTED_EXTENSIONS.has(path.extname(baseName)) ||
    SUPPORTED_EXTENSIONLESS.has(baseName)
  );
}

function decodeSupportedText(bytes: Buffer, sourcePath: string): string {
  try {
    if (bytes[0] === 0xff && bytes[1] === 0xfe) {
      const text = utf16LeDecoder.decode(bytes.subarray(2));
      assertNoNul(text);
      return text;
    }
    if (bytes[0] === 0xfe && bytes[1] === 0xff) {
      const text = utf16BeDecoder.decode(bytes.subarray(2));
      assertNoNul(text);
      return text;
    }
    const text = utf8Decoder.decode(
      bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf
        ? bytes.subarray(3)
        : bytes,
    );
    assertNoNul(text);
    return text;
  } catch {
    throw new C7SourceError(
      "source_rejected",
      `A selected ${path.extname(sourcePath) || "text"} file is not safely decodable text.`,
    );
  }
}

function assertNoNul(text: string): void {
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(text)) {
    throw new C7SourceError(
      "source_rejected",
      "A selected text file contains binary control bytes and was rejected.",
    );
  }
}

function safeSnapshotName(sourcePath: string): string {
  const name = path.basename(sourcePath).replace(/[^A-Za-z0-9._-]/gu, "_");
  return name === "" ? "source.txt" : name;
}

function computeManifestHash(input: {
  files: readonly PreparedSourceFile[];
  sensitivePolicyHash: string;
  sensitivePolicyVersion: number;
}): string {
  const hasher = createHash("sha256");
  hasher.update("kg-c7-source-manifest-v1\0", "utf8");
  hasher.update(String(input.sensitivePolicyVersion), "ascii");
  hasher.update("\0", "ascii");
  hasher.update(input.sensitivePolicyHash, "ascii");
  hasher.update("\0", "ascii");
  for (const file of input.files) {
    hasher.update(
      JSON.stringify({
        canonicalPath: file.canonicalPath,
        fileIndex: file.fileIndex,
        hash: file.hash,
        lastWriteFileTime: file.lastWriteFileTime,
        requestedPath: file.requestedPath,
        risks: file.risks,
        size: file.size,
        volumeSerial: file.volumeSerial,
      }),
      "utf8",
    );
    hasher.update("\0", "ascii");
  }
  return `sha256:${hasher.digest("hex")}`;
}

export async function hashSourceSnapshotTree(
  snapshotPath: string,
): Promise<string> {
  if (!path.isAbsolute(snapshotPath)) {
    throw new C7SourceError(
      "source_manifest_invalid",
      "The source snapshot path must be absolute.",
    );
  }
  const files: Array<{ hash: string; relativePath: string; size: number }> = [];
  await collectSnapshotFiles(snapshotPath, "", files);
  files.sort((left, right) =>
    left.relativePath < right.relativePath ? -1 : 1,
  );
  const hasher = createHash("sha256");
  hasher.update("kg-c7-source-snapshot-tree-v1\0", "utf8");
  for (const file of files) {
    hasher.update(file.relativePath, "utf8");
    hasher.update("\0", "ascii");
    hasher.update(String(file.size), "ascii");
    hasher.update("\0", "ascii");
    hasher.update(file.hash, "ascii");
    hasher.update("\0", "ascii");
  }
  return `sha256:${hasher.digest("hex")}`;
}

async function collectSnapshotFiles(
  root: string,
  relativeDirectory: string,
  files: Array<{ hash: string; relativePath: string; size: number }>,
): Promise<void> {
  const directory =
    relativeDirectory === "" ? root : path.join(root, relativeDirectory);
  const stat = await lstat(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new C7SourceError(
      "source_manifest_invalid",
      "The source snapshot tree contains an invalid directory.",
    );
  }
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const relativePath =
      relativeDirectory === ""
        ? entry.name
        : path.join(relativeDirectory, entry.name);
    const normalized = relativePath.split(path.sep).join("/");
    const candidate = path.join(root, relativePath);
    const entryStat = await lstat(candidate);
    if (entry.isSymbolicLink() || entryStat.isSymbolicLink()) {
      throw new C7SourceError(
        "source_manifest_invalid",
        "The source snapshot tree contains a link.",
      );
    }
    if (entry.isDirectory() && entryStat.isDirectory()) {
      await collectSnapshotFiles(root, relativePath, files);
    } else if (entry.isFile() && entryStat.isFile()) {
      const bytes = await readFile(candidate);
      files.push({
        hash: hashBytes(bytes),
        relativePath: normalized,
        size: bytes.byteLength,
      });
    } else {
      throw new C7SourceError(
        "source_manifest_invalid",
        "The source snapshot tree contains a special file object.",
      );
    }
  }
}

function sourceConfirmation(sourceManifestId: string, manifestHash: string) {
  return `confirm-source:${sourceManifestId}:${manifestHash}`;
}

function sourceFilesEqual(
  expected: readonly PreparedSourceFile[],
  current: readonly PreparedSourceFile[],
): boolean {
  return (
    expected.length === current.length &&
    expected.every((file, index) => {
      const candidate = current[index];
      return (
        candidate !== undefined &&
        file.canonicalPath.toLowerCase() ===
          candidate.canonicalPath.toLowerCase() &&
        file.fileIndex === candidate.fileIndex &&
        file.hash === candidate.hash &&
        file.lastWriteFileTime === candidate.lastWriteFileTime &&
        file.size === candidate.size &&
        file.volumeSerial === candidate.volumeSerial
      );
    })
  );
}

async function removePrivateTree(treePath: string): Promise<void> {
  await rm(treePath, {
    force: true,
    maxRetries: 20,
    recursive: true,
    retryDelay: 25,
  });
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function pathsEqual(left: string, right: string): boolean {
  return normalizePath(left) === normalizePath(right);
}

function normalizePath(value: string): string {
  const normalized = path.resolve(value);
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function mapCopyError(error: unknown): C7SourceError {
  const code =
    typeof error === "object" && error !== null && "code" in error
      ? error.code
      : undefined;
  if (code === "source_changed") {
    return new C7SourceError(
      "source_changed",
      "A selected source changed while it was copied.",
    );
  }
  if (code === "source_too_large") {
    return new C7SourceError(
      "source_too_large",
      "A selected source exceeds the configured byte limit.",
    );
  }
  if (code === "platform_unsupported") {
    return new C7SourceError(
      "platform_unsupported",
      "Local source preparation is not verified on this platform.",
    );
  }
  return new C7SourceError(
    "source_rejected",
    "A selected source could not be copied by the trusted local-file helper.",
  );
}
