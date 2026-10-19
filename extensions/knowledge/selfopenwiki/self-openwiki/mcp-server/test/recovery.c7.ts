import { createHash } from "node:crypto";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { computeExternalPublishRunId, WikiPublisher } from "../src/publish.js";
import { WikiRecoveryService } from "../src/recovery.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type SelectedC7Skill,
} from "../src/skills.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("Wiki publication recovery", () => {
  test.each([false, true])("cold rollback preserves Git policies, including partial moves with unchanged Markdown (%s)", async (sameContent) => {
    const policies = { ".gitignore": "*.tmp\r\n", ".gitattributes": "*.md -text\n*.json -text\n" };
    const fixture = await createCommittedFixture({ policies, sameContent });
    await unlink(path.join(fixture.journalPath, "commit.marker"));
    if (sameContent) {
      // Durable state of a crash between the two policy moves.
      await rename(path.join(fixture.formalWiki, ".gitattributes"), path.join(fixture.journalPath, "displaced", ".gitattributes"));
    }
    await expect(fixture.recovery.recoverRun("run-recovery-12345678")).resolves.toMatchObject({ recoveryState: "clean", reviewPending: false });
    for (const [name, bytes] of Object.entries(policies)) {
      await expect(readFile(path.join(fixture.formalWiki, name), "utf8")).resolves.toBe(bytes);
    }
    await expect(snapshotMarkdownTree(fixture.formalWiki)).resolves.toEqual(fixture.before);
  });

  test("conflicting root Git policies fail recovery without overwriting either copy", async () => {
    const policies = { ".gitattributes": "*.md -text\n" };
    const fixture = await createCommittedFixture({ policies });
    await unlink(path.join(fixture.journalPath, "commit.marker"));
    const conflict = path.join(fixture.journalPath, "displaced", ".gitattributes");
    await writeFile(conflict, "conflicting policy\n");
    await expect(fixture.recovery.recoverRun("run-recovery-12345678")).resolves.toMatchObject({ recoveryState: "restore_failed" });
    await expect(readFile(path.join(fixture.formalWiki, ".gitattributes"), "utf8")).resolves.toBe(policies[".gitattributes"]);
    await expect(readFile(conflict, "utf8")).resolves.toBe("conflicting policy\n");
  });

  test("recovers a marked version-4 external publication without creating a Review obligation", async () => {
    const fixture = await createExternalCommittedFixture();
    const recover = vi.fn(async (transactionId: string) => {
      expect(transactionId).toBe("external-12345678");
      await rm(fixture.journalPath, { recursive: true });
    });
    const recovery = new WikiRecoveryService({
      formalWikiPath: fixture.formalWiki,
      runtimeDir: fixture.runtimeDir,
      security: fixture.security,
      externalRecovery: { recover },
    });

    const result = await recovery.recoverRun(fixture.runId);

    expect(result).toEqual({
      recoveryState: "clean",
      reviewPending: false,
      runId: fixture.runId,
    });
    expect(recover).toHaveBeenCalledTimes(1);
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(
      fixture.after,
    );
    expect(JSON.stringify(result)).not.toMatch(/model|reviewObligation/iu);
  });

  test("rolls back an unmarked installed tree to the exact before snapshot", async () => {
    const fixture = await createCommittedFixture();
    await unlink(path.join(fixture.journalPath, "commit.marker"));

    const result = await fixture.recovery.recoverRun("run-recovery-12345678");

    expect(result).toEqual({
      recoveryState: "clean",
      reviewPending: false,
      runId: "run-recovery-12345678",
    });
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(
      fixture.before,
    );
  });

  test("preserves a marked exact after tree and reports review_pending", async () => {
    const fixture = await createCommittedFixture();

    const result = await fixture.recovery.recoverRun("run-recovery-12345678");

    expect(result).toEqual(
      expect.objectContaining({
        recoveryState: "review_pending",
        reviewPending: true,
        reviewReady: true,
        runId: "run-recovery-12345678",
      }),
    );
    expect(result.reviewObligation).toEqual(
      expect.objectContaining({
        generation: 1,
        instruction: "Document the confirmed change.",
        model: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
        sourceManifestHash: null,
      }),
    );
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(
      fixture.after,
    );
  });

  test("fails closed when a marked formal tree drifts", async () => {
    const fixture = await createCommittedFixture();
    await writeFile(
      path.join(fixture.formalWiki, "quickstart.md"),
      page("# Unexpected drift\n"),
      "utf8",
    );

    const result = await fixture.recovery.recoverRun("run-recovery-12345678");

    expect(result.recoveryState).toBe("restore_failed");
    expect(result.reviewPending).toBe(true);
  });

  test("does not overwrite external drift while rolling back an unmarked journal", async () => {
    const fixture = await createCommittedFixture();
    await unlink(path.join(fixture.journalPath, "commit.marker"));
    await writeFile(
      path.join(fixture.formalWiki, "quickstart.md"),
      page("# External recovery edit\n"),
      "utf8",
    );

    const result = await fixture.recovery.recoverRun("run-recovery-12345678");

    expect(result.recoveryState).toBe("restore_failed");
    expect(
      await readFile(path.join(fixture.formalWiki, "quickstart.md"), "utf8"),
    ).toContain("External recovery edit");
  });

  test("persists attention and cannot complete when an exact Skill snapshot is missing", async () => {
    const fixture = await createCommittedFixture();
    await rm(path.join(fixture.journalPath, "review", "skills"), {
      recursive: true,
    });

    const result = await fixture.recovery.recoverRun("run-recovery-12345678");

    expect(result).toEqual({
      recoveryState: "review_pending",
      reviewPending: true,
      reviewReady: false,
      runId: "run-recovery-12345678",
    });
    expect(
      JSON.parse(
        await readFile(
          path.join(fixture.journalPath, "attention.json"),
          "utf8",
        ),
      ),
    ).toEqual(expect.objectContaining({ code: "review_snapshot_unavailable" }));
  });

  test("collapses a committed repair successor chain after a cleanup crash", async () => {
    const fixture = await createCommittedFixture();
    await writeFile(
      path.join(fixture.candidateWiki, "quickstart.md"),
      page("# Repaired\n"),
      "utf8",
    );
    const successor = await fixture.publisher.publish({
      after: await snapshotMarkdownTree(fixture.candidateWiki),
      before: await snapshotMarkdownTree(fixture.formalWiki),
      binding: {
        model: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
        skillAggregateHash: fixture.selectedSkills.aggregateHash,
        sourceManifestHash: null,
        sourceTreeHash: null,
      },
      candidateWikiPath: fixture.candidateWiki,
      review: {
        instruction: "Document the repaired change.",
        selectedSkills: fixture.selectedSkills,
      },
      runId: "run-recovery-successor-12345678",
      supersedes: {
        journalPath: fixture.journalPath,
        reviewedRootHash: fixture.after.rootHash,
        runId: "run-recovery-12345678",
      },
    });

    const results = await fixture.recovery.recoverAll();

    expect(results).toEqual([
      expect.objectContaining({
        recoveryState: "review_pending",
        reviewPending: true,
        runId: "run-recovery-successor-12345678",
      }),
    ]);
    await expect(access(fixture.journalPath)).rejects.toBeDefined();
    expect(await snapshotMarkdownTree(fixture.formalWiki)).toEqual(
      successor.after,
    );
  });
});

async function createCommittedFixture({ policies = {} as Record<string, string>, sameContent = false } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-recovery-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWiki = path.join(runtimeDir, "wiki");
  const candidateWiki = path.join(root, "candidate");
  await Promise.all([
    mkdir(formalWiki, { recursive: true }),
    mkdir(candidateWiki, { recursive: true }),
  ]);
  await writeFile(path.join(formalWiki, "quickstart.md"), page("# Before\n"));
  await writeFile(path.join(candidateWiki, "quickstart.md"), page(sameContent ? "# Before\n" : "# After\n"));
  for (const [name, bytes] of Object.entries(policies)) {
    await writeFile(path.join(formalWiki, name), bytes);
  }
  const before = await snapshotMarkdownTree(formalWiki);
  const after = await snapshotMarkdownTree(candidateWiki);
  const security = { securePrivatePath: vi.fn().mockResolvedValue(undefined) };
  const publisher = new WikiPublisher({
    formalWikiPath: formalWiki,
    runtimeDir,
    security,
  });
  const selectedSkills = createSelectedSkills();
  const published = await publisher.publish({
    after,
    before,
    binding: {
      model: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
      skillAggregateHash: selectedSkills.aggregateHash,
      sourceManifestHash: null,
      sourceTreeHash: null,
    },
    candidateWikiPath: candidateWiki,
    review: {
      instruction: "Document the confirmed change.",
      selectedSkills,
    },
    runId: "run-recovery-12345678",
  });
  return {
    after,
    before,
    candidateWiki,
    formalWiki,
    journalPath: published.journalPath,
    publisher,
    recovery: new WikiRecoveryService({
      formalWikiPath: formalWiki,
      runtimeDir,
      security,
    }),
    selectedSkills,
  };
}

async function createExternalCommittedFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-external-recovery-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWiki = path.join(runtimeDir, "wiki");
  const candidateWiki = path.join(root, "candidate");
  await Promise.all([
    mkdir(formalWiki, { recursive: true }),
    mkdir(candidateWiki, { recursive: true }),
  ]);
  await writeFile(path.join(formalWiki, "quickstart.md"), page("# Before\n"));
  await writeFile(path.join(candidateWiki, "quickstart.md"), page("# After\n"));
  const before = await snapshotMarkdownTree(formalWiki);
  const after = await snapshotMarkdownTree(candidateWiki);
  const security = { securePrivatePath: vi.fn().mockResolvedValue(undefined) };
  const publisher = new WikiPublisher({
    formalWikiPath: formalWiki,
    runtimeDir,
    security,
  });
  const selectedSkills = createSelectedSkills();
  const identity = {
    bindingHash: hash("a"),
    generation: 1,
    reviewReceiptHash: hash("b"),
    transactionId: "external-12345678",
  };
  const runId = computeExternalPublishRunId(identity);
  const published = await publisher.publishExternal({
    after,
    before,
    candidateWikiPath: candidateWiki,
    plan: {
      version: 4,
      executionMode: "external_agent",
      runId,
      transactionId: identity.transactionId,
      generation: identity.generation,
      bindingHash: identity.bindingHash,
      inputHash: hash("c"),
      beforeRootHash: before.rootHash,
      candidateRootHash: after.rootHash,
      requestPackageHash: hash("d"),
      candidateReceiptHash: hash("e"),
      reviewPackageHash: hash("f"),
      reviewReceiptHash: identity.reviewReceiptHash,
      sourceManifestHash: null,
      sourceTreeHash: null,
      skillAggregateHash: selectedSkills.aggregateHash,
      orderedSkillPackages: selectedSkills.skills.map(
        ({ id, packageHash }) => ({ id, packageHash }),
      ),
      hardRulePackageHash: hash("1"),
      candidateResultContractSchemaHash: hash("2"),
      reviewResultContractSchemaHash: hash("3"),
      confirmedWikiPathsHash: hash("4"),
      reviewCompletedBeforePublish: true,
    },
  });
  return {
    after,
    formalWiki,
    journalPath: published.journalPath,
    runId,
    runtimeDir,
    security,
  };
}

function createSelectedSkills() {
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

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}
