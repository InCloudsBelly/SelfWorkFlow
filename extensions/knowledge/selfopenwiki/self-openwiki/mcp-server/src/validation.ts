import { lstat, readFile, readdir, unlink } from "node:fs/promises";
import path from "node:path";
import { TextDecoder } from "node:util";
import { parseDocument } from "yaml";
import {
  C7SnapshotError,
  snapshotMarkdownTree,
  type MarkdownTreeSnapshot,
} from "./snapshot.js";

export type WikiValidationCheck = {
  readonly id: string;
  readonly message?: string;
  readonly status: "failed" | "passed";
};

export type WikiValidationResult = {
  readonly checks: readonly WikiValidationCheck[];
  readonly passed: boolean;
  readonly snapshot?: MarkdownTreeSnapshot;
};

type WikiDiff = {
  readonly added: ReadonlySet<string>;
  readonly changed: ReadonlySet<string>;
  readonly changedBytes: number;
};

type ParsedPage = {
  readonly anchors: ReadonlySet<string>;
  readonly content: string;
  readonly frontmatter: Record<string, unknown>;
};

const utf8Decoder = new TextDecoder("utf-8", { fatal: true });
const utf16LeDecoder = new TextDecoder("utf-16le", { fatal: true });
const utf16BeDecoder = new TextDecoder("utf-16be", { fatal: true });

export async function stripOpenWikiRuntimeMetadata(
  candidateRoot: string,
): Promise<void> {
  if (!path.isAbsolute(candidateRoot)) {
    throw new Error("candidate Wiki root must be absolute");
  }
  await stripOpenWikiRuntimeMetadataWith(candidateRoot);
}

export async function normalizeWikiCandidate(
  candidateRoot: string,
): Promise<void> {
  if (!path.isAbsolute(candidateRoot)) {
    throw new Error("candidate Wiki root must be absolute");
  }
  const rootStat = await lstat(candidateRoot);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    throw new Error("candidate Wiki root must be a regular non-link directory");
  }
  await stripOpenWikiRuntimeMetadataWith(candidateRoot);
}

async function stripOpenWikiRuntimeMetadataWith(
  candidateRoot: string,
): Promise<void> {
  const metadataPath = path.join(candidateRoot, ".last-update.json");
  let stat;
  try {
    stat = await lstat(metadataPath);
  } catch (error) {
    if (isMissing(error)) return;
    throw error;
  }
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 1024 * 1024) {
    throw new Error("OpenWiki run metadata is not a bounded regular file");
  }
  await unlink(metadataPath);
}

export async function validateWikiCandidate(input: {
  allowedChangedPaths?: readonly string[];
  beforeSnapshot?: MarkdownTreeSnapshot;
  candidateRoot: string;
  forbiddenContentHashes?: readonly string[];
  forbiddenSourceRoot?: string;
  maxAddedPages?: number;
  maxChangedBytes?: number;
  maxFileBytes?: number;
  maxPages?: number;
  maxTotalBytes?: number;
  requireProvisionalMarker?: boolean;
}): Promise<WikiValidationResult> {
  const checks: WikiValidationCheck[] = [];
  let snapshot: MarkdownTreeSnapshot;
  try {
    snapshot = await snapshotMarkdownTree(input.candidateRoot);
    checks.push(passed("markdown_tree"));
  } catch (error) {
    checks.push(
      failed(
        "markdown_tree",
        error instanceof C7SnapshotError
          ? "The candidate Wiki is not a regular Markdown-only tree."
          : "The candidate Wiki could not be inspected.",
      ),
    );
    return { checks, passed: false };
  }

  const maxPages = input.maxPages ?? 500;
  const maxFileBytes = input.maxFileBytes ?? 2 * 1024 * 1024;
  const maxTotalBytes = input.maxTotalBytes ?? 50 * 1024 * 1024;
  const totalBytes = snapshot.files.reduce((sum, file) => sum + file.size, 0);
  checks.push(
    snapshot.files.length <= maxPages &&
      snapshot.files.every((file) => file.size <= maxFileBytes) &&
      totalBytes <= maxTotalBytes
      ? passed("size_limits")
      : failed(
          "size_limits",
          "The candidate Wiki exceeds its page or byte limits.",
        ),
  );

  const paths = new Set(snapshot.files.map((file) => file.relativePath));
  checks.push(
    paths.has("quickstart.md")
      ? passed("quickstart")
      : failed("quickstart", "The candidate Wiki must contain quickstart.md."),
  );

  const diff = computeDiff(input.beforeSnapshot, snapshot);
  const maxAddedPages = input.maxAddedPages ?? 100;
  checks.push(
    diff.added.size <= maxAddedPages
      ? passed("page_expansion")
      : failed(
          "page_expansion",
          "The candidate Wiki adds more pages than the confirmed limit.",
        ),
  );
  checks.push(
    diff.changedBytes <= (input.maxChangedBytes ?? 20 * 1024 * 1024)
      ? passed("changed_bytes")
      : failed(
          "changed_bytes",
          "The candidate Wiki changes more bytes than the transaction limit.",
        ),
  );

  const allowedChangedPaths = parseAllowedPaths(input.allowedChangedPaths);
  checks.push(
    allowedChangedPaths === undefined ||
      (input.beforeSnapshot !== undefined &&
        [...diff.changed].every((candidate) =>
          allowedChangedPaths.has(candidate),
        ))
      ? passed("change_scope")
      : failed(
          "change_scope",
          "The candidate Wiki changes a page outside the autonomous repair scope.",
        ),
  );

  const forbidden = new Set(input.forbiddenContentHashes ?? []);
  let sourceCopyValid = !snapshot.files.some((file) =>
    forbidden.has(file.hash),
  );

  const pageContents = new Map<string, string>();
  const parsedPages = new Map<string, ParsedPage>();
  let okfValid = true;
  let mermaidValid = true;
  for (const file of snapshot.files) {
    const content = await readFile(
      path.join(input.candidateRoot, ...file.relativePath.split("/")),
      "utf8",
    );
    pageContents.set(file.relativePath, content);
    const parsed = parsePage(content);
    if (parsed === undefined) {
      okfValid = false;
    } else {
      parsedPages.set(file.relativePath, parsed);
    }
    if (!hasValidMermaid(content)) mermaidValid = false;
  }

  if (sourceCopyValid && input.forbiddenSourceRoot !== undefined) {
    try {
      const sourceTexts = await collectSourceTexts(input.forbiddenSourceRoot);
      const normalizedPages = [...pageContents.values()].map(normalizeText);
      sourceCopyValid = sourceTexts.every((source) => {
        const normalizedSource = normalizeText(source).trim();
        return (
          normalizedSource.length === 0 ||
          !normalizedPages.some((candidate) =>
            candidate.includes(normalizedSource),
          )
        );
      });
    } catch {
      sourceCopyValid = false;
    }
  }
  checks.push(
    sourceCopyValid
      ? passed("source_copy")
      : failed(
          "source_copy",
          "A candidate page contains a complete confirmed source file.",
        ),
  );

  let linksValid = true;
  for (const [relativePath, content] of pageContents) {
    if (!internalLinksResolve(relativePath, content, paths, parsedPages)) {
      linksValid = false;
    }
  }
  checks.push(
    okfValid
      ? passed("okf_frontmatter")
      : failed(
          "okf_frontmatter",
          "Every Wiki page must have bounded valid YAML front matter with a non-empty string type.",
        ),
  );
  checks.push(
    linksValid
      ? passed("internal_links")
      : failed(
          "internal_links",
          "At least one internal Markdown page or anchor link is broken.",
        ),
  );
  checks.push(
    navigationIsComplete(pageContents, paths)
      ? passed("navigation_index")
      : failed(
          "navigation_index",
          "Every Wiki page must be reachable from quickstart.md navigation.",
        ),
  );
  checks.push(
    mermaidValid
      ? passed("mermaid")
      : failed("mermaid", "At least one Mermaid block is malformed."),
  );

  const provisionalMarked = [...diff.changed].some(
    (relativePath) =>
      parsedPages.get(relativePath)?.frontmatter.status === "provisional",
  );
  checks.push(
    !input.requireProvisionalMarker || provisionalMarked
      ? passed("provisional_marker")
      : failed(
          "provisional_marker",
          "A provisional update must mark at least one changed page with front matter status: provisional.",
        ),
  );

  return {
    checks,
    passed: checks.every((check) => check.status === "passed"),
    snapshot,
  };
}

function computeDiff(
  before: MarkdownTreeSnapshot | undefined,
  after: MarkdownTreeSnapshot,
): WikiDiff {
  if (before === undefined) {
    return { added: new Set(), changed: new Set(), changedBytes: 0 };
  }
  const beforeByPath = new Map(
    before.files.map((file) => [file.relativePath, file]),
  );
  const afterByPath = new Map(
    after.files.map((file) => [file.relativePath, file]),
  );
  const added = new Set<string>();
  const changed = new Set<string>();
  let changedBytes = 0;
  for (const [relativePath, file] of beforeByPath) {
    const candidate = afterByPath.get(relativePath);
    if (candidate === undefined) {
      changed.add(relativePath);
      changedBytes += file.size;
    } else if (candidate.hash !== file.hash) {
      changed.add(relativePath);
      changedBytes += file.size + candidate.size;
    }
  }
  for (const [relativePath, file] of afterByPath) {
    if (!beforeByPath.has(relativePath)) {
      added.add(relativePath);
      changed.add(relativePath);
      changedBytes += file.size;
    }
  }
  return { added, changed, changedBytes };
}

function parseAllowedPaths(
  values: readonly string[] | undefined,
): ReadonlySet<string> | undefined {
  if (values === undefined) return undefined;
  const parsed = new Set<string>();
  for (const value of values) {
    const normalized = value.replace(/\\/gu, "/");
    if (
      path.posix.isAbsolute(normalized) ||
      path.posix.normalize(normalized) !== normalized ||
      !normalized.toLowerCase().endsWith(".md") ||
      normalized.split("/").some((segment) => segment === "..")
    ) {
      return new Set(["__invalid_scope__"]);
    }
    parsed.add(normalized);
  }
  return parsed;
}

function parsePage(content: string): ParsedPage | undefined {
  const normalized = normalizeText(content);
  if (!normalized.startsWith("---\n")) return undefined;
  const end = normalized.indexOf("\n---\n", 4);
  if (end < 0 || end > 16 * 1024) return undefined;
  try {
    const document = parseDocument(normalized.slice(4, end), {
      prettyErrors: false,
      strict: true,
      uniqueKeys: true,
    });
    if (document.errors.length > 0) return undefined;
    const value = document.toJS({ maxAliasCount: 0 }) as unknown;
    if (
      typeof value !== "object" ||
      value === null ||
      Array.isArray(value) ||
      !("type" in value) ||
      typeof (value as { type?: unknown }).type !== "string" ||
      (value as { type: string }).type.trim() === ""
    ) {
      return undefined;
    }
    return {
      anchors: collectHeadingAnchors(normalized.slice(end + 5)),
      content,
      frontmatter: value as Record<string, unknown>,
    };
  } catch {
    return undefined;
  }
}

function collectHeadingAnchors(content: string): ReadonlySet<string> {
  const anchors = new Set<string>();
  const occurrences = new Map<string, number>();
  let fenced = false;
  for (const line of content.split("\n")) {
    if (/^\s*```/u.test(line)) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    const heading = /^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/u.exec(line)?.[1];
    if (heading === undefined) continue;
    const base = headingSlug(heading);
    if (base === "") continue;
    const count = occurrences.get(base) ?? 0;
    occurrences.set(base, count + 1);
    anchors.add(count === 0 ? base : `${base}-${count}`);
  }
  for (const match of content.matchAll(
    /<a\s+(?:[^>]*?\s)?(?:id|name)=["']([^"']+)["'][^>]*>/giu,
  )) {
    if (match[1] !== undefined) anchors.add(match[1]);
  }
  return anchors;
}

function headingSlug(value: string): string {
  return value
    .replace(/<[^>]*>/gu, "")
    .replace(/[`*_~]/gu, "")
    .trim()
    .toLocaleLowerCase("en-US")
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/gu, "-")
    .replace(/-+/gu, "-");
}

function hasValidMermaid(content: string): boolean {
  const openings = content.match(/```mermaid(?:\r?\n|$)/gu)?.length ?? 0;
  const blocks = [...content.matchAll(/```mermaid\s*\r?\n([\s\S]*?)```/gu)];
  if (openings !== blocks.length) return false;
  const allowed =
    /^(?:architecture-beta|block-beta|classDiagram|erDiagram|flowchart\b|gantt\b|gitGraph\b|graph\b|journey\b|mindmap\b|pie\b|quadrantChart\b|requirementDiagram\b|sankey-beta\b|sequenceDiagram\b|stateDiagram(?:-v2)?\b|timeline\b|xychart-beta\b)/u;
  return blocks.every((block) => {
    const body = block[1] ?? "";
    const firstLine = body
      .split(/\r?\n/u)
      .map((line) => line.trim())
      .find((line) => line !== "" && !line.startsWith("%%"));
    return (
      firstLine !== undefined &&
      allowed.test(firstLine) &&
      delimitersBalanced(
        body
          .split(/\r?\n/u)
          .filter((line) => !line.trimStart().startsWith("%%"))
          .join("\n"),
      )
    );
  });
}

function delimitersBalanced(value: string): boolean {
  const pairs = new Map([
    [")", "("],
    ["]", "["],
    ["}", "{"],
  ]);
  const stack: string[] = [];
  let quote: '"' | "'" | undefined;
  let escaped = false;
  for (const character of value) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (character === "\\" && quote !== undefined) {
      escaped = true;
      continue;
    }
    if (quote !== undefined) {
      if (character === quote) quote = undefined;
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
    } else if (character === "(" || character === "[" || character === "{") {
      stack.push(character);
    } else if (pairs.has(character) && stack.pop() !== pairs.get(character)) {
      return false;
    }
  }
  return quote === undefined && stack.length === 0;
}

function internalLinksResolve(
  pagePath: string,
  content: string,
  availablePaths: ReadonlySet<string>,
  parsedPages: ReadonlyMap<string, ParsedPage>,
): boolean {
  for (const rawTarget of markdownTargets(content)) {
    const target = resolveInternalTarget(pagePath, rawTarget);
    if (target === null) continue;
    if (target === undefined || !availablePaths.has(target.relativePath)) {
      return false;
    }
    if (
      target.anchor !== undefined &&
      !parsedPages.get(target.relativePath)?.anchors.has(target.anchor)
    ) {
      return false;
    }
  }
  return true;
}

function navigationIsComplete(
  pageContents: ReadonlyMap<string, string>,
  availablePaths: ReadonlySet<string>,
): boolean {
  if (!availablePaths.has("quickstart.md")) return false;
  const visited = new Set(["quickstart.md"]);
  const queue = ["quickstart.md"];
  while (queue.length > 0) {
    const pagePath = queue.shift()!;
    for (const rawTarget of markdownTargets(pageContents.get(pagePath) ?? "")) {
      const target = resolveInternalTarget(pagePath, rawTarget);
      if (
        target !== null &&
        target !== undefined &&
        availablePaths.has(target.relativePath) &&
        !visited.has(target.relativePath)
      ) {
        visited.add(target.relativePath);
        queue.push(target.relativePath);
      }
    }
  }
  return [...availablePaths].every((candidate) => visited.has(candidate));
}

function markdownTargets(content: string): string[] {
  return [...content.matchAll(/(?<!!)\[[^\]]*\]\(([^)]+)\)/gu)].map(
    (match) => match[1]?.trim() ?? "",
  );
}

function resolveInternalTarget(
  pagePath: string,
  rawValue: string,
): { anchor?: string; relativePath: string } | null | undefined {
  let value = rawValue;
  if (value.startsWith("<") && value.endsWith(">")) {
    value = value.slice(1, -1);
  }
  if (value === "" || /^[A-Za-z][A-Za-z0-9+.-]*:/u.test(value)) {
    return null;
  }
  const hashIndex = value.indexOf("#");
  const rawPath = (hashIndex < 0 ? value : value.slice(0, hashIndex)).split(
    "?",
    1,
  )[0]!;
  const rawAnchor = hashIndex < 0 ? undefined : value.slice(hashIndex + 1);
  try {
    const decodedPath = decodeURIComponent(rawPath);
    const anchor =
      rawAnchor === undefined || rawAnchor === ""
        ? undefined
        : decodeURIComponent(rawAnchor);
    const relativePath =
      decodedPath === ""
        ? pagePath
        : path.posix.normalize(
            path.posix.join(path.posix.dirname(pagePath), decodedPath),
          );
    if (
      relativePath === ".." ||
      relativePath.startsWith("../") ||
      path.posix.isAbsolute(relativePath)
    ) {
      return undefined;
    }
    return { ...(anchor ? { anchor } : {}), relativePath };
  } catch {
    return undefined;
  }
}

async function collectSourceTexts(root: string): Promise<string[]> {
  if (!path.isAbsolute(root)) throw new Error("source root must be absolute");
  const rootStat = await lstat(root);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    throw new Error("source root must be a regular directory");
  }
  const texts: string[] = [];
  await collectSourceTextsIn(root, texts);
  return texts;
}

async function collectSourceTextsIn(
  directory: string,
  texts: string[],
): Promise<void> {
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const candidate = path.join(directory, entry.name);
    const stat = await lstat(candidate);
    if (entry.isSymbolicLink() || stat.isSymbolicLink()) {
      throw new Error("source snapshot contains a link");
    }
    if (entry.isDirectory() && stat.isDirectory()) {
      await collectSourceTextsIn(candidate, texts);
    } else if (entry.isFile() && stat.isFile()) {
      texts.push(decodeText(await readFile(candidate)));
    } else {
      throw new Error("source snapshot contains a special file");
    }
  }
}

function decodeText(bytes: Uint8Array): string {
  if (bytes[0] === 0xff && bytes[1] === 0xfe) {
    return utf16LeDecoder.decode(bytes.subarray(2));
  }
  if (bytes[0] === 0xfe && bytes[1] === 0xff) {
    return utf16BeDecoder.decode(bytes.subarray(2));
  }
  return utf8Decoder.decode(
    bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf
      ? bytes.subarray(3)
      : bytes,
  );
}

function normalizeText(value: string): string {
  return value.replace(/^\uFEFF/u, "").replace(/\r\n?/gu, "\n");
}

function passed(id: string): WikiValidationCheck {
  return { id, status: "passed" };
}

function failed(id: string, message: string): WikiValidationCheck {
  return { id, message, status: "failed" };
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === "ENOENT"
  );
}
