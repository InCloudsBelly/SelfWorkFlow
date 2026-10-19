import { execFile } from "node:child_process";
import { chmod, lstat, mkdir, realpath } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { snapshotPersonalWiki } from "./personal-wiki-snapshot.js";
import type {
  PersonalRootBinding,
  PersonalRootResolver,
} from "./personal-wiki-lifecycle.js";

const execFileAsync = promisify(execFile);

export class PersonalWikiRootError extends Error {
  constructor(
    readonly code: "personal_root_invalid",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "PersonalWikiRootError";
  }
}

export type PersonalWikiRootOptions = {
  repositoryRoot?: string;
  runGit?(wikiRoot: string): Promise<string>;
};

export class PersonalWikiRootResolver implements PersonalRootResolver {
  private readonly options: PersonalWikiRootOptions;

  constructor(options: PersonalWikiRootOptions = {}) {
    this.options = options;
  }

  async resolve(wikiRoot: string): Promise<PersonalRootBinding> {
    return resolvePersonalWikiRoot(wikiRoot, this.options);
  }
}

export async function resolvePersonalWikiRoot(
  wikiRoot: string,
  options: PersonalWikiRootOptions = {},
): Promise<PersonalRootBinding> {
  if (!path.isAbsolute(wikiRoot)) {
    throw invalidRoot("The personal Wiki root must be an absolute path.");
  }
  const canonicalRoot = await canonicalDirectory(wikiRoot);
  const gitRoot = await (options.runGit ?? readGitRoot)(canonicalRoot).catch(
    (error: unknown) => {
      throw invalidRoot(
        "The personal Wiki root is not a readable Git repository.",
        error,
      );
    },
  );
  const canonicalGitRoot = await canonicalDirectory(gitRoot.trim()).catch(
    (error: unknown) => {
      throw invalidRoot(
        "The personal Wiki Git root could not be verified.",
        error,
      );
    },
  );
  if (!samePath(canonicalRoot, canonicalGitRoot)) {
    throw invalidRoot(
      "The personal Wiki path must be the canonical root of its independent Git repository.",
    );
  }
  if (options.repositoryRoot !== undefined) {
    const canonicalOwnerRoot = await canonicalDirectory(options.repositoryRoot);
    if (pathsOverlap(canonicalRoot, canonicalOwnerRoot)) {
      throw invalidRoot(
        "The personal Wiki must not overlap the SelfOpenWiki repository.",
      );
    }
  }
  const runtimeRoot = `${canonicalRoot}.selfopenwiki`;
  let wikiRevision: string;
  let markdownWikiRevision: string;
  try {
    const snapshot = await snapshotPersonalWiki(canonicalRoot);
    markdownWikiRevision = snapshot.markdownRootHash;
    wikiRevision = snapshot.rootHash;
  } catch (error) {
    throw invalidRoot(
      "The personal Wiki root must contain readable Markdown and valid personal Claim sidecars.",
      error,
    );
  }
  await prepareRuntimeRoot(runtimeRoot);
  return {
    runtimeRoot,
    markdownWikiRevision,
    wikiRevision,
    wikiRoot: canonicalRoot,
  };
}

async function prepareRuntimeRoot(runtimeRoot: string): Promise<void> {
  const existing = await lstat(runtimeRoot).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (existing === null) {
    await mkdir(runtimeRoot, { mode: 0o700, recursive: false });
  }
  const current = await lstat(runtimeRoot).catch((error: unknown) => {
    throw invalidRoot(
      "The personal Wiki runtime sibling is missing or unreadable.",
      error,
    );
  });
  if (!current.isDirectory() || current.isSymbolicLink()) {
    throw invalidRoot(
      "The personal Wiki runtime sibling must be a private regular directory.",
    );
  }
  const canonical = await realpath(runtimeRoot).catch((error: unknown) => {
    throw invalidRoot(
      "The personal Wiki runtime sibling could not be canonicalized.",
      error,
    );
  });
  if (!samePath(runtimeRoot, canonical)) {
    throw invalidRoot(
      "The personal Wiki runtime sibling cannot be a redirected path.",
    );
  }
  await chmod(runtimeRoot, 0o700).catch((error: unknown) => {
    throw invalidRoot(
      "The personal Wiki runtime sibling could not be secured.",
      error,
    );
  });
}

async function readGitRoot(wikiRoot: string): Promise<string> {
  const result = await execFileAsync(
    "git",
    ["-C", wikiRoot, "rev-parse", "--show-toplevel"],
    { encoding: "utf8", env: sanitizedGitEnvironment() },
  );
  return result.stdout;
}

function sanitizedGitEnvironment(): NodeJS.ProcessEnv {
  const environment = { ...process.env };
  for (const key of [
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
  ]) {
    delete environment[key];
  }
  const nullDevice = process.platform === "win32" ? "NUL" : "/dev/null";
  environment.GIT_CONFIG_COUNT = "0";
  environment.GIT_CONFIG_GLOBAL = nullDevice;
  environment.GIT_CONFIG_NOSYSTEM = "1";
  environment.GIT_CONFIG_SYSTEM = nullDevice;
  environment.GIT_OPTIONAL_LOCKS = "0";
  environment.GIT_TERMINAL_PROMPT = "0";
  return environment;
}

async function canonicalDirectory(value: string): Promise<string> {
  if (!path.isAbsolute(value)) {
    throw invalidRoot("The personal Wiki Git root must be absolute.");
  }
  const stat = await lstat(value).catch((error: unknown) => {
    throw invalidRoot(
      "The personal Wiki root is missing or unreadable.",
      error,
    );
  });
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw invalidRoot(
      "The personal Wiki root must be a regular non-link directory.",
    );
  }
  return realpath(value).catch((error: unknown) => {
    throw invalidRoot(
      "The personal Wiki root could not be canonicalized.",
      error,
    );
  });
}

function samePath(left: string, right: string): boolean {
  const normalize = (value: string) =>
    process.platform === "win32" ? value.toLowerCase() : value;
  return normalize(path.resolve(left)) === normalize(path.resolve(right));
}

function pathsOverlap(left: string, right: string): boolean {
  return isSameOrDescendant(left, right) || isSameOrDescendant(right, left);
}

function isSameOrDescendant(parent: string, candidate: string): boolean {
  const relative = path.relative(path.resolve(parent), path.resolve(candidate));
  return (
    relative === "" ||
    (relative !== ".." &&
      !relative.startsWith(`..${path.sep}`) &&
      !path.isAbsolute(relative))
  );
}

function invalidRoot(message: string, cause?: unknown): PersonalWikiRootError {
  return new PersonalWikiRootError("personal_root_invalid", message, {
    cause,
  });
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}
