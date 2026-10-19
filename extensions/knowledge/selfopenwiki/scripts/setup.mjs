import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const SETUP_PNPM_VERSION = "10.33.2";

const HELP_TEXT = `SelfOpenWiki setup (Windows)

Usage:
  Setup.bat
  Setup.bat --with-mcp
  Setup.bat --help

The default command materializes and builds the pinned official OpenWiki and
the pinned zxh_wiki_viewer visualizer.
--with-mcp additionally builds the SelfOpenWiki MCP and Win32 helper, then
runs the fail-closed capability verifier. Storage selection remains separate.
`;
const MAX_CAPTURE_BYTES = 64 * 1024;

class SetupError extends Error {
  constructor(message) {
    super(message);
    this.name = "SetupError";
  }
}

export function parseSetupArgs(argv) {
  if (argv.length === 0) return { help: false, withMcp: false };
  if (argv.length !== 1) {
    throw new SetupError("Only one setup option may be provided.");
  }
  if (argv[0] === "--help") return { help: true, withMcp: false };
  if (argv[0] === "--with-mcp") return { help: false, withMcp: true };
  throw new SetupError("Unknown setup option. Run Setup.bat --help for usage.");
}

function step({ command, args, cwd, label }) {
  return Object.freeze({ command, args: Object.freeze([...args]), cwd, label });
}

export function createSetupPlan({ repositoryRoot, withMcp }) {
  const generatedRoot = path.join(repositoryRoot, ".work", "openwiki");
  const visualizerRoot = path.join(
    repositoryRoot,
    "visualizer",
    "zxh_wiki_viewer",
  );
  const mcpRoot = path.join(repositoryRoot, "self-openwiki", "mcp-server");
  const plan = [
    step({
      command: process.execPath,
      args: ["scripts/materialize-openwiki.mjs"],
      cwd: repositoryRoot,
      label: "materialize official OpenWiki",
    }),
    step({
      command: "corepack",
      args: [`pnpm@${SETUP_PNPM_VERSION}`, "install", "--frozen-lockfile"],
      cwd: generatedRoot,
      label: "install official OpenWiki dependencies",
    }),
    step({
      command: "corepack",
      args: [`pnpm@${SETUP_PNPM_VERSION}`, "--config.enable-pre-post-scripts=false", "run", "build"],
      cwd: generatedRoot,
      label: "build official OpenWiki",
    }),
    step({
      command: "corepack",
      args: [`pnpm@${SETUP_PNPM_VERSION}`, "install", "--frozen-lockfile"],
      cwd: visualizerRoot,
      label: "install zxh_wiki_viewer dependencies",
    }),
    step({
      command: "corepack",
      args: [`pnpm@${SETUP_PNPM_VERSION}`, "run", "build"],
      cwd: visualizerRoot,
      label: "build zxh_wiki_viewer visualizer",
    }),
  ];
  if (withMcp) {
    plan.push(
      step({
        command: "corepack",
        args: [
          `pnpm@${SETUP_PNPM_VERSION}`,
          "install",
          "--frozen-lockfile",
          "--ignore-scripts",
        ],
        cwd: mcpRoot,
        label: "install SelfOpenWiki MCP dependencies",
      }),
      step({
        command: "corepack",
        args: [`pnpm@${SETUP_PNPM_VERSION}`, "run", "build"],
        cwd: mcpRoot,
        label: "build SelfOpenWiki MCP",
      }),
      step({
        command: "corepack",
        args: [`pnpm@${SETUP_PNPM_VERSION}`, "run", "build:win32-helper"],
        cwd: mcpRoot,
        label: "build SelfOpenWiki Win32 helper",
      }),
      step({
        command: process.execPath,
        args: ["scripts/refresh-compatibility.mjs"],
        cwd: repositoryRoot,
        label: "refresh module compatibility binding",
      }),
      step({
        command: process.execPath,
        args: ["self-openwiki/scripts/verify-capabilities.mts"],
        cwd: repositoryRoot,
        label: "verify SelfOpenWiki capabilities",
      }),
    );
  }
  return Object.freeze(plan);
}

export function spawnProcess(commandName, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(commandName, args, options);
    const stdout = [];
    const stderr = [];
    let capturedBytes = 0;
    let exceeded = false;
    let killed = false;
    const capture = (target, chunk) => {
      if (exceeded) return;
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      if (capturedBytes + bytes.length > MAX_CAPTURE_BYTES) {
        exceeded = true;
        if (!killed) {
          killed = true;
          child.kill();
        }
        return;
      }
      capturedBytes += bytes.length;
      target.push(bytes);
    };
    child.stdout?.on("data", (chunk) => capture(stdout, chunk));
    child.stderr?.on("data", (chunk) => capture(stderr, chunk));
    child.once("error", (error) => {
      if (!exceeded) reject(error);
    });
    child.once("close", (exitCode) => {
      if (exceeded) {
        reject(
          new SetupError(
            `Setup child output exceeded the ${MAX_CAPTURE_BYTES}-byte capture limit.`,
          ),
        );
        return;
      }
      resolve({
        exitCode: exitCode ?? 1,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
      });
    });
  });
}

const productionRepositoryRoot = path.dirname(
  path.dirname(fileURLToPath(import.meta.url)),
);
const productionDependencies = Object.freeze({
  platform: process.platform,
  nodeVersion: process.versions.node,
  repositoryRoot: productionRepositoryRoot,
  environment: process.env,
  spawnProcess,
  writeStdout: (text) => process.stdout.write(text),
  writeStderr: (text) => process.stderr.write(text),
});

function requireSupportedHost({ platform, nodeVersion }) {
  if (platform !== "win32") {
    throw new SetupError("Windows is required to run Setup.bat.");
  }
  const major = Number.parseInt(nodeVersion.split(".", 1)[0] ?? "", 10);
  if (!Number.isInteger(major) || major < 22) {
    throw new SetupError("Node.js 22 or newer is required.");
  }
}

function getComSpec(environment) {
  void environment;
  return "C:\\Windows\\System32\\cmd.exe";
}

function childInvocation(commandName, args, dependencies) {
  if (commandName === "corepack") {
    return {
      command: getComSpec(dependencies.environment),
      args: ["/d", "/s", "/c", "corepack.cmd", ...args],
    };
  }
  return { command: commandName, args };
}

async function runStep(planStep, dependencies) {
  const invocation = childInvocation(
    planStep.command,
    planStep.args,
    dependencies,
  );
  try {
    const result = await dependencies.spawnProcess(
      invocation.command,
      invocation.args,
      {
        cwd: planStep.cwd,
        env: { ...dependencies.environment, CI: "true" },
        shell: false,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    return result.exitCode;
  } catch {
    throw new SetupError(`Unable to start ${planStep.label}.`);
  }
}

export async function runSetup(argv, dependencies = productionDependencies) {
  const options = parseSetupArgs(argv);
  if (options.help) {
    dependencies.writeStdout(HELP_TEXT);
    return 0;
  }
  requireSupportedHost(dependencies);
  for (const planStep of createSetupPlan({
    repositoryRoot: dependencies.repositoryRoot,
    withMcp: options.withMcp,
  })) {
    const exitCode = await runStep(planStep, dependencies);
    if (exitCode !== 0) {
      dependencies.writeStderr(
        `SelfOpenWiki setup error: ${planStep.label} failed with exit code ${exitCode}.\n`,
      );
      return exitCode;
    }
  }
  dependencies.writeStdout(
    `OpenWiki CLI build: ${path.join(dependencies.repositoryRoot, ".work", "openwiki", "dist", "cli", "cli.js")}\n`,
  );
  dependencies.writeStdout(
    `Wiki visualizer build: ${path.join(dependencies.repositoryRoot, "visualizer", "zxh_wiki_viewer", ".next")}\n`,
  );
  if (options.withMcp) {
    dependencies.writeStdout(
      `SelfOpenWiki MCP entry: ${path.join(dependencies.repositoryRoot, "self-openwiki", "mcp-server", "dist", "index.js")}\n`,
    );
  }
  return 0;
}

const isDirectExecution =
  process.argv[1] !== undefined &&
  pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;

if (isDirectExecution) {
  runSetup(process.argv.slice(2)).then(
    (exitCode) => {
      process.exitCode = exitCode;
    },
    (error) => {
      const message =
        error instanceof SetupError
          ? error.message
          : "Unexpected setup failure.";
      process.stderr.write(`SelfOpenWiki setup error: ${message}\n`);
      process.exitCode = 1;
    },
  );
}
