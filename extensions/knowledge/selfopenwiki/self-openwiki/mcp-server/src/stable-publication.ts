import { createHash } from "node:crypto";
import {
  lstat,
  mkdir,
  open,
  readdir,
  rename,
  rmdir,
  unlink,
} from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { ExternalWikiPublishPlan } from "./publish.js";
import {
  assertMarkdownTreeVersion,
  snapshotMarkdownTree,
  type MarkdownTreeSnapshot,
} from "./snapshot.js";
import type { TransactionPathSecurity } from "./transaction.js";

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const modeSchema = z.strictObject({
  version: z.literal(1),
  planHash: hashSchema,
  beforeRootHash: hashSchema,
  afterRootHash: hashSchema,
  root: z.strictObject({
    dev: z.string().regex(/^\d+$/u),
    ino: z.string().regex(/^\d+$/u),
  }),
});
type StableMode = z.infer<typeof modeSchema>;
type StableInput = {
  formalWikiPath: string;
  journalPath: string;
  plan: ExternalWikiPublishPlan;
  planHash: string;
  before: MarkdownTreeSnapshot;
  after: MarkdownTreeSnapshot;
};

export class StablePublicationError extends Error {
  constructor(
    readonly code: "restore_required" | "wiki_changed",
    message: string,
  ) {
    super(message);
    this.name = "StablePublicationError";
  }
}

// Read-only validation is shared with C7 recovery. A mixed tree is acceptable
// only when the durable v5 mode binds this exact plan and formal directory.
export async function verifyStablePublication(
  input: StableInput,
): Promise<void> {
  const mode = await inspectStableJournal(input);
  if (mode === null) throw invalidJournal();
  await assertRoot(input.formalWikiPath, mode.root);
  assertComposed(await snapshotMarkdownTree(input.formalWikiPath), input);
}

export async function verifyStablePublicationAbort(
  input: StableInput,
): Promise<void> {
  const mode = await inspectStableJournal(input);
  if (await inspect(path.join(input.journalPath, "commit.marker")))
    throw invalidJournal();
  if (mode !== null) await assertRoot(input.formalWikiPath, mode.root);
  const current = await snapshotMarkdownTree(input.formalWikiPath);
  const before = new Map(
    input.before.files.map((file) => [file.relativePath, file]),
  );
  const after = new Map(
    input.after.files.map((file) => [file.relativePath, file]),
  );
  const actual = new Map(
    current.files.map((file) => [file.relativePath, file]),
  );
  // Explicit abort may keep an external conflict, but must never discard the
  // recovery obligation while any approved after change is still installed.
  for (const name of new Set([...before.keys(), ...after.keys()])) {
    const old = before.get(name);
    const desired = after.get(name);
    if (old?.hash === desired?.hash && old?.size === desired?.size) continue;
    const present = actual.get(name);
    if (
      desired === undefined
        ? present === undefined
        : present?.hash === desired.hash && present.size === desired.size
    )
      throw invalidJournal();
  }
}

export async function prepareStablePublication(
  input: StableInput & { security: TransactionPathSecurity },
): Promise<boolean> {
  const existing = await inspectStableJournal(input);
  if (existing !== null) {
    await assertRoot(input.formalWikiPath, existing.root);
    const current = await snapshotMarkdownTree(input.formalWikiPath);
    assertComposed(current, input);
    return current.rootHash !== input.before.rootHash;
  }
  await assertMarkdownTreeVersion(input.formalWikiPath, input.before);
  const root = await directoryIdentity(input.formalWikiPath);
  const mode: StableMode = {
    version: 1,
    planHash: input.planHash,
    beforeRootHash: input.before.rootHash,
    afterRootHash: input.after.rootHash,
    root,
  };
  const temporary = path.join(input.journalPath, "stable-root.json.tmp");
  await removeScratch(temporary);
  await durableWrite(
    temporary,
    Buffer.from(`${JSON.stringify(mode)}\n`),
    input.security,
  );
  await assertRoot(input.formalWikiPath, root);
  await assertMarkdownTreeVersion(input.formalWikiPath, input.before);
  await rename(temporary, path.join(input.journalPath, "stable-root.json"));
  return false;
}

export async function applyStablePublication(
  input: StableInput & {
    security: TransactionPathSecurity;
    target: "before" | "after";
    onChange?(): Promise<void> | void;
  },
): Promise<void> {
  const mode = await inspectStableJournal(input);
  if (mode === null) throw invalidJournal();
  await assertRoot(input.formalWikiPath, mode.root);
  const current = await snapshotMarkdownTree(input.formalWikiPath);
  assertComposed(current, input);
  const target = input[input.target];
  const desired = new Map(
    target.files.map((file) => [file.relativePath, file]),
  );
  const actual = new Map(
    current.files.map((file) => [file.relativePath, file]),
  );
  for (const file of current.files) {
    if (desired.has(file.relativePath)) continue;
    const destination = containedPath(input.formalWikiPath, file.relativePath);
    const parents = await bindParents(
      input.formalWikiPath,
      file.relativePath,
      false,
    );
    await assertRoot(input.formalWikiPath, mode.root);
    await assertParents(parents);
    await assertFile(destination, file);
    await unlink(destination);
    actual.delete(file.relativePath);
    await input.onChange?.();
  }
  for (const file of target.files) {
    const previous = actual.get(file.relativePath);
    if (previous?.hash === file.hash && previous.size === file.size) continue;
    const source = containedPath(
      path.join(input.journalPath, input.target),
      file.relativePath,
    );
    const bytes = await readBoundFile(source, file);
    const stage = path.join(input.journalPath, "apply.tmp");
    await removeScratch(stage);
    await durableWrite(stage, bytes, input.security);
    const destination = containedPath(input.formalWikiPath, file.relativePath);
    const parents = await bindParents(
      input.formalWikiPath,
      file.relativePath,
      true,
    );
    const existing = await inspect(destination);
    if (existing?.isDirectory() && !existing.isSymbolicLink()) {
      // A Markdown path may replace a former directory, but never erase its
      // contents. Only empty directories needed for this conversion are removed.
      await removeEmptyDirectories(destination);
    }
    // ACL/staging can yield. Recheck after those awaits, immediately before the
    // operation. Uncooperative external writers still require a quiet window.
    await assertRoot(input.formalWikiPath, mode.root);
    await assertParents(parents);
    await assertFile(destination, previous);
    await rename(stage, destination);
    actual.set(file.relativePath, file);
    await input.onChange?.();
  }
  await assertRoot(input.formalWikiPath, mode.root);
  await assertMarkdownTreeVersion(input.formalWikiPath, target);
}

async function inspectStableJournal(
  input: StableInput,
): Promise<StableMode | null> {
  if (input.plan.version !== 5) throw invalidJournal();
  await directoryIdentity(input.journalPath);
  const entries = await readdir(input.journalPath, { withFileTypes: true });
  const required = new Set(["before", "after", "publish", "plan.json"]);
  for (const entry of entries) {
    const isTree = ["before", "after", "publish"].includes(entry.name);
    const isFile =
      [
        "plan.json",
        "stable-root.json",
        "commit.marker",
        "apply.tmp",
        "stable-root.json.tmp",
      ].includes(entry.name) ||
      /^(?:plan\.json|commit\.marker)\.[a-f0-9-]{36}\.tmp$/u.test(entry.name);
    const stat = await lstat(path.join(input.journalPath, entry.name));
    if (
      stat.isSymbolicLink() ||
      (!isTree && !isFile) ||
      (isTree ? !stat.isDirectory() : !stat.isFile())
    )
      throw invalidJournal();
    required.delete(entry.name);
  }
  if (required.size !== 0) throw invalidJournal();
  const planBytes = await readRegular(
    path.join(input.journalPath, "plan.json"),
  );
  if (hashBytes(planBytes) !== input.planHash) throw invalidJournal();
  await Promise.all([
    assertMarkdownTreeVersion(
      path.join(input.journalPath, "before"),
      input.before,
    ),
    assertMarkdownTreeVersion(
      path.join(input.journalPath, "after"),
      input.after,
    ),
    assertMarkdownTreeVersion(
      path.join(input.journalPath, "publish"),
      input.after,
    ),
  ]);
  const modePath = path.join(input.journalPath, "stable-root.json");
  if ((await inspect(modePath)) === null) {
    if (await inspect(path.join(input.journalPath, "commit.marker")))
      throw invalidJournal();
    return null;
  }
  let mode: StableMode;
  try {
    mode = modeSchema.parse(
      JSON.parse((await readRegular(modePath)).toString("utf8")),
    );
  } catch {
    throw invalidJournal();
  }
  if (
    mode.planHash !== input.planHash ||
    mode.beforeRootHash !== input.before.rootHash ||
    mode.afterRootHash !== input.after.rootHash
  )
    throw invalidJournal();
  return mode;
}

function assertComposed(
  current: MarkdownTreeSnapshot,
  input: StableInput,
): void {
  const before = new Map(
    input.before.files.map((file) => [file.relativePath, file]),
  );
  const after = new Map(
    input.after.files.map((file) => [file.relativePath, file]),
  );
  const actual = new Set<string>();
  for (const file of current.files) {
    const alternatives = [
      before.get(file.relativePath),
      after.get(file.relativePath),
    ];
    if (
      !alternatives.some(
        (known) => known?.hash === file.hash && known.size === file.size,
      )
    )
      throw changed();
    actual.add(file.relativePath);
  }
  for (const name of before.keys()) {
    if (after.has(name) && !actual.has(name)) throw changed();
  }
}

type Identity = { dev: string; ino: string };
async function directoryIdentity(directory: string): Promise<Identity> {
  const stat = await lstat(directory, { bigint: true });
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw invalidJournal();
  return { dev: String(stat.dev), ino: String(stat.ino) };
}
async function assertRoot(
  directory: string,
  expected: Identity,
): Promise<void> {
  const actual = await directoryIdentity(directory);
  if (actual.dev !== expected.dev || actual.ino !== expected.ino)
    throw changed();
}
async function bindParents(
  root: string,
  relativePath: string,
  create: boolean,
) {
  const parents: Array<{ directory: string; identity: Identity }> = [];
  let directory = root;
  for (const segment of ["", ...relativePath.split("/").slice(0, -1)]) {
    if (segment) directory = path.join(directory, segment);
    await assertParents(parents);
    if (create && (await inspect(directory)) === null) await mkdir(directory);
    parents.push({ directory, identity: await directoryIdentity(directory) });
  }
  return parents;
}
async function assertParents(
  parents: Array<{ directory: string; identity: Identity }>,
) {
  for (const parent of parents)
    await assertRoot(parent.directory, parent.identity);
}
async function inspect(target: string) {
  return lstat(target).catch((error: unknown) => {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  });
}
async function assertFile(
  target: string,
  expected: MarkdownTreeSnapshot["files"][number] | undefined,
) {
  if (expected === undefined) {
    if ((await inspect(target)) !== null) throw changed();
  } else await readBoundFile(target, expected);
}
async function readRegular(target: string): Promise<Buffer> {
  const stat = await lstat(target, { bigint: true });
  if (!stat.isFile() || stat.isSymbolicLink()) throw invalidJournal();
  const handle = await open(target, "r");
  try {
    const opened = await handle.stat({ bigint: true });
    if (!opened.isFile() || opened.dev !== stat.dev || opened.ino !== stat.ino)
      throw changed();
    const bytes = await handle.readFile();
    const after = await lstat(target, { bigint: true });
    if (
      after.isSymbolicLink() ||
      after.dev !== stat.dev ||
      after.ino !== stat.ino ||
      after.size !== BigInt(bytes.length) ||
      after.mtimeNs !== stat.mtimeNs
    )
      throw changed();
    return bytes;
  } finally {
    await handle.close();
  }
}
async function readBoundFile(
  target: string,
  expected: MarkdownTreeSnapshot["files"][number],
) {
  const bytes = await readRegular(target);
  if (bytes.length !== expected.size || hashBytes(bytes) !== expected.hash)
    throw changed();
  return bytes;
}
async function durableWrite(
  target: string,
  bytes: Buffer,
  security: TransactionPathSecurity,
) {
  const handle = await open(target, "wx", 0o600);
  try {
    await handle.writeFile(bytes);
    await handle.sync();
  } finally {
    await handle.close();
  }
  await security.securePrivatePath({ directory: false, targetPath: target });
}
async function removeScratch(target: string) {
  const stat = await inspect(target);
  if (stat === null) return;
  if (!stat.isFile() || stat.isSymbolicLink()) throw invalidJournal();
  await unlink(target);
}
async function removeEmptyDirectories(directory: string): Promise<void> {
  await directoryIdentity(directory);
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) throw changed();
    await removeEmptyDirectories(path.join(directory, entry.name));
  }
  await rmdir(directory);
}
function containedPath(root: string, relative: string) {
  const segments = relative.split("/");
  if (
    segments.some(
      (segment) =>
        !segment ||
        segment === "." ||
        segment === ".." ||
        /[\\:]/u.test(segment),
    ) ||
    [".git", ".claims", ".selfopenwiki"].includes(segments[0]!)
  )
    throw invalidJournal();
  const result = path.resolve(root, ...segments);
  if (!result.startsWith(`${path.resolve(root)}${path.sep}`))
    throw invalidJournal();
  return result;
}
function hashBytes(bytes: Buffer): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
function invalidJournal() {
  return new StablePublicationError(
    "restore_required",
    "The stable publication journal is incomplete or conflicts with its plan.",
  );
}
function changed() {
  return new StablePublicationError(
    "wiki_changed",
    "The stable Wiki paths or content changed during publication.",
  );
}
