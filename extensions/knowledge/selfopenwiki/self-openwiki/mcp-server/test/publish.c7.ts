import { createHash } from "node:crypto";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  inspectPersistedReviewAttention,
  WikiPublisher,
} from "../src/publish.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type SelectedC7Skill,
  type SelectedC7Skills,
} from "../src/skills.js";

const tempDirs: string[] = [];
const model = { model: "gpt-5.6-sol", reasoningEffort: "xhigh" as const };

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("crash-recoverable Wiki publication", () => {
  test.each(["after_plan", "after_install"] as const)(
    "retains the filesystem cause and before tree when publication fails at %s",
    async (faultPoint) => {
      const fixture = await createFixture();
      const cause = Object.assign(new Error("token=private-error-canary"), {
        code: "EPERM",
        syscall: "rename",
      });
      const publisher = new WikiPublisher({
        formalWikiPath: fixture.formalWiki,
        runtimeDir: fixture.runtimeDir,
        security: { securePrivatePath: async () => undefined },
        fault(point) {
          if (point === faultPoint) throw cause;
        },
      });
      const before = await snapshotMarkdownTree(fixture.formalWiki);
      const after = await snapshotMarkdownTree(fixture.candidateWiki);
      await expect(
        publisher.publishExternal({
          before,
          after,
          candidateWikiPath: fixture.candidateWiki,
          plan: externalPlan(before.rootHash, after.rootHash),
        }),
      ).rejects.toMatchObject({ code: "publish_failed", cause });
      expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(before);
    },
  );

  test.each([undefined, "after_install" as const])(
    "preserves root Git policy bytes during publication and rollback (%s)",
    async (faultPoint) => {
      const fixture = await createFixture({ faultPoint });
      const policies = {
        ".gitignore": "*.tmp\r\n",
        ".gitattributes": "*.md -text\n*.json -text\n",
      };
      for (const [name, bytes] of Object.entries(policies)) {
        await writeFile(path.join(fixture.formalWiki, name), bytes);
      }
      const before = await snapshotMarkdownTree(fixture.formalWiki);
      const after = await snapshotMarkdownTree(fixture.candidateWiki);
      const publication = fixture.publisher.publishExternal({
        after,
        before,
        candidateWikiPath: fixture.candidateWiki,
        plan: externalPlan(before.rootHash, after.rootHash),
      });
      if (faultPoint) {
        await expect(publication).rejects.toMatchObject({
          code: "publish_failed",
        });
      } else {
        await expect(publication).resolves.toMatchObject({ after });
      }
      for (const [name, bytes] of Object.entries(policies)) {
        await expect(
          readFile(path.join(fixture.formalWiki, name), "utf8"),
        ).resolves.toBe(bytes);
      }
      await expect(snapshotMarkdownTree(fixture.formalWiki)).resolves.toEqual(
        faultPoint ? before : after,
      );
    },
  );

  test("preserves Git metadata when publishing a Git-backed Wiki root", async () => {
    const fixture = await createFixture();
    const gitDirectory = path.join(fixture.formalWiki, ".git");
    await mkdir(gitDirectory, { recursive: true });
    await writeFile(
      path.join(gitDirectory, "HEAD"),
      "ref: refs/heads/main\n",
      "utf8",
    );
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);

    await fixture.publisher.publishExternal({
      after,
      before,
      candidateWikiPath: fixture.candidateWiki,
      plan: externalPlan(before.rootHash, after.rootHash),
    });

    await expect(
      readFile(path.join(fixture.formalWiki, ".git", "HEAD"), "utf8"),
    ).resolves.toBe("ref: refs/heads/main\n");
  });

  test("preserves personal Claim sidecars when publishing a Wiki root", async () => {
    const fixture = await createFixture();
    const claimsPath = path.join(
      fixture.formalWiki,
      ".claims",
      "quickstart.json",
    );
    const claims =
      '{"claims":[],"pageVersion":"sha256:test","schemaVersion":1}\n';
    await mkdir(path.dirname(claimsPath), { recursive: true });
    await writeFile(claimsPath, claims, "utf8");
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);

    await fixture.publisher.publishExternal({
      after,
      before,
      candidateWikiPath: fixture.candidateWiki,
      plan: externalPlan(before.rootHash, after.rootHash),
    });

    await expect(readFile(claimsPath, "utf8")).resolves.toBe(claims);
  });

  test("restores personal Claim sidecars when external publication fails after install", async () => {
    const fixture = await createFixture({ faultPoint: "after_install" });
    const claimsPath = path.join(
      fixture.formalWiki,
      ".claims",
      "quickstart.json",
    );
    const claims = '{"claims":[{"id":"keep-me"}],"schemaVersion":1}\n';
    await mkdir(path.dirname(claimsPath), { recursive: true });
    await writeFile(claimsPath, claims, "utf8");
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);

    await expect(
      fixture.publisher.publishExternal({
        after,
        before,
        candidateWikiPath: fixture.candidateWiki,
        plan: externalPlan(before.rootHash, after.rootHash),
      }),
    ).rejects.toMatchObject({ code: "publish_failed" });

    await expect(readFile(claimsPath, "utf8")).resolves.toBe(claims);
  });

  test("restores Git metadata when publication fails after install", async () => {
    const fixture = await createFixture({ faultPoint: "after_install" });
    const gitDirectory = path.join(fixture.formalWiki, ".git");
    await mkdir(gitDirectory, { recursive: true });
    await writeFile(
      path.join(gitDirectory, "HEAD"),
      "ref: refs/heads/main\n",
      "utf8",
    );
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);

    await expect(
      fixture.publisher.publishExternal({
        after,
        before,
        candidateWikiPath: fixture.candidateWiki,
        plan: externalPlan(before.rootHash, after.rootHash),
      }),
    ).rejects.toMatchObject({ code: "publish_failed" });

    await expect(
      readFile(path.join(fixture.formalWiki, ".git", "HEAD"), "utf8"),
    ).resolves.toBe("ref: refs/heads/main\n");
    await expect(snapshotMarkdownTree(fixture.formalWiki)).resolves.toEqual(
      before,
    );
  });

  test("publishes one strict external-Agent version-4 plan with deterministic full-digest identity", async () => {
    const fixture = await createFixture();
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);
    const plan = externalPlan(before.rootHash, after.rootHash);

    const result = await fixture.publisher.publishExternal({
      after,
      before,
      candidateWikiPath: fixture.candidateWiki,
      plan,
    });

    expect(result.runId).toBe(plan.runId);
    expect(result.generation).toBe(1);
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(after);
    const journal = path.join(fixture.runtimeDir, "recovery", plan.runId);
    const persistedBytes = await readFile(path.join(journal, "plan.json"));
    expect(persistedBytes).toEqual(canonicalBytes(plan));
    expect(JSON.parse(persistedBytes.toString("utf8"))).toEqual(plan);
    expect(persistedBytes.toString("utf8")).not.toMatch(
      /model|reviewPending|reviewInstruction|reviewSkills/iu,
    );
    const marker = JSON.parse(
      await readFile(path.join(journal, "commit.marker"), "utf8"),
    ) as Record<string, unknown>;
    expect(marker).toEqual(
      expect.objectContaining({
        afterRootHash: after.rootHash,
        planHash: sha256(persistedBytes),
        runId: plan.runId,
      }),
    );
  });

  test("rejects an external plan with an extra field before creating a journal", async () => {
    const fixture = await createFixture();
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);
    const plan = {
      ...externalPlan(before.rootHash, after.rootHash),
      model,
    };

    await expect(
      fixture.publisher.publishExternal({
        after,
        before,
        candidateWikiPath: fixture.candidateWiki,
        plan,
      }),
    ).rejects.toMatchObject({ code: "publish_failed" });
    await expect(
      access(path.join(fixture.runtimeDir, "recovery", plan.runId)),
    ).rejects.toBeDefined();
  });

  test("freezes the external publication run identity domain and full digest", () => {
    const identity = {
      bindingHash: hash("a"),
      generation: 1,
      reviewReceiptHash: hash("b"),
      transactionId: "external-12345678",
    };
    expect(independentExternalRunId(identity)).toBe(
      "run-external-ec42061de48bfc4c9ac7709b4f69d476590a9e24f58418b1602f3eebeb35112b",
    );
    expect(independentExternalRunId(identity)).toMatch(
      /^run-external-[a-f0-9]{64}$/u,
    );
  });

  test.each([
    "after_external_init_mkdir",
    "after_external_init_trees",
    "after_external_init_plan",
  ] as const)(
    "rebuilds one isolated external journal after %s process loss",
    async (faultPoint) => {
      const fixture = await createFixture({ faultPoint });
      const before = await snapshotMarkdownTree(fixture.formalWiki);
      const after = await snapshotMarkdownTree(fixture.candidateWiki);
      const plan = externalPlan(before.rootHash, after.rootHash);
      const input = {
        after,
        before,
        candidateWikiPath: fixture.candidateWiki,
        plan,
      };

      await expect(
        fixture.publisher.publishExternal(input),
      ).rejects.toMatchObject({ code: "publish_failed" });
      expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(before);
      const initializingPath = path.join(
        fixture.runtimeDir,
        "recovery",
        `${plan.runId}.initializing`,
      );
      if (faultPoint === "after_external_init_trees") {
        await writeFile(
          path.join(initializingPath, "after", "quickstart.md"),
          "truncated",
          "utf8",
        );
      } else if (faultPoint === "after_external_init_plan") {
        await writeFile(
          path.join(initializingPath, "plan.json.tmp"),
          "partial",
          "utf8",
        );
      } else {
        const quarantinePath = `${initializingPath}.cleanup`;
        await rename(initializingPath, quarantinePath);
        await writeFile(
          path.join(quarantinePath, "partial.tmp"),
          "partial",
          "utf8",
        );
      }
      expect(await readdir(path.join(fixture.runtimeDir, "recovery"))).toEqual([
        faultPoint === "after_external_init_mkdir"
          ? `${plan.runId}.initializing.cleanup`
          : `${plan.runId}.initializing`,
      ]);

      const restarted = new WikiPublisher({
        formalWikiPath: fixture.formalWiki,
        runtimeDir: fixture.runtimeDir,
        security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
      });
      await expect(restarted.publishExternal(input)).resolves.toMatchObject({
        runId: plan.runId,
      });
      expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(after);
      expect(await readdir(path.join(fixture.runtimeDir, "recovery"))).toEqual([
        plan.runId,
      ]);
    },
  );

  test("takes over the same external journal after a crash immediately after its plan", async () => {
    const fixture = await createFixture({ faultPoint: "after_plan" });
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);
    const plan = externalPlan(before.rootHash, after.rootHash);
    const input = {
      after,
      before,
      candidateWikiPath: fixture.candidateWiki,
      plan,
    };

    await expect(
      fixture.publisher.publishExternal(input),
    ).rejects.toMatchObject({ code: "publish_failed" });
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(before);
    const restarted = new WikiPublisher({
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
    });
    const result = await restarted.publishExternal(input);

    expect(result.runId).toBe(plan.runId);
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(after);
    expect(await readdir(path.join(fixture.runtimeDir, "recovery"))).toEqual([
      plan.runId,
    ]);
  });

  test("deterministically reconstructs a missing external plan from an otherwise exact journal", async () => {
    const fixture = await createFixture({ faultPoint: "after_plan" });
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    const after = await snapshotMarkdownTree(fixture.candidateWiki);
    const plan = externalPlan(before.rootHash, after.rootHash);
    const input = {
      after,
      before,
      candidateWikiPath: fixture.candidateWiki,
      plan,
    };

    await expect(
      fixture.publisher.publishExternal(input),
    ).rejects.toMatchObject({ code: "publish_failed" });
    const planPath = path.join(
      fixture.runtimeDir,
      "recovery",
      plan.runId,
      "plan.json",
    );
    await rm(planPath);
    const restarted = new WikiPublisher({
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
    });

    await expect(restarted.publishExternal(input)).resolves.toMatchObject({
      runId: plan.runId,
    });
    expect(await readFile(planPath)).toEqual(canonicalBytes(plan));
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(after);
  });

  test("publishes an exact candidate with a bound plan and commit marker", async () => {
    const fixture = await createFixture();
    const result = await fixture.publisher.publish({
      after: await snapshotMarkdownTree(fixture.candidateWiki),
      before: await snapshotMarkdownTree(fixture.formalWiki),
      binding: binding(),
      candidateWikiPath: fixture.candidateWiki,
      review: reviewBinding(),
      runId: "run-publish-12345678",
    });

    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(
      result.after,
    );
    expect(result.changes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          operation: "modified",
          path: "quickstart.md",
        }),
        expect.objectContaining({ operation: "added", path: "new.md" }),
      ]),
    );
    const journal = path.join(
      fixture.runtimeDir,
      "recovery",
      "run-publish-12345678",
    );
    const plan = JSON.parse(
      await readFile(path.join(journal, "plan.json"), "utf8"),
    ) as Record<string, unknown>;
    expect(plan).toEqual(
      expect.objectContaining({
        afterRootHash: result.after.rootHash,
        beforeRootHash: result.before.rootHash,
        model,
        reviewPending: true,
      }),
    );
    expect(
      JSON.parse(await readFile(path.join(journal, "commit.marker"), "utf8")),
    ).toEqual(
      expect.objectContaining({
        afterRootHash: result.after.rootHash,
        runId: "run-publish-12345678",
      }),
    );
  });

  test("allocates a monotonic generation across independent publications", async () => {
    const fixture = await createFixture();
    const first = await fixture.publisher.publish({
      after: await snapshotMarkdownTree(fixture.candidateWiki),
      before: await snapshotMarkdownTree(fixture.formalWiki),
      binding: binding(),
      candidateWikiPath: fixture.candidateWiki,
      review: reviewBinding(),
      runId: "run-generation-first-12345678",
    });
    await fixture.publisher.completeReview({
      expectedRootHash: first.after.rootHash,
      journalPath: first.journalPath,
    });
    await writeFile(
      path.join(fixture.candidateWiki, "quickstart.md"),
      page("# Generation two\n"),
      "utf8",
    );
    const second = await fixture.publisher.publish({
      after: await snapshotMarkdownTree(fixture.candidateWiki),
      before: await snapshotMarkdownTree(fixture.formalWiki),
      binding: binding(),
      candidateWikiPath: fixture.candidateWiki,
      review: reviewBinding(),
      runId: "run-generation-second-12345678",
    });

    expect(first.generation).toBe(1);
    expect(second.generation).toBe(2);
  });

  test("persists semantic attention and closes the mandatory review journal", async () => {
    const fixture = await createFixture();
    const published = await fixture.publisher.publish({
      after: await snapshotMarkdownTree(fixture.candidateWiki),
      before: await snapshotMarkdownTree(fixture.formalWiki),
      binding: binding(),
      candidateWikiPath: fixture.candidateWiki,
      review: reviewBinding(),
      runId: "run-attention-12345678",
    });

    await fixture.publisher.completeReviewWithAttention({
      expectedRootHash: published.after.rootHash,
      issues: [
        {
          code: "owner_confirmation",
          message: "The owner still needs user confirmation.",
          page: "quickstart.md",
          severity: "provisional",
        },
      ],
      journalPath: published.journalPath,
    });

    await expect(access(published.journalPath)).rejects.toBeDefined();
    const attentionFiles = await readdir(
      path.join(fixture.runtimeDir, "attention"),
    );
    expect(attentionFiles).toEqual(["1-run-attention-12345678.json"]);
    expect(
      JSON.parse(
        await readFile(
          path.join(fixture.runtimeDir, "attention", attentionFiles[0]!),
          "utf8",
        ),
      ),
    ).toEqual(
      expect.objectContaining({
        generation: 1,
        rootHash: published.after.rootHash,
        runId: "run-attention-12345678",
      }),
    );
    await expect(
      inspectPersistedReviewAttention({
        formalWikiPath: fixture.formalWiki,
        runtimeDir: fixture.runtimeDir,
      }),
    ).resolves.toBe("attention");

    await writeFile(
      path.join(fixture.candidateWiki, "quickstart.md"),
      page("# Attention resolved\n"),
      "utf8",
    );
    const resolved = await fixture.publisher.publish({
      after: await snapshotMarkdownTree(fixture.candidateWiki),
      before: await snapshotMarkdownTree(fixture.formalWiki),
      binding: binding(),
      candidateWikiPath: fixture.candidateWiki,
      review: reviewBinding(),
      runId: "run-attention-resolved-12345678",
    });
    await fixture.publisher.completeReview({
      expectedRootHash: resolved.after.rootHash,
      journalPath: resolved.journalPath,
    });
    await expect(
      inspectPersistedReviewAttention({
        formalWikiPath: fixture.formalWiki,
        runtimeDir: fixture.runtimeDir,
      }),
    ).resolves.toBe("clean");
  });

  test("rejects formal Wiki drift before touching the formal tree", async () => {
    const fixture = await createFixture();
    const before = await snapshotMarkdownTree(fixture.formalWiki);
    await writeFile(
      path.join(fixture.formalWiki, "quickstart.md"),
      page("# External edit\n"),
      "utf8",
    );

    await expect(
      fixture.publisher.publish({
        after: await snapshotMarkdownTree(fixture.candidateWiki),
        before,
        binding: binding(),
        candidateWikiPath: fixture.candidateWiki,
        review: reviewBinding(),
        runId: "run-publish-12345678",
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "wiki_changed" }));
    expect(
      await readFile(path.join(fixture.formalWiki, "quickstart.md"), "utf8"),
    ).toContain("External edit");
  });

  test.each([
    "after_plan",
    "after_displace",
    "after_install",
    "before_marker_rename",
  ] as const)(
    "restores the complete before tree when publication fails at %s",
    async (faultPoint) => {
      const fixture = await createFixture({ faultPoint });
      const before = await snapshotMarkdownTree(fixture.formalWiki);

      await expect(
        fixture.publisher.publish({
          after: await snapshotMarkdownTree(fixture.candidateWiki),
          before,
          binding: binding(),
          candidateWikiPath: fixture.candidateWiki,
          review: reviewBinding(),
          runId: "run-publish-12345678",
        }),
      ).rejects.toEqual(expect.objectContaining({ code: "publish_failed" }));
      expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(before);
    },
  );

  test("treats a fault after the durable marker as committed review-pending", async () => {
    const fixture = await createFixture({ faultPoint: "after_marker" });
    const after = await snapshotMarkdownTree(fixture.candidateWiki);

    const result = await fixture.publisher.publish({
      after,
      before: await snapshotMarkdownTree(fixture.formalWiki),
      binding: binding(),
      candidateWikiPath: fixture.candidateWiki,
      review: reviewBinding(),
      runId: "run-publish-12345678",
    });

    expect(result.after).toEqual(after);
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(after);
  });

  test("fails closed without overwriting an external edit made before rollback", async () => {
    const fixture = await createFixture();
    const publisher = new WikiPublisher({
      fault: async (point) => {
        if (point !== "after_install") return;
        await writeFile(
          path.join(fixture.formalWiki, "quickstart.md"),
          page("# External edit\n"),
          "utf8",
        );
        throw new Error("fault:external-drift");
      },
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
    });

    await expect(
      publisher.publish({
        after: await snapshotMarkdownTree(fixture.candidateWiki),
        before: await snapshotMarkdownTree(fixture.formalWiki),
        binding: binding(),
        candidateWikiPath: fixture.candidateWiki,
        review: reviewBinding(),
        runId: "run-external-12345678",
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "restore_failed" }));
    expect(
      await readFile(path.join(fixture.formalWiki, "quickstart.md"), "utf8"),
    ).toContain("External edit");
  });
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

function binding() {
  const selected = selectedSkills();
  return {
    model,
    skillAggregateHash: selected.aggregateHash,
    sourceManifestHash: null,
    sourceTreeHash: null,
  };
}

function reviewBinding() {
  return {
    instruction: "Document the confirmed change.",
    selectedSkills: selectedSkills(),
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
