import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  rmdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, extname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const upstreamPath = join(repositoryRoot, "upstream", "openwiki");
const visualizerPath = join(repositoryRoot, "visualizer", "zxh_wiki_viewer");
const frozenUpstreamCommit = "d1c7fc75a6a906da258cd94dbcb1602f98516480";
const officialUpstreamUrl = "https://github.com/langchain-ai/openwiki.git";
const personalVisualizerUrl =
  "https://github.com/InCloudsBelly/zxh_wiki_viewer.git";
const personalVisualizerBranch = "codex/selfopenwiki-local-source";

function requirePath(path, description) {
  assert.equal(existsSync(path), true, `missing ${description}: ${path}`);
}

function readJson(relativePath) {
  const path = join(repositoryRoot, relativePath);
  requirePath(path, relativePath);
  return JSON.parse(readFileSync(path, "utf8"));
}

function git(args, cwd = repositoryRoot) {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

function listPublicCandidates() {
  const output = execFileSync(
    "git",
    ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    { cwd: repositoryRoot, encoding: "utf8" },
  );
  return output.split("\0").filter(Boolean);
}

function isTextCandidate(relativePath) {
  const textNames = new Set([
    ".gitignore",
    ".gitmodules",
    ".gitkeep",
    "LICENSE",
  ]);
  const textExtensions = new Set([
    ".bat",
    ".cs",
    ".csproj",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".patch",
    ".ps1",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
  ]);
  return (
    textNames.has(basename(relativePath)) ||
    textExtensions.has(extname(relativePath).toLowerCase())
  );
}

function normalizePrivateBinding(value) {
  return value.replaceAll("\\", "/").toLowerCase();
}

function assertNoPrivateBindings(candidateRelativePaths) {
  const normalizedForbiddenLiterals = [
    ["D:", "\\wiki_", "zxh"].join(""),
    ["D:", "\\openwiki", "C7"].join(""),
    ["InCloudsBelly/", "wiki_", "zxh"].join(""),
    [
      "48fafb44",
      "32d126af",
      "72d55520",
      "567fa552",
      "0288c1d9",
      "c843ff1f",
      "3259410e",
      "72ebff23",
    ].join(""),
  ].map(normalizePrivateBinding);

  for (const relativePath of candidateRelativePaths) {
    const path = join(repositoryRoot, ...relativePath.split("/"));
    const stats = lstatSync(path);
    if (
      ["upstream/openwiki", "visualizer/zxh_wiki_viewer"].includes(
        relativePath.replace(/\/$/u, ""),
      )
    ) {
      assert.equal(
        stats.isDirectory(),
        true,
        "gitlink candidate must be a directory",
      );
      continue;
    }
    assert.equal(
      stats.isSymbolicLink(),
      false,
      `${relativePath} must not be a link`,
    );
    assert.equal(
      stats.isFile(),
      true,
      `${relativePath} must be a regular file`,
    );
    if (!isTextCandidate(relativePath)) {
      continue;
    }
    const normalizedContents = normalizePrivateBinding(
      readFileSync(path, "utf8"),
    );
    for (const literal of normalizedForbiddenLiterals) {
      assert.equal(
        normalizedContents.includes(literal),
        false,
        `private binding found in ${path}`,
      );
    }
  }
}

function assertGitIgnored(relativePath) {
  const result = spawnSync(
    "git",
    ["check-ignore", "--quiet", "--", relativePath],
    {
      cwd: repositoryRoot,
      encoding: "utf8",
    },
  );
  assert.equal(result.status, 0, `${relativePath} must remain Git-ignored`);
}

test("root package identifies the Windows SelfOpenWiki v0.1 toolchain", () => {
  const packageJson = readJson("package.json");
  assert.equal(packageJson.name, "self-openwiki");
  assert.equal(packageJson.version, "0.1.0");
  assert.equal(packageJson.private, true);
  assert.equal(packageJson.license, "MIT");
  assert.equal(packageJson.packageManager, "pnpm@10.33.2");
  assert.deepEqual(packageJson.os, ["win32"]);
  assert.equal(packageJson.engines?.node, ">=22");
  assert.equal(packageJson.engines?.pnpm, "10.33.2");
  assert.equal(packageJson.scripts?.test, "node --test test/*.test.mjs");
  assert.equal(packageJson.scripts?.visualize, "node scripts/visualize.mjs");

  const globalJson = readJson("global.json");
  assert.equal(globalJson.sdk?.version, "9.0.100");
  assert.equal(globalJson.sdk?.rollForward, "latestFeature");
  assert.equal(globalJson.sdk?.allowPrerelease, false);
});

test("OpenWiki production and personal visualizer submodules are configured", () => {
  const parentRoot = realpathSync.native(git(["rev-parse", "--show-toplevel"]));
  const prefix = git(["rev-parse", "--show-prefix"]);
  const gitmodulesPath = join(parentRoot, ".gitmodules");
  requirePath(gitmodulesPath, ".gitmodules");
  assert.equal(
    git([
      "config",
      "--file",
      gitmodulesPath,
      "--get",
      `submodule.${prefix}upstream/openwiki.path`,
    ]),
    `${prefix}upstream/openwiki`,
  );
  assert.equal(
    git([
      "config",
      "--file",
      gitmodulesPath,
      "--get",
      `submodule.${prefix}upstream/openwiki.url`,
    ]),
    officialUpstreamUrl,
  );
  assert.deepEqual(
    git(["config", "--file", gitmodulesPath, "--get-regexp", "^submodule\\."])
      .split(/\r?\n/u)
      .filter(row => row.startsWith(`submodule.${prefix}`))
      .sort(),
    [
      `submodule.${prefix}upstream/openwiki.path ${prefix}upstream/openwiki`,
      `submodule.${prefix}upstream/openwiki.url ${officialUpstreamUrl}`,
      `submodule.${prefix}visualizer/zxh_wiki_viewer.branch ${personalVisualizerBranch}`,
      `submodule.${prefix}visualizer/zxh_wiki_viewer.path ${prefix}visualizer/zxh_wiki_viewer`,
      `submodule.${prefix}visualizer/zxh_wiki_viewer.url ${personalVisualizerUrl}`,
    ],
  );

  requirePath(upstreamPath, "OpenWiki submodule checkout");
  const gitFile = join(upstreamPath, ".git");
  requirePath(gitFile, "OpenWiki submodule gitfile");
  assert.equal(
    lstatSync(gitFile).isFile(),
    true,
    "submodule .git must be a gitfile",
  );
  const gitFileMatch = /^gitdir: ([^\r\n]+)\r?\n?$/u.exec(
    readFileSync(gitFile, "utf8"),
  );
  assert.ok(
    gitFileMatch,
    "submodule gitfile must contain one gitdir directive",
  );
  const gitFileDirectory = realpathSync.native(
    resolve(dirname(gitFile), gitFileMatch[1]),
  );
  const expectedParentGitDirectory = realpathSync.native(
    join(parentRoot, ".git", "modules", prefix, "upstream", "openwiki"),
  );
  assert.equal(
    gitFileDirectory,
    expectedParentGitDirectory,
    "submodule gitfile must resolve to parent-owned metadata",
  );
  assert.equal(
    realpathSync.native(git(["rev-parse", "--git-dir"], upstreamPath)),
    expectedParentGitDirectory,
  );
  assert.equal(
    realpathSync.native(git(["rev-parse", "--git-common-dir"], upstreamPath)),
    expectedParentGitDirectory,
  );
  assert.equal(git(["rev-parse", "HEAD"], upstreamPath), frozenUpstreamCommit);
  assert.equal(
    git(["remote", "get-url", "origin"], upstreamPath),
    officialUpstreamUrl,
  );
  assert.equal(git(["status", "--porcelain"], upstreamPath), "");

  const symbolicHead = spawnSync("git", ["symbolic-ref", "-q", "HEAD"], {
    cwd: upstreamPath,
    encoding: "utf8",
  });
  assert.equal(symbolicHead.status, 1, "submodule HEAD must be detached");

  requirePath(visualizerPath, "personal visualizer submodule checkout");
  const visualizerGitFile = join(visualizerPath, ".git");
  requirePath(visualizerGitFile, "personal visualizer submodule gitfile");
  assert.equal(lstatSync(visualizerGitFile).isFile(), true);
  const visualizerGitFileMatch = /^gitdir: ([^\r\n]+)\r?\n?$/u.exec(
    readFileSync(visualizerGitFile, "utf8"),
  );
  assert.ok(visualizerGitFileMatch);
  assert.equal(
    realpathSync.native(
      resolve(dirname(visualizerGitFile), visualizerGitFileMatch[1]),
    ),
    realpathSync.native(
      join(parentRoot, ".git", "modules", prefix, "visualizer", "zxh_wiki_viewer"),
    ),
  );
  assert.equal(
    git(["remote", "get-url", "origin"], visualizerPath),
    personalVisualizerUrl,
  );
  assert.equal(git(["status", "--porcelain"], visualizerPath), "");

  const patchManifest = readJson("patches/openwiki/manifest.json");
  assert.equal(patchManifest.schemaVersion, 2);
  assert.equal(patchManifest.domain, "selfopenwiki:openwiki-patch-manifest:v2");
  assert.equal(patchManifest.upstream.commit, frozenUpstreamCommit);
  assert.deepEqual(patchManifest.patches, []);
});

test("public repository skeleton has the approved owner directories", () => {
  const expectedDirectories = [
    "patches/openwiki",
    "scripts",
    "self-openwiki/mcp-server",
    "self-openwiki/win32-helper",
    "self-openwiki/agent-skills/self-openwiki",
    "self-openwiki/config",
    "test",
    "visualizer/zxh_wiki_viewer",
  ];
  for (const relativePath of expectedDirectories) {
    const path = join(repositoryRoot, ...relativePath.split("/"));
    requirePath(path, relativePath);
    assert.equal(
      lstatSync(path).isDirectory(),
      true,
      `${relativePath} must be a directory`,
    );
  }
});

test("license, ignore rules, and README expose only public boundaries", () => {
  const licensePath = join(repositoryRoot, "LICENSE");
  requirePath(licensePath, "MIT LICENSE");
  const license = readFileSync(licensePath, "utf8");
  assert.match(license, /MIT License/);
  assert.match(license, /Permission is hereby granted, free of charge/);

  const ignorePath = join(repositoryRoot, ".gitignore");
  requirePath(ignorePath, ".gitignore");
  const ignoreRules = readFileSync(ignorePath, "utf8").split(/\r?\n/u);
  const expectedIgnoreRules = [
  "/.work/",
    "/.selfopenwiki-upstream-update-journal.json",
    "/.selfopenwiki-upstream-update.lock",
  "/runtime/",
    "/self-openwiki/runtime/",
    "node_modules/",
    "dist/",
    "coverage/",
    "self-openwiki/win32-helper-compat/bin/",
    "self-openwiki/win32-helper-compat/obj/",
    "*.tmp",
    "*.temp",
  ];
  for (const rule of expectedIgnoreRules) {
    assert.equal(
      ignoreRules.includes(rule),
      true,
      `.gitignore must contain ${rule}`,
    );
  }
  const activeIgnoreRules = ignoreRules.filter(
    (rule) => rule.length > 0 && !rule.startsWith("#"),
  );
  assert.deepEqual(activeIgnoreRules, expectedIgnoreRules);
  assert.equal(
    activeIgnoreRules.some((rule) =>
      /^\/?(?:wiki|\.selfopenwiki)\/?$/iu.test(rule),
    ),
    false,
  );

  const readmePath = join(repositoryRoot, "README.md");
  requirePath(readmePath, "README.md");
  const readme = readFileSync(readmePath, "utf8");
  assert.match(readme, /^# SelfOpenWiki$/mu);
  assert.match(readme, /Setup\.bat/u);
  assert.match(readme, /Install\.bat/u);
  assert.match(readme, /<wiki-root>/u);
  assert.match(readme, /<wiki-root>\.selfopenwiki/u);
  assert.match(readme, /upstream\/openwiki/u);
});

test("bounded public candidates exclude generated runtime and private bindings", () => {
  const createdDirectories = [];
  const ignoredProbePaths = [
    join(repositoryRoot, ".work", "openwiki", "probe"),
    join(repositoryRoot, "runtime", "verified-capabilities.json"),
  ];
  const createdProbePaths = [];

  try {
    for (const relativePath of [".work", ".work/openwiki", "runtime"]) {
      const path = join(repositoryRoot, ...relativePath.split("/"));
      if (!existsSync(path)) {
        mkdirSync(path);
        createdDirectories.push(path);
      }
    }
    for (const path of ignoredProbePaths) {
      writeFileSync(path, "ignored probe\n", { encoding: "utf8", flag: "wx" });
      createdProbePaths.push(path);
    }

    for (const relativePath of [".selfopenwiki", "wiki"]) {
      assert.equal(
        existsSync(join(repositoryRoot, relativePath)),
        false,
        `${relativePath} must not exist in the public repository root`,
      );
    }
    const ignoredProbeRelativePaths = [
      ".work/openwiki/probe",
      "runtime/verified-capabilities.json",
    ];
    for (const relativePath of ignoredProbeRelativePaths) {
      assertGitIgnored(relativePath);
    }
    const candidates = listPublicCandidates();
    for (const relativePath of ignoredProbeRelativePaths) {
      assert.equal(candidates.includes(relativePath), false);
    }
    assertNoPrivateBindings(candidates);
  } finally {
    for (const path of createdProbePaths) {
      if (existsSync(path)) {
        unlinkSync(path);
      }
    }
    for (const path of createdDirectories.reverse()) {
      rmdirSync(path);
    }
  }
});

test("bounded public scanner normalizes exact Windows private bindings", () => {
  const probePath = join(repositoryRoot, ".private-binding-probe.txt");
  const differentlyCasedPrivateBinding = ["d:/", "WIKI_", "ZXH"].join("");
  let createdProbe = false;
  try {
    writeFileSync(probePath, differentlyCasedPrivateBinding, {
      encoding: "utf8",
      flag: "wx",
    });
    createdProbe = true;
    assert.throws(
      () => assertNoPrivateBindings(listPublicCandidates()),
      /private binding found/u,
    );
  } finally {
    if (createdProbe && existsSync(probePath)) {
      unlinkSync(probePath);
    }
  }
});
