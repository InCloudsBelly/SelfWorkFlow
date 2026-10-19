import { mkdir, mkdtemp, rm, stat, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, expect, test } from "vitest";
import { bootstrapC7Runtime } from "../src/bootstrap.js";

const tempRoots: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempRoots
      .splice(0)
      .map((root) => rm(root, { force: true, recursive: true })),
  );
});

test("binds MCP status and revision to a selected external Git Wiki root", async () => {
  const wikiRoot = await mkdtemp(path.join(os.tmpdir(), "self-openwiki-wiki-"));
  tempRoots.push(wikiRoot);
  const runtimeRoot = `${wikiRoot}.selfopenwiki`;
  tempRoots.push(runtimeRoot);
  await mkdir(path.join(wikiRoot, ".git"));
  await writeFile(
    path.join(wikiRoot, ".git", "HEAD"),
    "ref: refs/heads/main\n",
  );
  await writeFile(path.join(wikiRoot, "index.md"), "# Personal Wiki\n");

  const repositoryRoot = path.resolve(import.meta.dirname, "../..");
  const result = await bootstrapC7Runtime({
    openWikiRoot: path.resolve(repositoryRoot, "..", ".work", "openwiki"),
    repositoryRoot,
    runtimeDir: runtimeRoot,
    wikiRoot,
  });
  const status = (await result.runtime.invoke("openwiki_status", {})) as {
    paths: { wikiRoot: string; runtimeRoot: string };
    wikiRevision: string;
  };

  expect(status.paths.wikiRoot).toBe(wikiRoot);
  expect(status.paths.runtimeRoot).toBe(runtimeRoot);
  expect(status.wikiRevision).toMatch(/^sha256:[a-f0-9]{64}$/u);
});

test("rejects an external Wiki root junction before creating its runtime sibling", async () => {
  const parent = await mkdtemp(
    path.join(os.tmpdir(), "self-openwiki-reparse-"),
  );
  tempRoots.push(parent);
  const target = path.join(parent, "target");
  const wikiRoot = path.join(parent, "wiki");
  const runtimeRoot = `${wikiRoot}.selfopenwiki`;
  await mkdir(target);
  await symlink(
    target,
    wikiRoot,
    process.platform === "win32" ? "junction" : "dir",
  );

  await expect(
    bootstrapC7Runtime({
      repositoryRoot: path.resolve(import.meta.dirname, "../.."),
      runtimeDir: runtimeRoot,
      wikiRoot,
    }),
  ).rejects.toThrow(/link|junction/u);
  await expect(stat(runtimeRoot)).rejects.toMatchObject({ code: "ENOENT" });
});
