import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import {
  computeParentSourceManifestSync,
  parentSourceManifestHash,
} from "../scripts/parent-source-manifest.mjs";

function git(cwd, args) {
  return execFileSync("git", args, {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_TERMINAL_PROMPT: "0",
    },
  }).trim();
}

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "selfopenwiki-source-manifest-"));
  git(root, ["init", "--initial-branch=main"]);
  writeFileSync(join(root, "README.md"), "one\n", "utf8");
  mkdirSync(join(root, "docs"));
  writeFileSync(join(root, "docs", "guide.md"), "guide\n", "utf8");
  git(root, ["add", "."]);
  git(root, ["commit", "-m", "fixture"]);
  return root;
}

test("uses the normative empty manifest hash", () => {
  assert.equal(
    parentSourceManifestHash({ version: 1, records: [] }),
    "sha256:7e991f4d5d5045988a783bb6a2b3760bdc7efb7aa2f2a8c847c00597c9354edc",
  );
});

test("binds tracked, untracked, deleted, and conflict observations", () => {
  const root = fixture();
  try {
    writeFileSync(join(root, "README.md"), "worktree\n", "utf8");
    rmSync(join(root, "docs", "guide.md"));
    writeFileSync(join(root, "docs", "new.md"), "new\n", "utf8");
    mkdirSync(join(root, ".codegraph"));
    writeFileSync(join(root, ".codegraph", ".gitignore"), "*\n", "utf8");
    git(root, ["add", "-u", "docs/guide.md"]);
    const result = computeParentSourceManifestSync(root);
    const records = result.manifest.records.filter(
      (record) => record.path === "README.md" || record.path.startsWith("docs/"),
    );
    assert.ok(records.some((record) => record.path === "README.md" && record.layer === "worktree"));
    assert.ok(records.some((record) => record.path === "docs/guide.md" && record.layer === "index" && record.kind === "absent"));
    assert.ok(records.some((record) => record.path === "docs/new.md" && record.layer === "worktree"));
    assert.ok(result.manifest.records.every((record) => !record.path.startsWith(".codegraph/")));

    writeFileSync(join(root, "docs", "guide.md"), "ours\n", "utf8");
    git(root, ["add", "docs/guide.md"]);
    git(root, ["write-tree"]);
    const conflict = computeParentSourceManifestSync(root);
    assert.ok(conflict.manifest.records.every((record) => record.path !== "docs/guide.md" || record.layer !== "index" || record.stage === 0));
  } finally {
    rmSync(root, { force: true, recursive: true });
  }
});
