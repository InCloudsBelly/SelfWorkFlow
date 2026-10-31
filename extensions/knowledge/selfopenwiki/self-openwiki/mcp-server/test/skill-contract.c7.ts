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
          "sha256:60bc4644623b373155ecc53086ef6b00249b8d5f25f690a9070ce56c7df52b26",
        skills: [
          expect.objectContaining({
            packageHash:
              "sha256:47f2c3b99da439d40c7f4062eb17b8c802403fd19dd1ca7c87455aa9c715df3b",
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
