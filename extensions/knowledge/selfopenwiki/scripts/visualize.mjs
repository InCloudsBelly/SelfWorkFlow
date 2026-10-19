#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { lstat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { readStorageConfig } from "./storage-config.mjs";

export const VISUALIZER_PNPM_VERSION = "10.33.2";
export const DEFAULT_VISUALIZER_PORT = 3000;
export const VISUALIZER_RELATIVE_ROOT = path.join(
  "visualizer",
  "zxh_wiki_viewer",
);

const HELP_TEXT = `SelfOpenWiki visualization (Windows)

Usage:
  Visualize.bat
  Visualize.bat --production
  Visualize.bat --wiki-root <absolute-path>
  Visualize.bat --port <1-65535>
  Visualize.bat --help

The command reads the configured Wiki root and starts the pinned
zxh_wiki_viewer submodule on loopback. The default mode is Next.js development;
--production starts the previously built production server.
`;

class VisualizeError extends Error {
  constructor(message) {
    super(message);
    this.name = "VisualizeError";
  }
}

function parsePort(value) {
  if (!/^\d+$/u.test(value ?? "")) {
    throw new VisualizeError("--port must be an integer between 1 and 65535.");
  }
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new VisualizeError("--port must be an integer between 1 and 65535.");
  }
  return port;
}

export function parseVisualizeArgs(argv) {
  const options = {
    help: false,
    production: false,
    port: DEFAULT_VISUALIZER_PORT,
    wikiRoot: null,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--help") {
      if (argv.length !== 1) {
        throw new VisualizeError("--help cannot be combined with other options.");
      }
      return { ...options, help: true };
    }
    if (flag === "--production") {
      if (options.production) {
        throw new VisualizeError("--production may be provided only once.");
      }
      options.production = true;
      continue;
    }
    if (flag === "--wiki-root") {
      if (options.wikiRoot !== null) {
        throw new VisualizeError("--wiki-root may be provided only once.");
      }
      const value = argv[index + 1];
      if (value === undefined) {
        throw new VisualizeError("--wiki-root requires a value.");
      }
      if (!path.isAbsolute(value)) {
        throw new VisualizeError("--wiki-root must be an absolute path.");
      }
      options.wikiRoot = path.resolve(value);
      index += 1;
      continue;
    }
    if (flag === "--port") {
      const value = argv[index + 1];
      if (value === undefined) {
        throw new VisualizeError("--port requires a value.");
      }
      options.port = parsePort(value);
      index += 1;
      continue;
    }
    throw new VisualizeError(`Unknown visualization option: ${flag}`);
  }
  return options;
}

async function validateWikiRoot(wikiRoot) {
  if (typeof wikiRoot !== "string" || !path.isAbsolute(wikiRoot)) {
    throw new VisualizeError("Wiki root must be an absolute path.");
  }
  const resolved = path.resolve(wikiRoot);
  try {
    const stats = await lstat(resolved);
    if (!stats.isDirectory() || stats.isSymbolicLink()) {
      throw new VisualizeError(
        "Wiki root must be an existing non-link directory.",
      );
    }
  } catch (error) {
    if (error instanceof VisualizeError) throw error;
    if (error?.code === "ENOENT") {
      throw new VisualizeError("Wiki root does not exist.");
    }
    throw new VisualizeError("Wiki root could not be validated.");
  }
  return resolved;
}

export function createVisualizeProcessSpec({
  repositoryRoot,
  wikiRoot,
  production,
  port,
  platform = process.platform,
  environment = process.env,
}) {
  const visualizerRoot = path.join(repositoryRoot, VISUALIZER_RELATIVE_ROOT);
  const pnpmArgs = [
    `pnpm@${VISUALIZER_PNPM_VERSION}`,
    production ? "start" : "dev",
    "--hostname",
    "127.0.0.1",
    "--port",
    String(port),
  ];
  const command =
    platform === "win32" ? "C:\\Windows\\System32\\cmd.exe" : "corepack";
  const args =
    platform === "win32"
      ? ["/d", "/s", "/c", "corepack.cmd", ...pnpmArgs]
      : pnpmArgs;
  return {
    command,
    args,
    cwd: visualizerRoot,
    env: { ...environment, SELFOPENWIKI_WIKI_ROOT: wikiRoot },
    url: `http://127.0.0.1:${port}/wiki/local`,
  };
}

function spawnVisualizer(spec) {
  return new Promise((resolve, reject) => {
    const child = spawn(spec.command, spec.args, {
      cwd: spec.cwd,
      env: spec.env,
      shell: false,
      windowsHide: false,
      stdio: "inherit",
    });
    child.once("error", reject);
    child.once("close", (exitCode) => resolve(exitCode ?? 1));
  });
}

const productionDependencies = Object.freeze({
  environment: process.env,
  existsSync,
  readStorageConfig,
  spawnVisualizer,
  validateWikiRoot,
  writeStdout: (text) => process.stdout.write(text),
  writeStderr: (text) => process.stderr.write(text),
});

export async function runVisualize(argv, dependencies = productionDependencies) {
  try {
    const options = parseVisualizeArgs(argv);
    if (options.help) {
      dependencies.writeStdout(HELP_TEXT);
      return 0;
    }

    const configuredWikiRoot =
      options.wikiRoot ?? (await dependencies.readStorageConfig()).wikiRoot;
    const wikiRoot = await dependencies.validateWikiRoot(configuredWikiRoot);
    const repositoryRoot = path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      "..",
    );
    const spec = createVisualizeProcessSpec({
      repositoryRoot,
      wikiRoot,
      production: options.production,
      port: options.port,
      environment: dependencies.environment,
    });
    if (!dependencies.existsSync(path.join(spec.cwd, "package.json"))) {
      throw new VisualizeError(
        `The zxh_wiki_viewer submodule is not initialized: ${spec.cwd}`,
      );
    }
    dependencies.writeStdout(
      `Starting zxh_wiki_viewer at ${spec.url} for Wiki root ${wikiRoot}\n`,
    );
    return await dependencies.spawnVisualizer(spec);
  } catch (error) {
    const message =
      error instanceof VisualizeError
        ? error.message
        : error?.code === "ENOENT"
          ? "Storage is not configured. Run Install.bat or configure:storage first."
          : "Unexpected visualization startup failure.";
    dependencies.writeStderr(`SelfOpenWiki visualization error: ${message}\n`);
    return 2;
  }
}

const isDirectExecution =
  process.argv[1] !== undefined &&
  pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;

if (isDirectExecution) {
  process.exitCode = await runVisualize(process.argv.slice(2));
}
