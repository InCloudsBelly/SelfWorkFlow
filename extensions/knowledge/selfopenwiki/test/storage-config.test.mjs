import assert from "node:assert/strict";
import {
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  deriveWikiLayout,
  readStorageConfig,
  resolveWikiPath,
  writeStorageConfig,
} from "../scripts/storage-config.mjs";

async function withTempDirectory(fn) {
  const root = await mkdtemp(path.join(os.tmpdir(), "selfopenwiki-config-"));
  try {
    return await fn(await realpath(root));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test("derives the runtime sibling without inserting a wiki child", () => {
  const layout = deriveWikiLayout("C:\\Knowledge\\wiki_zxh");
  assert.deepEqual(layout, {
    wikiRoot: path.resolve("C:\\Knowledge\\wiki_zxh"),
    runtimeRoot: path.resolve("C:\\Knowledge\\wiki_zxh.selfopenwiki"),
  });
  assert.equal(
    layout.runtimeRoot.startsWith(`${layout.wikiRoot}${path.sep}`),
    false,
  );
});

test("writes and reads a strict config bound to the direct Wiki root", async () => {
  await withTempDirectory(async (root) => {
    const configPath = path.join(root, "config.json");
    const wikiRoot = path.join(root, "private-wiki");
    await mkdir(wikiRoot);
    const written = await writeStorageConfig({ configPath, wikiRoot });
    assert.deepEqual(written, {
      schemaVersion: 1,
      generation: 1,
      wikiRoot: path.resolve(wikiRoot),
      runtimeRoot: path.resolve(`${wikiRoot}.selfopenwiki`),
    });
    assert.deepEqual(await readStorageConfig({ configPath }), written);
    assert.equal(
      await readFile(configPath, "utf8"),
      `${JSON.stringify(written, null, 2)}\n`,
    );
  });
});

test("rejects a config whose derived runtime root or schema is inconsistent", async () => {
  await withTempDirectory(async (root) => {
    const configPath = path.join(root, "config.json");
    const wikiRoot = path.join(root, "private-wiki");
    await writeFile(
      configPath,
      `${JSON.stringify({
        schemaVersion: 1,
        generation: 1,
        wikiRoot: path.resolve(wikiRoot),
        runtimeRoot: path.join(root, "wrong-runtime"),
      })}\n`,
    );
    await assert.rejects(
      readStorageConfig({ configPath }),
      /runtimeRoot|invalid storage config/u,
    );
  });
});

test("rejects a Wiki root with a missing parent or a reparse root", async () => {
  await withTempDirectory(async (root) => {
    await assert.rejects(
      writeStorageConfig({
        configPath: path.join(root, "config.json"),
        wikiRoot: path.join(root, "missing", "wiki"),
      }),
      /parent|root|invalid storage config/u,
    );
    const target = path.join(root, "target");
    const link = path.join(root, "linked-wiki");
    await mkdir(target);
    await symlink(target, link, "junction");
    await assert.rejects(
      writeStorageConfig({
        configPath: path.join(root, "config.json"),
        wikiRoot: link,
      }),
      /link|reparse|invalid storage config/u,
    );
  });
});

test("rejects Windows reserved, ADS, wildcard, and trailing-space Wiki paths", async () => {
  await withTempDirectory(async (root) => {
    for (const relative of ["CON.md", "foo:bar.md", "a. /wiki", "wild*.md"]) {
      assert.throws(
        () => resolveWikiPath(deriveWikiLayout(root), relative),
        /wiki path/u,
        relative,
      );
    }
  });
});

test("rejects 8.3 alias-like segments in parent directories", () => {
  assert.throws(
    () => deriveWikiLayout("C:\\PROGRA~1\\SelfOpenWiki\\wiki"),
    /alias-like segment/u,
  );
});

test("fails closed when a concurrent config writer owns the lock", async () => {
  await withTempDirectory(async (root) => {
    const configPath = path.join(root, "config.json");
    const lockPath = `${configPath}.lock`;
    const wikiRoot = path.join(root, "private-wiki");
    await mkdir(wikiRoot);
    await writeFile(lockPath, "owner\n", { flag: "wx" });
    await assert.rejects(
      writeStorageConfig({ configPath, wikiRoot }),
      /busy|lock/u,
    );
    assert.equal(await readFile(lockPath, "utf8"), "owner\n");
  });
});

test("resolves only Markdown paths inside the direct Wiki root", async () => {
  await withTempDirectory(async (root) => {
    const layout = deriveWikiLayout(path.join(root, "private-wiki"));
    assert.equal(
      resolveWikiPath(layout, "architecture/overview.md"),
      path.join(layout.wikiRoot, "architecture", "overview.md"),
    );
    assert.throws(() => resolveWikiPath(layout, "../outside.md"), /wiki path/u);
    assert.throws(() => resolveWikiPath(layout, ".git/config"), /wiki path/u);
    assert.throws(
      () => resolveWikiPath(layout, "notes.txt"),
      /Markdown|wiki path/u,
    );
  });
});
