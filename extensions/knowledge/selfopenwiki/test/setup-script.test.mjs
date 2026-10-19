import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";

import {
  SETUP_PNPM_VERSION,
  createSetupPlan,
  parseSetupArgs,
  runSetup,
  spawnProcess,
} from "../scripts/setup.mjs";

const repositoryRoot = "D:\\SelfOpenWiki";

test("setup accepts only help and with-mcp options", () => {
  assert.deepEqual(parseSetupArgs([]), { help: false, withMcp: false });
  assert.deepEqual(parseSetupArgs(["--help"]), {
    help: true,
    withMcp: false,
  });
  assert.deepEqual(parseSetupArgs(["--with-mcp"]), {
    help: false,
    withMcp: true,
  });
  assert.throws(() => parseSetupArgs(["--unknown"]), /Unknown setup option/);
  assert.throws(
    () => parseSetupArgs(["--help", "--with-mcp"]),
    /one setup option/,
  );
});

test("setup plans materialization and base OpenWiki build without storage mutation", () => {
  const plan = createSetupPlan({ repositoryRoot, withMcp: false });
  assert.deepEqual(
    plan.map(({ command, args, cwd, label }) => ({
      command,
      args,
      cwd,
      label,
    })),
    [
      {
        command: process.execPath,
        args: ["scripts/materialize-openwiki.mjs"],
        cwd: repositoryRoot,
        label: "materialize official OpenWiki",
      },
      {
        command: "corepack",
        args: [`pnpm@${SETUP_PNPM_VERSION}`, "install", "--frozen-lockfile"],
        cwd: path.join(repositoryRoot, ".work", "openwiki"),
        label: "install official OpenWiki dependencies",
      },
      {
        command: "corepack",
        args: [`pnpm@${SETUP_PNPM_VERSION}`, "--config.enable-pre-post-scripts=false", "run", "build"],
        cwd: path.join(repositoryRoot, ".work", "openwiki"),
        label: "build official OpenWiki",
      },
      {
        command: "corepack",
        args: [`pnpm@${SETUP_PNPM_VERSION}`, "install", "--frozen-lockfile"],
        cwd: path.join(repositoryRoot, "visualizer", "zxh_wiki_viewer"),
        label: "install zxh_wiki_viewer dependencies",
      },
      {
        command: "corepack",
        args: [`pnpm@${SETUP_PNPM_VERSION}`, "run", "build"],
        cwd: path.join(repositoryRoot, "visualizer", "zxh_wiki_viewer"),
        label: "build zxh_wiki_viewer visualizer",
      },
    ],
  );
});

test("with-mcp appends MCP install, helper build, and capability verification", () => {
  const plan = createSetupPlan({ repositoryRoot, withMcp: true });
  assert.deepEqual(
    plan
      .slice(-5)
      .map(({ command, args, cwd, label }) => ({ command, args, cwd, label })),
    [
      {
        command: "corepack",
        args: [
          `pnpm@${SETUP_PNPM_VERSION}`,
          "install",
          "--frozen-lockfile",
          "--ignore-scripts",
        ],
        cwd: path.join(repositoryRoot, "self-openwiki", "mcp-server"),
        label: "install SelfOpenWiki MCP dependencies",
      },
      {
        command: "corepack",
        args: [`pnpm@${SETUP_PNPM_VERSION}`, "run", "build"],
        cwd: path.join(repositoryRoot, "self-openwiki", "mcp-server"),
        label: "build SelfOpenWiki MCP",
      },
      {
        command: "corepack",
        args: [`pnpm@${SETUP_PNPM_VERSION}`, "run", "build:win32-helper"],
        cwd: path.join(repositoryRoot, "self-openwiki", "mcp-server"),
        label: "build SelfOpenWiki Win32 helper",
      },
      {
        command: process.execPath,
        args: ["scripts/refresh-compatibility.mjs"],
        cwd: repositoryRoot,
        label: "refresh module compatibility binding",
      },
      {
        command: process.execPath,
        args: ["self-openwiki/scripts/verify-capabilities.mts"],
        cwd: repositoryRoot,
        label: "verify SelfOpenWiki capabilities",
      },
    ],
  );
});

test("setup ignores an inherited COMSPEC override", async () => {
  const calls = [];
  const dependencies = {
    platform: "win32",
    nodeVersion: "22.0.0",
    repositoryRoot,
    environment: {
      COMSPEC: "C:\\attacker\\cmd.exe",
      PATH: "C:\\Windows\\System32",
    },
    spawnProcess: async (...args) => {
      calls.push(args);
      return { exitCode: 0, stdout: "", stderr: "" };
    },
    writeStdout: () => {},
    writeStderr: () => {},
  };
  await runSetup([], dependencies);
  const corepackCall = calls.find(([, args]) => args.includes("corepack.cmd"));
  assert.equal(corepackCall?.[0], "C:\\Windows\\System32\\cmd.exe");
});

test("production capture rejects oversized child output without retaining it", async () => {
  await assert.rejects(
    spawnProcess(
      process.execPath,
      [
        "-e",
        "process.stdout.write('x'.repeat(70 * 1024)); setTimeout(() => {}, 1000)",
      ],
      {
        cwd: repositoryRoot,
        env: process.env,
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
      },
    ),
    /65536-byte capture limit/,
  );
});
