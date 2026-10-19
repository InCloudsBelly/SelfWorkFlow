import { createHash } from "node:crypto";
import { lstat, mkdir, open, realpath, rename, rm } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);

type FileIdentity = {
  readonly birthtimeMs: number;
  readonly dev: number;
  readonly ino: number;
};

type BoundDirectory = {
  readonly absolutePath: string;
  readonly identity: FileIdentity;
};
const sidecarSchema = z
  .strictObject({
    claims: z.array(
      z.strictObject({
        evidence: z.array(
          z.strictObject({
            resource: z.string().trim().min(1).max(1_024),
            version: z.string().trim().min(1).max(512),
          }),
        ),
        id: z.string().trim().min(1).max(1_024),
        statement: z.string().trim().min(1).max(4_096),
      }),
    ),
    pageVersion: hashSchema,
    schemaVersion: z.literal(1),
  })
  .superRefine((value, context) => {
    const ids = value.claims.map((claim) => claim.id);
    if (new Set(ids).size !== ids.length) {
      context.addIssue({
        code: "custom",
        message: "Claim ids must be unique.",
      });
    }
    for (const [claimIndex, claim] of value.claims.entries()) {
      for (const [evidenceIndex, evidence] of claim.evidence.entries()) {
        if (!isValidPersonalEvidenceResource(evidence.resource)) {
          context.addIssue({
            code: "custom",
            message: `Claim evidence ${claimIndex}:${evidenceIndex} is not a safe repo:// or wiki:// resource.`,
          });
        }
      }
    }
  });

export type PersonalClaimsSnapshot = {
  readonly claims: readonly {
    readonly evidence: readonly { readonly resource: string }[];
    readonly id: string;
    readonly statement: string;
  }[];
  readonly source: "authoritative" | "none";
};

export interface PersonalClaimsResolver {
  load(wikiRoot: string, pagePath: string): Promise<PersonalClaimsSnapshot>;
}

export function personalClaimsSidecarPath(pagePath: string): string {
  const normalizedPage = validatePagePath(pagePath);
  return `.claims/${normalizedPage.replace(/\.md$/iu, ".json")}`;
}

export function createPersonalClaimsPayload(
  claims: readonly unknown[],
  pageBytes: Uint8Array,
): { readonly bytes: Uint8Array; readonly hash: string } {
  const normalizedClaims = normalizeClaimsForSidecar(claims);
  const payload = {
    claims: normalizedClaims,
    pageVersion: hashBytes(pageBytes),
    schemaVersion: 1,
  };
  const bytes = Buffer.from(`${JSON.stringify(payload)}\n`, "utf8");
  return { bytes, hash: hashBytes(bytes) };
}

export function hashPersonalClaimsBytes(bytes: Uint8Array): string {
  return hashBytes(bytes);
}

export async function inspectPersonalClaimsSidecar(
  wikiRoot: string,
  pagePath: string,
): Promise<string | null> {
  const rootDirectory = await bindDirectory(wikiRoot);
  const root = rootDirectory.absolutePath;
  const sidecar = path.resolve(
    root,
    ...personalClaimsSidecarPath(pagePath).split("/"),
  );
  await assertContained(root, sidecar);
  const directories = await bindDirectoryChain(
    rootDirectory,
    path.dirname(sidecar),
    true,
  );
  if (directories === null) return null;
  const stat = await lstat(sidecar).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (stat === null) return null;
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim sidecar must be a regular file.",
    );
  }
  return hashBytes(await readBoundFile(sidecar, stat, directories));
}

/**
 * Persists the complete reconciled Claim set for one published personal page.
 * The personal adapter owns the sidecar; C7 continues to own Markdown CAS and
 * publication. Existing evidence versions are intentionally not exposed to
 * the host-facing protocol, so newly written records use a deterministic
 * personal resource version token.
 */
export async function writePersonalClaims(
  wikiRoot: string,
  pagePath: string,
  claims: readonly unknown[],
  pageBytes: Uint8Array,
): Promise<void> {
  const rootDirectory = await bindDirectory(wikiRoot);
  const root = rootDirectory.absolutePath;
  const normalizedPage = validatePagePath(pagePath);
  const sidecar = path.resolve(
    root,
    ...personalClaimsSidecarPath(normalizedPage).split("/"),
  );
  await assertContained(root, sidecar);
  const payload = createPersonalClaimsPayload(claims, pageBytes);
  const directory = path.dirname(sidecar);
  const directories = await ensureSafeDirectory(rootDirectory, directory);
  const temporary = `${sidecar}.${claimsHash(payload.bytes).slice(7, 23)}.tmp`;
  let temporaryIdentity: FileIdentity | null = null;
  try {
    const handle = await open(temporary, "wx", 0o600);
    try {
      const opened = await handle.stat();
      if (!opened.isFile()) {
        throw new Error("The temporary Claim sidecar is not a regular file.");
      }
      temporaryIdentity = opened;
      await assertDirectoryChain(directories);
      await handle.writeFile(payload.bytes);
      await handle.sync();
      const after = await handle.stat();
      if (!after.isFile() || !sameFileIdentity(opened, after)) {
        throw new Error("The temporary Claim sidecar changed while written.");
      }
    } finally {
      await handle.close();
    }
    await assertDirectoryChain(directories);
    await assertBoundFilePath(temporary, temporaryIdentity);
    await assertSafeDestination(sidecar);
    await rename(temporary, sidecar);
    await assertDirectoryChain(directories);
    await assertBoundFilePath(sidecar, temporaryIdentity);
  } catch (error) {
    if (temporaryIdentity !== null) {
      await removeBoundTemporary(temporary, temporaryIdentity, directories);
    }
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim sidecar could not be written atomically.",
      { cause: error },
    );
  }
}

export async function removePersonalClaims(
  wikiRoot: string,
  pagePath: string,
): Promise<void> {
  const rootDirectory = await bindDirectory(wikiRoot);
  const root = rootDirectory.absolutePath;
  const normalizedPage = validatePagePath(pagePath);
  const sidecar = path.resolve(
    root,
    ...personalClaimsSidecarPath(normalizedPage).split("/"),
  );
  await assertContained(root, sidecar);
  const directories = await bindDirectoryChain(
    rootDirectory,
    path.dirname(sidecar),
    true,
  );
  if (directories === null) return;
  const stat = await lstat(sidecar).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (stat === null) return;
  if (stat.isSymbolicLink() || !stat.isFile()) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim sidecar must be a regular file before removal.",
    );
  }
  await assertDirectoryChain(directories);
  await assertBoundFilePath(sidecar, stat);
  await rm(sidecar, { force: false });
  await assertDirectoryChain(directories);
  if (
    await lstat(sidecar).catch((error: unknown) =>
      isMissing(error) ? null : Promise.reject(error),
    )
  ) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim sidecar remained after removal.",
    );
  }
}

export class PersonalClaimsError extends Error {
  constructor(
    readonly code: "validation_failed",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "PersonalClaimsError";
  }
}

export class FilePersonalClaimsResolver implements PersonalClaimsResolver {
  async load(
    wikiRoot: string,
    pagePath: string,
  ): Promise<PersonalClaimsSnapshot> {
    const rootDirectory = await bindDirectory(wikiRoot);
    const root = rootDirectory.absolutePath;
    const normalizedPage = validatePagePath(pagePath);
    const pageFile = path.resolve(root, ...normalizedPage.split("/"));
    await assertContained(root, pageFile);
    const sidecar = path.resolve(
      root,
      ...personalClaimsSidecarPath(normalizedPage).split("/"),
    );
    await assertContained(root, sidecar);
    const pageDirectories = await bindDirectoryChain(
      rootDirectory,
      path.dirname(pageFile),
      false,
    );
    const sidecarDirectories = await bindDirectoryChain(
      rootDirectory,
      path.dirname(sidecar),
      true,
    );
    if (sidecarDirectories === null) {
      return { claims: [], source: "none" };
    }
    const sidecarStat = await lstat(sidecar).catch((error: unknown) => {
      if (isMissing(error)) return null;
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim sidecar could not be inspected.",
        { cause: error },
      );
    });
    if (sidecarStat === null) return { claims: [], source: "none" };
    if (sidecarStat.isSymbolicLink() || !sidecarStat.isFile()) {
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim sidecar must be a regular file.",
      );
    }
    if (pageDirectories === null) {
      throw new PersonalClaimsError(
        "validation_failed",
        "A personal Wiki Claim sidecar must have a current Markdown page.",
      );
    }
    const pageStat = await lstat(pageFile).catch(() => null);
    if (pageStat === null || pageStat.isSymbolicLink() || !pageStat.isFile()) {
      throw new PersonalClaimsError(
        "validation_failed",
        "A personal Wiki Claim sidecar must have a current Markdown page.",
      );
    }
    let parsed: unknown;
    try {
      const sidecarBytes = await readBoundFile(
        sidecar,
        sidecarStat,
        sidecarDirectories,
      );
      parsed = JSON.parse(sidecarBytes.toString("utf8"));
    } catch (error) {
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim sidecar is not valid JSON.",
        { cause: error },
      );
    }
    const result = sidecarSchema.safeParse(parsed);
    if (!result.success) {
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim sidecar does not match the supported schema.",
      );
    }
    const pageBytes = await readBoundFile(
      pageFile,
      pageStat,
      mergeDirectories(pageDirectories, sidecarDirectories),
    );
    await assertBoundFilePath(sidecar, sidecarStat);
    await assertDirectoryChain(sidecarDirectories);
    const pageHash = hashBytes(pageBytes);
    if (pageHash !== result.data.pageVersion) {
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim sidecar is stale for the current page.",
      );
    }
    return {
      claims: result.data.claims.map((claim) => ({
        evidence: claim.evidence.map(({ resource }) => ({ resource })),
        id: claim.id,
        statement: claim.statement,
      })),
      source: "authoritative",
    };
  }
}

function validatePagePath(value: string): string {
  const normalized = value.replaceAll("\\", "/");
  if (
    normalized !== value ||
    normalized.length === 0 ||
    path.posix.normalize(normalized) !== normalized ||
    normalized.startsWith("/") ||
    !normalized.toLowerCase().endsWith(".md") ||
    normalized
      .split("/")
      .some((segment) => !segment || segment === "." || segment === "..")
  ) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim page path is invalid.",
    );
  }
  return normalized;
}

async function bindDirectory(value: string): Promise<BoundDirectory> {
  if (!path.isAbsolute(value)) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki root must be absolute.",
    );
  }
  const before = await lstat(value).catch((error: unknown) => {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki root is unavailable.",
      { cause: error },
    );
  });
  if (before.isSymbolicLink() || !before.isDirectory()) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki root must be a real directory.",
    );
  }
  const canonicalRoot = await realpath(value).catch((error: unknown) => {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki root is unavailable.",
      { cause: error },
    );
  });
  const [afterPath, canonical] = await Promise.all([
    lstat(value),
    lstat(canonicalRoot),
  ]).catch((error: unknown) => {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki root changed while it was inspected.",
      { cause: error },
    );
  });
  if (
    !afterPath.isDirectory() ||
    afterPath.isSymbolicLink() ||
    !canonical.isDirectory() ||
    canonical.isSymbolicLink() ||
    !sameFileIdentity(before, afterPath) ||
    !sameFileIdentity(before, canonical)
  ) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki root changed while it was inspected.",
    );
  }
  return { absolutePath: canonicalRoot, identity: canonical };
}

async function assertContained(root: string, candidate: string): Promise<void> {
  const canonical = path.resolve(candidate);
  const relative = path.relative(root, canonical);
  if (
    relative === "" ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim path escapes the Wiki root.",
    );
  }
}

async function ensureSafeDirectory(
  rootDirectory: BoundDirectory,
  target: string,
): Promise<readonly BoundDirectory[]> {
  const rootPath = rootDirectory.absolutePath;
  await assertContained(rootPath, target);
  const directories: BoundDirectory[] = [rootDirectory];
  let current = rootPath;
  for (const segment of path
    .relative(current, target)
    .split(path.sep)
    .filter(Boolean)) {
    await assertDirectoryChain(directories);
    current = path.join(current, segment);
    const existing = await lstat(current).catch((error: unknown) => {
      if (isMissing(error)) return null;
      throw error;
    });
    if (existing === null) {
      await mkdir(current, { mode: 0o700 });
    }
    directories.push(await bindDirectoryEntry(current));
  }
  await assertDirectoryChain(directories);
  return directories;
}

async function bindDirectoryEntry(directory: string): Promise<BoundDirectory> {
  const before = await lstat(directory).catch((error: unknown) => {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim directory is unavailable.",
      { cause: error },
    );
  });
  if (before.isSymbolicLink() || !before.isDirectory()) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim directory cannot be a link or non-directory.",
    );
  }
  const canonical = await realpath(directory).catch((error: unknown) => {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim directory is unavailable.",
      { cause: error },
    );
  });
  const [afterPath, canonicalStat] = await Promise.all([
    lstat(directory),
    lstat(canonical),
  ]).catch((error: unknown) => {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim directory changed while it was inspected.",
      { cause: error },
    );
  });
  if (
    afterPath.isSymbolicLink() ||
    !afterPath.isDirectory() ||
    canonicalStat.isSymbolicLink() ||
    !canonicalStat.isDirectory() ||
    !sameFileIdentity(before, afterPath) ||
    !sameFileIdentity(before, canonicalStat) ||
    !samePath(canonical, directory)
  ) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim directory changed while it was inspected.",
    );
  }
  return { absolutePath: directory, identity: canonicalStat };
}

async function bindDirectoryChain(
  root: BoundDirectory,
  target: string,
  allowMissing: boolean,
): Promise<readonly BoundDirectory[] | null> {
  const rootPath = root.absolutePath;
  const relative = path.relative(rootPath, path.resolve(target));
  if (relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim path escapes the Wiki root.",
    );
  }
  const directories: BoundDirectory[] = [root];
  let current = rootPath;
  for (const segment of relative.split(path.sep).filter(Boolean)) {
    await assertDirectoryChain(directories);
    current = path.join(current, segment);
    const stat = await lstat(current).catch((error: unknown) => {
      if (allowMissing && isMissing(error)) return null;
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim directory is unavailable.",
        { cause: error },
      );
    });
    if (stat === null) return null;
    directories.push(await bindDirectoryEntry(current));
  }
  await assertDirectoryChain(directories);
  return directories;
}

async function readBoundFile(
  filePath: string,
  expected: FileIdentity,
  directories: readonly BoundDirectory[],
): Promise<Buffer> {
  const handle = await open(filePath, "r").catch((error: unknown) => {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim file could not be read.",
      { cause: error },
    );
  });
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || !sameFileIdentity(expected, opened)) {
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim file changed before it was read.",
      );
    }
    await assertDirectoryChain(directories);
    await assertBoundFilePath(filePath, opened);
    const bytes = await handle.readFile();
    const after = await handle.stat();
    if (!after.isFile() || !sameFileIdentity(opened, after)) {
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim file changed while it was read.",
      );
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
  const stat = await lstat(filePath).catch((error: unknown) => {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim file changed while it was read.",
      { cause: error },
    );
  });
  if (
    !stat.isFile() ||
    stat.isSymbolicLink() ||
    !sameFileIdentity(expected, stat)
  ) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim file changed while it was read.",
    );
  }
}

async function assertDirectoryChain(
  directories: readonly BoundDirectory[],
): Promise<void> {
  for (const directory of directories) {
    const stat = await lstat(directory.absolutePath).catch((error: unknown) => {
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim directory changed.",
        { cause: error },
      );
    });
    if (
      stat.isSymbolicLink() ||
      !stat.isDirectory() ||
      !sameFileIdentity(directory.identity, stat)
    ) {
      throw new PersonalClaimsError(
        "validation_failed",
        "The personal Wiki Claim directory changed.",
      );
    }
  }
}

async function assertSafeDestination(filePath: string): Promise<void> {
  const stat = await lstat(filePath).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (stat !== null && (stat.isSymbolicLink() || !stat.isFile())) {
    throw new PersonalClaimsError(
      "validation_failed",
      "The personal Wiki Claim sidecar must be a regular file.",
    );
  }
}

async function removeBoundTemporary(
  filePath: string,
  expected: FileIdentity,
  directories: readonly BoundDirectory[],
): Promise<void> {
  try {
    await assertDirectoryChain(directories);
    await assertBoundFilePath(filePath, expected);
    await rm(filePath, { force: false });
  } catch {
    // Never remove a path after its bound directory or file identity changed.
  }
}

function mergeDirectories(
  first: readonly BoundDirectory[],
  second: readonly BoundDirectory[],
): readonly BoundDirectory[] {
  const merged = [...first];
  for (const directory of second) {
    if (
      !merged.some((item) =>
        samePath(item.absolutePath, directory.absolutePath),
      )
    ) {
      merged.push(directory);
    }
  }
  return merged;
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

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function normalizeClaimsForSidecar(claims: readonly unknown[]) {
  const ids = new Set<string>();
  return claims.map((value, index) => {
    if (
      typeof value !== "object" ||
      value === null ||
      typeof (value as { statement?: unknown }).statement !== "string" ||
      !Array.isArray((value as { evidence?: unknown }).evidence)
    ) {
      throw new PersonalClaimsError(
        "validation_failed",
        `Personal Claim ${index} is not a valid reconciled Claim.`,
      );
    }
    const record = value as {
      id?: unknown;
      statement: string;
      evidence: readonly unknown[];
    };
    const evidence = record.evidence.map((entry, evidenceIndex) => {
      if (
        typeof entry !== "object" ||
        entry === null ||
        typeof (entry as { resource?: unknown }).resource !== "string" ||
        (entry as { resource: string }).resource.trim() === ""
      ) {
        throw new PersonalClaimsError(
          "validation_failed",
          `Personal Claim evidence ${index}:${evidenceIndex} is invalid.`,
        );
      }
      const resource = (entry as { resource: string }).resource;
      if (!isValidPersonalEvidenceResource(resource)) {
        throw new PersonalClaimsError(
          "validation_failed",
          `Personal Claim evidence ${index}:${evidenceIndex} has an unsafe resource.`,
        );
      }
      return {
        resource,
        version: `personal-resource-v1:${claimsHash(resource).slice(7)}`,
      };
    });
    const id =
      typeof record.id === "string" && record.id.trim() !== ""
        ? record.id
        : `personal-claim-${claimsHash({ evidence, statement: record.statement }).slice(7, 31)}`;
    if (ids.has(id)) {
      throw new PersonalClaimsError(
        "validation_failed",
        "Personal Claim ids must be unique before publication.",
      );
    }
    ids.add(id);
    return { evidence, id, statement: record.statement };
  });
}

export function isValidPersonalEvidenceResource(resource: string): boolean {
  const match = /^(repo|wiki):\/\/(.+)$/u.exec(resource);
  if (match === null) return false;
  const reference = match[2]!.split("#", 1)[0]!;
  return (
    reference.length > 0 &&
    !reference.includes("\\") &&
    !reference.startsWith("/") &&
    path.posix.normalize(reference) === reference &&
    reference
      .split("/")
      .every((segment) => segment !== ".." && segment !== "") &&
    !reference.toLowerCase().includes(".git") &&
    !reference.startsWith(".claims/") &&
    /^[A-Za-z0-9._~:/?\[\]@!$&'()*+,;=%-]+$/u.test(resource)
  );
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

function claimsHash(value: unknown): string {
  const hasher = createHash("sha256");
  hasher.update("selfopenwiki:personal-claims-v1\0", "utf8");
  hasher.update(canonicalJson(value), "utf8");
  return `sha256:${hasher.digest("hex")}`;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}
