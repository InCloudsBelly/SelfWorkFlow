import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { composeSkillContract, loadC7SkillRegistry } from "../src/skills.js";

const packageRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
);

describe("repository C7 Skill contract", () => {
  test("loads only the hash-trusted base package and identifies its fixed order", async () => {
    const registry = await loadC7SkillRegistry(
      path.join(packageRoot, "config", "trusted-skills.json"),
      path.join(packageRoot, "openwiki-skills"),
    );

    expect(registry.list()).toEqual([
      expect.objectContaining({
        category: "base",
        id: "kg-c7-project-wiki",
        loadOrder: "base_always_first",
        verified: true,
      }),
    ]);
    expect(registry.select([]).skills).toHaveLength(1);
    expect(registry.select([])).toEqual(
      expect.objectContaining({
        aggregateHash:
          "sha256:92860b3a50bcb77821b72a6b394bd4999f642b0f498cc001d198c724540fb891",
        skills: [
          expect.objectContaining({
            packageHash:
              "sha256:4ceb69372f4caadcb1b41c16738d09c5c29dae06f6f0fa8d8ee5211d1ee2c8ba",
          }),
        ],
      }),
    );
  });

  test("states C7 injection scope without hiding OpenWiki bundled Skills", async () => {
    const registry = await loadC7SkillRegistry(
      path.join(packageRoot, "config", "trusted-skills.json"),
      path.join(packageRoot, "openwiki-skills"),
    );
    const contract = composeSkillContract(registry.select([]).skills);

    expect(contract).toContain("KG_C7_Project_Wiki base policy");
    expect(contract).toContain(
      "OpenWiki upstream bundled Skills remain visible",
    );
    expect(contract).toContain("当前源码、配置和测试优先于旧文档");
  });
});
