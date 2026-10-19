import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, test } from "vitest";
import {
  assertPersonalCompatibility,
  computePersonalToolBindings,
  loadPersonalCompatibilityManifest,
} from "../src/personal-skill-adapter.js";
import { canonicalPersonalJson } from "../src/personal-wiki-lifecycle.js";
import { TOOL_NAMES } from "../src/contracts.js";

const repositoryRoot = path.resolve(import.meta.dirname, "../..");

describe("personal OpenWiki compatibility binding", () => {
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
          openWikiRoot: path.resolve(repositoryRoot, "..", ".work", "openwiki"),
          repositoryRoot,
        },
      ),
    ).rejects.toThrow(
      "Personal compatibility implementation mapping is stale:",
    );
  });
});
