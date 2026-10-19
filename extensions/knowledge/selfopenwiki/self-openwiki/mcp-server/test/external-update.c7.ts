import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { withC7Locks } from "../src/config.js";
import { toolOutputSchemas } from "../src/contracts.js";
import { OpenWikiExternalUpdateService } from "../src/external-update.js";
import { ExternalUpdateTransactionOwner } from "../src/external-update-transaction.js";
import { WikiPublisher } from "../src/publish.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type C7SkillRegistry,
  type SelectedC7Skill,
  type SelectedC7Skills,
} from "../src/skills.js";
import { hashSourceSnapshotTree } from "../src/sources.js";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) => rm(root, { force: true, recursive: true })),
  );
});

describe("external update begin service", () => {
  test("starts and replays an exact provider-free work package without credentials or config", async () => {
    const fixture = await createFixture();

    const first = asWritable(await fixture.service.begin(fixture.input));
    const replay = asWritable(await fixture.service.begin(fixture.input));

    expect(first.status).toBe("external_update_ready");
    expect(replay).toEqual(first);
    expect(first).toMatchObject({
      authRequired: false,
      executionMode: "external_agent",
      ok: true,
      recovery: { action: "none" },
      workPackage: {
        beforeWikiRevision: fixture.wikiRevision,
        candidate: {
          allowedChangedPaths: ["index.md"],
          permissions: ["read", "list", "write"],
        },
        confirmedWikiPaths: ["index.md"],
        sources: null,
      },
    });
    expect(
      JSON.parse(await readFile(first.workPackage.requestPackage.path, "utf8")),
    ).toEqual({
      instruction: "Refresh the project overview.",
      materials: [
        {
          byteLength: 8,
          content: "Evidence",
          id: "material-1",
          source: "user-note",
        },
      ],
      version: 1,
    });
    expect(JSON.stringify(first)).not.toMatch(/model|provider|credential/iu);
    await expect(stat(fixture.configPath)).rejects.toMatchObject({
      code: "ENOENT",
    });
    await expect(stat(fixture.credentialPath)).rejects.toMatchObject({
      code: "ENOENT",
    });
    expect(fixture.sources.verify).not.toHaveBeenCalled();
  });

  test("keeps the immutable request package after caller mutation and resumes the same writer workspace", async () => {
    const fixture = await createFixture();
    const mutable = structuredClone(fixture.input);
    const first = asWritable(await fixture.service.begin(mutable));
    mutable.instruction = "Replace the instruction.";
    mutable.materials[0]!.content = "Replaced";

    const resumed = asWritable(
      await fixture.service.begin({
        action: "resume",
        bindingHash: first.workPackage.bindingHash,
        transactionId: first.workPackage.transactionId,
      }),
    );

    expect(resumed.status).toBe("external_update_resumed");
    expect(resumed.workPackage).toEqual(first.workPackage);
    expect(
      JSON.parse(await readFile(first.workPackage.requestPackage.path, "utf8")),
    ).toMatchObject({
      instruction: "Refresh the project overview.",
      materials: [{ content: "Evidence" }],
    });
  });

  test("releases the operation lock before returning a Host work package", async () => {
    const fixture = await createFixture();
    const result = asWritable(await fixture.service.begin(fixture.input));

    await expect(
      withC7Locks(
        fixture.runtimeDir,
        ["operation"],
        async () => result.workPackage.transactionId,
      ),
    ).resolves.toBe(result.workPackage.transactionId);
  });

  test.each([
    {
      field: "instruction",
      canary: "api_key=abcdefghijklmnop",
      update: (input: StartInput) => {
        input.instruction = "Use api_key=abcdefghijklmnop";
      },
    },
    {
      field: "material id",
      canary: "token=abcdefghijklmnop",
      update: (input: StartInput) => {
        input.materials[0]!.id = "token=abcdefghijklmnop";
      },
    },
    {
      field: "material source",
      canary: "secret=abcdefghijklmnop",
      update: (input: StartInput) => {
        input.materials[0]!.source = "secret=abcdefghijklmnop";
      },
    },
    {
      field: "material content",
      canary: "token=abcdefghijklmnop",
      update: (input: StartInput) => {
        input.materials[0]!.content = "token=abcdefghijklmnop";
      },
    },
  ])(
    "rejects sensitive $field before committing a transaction",
    async ({ canary, update }) => {
      const fixture = await createFixture();
      const input = structuredClone(fixture.input);
      update(input);
      const start = vi.spyOn(fixture.transactions, "start");

      const failure = await fixture.service
        .begin(input)
        .catch((error) => error);
      expect(failure).toMatchObject({
        code: "source_rejected",
        message:
          "The external update contains credential-like material and was rejected.",
      });
      if (!(failure instanceof Error)) throw new Error("expected rejection");
      expect(failure.message.length).toBeLessThanOrEqual(128);
      expect(JSON.stringify(failure)).not.toContain(canary);
      await expect(fixture.transactions.readActive()).resolves.toBeNull();
      const updateEntries = await readdir(
        path.join(fixture.runtimeDir, "external-updates"),
      ).catch((error: NodeJS.ErrnoException) => {
        if (error.code === "ENOENT") return [];
        throw error;
      });
      expect(updateEntries).toEqual([]);
      expect(fixture.select).not.toHaveBeenCalled();
      expect(start).not.toHaveBeenCalled();
    },
  );

  test("verifies and freezes a confirmed source manifest before returning", async () => {
    const fixture = await createFixture();
    const sourceRoot = path.join(fixture.root, "source-snapshot");
    await mkdir(sourceRoot, { recursive: true });
    await writeFile(
      path.join(sourceRoot, "evidence.txt"),
      "Source evidence\n",
      "utf8",
    );
    const cleanup = vi.fn().mockResolvedValue(undefined);
    fixture.sources.verify.mockResolvedValueOnce({
      cleanup,
      files: [],
      manifestHash: hash("a"),
      snapshotPath: sourceRoot,
      snapshotTreeHash: await hashSourceSnapshotTree(sourceRoot),
    });

    const result = asWritable(
      await fixture.service.begin({
        ...fixture.input,
        sourceConfirmation: `confirm-source:source-12345678:${hash("a")}`,
        sourceManifestId: "source-12345678",
      }),
    );

    expect(fixture.sources.verify).toHaveBeenCalledWith({
      confirmation: `confirm-source:source-12345678:${hash("a")}`,
      sourceManifestId: "source-12345678",
    });
    expect(result.workPackage).toMatchObject({
      sourceManifestHash: hash("a"),
      sources: { permissions: ["read", "list"] },
    });
    expect(
      await readFile(
        path.join(
          (result.workPackage.sources as { rootPath: string }).rootPath,
          "evidence.txt",
        ),
        "utf8",
      ),
    ).toBe("Source evidence\n");
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  test("replays the frozen source package without rereading changed originals", async () => {
    const fixture = await createFixture();
    const sourceRoot = path.join(fixture.root, "replay-source-snapshot");
    await mkdir(sourceRoot, { recursive: true });
    await writeFile(
      path.join(sourceRoot, "evidence.txt"),
      "Original\n",
      "utf8",
    );
    fixture.sources.verify
      .mockResolvedValueOnce({
        cleanup: vi.fn().mockResolvedValue(undefined),
        files: [],
        manifestHash: hash("c"),
        snapshotPath: sourceRoot,
        snapshotTreeHash: await hashSourceSnapshotTree(sourceRoot),
      })
      .mockRejectedValueOnce(
        Object.assign(new Error("changed"), { code: "source_changed" }),
      );
    const input = {
      ...fixture.input,
      sourceConfirmation: `confirm-source:source-12345678:${hash("c")}`,
      sourceManifestId: "source-12345678",
    };
    const start = vi.spyOn(fixture.transactions, "start");

    const first = asWritable(await fixture.service.begin(input));
    const replay = asWritable(await fixture.service.begin(input));

    expect(replay).toEqual(first);
    expect(fixture.sources.verify).toHaveBeenCalledTimes(1);
    expect(start.mock.calls.map(([value]) => value.sourceManifestId)).toEqual([
      "source-12345678",
      "source-12345678",
    ]);
    await expect(
      fixture.service.begin({
        ...input,
        sourceManifestId: "source-87654321",
        sourceConfirmation: `confirm-source:source-87654321:${hash("c")}`,
      }),
    ).rejects.toMatchObject({ code: "busy" });
    expect(fixture.sources.verify).toHaveBeenCalledTimes(1);
  });

  test("leaves no active transaction when source verification fails", async () => {
    const fixture = await createFixture();
    fixture.sources.verify.mockRejectedValueOnce(
      Object.assign(new Error("changed"), { code: "source_changed" }),
    );

    await expect(
      fixture.service.begin({
        ...fixture.input,
        sourceConfirmation: "confirm-source:source-12345678:stale",
        sourceManifestId: "source-12345678",
      }),
    ).rejects.toMatchObject({ code: "source_changed" });
    await expect(fixture.transactions.readActive()).resolves.toBeNull();
  });

  test("rejects revision drift, missing scope, and untrusted Skills before an active commit", async () => {
    const revisionFixture = await createFixture();
    await expect(
      revisionFixture.service.begin({
        ...revisionFixture.input,
        expectedWikiRevision: hash("b"),
      }),
    ).rejects.toMatchObject({ code: "wiki_conflict" });
    await expect(revisionFixture.transactions.readActive()).resolves.toBeNull();

    const scopeFixture = await createFixture();
    const { confirmedWikiPaths: _, ...withoutScope } = scopeFixture.input;
    await expect(
      scopeFixture.service.begin(withoutScope),
    ).rejects.toMatchObject({
      code: "invalid_input",
    });
    await expect(scopeFixture.transactions.readActive()).resolves.toBeNull();

    const skillFixture = await createFixture();
    skillFixture.select.mockImplementationOnce(() => {
      throw Object.assign(new Error("untrusted"), { code: "skill_untrusted" });
    });
    await expect(
      skillFixture.service.begin({
        ...skillFixture.input,
        skills: ["rendering"],
      }),
    ).rejects.toMatchObject({ code: "skill_untrusted" });
    await expect(skillFixture.transactions.readActive()).resolves.toBeNull();
  });

  test("retains requested specialized Skill order after the mandatory base Skill", async () => {
    const fixture = await createFixture();
    const rendering = makeSkill("rendering", "# Rendering\n");
    const networking = makeSkill("networking", "# Networking\n");
    fixture.select.mockReturnValueOnce({
      aggregateHash: aggregateSkillHash([
        fixture.baseSkill,
        networking,
        rendering,
      ]),
      skills: [fixture.baseSkill, networking, rendering],
    });

    const result = asWritable(
      await fixture.service.begin({
        ...fixture.input,
        skills: ["networking", "rendering"],
      }),
    );

    expect(fixture.select).toHaveBeenCalledWith(["networking", "rendering"]);
    expect(
      (
        result.workPackage.rules as { skills: readonly { id: string }[] }
      ).skills.map((skill) => skill.id),
    ).toEqual(["kg-c7-project-wiki", "networking", "rendering"]);
  });
});

describe("external update Review preparation", () => {
  test("rejects a candidate receipt whose generation does not match the active binding", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));

    await expect(
      fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started, { generation: 2 }),
      }),
    ).rejects.toMatchObject({ code: "transaction_state_invalid" });

    await expect(fixture.transactions.readActive()).resolves.toMatchObject({
      state: { stage: "candidate_writable", review: null },
    });
  });

  test("short-circuits a blocking candidate without validation, Review, publication, or a retained lock", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));
    const candidateRoot = started.workPackage.candidate.rootPath;
    await writeFile(path.join(candidateRoot, "not-markdown.txt"), "invalid");
    const receipt = candidateReceipt(started, {
      classification: "blocking",
      issues: [
        {
          code: "missing_decision",
          message: "The requested direction is ambiguous.",
          severity: "blocking",
        },
      ],
      questions: ["Which direction should the Wiki use?"],
    });

    const result = await fixture.service.finalize({
      action: "prepare_review",
      transactionId: started.workPackage.transactionId,
      bindingHash: started.workPackage.bindingHash,
      candidateReceipt: receipt,
    });

    expect(result).toEqual({
      ok: true,
      executionMode: "external_agent",
      authRequired: false,
      transactionId: started.workPackage.transactionId,
      generation: 1,
      bindingHash: started.workPackage.bindingHash,
      recovery: { action: "none" },
      status: "needs_clarification",
      published: false,
      candidateRetained: true,
      nextAction: "clarify",
      issues: [
        {
          code: "missing_decision",
          message: "The requested direction is ambiguous.",
          severity: "blocking",
        },
      ],
      questions: ["Which direction should the Wiki use?"],
    });
    const active = await fixture.transactions.readActive();
    expect(active?.state).toMatchObject({
      stage: "attention",
      review: null,
    });
    await expect(stat(candidateRoot)).resolves.toMatchObject({
      isDirectory: expect.any(Function),
    });
    await expect(
      fixture.transactions.resume(
        started.workPackage.transactionId,
        started.workPackage.bindingHash,
      ),
    ).resolves.toMatchObject({ kind: "attention" });
    await expect(
      fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: receipt,
      }),
    ).resolves.toEqual(result);
    await expect(
      fixture.service.begin({
        action: "resume",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
      }),
    ).resolves.toEqual(result);
    const restartedService = new OpenWikiExternalUpdateService({
      sensitivePolicyPath: fixture.sensitivePolicyPath,
      skills: { select: fixture.select },
      sources: fixture.sources,
      transactions: new ExternalUpdateTransactionOwner({
        formalWikiPath: fixture.formalWikiPath,
        runtimeDir: fixture.runtimeDir,
        security: fixture.security,
      }),
    });
    await expect(
      restartedService.begin({
        action: "resume",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
      }),
    ).resolves.toEqual(result);
    expect(
      await readdir(path.join(active!.state.transactionRoot, "immutable")),
    ).not.toContain("review-result-contract.json");
    await expect(snapshotMarkdownTree(fixture.formalWikiPath)).resolves.toEqual(
      fixture.beforeSnapshot,
    );
    await expect(
      withC7Locks(fixture.runtimeDir, ["operation", "wiki"], async () => true),
    ).resolves.toBe(true);
  });

  test.each([
    {
      label: "confirmed path scope",
      mutate: async (root: string) => {
        await writeFile(
          path.join(root, "quickstart.md"),
          "---\ntype: Guide\n---\n\n# Changed outside scope\n\nSee [home](./index.md).\n",
          "utf8",
        );
      },
    },
    {
      label: "Markdown-only tree",
      mutate: async (root: string) => {
        await writeFile(path.join(root, "unexpected.txt"), "not Markdown");
      },
    },
    {
      label: "OKF front matter",
      mutate: async (root: string) => {
        await writeFile(path.join(root, "index.md"), "# Missing OKF\n");
      },
    },
    {
      label: "internal links",
      mutate: async (root: string) => {
        await writeFile(
          path.join(root, "index.md"),
          "---\ntype: Guide\n---\n\n# Home\n\n[missing](./missing.md)\n",
        );
      },
    },
    {
      label: "navigation reachability",
      confirmedWikiPaths: ["index.md", "orphan.md"],
      mutate: async (root: string) => {
        await writeFile(
          path.join(root, "orphan.md"),
          "---\ntype: Guide\n---\n\n# Orphan\n",
        );
      },
    },
  ])(
    "rejects invalid exact candidate bytes at the $label check without freezing Review state",
    async ({ confirmedWikiPaths, mutate }) => {
      const fixture = await createFixture();
      const started = asWritable(
        await fixture.service.begin({
          ...fixture.input,
          ...(confirmedWikiPaths === undefined ? {} : { confirmedWikiPaths }),
        }),
      );
      await mutate(started.workPackage.candidate.rootPath);
      const formalBefore = await snapshotMarkdownTree(fixture.formalWikiPath);

      await expect(
        fixture.service.finalize({
          action: "prepare_review",
          transactionId: started.workPackage.transactionId,
          bindingHash: started.workPackage.bindingHash,
          candidateReceipt: candidateReceipt(started),
        }),
      ).rejects.toMatchObject({ code: "validation_failed" });

      await expect(
        snapshotMarkdownTree(fixture.formalWikiPath),
      ).resolves.toEqual(formalBefore);
      await expectNoReviewState(fixture, started);
    },
  );

  test("requires a provisional marker for provisional candidate bytes", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));
    await writeFile(
      path.join(started.workPackage.candidate.rootPath, "index.md"),
      "---\ntype: Guide\n---\n\n# Tentative\n",
    );

    await expect(
      fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started, {
          classification: "provisional",
          issues: [
            {
              code: "needs_confirmation",
              message: "The update remains provisional.",
              severity: "provisional",
            },
          ],
        }),
      }),
    ).rejects.toMatchObject({ code: "validation_failed" });
    await expectNoReviewState(fixture, started);
  });

  test("rejects formal Wiki revision drift without changing the externally modified Wiki", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));
    await writeFile(
      path.join(fixture.formalWikiPath, "index.md"),
      "---\ntype: Guide\n---\n\n# Concurrent change\n",
    );
    const drifted = await snapshotMarkdownTree(fixture.formalWikiPath);

    await expect(
      fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started),
      }),
    ).rejects.toMatchObject({ code: "wiki_conflict" });

    await expect(snapshotMarkdownTree(fixture.formalWikiPath)).resolves.toEqual(
      drifted,
    );
    await expectNoReviewState(fixture, started);
  });

  test("rejects a complete frozen source copy without Review or publication", async () => {
    const fixture = await createFixture();
    const sourceRoot = path.join(fixture.root, "prepare-source-snapshot");
    await mkdir(sourceRoot, { recursive: true });
    const sourceText = "Exact private source evidence for validation.\n";
    await writeFile(path.join(sourceRoot, "evidence.txt"), sourceText);
    fixture.sources.verify.mockResolvedValueOnce({
      cleanup: vi.fn().mockResolvedValue(undefined),
      files: [],
      manifestHash: hash("d"),
      snapshotPath: sourceRoot,
      snapshotTreeHash: await hashSourceSnapshotTree(sourceRoot),
    });
    const started = asWritable(
      await fixture.service.begin({
        ...fixture.input,
        sourceConfirmation: `confirm-source:source-12345678:${hash("d")}`,
        sourceManifestId: "source-12345678",
      }),
    );
    await writeFile(
      path.join(started.workPackage.candidate.rootPath, "index.md"),
      `---\ntype: Guide\n---\n\n# Home\n\n${sourceText}`,
    );

    await expect(
      fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started),
      }),
    ).rejects.toMatchObject({ code: "validation_failed" });
    await expectNoReviewState(fixture, started);
    await expect(snapshotMarkdownTree(fixture.formalWikiPath)).resolves.toEqual(
      fixture.beforeSnapshot,
    );
  });

  test.each([
    [
      "request package",
      (started: ReturnType<typeof asWritable>) =>
        started.workPackage.requestPackage.path,
    ],
    [
      "hard-rule package",
      (started: ReturnType<typeof asWritable>) =>
        started.workPackage.rules.hardRulePackage.path,
    ],
    [
      "candidate-result contract",
      (started: ReturnType<typeof asWritable>) =>
        started.workPackage.rules.candidateResultContract.path,
    ],
    [
      "ordered Skill package",
      (started: ReturnType<typeof asWritable>) =>
        path.join(started.workPackage.rules.skills[0]!.rootPath, "SKILL.md"),
    ],
  ])(
    "fails closed when the frozen %s drifts before validation",
    async (_label, targetPath) => {
      const fixture = await createFixture();
      const started = asWritable(await fixture.service.begin(fixture.input));
      await writeFile(targetPath(started), "tampered\n");

      await expect(
        fixture.service.finalize({
          action: "prepare_review",
          transactionId: started.workPackage.transactionId,
          bindingHash: started.workPackage.bindingHash,
          candidateReceipt: candidateReceipt(started),
        }),
      ).rejects.toMatchObject({ code: "restore_required" });
      await expectNoReviewState(fixture, started);
      await expect(
        snapshotMarkdownTree(fixture.formalWikiPath),
      ).resolves.toEqual(fixture.beforeSnapshot);
    },
  );

  test("fails closed when the frozen source snapshot drifts before validation", async () => {
    const fixture = await createFixture();
    const sourceRoot = path.join(fixture.root, "drift-source-snapshot");
    await mkdir(sourceRoot, { recursive: true });
    await writeFile(path.join(sourceRoot, "evidence.txt"), "Original\n");
    fixture.sources.verify.mockResolvedValueOnce({
      cleanup: vi.fn().mockResolvedValue(undefined),
      files: [],
      manifestHash: hash("e"),
      snapshotPath: sourceRoot,
      snapshotTreeHash: await hashSourceSnapshotTree(sourceRoot),
    });
    const started = asWritable(
      await fixture.service.begin({
        ...fixture.input,
        sourceConfirmation: `confirm-source:source-12345678:${hash("e")}`,
        sourceManifestId: "source-12345678",
      }),
    );
    await writeFile(
      path.join(started.workPackage.sources!.rootPath, "evidence.txt"),
      "Tampered\n",
    );

    await expect(
      fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started),
      }),
    ).rejects.toMatchObject({ code: "restore_required" });
    await expectNoReviewState(fixture, started);
    await expect(snapshotMarkdownTree(fixture.formalWikiPath)).resolves.toEqual(
      fixture.beforeSnapshot,
    );
  });

  test("atomically freezes exact candidate and receipt bytes into an immutable Review package and replays it after restart", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));
    const receipt = candidateReceipt(started);
    const candidateBefore = await snapshotMarkdownTree(
      started.workPackage.candidate.rootPath,
    );

    const prepared = asReviewReady(
      await fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: receipt,
      }),
    );

    expect(
      toolOutputSchemas.openwiki_finalize_external_update.safeParse(prepared)
        .success,
    ).toBe(true);
    expect(prepared).toMatchObject({
      ok: true,
      executionMode: "external_agent",
      authRequired: false,
      status: "external_review_ready",
      transactionId: started.workPackage.transactionId,
      generation: 1,
      bindingHash: started.workPackage.bindingHash,
      candidateRootHash: candidateBefore.rootHash,
      reviewPackage: {
        version: 1,
        transactionId: started.workPackage.transactionId,
        generation: 1,
        bindingHash: started.workPackage.bindingHash,
        candidateRootHash: candidateBefore.rootHash,
        requestPackage: started.workPackage.requestPackage,
        sourceManifestHash: null,
        confirmedWikiPaths: ["index.md"],
        candidate: {
          rootPath: started.workPackage.candidate.rootPath,
          permissions: ["read", "list"],
        },
        rules: {
          hardRulePackage: started.workPackage.rules.hardRulePackage,
          skills: started.workPackage.rules.skills,
        },
      },
    });
    expect(prepared.candidateReceiptHash).toBe(
      hashCanonicalBytes("kg-c7:external-candidate-receipt:v1", receipt),
    );
    expect(prepared.reviewPackage.candidateReceiptHash).toBe(
      prepared.candidateReceiptHash,
    );

    const state = await readPersistedState(fixture, started);
    expect(state).toMatchObject({
      stage: "review_ready",
      review: {
        candidateRootHash: prepared.candidateRootHash,
        candidateReceiptHash: prepared.candidateReceiptHash,
        reviewPackageHash: prepared.reviewPackageHash,
      },
    });
    const review = state.review as { reviewPackagePath: string };
    const reviewBytes = await readFile(review.reviewPackagePath);
    expect(reviewBytes).toEqual(canonicalBytes(prepared.reviewPackage));
    expect(prepared.reviewPackageHash).toBe(
      hashDomainBytes("kg-c7:external-review-package:v1", reviewBytes),
    );
    const reviewContract = prepared.reviewPackage.rules.reviewResultContract;
    expect(reviewContract.path).not.toBe(
      started.workPackage.rules.candidateResultContract.path,
    );
    expect(reviewContract.schemaHash).toBe(
      hashDomainBytes(
        "kg-c7:external-review-result-contract:v1",
        await readFile(reviewContract.path),
      ),
    );
    await expect(
      snapshotMarkdownTree(started.workPackage.candidate.rootPath),
    ).resolves.toEqual(candidateBefore);

    const replay = asReviewReady(
      await fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: receipt,
      }),
    );
    expect(replay).toEqual(prepared);

    const restartedOwner = new ExternalUpdateTransactionOwner({
      formalWikiPath: fixture.formalWikiPath,
      now: () => new Date("2026-08-12T00:00:01.000Z"),
      runtimeDir: fixture.runtimeDir,
      security: fixture.security,
    });
    const restartedService = new OpenWikiExternalUpdateService({
      sensitivePolicyPath: fixture.sensitivePolicyPath,
      skills: { select: fixture.select },
      sources: fixture.sources,
      transactions: restartedOwner,
    });
    const resumed = asReviewReady(
      await restartedService.begin({
        action: "resume",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
      }),
    );
    expect(resumed).toEqual({ ...prepared, status: "external_review_resumed" });
    await expect(
      withC7Locks(fixture.runtimeDir, ["operation", "wiki"], async () => true),
    ).resolves.toBe(true);
  });

  test("submits a host-attested pass through the owner-supplied publisher callback", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));
    const prepared = asReviewReady(
      await fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started),
      }),
    );
    const candidateSnapshot = await snapshotMarkdownTree(
      started.workPackage.candidate.rootPath,
    );

    const reviewReceipt = {
      type: "external_review_receipt" as const,
      version: 1 as const,
      transactionId: prepared.transactionId,
      generation: prepared.generation,
      bindingHash: prepared.bindingHash,
      reviewPackageHash: prepared.reviewPackageHash,
      candidateRootHash: prepared.candidateRootHash,
      candidateReceiptHash: prepared.candidateReceiptHash,
      reviewerExecutionId: "reviewer-execution-12345678",
      verdict: "pass" as const,
      issues: [],
    };
    const submitInput = {
      action: "submit_review",
      transactionId: prepared.transactionId,
      bindingHash: prepared.bindingHash,
      reviewReceipt,
    } as const;
    const result = await fixture.service.finalize(submitInput);

    expect(result).toMatchObject({
      ok: true,
      executionMode: "external_agent",
      authRequired: false,
      status: "published",
      published: true,
      reviewEvidence: "host_attested",
      candidateRootHash: prepared.candidateRootHash,
    });
    expect(
      toolOutputSchemas.openwiki_finalize_external_update.safeParse(result)
        .success,
    ).toBe(true);
    expect(await snapshotMarkdownTree(fixture.formalWikiPath)).toEqual(
      candidateSnapshot,
    );
    expect(JSON.stringify(result)).not.toMatch(/model|provider/iu);
    await expect(fixture.service.finalize(submitInput)).resolves.toEqual(
      result,
    );
    await expect(
      fixture.service.finalize({
        ...submitInput,
        reviewReceipt: {
          ...reviewReceipt,
          reviewerExecutionId: "other-reviewer-12345678",
        },
      }),
    ).rejects.toMatchObject({ code: "transaction_state_invalid" });
  });

  test("replays an exact submit through a fresh service after terminal-state response loss", async () => {
    const fixture = await createFixture({
      faultInjector(point) {
        if (point === "after_terminal_state") throw new Error("response lost");
      },
    });
    const started = asWritable(await fixture.service.begin(fixture.input));
    const prepared = asReviewReady(
      await fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started),
      }),
    );
    const reviewReceipt = {
      type: "external_review_receipt" as const,
      version: 1 as const,
      transactionId: prepared.transactionId,
      generation: prepared.generation,
      bindingHash: prepared.bindingHash,
      reviewPackageHash: prepared.reviewPackageHash,
      candidateRootHash: prepared.candidateRootHash,
      candidateReceiptHash: prepared.candidateReceiptHash,
      reviewerExecutionId: "reviewer-execution-12345678",
      verdict: "pass" as const,
      issues: [],
    };
    const submitInput = {
      action: "submit_review" as const,
      transactionId: prepared.transactionId,
      bindingHash: prepared.bindingHash,
      reviewReceipt,
    };
    await expect(fixture.service.finalize(submitInput)).rejects.toThrow(
      "response lost",
    );

    const restartedOwner = new ExternalUpdateTransactionOwner({
      formalWikiPath: fixture.formalWikiPath,
      runtimeDir: fixture.runtimeDir,
      security: fixture.security,
    });
    const restarted = new OpenWikiExternalUpdateService({
      sensitivePolicyPath: fixture.sensitivePolicyPath,
      skills: { select: fixture.select },
      sources: fixture.sources,
      transactions: restartedOwner,
      publisher: { publishExternal: vi.fn() },
    });
    await expect(restarted.finalize(submitInput)).resolves.toMatchObject({
      status: "published",
      reviewReceiptHash: expect.stringMatching(/^sha256:/u),
    });
    await expect(
      restarted.finalize({
        ...submitInput,
        reviewReceipt: {
          ...reviewReceipt,
          reviewerExecutionId: "other-reviewer-12345678",
        },
      }),
    ).rejects.toMatchObject({ code: "transaction_state_invalid" });
  });

  test("removes Review artifacts when atomic state freeze fails", async () => {
    const faultInjector = vi.fn((point: string) => {
      if (point === "after_review_package") throw new Error("injected");
    });
    const fixture = await createFixture({
      faultInjector,
    });
    const started = asWritable(await fixture.service.begin(fixture.input));

    await expect(
      fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started),
      }),
    ).rejects.toMatchObject({ code: "transaction_state_invalid" });
    expect(faultInjector).toHaveBeenCalledWith("after_review_package");
    await expectNoReviewState(fixture, started);
    await expect(
      stat(
        path.join(
          fixture.runtimeDir,
          "external-updates",
          started.workPackage.transactionId,
          "immutable",
          "review-result-contract.json",
        ),
      ),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });
});

describe("external update host completion", () => {
  test.each([
    ["candidate_writable", "resume_candidate"],
    ["review_ready", "retry_review"],
    ["repair_ready", "resume_candidate"],
    ["attention", "resolve_attention"],
    ["publish_pending", "restore"],
  ] as const)(
    "projects bounded owner status for %s",
    async (stage, nextAction) => {
      const readActive = vi.fn(async () => ({
        state: {
          bindingHash: hash("1"),
          generation: 2,
          stage,
          transactionId: "external-12345678",
        },
        version: "version-1",
      }));
      const service = new OpenWikiExternalUpdateService({
        sensitivePolicyPath: path.join(os.tmpdir(), "sensitive-files.json"),
        skills: { select: vi.fn() } as never,
        sources: { verify: vi.fn() } as never,
        transactions: { readActive } as never,
      });

      await expect(service.status()).resolves.toEqual({
        generation: 2,
        nextAction,
        state: stage,
        transactionId: "external-12345678",
      });
    },
  );

  test.each(["candidate_writer", "reviewer"] as const)(
    "records a bound %s failure without publishing or dropping the candidate",
    async (phase) => {
      const fixture = await createFixture();
      const started = asWritable(await fixture.service.begin(fixture.input));
      let reviewPackageHash: string | undefined;
      if (phase === "reviewer") {
        const prepared = asReviewReady(
          await fixture.service.finalize({
            action: "prepare_review",
            transactionId: started.workPackage.transactionId,
            bindingHash: started.workPackage.bindingHash,
            candidateReceipt: candidateReceipt(started),
          }),
        );
        reviewPackageHash = prepared.reviewPackageHash;
      }
      const publish = vi.spyOn(fixture.publisher, "publishExternal");

      const result = await fixture.service.finalize({
        action: "report_host_failure",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        phase,
        code: "host_timeout",
        message: "The host execution timed out without a result.",
        retryable: true,
        ...(reviewPackageHash === undefined ? {} : { reviewPackageHash }),
      });

      expect(result).toEqual({
        authRequired: false,
        bindingHash: started.workPackage.bindingHash,
        candidateRetained: true,
        executionMode: "external_agent",
        generation: 1,
        nextAction:
          phase === "candidate_writer" ? "resume_candidate" : "retry_review",
        ok: true,
        recovery: { action: "none" },
        status: "external_host_failure",
        transactionId: started.workPackage.transactionId,
      });
      expect(
        toolOutputSchemas.openwiki_finalize_external_update.safeParse(result)
          .success,
      ).toBe(true);
      await expect(fixture.transactions.readActive()).resolves.toMatchObject({
        state: {
          failures: [{ code: "host_timeout", phase, retryable: true }],
          stage:
            phase === "candidate_writer"
              ? "candidate_writable"
              : "review_ready",
        },
      });
      await expect(
        stat(started.workPackage.candidate.rootPath),
      ).resolves.toMatchObject({ isDirectory: expect.any(Function) });
      await expect(
        snapshotMarkdownTree(fixture.formalWikiPath),
      ).resolves.toEqual(fixture.beforeSnapshot);
      expect(publish).not.toHaveBeenCalled();
      expect(JSON.stringify(result)).not.toMatch(/model|provider|process/iu);
    },
  );

  test("aborts a confirmed active update durably and replays it through a fresh service", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));
    const publish = vi.spyOn(fixture.publisher, "publishExternal");
    const resume = vi.spyOn(fixture.transactions, "resume");
    const input = {
      action: "abort" as const,
      transactionId: started.workPackage.transactionId,
      bindingHash: started.workPackage.bindingHash,
      confirmedByUser: true as const,
    };

    const result = await fixture.service.finalize(input);

    expect(result).toEqual({
      authRequired: false,
      bindingHash: started.workPackage.bindingHash,
      executionMode: "external_agent",
      generation: 1,
      ok: true,
      published: false,
      recovery: { action: "none" },
      status: "external_update_aborted",
      transactionId: started.workPackage.transactionId,
    });
    expect(resume).not.toHaveBeenCalled();
    expect(publish).not.toHaveBeenCalled();
    await expect(fixture.transactions.readActive()).resolves.toBeNull();
    await expect(
      stat(started.workPackage.candidate.rootPath),
    ).rejects.toMatchObject({ code: "ENOENT" });
    await expect(snapshotMarkdownTree(fixture.formalWikiPath)).resolves.toEqual(
      fixture.beforeSnapshot,
    );

    const restarted = externalServiceWithOwner(
      fixture,
      new ExternalUpdateTransactionOwner({
        formalWikiPath: fixture.formalWikiPath,
        runtimeDir: fixture.runtimeDir,
        security: fixture.security,
      }),
    );
    await expect(restarted.finalize(input)).resolves.toEqual(result);
    await expect(
      restarted.finalize({ ...input, bindingHash: hash("f") }),
    ).rejects.toMatchObject({ code: "restore_required" });
  });

  test("rejects abort when the retained terminal result is not aborted", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));
    const prepared = asReviewReady(
      await fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started),
      }),
    );
    await expect(
      fixture.service.finalize({
        action: "submit_review",
        transactionId: prepared.transactionId,
        bindingHash: prepared.bindingHash,
        reviewReceipt: reviewReceipt(prepared),
      }),
    ).resolves.toMatchObject({ status: "published" });

    await expect(
      fixture.service.finalize({
        action: "abort",
        transactionId: prepared.transactionId,
        bindingHash: prepared.bindingHash,
        confirmedByUser: true,
      }),
    ).rejects.toMatchObject({ code: "transaction_state_invalid" });
  });

  test("aborts repair-ready state without resuming a successor generation", async () => {
    const fixture = await createFixture();
    const started = asWritable(await fixture.service.begin(fixture.input));
    const prepared = asReviewReady(
      await fixture.service.finalize({
        action: "prepare_review",
        transactionId: started.workPackage.transactionId,
        bindingHash: started.workPackage.bindingHash,
        candidateReceipt: candidateReceipt(started),
      }),
    );
    await expect(
      fixture.service.finalize({
        action: "submit_review",
        transactionId: prepared.transactionId,
        bindingHash: prepared.bindingHash,
        reviewReceipt: reviewReceipt(prepared, {
          verdict: "changes_requested",
          issues: [
            {
              code: "minor_fix",
              message: "Clarify the changed wording.",
              severity: "minor",
            },
          ],
        }),
      }),
    ).resolves.toMatchObject({ status: "repair_ready", generation: 1 });
    const resume = vi.spyOn(fixture.transactions, "resume");

    const result = await fixture.service.finalize({
      action: "abort",
      transactionId: prepared.transactionId,
      bindingHash: prepared.bindingHash,
      confirmedByUser: true,
    });

    expect(result).toMatchObject({
      status: "external_update_aborted",
      generation: 1,
    });
    expect(resume).not.toHaveBeenCalled();
    await expect(fixture.transactions.readActive()).resolves.toBeNull();
    await expect(
      stat(
        path.join(
          fixture.runtimeDir,
          "external-updates",
          prepared.transactionId,
        ),
      ),
    ).rejects.toMatchObject({ code: "ENOENT" });
    await expect(snapshotMarkdownTree(fixture.formalWikiPath)).resolves.toEqual(
      fixture.beforeSnapshot,
    );
  });

  test("replays an abort through a fresh service after terminal-state response loss", async () => {
    const fixture = await createFixture({
      faultInjector(point) {
        if (point === "after_terminal_state") throw new Error("response lost");
      },
    });
    const started = asWritable(await fixture.service.begin(fixture.input));
    const input = {
      action: "abort" as const,
      transactionId: started.workPackage.transactionId,
      bindingHash: started.workPackage.bindingHash,
      confirmedByUser: true as const,
    };
    await expect(fixture.service.finalize(input)).rejects.toThrow(
      "response lost",
    );
    const restarted = externalServiceWithOwner(
      fixture,
      new ExternalUpdateTransactionOwner({
        formalWikiPath: fixture.formalWikiPath,
        runtimeDir: fixture.runtimeDir,
        security: fixture.security,
      }),
    );

    await expect(restarted.finalize(input)).resolves.toMatchObject({
      status: "external_update_aborted",
      generation: 1,
      bindingHash: started.workPackage.bindingHash,
    });
    await expect(fixture.transactions.readActive()).resolves.toBeNull();
    await expect(snapshotMarkdownTree(fixture.formalWikiPath)).resolves.toEqual(
      fixture.beforeSnapshot,
    );
  });
});

async function createFixture(
  options: {
    faultInjector?: (point: string) => void | Promise<void>;
  } = {},
) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-external-service-"));
  roots.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWikiPath = path.join(runtimeDir, "wiki");
  const sensitivePolicyPath = path.join(root, "sensitive-files.json");
  const configPath = path.join(runtimeDir, "config.json");
  const credentialPath = path.join(runtimeDir, "credentials.json");
  await mkdir(formalWikiPath, { recursive: true });
  await writeFile(
    path.join(formalWikiPath, "quickstart.md"),
    "---\ntype: Guide\n---\n\n# Quickstart\n\nSee [home](./index.md).\n",
    "utf8",
  );
  await writeFile(
    path.join(formalWikiPath, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n",
    "utf8",
  );
  await writeFile(
    sensitivePolicyPath,
    `${JSON.stringify({
      contentPatterns: [
        "(?:api[_-]?key|token|secret|password)\\s*[=:]\\s*\\S+",
      ],
      rejectedBaseNames: [],
      rejectedNamePrefixes: [],
      rejectedPathSegments: [],
      rejectedSuffixes: [],
      version: 1,
    })}\n`,
    "utf8",
  );
  const beforeSnapshot = await snapshotMarkdownTree(formalWikiPath);
  const wikiRevision = beforeSnapshot.rootHash;
  const bytes = Buffer.from("# Base Skill\n", "utf8");
  const file = {
    bytes,
    hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
    relativePath: "SKILL.md",
    size: bytes.byteLength,
  };
  const baseSkill: SelectedC7Skill = {
    category: "base" as const,
    description: "Base project Wiki rules.",
    files: [file],
    id: "kg-c7-project-wiki",
    loadOrder: "base_always_first" as const,
    packageHash: computeSkillPackageHash([file]),
    title: "KG C7 Project Wiki",
    verified: true,
  };
  const selected: SelectedC7Skills = {
    aggregateHash: aggregateSkillHash([baseSkill]),
    skills: [baseSkill],
  };
  const sources = { verify: vi.fn() };
  const select = vi.fn<C7SkillRegistry["select"]>(() => selected);
  const security = { securePrivatePath: vi.fn().mockResolvedValue(undefined) };
  const transactions = new ExternalUpdateTransactionOwner({
    createTransactionId: () => "external-12345678",
    createWorkspaceId: () => "workspace-12345678",
    formalWikiPath,
    now: () => new Date("2026-08-12T00:00:00.000Z"),
    runtimeDir,
    security,
    faultInjector: options.faultInjector,
  });
  const publisher = new WikiPublisher({
    formalWikiPath,
    runtimeDir,
    security,
  });
  const service = new OpenWikiExternalUpdateService({
    sensitivePolicyPath,
    skills: {
      select,
    },
    sources,
    transactions,
    publisher,
  });
  return {
    configPath,
    beforeSnapshot,
    baseSkill,
    credentialPath,
    formalWikiPath,
    input: {
      action: "start" as const,
      confirmedByUser: true as const,
      confirmedWikiPaths: ["index.md"],
      expectedWikiRevision: wikiRevision,
      instruction: "Refresh the project overview.",
      materials: [
        { id: "material-1", source: "user-note", content: "Evidence" },
      ],
      requestId: "request-12345678",
    },
    publisher,
    runtimeDir,
    root,
    security,
    sensitivePolicyPath,
    select,
    service,
    sources,
    transactions,
    wikiRevision,
  };
}

function externalServiceWithOwner(
  fixture: Awaited<ReturnType<typeof createFixture>>,
  transactions: ExternalUpdateTransactionOwner,
) {
  return new OpenWikiExternalUpdateService({
    sensitivePolicyPath: fixture.sensitivePolicyPath,
    skills: { select: fixture.select },
    sources: fixture.sources,
    transactions,
    publisher: fixture.publisher,
  });
}

type StartInput = Awaited<ReturnType<typeof createFixture>>["input"];

function candidateReceipt(
  started: ReturnType<typeof asWritable>,
  overrides: Record<string, unknown> = {},
) {
  return {
    type: "external_candidate_receipt" as const,
    version: 1 as const,
    transactionId: started.workPackage.transactionId,
    generation: 1,
    bindingHash: started.workPackage.bindingHash,
    writerExecutionId: "writer-12345678",
    classification: "minor" as const,
    issues: [],
    questions: [],
    summary: "Updated the confirmed Wiki scope.",
    ...overrides,
  };
}

function reviewReceipt(
  prepared: ReturnType<typeof asReviewReady>,
  overrides: Record<string, unknown> = {},
) {
  return {
    type: "external_review_receipt" as const,
    version: 1 as const,
    transactionId: prepared.transactionId,
    generation: prepared.generation,
    bindingHash: prepared.bindingHash,
    reviewPackageHash: prepared.reviewPackageHash,
    candidateRootHash: prepared.candidateRootHash,
    candidateReceiptHash: prepared.candidateReceiptHash,
    reviewerExecutionId: "reviewer-execution-12345678",
    verdict: "pass" as const,
    issues: [],
    ...overrides,
  };
}

async function expectNoReviewState(
  fixture: Awaited<ReturnType<typeof createFixture>>,
  started: ReturnType<typeof asWritable>,
): Promise<void> {
  const state = JSON.parse(
    await readFile(
      path.join(
        fixture.runtimeDir,
        "external-updates",
        started.workPackage.transactionId,
        "state.json",
      ),
      "utf8",
    ),
  ) as { review: unknown; stage: string };
  expect(state).toMatchObject({ stage: "candidate_writable", review: null });
  await expect(
    stat(
      path.join(
        path.dirname(started.workPackage.candidate.rootPath),
        "review-package.json",
      ),
    ),
  ).rejects.toMatchObject({ code: "ENOENT" });
}

async function readPersistedState(
  fixture: Awaited<ReturnType<typeof createFixture>>,
  started: ReturnType<typeof asWritable>,
): Promise<Record<string, unknown>> {
  return JSON.parse(
    await readFile(
      path.join(
        fixture.runtimeDir,
        "external-updates",
        started.workPackage.transactionId,
        "state.json",
      ),
      "utf8",
    ),
  ) as Record<string, unknown>;
}

function makeSkill(id: string, markdown: string): SelectedC7Skill {
  const bytes = Buffer.from(markdown, "utf8");
  const file = {
    bytes,
    hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
    relativePath: "SKILL.md",
    size: bytes.byteLength,
  };
  return {
    category: "specialized" as const,
    description: id,
    files: [file],
    id,
    loadOrder: "request_order" as const,
    packageHash: computeSkillPackageHash([file]),
    title: id,
    verified: true,
  };
}

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}

function canonicalBytes(value: unknown): Buffer {
  return Buffer.from(`${stableJson(value)}\n`, "utf8");
}

function hashCanonicalBytes(domain: string, value: unknown): string {
  return hashDomainBytes(domain, canonicalBytes(value));
}

function hashDomainBytes(domain: string, bytes: Uint8Array): string {
  return `sha256:${createHash("sha256")
    .update(`${domain}\0`, "utf8")
    .update(bytes)
    .digest("hex")}`;
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

function asWritable(value: unknown) {
  if (
    typeof value !== "object" ||
    value === null ||
    !("ok" in value) ||
    value.ok !== true ||
    !("workPackage" in value)
  ) {
    throw new Error("Expected a writable external update outcome.");
  }
  return value as {
    authRequired: false;
    executionMode: "external_agent";
    ok: true;
    recovery: { action: "none" };
    status: "external_update_ready" | "external_update_resumed";
    workPackage: {
      bindingHash: string;
      candidate: { rootPath: string };
      requestPackage: { path: string; packageHash: string };
      sources: null | { rootPath: string };
      rules: {
        hardRulePackage: { path: string; packageHash: string };
        skills: readonly { id: string; rootPath: string }[];
        candidateResultContract: { path: string; schemaHash: string };
      };
      transactionId: string;
      [key: string]: unknown;
    };
  };
}

function asReviewReady(value: unknown) {
  if (
    typeof value !== "object" ||
    value === null ||
    !("ok" in value) ||
    value.ok !== true ||
    !("reviewPackage" in value)
  ) {
    throw new Error("Expected an external Review-ready outcome.");
  }
  return value as {
    ok: true;
    executionMode: "external_agent";
    authRequired: false;
    status: "external_review_ready" | "external_review_resumed";
    transactionId: string;
    generation: number;
    bindingHash: string;
    candidateRootHash: string;
    candidateReceiptHash: string;
    reviewPackageHash: string;
    reviewPackage: {
      candidateReceiptHash: string;
      rules: {
        reviewResultContract: { path: string; schemaHash: string };
        [key: string]: unknown;
      };
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
}
