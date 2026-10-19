import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { parseInstallArgs, runInstall } from "../scripts/install.mjs";

async function makeTempRoot() {
  return mkdtemp(path.join(os.tmpdir(), "selfopenwiki-install-"));
}

function fakeDependencies({
  repositoryRoot,
  setupCalls,
  storageCalls,
  output,
}) {
  return {
    repositoryRoot,
    runSetup: async (args) => {
      setupCalls.push(args);
      return 0;
    },
    writeStorageConfig: async (args) => {
      storageCalls.push(args);
      return { wikiRoot: args.wikiRoot };
    },
    writeStdout: (text) => output.stdout.push(text),
    writeStderr: (text) => output.stderr.push(text),
  };
}

test("install requires an explicit Wiki root and confirmation flags", () => {
  assert.throws(() => parseInstallArgs([]), /--wiki-root is required/);
  assert.deepEqual(
    parseInstallArgs([
      "--wiki-root",
      "D:\\wiki_zxh",
      "--confirm-data-safety",
      "--confirm-git-authorization",
    ]),
    {
      help: false,
      wikiRoot: "D:\\wiki_zxh",
      confirmDataSafety: true,
      confirmGitAuthorization: true,
    },
  );
});

test("install fails before setup when data-safety confirmation is missing", async () => {
  const root = await makeTempRoot();
  const setupCalls = [];
  const storageCalls = [];
  const output = { stdout: [], stderr: [] };
  try {
    const exitCode = await runInstall(
      ["--wiki-root", root],
      fakeDependencies({
        repositoryRoot: "D:\\SelfOpenWiki",
        setupCalls,
        storageCalls,
        output,
      }),
    );
    assert.equal(exitCode, 2);
    assert.match(output.stderr.join(""), /confirm-data-safety/);
    assert.deepEqual(setupCalls, []);
    assert.deepEqual(storageCalls, []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("install rejects a missing Wiki root before setup", async () => {
  const root = path.join(await makeTempRoot(), "missing");
  const setupCalls = [];
  const storageCalls = [];
  const output = { stdout: [], stderr: [] };
  const exitCode = await runInstall(
    ["--wiki-root", root, "--confirm-data-safety"],
    fakeDependencies({
      repositoryRoot: "D:\\SelfOpenWiki",
      setupCalls,
      storageCalls,
      output,
    }),
  );
  assert.equal(exitCode, 2);
  assert.match(output.stderr.join(""), /must already exist/);
  assert.deepEqual(setupCalls, []);
  assert.deepEqual(storageCalls, []);
});

test("install requires Git authorization before touching a Git Wiki", async () => {
  const root = await makeTempRoot();
  const setupCalls = [];
  const storageCalls = [];
  const output = { stdout: [], stderr: [] };
  const gitMarker = path.join(root, ".git");
  try {
    await mkdir(gitMarker);
    const before = await readFile(gitMarker, { encoding: "utf8" }).catch(
      () => "directory",
    );
    const exitCode = await runInstall(
      ["--wiki-root", root, "--confirm-data-safety"],
      fakeDependencies({
        repositoryRoot: "D:\\SelfOpenWiki",
        setupCalls,
        storageCalls,
        output,
      }),
    );
    assert.equal(exitCode, 2);
    assert.match(output.stderr.join(""), /confirm-git-authorization/);
    assert.deepEqual(setupCalls, []);
    assert.deepEqual(storageCalls, []);
    assert.equal(
      await readFile(gitMarker, { encoding: "utf8" }).catch(() => "directory"),
      before,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("install binds a plain Wiki directory after setup", async () => {
  const root = await makeTempRoot();
  const setupCalls = [];
  const storageCalls = [];
  const output = { stdout: [], stderr: [] };
  try {
    const exitCode = await runInstall(
      ["--wiki-root", root, "--confirm-data-safety"],
      fakeDependencies({
        repositoryRoot: "D:\\SelfOpenWiki",
        setupCalls,
        storageCalls,
        output,
      }),
    );
    assert.equal(exitCode, 0);
    assert.deepEqual(setupCalls, [["--with-mcp"]]);
    assert.deepEqual(storageCalls, [{ wikiRoot: root }]);
    assert.match(output.stdout.join(""), /installed for Wiki root/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("install binds a Git Wiki only after both confirmations", async () => {
  const root = await makeTempRoot();
  const setupCalls = [];
  const storageCalls = [];
  const output = { stdout: [], stderr: [] };
  try {
    await mkdir(path.join(root, ".git"));
    await writeFile(path.join(root, "README.md"), "private wiki\n");
    const before = await readFile(path.join(root, "README.md"), "utf8");
    const exitCode = await runInstall(
      [
        "--wiki-root",
        root,
        "--confirm-data-safety",
        "--confirm-git-authorization",
      ],
      fakeDependencies({
        repositoryRoot: "D:\\SelfOpenWiki",
        setupCalls,
        storageCalls,
        output,
      }),
    );
    assert.equal(exitCode, 0);
    assert.deepEqual(setupCalls, [["--with-mcp"]]);
    assert.deepEqual(storageCalls, [{ wikiRoot: root }]);
    assert.equal(await readFile(path.join(root, "README.md"), "utf8"), before);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
