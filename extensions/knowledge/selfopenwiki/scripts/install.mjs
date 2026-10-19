import { lstat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { runSetup } from "./setup.mjs";
import { writeStorageConfig } from "./storage-config.mjs";

const HELP_TEXT = `SelfOpenWiki install (Windows)

Usage:
  Install.bat --wiki-root <absolute-path> --confirm-data-safety
  Install.bat --wiki-root <absolute-path> --confirm-data-safety --confirm-git-authorization
  Install.bat --help

The Agent must obtain the user's Wiki-root, data-safety, and (for Git roots)
write/commit authorization before invoking this command. Install never migrates,
commits, pushes, or changes the selected Wiki repository.
`;

class InstallError extends Error {
  constructor(message) {
    super(message);
    this.name = "InstallError";
  }
}

export function parseInstallArgs(argv) {
  const options = {
    help: false,
    wikiRoot: undefined,
    confirmDataSafety: false,
    confirmGitAuthorization: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--help") {
      if (argv.length !== 1) {
        throw new InstallError("--help cannot be combined with other options.");
      }
      return { ...options, help: true };
    }
    if (flag === "--wiki-root") {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) {
        throw new InstallError("--wiki-root requires a value.");
      }
      if (options.wikiRoot !== undefined) {
        throw new InstallError("--wiki-root may be provided only once.");
      }
      options.wikiRoot = value;
      index += 1;
      continue;
    }
    if (flag === "--confirm-data-safety") {
      if (options.confirmDataSafety) {
        throw new InstallError(
          "--confirm-data-safety may be provided only once.",
        );
      }
      options.confirmDataSafety = true;
      continue;
    }
    if (flag === "--confirm-git-authorization") {
      if (options.confirmGitAuthorization) {
        throw new InstallError(
          "--confirm-git-authorization may be provided only once.",
        );
      }
      options.confirmGitAuthorization = true;
      continue;
    }
    throw new InstallError(`Unknown install option: ${flag}`);
  }
  if (!options.wikiRoot) {
    throw new InstallError(
      "--wiki-root is required; the Agent must ask the user for the Wiki directory.",
    );
  }
  return options;
}

async function inspectWikiRoot(wikiRoot) {
  if (!path.isAbsolute(wikiRoot)) {
    throw new InstallError("--wiki-root must be an absolute path.");
  }
  const resolved = path.resolve(wikiRoot);
  if (resolved !== wikiRoot) {
    throw new InstallError(
      "--wiki-root must use its canonical absolute spelling.",
    );
  }
  let rootStats;
  try {
    rootStats = await lstat(resolved);
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new InstallError(
        "--wiki-root must already exist as a non-link directory; no directory is created automatically.",
      );
    }
    throw error;
  }
  if (!rootStats.isDirectory() || rootStats.isSymbolicLink()) {
    throw new InstallError(
      "--wiki-root must already exist as a non-link directory; no directory is created automatically.",
    );
  }
  let isGit = false;
  try {
    const gitStats = await lstat(path.join(resolved, ".git"));
    isGit = gitStats.isDirectory() || gitStats.isFile();
    if (gitStats.isSymbolicLink()) {
      throw new InstallError("the Wiki .git entry must not be a link.");
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  return { wikiRoot: resolved, isGit };
}

const productionDependencies = Object.freeze({
  runSetup: (args) => runSetup(args),
  writeStorageConfig,
  writeStdout: (text) => process.stdout.write(text),
  writeStderr: (text) => process.stderr.write(text),
});

export async function runInstall(argv, dependencies = productionDependencies) {
  try {
    const options = parseInstallArgs(argv);
    if (options.help) {
      dependencies.writeStdout(HELP_TEXT);
      return 0;
    }
    const target = await inspectWikiRoot(options.wikiRoot);
    if (!options.confirmDataSafety) {
      throw new InstallError(
        "Install blocked: the Agent must obtain --confirm-data-safety after explaining Wiki read/write and backup risks.",
      );
    }
    if (target.isGit && !options.confirmGitAuthorization) {
      throw new InstallError(
        "Install blocked: this Wiki is a Git repository; the Agent must obtain --confirm-git-authorization.",
      );
    }
    const setupExitCode = await dependencies.runSetup(["--with-mcp"]);
    if (setupExitCode !== 0) {
      throw new InstallError(
        `SelfOpenWiki setup failed with exit code ${setupExitCode}.`,
      );
    }
    await dependencies.writeStorageConfig({ wikiRoot: target.wikiRoot });
    dependencies.writeStdout(
      `SelfOpenWiki installed for Wiki root: ${target.wikiRoot}\n`,
    );
    dependencies.writeStdout(
      "No Wiki migration, commit, or push was performed.\n",
    );
    return 0;
  } catch (error) {
    const message =
      error instanceof InstallError
        ? error.message
        : "Unexpected installation failure.";
    dependencies.writeStderr(`SelfOpenWiki install error: ${message}\n`);
    return 2;
  }
}

const isDirectExecution =
  process.argv[1] !== undefined &&
  pathToFileURL(path.resolve(process.argv[1])).href ===
    pathToFileURL(fileURLToPath(import.meta.url)).href;

if (isDirectExecution) {
  process.exitCode = await runInstall(process.argv.slice(2));
}
