import { lstatSync } from "node:fs";
import {
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const STORAGE_CONFIG_SCHEMA_VERSION = 1;

const CONFIG_KEYS = new Set([
  "schemaVersion",
  "generation",
  "wikiRoot",
  "runtimeRoot",
]);

function absolutePath(value, label) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    !path.isAbsolute(value)
  ) {
    throw new Error(`invalid storage config: ${label} must be absolute`);
  }
  const resolved = path.resolve(value);
  if (resolved !== value) {
    throw new Error(`invalid storage config: ${label} is not canonical`);
  }
  return resolved;
}

function assertSafePathSyntax(value, label) {
  if (/[*?<>|"\u0000-\u001f]/u.test(value)) {
    throw new Error(
      `invalid storage config: ${label} contains a forbidden character`,
    );
  }
  const normalized = value.replaceAll("/", "\\");
  const withoutDrive = /^[A-Za-z]:\\/u.test(normalized)
    ? normalized.slice(3)
    : normalized;
  const segments = withoutDrive.split("\\").filter(Boolean);
  for (const [index, segment] of segments.entries()) {
    if (!segment) continue;
    if (
      segment.endsWith(".") ||
      segment.endsWith(" ") ||
      segment.includes("~")
    ) {
      throw new Error(
        `invalid storage config: ${label} contains an alias-like segment`,
      );
    }
    if (/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/iu.test(segment)) {
      throw new Error(
        `invalid storage config: ${label} contains a reserved name`,
      );
    }
    if (segment.includes(":")) {
      throw new Error(`invalid storage config: ${label} contains ADS syntax`);
    }
  }
}

function assertNonLinkStat(stats, label) {
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new Error(
      `invalid storage config: ${label} must be a non-link directory`,
    );
  }
}

async function validateWikiLayout(layout) {
  assertSafePathSyntax(layout.wikiRoot, "wikiRoot");
  assertSafePathSyntax(layout.runtimeRoot, "runtimeRoot");
  const ancestors = [];
  let cursor = layout.wikiRoot;
  while (true) {
    ancestors.push(cursor);
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
  ancestors.reverse();
  let rootStats;
  for (const candidate of ancestors) {
    try {
      const current = await lstat(candidate);
      if (current.isSymbolicLink()) {
        throw new Error(`invalid storage config: linked ancestor ${candidate}`);
      }
      if (candidate === layout.wikiRoot) rootStats = current;
    } catch (error) {
      if (error?.code === "ENOENT" && candidate === layout.wikiRoot) break;
      if (error?.code === "ENOENT") {
        throw new Error(
          "invalid storage config: Wiki-root parent chain is missing",
        );
      }
      throw error;
    }
  }
  if (rootStats) assertNonLinkStat(rootStats, "wikiRoot");
  else {
    const parent = await lstat(path.dirname(layout.wikiRoot));
    assertNonLinkStat(parent, "wikiRoot parent");
  }
  try {
    const runtimeStats = await lstat(layout.runtimeRoot);
    assertNonLinkStat(runtimeStats, "runtimeRoot");
    if (rootStats) {
      const runtimeDevice = (await stat(layout.runtimeRoot)).dev;
      const rootDevice = (await stat(layout.wikiRoot)).dev;
      if (runtimeDevice !== rootDevice) {
        throw new Error(
          "invalid storage config: Wiki and runtime roots cross volumes",
        );
      }
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

async function assertNoActiveTransaction(runtimeRoot) {
  try {
    const entries = await readdir(path.join(runtimeRoot, "migration"));
    if (entries.length > 0)
      throw new Error("storage config busy: active migration or recovery");
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function defaultConfigPath() {
  const localAppData =
    process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local");
  return path.join(localAppData, "SelfOpenWiki", "config.json");
}

export function deriveWikiLayout(wikiRoot) {
  const canonicalWikiRoot = absolutePath(wikiRoot, "wikiRoot");
  assertSafePathSyntax(canonicalWikiRoot, "wikiRoot");
  const runtimeRoot = path.resolve(`${canonicalWikiRoot}.selfopenwiki`);
  assertSafePathSyntax(runtimeRoot, "runtimeRoot");
  if (
    runtimeRoot === canonicalWikiRoot ||
    runtimeRoot.startsWith(`${canonicalWikiRoot}${path.sep}`)
  ) {
    throw new Error("invalid storage config: runtimeRoot must be a sibling");
  }
  if (path.dirname(runtimeRoot) !== path.dirname(canonicalWikiRoot)) {
    throw new Error(
      "invalid storage config: Wiki and runtime roots must share a parent",
    );
  }
  return { wikiRoot: canonicalWikiRoot, runtimeRoot };
}

function assertConfig(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid storage config: expected an object");
  }
  const keys = Object.keys(value);
  if (
    keys.length !== CONFIG_KEYS.size ||
    keys.some((key) => !CONFIG_KEYS.has(key))
  ) {
    throw new Error("invalid storage config: unexpected fields");
  }
  if (value.schemaVersion !== STORAGE_CONFIG_SCHEMA_VERSION) {
    throw new Error("invalid storage config: unsupported schemaVersion");
  }
  if (!Number.isSafeInteger(value.generation) || value.generation < 1) {
    throw new Error("invalid storage config: generation");
  }
  const layout = deriveWikiLayout(value.wikiRoot);
  if (value.runtimeRoot !== layout.runtimeRoot) {
    throw new Error(
      "invalid storage config: runtimeRoot does not match wikiRoot",
    );
  }
  return {
    schemaVersion: STORAGE_CONFIG_SCHEMA_VERSION,
    generation: value.generation,
    ...layout,
  };
}

export async function readStorageConfig({
  configPath = defaultConfigPath(),
} = {}) {
  const bytes = await readFile(configPath, "utf8");
  const keyMatches = [...bytes.matchAll(/"((?:\\.|[^"\\])*)"\s*:/gu)].map(
    (match) => JSON.parse(`"${match[1]}"`),
  );
  if (new Set(keyMatches).size !== keyMatches.length) {
    throw new Error("invalid storage config: duplicate fields");
  }
  let value;
  try {
    value = JSON.parse(bytes);
  } catch {
    throw new Error("invalid storage config: malformed JSON");
  }
  const config = assertConfig(value);
  await validateWikiLayout(config);
  return config;
}

export async function writeStorageConfig({
  configPath = defaultConfigPath(),
  wikiRoot,
} = {}) {
  const canonicalConfigPath = absolutePath(
    path.resolve(configPath),
    "configPath",
  );
  const layout = deriveWikiLayout(wikiRoot);
  await mkdir(path.dirname(canonicalConfigPath), { recursive: true });
  const lockPath = `${canonicalConfigPath}.lock`;
  let lockHandle;
  let tempPath;
  try {
    try {
      lockHandle = await open(lockPath, "wx");
    } catch (error) {
      if (error?.code === "EEXIST")
        throw new Error("storage config busy: lock is held");
      throw error;
    }
    await validateWikiLayout(layout);
    let current;
    try {
      current = await readStorageConfig({ configPath: canonicalConfigPath });
      await assertNoActiveTransaction(current.runtimeRoot);
      await assertNoActiveTransaction(layout.runtimeRoot);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    const generation = current ? current.generation + 1 : 1;
    const config = assertConfig({
      schemaVersion: STORAGE_CONFIG_SCHEMA_VERSION,
      generation,
      ...layout,
    });
    const serialized = `${JSON.stringify(config, null, 2)}\n`;
    tempPath = `${canonicalConfigPath}.${process.pid}.${Date.now()}.tmp`;
    const tempHandle = await open(tempPath, "wx");
    try {
      await tempHandle.writeFile(serialized, "utf8");
      await tempHandle.sync();
    } finally {
      await tempHandle.close();
    }
    if ((await readFile(tempPath, "utf8")) !== serialized) {
      throw new Error("invalid storage config: temporary bytes changed");
    }
    await rename(tempPath, canonicalConfigPath);
    tempPath = undefined;
    const verified = await readStorageConfig({
      configPath: canonicalConfigPath,
    });
    if (JSON.stringify(verified) !== JSON.stringify(config)) {
      throw new Error("invalid storage config: read-back mismatch");
    }
    return verified;
  } finally {
    if (tempPath) await rm(tempPath, { force: true });
    if (lockHandle) {
      await lockHandle.close();
      await rm(lockPath, { force: true });
    }
  }
}

export function resolveWikiPath(layout, relativePath) {
  if (!layout || typeof layout.wikiRoot !== "string") {
    throw new Error("invalid wiki path: missing layout");
  }
  if (
    typeof relativePath !== "string" ||
    relativePath.length === 0 ||
    path.isAbsolute(relativePath)
  ) {
    throw new Error("invalid wiki path");
  }
  const normalized = relativePath.replaceAll("\\", "/");
  const segments = normalized.split("/");
  if (
    segments.some(
      (segment) => segment.length === 0 || segment === "." || segment === "..",
    ) ||
    segments.some(
      (segment) =>
        segment.toLowerCase() === ".git" ||
        segment.toLowerCase() === ".selfopenwiki",
    ) ||
    !normalized.toLowerCase().endsWith(".md")
  ) {
    throw new Error(
      "invalid wiki path: only Markdown files inside the Wiki root are allowed",
    );
  }
  assertSafePathSyntax(normalized, "wiki path");
  const resolved = path.resolve(layout.wikiRoot, ...segments);
  const relative = path.relative(path.resolve(layout.wikiRoot), resolved);
  if (
    !relative ||
    relative.startsWith(`..${path.sep}`) ||
    relative === ".." ||
    path.isAbsolute(relative)
  ) {
    throw new Error("invalid wiki path");
  }
  let cursor = layout.wikiRoot;
  for (const segment of relative.split(path.sep)) {
    cursor = path.join(cursor, segment);
    try {
      if (lstatSync(cursor).isSymbolicLink())
        throw new Error("invalid wiki path: link component");
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      break;
    }
  }
  return resolved;
}
