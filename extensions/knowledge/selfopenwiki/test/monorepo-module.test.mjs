import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { computeParentSourceManifestSync } from "../scripts/parent-source-manifest.mjs";

function git(root, args) {
  return execFileSync("git", ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", ...args], { cwd: root, encoding: "utf8", windowsHide: true });
}

test("an embedded Wiki module binds only its own HEAD, index and worktree", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "selfworkflow-wiki-module-")));
  const module = join(root, "extensions", "knowledge", "selfopenwiki");
  let failure;
  try {
    mkdirSync(module, { recursive: true });
    mkdirSync(join(root, "src"));
    writeFileSync(join(root, "src", "unrelated.py"), "outside\n");
    writeFileSync(join(module, "README.md"), "wiki module\n");
    git(root, ["init", "--initial-branch=main"]);
    git(root, ["add", "."]);
    git(root, ["commit", "-m", "fixture"]);
    const before = computeParentSourceManifestSync(module);
    assert.deepEqual(new Set(before.manifest.records.map(record => record.path)), new Set(["README.md"]));
    writeFileSync(join(root, "src", "unrelated.py"), "outside changed\n");
    git(root, ["add", "src/unrelated.py"]);
    assert.equal(computeParentSourceManifestSync(module).hash, before.hash);
    writeFileSync(join(module, "README.md"), "module changed\n");
    assert.notEqual(computeParentSourceManifestSync(module).hash, before.hash);
    writeFileSync(join(module, "unknown.py"), "unapproved module source\n");
    assert.throws(() => computeParentSourceManifestSync(module), /outside the allowed manifest/u);
  } catch (error) {
    failure = error;
    throw error;
  } finally {
    // This test owns the absolute temporary root created above.
    try {
      rmSync(root, { force: true, recursive: true, maxRetries: 5, retryDelay: 50 });
    } catch (error) {
      if (!failure) throw error;
    }
  }
});
