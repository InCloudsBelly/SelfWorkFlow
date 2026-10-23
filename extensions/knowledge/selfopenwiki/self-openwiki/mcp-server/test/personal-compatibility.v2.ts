import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, expect, test } from "vitest";
import {
  assertPersonalCompatibility,
  computeAdapterSetHash,
  computePersonalToolBindings,
  loadPersonalCompatibilityManifest,
} from "../src/personal-skill-adapter.js";
import { canonicalPersonalJson } from "../src/personal-wiki-lifecycle.js";
import { TOOL_NAMES } from "../src/contracts.js";
import { computeSkillPackage } from "../src/skills.js";

const repositoryRoot = path.resolve(import.meta.dirname, "../..");
const fixtureRoots: string[] = [];
afterEach(async () => {
  for (const root of fixtureRoots.splice(0)) {
    if (path.dirname(root) !== (await realpath(os.tmpdir())))
      throw new Error("Fixture cleanup outside temporary root.");
    await rm(root, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 100,
    });
  }
});

describe("personal OpenWiki compatibility binding", () => {
  test("uses verified module content independently of parent commits and staging", async () => {
    const fixtureRoot = await realpath(
      await mkdtemp(path.join(os.tmpdir(), "wiki-compatibility-")),
    );
    fixtureRoots.push(fixtureRoot);
    const parentRoot = path.join(fixtureRoot, "wiki-module");
    const copiedRepository = path.join(parentRoot, "self-openwiki");
    const openWikiRoot = path.join(parentRoot, ".work", "openwiki");
    const execute = promisify(execFile);
    const git = async (...args: string[]) =>
      (
        await execute("git", ["-C", fixtureRoot, ...args], {
          windowsHide: true,
        })
      ).stdout.trim();
    const commit = () =>
      git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "Fixture change",
      );
    const sourceHash = async () =>
      JSON.parse(
        (
          await execute(
            process.execPath,
            [
              path.join(parentRoot, "scripts", "parent-source-manifest.mjs"),
              parentRoot,
              "--module-content",
            ],
            { windowsHide: true },
          )
        ).stdout,
      ).hash as string;
    const hash = (bytes: Buffer) =>
      `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
    await mkdir(path.join(parentRoot, "scripts"), { recursive: true });
    await cp(
      path.resolve(repositoryRoot, "../scripts/parent-source-manifest.mjs"),
      path.join(parentRoot, "scripts", "parent-source-manifest.mjs"),
    );
    await cp(
      path.join(repositoryRoot, "mcp-server", "src"),
      path.join(copiedRepository, "mcp-server", "src"),
      { recursive: true },
    );
    await cp(
      path.join(repositoryRoot, "agent-skills"),
      path.join(copiedRepository, "agent-skills"),
      { recursive: true },
    );
    await cp(
      path.join(repositoryRoot, "mcp-server", "pnpm-lock.yaml"),
      path.join(copiedRepository, "mcp-server", "pnpm-lock.yaml"),
    );
    await mkdir(openWikiRoot, { recursive: true });
    const manifest = await loadPersonalCompatibilityManifest(repositoryRoot);
    await writeFile(
      path.join(openWikiRoot, "package.json"),
      JSON.stringify({ version: manifest.upstream.packageVersion }),
    );
    const marker = Buffer.from("Verified materialization fixture\n");
    await writeFile(
      path.join(openWikiRoot, ".selfopenwiki-materialization.json"),
      marker,
    );
    const readme = path.join(parentRoot, "README.md");
    await writeFile(readme, "Wiki module source\n");
    await git("init", "--initial-branch=main");
    await git("config", "core.autocrlf", "false");
    await git("config", "core.fsmonitor", "false");
    await git("add", ".");
    await commit();
    manifest.build.parentCommit = await git("rev-parse", "HEAD");
    manifest.build.parentSourceManifestHash = await sourceHash();
    manifest.build.adapterSetHash =
      await computeAdapterSetHash(copiedRepository);
    manifest.build.generatedMarkerHash = hash(marker);
    manifest.build.lockfileHash = hash(
      await readFile(
        path.join(copiedRepository, "mcp-server", "pnpm-lock.yaml"),
      ),
    );
    manifest.skill.packageHash = (
      await computeSkillPackage(
        path.join(copiedRepository, "agent-skills", "self-openwiki"),
      )
    ).packageHash;
    const expectedModuleHasherHash = hash(
      await readFile(
        path.join(parentRoot, "scripts", "parent-source-manifest.mjs"),
      ),
    );
    const verify = () =>
      assertPersonalCompatibility(
        manifest,
        manifest.upstream.commit,
        TOOL_NAMES,
        {
          expectedModuleHasherHash,
          openWikiRoot,
          repositoryRoot: copiedRepository,
        },
      );
    await expect(verify()).resolves.toBeUndefined();

    const helperPath = path.join(
      parentRoot,
      "scripts",
      "parent-source-manifest.mjs",
    );
    const trustedHelper = await readFile(helperPath);
    const executionMarker = path.join(
      fixtureRoot,
      "untrusted-helper-executed.txt",
    );
    await writeFile(
      helperPath,
      `import { writeFileSync } from "node:fs"; writeFileSync(${JSON.stringify(executionMarker)}, "unsafe"); process.stdout.write(${JSON.stringify(JSON.stringify({ hash: manifest.build.parentSourceManifestHash }))});`,
    );
    await expect(verify()).rejects.toThrow(
      "The parent source manifest could not be verified.",
    );
    await expect(readFile(executionMarker)).rejects.toMatchObject({
      code: "ENOENT",
    });
    await writeFile(helperPath, trustedHelper);
    await expect(verify()).resolves.toBeUndefined();

    await writeFile(
      path.join(fixtureRoot, "unrelated-workflow.txt"),
      "Outside the Wiki module source set\n",
    );
    expect(await sourceHash()).toBe(manifest.build.parentSourceManifestHash);
    await expect(verify()).resolves.toBeUndefined();
    await git("add", "unrelated-workflow.txt");
    await commit();
    expect(await sourceHash()).toBe(manifest.build.parentSourceManifestHash);
    await expect(verify()).resolves.toBeUndefined();

    await writeFile(readme, "Changed Wiki module source\n");
    await expect(verify()).rejects.toThrow(
      "Personal compatibility parent source manifest is stale.",
    );
    await git("add", "wiki-module/README.md");
    await writeFile(readme, "Wiki module source\n");
    await expect(verify()).resolves.toBeUndefined();
    await commit();
    await git("add", "wiki-module/README.md");
    await expect(verify()).resolves.toBeUndefined();

    await git("rm", "--cached", "wiki-module/README.md");
    await writeFile(
      path.join(fixtureRoot, ".gitignore"),
      "wiki-module/README.md\n",
    );
    expect(await sourceHash()).toBe(manifest.build.parentSourceManifestHash);
    await expect(verify()).resolves.toBeUndefined();
    await writeFile(readme, "Changed ignored Wiki module source\n");
    await expect(verify()).rejects.toThrow(
      "Personal compatibility parent source manifest is stale.",
    );
  }, 45_000);

  test("keeps a nested gitlink stable when only its parent index entry is removed", async () => {
    const fixtureRoot = await realpath(
      await mkdtemp(path.join(os.tmpdir(), "wiki-gitlink-")),
    );
    fixtureRoots.push(fixtureRoot);
    const moduleRoot = path.join(fixtureRoot, "wiki-module");
    const nestedRoot = path.join(moduleRoot, "upstream", "openwiki");
    await mkdir(path.join(moduleRoot, "scripts"), { recursive: true });
    await mkdir(nestedRoot, { recursive: true });
    await cp(
      path.resolve(repositoryRoot, "../scripts/parent-source-manifest.mjs"),
      path.join(moduleRoot, "scripts", "parent-source-manifest.mjs"),
    );
    await writeFile(path.join(nestedRoot, "package.json"), '{"version":"1"}\n');
    await writeFile(path.join(nestedRoot, ".gitignore"), "package.json\n");
    const execute = promisify(execFile);
    const git = async (root: string, ...args: string[]) =>
      (
        await execute("git", ["-C", root, ...args], { windowsHide: true })
      ).stdout.trim();
    const commit = (root: string) =>
      git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "Fixture",
      );
    await git(nestedRoot, "init", "--initial-branch=main");
    await git(nestedRoot, "add", ".gitignore");
    await git(nestedRoot, "add", "-f", "package.json");
    await commit(nestedRoot);
    await git(fixtureRoot, "init", "--initial-branch=main");
    await git(
      fixtureRoot,
      "add",
      "wiki-module/scripts",
      "wiki-module/upstream/openwiki",
    );
    await commit(fixtureRoot);
    const sourceHash = async () =>
      JSON.parse(
        (
          await execute(
            process.execPath,
            [
              path.join(moduleRoot, "scripts", "parent-source-manifest.mjs"),
              moduleRoot,
              "--module-content",
            ],
            { windowsHide: true },
          )
        ).stdout,
      ).hash as string;
    const before = await sourceHash();
    await git(fixtureRoot, "rm", "--cached", "wiki-module/upstream/openwiki");
    expect(await sourceHash()).toBe(before);
    await git(nestedRoot, "rm", "--cached", "package.json");
    expect(await sourceHash()).toBe(before);
    await writeFile(path.join(nestedRoot, "package.json"), '{"version":"2"}\n');
    expect(await sourceHash()).not.toBe(before);
  }, 30_000);

  test("binds the v2 upstream, personal Skill, six tools, and zero-patch policy", async () => {
    const manifest = JSON.parse(
      await readFile(
        path.join(
          repositoryRoot,
          "config",
          "personal-openwiki-compatibility.json",
        ),
        "utf8",
      ),
    ) as {
      schemaVersion: number;
      upstream: { commit: string; packageVersion: string; url: string };
      protocol: { adapted: string; official: string };
      skill: {
        id: string;
        packageHash: string;
        path: string;
        version: string;
      };
      toolBindings: Record<string, unknown>;
      discoveryOrder: string[];
      build: Record<string, string>;
    };
    const upstreamPackage = JSON.parse(
      await readFile(
        path.resolve(repositoryRoot, "..", ".work", "openwiki", "package.json"),
        "utf8",
      ),
    ) as { version: string };

    expect(manifest.schemaVersion).toBe(2);
    expect(manifest.upstream).toEqual({
      commit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
      packageVersion: upstreamPackage.version,
      url: "https://github.com/langchain-ai/openwiki.git",
    });
    expect(manifest.protocol).toEqual({
      adapted: "selfopenwiki:personal-openwiki-v1",
      official: "openwiki-repository-v0.5",
    });
    expect(manifest.skill).toMatchObject({
      id: "self-openwiki",
      path: "self-openwiki/agent-skills/self-openwiki",
      version: "2.0.0",
    });
    expect(manifest.skill.packageHash).toMatch(/^sha256:[a-f0-9]{64}$/u);
    expect(Object.keys(manifest.toolBindings).sort()).toEqual(
      [
        "openwiki_begin",
        "openwiki_submit_plan",
        "openwiki_next_page",
        "openwiki_inspect_page_claims",
        "openwiki_submit_page",
        "openwiki_finish",
      ].sort(),
    );
    expect(manifest.discoveryOrder).toEqual([
      "openwiki_status",
      "openwiki_read",
      "openwiki_begin",
      "openwiki_submit_plan",
      "openwiki_next_page",
      "openwiki_inspect_page_claims",
      "openwiki_submit_page",
      "openwiki_finish",
      "openwiki_setup",
      "openwiki_prepare_sources",
      "openwiki_list_skills",
      "openwiki_query",
      "openwiki_update",
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
      "openwiki_set_default_model",
    ]);
    expect(manifest.build.parentCommit).toMatch(/^[a-f0-9]{40}$/u);
    for (const [key, hash] of Object.entries(manifest.build)) {
      if (key === "parentCommit") continue;
      expect(hash).toMatch(/^sha256:[a-f0-9]{64}$/u);
    }
  });

  test("stores the compatibility binding as sorted canonical JSON", async () => {
    const manifestPath = path.join(
      repositoryRoot,
      "config",
      "personal-openwiki-compatibility.json",
    );
    const bytes = await readFile(manifestPath, "utf8");
    const manifest = JSON.parse(bytes) as unknown;
    expect(bytes).toBe(`${canonicalPersonalJson(manifest)}\n`);
  });

  test("matches the compiled six-tool binding generator", async () => {
    const manifest = JSON.parse(
      await readFile(
        path.join(
          repositoryRoot,
          "config",
          "personal-openwiki-compatibility.json",
        ),
        "utf8",
      ),
    ) as { toolBindings: unknown };
    expect(manifest.toolBindings).toEqual(computePersonalToolBindings());
  });

  test("rejects a manifest that remaps a tool to another valid adapter anchor", async () => {
    const manifest = await loadPersonalCompatibilityManifest(repositoryRoot);
    const tampered = structuredClone(manifest);
    tampered.toolBindings.openwiki_begin = {
      ...tampered.toolBindings.openwiki_begin,
      implementation: "mcp-server/src/official-lifecycle-adapter.ts#finish",
    };
    await expect(
      assertPersonalCompatibility(
        tampered,
        manifest.upstream.commit,
        TOOL_NAMES,
        {
          expectedModuleHasherHash: `sha256:${createHash("sha256")
            .update(
              await readFile(
                path.resolve(
                  repositoryRoot,
                  "../scripts/parent-source-manifest.mjs",
                ),
              ),
            )
            .digest("hex")}`,
          openWikiRoot: path.resolve(repositoryRoot, "..", ".work", "openwiki"),
          repositoryRoot,
        },
      ),
    ).rejects.toThrow(
      "Personal compatibility implementation mapping is stale:",
    );
  });
});
