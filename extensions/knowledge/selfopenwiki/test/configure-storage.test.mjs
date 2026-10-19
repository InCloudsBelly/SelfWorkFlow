import assert from "node:assert/strict";
import { mkdtemp, readFile, realpath, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { test } from "node:test";

const scriptPath = path.resolve("scripts/configure-storage.mjs");

function run(args, cwd, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [scriptPath, ...args], {
      cwd,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.once("error", reject);
    child.once("close", (code) => resolve({ code, stdout, stderr }));
  });
}

test("configure-storage persists an explicitly selected Wiki root", async () => {
  const root = await realpath(
    await mkdtemp(path.join(os.tmpdir(), "selfopenwiki-config-cli-")),
  );
  try {
    const configPath = path.join(root, "config.json");
    const wikiRoot = path.join(root, "wiki");
    await (await import("node:fs/promises")).mkdir(wikiRoot);
    const result = await run(["--wiki-root", wikiRoot], root, {
      ...process.env,
      LOCALAPPDATA: root,
    });
    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stdout, /wikiRoot/u);
    const config = JSON.parse(
      await readFile(path.join(root, "SelfOpenWiki", "config.json"), "utf8"),
    );
    assert.equal(config.wikiRoot, path.resolve(wikiRoot));
    assert.equal(config.runtimeRoot, path.resolve(`${wikiRoot}.selfopenwiki`));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("configure-storage rejects a missing Wiki-root argument without writing", async () => {
  const root = await mkdtemp(
    path.join(os.tmpdir(), "selfopenwiki-config-cli-"),
  );
  try {
    const result = await run([], root, { ...process.env, LOCALAPPDATA: root });
    assert.equal(result.code, 2);
    assert.match(result.stderr, /--wiki-root/u);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
