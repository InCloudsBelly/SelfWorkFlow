import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { toolOutputSchemas } from "../src/contracts.js";
import { C7ProcessError } from "../src/process.js";
import { WikiPublisher } from "../src/publish.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type SelectedC7Skill,
  type SelectedC7Skills,
} from "../src/skills.js";
import { C7TransactionFactory } from "../src/transaction.js";
import {
  OpenWikiUpdateService,
  type UpdateProcessRunner,
  type UpdateReviewer,
} from "../src/update.js";
import { hashSourceSnapshotTree } from "../src/sources.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";

const tempDirs: string[] = [];
const selection = { model: "gpt-5.6-sol", reasoningEffort: "xhigh" as const };
type ResultFailureStage =
  | "result_binding_mismatch"
  | "result_json_invalid"
  | "result_missing"
  | "result_schema_invalid";

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("openwiki_update transaction", () => {
  test("returns a structured conflict before starting the model when the confirmed Wiki revision is stale", async () => {
    const fixture = await createFixture();
    await writeFile(
      path.join(fixture.formalWikiPath, "quickstart.md"),
      page("# Concurrent change\n"),
      "utf8",
    );
    const actualRevision = (await snapshotMarkdownTree(fixture.formalWikiPath))
      .rootHash;

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Do not overwrite the concurrent change.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        baseWikiRevision: actualRevision,
        published: false,
        status: "conflict",
      }),
    );
    expect(fixture.processRunner.run).not.toHaveBeenCalled();
    expect(fixture.createHomeLease).not.toHaveBeenCalled();
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toBe(page("# Concurrent change\n"));
  });

  test("returns a non-null base revision when transaction creation fails", async () => {
    const fixture = await createFixture({ createHomeLeaseFails: true });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update the Wiki.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        baseWikiRevision: fixture.initialRevision,
        published: false,
        status: "failed",
      }),
    );
    expect(fixture.processRunner.run).not.toHaveBeenCalled();
  });

  test("rejects missing confirmation before sources, model, or transaction work", async () => {
    const fixture = await createFixture();

    await expect(
      fixture.service.update({
        executionMode: "legacy_provider",
        confirmedByUser: false,
        instruction: "Update the Wiki.",
      }),
    ).rejects.toEqual(
      expect.objectContaining({ code: "confirmation_required" }),
    );
    expect(fixture.processRunner.run).not.toHaveBeenCalled();
    expect(fixture.createHomeLease).not.toHaveBeenCalled();
    expect(fixture.reviewer.review).not.toHaveBeenCalled();
  });

  test("publishes a validated minor update and completes mandatory review", async () => {
    const fixture = await createFixture({
      expectFormalWikiUnchangedDuringReview: true,
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update rendering ownership.",
    });

    expect(toolOutputSchemas.openwiki_update.parse(result)).toEqual(result);
    expect(result).toEqual(
      expect.objectContaining({
        model: {
          providerAccepted: true,
          requested: selection,
          sent: selection,
        },
        ok: true,
        published: true,
        recoveryState: "clean",
        review: { rounds: 1, status: "passed" },
        status: "published",
      }),
    );
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toContain("Updated rendering ownership");
    expect(fixture.reviewer.review).toHaveBeenCalledWith(
      expect.objectContaining({
        candidateId: expect.stringMatching(/^run-/u),
        reviewedRootHash: expect.stringMatching(/^sha256:/u),
        selection,
      }),
    );
    expect(fixture.publish).toHaveBeenCalledTimes(1);
  });

  test("publishes exactly the two explicitly confirmed business pages", async () => {
    const fixture = await createFixture({ writesBusinessPages: 2 });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      confirmedWikiPaths: ["quickstart.md", "sources/kgpr-source-set.md"],
      expectedWikiRevision: fixture.initialRevision,
      instruction:
        "Publish the confirmed quickstart and KGPR source-set pages.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        published: true,
        status: "published",
        validation: expect.objectContaining({ passed: true }),
      }),
    );
    expect(
      (await snapshotMarkdownTree(fixture.formalWikiPath)).files.map(
        (file) => file.relativePath,
      ),
    ).toEqual(["quickstart.md", "sources/kgpr-source-set.md"]);
    expect(fixture.reviewer.review).toHaveBeenCalledTimes(1);
  });

  test("rejects a valid third business page outside the confirmed scope before first publication", async () => {
    const fixture = await createFixture({ writesBusinessPages: 3 });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      confirmedWikiPaths: ["quickstart.md", "sources/kgpr-source-set.md"],
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Publish only the two confirmed Wiki pages.",
    });
    const parsedResult = toolOutputSchemas.openwiki_update.parse(result);
    if (!("validation" in parsedResult)) {
      throw new Error("expected a transaction update result");
    }

    expect(parsedResult).toEqual(
      expect.objectContaining({
        baseWikiRevision: fixture.initialRevision,
        changes: [],
        published: false,
        review: { rounds: 0, status: "not_run" },
        status: "failed",
      }),
    );
    expect(
      parsedResult.validation.checks
        .filter((check) => check.status === "failed")
        .map((check) => check.id),
    ).toEqual(["change_scope"]);
    expect((await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash).toBe(
      fixture.initialRevision,
    );
    expect(fixture.publish).not.toHaveBeenCalled();
    expect(fixture.reviewer.review).not.toHaveBeenCalled();
    expect(fixture.cleanup).toHaveBeenCalledTimes(1);
    await expectCleanRuntime(fixture.runtimeDir);
  });

  test("does not publish a blocking model result and returns clarification", async () => {
    const fixture = await createFixture({ classification: "blocking" });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update uncertain ownership.",
    });

    expect(toolOutputSchemas.openwiki_update.parse(result)).toEqual(result);
    expect(result).toEqual(
      expect.objectContaining({
        published: false,
        questions: ["Which team owns this runtime?"],
        status: "needs_clarification",
      }),
    );
    expect(fixture.reviewer.review).not.toHaveBeenCalled();
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toContain("Before");
    expect(fixture.publish).not.toHaveBeenCalled();
    await expect(
      readdir(path.join(fixture.runtimeDir, "recovery")).catch(() => []),
    ).resolves.toEqual([]);
  });

  test("keeps a provisional publication and returns explicit follow-up", async () => {
    const issue = {
      code: "owner_unverified",
      message: "Runtime owner is provisional.",
      severity: "provisional" as const,
    };
    const fixture = await createFixture({
      classification: "provisional",
      reviewResult: { issues: [issue], verdict: "follow_up" },
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update with provisional ownership.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        followUp: [issue],
        published: true,
        review: { issues: [issue], rounds: 1, status: "follow_up" },
        status: "published_with_follow_up",
      }),
    );
  });

  test("does not publish a deterministically invalid candidate", async () => {
    const fixture = await createFixture({ invalidCandidate: true });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Write an invalid candidate.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        failure: expect.objectContaining({ code: "validation_failed" }),
        published: false,
        status: "failed",
      }),
    );
    expect(fixture.reviewer.review).not.toHaveBeenCalled();
  });

  test.each([
    "result_missing",
    "result_json_invalid",
    "result_schema_invalid",
  ] as const)(
    "finalizes one %s update result read-only",
    async (failureStage) => {
      const fixture = await createFixture({
        finalizerResult: "valid",
        resultFailure: failureStage,
        writesRuntimeMetadata: true,
      });

      const result = await fixture.service.update({
        executionMode: "legacy_provider",
        confirmedByUser: true,
        expectedWikiRevision: fixture.initialRevision,
        instruction:
          "Finalize the bound result without rewriting the candidate.",
      });

      expect(result).toEqual(
        expect.objectContaining({
          published: true,
          status: "published",
        }),
      );
      expect(fixture.processRunner.run).toHaveBeenCalledTimes(2);
      expect(fixture.processRunner.run.mock.calls[0]?.[0]).toEqual(
        expect.objectContaining({ operation: "update", selection }),
      );
      expect(fixture.processRunner.run.mock.calls[1]?.[0]).toEqual(
        expect.objectContaining({
          operation: "query",
          requestFileName: "result-finalizer.md",
          selection,
        }),
      );
      expect(fixture.processRunner.run.mock.calls[1]?.[0].policyPath).not.toBe(
        fixture.processRunner.run.mock.calls[0]?.[0].policyPath,
      );
      expect(
        await readFile(
          path.join(fixture.formalWikiPath, "quickstart.md"),
          "utf8",
        ),
      ).toContain("Updated rendering ownership");
      expect(fixture.reviewer.review).toHaveBeenCalledTimes(1);
    },
  );

  test("provides the exact strict update-result contract to update, repair, and finalizer passes", async () => {
    const repairFixture = await createFixture({
      reviewResults: [
        {
          issues: [
            {
              code: "link_label",
              message: "Clarify one relationship label.",
              page: "quickstart.md",
              severity: "minor",
            },
          ],
          verdict: "auto_fixable",
        },
        { issues: [], verdict: "pass" },
      ],
    });
    await repairFixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: repairFixture.initialRevision,
      instruction: "Update, review, and repair with a strict result.",
    });

    const finalizerFixture = await createFixture({
      finalizerResult: "valid",
      resultFailure: "result_missing",
    });
    await finalizerFixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: finalizerFixture.initialRevision,
      instruction: "Finalize one strict result.",
    });

    const observed = [
      ...repairFixture.observedProcessRequests,
      ...finalizerFixture.observedProcessRequests,
    ];
    expect(
      observed.map(
        (request) => `${request.operation}:${request.requestFileName}`,
      ),
    ).toEqual([
      "update:request.md",
      "repair:request.md",
      "update:request.md",
      "query:result-finalizer.md",
    ]);
    for (const request of observed) {
      expect(request.text).toContain(
        "Top-level keys must be exactly binding, classification, issues, questions, summary, type, version.",
      );
      expect(request.text).toContain(
        "Each issue permits exactly code, message, optional page, and severity.",
      );
      expect(request.text).toContain(
        "minor requires zero questions and every issue must be minor; provisional requires at least one provisional issue; blocking requires at least one blocking issue and at least one question.",
      );
    }
  });

  test("normalizes root metadata before finalization and preserves both business pages byte-for-byte", async () => {
    const fixture = await createFixture({
      finalizerResult: "valid",
      resultFailure: "result_missing",
      writesRuntimeMetadata: true,
      writesBusinessPages: 2,
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      confirmedWikiPaths: ["quickstart.md", "sources/kgpr-source-set.md"],
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Finalize the exact two-page candidate.",
    });

    expect(result).toEqual(
      expect.objectContaining({ published: true, status: "published" }),
    );
    expect(fixture.finalizerCandidateSnapshots).toHaveLength(2);
    expect(
      fixture.finalizerCandidateSnapshots[0]?.files.map(
        (file) => file.relativePath,
      ),
    ).toEqual(["quickstart.md", "sources/kgpr-source-set.md"]);
    expect(fixture.finalizerCandidateSnapshots[1]).toEqual(
      fixture.finalizerCandidateSnapshots[0],
    );
    expect(
      (await snapshotMarkdownTree(fixture.formalWikiPath)).files.map(
        (file) => file.relativePath,
      ),
    ).toEqual(["quickstart.md", "sources/kgpr-source-set.md"]);
  });

  test("does not publish when the result finalizer changes the candidate Wiki", async () => {
    const fixture = await createFixture({
      finalizerMutatesCandidate: true,
      finalizerResult: "valid",
      resultFailure: "result_missing",
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Keep the candidate immutable during result finalization.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        failure: expect.objectContaining({
          code: "process_failure",
          details: {
            diagnostic: "stage=result-finalizer-candidate-integrity",
          },
        }),
        published: false,
        status: "failed",
      }),
    );
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(2);
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toBe(page("# Before\n"));
    expect(fixture.reviewer.review).not.toHaveBeenCalled();
  });

  test("returns a sanitized diagnostic when the result finalizer process fails", async () => {
    const fixture = await createFixture({
      finalizerProcessFails: true,
      resultFailure: "result_missing",
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Report a bounded finalizer failure without leaking data.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        failure: expect.objectContaining({
          code: "process_failure",
          details: {
            diagnostic:
              "stage=result-finalizer-process; stage=cli-import; token=[REDACTED]",
          },
        }),
        published: false,
        status: "failed",
      }),
    );
    expect(JSON.stringify(result)).not.toContain("secret-finalizer-canary");
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(2);
  });

  test.each<ResultFailureStage>([
    "result_missing",
    "result_json_invalid",
    "result_schema_invalid",
    "result_binding_mismatch",
  ])(
    "returns %s after model completion without publishing the candidate",
    async (failureStage) => {
      const fixture = await createFixture({ resultFailure: failureStage });

      const result = await fixture.service.update({
        executionMode: "legacy_provider",
        confirmedByUser: true,
        expectedWikiRevision: fixture.initialRevision,
        instruction: "Update from a strictly bound model result.",
      });

      expect(toolOutputSchemas.openwiki_update.parse(result)).toEqual(result);
      expect(result).toEqual(
        expect.objectContaining({
          failure: expect.objectContaining({
            code: "process_failure",
            details: { failureStage },
          }),
          model: expect.objectContaining({ providerAccepted: true }),
          published: false,
          status: "failed",
        }),
      );
      expect(JSON.stringify(result)).not.toContain("secret-result-canary");
      expect(
        await readFile(
          path.join(fixture.formalWikiPath, "quickstart.md"),
          "utf8",
        ),
      ).toBe(page("# Before\n"));
      expect(fixture.reviewer.review).not.toHaveBeenCalled();
      expect(fixture.processRunner.run).toHaveBeenCalledTimes(
        failureStage === "result_binding_mismatch" ? 1 : 2,
      );
    },
  );

  test("preserves a structured result stage and formal Wiki when candidate review fails", async () => {
    const fixture = await createFixture({
      reviewFailureStage: "result_schema_invalid",
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update and retain a safe review failure stage.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        failure: expect.objectContaining({
          code: "process_failure",
          details: { failureStage: "result_schema_invalid" },
        }),
        published: false,
        status: "failed",
      }),
    );
    expect((await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash).toBe(
      fixture.initialRevision,
    );
  });

  test("retries two transient provider failures in fresh transaction homes", async () => {
    const fixture = await createFixture({ providerTransientFailures: 2 });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Retry only transient provider failures.",
    });

    expect(result).toEqual(
      expect.objectContaining({ published: true, status: "published" }),
    );
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(3);
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(3);
    const attempts = fixture.operationAttempts.filter(
      (attempt) => attempt.operation === "update",
    );
    expect(attempts).toHaveLength(3);
    expect(attempts.map((attempt) => attempt.binding)).toEqual([
      attempts[0]!.binding,
      attempts[0]!.binding,
      attempts[0]!.binding,
    ]);
    expect(new Set(attempts.map((attempt) => attempt.homePath)).size).toBe(3);
    expect(fixture.failedHomePaths).toEqual([
      attempts[0]!.homePath,
      attempts[1]!.homePath,
    ]);
    await expectFailureSentinelsRemoved(fixture.failedHomePaths);
    expect(fixture.cleanup).toHaveBeenCalledTimes(3);
  });

  test("stops after three total transient provider attempts", async () => {
    const fixture = await createFixture({ providerTransientFailures: 3 });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Stop bounded transient retries.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        failure: expect.objectContaining({
          code: "provider_failure",
          details: {
            providerStatusClass: "5xx",
            retryAfterMs: 0,
          },
          retryable: true,
        }),
        published: false,
        status: "failed",
      }),
    );
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(3);
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(3);
    expect((await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash).toBe(
      fixture.initialRevision,
    );
  });

  test("stops before generation retry when the trusted formal Wiki drifts during backoff", async () => {
    const fixture = await createFixture({
      providerTransientFailures: 1,
      retryDrift: "formal",
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Stop before retrying a drifted formal Wiki.",
    });

    expect(result).toEqual(
      expect.objectContaining({ published: false, status: "conflict" }),
    );
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(1);
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(1);
    expect(fixture.publish).not.toHaveBeenCalled();
    await expectFailureSentinelsRemoved(fixture.failedHomePaths);
  });

  test("does not retry a rejected provider response", async () => {
    const fixture = await createFixture({ providerRejectedFailures: 1 });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Do not retry a rejected provider request.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        failure: expect.objectContaining({
          code: "provider_failure",
          details: {
            providerStatusClass: "4xx",
            retryAfterMs: 1_200,
          },
          retryable: false,
        }),
        published: false,
        status: "failed",
      }),
    );
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(1);
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(1);
  });

  test.each([
    "aborted",
    "model_mismatch",
    "output_limit",
    "timeout",
    "untrusted_executable",
  ] as const)(
    "does not retry non-transient process failure %s",
    async (code) => {
      const fixture = await createFixture({ nonRetryableProcessFailure: code });

      const result = await fixture.service.update({
        executionMode: "legacy_provider",
        confirmedByUser: true,
        expectedWikiRevision: fixture.initialRevision,
        instruction: "Do not retry this process failure.",
      });

      expect(result).toEqual(
        expect.objectContaining({ published: false, status: "failed" }),
      );
      expect(fixture.createHomeLease).toHaveBeenCalledTimes(1);
      expect(fixture.processRunner.run).toHaveBeenCalledTimes(1);
    },
  );

  test("returns candidate review attention without publishing the Wiki", async () => {
    const issue = {
      code: "scope_question",
      message: "The page boundary needs user confirmation.",
      severity: "blocking" as const,
    };
    const fixture = await createFixture({
      reviewResult: { issues: [issue], verdict: "requires_user" },
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update and review.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        issues: [issue],
        published: false,
        recoveryState: "clean",
        status: "needs_clarification",
      }),
    );
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toContain("Before");
  });

  test("runs a fresh bounded repair transaction and reviews again", async () => {
    const minorIssue = {
      code: "link_label",
      message: "Clarify one relationship label.",
      page: "quickstart.md",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      reviewResults: [
        { issues: [minorIssue], verdict: "auto_fixable" },
        { issues: [], verdict: "pass" },
      ],
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update, review, and repair.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        published: true,
        review: { rounds: 2, status: "passed" },
        status: "published",
      }),
    );
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update", "repair"]);
    expect(fixture.reviewer.review).toHaveBeenCalledTimes(2);
    expect(fixture.publish).toHaveBeenCalledTimes(1);
  });

  test("retries two transient repairs in fresh candidate transactions", async () => {
    const minorIssue = {
      code: "link_label",
      message: "Clarify one relationship label.",
      page: "quickstart.md",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      providerTransientRepairFailures: 2,
      reviewResults: [
        { issues: [minorIssue], verdict: "auto_fixable" },
        { issues: [], verdict: "pass" },
      ],
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Retry two transient repairs.",
    });

    expect(fixture.createHomeLease).toHaveBeenCalledTimes(4);
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update", "repair", "repair", "repair"]);
    expect(result).toEqual(
      expect.objectContaining({ published: true, status: "published" }),
    );
    const attempts = fixture.operationAttempts.filter(
      (attempt) => attempt.operation === "repair",
    );
    expect(attempts).toHaveLength(3);
    expect(attempts.map((attempt) => attempt.binding)).toEqual([
      attempts[0]!.binding,
      attempts[0]!.binding,
      attempts[0]!.binding,
    ]);
    expect(new Set(attempts.map((attempt) => attempt.homePath)).size).toBe(3);
    expect(fixture.failedHomePaths).toEqual([
      attempts[0]!.homePath,
      attempts[1]!.homePath,
    ]);
    await expectFailureSentinelsRemoved(fixture.failedHomePaths);
    expect(fixture.cleanup).toHaveBeenCalledTimes(4);
  });

  test("stops after three total transient repair attempts without publishing", async () => {
    const minorIssue = {
      code: "link_label",
      message: "Clarify one relationship label.",
      page: "quickstart.md",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      providerTransientRepairFailures: 3,
      reviewResult: { issues: [minorIssue], verdict: "auto_fixable" },
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Stop bounded transient repair retries.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        failure: expect.objectContaining({ code: "provider_failure" }),
        published: false,
        status: "failed",
      }),
    );
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(4);
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update", "repair", "repair", "repair"]);
    expect(fixture.publish).not.toHaveBeenCalled();
    expect((await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash).toBe(
      fixture.initialRevision,
    );
  });

  test("stops before repair retry when the trusted candidate baseline drifts during backoff", async () => {
    const minorIssue = {
      code: "link_label",
      message: "Clarify one relationship label.",
      page: "quickstart.md",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      providerTransientRepairFailures: 1,
      retryDrift: "candidate",
      reviewResult: { issues: [minorIssue], verdict: "auto_fixable" },
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Stop before retrying a drifted repair candidate.",
    });

    expect(result).toEqual(
      expect.objectContaining({ published: false, status: "failed" }),
    );
    expect(
      fixture.operationAttempts.map((attempt) => attempt.operation),
    ).toEqual(["update", "repair"]);
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(2);
    expect(fixture.publish).not.toHaveBeenCalled();
    expect((await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash).toBe(
      fixture.initialRevision,
    );
    await expectFailureSentinelsRemoved(fixture.failedHomePaths);
  });

  test("normalizes root metadata and narrows repair to confirmed review pages", async () => {
    const minorIssue = {
      code: "link_label",
      message: "Clarify the quickstart relationship label.",
      page: "quickstart.md",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      reviewResults: [
        { issues: [minorIssue], verdict: "auto_fixable" },
        { issues: [], verdict: "pass" },
      ],
      writesBusinessPages: 2,
      writesRuntimeMetadata: true,
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      confirmedWikiPaths: ["quickstart.md", "sources/kgpr-source-set.md"],
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Publish and repair only the two confirmed business pages.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        published: true,
        review: { rounds: 2, status: "passed" },
        status: "published",
      }),
    );
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update", "repair"]);
    expect(fixture.updateBindings).toEqual([
      expect.objectContaining({
        confirmedWikiPaths: ["quickstart.md", "sources/kgpr-source-set.md"],
        operation: "update",
      }),
      expect.objectContaining({
        confirmedWikiPaths: ["quickstart.md"],
        operation: "repair",
      }),
    ]);
    expect(
      (await snapshotMarkdownTree(fixture.formalWikiPath)).files.map(
        (file) => file.relativePath,
      ),
    ).toEqual(["quickstart.md", "sources/kgpr-source-set.md"]);
  });

  test("maps bounded repair normalization failure to candidate-normalization", async () => {
    const minorIssue = {
      code: "link_label",
      message: "Clarify the quickstart relationship label.",
      page: "quickstart.md",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      reviewResult: { issues: [minorIssue], verdict: "auto_fixable" },
      writesInvalidRuntimeMetadataOnRepair: true,
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      confirmedWikiPaths: ["quickstart.md"],
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Repair only the confirmed quickstart page.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        failure: expect.objectContaining({
          code: "process_failure",
          details: { diagnostic: "stage=candidate-normalization" },
        }),
        published: false,
        status: "failed",
      }),
    );
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update", "repair"]);
    expect(fixture.reviewer.review).toHaveBeenCalledTimes(1);
    expect(fixture.publish).not.toHaveBeenCalled();
    await expectCleanRuntime(fixture.runtimeDir);
    expect(fixture.cleanup).toHaveBeenCalledTimes(2);
  });

  test("does not repair a reviewed page outside the initial confirmed set", async () => {
    const outsideIssue = {
      code: "source_label",
      message: "Clarify a source page outside the confirmed scope.",
      page: "sources/kgpr-source-set.md",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      reviewResult: { issues: [outsideIssue], verdict: "auto_fixable" },
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      confirmedWikiPaths: ["quickstart.md"],
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update only quickstart.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        issues: [outsideIssue],
        published: false,
        status: "needs_clarification",
      }),
    );
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update"]);
    expect(fixture.updateBindings).toEqual([
      expect.objectContaining({
        confirmedWikiPaths: ["quickstart.md"],
        operation: "update",
      }),
    ]);
    expect(fixture.reviewer.review).toHaveBeenCalledTimes(1);
  });

  test.each(["missing", "invalid-metadata"] as const)(
    "fails closed with a normalized diagnostic when the candidate is %s",
    async (failure) => {
      const fixture = await createFixture({
        candidateMissingAfterRun: failure === "missing",
        writesInvalidRuntimeMetadata: failure === "invalid-metadata",
      });

      const result = await fixture.service.update({
        executionMode: "legacy_provider",
        confirmedByUser: true,
        expectedWikiRevision: fixture.initialRevision,
        instruction: "Fail closed before publication.",
      });

      expect(result).toEqual(
        expect.objectContaining({
          baseWikiRevision: fixture.initialRevision,
          changes: [],
          failure: expect.objectContaining({
            code: "process_failure",
            details: { diagnostic: "stage=candidate-normalization" },
          }),
          published: false,
          review: { rounds: 0, status: "not_run" },
          status: "failed",
        }),
      );
      expect(
        (await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash,
      ).toBe(fixture.initialRevision);
      expect(fixture.reviewer.review).not.toHaveBeenCalled();
      await expectCleanRuntime(fixture.runtimeDir);
      expect(fixture.cleanup).toHaveBeenCalledTimes(1);
    },
  );

  test("does not delete extra indexes or traverse a candidate junction before failing closed", async () => {
    const fixture = await createFixture({
      writesCandidateJunction: true,
      writesUpstreamIndexes: true,
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Do not publish indexes or traverse candidate junctions.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        baseWikiRevision: fixture.initialRevision,
        changes: [],
        failure: expect.objectContaining({ code: "validation_failed" }),
        published: false,
        review: { rounds: 0, status: "not_run" },
        status: "failed",
      }),
    );
    await expect(readFile(fixture.outsideIndexPath, "utf8")).resolves.toBe(
      "outside index\n",
    );
    await expect(readFile(fixture.outsideSentinelPath, "utf8")).resolves.toBe(
      "outside sentinel\n",
    );
    expect((await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash).toBe(
      fixture.initialRevision,
    );
    expect(fixture.reviewer.review).not.toHaveBeenCalled();
    await expectCleanRuntime(fixture.runtimeDir);
    expect(fixture.cleanup).toHaveBeenCalledTimes(1);
  });

  test("maps finalizer normalization failure to candidate-normalization", async () => {
    const fixture = await createFixture({
      finalizerResult: "valid",
      resultFailure: "result_missing",
      writesInvalidRuntimeMetadata: true,
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Fail before finalization when normalization is invalid.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        baseWikiRevision: fixture.initialRevision,
        changes: [],
        failure: expect.objectContaining({
          code: "process_failure",
          details: { diagnostic: "stage=candidate-normalization" },
        }),
        published: false,
        review: { rounds: 0, status: "not_run" },
        status: "failed",
      }),
    );
    expect((await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash).toBe(
      fixture.initialRevision,
    );
    expect(fixture.reviewer.review).not.toHaveBeenCalled();
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(1);
    await expectCleanRuntime(fixture.runtimeDir);
    expect(fixture.cleanup).toHaveBeenCalledTimes(1);
  });

  test("keeps finalizer snapshot failure distinct after normalization succeeds", async () => {
    const fixture = await createFixture({
      finalizerResult: "valid",
      resultFailure: "result_missing",
      writesCandidateJunction: true,
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Fail at the finalizer snapshot boundary.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        baseWikiRevision: fixture.initialRevision,
        changes: [],
        failure: expect.objectContaining({
          code: "process_failure",
          details: {
            diagnostic: "stage=result-finalizer-candidate-snapshot",
          },
        }),
        published: false,
        review: { rounds: 0, status: "not_run" },
        status: "failed",
      }),
    );
    expect((await snapshotMarkdownTree(fixture.formalWikiPath)).rootHash).toBe(
      fixture.initialRevision,
    );
    expect(fixture.reviewer.review).not.toHaveBeenCalled();
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(1);
    await expectCleanRuntime(fixture.runtimeDir);
    expect(fixture.cleanup).toHaveBeenCalledTimes(1);
  });

  test("stops after two autonomous repairs and returns attention", async () => {
    const minorIssue = {
      code: "still_minor",
      message: "The same bounded issue remains.",
      page: "quickstart.md",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      reviewResults: Array.from({ length: 3 }, () => ({
        issues: [minorIssue],
        verdict: "auto_fixable" as const,
      })),
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Try bounded repairs only.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        published: false,
        review: expect.objectContaining({ rounds: 3 }),
        status: "needs_clarification",
      }),
    );
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update", "repair", "repair"]);
    expect(fixture.publish).not.toHaveBeenCalled();
  });

  test("does not start autonomous repair when review omits an exact page scope", async () => {
    const issue = {
      code: "unscoped_fix",
      message: "The fix has no page binding.",
      severity: "minor" as const,
    };
    const fixture = await createFixture({
      reviewResult: { issues: [issue], verdict: "auto_fixable" },
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Keep autonomous repairs bounded.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        issues: [issue],
        published: false,
        status: "needs_clarification",
      }),
    );
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update"]);
  });

  test("fails closed before repair when the reviewed Wiki root drifts", async () => {
    const fixture = await createFixture({
      driftBeforeRepair: true,
      reviewResult: {
        issues: [
          {
            code: "bounded_fix",
            message: "Repair the reviewed page.",
            page: "quickstart.md",
            severity: "minor",
          },
        ],
        verdict: "auto_fixable",
      },
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Do not repair a stale reviewed root.",
    });

    expect(result).toEqual(
      expect.objectContaining({
        published: false,
        status: "failed",
      }),
    );
    expect(
      fixture.processRunner.run.mock.calls.map((call) => call[0].operation),
    ).toEqual(["update"]);
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toContain("Before");
  });

  test("returns published attention when confirmed source cleanup fails", async () => {
    const fixture = await createFixture({ sourceCleanupFails: true });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update with confirmed source.",
      sourceConfirmation: "confirm-source:source-12345678:bound",
      sourceManifestId: "source-12345678",
    });

    expect(result).toEqual(
      expect.objectContaining({
        baseWikiRevision: fixture.initialRevision,
        failure: expect.objectContaining({ code: "process_failure" }),
        published: true,
        status: "review_requires_attention",
      }),
    );
  });

  test("preserves the locked revision when cleanup fails before publication", async () => {
    const fixture = await createFixture({
      classification: "blocking",
      sourceCleanupFails: true,
    });

    const result = await fixture.service.update({
      executionMode: "legacy_provider",
      confirmedByUser: true,
      expectedWikiRevision: fixture.initialRevision,
      instruction: "Update with a blocking gap.",
      sourceConfirmation: "confirm-source:source-12345678:bound",
      sourceManifestId: "source-12345678",
    });

    expect(result).toEqual(
      expect.objectContaining({
        baseWikiRevision: fixture.initialRevision,
        failure: expect.objectContaining({ code: "process_failure" }),
        published: false,
        status: "failed",
      }),
    );
  });
});

async function createFixture(
  options: {
    candidateMissingAfterRun?: boolean;
    classification?: "blocking" | "minor" | "provisional";
    driftBeforeRepair?: boolean;
    expectFormalWikiUnchangedDuringReview?: boolean;
    finalizerMutatesCandidate?: boolean;
    finalizerProcessFails?: boolean;
    finalizerResult?: "missing" | "valid";
    invalidCandidate?: boolean;
    nonRetryableProcessFailure?: C7ProcessError["code"];
    providerRejectedFailures?: number;
    providerTransientFailures?: number;
    providerTransientRepairFailures?: number;
    retryDrift?: "candidate" | "formal";
    resultFailure?: ResultFailureStage;
    reviewFailureStage?: ResultFailureStage;
    writesCandidateJunction?: boolean;
    writesInvalidRuntimeMetadata?: boolean;
    writesInvalidRuntimeMetadataOnRepair?: boolean;
    writesRuntimeMetadata?: boolean;
    writesUpstreamIndexes?: boolean;
    writesBusinessPages?: 2 | 3;
    reviewResult?: {
      issues: Array<{
        code: string;
        message: string;
        page?: string;
        severity: "blocking" | "minor" | "provisional";
      }>;
      verdict: "auto_fixable" | "follow_up" | "pass" | "requires_user";
    };
    reviewResults?: Array<{
      issues: Array<{
        code: string;
        message: string;
        page?: string;
        severity: "blocking" | "minor" | "provisional";
      }>;
      verdict: "auto_fixable" | "follow_up" | "pass" | "requires_user";
    }>;
    createHomeLeaseFails?: boolean;
    sourceCleanupFails?: boolean;
  } = {},
) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-update-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWikiPath = path.join(runtimeDir, "wiki");
  const outsideWikiPath = path.join(root, "outside-wiki");
  const outsideIndexPath = path.join(outsideWikiPath, "index.md");
  const outsideSentinelPath = path.join(outsideWikiPath, "sentinel.txt");
  const sensitivePolicyPath = path.join(root, "sensitive.json");
  const sourceSnapshotPath = path.join(root, "source-snapshot");
  await mkdir(formalWikiPath, { recursive: true });
  await mkdir(outsideWikiPath, { recursive: true });
  await writeFile(outsideIndexPath, "outside index\n", "utf8");
  await writeFile(outsideSentinelPath, "outside sentinel\n", "utf8");
  await mkdir(path.join(sourceSnapshotPath, "000000"), { recursive: true });
  await writeFile(
    path.join(sourceSnapshotPath, "000000", "source.cpp"),
    "int Source;\n",
    "utf8",
  );
  await writeFile(
    path.join(formalWikiPath, "quickstart.md"),
    page("# Before\n"),
    "utf8",
  );
  const initialRevision = (await snapshotMarkdownTree(formalWikiPath)).rootHash;
  await writeFile(
    sensitivePolicyPath,
    `${JSON.stringify({
      contentPatterns: ["Authorization\\s*:\\s*Bearer\\s+[^\\s]+"],
      rejectedBaseNames: [".env"],
      rejectedNamePrefixes: [],
      rejectedPathSegments: [],
      rejectedSuffixes: [".pem"],
      version: 1,
    })}\n`,
    "utf8",
  );
  const cleanup = vi.fn<() => Promise<void>>(async () => undefined);
  const finalize = vi.fn(async () => undefined);
  const createHomeLease = vi.fn(async () => {
    if (options.createHomeLeaseFails) throw new Error("lease failed");
    const home = await mkdtemp(path.join(root, "home-"));
    return {
      cleanup: async () => {
        await cleanup();
        await rm(home, { force: true, recursive: true });
      },
      finalize,
      path: home,
    };
  });
  let runSequence = 0;
  let providerTransientFailures = options.providerTransientFailures ?? 0;
  let providerTransientRepairFailures =
    options.providerTransientRepairFailures ?? 0;
  let providerRejectedFailures = options.providerRejectedFailures ?? 0;
  let nonRetryableProcessFailure = options.nonRetryableProcessFailure;
  const security = { securePrivatePath: vi.fn().mockResolvedValue(undefined) };
  const transactions = new C7TransactionFactory({
    createHomeLease,
    createRunId: () => `run-update-${String(++runSequence).padStart(8, "0")}`,
    formalWikiPath,
    runtimeDir,
    security,
  });
  const skills = selectedSkills();
  const updateBindings: Array<Record<string, unknown>> = [];
  const operationAttempts: Array<{
    binding: Record<string, unknown>;
    homePath: string;
    operation: "repair" | "update";
  }> = [];
  const failedHomePaths: string[] = [];
  let trustedCandidateWikiPath: string | undefined;
  let lastTransientOperation: "repair" | "update" | undefined;
  const observedProcessRequests: Array<{
    operation: string;
    requestFileName: string;
    text: string;
  }> = [];
  const processRunner = {
    run: vi.fn(async (input: Parameters<UpdateProcessRunner["run"]>[0]) => {
      const isFinalizer = input.requestFileName === "result-finalizer.md";
      const binding = JSON.parse(
        await readFile(
          path.join(input.openWikiHome, "_c7-control", "in", "binding.json"),
          "utf8",
        ),
      ) as Record<string, unknown>;
      if (
        !isFinalizer &&
        (input.operation === "update" || input.operation === "repair")
      ) {
        operationAttempts.push({
          binding,
          homePath: input.openWikiHome,
          operation: input.operation,
        });
      }
      if (providerTransientFailures > 0) {
        providerTransientFailures -= 1;
        lastTransientOperation = "update";
        failedHomePaths.push(input.openWikiHome);
        await writeFile(
          path.join(input.openWikiHome, "failure-sentinel.txt"),
          "discard this failed generation home\n",
          "utf8",
        );
        throw new C7ProcessError(
          "provider_transient",
          "The provider asked C7 to retry.",
          undefined,
          0,
          "5xx",
        );
      }
      if (input.operation === "repair" && providerTransientRepairFailures > 0) {
        providerTransientRepairFailures -= 1;
        lastTransientOperation = "repair";
        failedHomePaths.push(input.openWikiHome);
        await writeFile(
          path.join(input.openWikiHome, "failure-sentinel.txt"),
          "discard this failed repair home\n",
          "utf8",
        );
        throw new C7ProcessError(
          "provider_transient",
          "The provider asked C7 to retry Repair.",
        );
      }
      if (providerRejectedFailures > 0) {
        providerRejectedFailures -= 1;
        throw new C7ProcessError(
          "provider_rejected",
          "The provider rejected the request.",
          undefined,
          1_200,
          "4xx",
        );
      }
      if (nonRetryableProcessFailure !== undefined) {
        const code = nonRetryableProcessFailure;
        nonRetryableProcessFailure = undefined;
        throw new C7ProcessError(code, "The process failed without retry.");
      }
      const requestFileName = input.requestFileName ?? "request.md";
      observedProcessRequests.push({
        operation: input.operation,
        requestFileName,
        text: await readFile(
          path.join(input.openWikiHome, "_c7-control", "in", requestFileName),
          "utf8",
        ),
      });
      if (isFinalizer && options.finalizerProcessFails) {
        throw new C7ProcessError(
          "process_failed",
          "The finalizer process failed.",
          "stage=cli-import; token=secret-finalizer-canary",
        );
      }
      const classification = options.classification ?? "minor";
      if (input.operation === "update" || input.operation === "repair") {
        updateBindings.push(binding);
      }
      if (input.operation === "update" && !isFinalizer) {
        trustedCandidateWikiPath = path.join(input.openWikiHome, "openwiki");
      }
      if (!isFinalizer || options.finalizerMutatesCandidate) {
        if (
          !isFinalizer &&
          (options.writesUpstreamIndexes || options.writesBusinessPages)
        ) {
          const sourcesDir = path.join(
            input.openWikiHome,
            "openwiki",
            "sources",
          );
          await mkdir(sourcesDir, { recursive: true });
          await writeFile(
            path.join(input.openWikiHome, "openwiki", "quickstart.md"),
            page(
              `# Updated rendering ownership\n\nSee [KGPR source set](./sources/kgpr-source-set.md).${
                options.writesBusinessPages === 3
                  ? "\n\nSee [Diagnostics](./diagnostics.md)."
                  : ""
              }${input.operation === "repair" ? "\n\nRepaired label." : ""}\n`,
              classification === "provisional",
            ),
            "utf8",
          );
          await writeFile(
            path.join(sourcesDir, "kgpr-source-set.md"),
            page("# KGPR source set\n"),
            "utf8",
          );
          if (options.writesBusinessPages === 3) {
            await writeFile(
              path.join(input.openWikiHome, "openwiki", "diagnostics.md"),
              page("# Diagnostics\n"),
              "utf8",
            );
          }
          if (options.writesUpstreamIndexes) {
            await writeFile(
              path.join(input.openWikiHome, "openwiki", "index.md"),
              "# Wiki index\n\n[Sources](./sources/)\n",
              "utf8",
            );
            await writeFile(
              path.join(sourcesDir, "index.md"),
              "# Sources index\n\n[Wiki root](../)\n",
              "utf8",
            );
          }
        } else {
          await writeFile(
            path.join(input.openWikiHome, "openwiki", "quickstart.md"),
            isFinalizer
              ? page("# Illicit finalizer mutation\n")
              : options.invalidCandidate
                ? "# Missing front matter\n"
                : page(
                    "# Updated rendering ownership\n",
                    classification === "provisional",
                  ),
            "utf8",
          );
        }
      }
      if (
        !isFinalizer &&
        (options.writesInvalidRuntimeMetadata ||
          (options.writesInvalidRuntimeMetadataOnRepair &&
            input.operation === "repair"))
      ) {
        await mkdir(
          path.join(input.openWikiHome, "openwiki", ".last-update.json"),
        );
      } else if (!isFinalizer && options.writesRuntimeMetadata) {
        await writeFile(
          path.join(input.openWikiHome, "openwiki", ".last-update.json"),
          '{"gitHead":"real-update-shape"}\n',
          "utf8",
        );
      }
      if (!isFinalizer && options.writesCandidateJunction) {
        await symlink(
          outsideWikiPath,
          path.join(input.openWikiHome, "openwiki", "linked-outside"),
          "junction",
        );
      }
      const issues =
        classification === "blocking"
          ? [
              {
                code: "owner_unknown",
                message: "Ownership changes the technical meaning.",
                severity: "blocking",
              },
            ]
          : classification === "provisional"
            ? [
                {
                  code: "owner_unverified",
                  message: "Runtime owner is provisional.",
                  severity: "provisional",
                },
              ]
            : [];
      const resultPath = path.join(
        input.openWikiHome,
        "_c7-control",
        "out",
        "result.json",
      );
      const effectiveResultFailure =
        isFinalizer && options.finalizerResult === "valid"
          ? undefined
          : options.resultFailure;
      if (isFinalizer && options.finalizerResult !== "valid") {
        // Preserve the missing-result failure for the one permitted retry.
      } else if (effectiveResultFailure === "result_json_invalid") {
        await writeFile(resultPath, "{secret-result-canary", "utf8");
      } else if (effectiveResultFailure !== "result_missing") {
        const result = {
          binding:
            effectiveResultFailure === "result_binding_mismatch"
              ? {
                  ...binding,
                  beforeWikiRootHash: `sha256:${"b".repeat(64)}`,
                }
              : binding,
          classification,
          issues,
          questions:
            classification === "blocking"
              ? ["Which team owns this runtime?"]
              : [],
          summary: "Updated Wiki knowledge.",
          type: "update_result",
          version: 1,
          ...(effectiveResultFailure === "result_schema_invalid"
            ? { secret: "secret-result-canary" }
            : {}),
        };
        await writeFile(resultPath, `${JSON.stringify(result)}\n`, "utf8");
      }
      if (!isFinalizer && options.candidateMissingAfterRun) {
        await rm(path.join(input.openWikiHome, "openwiki"), {
          force: true,
          recursive: true,
        });
      }
      return {
        model: {
          providerAccepted: true as const,
          requested: selection,
          sent: selection,
        },
        stderr: "",
        stdout: "",
      };
    }),
  };
  const finalizerCandidateSnapshots: Array<
    Awaited<ReturnType<typeof snapshotMarkdownTree>>
  > = [];
  const originalRun = processRunner.run.getMockImplementation()!;
  processRunner.run.mockImplementation(async (input) => {
    const isFinalizer = input.requestFileName === "result-finalizer.md";
    if (isFinalizer) {
      finalizerCandidateSnapshots.push(
        await snapshotMarkdownTree(path.join(input.openWikiHome, "openwiki")),
      );
    }
    const result = await originalRun(input);
    if (isFinalizer) {
      finalizerCandidateSnapshots.push(
        await snapshotMarkdownTree(path.join(input.openWikiHome, "openwiki")),
      );
    }
    return result;
  });
  let reviewIndex = 0;
  const reviewer = {
    review: vi.fn(
      async (reviewInput: Parameters<UpdateReviewer["review"]>[0]) => {
        if (options.expectFormalWikiUnchangedDuringReview) {
          expect((await snapshotMarkdownTree(formalWikiPath)).rootHash).toBe(
            initialRevision,
          );
        }
        if (options.reviewFailureStage !== undefined) {
          throw Object.assign(new Error("secret-result-canary"), {
            failureStage: options.reviewFailureStage,
          });
        }
        const result = options.reviewResults?.[reviewIndex++] ??
          options.reviewResult ?? { issues: [], verdict: "pass" as const };
        if (options.driftBeforeRepair) {
          options.driftBeforeRepair = false;
          await writeFile(
            path.join(reviewInput.reviewWikiPath!, "quickstart.md"),
            page("# Candidate drift before repair\n"),
            "utf8",
          );
        }
        return {
          ...result,
          binding: {
            candidateId: reviewInput.candidateId,
            model: selection,
            reviewedRootHash: reviewInput.reviewedRootHash,
            skillAggregateHash: skills.aggregateHash,
            sourceManifestHash: null,
            version: 1 as const,
          },
          model: {
            providerAccepted: true as const,
            requested: selection,
            sent: selection,
          },
          type: "review_result" as const,
          version: 1 as const,
        };
      },
    ),
  };
  const sourceCleanup = vi.fn(async () => {
    if (options.sourceCleanupFails) throw new Error("cleanup failed");
  });
  const sourceTreeHash = await hashSourceSnapshotTree(sourceSnapshotPath);
  const publisher = new WikiPublisher({ formalWikiPath, runtimeDir, security });
  const publish = vi.spyOn(publisher, "publish");
  const service = new OpenWikiUpdateService({
    config: {
      defaultModel: selection,
      generation: 1,
      initialized: true,
      provider: "openai-chatgpt",
      schemaVersion: 1,
      verifiedModels: [
        {
          ...selection,
          providerAccepted: true,
          verifiedAt: "2026-08-07T00:00:00.000Z",
        },
      ],
    },
    formalWikiPath,
    processRunner,
    publisher,
    reviewer,
    runtimeDir,
    sensitivePolicyPath,
    skills: { list: () => [], select: vi.fn(() => skills) },
    sources: {
      verify: vi.fn(async () => ({
        cleanup: sourceCleanup,
        files: [],
        manifestHash: `sha256:${"f".repeat(64)}`,
        snapshotPath: sourceSnapshotPath,
        snapshotTreeHash: sourceTreeHash,
      })),
    },
    transactions,
    waitBeforeRetry: async () => {
      if (options.retryDrift === "formal") {
        await writeFile(
          path.join(formalWikiPath, "quickstart.md"),
          page("# External formal drift during retry backoff\n"),
          "utf8",
        );
      } else if (
        options.retryDrift === "candidate" &&
        lastTransientOperation === "repair" &&
        trustedCandidateWikiPath !== undefined
      ) {
        await writeFile(
          path.join(trustedCandidateWikiPath, "quickstart.md"),
          page("# External candidate drift during retry backoff\n"),
          "utf8",
        );
      }
    },
  });
  return {
    cleanup,
    createHomeLease,
    failedHomePaths,
    finalizerCandidateSnapshots,
    formalWikiPath,
    initialRevision,
    observedProcessRequests,
    operationAttempts,
    outsideIndexPath,
    outsideSentinelPath,
    processRunner,
    publish,
    reviewer,
    runtimeDir,
    service,
    updateBindings,
  };
}

async function expectCleanRuntime(runtimeDir: string): Promise<void> {
  await expect(
    readdir(path.join(runtimeDir, "transactions")).catch(() => []),
  ).resolves.toEqual([]);
  await expect(
    readdir(path.join(runtimeDir, "locks")).catch(() => []),
  ).resolves.toEqual([]);
}

async function expectFailureSentinelsRemoved(
  failedHomePaths: readonly string[],
): Promise<void> {
  await Promise.all(
    failedHomePaths.map((homePath) =>
      expect(
        readFile(path.join(homePath, "failure-sentinel.txt"), "utf8"),
      ).rejects.toMatchObject({ code: "ENOENT" }),
    ),
  );
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

function page(body: string, provisional = false): string {
  return `---\ntype: Guide\n${provisional ? "status: provisional\n" : ""}---\n\n${body}`;
}
