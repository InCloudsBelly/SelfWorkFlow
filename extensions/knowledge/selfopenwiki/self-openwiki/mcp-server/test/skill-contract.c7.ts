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
          "sha256:1ac09de491ab8696ce9ad948c77d1ada21d9f165d21826533892c489e281b806",
        skills: [
          expect.objectContaining({
            packageHash:
              "sha256:6d8a3287f6f0d55e6f549a4aeabf50e81fa9320755cfb6e81fb5a40c7aeadd06",
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
