import { createHash } from "node:crypto";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { WikiPublisher } from "../src/publish.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type SelectedC7Skill,
  type SelectedC7Skills,
} from "../src/skills.js";
const tempDirs: string[] = [];
afterEach(async () => {
  await Promise.all(
    tempDirs
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});
describe("stable personal Wiki publication", () => {
  test("retries a v4 upgrade with a durable but uninstalled plan scratch file", async () => {
    const fixture = await createFixture({ faultPoint: "after_plan" });
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);
    const oldPlan = externalPlan(before.rootHash, after.rootHash);
    const input = {
      before,
      after,
      candidateWikiPath: fixture.candidateWiki,
      plan: oldPlan,
    };
    await expect(
      fixture.publisher.publishExternal(input),
    ).rejects.toMatchObject({ code: "publish_failed" });
    await writeFile(
      path.join(
        fixture.runtimeDir,
        "recovery",
        oldPlan.runId,
        "plan.json.12345678-1234-1234-1234-123456789012.tmp",
      ),
      canonicalBytes({ ...oldPlan, version: 5 }),
    );
    const retry = new WikiPublisher({
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: { securePrivatePath: async () => undefined },
    });
    await expect(
      retry.publishExternal({ ...input, plan: { ...oldPlan, version: 5 } }),
    ).resolves.toMatchObject({ after });
  });

  test.each(
    [false, true].flatMap((directoryBefore) =>
      [false, true].map((rollback) => ({ directoryBefore, rollback })),
    ),
  )(
    "supports a required file/directory conversion (directory before: $directoryBefore, rollback: $rollback)",
    async ({ directoryBefore, rollback }) => {
      const fixture = await createFixture({
        faultPoint: rollback ? "after_install" : undefined,
      });
      for (const [root, directory] of [
        [fixture.formalWiki, directoryBefore],
        [fixture.candidateWiki, !directoryBefore],
      ] as const) {
        const relative = directory ? "converted.md/nested.md" : "converted.md";
        await mkdir(path.dirname(path.join(root, relative)), {
          recursive: true,
        });
        await writeFile(
          path.join(root, relative),
          page(`# Converted ${directory}\n`),
        );
      }
      const before = await snapshotMarkdownTree(fixture.formalWiki);
      const after = await snapshotMarkdownTree(fixture.candidateWiki);
      const publication = fixture.publisher.publishExternal({
        before,
        after,
        candidateWikiPath: fixture.candidateWiki,
        plan: { ...externalPlan(before.rootHash, after.rootHash), version: 5 },
      });
      if (rollback)
        await expect(publication).rejects.toMatchObject({
          code: "publish_failed",
        });
      else await expect(publication).resolves.toMatchObject({ after });
      expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(
        rollback ? before : after,
      );
    },
  );

  test("rolls back an already installed unmarked v5 tree when its retry fails", async () => {
    const fixture = await createFixture();
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);
    const plan = {
      ...externalPlan(before.rootHash, after.rootHash),
      version: 5,
    };
    const input = {
      before,
      after,
      candidateWikiPath: fixture.candidateWiki,
      plan,
    };
    const publisher = new WikiPublisher({
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: { securePrivatePath: async () => undefined },
      fault: (point) => {
        if (point === "after_stable_mode") throw new Error("retained mode");
      },
    });
    await expect(publisher.publishExternal(input)).rejects.toMatchObject({
      code: "publish_failed",
    });
    for (const file of after.files)
      await writeFile(
        path.join(fixture.formalWiki, file.relativePath),
        await readFile(path.join(fixture.candidateWiki, file.relativePath)),
      );
    const retry = new WikiPublisher({
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: { securePrivatePath: async () => undefined },
      fault: (point) => {
        if (point === "after_install") throw new Error("retry failure");
      },
    });
    await expect(retry.publishExternal(input)).rejects.toMatchObject({
      code: "publish_failed",
    });
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(before);
  });

  test.each([
    "after_displace",
    "after_install",
    "before_marker_rename",
  ] as const)(
    "rolls stable v5 content back without moving Git or Claims (%s)",
    async (faultPoint) => {
      const fixture = await createFixture({ faultPoint });
      const protectedFiles = {
        ".git/HEAD": "ref: refs/heads/main\n",
        ".claims/quickstart.json": "claim bytes\n",
        ".gitignore": "*.tmp\n",
        ".gitattributes": "*.md -text\n",
      };
      for (const [relative, bytes] of Object.entries(protectedFiles)) {
        await mkdir(path.dirname(path.join(fixture.formalWiki, relative)), {
          recursive: true,
        });
        await writeFile(path.join(fixture.formalWiki, relative), bytes);
      }
      const before = await snapshotMarkdownTree(fixture.formalWiki);
      const after = await snapshotMarkdownTree(fixture.candidateWiki);
      await expect(
        fixture.publisher.publishExternal({
          before,
          after,
          candidateWikiPath: fixture.candidateWiki,
          plan: {
            ...externalPlan(before.rootHash, after.rootHash),
            version: 5,
          },
        }),
      ).rejects.toMatchObject({ code: "publish_failed" });
      expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(before);
      for (const [relative, bytes] of Object.entries(protectedFiles))
        expect(
          await readFile(path.join(fixture.formalWiki, relative), "utf8"),
        ).toBe(bytes);
    },
  );

  test("rejects an edit introduced during staging before the final target check", async () => {
    const fixture = await createFixture();
    await rm(path.join(fixture.candidateWiki, "new.md"));
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);
    const edited = page("# External edit\n");
    const publisher = new WikiPublisher({
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: {
        securePrivatePath: async ({ targetPath }) => {
          if (path.basename(targetPath) === "apply.tmp")
            await writeFile(
              path.join(fixture.formalWiki, "quickstart.md"),
              edited,
            );
        },
      },
    });
    const plan = {
      ...externalPlan(before.rootHash, after.rootHash),
      version: 5,
    };
    await expect(
      publisher.publishExternal({
        before,
        after,
        candidateWikiPath: fixture.candidateWiki,
        plan,
      }),
    ).rejects.toMatchObject({ code: "wiki_changed" });
    expect(
      await readFile(path.join(fixture.formalWiki, "quickstart.md"), "utf8"),
    ).toBe(edited);
    await expect(
      access(
        path.join(fixture.runtimeDir, "recovery", plan.runId, "commit.marker"),
      ),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });

  test("retains partial publication and a detected foreign edit when rollback is unsafe", async () => {
    const fixture = await createFixture();
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);
    const edited = page("# External edit after first change\n");
    const plan = {
      ...externalPlan(before.rootHash, after.rootHash),
      version: 5,
    };
    const publisher = new WikiPublisher({
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: { securePrivatePath: async () => undefined },
      fault: async (point) => {
        if (point === "after_displace") {
          await writeFile(
            path.join(fixture.formalWiki, "quickstart.md"),
            edited,
          );
          throw new Error("interrupted with foreign edit");
        }
      },
    });
    await expect(
      publisher.publishExternal({
        before,
        after,
        candidateWikiPath: fixture.candidateWiki,
        plan,
      }),
    ).rejects.toMatchObject({ code: "restore_failed" });
    expect(
      await readFile(path.join(fixture.formalWiki, "quickstart.md"), "utf8"),
    ).toBe(edited);
    await expect(
      access(path.join(fixture.formalWiki, "new.md")),
    ).resolves.toBeUndefined();
    await expect(
      access(
        path.join(
          fixture.runtimeDir,
          "recovery",
          plan.runId,
          "stable-root.json",
        ),
      ),
    ).resolves.toBeUndefined();
    await expect(
      access(
        path.join(fixture.runtimeDir, "recovery", plan.runId, "commit.marker"),
      ),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });

  test.each([
    "mode-without-plan",
    "v4-with-mode",
    "mixed-without-mode",
    "foreign-page",
    "missing-common",
    "wrong-mode",
    "unknown-entry",
    "replaced-root",
    "linked-stage",
  ] as const)(
    "rejects invalid stable recovery without changing formal content (%s)",
    async (corruption) => {
      const fixture = await createFixture();
      const before = await snapshotMarkdownTree(fixture.formalWiki);
      const after = await snapshotMarkdownTree(fixture.candidateWiki);
      const plan = {
        ...externalPlan(before.rootHash, after.rootHash),
        version: 5,
      };
      const input = {
        before,
        after,
        candidateWikiPath: fixture.candidateWiki,
        plan,
      };
      const publisher = new WikiPublisher({
        formalWikiPath: fixture.formalWiki,
        runtimeDir: fixture.runtimeDir,
        security: { securePrivatePath: async () => undefined },
        fault: (point) => {
          if (
            point ===
            (corruption === "mixed-without-mode"
              ? "after_plan"
              : "after_stable_mode")
          )
            throw new Error("retained journal");
        },
      });
      await expect(publisher.publishExternal(input)).rejects.toMatchObject({
        code: "publish_failed",
      });
      const journal = path.join(fixture.runtimeDir, "recovery", plan.runId);
      if (corruption === "mode-without-plan")
        await rm(path.join(journal, "plan.json"));
      if (corruption === "v4-with-mode")
        await writeFile(
          path.join(journal, "plan.json"),
          canonicalBytes({ ...plan, version: 4 }),
        );
      if (corruption === "mixed-without-mode")
        await writeFile(
          path.join(fixture.formalWiki, "new.md"),
          await readFile(path.join(fixture.candidateWiki, "new.md")),
        );
      if (corruption === "foreign-page")
        await writeFile(
          path.join(fixture.formalWiki, "foreign.md"),
          page("# Foreign\n"),
        );
      if (corruption === "missing-common")
        await rm(path.join(fixture.formalWiki, "quickstart.md"));
      if (corruption === "wrong-mode") {
        const mode = JSON.parse(
          await readFile(path.join(journal, "stable-root.json"), "utf8"),
        );
        await writeFile(
          path.join(journal, "stable-root.json"),
          JSON.stringify({ ...mode, planHash: hash("0") }),
        );
      }
      if (corruption === "unknown-entry")
        await writeFile(path.join(journal, "foreign.tmp"), "untrusted");
      if (corruption === "replaced-root") {
        await rename(fixture.formalWiki, `${fixture.formalWiki}.original`);
        await mkdir(fixture.formalWiki);
        await writeFile(
          path.join(fixture.formalWiki, "quickstart.md"),
          await readFile(path.join(journal, "before", "quickstart.md")),
        );
      }
      if (corruption === "linked-stage")
        await symlink(
          fixture.candidateWiki,
          path.join(journal, "apply.tmp"),
          "junction",
        );
      const unchanged = await snapshotMarkdownTree(fixture.formalWiki);
      await expect(
        fixture.publisher.publishExternal(input),
      ).rejects.toMatchObject({
        code: [
          "mixed-without-mode",
          "foreign-page",
          "missing-common",
          "replaced-root",
        ].includes(corruption)
          ? "wiki_changed"
          : "restore_required",
      });
      expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(unchanged);
      await expect(
        access(path.join(journal, "commit.marker")),
      ).rejects.toMatchObject({ code: "ENOENT" });
    },
  );

  test.each([
    "before",
    "after_displace",
    "after_install",
    "committed",
  ] as const)(
    "accepts the same approved v4 journal from v5 recovery (%s)",
    async (layout) => {
      const fixture = await createFixture({
        faultPoint: layout === "committed" ? undefined : "after_plan",
      });
      const before = await snapshotMarkdownTree(fixture.formalWiki);
      const after = await snapshotMarkdownTree(fixture.candidateWiki);
      const plan = externalPlan(before.rootHash, after.rootHash);
      const input = {
        before,
        after,
        candidateWikiPath: fixture.candidateWiki,
        plan,
      };
      if (layout === "committed")
        await fixture.publisher.publishExternal(input);
      else
        await expect(
          fixture.publisher.publishExternal(input),
        ).rejects.toMatchObject({ code: "publish_failed" });
      const journal = path.join(fixture.runtimeDir, "recovery", plan.runId);
      if (layout === "after_displace" || layout === "after_install") {
        await rename(fixture.formalWiki, path.join(journal, "displaced"));
        if (layout === "after_install")
          await rename(path.join(journal, "publish"), fixture.formalWiki);
      }
      const publisher = new WikiPublisher({
        formalWikiPath: fixture.formalWiki,
        runtimeDir: fixture.runtimeDir,
        security: { securePrivatePath: async () => undefined },
      });
      const result = await publisher.publishExternal({
        ...input,
        plan: { ...plan, version: 5 },
      });
      expect(result.after).toEqual(after);
      expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(after);
      expect(
        JSON.parse(await readFile(path.join(journal, "plan.json"), "utf8"))
          .version,
      ).toBe(layout === "before" ? 5 : 4);
      if (layout === "before")
        await expect(
          access(path.join(journal, "stable-root.json")),
        ).resolves.toBeUndefined();
      else
        await expect(
          access(path.join(journal, "stable-root.json")),
        ).rejects.toMatchObject({ code: "ENOENT" });
    },
  );
});

async function createFixture(
  options: {
    faultPoint?:
      | "after_displace"
      | "after_external_init_mkdir"
      | "after_external_init_plan"
      | "after_external_init_trees"
      | "after_install"
      | "after_marker"
      | "after_plan"
      | "before_marker_rename";
  } = {},
) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-publish-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWiki = path.join(runtimeDir, "wiki");
  const candidateWiki = path.join(root, "candidate");
  await Promise.all([
    mkdir(formalWiki, { recursive: true }),
    mkdir(candidateWiki, { recursive: true }),
  ]);
  await writeFile(
    path.join(formalWiki, "quickstart.md"),
    page("# Before\n"),
    "utf8",
  );
  await writeFile(
    path.join(candidateWiki, "quickstart.md"),
    page("# After\n"),
    "utf8",
  );
  await writeFile(path.join(candidateWiki, "new.md"), page("# New\n"), "utf8");
  const fault = vi.fn((point: string) => {
    if (point === options.faultPoint) throw new Error(`fault:${point}`);
  });
  return {
    candidateWiki,
    formalWiki,
    publisher: new WikiPublisher({
      fault,
      formalWikiPath: formalWiki,
      runtimeDir,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
    }),
    runtimeDir,
  };
}

function selectedSkills(): SelectedC7Skills {
  const bytes = Buffer.from("# Base\n", "utf8");
  const files = [
    {
      bytes,
      hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
      relativePath: "SKILL.md",
      size: bytes.length,
    },
  ];
  const skill: SelectedC7Skill = {
    category: "base",
    description: "Base",
    files,
    id: "kg-c7-project-wiki",
    loadOrder: "base_always_first",
    packageHash: computeSkillPackageHash(files),
    title: "KG_C7_Project_Wiki",
    verified: true,
  };
  return {
    aggregateHash: aggregateSkillHash([skill]),
    skills: [skill],
  };
}

function page(body: string): string {
  return `---\ntype: Guide\n---\n\n${body}`;
}

function externalPlan(beforeRootHash: string, candidateRootHash: string) {
  const orderedSkillPackages = selectedSkills().skills.map(
    ({ id, packageHash }) => ({ id, packageHash }),
  );
  const identity = {
    bindingHash: hash("a"),
    generation: 1,
    reviewReceiptHash: hash("b"),
    transactionId: "external-12345678",
  };
  return {
    version: 4 as const,
    executionMode: "external_agent" as const,
    runId: independentExternalRunId(identity),
    transactionId: identity.transactionId,
    generation: identity.generation,
    bindingHash: identity.bindingHash,
    inputHash: hash("c"),
    beforeRootHash,
    candidateRootHash,
    requestPackageHash: hash("d"),
    candidateReceiptHash: hash("e"),
    reviewPackageHash: hash("f"),
    reviewReceiptHash: identity.reviewReceiptHash,
    sourceManifestHash: null,
    sourceTreeHash: null,
    skillAggregateHash: selectedSkills().aggregateHash,
    orderedSkillPackages,
    hardRulePackageHash: hash("1"),
    candidateResultContractSchemaHash: hash("2"),
    reviewResultContractSchemaHash: hash("3"),
    confirmedWikiPathsHash: hash("4"),
    reviewCompletedBeforePublish: true as const,
  };
}

function independentExternalRunId(input: {
  bindingHash: string;
  generation: number;
  reviewReceiptHash: string;
  transactionId: string;
}): string {
  return `run-external-${createHash("sha256")
    .update("kg-c7:external-publish-run:v1\0", "utf8")
    .update(stableJson(input), "utf8")
    .digest("hex")}`;
}

function canonicalBytes(value: unknown): Buffer {
  return Buffer.from(`${stableJson(value)}\n`, "utf8");
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}
