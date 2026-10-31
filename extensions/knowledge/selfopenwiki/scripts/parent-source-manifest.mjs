#!/usr/bin/env node
import { createHash } from "node:crypto";
import { execFile, execFileSync } from "node:child_process";
import { lstatSync, readFileSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const DOMAIN = "selfopenwiki-parent-source-manifest-v1\0";
const COMMIT = /^[0-9a-f]{40}$/u;
const ALLOWED_ROOTS = [
  ".gitignore",
  ".gitmodules",
  "AGENTS.md",
  "Install.bat",
  "LICENSE",
  "README.md",
  "WIKI_LAYOUT.md",
  "adapter.yaml",
  "tool-contract.json",
  "source-import.json",
  "templates/",
  "Setup.bat",
  "Update-Upstream.bat",
  "Visualize.bat",
  "docs/",
  "global.json",
  "package.json",
  "patches/openwiki/",
  "scripts/",
  "self-openwiki/",
  "test/",
  "upstream/openwiki",
  "visualizer/",
];
const LAYERS = ["head", "index", "worktree"];
const DERIVED_PATHS = new Set([
  "self-openwiki/config/bootstrap-source-manifest.json",
  "self-openwiki/config/personal-openwiki-compatibility.json",
]);

// Runtime verification follows the module bytes that execute. Git's three-layer
// manifest below remains available for provenance, but staging is not deployment.
export function computeModuleSourceManifestSync(repositoryRoot) {
  const root = resolve(repositoryRoot);
  const index = readIndex(root);
  const head = readHead(root);
  const gitlinkPaths = new Set(
    [...head, ...index].flatMap(([name, records]) =>
      (Array.isArray(records) ? records : [records]).some(
        (record) => record.mode === "160000",
      )
        ? [name]
        : [],
    ),
  );
  const records = [];
  const paths = [
    ...new Set([
      ...readWorktreePaths(root, gitlinkPaths),
      ...[...head.keys()].filter(
        (name) =>
          ![...gitlinkPaths].some((gitlink) => name.startsWith(`${gitlink}/`)),
      ),
      ...gitlinkPaths,
    ]),
  ].filter((name) => !DERIVED_PATHS.has(name));
  paths.sort((left, right) => Buffer.from(left).compare(Buffer.from(right)));
  for (const sourcePath of paths) {
    const isGitlink = gitlinkPaths.has(sourcePath);
    const record = readWorktreeRecord(
      root,
      sourcePath,
      isGitlink ? "160000" : null,
    );
    if (record.kind === "absent") continue;
    const { layer, stage, worktreeDirty, ...content } = record;
    if (record.kind === "gitlink") {
      const nestedRoot = resolve(root, sourcePath);
      const nestedPaths = [
        ...new Set([
          ...git(nestedRoot, [
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            ".",
          ]),
          ...git(nestedRoot, ["ls-tree", "-r", "-z", "HEAD", "--", "."]).map(
            (entry) => {
              const tab = entry.indexOf("\t");
              if (tab < 0)
                throw new Error("The nested HEAD tree entry is invalid.");
              return entry.slice(tab + 1);
            },
          ),
        ]),
      ];
      nestedPaths.sort((left, right) =>
        Buffer.from(left).compare(Buffer.from(right)),
      );
      const nested = nestedPaths
        .map((name) => readWorktreeRecord(nestedRoot, name, null))
        .filter((entry) => entry.kind !== "absent");
      content.byteHash = sha256(Buffer.from(canonicalJson(nested)));
    }
    records.push(content);
  }
  const manifest = {
    version: 1,
    scope: "selfopenwiki-module-content",
    records,
  };
  return {
    hash: sha256(
      Buffer.from(`selfopenwiki-module-content-v1\0${canonicalJson(manifest)}`),
    ),
    manifest,
  };
}

// Read the same bytes as the synchronous provenance implementation. Independent
// Git observations run concurrently; no filesystem metadata or result is cached.
export async function computeModuleSourceManifest(repositoryRoot) {
  const root = resolve(repositoryRoot);
  const runGit = createAsyncGitRunner();
  const [indexEntries, headEntries, worktreeEntries] = await Promise.all([
    runGit(root, ["ls-files", "-s", "-z", "--", "."]),
    runGit(root, ["ls-tree", "-r", "-z", "HEAD", "--", "."]),
    runGit(root, [
      "ls-files",
      "--cached",
      "--others",
      "--exclude-standard",
      "-z",
      "--",
      ".",
    ]),
  ]);
  const index = readIndex(root, indexEntries);
  const head = readHead(root, headEntries);
  const gitlinkPaths = new Set(
    [...head, ...index].flatMap(([name, records]) =>
      (Array.isArray(records) ? records : [records]).some(
        (record) => record.mode === "160000",
      )
        ? [name]
        : [],
    ),
  );
  const paths = [
    ...new Set([
      ...readWorktreePaths(root, gitlinkPaths, worktreeEntries),
      ...[...head.keys()].filter(
        (name) =>
          ![...gitlinkPaths].some((gitlink) => name.startsWith(`${gitlink}/`)),
      ),
      ...gitlinkPaths,
    ]),
  ].filter((name) => !DERIVED_PATHS.has(name));
  paths.sort((left, right) => Buffer.from(left).compare(Buffer.from(right)));
  const records = (
    await Promise.all(
      paths.map(async (sourcePath) => {
        let observation;
        let nestedEntries;
        if (gitlinkPaths.has(sourcePath)) {
          const nestedRoot = resolve(root, sourcePath);
          const stat = lstatSync(nestedRoot, { throwIfNoEntry: false });
          if (stat === undefined) return null;
          assertNoReparsePath(root, nestedRoot);
          if (stat.isSymbolicLink() || !stat.isDirectory())
            throw new Error("The module gitlink must be a real directory.");
          const [commit, tracked, nestedHead] = await Promise.all([
            runGit(nestedRoot, ["rev-parse", "HEAD"]),
            runGit(nestedRoot, [
              "ls-files",
              "--cached",
              "--others",
              "--exclude-standard",
              "-z",
              "--",
              ".",
            ]),
            runGit(nestedRoot, ["ls-tree", "-r", "-z", "HEAD", "--", "."]),
          ]);
          // Dirty/staging status is not part of the module-content identity.
          observation = { commit: commit.join("\0").trim(), dirty: false };
          nestedEntries = [
            ...new Set([
              ...tracked,
              ...nestedHead.map((entry) => {
                const tab = entry.indexOf("\t");
                if (tab < 0)
                  throw new Error("The nested HEAD tree entry is invalid.");
                return entry.slice(tab + 1);
              }),
            ]),
          ];
        }
        const record = readWorktreeRecord(
          root,
          sourcePath,
          gitlinkPaths.has(sourcePath) ? "160000" : null,
          observation,
        );
        if (record.kind === "absent") return null;
        const { layer, stage, worktreeDirty, ...content } = record;
        if (nestedEntries !== undefined) {
          nestedEntries.sort((left, right) =>
            Buffer.from(left).compare(Buffer.from(right)),
          );
          const nested = nestedEntries
            .map((name) =>
              readWorktreeRecord(resolve(root, sourcePath), name, null),
            )
            .filter((entry) => entry.kind !== "absent");
          content.byteHash = sha256(Buffer.from(canonicalJson(nested)));
        }
        return content;
      }),
    )
  ).filter((record) => record !== null);
  const manifest = {
    version: 1,
    scope: "selfopenwiki-module-content",
    records,
  };
  return {
    hash: sha256(
      Buffer.from(`selfopenwiki-module-content-v1\0${canonicalJson(manifest)}`),
    ),
    manifest,
  };
}

export function computeParentSourceManifestSync(repositoryRoot) {
  const root = resolve(repositoryRoot);
  const head = readHead(root);
  const index = readIndex(root);
  hydrateBlobRecords(root, [...head.values(), ...index.values()].flat());
  const worktreePaths = readWorktreePaths(root);
  const paths = new Set([...head.keys(), ...index.keys(), ...worktreePaths]);
  const sortedPaths = [...paths]
    .filter((sourcePath) => !DERIVED_PATHS.has(sourcePath))
    .sort((left, right) =>
      Buffer.from(left, "utf8").compare(Buffer.from(right, "utf8")),
    );
  const records = [];
  for (const sourcePath of sortedPaths) {
    const headRecord = head.get(sourcePath);
    records.push(headRecord ?? absentRecord(sourcePath, "head"));
    const indexRecords = index.get(sourcePath);
    if (indexRecords === undefined) {
      records.push(absentRecord(sourcePath, "index"));
    } else {
      records.push(...indexRecords);
    }
    const indexMode = indexRecords?.some((record) => record.mode === "160000")
      ? "160000"
      : (indexRecords?.[0]?.mode ?? null);
    records.push(readWorktreeRecord(root, sourcePath, indexMode));
  }
  const manifest = { version: 1, records };
  return { hash: parentSourceManifestHash(manifest), manifest };
}

export function parentSourceManifestHash(manifest) {
  if (
    manifest === null ||
    typeof manifest !== "object" ||
    manifest.version !== 1 ||
    !Array.isArray(manifest.records)
  ) {
    throw new Error("The parent source manifest is invalid.");
  }
  const bytes = Buffer.from(`${DOMAIN}${canonicalJson(manifest)}`, "utf8");
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function readHead(root, entries = git(root, ["ls-tree", "-r", "-z", "HEAD", "--", "."])) {
  const result = new Map();
  for (const entry of entries) {
    const tab = entry.indexOf("\t");
    if (tab < 0) throw new Error("The parent HEAD tree entry is invalid.");
    const [mode, type, object] = entry.slice(0, tab).split(" ");
    const sourcePath = entry
      .slice(tab + 1)
      .replaceAll("\\", "/")
      .normalize("NFC");
    if (isOperationalPath(sourcePath)) continue;
    validateAllowedPath(sourcePath);
    validateAllowedPath(sourcePath);
    if (result.has(sourcePath))
      throw new Error("Duplicate parent source path.");
    result.set(
      sourcePath,
      gitRecord(sourcePath, "head", 0, mode, type, object),
    );
  }
  return result;
}

function readIndex(root, entries = git(root, ["ls-files", "-s", "-z", "--", "."])) {
  const result = new Map();
  for (const entry of entries) {
    const tab = entry.indexOf("\t");
    if (tab < 0) throw new Error("The parent index entry is invalid.");
    const [mode, object, stageText] = entry.slice(0, tab).split(" ");
    const stage = Number(stageText);
    const sourcePath = entry
      .slice(tab + 1)
      .replaceAll("\\", "/")
      .normalize("NFC");
    if (isOperationalPath(sourcePath)) continue;
    validateAllowedPath(sourcePath);
    validateAllowedPath(sourcePath);
    if (![0, 1, 2, 3].includes(stage) || !COMMIT.test(object)) {
      throw new Error("The parent index entry is invalid.");
    }
    const values = result.get(sourcePath) ?? [];
    if (values.some((value) => value.stage === stage)) {
      throw new Error("Duplicate parent index stage.");
    }
    values.push(
      gitRecord(
        sourcePath,
        "index",
        stage,
        mode,
        mode === "160000" ? "commit" : "blob",
        object,
      ),
    );
    values.sort((left, right) => left.stage - right.stage);
    result.set(sourcePath, values);
  }
  return result;
}

function readWorktreePaths(root, gitlinkPaths = new Set(), entries) {
  return new Set(
    (entries ?? git(root, [
      "ls-files",
      "--cached",
      "--others",
      "--exclude-standard",
      "-z",
      "--",
      ".",
    ]))
      .map((value) => {
        const sourcePath = value.replaceAll("\\", "/").normalize("NFC");
        if (isOperationalPath(sourcePath)) return null;
        if (
          [...gitlinkPaths].some((gitlink) =>
            sourcePath.startsWith(`${gitlink}/`),
          )
        )
          return null;
        validateAllowedPath(sourcePath);
        return sourcePath;
      })
      .filter((value) => value !== null),
  );
}

function isOperationalPath(sourcePath) {
  return (
    sourcePath === ".work" ||
    sourcePath.startsWith(".work/") ||
    sourcePath === ".codegraph" ||
    sourcePath.startsWith(".codegraph/") ||
    sourcePath === ".selfopenwiki-upstream-update.lock" ||
    sourcePath === ".selfopenwiki-upstream-update-journal.json" ||
    sourcePath.split("/").some((segment) => segment.endsWith(".selfopenwiki"))
  );
}

function readWorktreeRecord(root, sourcePath, indexMode, observation) {
  const absolute = resolve(root, ...sourcePath.split("/"));
  if (!isWithin(root, absolute))
    throw new Error("The parent source path escapes the repository.");
  let stats;
  try {
    stats = lstatSync(absolute);
  } catch (error) {
    if (error?.code === "ENOENT") return absentRecord(sourcePath, "worktree");
    throw error;
  }
  assertNoReparsePath(root, absolute);
  if (indexMode === "160000") {
    if (stats.isSymbolicLink() || !stats.isDirectory()) {
      throw new Error(
        `The parent gitlink is not a real directory: ${sourcePath}.`,
      );
    }
  } else if (stats.isSymbolicLink() || stats.isDirectory()) {
    throw new Error(
      `The parent source path is not a regular file: ${sourcePath}.`,
    );
  }
  if (indexMode === "160000") {
    const nestedRoot = absolute;
    const commit = observation?.commit ?? gitText(nestedRoot, ["rev-parse", "HEAD"]);
    if (!COMMIT.test(commit))
      throw new Error("The nested Submodule commit is invalid.");
    const dirty = observation?.dirty ?? (gitText(nestedRoot, [
      "status",
      "--porcelain",
      "--untracked-files=all",
    ]) !== "");
    return {
      byteHash: null,
      byteLength: 0,
      gitlinkCommit: commit,
      kind: "gitlink",
      layer: "worktree",
      mode: "160000",
      path: sourcePath,
      stage: 0,
      worktreeDirty: dirty,
    };
  }
  const bytes = readFileSync(absolute);
  const mode = stats.mode & 0o111 ? "100755" : "100644";
  return {
    byteHash: sha256(bytes),
    byteLength: bytes.byteLength,
    gitlinkCommit: null,
    kind: "blob",
    layer: "worktree",
    mode,
    path: sourcePath,
    stage: 0,
    worktreeDirty: false,
  };
}

function gitRecord(sourcePath, layer, stage, mode, type, object) {
  if (!mode || !["100644", "100755", "160000"].includes(mode)) {
    throw new Error(`The parent source mode is unsupported: ${sourcePath}.`);
  }
  if (mode === "160000") {
    if (type !== "commit" || !COMMIT.test(object)) {
      throw new Error(`The parent gitlink entry is invalid: ${sourcePath}.`);
    }
    return {
      byteHash: null,
      byteLength: 0,
      gitlinkCommit: object,
      kind: "gitlink",
      layer,
      mode,
      path: sourcePath,
      stage,
      worktreeDirty: false,
    };
  }
  if (type !== "blob")
    throw new Error(`The parent source entry is not a blob: ${sourcePath}.`);
  return {
    byteHash: null,
    byteLength: 0,
    gitlinkCommit: null,
    kind: "blob",
    layer,
    mode,
    path: sourcePath,
    stage,
    worktreeDirty: false,
    gitObject: object,
  };
}

function hydrateBlobRecords(root, records) {
  const blobRecords = records.filter((record) => record.kind === "blob");
  const objects = [...new Set(blobRecords.map((record) => record.gitObject))];
  const blobs = readGitBlobs(root, objects);
  for (const record of blobRecords) {
    const object = record.gitObject;
    const bytes = blobs.get(object);
    if (bytes === undefined)
      throw new Error(`The parent blob is missing: ${object}.`);
    record.byteHash = sha256(bytes);
    record.byteLength = bytes.byteLength;
    delete record.gitObject;
  }
}

function readGitBlobs(root, objects) {
  if (objects.length === 0) return new Map();
  const output = execFileSync(
    "git",
    ["-c", "core.quotepath=false", "cat-file", "--batch"],
    {
      cwd: root,
      env: gitEnvironment(),
      encoding: null,
      input: `${objects.join("\n")}\n`,
      maxBuffer: 256 * 1024 * 1024,
      windowsHide: true,
    },
  );
  const blobs = new Map();
  let offset = 0;
  for (const requested of objects) {
    const headerEnd = output.indexOf(0x0a, offset);
    if (headerEnd < 0)
      throw new Error("The parent blob batch response is incomplete.");
    const [object, type, sizeText] = output
      .subarray(offset, headerEnd)
      .toString("utf8")
      .split(" ");
    if (object !== requested || type !== "blob") {
      throw new Error(
        `The parent blob batch response is invalid: ${requested}.`,
      );
    }
    const size = Number(sizeText);
    if (!Number.isSafeInteger(size) || size < 0) {
      throw new Error(`The parent blob size is invalid: ${requested}.`);
    }
    const bodyStart = headerEnd + 1;
    const bodyEnd = bodyStart + size;
    if (bodyEnd >= output.length || output[bodyEnd] !== 0x0a) {
      throw new Error(
        `The parent blob batch body is incomplete: ${requested}.`,
      );
    }
    blobs.set(requested, output.subarray(bodyStart, bodyEnd));
    offset = bodyEnd + 1;
  }
  return blobs;
}

function absentRecord(sourcePath, layer) {
  return {
    byteHash: null,
    byteLength: 0,
    gitlinkCommit: null,
    kind: "absent",
    layer,
    mode: null,
    path: sourcePath,
    stage: 0,
    worktreeDirty: false,
  };
}

function assertNoReparsePath(root, target) {
  let current = resolve(root);
  const suffix = relative(current, target);
  for (const segment of suffix.split(sep).filter(Boolean)) {
    current = resolve(current, segment);
    const stats = lstatSync(current);
    if (stats.isSymbolicLink())
      throw new Error(`The parent source path contains a link: ${target}.`);
  }
}

function validateAllowedPath(sourcePath) {
  if (
    sourcePath === "" ||
    sourcePath.startsWith("/") ||
    sourcePath.includes("\\") ||
    sourcePath
      .split("/")
      .some(
        (segment) => segment === "" || segment === "." || segment === "..",
      ) ||
    !ALLOWED_ROOTS.some((prefix) =>
      prefix.endsWith("/")
        ? sourcePath.startsWith(prefix)
        : sourcePath === prefix,
    )
  ) {
    throw new Error(
      `The parent source path is outside the allowed manifest: ${sourcePath}.`,
    );
  }
}

function normalizeGitPath(value) {
  const normalized = value.replaceAll("\\", "/");
  validateAllowedPath(normalized);
  return normalized.normalize("NFC");
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value)
      .sort((left, right) => Buffer.from(left).compare(Buffer.from(right)))
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256(bytes) {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function isWithin(root, candidate) {
  const suffix = relative(resolve(root), resolve(candidate));
  return (
    suffix === "" ||
    (!suffix.startsWith(`..${sep}`) &&
      suffix !== ".." &&
      !suffix.includes(`..${sep}`))
  );
}

function git(root, args) {
  const bytes = execFileSync("git", ["-c", "core.quotepath=false", ...args], {
    cwd: root,
    env: gitEnvironment(),
    encoding: null,
    maxBuffer: 256 * 1024 * 1024,
    windowsHide: true,
  });
  return bytes.toString("utf8").split("\0").filter(Boolean);
}

function gitAsync(root, args) {
  return new Promise((resolveResult, reject) => {
    execFile(
      "git",
      ["-c", "core.quotepath=false", ...args],
      {
        cwd: root,
        env: gitEnvironment(),
        encoding: "utf8",
        maxBuffer: 256 * 1024 * 1024,
        windowsHide: true,
      },
      (error, stdout) =>
        error
          ? reject(error)
          : resolveResult(stdout.split("\0").filter(Boolean)),
    );
  });
}

function createAsyncGitRunner() {
  let active = 0;
  const waiting = [];
  return async (root, args) => {
    if (active >= 4) await new Promise((resume) => waiting.push(resume));
    else active++;
    try {
      return await gitAsync(root, args);
    } finally {
      const next = waiting.shift();
      if (next) next();
      else active--;
    }
  };
}

function gitBytes(root, args) {
  return execFileSync("git", ["-c", "core.quotepath=false", ...args], {
    cwd: root,
    env: gitEnvironment(),
    encoding: null,
    maxBuffer: 256 * 1024 * 1024,
    windowsHide: true,
  });
}

function gitText(root, args) {
  return gitBytes(root, args).toString("utf8").trim();
}

function gitEnvironment() {
  const environment = { ...process.env };
  const nullDevice = process.platform === "win32" ? "NUL" : "/dev/null";
  for (const key of [
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
  ])
    delete environment[key];
  Object.assign(environment, {
    GIT_CONFIG_COUNT: "0",
    GIT_CONFIG_GLOBAL: nullDevice,
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_OPTIONAL_LOCKS: "0",
    GIT_TERMINAL_PROMPT: "0",
  });
  return environment;
}

function isMainModule() {
  return (
    process.argv[1] !== undefined &&
    pathToFileURL(resolve(process.argv[1])).href === import.meta.url
  );
}

if (isMainModule()) {
  try {
    const root = process.argv[2];
    const moduleContent = process.argv[3] === "--module-content";
    if (
      root === undefined ||
      (process.argv.length !== 3 &&
        !(moduleContent && process.argv.length === 4))
    )
      throw new Error(
        "Usage: parent-source-manifest.mjs <repository-root> [--module-content]",
      );
    process.stdout.write(
      `${JSON.stringify(moduleContent ? computeModuleSourceManifestSync(root) : computeParentSourceManifestSync(root))}\n`,
    );
  } catch (error) {
    process.stderr.write(
      `${error instanceof Error ? error.message : String(error)}\n`,
    );
    process.exitCode = 1;
  }
}
