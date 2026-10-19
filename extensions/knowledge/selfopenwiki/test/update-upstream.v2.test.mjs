import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import { canonicalManifestBytes } from "../scripts/materialize-openwiki.mjs";
import { applyUpstreamUpdate } from "../scripts/update-upstream.mjs";

const officialUrl = "https://github.com/langchain-ai/openwiki.git";
const bindingPaths = [
  "patches/openwiki/manifest.json",
  "scripts/build-win32-helper.mjs",
  "scripts/materialize-openwiki.mjs",
  "scripts/update-upstream.mjs",
  "test/repository-contract.test.mjs",
  "test/materialize-openwiki.test.mjs",
  "test/update-upstream.v2.test.mjs",
  "README.md",
  "docs/specs/2026-09-10-selfopenwiki-v2-openwiki-integration-design.md",
  "docs/testing/2026-09-10-selfopenwiki-v2-test-design.md",
  "docs/plans/2026-09-10-selfopenwiki-v2-implementation-plan.md",
  "self-openwiki/config/personal-openwiki-compatibility.json",
  "self-openwiki/config/capability-matrix.json",
  "self-openwiki/agent-skills/self-openwiki/SKILL.md",
  "self-openwiki/agent-skills/self-openwiki/references/mcp-contract.md",
  "self-openwiki/agent-skills/self-openwiki/references/migration-v2.md",
  "self-openwiki/mcp-server/src/personal-skill-adapter.ts",
  "self-openwiki/mcp-server/src/contracts.ts",
  "self-openwiki/mcp-server/src/runtime.ts",
  "self-openwiki/mcp-server/src/server.ts",
  "self-openwiki/mcp-server/src/bootstrap.ts",
  "self-openwiki/mcp-server/src/official-lifecycle-adapter.ts",
  "self-openwiki/mcp-server/src/personal-candidate-marker.ts",
  "self-openwiki/mcp-server/src/personal-claims.ts",
  "self-openwiki/mcp-server/src/personal-run-store.ts",
  "self-openwiki/mcp-server/src/personal-wiki-snapshot.ts",
  "self-openwiki/mcp-server/src/personal-wiki-lifecycle.ts",
  "self-openwiki/mcp-server/src/personal-wiki-root.ts",
  "self-openwiki/mcp-server/scripts/personal-tool-bindings.mjs",
  "self-openwiki/mcp-server/test/runtime.c7.ts",
  "self-openwiki/mcp-server/test/personal-lifecycle.v2.ts",
  "self-openwiki/mcp-server/test/personal-compatibility.v2.ts",
  "self-openwiki/mcp-server/test/mcp-surface.v2.ts",
  "self-openwiki/mcp-server/test/official-lifecycle-adapter.v2.ts",
  "self-openwiki/mcp-server/test/personal-candidate-marker.v2.ts",
  "self-openwiki/mcp-server/test/personal-claims.v2.ts",
  "self-openwiki/mcp-server/test/personal-root.v2.ts",
  "self-openwiki/mcp-server/test/personal-run-store.v2.ts",
  "self-openwiki/mcp-server/test/skill-adaptation.v2.ts",
];
const adapterPaths = [
  "contracts.ts",
  "external-update-state.ts",
  "external-update-transaction.ts",
  "official-lifecycle-adapter.ts",
  "personal-candidate-marker.ts",
  "personal-claims.ts",
  "personal-run-store.ts",
  "personal-wiki-snapshot.ts",
  "personal-skill-adapter.ts",
  "personal-wiki-lifecycle.ts",
  "personal-wiki-root.ts",
  "publish.ts",
  "recovery.ts",
  "runtime.ts",
  "server.ts",
  "transaction.ts",
  "transaction-recovery.ts",
];

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

function writeRelative(root, relativePath, value) {
  const absolutePath = join(root, ...relativePath.split("/"));
  mkdirSync(join(absolutePath, ".."), { recursive: true });
  writeFileSync(absolutePath, value, "utf8");
}

function createFixture({ embedded = false } = {}) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "selfopenwiki-updater-")));
  const parentRoot = join(root, "parent");
  const prefix = embedded ? "extensions/knowledge/selfopenwiki/" : "";
  const repositoryRoot = join(parentRoot, prefix);
  const sourceRoot = join(repositoryRoot, "upstream", "openwiki");
  const generatedRoot = join(repositoryRoot, ".work", "openwiki");
  mkdirSync(sourceRoot, { recursive: true });
  git(parentRoot, ["init", "--initial-branch=main"]);
  if (embedded) {
    writeRelative(parentRoot, "src/unrelated.py", "unchanged = True\n");
    writeRelative(parentRoot, "dependencies/locks/selfopenwiki.lock.yaml", "revisionSource: parent-gitlink\n");
    git(parentRoot, ["add", "src", "dependencies"]);
  }
  git(sourceRoot, ["init", "--initial-branch=main"]);
  git(sourceRoot, ["remote", "add", "origin", officialUrl]);
  writeFileSync(join(sourceRoot, "README.md"), "old upstream\n", "utf8");
  git(sourceRoot, ["add", "README.md"]);
  git(sourceRoot, ["commit", "-m", "old upstream"]);
  const previousCommit = git(sourceRoot, ["rev-parse", "HEAD"]);
  writeFileSync(join(sourceRoot, "README.md"), "new upstream\n", "utf8");
  git(sourceRoot, ["add", "README.md"]);
  git(sourceRoot, ["commit", "-m", "new upstream"]);
  const nextCommit = git(sourceRoot, ["rev-parse", "HEAD"]);
  git(sourceRoot, ["checkout", "--detach", previousCommit]);

  writeRelative(
    repositoryRoot,
    "patches/openwiki/manifest.json",
    canonicalManifestBytes({
      schemaVersion: 2,
      domain: "selfopenwiki:openwiki-patch-manifest:v2",
      upstream: { url: officialUrl, commit: previousCommit },
      patches: [],
    }),
  );
  for (const relativePath of bindingPaths.slice(1)) {
    writeRelative(repositoryRoot, relativePath, `${previousCommit}\n`);
  }
  writeRelative(
    repositoryRoot,
    "self-openwiki/config/personal-openwiki-compatibility.json",
    JSON.stringify({
      build: {
        adapterSetHash: "sha256:" + "0".repeat(64),
        generatedMarkerHash: "sha256:" + "0".repeat(64),
        lockfileHash: "sha256:" + "0".repeat(64),
        parentCommit: "0".repeat(40),
        parentSourceManifestHash: "sha256:" + "0".repeat(64),
      },
      upstream: {
        commit: previousCommit,
        packageVersion: "0.1.0",
        url: officialUrl,
      },
    }),
  );
  writeRelative(
    repositoryRoot,
    "self-openwiki/mcp-server/pnpm-lock.yaml",
    "lock\n",
  );
  writeRelative(
    repositoryRoot,
    "self-openwiki/config/bootstrap-source-manifest.json",
    "source\n",
  );
  for (const relativePath of adapterPaths) {
    writeRelative(
      repositoryRoot,
      `self-openwiki/mcp-server/src/${relativePath}`,
      "adapter\n",
    );
  }
  mkdirSync(generatedRoot, { recursive: true });
  writeRelative(generatedRoot, "package.json", '{"version":"0.1.0"}\n');
  writeRelative(
    generatedRoot,
    ".selfopenwiki-materialization.json",
    "old marker\n",
  );
  git(repositoryRoot, ["add", "."]);
  git(repositoryRoot, [
    "update-index",
    "--add",
    "--cacheinfo",
    `160000,${previousCommit},${prefix}upstream/openwiki`,
  ]);
  git(repositoryRoot, ["commit", "-m", "fixture parent"]);
  return {
    generatedRoot,
    nextCommit,
    previousCommit,
    repositoryRoot,
    parentRoot,
    prefix,
    root,
    sourceRoot,
  };
}

function fixtureMaterialize({ generatedRoot }) {
  return () => {
    rmSync(generatedRoot, { recursive: true, force: true });
    mkdirSync(generatedRoot, { recursive: true });
    writeFileSync(
      join(generatedRoot, "package.json"),
      '{"version":"0.6.0"}\n',
      "utf8",
    );
    writeFileSync(
      join(generatedRoot, ".selfopenwiki-materialization.json"),
      "new marker\n",
      "utf8",
    );
    return { status: "materialized" };
  };
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

test("explicit upstream apply updates the bound artifact set and gitlink transactionally", async () => {
  const fixture = createFixture();
  try {
    const result = applyUpstreamUpdate([fixture.nextCommit], {
      confirmed: true,
      repositoryRoot: fixture.repositoryRoot,
      materialize: fixtureMaterialize(fixture),
      stageGitlink: false,
      fetch: false,
      verify: () => undefined,
    });
    assert.equal(result.status, "adopted");
    assert.equal(result.commit, fixture.nextCommit);
    assert.equal(
      git(fixture.repositoryRoot, [
        "-C",
        "upstream/openwiki",
        "rev-parse",
        "HEAD",
      ]),
      fixture.nextCommit,
    );
    assert.match(
      readFileSync(join(fixture.repositoryRoot, "README.md"), "utf8"),
      new RegExp(fixture.nextCommit),
    );
    assert.equal(
      JSON.parse(
        readFileSync(
          join(
            fixture.repositoryRoot,
            "self-openwiki",
            "config",
            "personal-openwiki-compatibility.json",
          ),
          "utf8",
        ),
      ).upstream.commit,
      fixture.nextCommit,
    );
  } finally {
    await cleanup(fixture);
  }
});

test("verification failure preserves a durable recovery journal without checking out the active Submodule", async () => {
  const fixture = createFixture();
  try {
    assert.throws(
      () =>
        applyUpstreamUpdate([fixture.nextCommit], {
          confirmed: true,
          repositoryRoot: fixture.repositoryRoot,
          materialize: fixtureMaterialize(fixture),
          stageGitlink: false,
          fetch: false,
          verify: () => {
            throw new Error("verification fixture failure");
          },
        }),
      /requires manual recovery/u,
    );
    assert.equal(
      git(fixture.sourceRoot, ["rev-parse", "HEAD"]),
      fixture.nextCommit,
    );
    assert.equal(
      git(fixture.repositoryRoot, ["ls-files", "-s", "--", "upstream/openwiki"]),
      `160000 ${fixture.previousCommit} 0\tupstream/openwiki`,
    );
    assert.equal(
      readFileSync(join(fixture.repositoryRoot, ".selfopenwiki-upstream-update.lock"), "utf8").includes("upstream-update-lock-v1"),
      true,
    );
  } finally {
    await cleanup(fixture);
  }
});

test("serializes concurrent upstream mutations with a durable repository lock", async () => {
  const fixture = createFixture();
  try {
    writeFileSync(
      join(fixture.repositoryRoot, ".selfopenwiki-upstream-update.lock"),
      '{"domain":"selfopenwiki:upstream-update-lock-v1","pid":1}\n',
      "utf8",
    );
    assert.throws(
      () =>
        applyUpstreamUpdate([fixture.nextCommit], {
          confirmed: true,
          repositoryRoot: fixture.repositoryRoot,
          fetch: false,
        }),
      /Another upstream update is already mutating/u,
    );
    assert.equal(
      git(fixture.sourceRoot, ["rev-parse", "HEAD"]),
      fixture.previousCommit,
    );
  } finally {
    rmSync(join(fixture.repositoryRoot, ".selfopenwiki-upstream-update.lock"), {
      force: true,
    });
    await cleanup(fixture);
  }
});

test("an embedded module stages the root gitlink without changing the root lock", async () => {
  const fixture = createFixture({ embedded: true });
  try {
    const lockPath = join(fixture.parentRoot, "dependencies/locks/selfopenwiki.lock.yaml");
    const lockBytes = readFileSync(lockPath);
    const result = applyUpstreamUpdate([fixture.nextCommit], {
      confirmed: true, repositoryRoot: fixture.repositoryRoot,
      materialize: fixtureMaterialize(fixture), fetch: false,
      verify: () => undefined,
    });
    assert.equal(result.stagedGitlink, true);
    assert.equal(git(fixture.parentRoot, ["ls-files", "-s", "--", `${fixture.prefix}upstream/openwiki`]), `160000 ${fixture.nextCommit} 0\t${fixture.prefix}upstream/openwiki`);
    assert.equal(git(fixture.parentRoot, ["ls-files", "--", "upstream/openwiki"]), "");
    assert.deepEqual(readFileSync(lockPath), lockBytes);
    assert.equal(readFileSync(join(fixture.parentRoot, "src/unrelated.py"), "utf8"), "unchanged = True\n");
  } finally {
    await cleanup(fixture);
  }
});

test("embedded update failure retains the original root gitlink and recovery state", async () => {
  const fixture = createFixture({ embedded: true });
  try {
    const lockPath = join(fixture.parentRoot, "dependencies/locks/selfopenwiki.lock.yaml");
    const lockBytes = readFileSync(lockPath);
    assert.throws(() => applyUpstreamUpdate([fixture.nextCommit], {
      confirmed: true, repositoryRoot: fixture.repositoryRoot,
      materialize: fixtureMaterialize(fixture), fetch: false,
      stageGitlink: false,
      verify: () => { throw new Error("embedded verification fixture failure"); },
    }), /requires manual recovery/u);
    assert.equal(git(fixture.parentRoot, ["ls-files", "-s", "--", `${fixture.prefix}upstream/openwiki`]), `160000 ${fixture.previousCommit} 0\t${fixture.prefix}upstream/openwiki`);
    assert.deepEqual(readFileSync(lockPath), lockBytes);
    assert.equal(readFileSync(join(fixture.repositoryRoot, ".selfopenwiki-upstream-update.lock"), "utf8").includes("upstream-update-lock-v1"), true);
  } finally {
    await cleanup(fixture);
  }
});
