import path from "node:path";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, realpath, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import { afterEach, describe, expect, test } from "vitest";
import { resolvePersonalWikiRoot } from "../src/personal-wiki-root.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("personal Wiki root binding", () => {
  test("a Git clone imports Markdown and Claims without the original runtime", async () => {
    const parent = await realpath(await mkdtemp(path.join(os.tmpdir(), "portable-wiki-")));
    tempDirs.push(parent);
    const source = path.join(parent, "source");
    const cloned = path.join(parent, "cloned");
    await mkdir(path.join(source, ".claims"), { recursive: true });
    const page = "# Shared knowledge\n";
    const claims = JSON.stringify({ schemaVersion: 1, claims: [], pageVersion: `sha256:${createHash("sha256").update(page).digest("hex")}` });
    await writeFile(path.join(source, "guide.md"), page);
    await writeFile(path.join(source, ".claims/guide.json"), claims);
    await writeFile(path.join(source, ".gitattributes"), await readFile(path.resolve(import.meta.dirname, "../../../templates/wiki.gitattributes")));
    await writeFile(path.join(source, ".gitignore"), await readFile(path.resolve(import.meta.dirname, "../../../templates/wiki.gitignore")));
    const git = (root: string, args: string[]) => execFileSync("git", ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", ...args], { cwd: root, stdio: "ignore" });
    git(source, ["init", "--initial-branch=main"]);
    git(source, ["config", "core.autocrlf", "true"]);
    git(source, ["add", "."]);
    git(source, ["commit", "-m", "portable knowledge"]);
    git(parent, ["clone", "--local", source, cloned]);
    expect(existsSync(`${source}.selfopenwiki`)).toBe(false);
    expect(existsSync(`${cloned}.selfopenwiki`)).toBe(false);
    const imported = await resolvePersonalWikiRoot(cloned);
    expect(await readFile(path.join(imported.wikiRoot, "guide.md"), "utf8")).toBe(page);
    expect(await readFile(path.join(imported.wikiRoot, ".claims/guide.json"), "utf8")).toBe(claims);
    expect(imported.runtimeRoot).toBe(`${imported.wikiRoot}.selfopenwiki`);
    expect(existsSync(`${source}.selfopenwiki`)).toBe(false);
  });

  test("accepts the explicit root only when it is the canonical Git repository root", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-wiki-"));
    tempDirs.push(root);
    await writeFile(path.join(root, "index.md"), "# Personal Wiki\n", "utf8");
    const binding = await resolvePersonalWikiRoot(root, {
      runGit: async () => `${root}\n`,
    });

    const canonicalRoot = await realpath(root);
    expect(binding.wikiRoot).toBe(canonicalRoot);
    expect(binding.runtimeRoot).toBe(`${canonicalRoot}.selfopenwiki`);
    expect(binding.wikiRevision).toMatch(/^sha256:[a-f0-9]{64}$/u);
  });

  test("rejects a path whose Git repository root differs from the requested Wiki root", async () => {
    const root = path.resolve(".");
    await expect(
      resolvePersonalWikiRoot(root, {
        runGit: async () => "C:\\other-wiki\n",
      }),
    ).rejects.toMatchObject({ code: "personal_root_invalid" });
  });

  test("binds a real independent Git root and secures the sibling runtime", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-git-wiki-"));
    tempDirs.push(root);
    await writeFile(path.join(root, "quickstart.md"), "# Quickstart\n", "utf8");
    execFileSync("git", ["init", "--initial-branch=main"], {
      cwd: root,
      stdio: "ignore",
    });

    const binding = await resolvePersonalWikiRoot(root);

    expect(binding.wikiRoot).toBe(await realpath(root));
    expect(binding.runtimeRoot).toBe(`${binding.wikiRoot}.selfopenwiki`);
    expect(binding.wikiRevision).toMatch(/^sha256:[a-f0-9]{64}$/u);
    expect(await realpath(binding.runtimeRoot)).toBe(binding.runtimeRoot);
  });

  test("includes valid Claim sidecars in the personal Wiki revision", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-claims-root-"));
    tempDirs.push(root);
    const page = "guide.md";
    await writeFile(path.join(root, page), "# Guide\n", "utf8");
    await mkdir(path.join(root, ".claims"), { recursive: true });
    const pageHash = `sha256:${createHash("sha256").update("# Guide\n").digest("hex")}`;
    await writeFile(
      path.join(root, ".claims", "guide.json"),
      JSON.stringify({ claims: [], pageVersion: pageHash, schemaVersion: 1 }),
      "utf8",
    );
    const first = await resolvePersonalWikiRoot(root, {
      runGit: async () => `${root}\n`,
    });
    const firstRevision = first.wikiRevision;
    await writeFile(
      path.join(root, ".claims", "guide.json"),
      JSON.stringify({
        claims: [
          {
            evidence: [{ resource: "wiki://guide.md", version: "v1" }],
            id: "claim-1",
            statement: "The guide exists.",
          },
        ],
        pageVersion: pageHash,
        schemaVersion: 1,
      }),
      "utf8",
    );
    const second = await resolvePersonalWikiRoot(root, {
      runGit: async () => `${root}\n`,
    });
    expect(second.wikiRevision).not.toBe(firstRevision);
  });

  test("rejects the SelfOpenWiki repository as a personal root", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "selfopenwiki-owner-"));
    tempDirs.push(root);
    await writeFile(path.join(root, "index.md"), "# Owner\n", "utf8");
    await expect(
      resolvePersonalWikiRoot(root, {
        repositoryRoot: root,
        runGit: async () => `${root}\n`,
      }),
    ).rejects.toMatchObject({ code: "personal_root_invalid" });
  });

  test("rejects a personal root nested inside the SelfOpenWiki repository", async () => {
    const repositoryRoot = await mkdtemp(
      path.join(os.tmpdir(), "selfopenwiki-owner-parent-"),
    );
    const wikiRoot = path.join(repositoryRoot, "upstream", "openwiki");
    tempDirs.push(repositoryRoot);
    await mkdir(wikiRoot, { recursive: true });
    await writeFile(path.join(wikiRoot, "index.md"), "# Upstream\n", "utf8");
    await expect(
      resolvePersonalWikiRoot(wikiRoot, {
        repositoryRoot,
        runGit: async () => `${wikiRoot}\n`,
      }),
    ).rejects.toMatchObject({ code: "personal_root_invalid" });
  });
});
