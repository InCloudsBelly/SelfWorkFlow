import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  copyFileSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  MATERIALIZATION_MARKER,
  FROZEN_UPSTREAM_COMMIT,
  canonicalManifestBytes,
  materializeOpenWiki,
  parseUpdateCommit,
  validateManifest,
  verifyGeneratedRoot,
} from "../scripts/materialize-openwiki.mjs";
import { createUpstreamUpdatePlan } from "../scripts/update-upstream.mjs";

const officialUrl = "https://github.com/langchain-ai/openwiki.git";

function git(cwd, args) {
  return execFileSync("git", args, {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      GIT_AUTHOR_EMAIL: "fixture@example.invalid",
      GIT_AUTHOR_NAME: "Fixture",
      GIT_COMMITTER_EMAIL: "fixture@example.invalid",
      GIT_COMMITTER_NAME: "Fixture",
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_TERMINAL_PROMPT: "0",
    },
  }).trim();
}

function createFixture() {
  const root = mkdtempSync(join(tmpdir(), "selfopenwiki-materializer-"));
  const repositoryRoot = join(root, "parent");
  const sourceRoot = join(repositoryRoot, "upstream", "openwiki");
  const patchRoot = join(repositoryRoot, "patches", "openwiki");
  const generatedRoot = join(repositoryRoot, ".work", "openwiki");
  mkdirSync(sourceRoot, { recursive: true });
  mkdirSync(patchRoot, { recursive: true });
  git(repositoryRoot, ["init", "--initial-branch=main"]);
  git(sourceRoot, ["init", "--initial-branch=main"]);
  git(sourceRoot, ["remote", "add", "origin", officialUrl]);
  writeFileSync(join(sourceRoot, "README.md"), "upstream\n", "utf8");
  writeFileSync(
    join(sourceRoot, ".gitignore"),
    "dist/\nnode_modules/\n.env\ncredentials.json\n*.pem\n",
    "utf8",
  );
  git(sourceRoot, ["add", "README.md", ".gitignore"]);
  git(sourceRoot, ["commit", "-m", "fixture upstream"]);
  const commit = git(sourceRoot, ["rev-parse", "HEAD"]);
  git(sourceRoot, ["checkout", "--detach", commit]);

  writeFileSync(
    join(patchRoot, "0001-historical-v1.patch"),
    "This historical patch is intentionally not a valid v2 input.\n",
    "utf8",
  );

  const manifest = {
    schemaVersion: 2,
    domain: "selfopenwiki:openwiki-patch-manifest:v2",
    upstream: { url: officialUrl, commit },
    patches: [],
  };
  const manifestPath = join(patchRoot, "manifest.json");
  writeFileSync(manifestPath, canonicalManifestBytes(manifest));
  return {
    commit,
    generatedRoot,
    manifest,
    manifestPath,
    repositoryRoot,
    root,
    sourceRoot,
  };
}

function snapshotTree(root) {
  const rows = [];
  const pending = [root];
  while (pending.length > 0) {
    const current = pending.pop();
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const path = join(current, entry.name);
      const relativePath = path.slice(root.length + 1).replaceAll("\\", "/");
      const stats = lstatSync(path);
      if (stats.isDirectory()) {
        pending.push(path);
      } else {
        const bytes = readFileSync(path);
        rows.push(
          `${relativePath}\0${bytes.length}\0${createHash("sha256").update(bytes).digest("hex")}`,
        );
      }
    }
  }
  return rows.sort().join("\n");
}

async function cleanup(fixture) {
  let lastError;
  for (let attempt = 0; attempt < 10; attempt += 1) {
    try {
      rmSync(fixture.root, { recursive: true, force: true });
      return;
    } catch (error) {
      lastError = error;
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
    }
  }
  throw lastError;
}

function runMaterializer(fixture, overrides = {}) {
  return materializeOpenWiki({
    repositoryRoot: fixture.repositoryRoot,
    sourceRoot: fixture.sourceRoot,
    generatedRoot: fixture.generatedRoot,
    manifestPath: fixture.manifestPath,
    expectedUpstreamCommit: fixture.commit,
    ...overrides,
  });
}

test("rejects tracked modifications hidden by Git index flags", async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    const binding = validateManifest(fixture.repositoryRoot, fixture.manifestPath, fixture.commit);
    for (const flag of ["--assume-unchanged", "--skip-worktree"]) {
      git(fixture.generatedRoot, ["update-index", flag, "README.md"]);
      writeFileSync(join(fixture.generatedRoot, "README.md"), "hidden modification\n");
      assert.equal(verifyGeneratedRoot(fixture.generatedRoot, fixture.commit, binding.manifest, binding.manifestHash), false);
      git(fixture.generatedRoot, ["update-index", flag === "--assume-unchanged" ? "--no-assume-unchanged" : "--no-skip-worktree", "README.md"]);
      writeFileSync(join(fixture.generatedRoot, "README.md"), "upstream\n");
    }
  } finally {
    await cleanup(fixture);
  }
});

test("does not execute a generated checkout fsmonitor during verification", async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    const sentinel = join(fixture.root, "fsmonitor-executed");
    const hook = join(fixture.root, "fsmonitor.sh");
    writeFileSync(hook, `#!/bin/sh\nprintf executed > '${sentinel.replaceAll("\\", "/")}'\nprintf '\\000'\n`);
    git(fixture.generatedRoot, ["config", "core.fsmonitor", hook.replaceAll("\\", "/")]);
    const binding = validateManifest(fixture.repositoryRoot, fixture.manifestPath, fixture.commit);
    assert.equal(verifyGeneratedRoot(fixture.generatedRoot, fixture.commit, binding.manifest, binding.manifestHash), true);
    assert.equal(existsSync(sentinel), false);
  } finally {
    await cleanup(fixture);
  }
});

test("does not execute a checkout-local clean filter during verification", async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    const sentinel = join(fixture.root, "filter-executed");
    const hook = join(fixture.root, "filter.sh");
    writeFileSync(hook, `#!/bin/sh\nprintf executed > '${sentinel.replaceAll("\\", "/")}'\ncat\n`);
    writeFileSync(join(fixture.generatedRoot, ".git", "info", "attributes"), "README.md filter=fixture\n");
    git(fixture.generatedRoot, ["config", "filter.fixture.clean", `sh '${hook.replaceAll("\\", "/")}'`]);
    writeFileSync(join(fixture.generatedRoot, "README.md"), "unverified change\n");
    const binding = validateManifest(fixture.repositoryRoot, fixture.manifestPath, fixture.commit);
    assert.equal(verifyGeneratedRoot(fixture.generatedRoot, fixture.commit, binding.manifest, binding.manifestHash), false);
    assert.equal(existsSync(sentinel), false);
  } finally {
    await cleanup(fixture);
  }
});

test("accepts a legitimate detached linked worktree with the same materialization", async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    const linked = join(fixture.root, "linked");
    git(fixture.generatedRoot, ["worktree", "add", "--detach", linked, fixture.commit]);
    writeFileSync(join(linked, MATERIALIZATION_MARKER), readFileSync(join(fixture.generatedRoot, MATERIALIZATION_MARKER)));
    const binding = validateManifest(fixture.repositoryRoot, fixture.manifestPath, fixture.commit);
    assert.equal(verifyGeneratedRoot(linked, fixture.commit, binding.manifest, binding.manifestHash), true);
  } finally {
    await cleanup(fixture);
  }
});

test("rejects tracked executable-bit drift on POSIX", { skip: process.platform === "win32" }, async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    chmodSync(join(fixture.generatedRoot, "README.md"), 0o755);
    const binding = validateManifest(fixture.repositoryRoot, fixture.manifestPath, fixture.commit);
    assert.equal(verifyGeneratedRoot(fixture.generatedRoot, fixture.commit, binding.manifest, binding.manifestHash), false);
  } finally {
    await cleanup(fixture);
  }
});

test("fails closed on a future upstream checkout transformed by eol attributes", async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    git(fixture.sourceRoot, ["checkout", "-b", "eol-update"]);
    writeFileSync(join(fixture.sourceRoot, ".gitattributes"), "*.txt text eol=crlf\n");
    writeFileSync(join(fixture.sourceRoot, "example.txt"), "one\ntwo\n");
    git(fixture.sourceRoot, ["add", ".gitattributes", "example.txt"]);
    git(fixture.sourceRoot, ["commit", "-m", "future transformed checkout"]);
    const next = git(fixture.sourceRoot, ["rev-parse", "HEAD"]);
    git(fixture.sourceRoot, ["checkout", "--detach", next]);
    writeFileSync(fixture.manifestPath, canonicalManifestBytes({ ...fixture.manifest, upstream: { url: officialUrl, commit: next } }));
    assert.throws(() => runMaterializer(fixture, { expectedUpstreamCommit: next }), /generated checkout verification failed/i);
    assert.equal(git(fixture.generatedRoot, ["rev-parse", "HEAD"]), fixture.commit);
    assert.equal(readFileSync(join(fixture.generatedRoot, "README.md"), "utf8"), "upstream\n");
  } finally {
    await cleanup(fixture);
  }
});

test("rejects a replacement Git object that hides changed generated source", async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    writeFileSync(join(fixture.generatedRoot, "README.md"), "replacement contents\n");
    git(fixture.generatedRoot, ["add", "README.md"]);
    git(fixture.generatedRoot, ["commit", "-m", "replacement tree"]);
    const replacement = git(fixture.generatedRoot, ["rev-parse", "HEAD"]);
    git(fixture.generatedRoot, ["replace", fixture.commit, replacement]);
    git(fixture.generatedRoot, ["update-ref", "--no-deref", "HEAD", fixture.commit]);
    const binding = validateManifest(fixture.repositoryRoot, fixture.manifestPath, fixture.commit);
    assert.equal(verifyGeneratedRoot(fixture.generatedRoot, fixture.commit, binding.manifest, binding.manifestHash), false);
  } finally {
    await cleanup(fixture);
  }
});

test("capability verification invalidates evidence before rejecting an old checkout without building it", { skip: process.platform !== "win32" }, async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    const runtime = join(fixture.repositoryRoot, "self-openwiki", "runtime");
    const verifierDir = join(fixture.repositoryRoot, "self-openwiki", "scripts");
    const scriptsDir = join(fixture.repositoryRoot, "scripts");
    const binDir = join(fixture.root, "bin");
    for (const directory of [runtime, verifierDir, scriptsDir, binDir]) mkdirSync(directory, { recursive: true });
    const evidence = join(runtime, "verified-capabilities.json");
    const sentinel = join(fixture.root, "build-invoked");
    writeFileSync(evidence, "old verified evidence");
    writeFileSync(join(binDir, "corepack.cmd"), `@echo invoked > "${sentinel}"\r\n@exit /b 1\r\n`);
    copyFileSync(fileURLToPath(new URL("../scripts/materialize-openwiki.mjs", import.meta.url)), join(scriptsDir, "materialize-openwiki.mjs"));
    copyFileSync(fileURLToPath(new URL("../self-openwiki/scripts/verify-capabilities.mts", import.meta.url)), join(verifierDir, "verify-capabilities.mts"));
    writeFileSync(fixture.manifestPath, canonicalManifestBytes({ ...fixture.manifest, upstream: { url: officialUrl, commit: FROZEN_UPSTREAM_COMMIT } }));
    const result = spawnSync(process.execPath, [join(verifierDir, "verify-capabilities.mts")], { env: { ...process.env, PATH: `${binDir};${process.env.PATH}` }, encoding: "utf8", timeout: 15000, windowsHide: true });
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stderr, /generated OpenWiki.*does not match/i);
    assert.equal(existsSync(evidence), false);
    assert.equal(existsSync(sentinel), false);
    assert.equal(git(fixture.generatedRoot, ["rev-parse", "HEAD"]), fixture.commit);
  } finally {
    await cleanup(fixture);
  }
});

test("materializes the exact upstream checkout without dirtying source", async () => {
  const fixture = createFixture();
  try {
    const before = git(fixture.sourceRoot, ["status", "--porcelain"]);
    const parentGitBefore = snapshotTree(join(fixture.repositoryRoot, ".git"));
    const result = runMaterializer(fixture);
    assert.equal(result.status, "materialized");
    assert.equal(
      readFileSync(join(fixture.generatedRoot, "README.md"), "utf8"),
      "upstream\n",
    );
    assert.equal(
      existsSync(join(fixture.generatedRoot, MATERIALIZATION_MARKER)),
      true,
    );
    assert.equal(
      git(fixture.generatedRoot, ["remote", "get-url", "origin"]),
      officialUrl,
    );
    assert.equal(
      readFileSync(
        join(fixture.generatedRoot, ".git", "config"),
        "utf8",
      ).includes(fixture.repositoryRoot),
      false,
      "generated Git metadata must not retain a machine-local owner path",
    );
    assert.equal(git(fixture.sourceRoot, ["status", "--porcelain"]), before);
    assert.equal(
      git(fixture.sourceRoot, ["rev-parse", "HEAD"]),
      fixture.commit,
    );
    assert.equal(
      snapshotTree(join(fixture.repositoryRoot, ".git")),
      parentGitBefore,
      "materialization must not mutate parent Git metadata",
    );

    const retry = runMaterializer(fixture);
    assert.equal(retry.status, "reused");
  } finally {
    await cleanup(fixture);
  }
});

test("rebuilds instead of reusing a generated checkout with extra drift", async () => {
  const fixture = createFixture();
  try {
    assert.equal(runMaterializer(fixture).status, "materialized");
    const unexpectedPath = join(fixture.generatedRoot, "unexpected.txt");
    writeFileSync(unexpectedPath, "drift\n", "utf8");

    assert.equal(runMaterializer(fixture).status, "materialized");
    assert.equal(existsSync(unexpectedPath), false);
    assert.equal(git(fixture.sourceRoot, ["status", "--porcelain"]), "");
  } finally {
    await cleanup(fixture);
  }
});

test("reuses a generated checkout with ignored dependency and build artifacts", async () => {
  const fixture = createFixture();
  try {
    assert.equal(runMaterializer(fixture).status, "materialized");
    const artifactPath = join(fixture.generatedRoot, "dist", "index.js");
    const dependencyPath = join(
      fixture.generatedRoot,
      "node_modules",
      "fixture-package",
      "index.js",
    );
    mkdirSync(dirname(artifactPath), { recursive: true });
    mkdirSync(dirname(dependencyPath), { recursive: true });
    writeFileSync(artifactPath, "verified build\n", "utf8");
    writeFileSync(dependencyPath, "installed dependency\n", "utf8");

    assert.equal(runMaterializer(fixture).status, "reused");
    assert.equal(readFileSync(artifactPath, "utf8"), "verified build\n");
    assert.equal(
      readFileSync(dependencyPath, "utf8"),
      "installed dependency\n",
    );
  } finally {
    await cleanup(fixture);
  }
});

test("rebuilds instead of reusing a generated checkout with an ignored secret", async () => {
  const fixture = createFixture();
  try {
    assert.equal(runMaterializer(fixture).status, "materialized");
    const ignoredSecret = join(fixture.generatedRoot, ".env");
    writeFileSync(ignoredSecret, "TOKEN=fixture-secret\n", "utf8");

    assert.equal(runMaterializer(fixture).status, "materialized");
    assert.equal(existsSync(ignoredSecret), false);
    assert.equal(git(fixture.sourceRoot, ["status", "--porcelain"]), "");
  } finally {
    await cleanup(fixture);
  }
});

test("rebuilds a generated checkout whose origin drifts to a machine-local path", async () => {
  const fixture = createFixture();
  try {
    assert.equal(runMaterializer(fixture).status, "materialized");
    git(fixture.generatedRoot, [
      "remote",
      "set-url",
      "origin",
      fixture.sourceRoot,
    ]);

    assert.equal(runMaterializer(fixture).status, "materialized");
    assert.equal(
      git(fixture.generatedRoot, ["remote", "get-url", "origin"]),
      officialUrl,
    );
  } finally {
    await cleanup(fixture);
  }
});

test("ignores inherited Git repository and hook redirection variables", async () => {
  const fixture = createFixture();
  const saved = {
    GIT_DIR: process.env.GIT_DIR,
    GIT_WORK_TREE: process.env.GIT_WORK_TREE,
    GIT_INDEX_FILE: process.env.GIT_INDEX_FILE,
    GIT_CONFIG_GLOBAL: process.env.GIT_CONFIG_GLOBAL,
  };
  try {
    process.env.GIT_DIR = join(fixture.root, "hostile-git-dir");
    process.env.GIT_WORK_TREE = join(fixture.root, "hostile-work-tree");
    process.env.GIT_INDEX_FILE = join(fixture.root, "hostile-index");
    process.env.GIT_CONFIG_GLOBAL = join(fixture.root, "hostile-global-config");
    assert.equal(runMaterializer(fixture).status, "materialized");
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await cleanup(fixture);
  }
});

test("fails closed for wrong URL, wrong commit, or dirty source", async () => {
  for (const mode of ["url", "commit", "dirty"]) {
    const fixture = createFixture();
    try {
      if (mode === "url") {
        git(fixture.sourceRoot, [
          "remote",
          "set-url",
          "origin",
          "https://example.invalid/openwiki.git",
        ]);
      } else if (mode === "commit") {
        git(fixture.sourceRoot, ["checkout", "-b", "drift"]);
        writeFileSync(join(fixture.sourceRoot, "drift.txt"), "drift\n", "utf8");
        git(fixture.sourceRoot, ["add", "drift.txt"]);
        git(fixture.sourceRoot, ["commit", "-m", "drift"]);
        git(fixture.sourceRoot, ["checkout", "--detach", "HEAD"]);
      } else {
        writeFileSync(join(fixture.sourceRoot, "README.md"), "dirty\n", "utf8");
      }
      assert.throws(
        () => runMaterializer(fixture),
        new RegExp(mode === "url" ? "URL" : mode),
      );
      assert.equal(existsSync(fixture.generatedRoot), false);
    } finally {
      await cleanup(fixture);
    }
  }
});

test("rejects alternate generated and manifest owner paths", async () => {
  const fixture = createFixture();
  try {
    assert.throws(
      () =>
        runMaterializer(fixture, {
          generatedRoot: join(fixture.repositoryRoot, ".work", "alternate"),
        }),
      /exactly \.work[/\\]openwiki/u,
    );
    const alternateManifest = join(
      fixture.repositoryRoot,
      "patches",
      "openwiki",
      "alternate.json",
    );
    writeFileSync(alternateManifest, readFileSync(fixture.manifestPath));
    assert.throws(
      () => runMaterializer(fixture, { manifestPath: alternateManifest }),
      /exact manifest owner path/u,
    );
  } finally {
    await cleanup(fixture);
  }
});

test("rejects legacy manifests and any non-empty v2 patch list", async () => {
  const fixture = createFixture();
  try {
    const base = structuredClone(fixture.manifest);
    const mutations = [
      (value) => {
        value.schemaVersion = 1;
        value.domain = "selfopenwiki:openwiki-patch-manifest:v1";
      },
      (value) => {
        value.patches = [{ order: 1 }];
      },
    ];
    for (const mutate of mutations) {
      const candidate = structuredClone(base);
      mutate(candidate);
      writeFileSync(
        fixture.manifestPath,
        `${JSON.stringify(candidate, null, 2)}\n`,
        "utf8",
      );
      assert.throws(() =>
        validateManifest(
          fixture.repositoryRoot,
          fixture.manifestPath,
          fixture.commit,
        ),
      );
    }
    writeFileSync(fixture.manifestPath, canonicalManifestBytes(base));
    assert.equal(runMaterializer(fixture).status, "materialized");
  } finally {
    await cleanup(fixture);
  }
});

test("rejecting a non-empty patch manifest preserves a preexisting last-good generated root", async () => {
  const fixture = createFixture();
  try {
    runMaterializer(fixture);
    const markerBefore = readFileSync(
      join(fixture.generatedRoot, MATERIALIZATION_MARKER),
    );
    const readmeBefore = readFileSync(join(fixture.generatedRoot, "README.md"));
    const changed = structuredClone(fixture.manifest);
    changed.patches = [{ order: 1 }];
    writeFileSync(
      fixture.manifestPath,
      `${JSON.stringify(changed, null, 2)}\n`,
      "utf8",
    );
    assert.throws(() => runMaterializer(fixture), /zero patches/u);
    assert.deepEqual(
      readFileSync(join(fixture.generatedRoot, MATERIALIZATION_MARKER)),
      markerBefore,
    );
    assert.deepEqual(
      readFileSync(join(fixture.generatedRoot, "README.md")),
      readmeBefore,
    );
    assert.equal(git(fixture.sourceRoot, ["status", "--porcelain"]), "");
  } finally {
    await cleanup(fixture);
  }
});

test("adoption response loss is reconciled exactly on retry", async () => {
  const fixture = createFixture();
  try {
    mkdirSync(dirname(fixture.generatedRoot), { recursive: true });
    mkdirSync(fixture.generatedRoot);
    writeFileSync(
      join(fixture.generatedRoot, "old.txt"),
      "last-good\n",
      "utf8",
    );
    assert.throws(
      () => runMaterializer(fixture, { faultAt: "after-backup-rename" }),
      /injected adoption response loss/u,
    );
    assert.equal(existsSync(fixture.generatedRoot), false);
    const retry = runMaterializer(fixture);
    assert.equal(retry.status, "materialized");
    assert.equal(
      readFileSync(join(fixture.generatedRoot, "README.md"), "utf8"),
      "upstream\n",
    );
    assert.equal(git(fixture.sourceRoot, ["status", "--porcelain"]), "");
  } finally {
    await cleanup(fixture);
  }
});

test("candidate-rename response loss is accepted only for the verified target", async () => {
  const fixture = createFixture();
  try {
    mkdirSync(dirname(fixture.generatedRoot), { recursive: true });
    mkdirSync(fixture.generatedRoot);
    writeFileSync(
      join(fixture.generatedRoot, "old.txt"),
      "last-good\n",
      "utf8",
    );
    assert.throws(
      () => runMaterializer(fixture, { faultAt: "after-candidate-rename" }),
      /injected candidate-rename response loss/u,
    );
    assert.equal(
      readFileSync(join(fixture.generatedRoot, "README.md"), "utf8"),
      "upstream\n",
    );
    const retry = runMaterializer(fixture);
    assert.equal(retry.status, "reused");
    assert.equal(git(fixture.sourceRoot, ["status", "--porcelain"]), "");
  } finally {
    await cleanup(fixture);
  }
});

test("a dead-owner lock is recovered without weakening a live exclusive lock", async () => {
  const fixture = createFixture();
  try {
    mkdirSync(dirname(fixture.generatedRoot), { recursive: true });
    writeFileSync(
      `${fixture.generatedRoot}.materialization-lock`,
      '{"domain":"selfopenwiki:openwiki-materialization-lock:v1","pid":2147483647,"schemaVersion":1}\n',
      "utf8",
    );
    assert.equal(runMaterializer(fixture).status, "materialized");
    writeFileSync(
      `${fixture.generatedRoot}.materialization-lock`,
      `${JSON.stringify({ domain: "selfopenwiki:openwiki-materialization-lock:v1", pid: process.pid, schemaVersion: 1 })}\n`,
      "utf8",
    );
    assert.throws(() => runMaterializer(fixture), /already running/u);
  } finally {
    await cleanup(fixture);
  }
});

test("partial deterministic candidate never replaces last-good on rejected manifest", async () => {
  const fixture = createFixture();
  try {
    mkdirSync(dirname(fixture.generatedRoot), { recursive: true });
    mkdirSync(fixture.generatedRoot);
    writeFileSync(
      join(fixture.generatedRoot, "old.txt"),
      "last-good\n",
      "utf8",
    );
    const candidateRoot = `${fixture.generatedRoot}.candidate`;
    mkdirSync(candidateRoot);
    writeFileSync(join(candidateRoot, "partial.txt"), "partial\n", "utf8");
    const changed = structuredClone(fixture.manifest);
    changed.patches = [{ order: 1 }];
    writeFileSync(
      fixture.manifestPath,
      `${JSON.stringify(changed, null, 2)}\n`,
      "utf8",
    );
    assert.throws(() => runMaterializer(fixture), /zero patches/u);
    assert.equal(
      readFileSync(join(fixture.generatedRoot, "old.txt"), "utf8"),
      "last-good\n",
    );
    assert.equal(existsSync(candidateRoot), true);
  } finally {
    await cleanup(fixture);
  }
});

test("manual upstream update requires an explicit commit or reviewed tag and never means latest", () => {
  const commit = "a".repeat(40);
  assert.equal(parseUpdateCommit([commit]), commit);
  assert.deepEqual(createUpstreamUpdatePlan([commit]), {
    schemaVersion: 1,
    domain: "selfopenwiki:manual-upstream-update-plan:v1",
    commit,
    actions: [
      "review-official-commit",
      "refresh-gitlink",
      "refresh-zero-patch-manifest",
      "adapt-personal-skill",
      "refresh-capability-evidence",
      "review-and-confirm-new-contract",
    ],
    automaticRemoteSelection: false,
    mutatesRepository: false,
  });
  for (const args of [
    [],
    ["latest"],
    ["main"],
    ["a".repeat(39)],
    [commit, "extra"],
  ]) {
    assert.throws(
      () => parseUpdateCommit(args),
      /explicit 40-character commit/u,
    );
  }
  for (const args of [["--tag"], ["--tag", "v1..2"], ["--tag", "v1//2"]]) {
    assert.throws(
      () => createUpstreamUpdatePlan(args, { resolveTag: () => ({}) }),
      /40-character commit or --tag <reviewed-tag>/u,
    );
  }
  assert.throws(
    () =>
      createUpstreamUpdatePlan(["--tag", "main"], { resolveTag: () => ({}) }),
    /tag resolution is invalid/u,
  );
  const launcher = readFileSync(
    join(fileURLToPath(new URL("..", import.meta.url)), "Update-Upstream.bat"),
    "utf8",
  );
  assert.doesNotMatch(launcher, /%\*/u);
  assert.match(launcher, /update-upstream\.mjs" "%~1"/u);
  assert.match(launcher, /--tag/iu);
  assert.match(launcher, /--apply/iu);
});

test("manual upstream update accepts a reviewed annotated tag with its peeled commit", () => {
  const tag = "v0.5.1";
  const peeledCommit = "b".repeat(40);
  const tagObject = "c".repeat(40);
  assert.deepEqual(
    createUpstreamUpdatePlan(["--tag", tag], {
      resolveTag: () => ({ tagObject, peeledCommit }),
    }),
    {
      schemaVersion: 1,
      domain: "selfopenwiki:manual-upstream-update-plan:v1",
      commit: peeledCommit,
      selection: {
        kind: "tag",
        name: tag,
        remote: "https://github.com/langchain-ai/openwiki.git",
        tagObject,
        peeledCommit,
      },
      actions: [
        "review-official-commit",
        "refresh-gitlink",
        "refresh-zero-patch-manifest",
        "adapt-personal-skill",
        "refresh-capability-evidence",
        "review-and-confirm-new-contract",
      ],
      automaticRemoteSelection: false,
      mutatesRepository: false,
    },
  );
});

test("materializer CLI exposes only an absolute repository-root override", async () => {
  const fixture = createFixture();
  try {
    const script = join(
      fileURLToPath(new URL("..", import.meta.url)),
      "scripts",
      "materialize-openwiki.mjs",
    );
    const rejected = spawnSync(
      process.execPath,
      [script, "--source-root", fixture.sourceRoot],
      { encoding: "utf8" },
    );
    assert.equal(rejected.status, 1);
    assert.match(
      rejected.stderr,
      /unknown or incomplete materializer argument/u,
    );

    const accepted = spawnSync(
      process.execPath,
      [script, "--repository-root", dirname(dirname(script))],
      { encoding: "utf8" },
    );
    assert.equal(accepted.status, 0, accepted.stderr);
    assert.match(
      JSON.parse(accepted.stdout).status,
      /^(?:materialized|reused)$/u,
    );
  } finally {
    await cleanup(fixture);
  }
});
