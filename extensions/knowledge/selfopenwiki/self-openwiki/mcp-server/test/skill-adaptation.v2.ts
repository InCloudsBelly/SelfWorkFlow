import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, test } from "vitest";
import {
  PersonalSkillAdapter,
  PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT,
} from "../src/personal-skill-adapter.js";
import { computeSkillPackage } from "../src/skills.js";

describe("personal Skill adaptation", () => {
  test("does not bind a changed base Skill into an existing verified run", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "wiki-personal-base-"));
    try {
      const personal = path.join(root, "agent-skills", "self-openwiki");
      const base = path.join(root, "openwiki-skills", "kg-c7-project-wiki");
      await mkdir(personal, { recursive: true });
      await mkdir(base, { recursive: true });
      await writeFile(path.join(personal, "SKILL.md"), "# Personal rules\n");
      await writeFile(path.join(base, "SKILL.md"), "# Verified base\n");
      const expectedBasePackageHash = (await computeSkillPackage(base))
        .packageHash;
      const adapter = new PersonalSkillAdapter({
        skillPath: path.join(personal, "SKILL.md"),
        upstreamCommit: PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT,
        expectedBasePackageHash,
      });
      await expect(adapter.resolve([])).resolves.toMatchObject({
        skillIds: ["kg-c7-project-wiki", "self-openwiki"],
      });
      await writeFile(path.join(base, "SKILL.md"), "# Unverified base\n");
      await expect(adapter.resolve([])).rejects.toMatchObject({
        code: "skill_untrusted",
      });
    } finally {
      await rm(root, { force: true, recursive: true });
    }
  });

  test("documents the adapted six-stage lifecycle and external Wiki boundary", async () => {
    const skill = await readFile(
      path.resolve(
        import.meta.dirname,
        "..",
        "..",
        "agent-skills",
        "self-openwiki",
        "SKILL.md",
      ),
      "utf8",
    );
    const contract = await readFile(
      path.resolve(
        import.meta.dirname,
        "..",
        "..",
        "agent-skills",
        "self-openwiki",
        "references",
        "mcp-contract.md",
      ),
      "utf8",
    );
    for (const name of [
      "openwiki_begin",
      "openwiki_submit_plan",
      "openwiki_next_page",
      "openwiki_inspect_page_claims",
      "openwiki_submit_page",
      "openwiki_finish",
    ]) {
      expect(skill).toContain(name);
    }
    expect(skill).toContain("wikiRoot");
    expect(skill).toContain("C7");
    expect(skill).toContain("submodule");
    expect(contract).toContain("openwiki_begin");
    expect(contract).toContain("wikiRoot");
    expect(contract).toContain("个人 Wiki");
  });

  test("rejects a syntactically valid but unregistered Skill id", async () => {
    const adapter = new PersonalSkillAdapter({
      skillPath: path.resolve(
        import.meta.dirname,
        "..",
        "..",
        "agent-skills",
        "self-openwiki",
        "SKILL.md",
      ),
      upstreamCommit: PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT,
    });

    await expect(adapter.resolve(["unknown-skill"])).rejects.toMatchObject({
      code: "skill_untrusted",
    });
  });
});
