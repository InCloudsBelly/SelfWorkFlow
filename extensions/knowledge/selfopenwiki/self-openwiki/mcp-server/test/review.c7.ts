import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { OpenWikiReviewService } from "../src/review.js";
import { C7ProcessError } from "../src/process.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type SelectedC7Skill,
} from "../src/skills.js";
import { C7TransactionFactory } from "../src/transaction.js";

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

describe("independent read-only Wiki review", () => {
  test.each([
    "result_missing",
    "result_json_invalid",
    "result_schema_invalid",
  ] as const)(
    "finalizes a %s review result without changing the reviewed Wiki",
    async (failureStage) => {
      const fixture = await createFixture({
        finalizerRecovers: true,
        resultFailure: failureStage,
      });

      await expect(
        fixture.service.review({
          candidateId: "run-review-00000001",
          instruction: "Review.",
          model: evidence(),
          reviewedRootHash: fixture.publishedRootHash,
          selectedSkills: fixture.selected,
          selection,
          sourceManifestHash: null,
        }),
      ).resolves.toEqual(expect.objectContaining({ verdict: "pass" }));
      expect(fixture.processRunner.run).toHaveBeenCalledTimes(2);
    },
  );

  test("retries transient provider review failures with fresh homes", async () => {
    const fixture = await createFixture({ providerTransientFailures: 2 });

    await expect(
      fixture.service.review({
        candidateId: "run-review-00000001",
        instruction: "Review.",
        model: evidence(),
        reviewedRootHash: fixture.publishedRootHash,
        selectedSkills: fixture.selected,
        selection,
        sourceManifestHash: null,
      }),
    ).resolves.toEqual(expect.objectContaining({ verdict: "pass" }));
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(3);
    expect(fixture.bindingAttempts).toHaveLength(3);
    expect(fixture.bindingAttempts.map((attempt) => attempt.binding)).toEqual([
      fixture.bindingAttempts[0]!.binding,
      fixture.bindingAttempts[0]!.binding,
      fixture.bindingAttempts[0]!.binding,
    ]);
    expect(
      new Set(fixture.bindingAttempts.map((attempt) => attempt.homePath)).size,
    ).toBe(3);
    expect(fixture.failedHomePaths).toEqual([
      fixture.bindingAttempts[0]!.homePath,
      fixture.bindingAttempts[1]!.homePath,
    ]);
    await expectFailureSentinelsRemoved(fixture.failedHomePaths);
    expect(fixture.cleanup).toHaveBeenCalledTimes(3);
  });

  test("stops after three total transient provider review attempts", async () => {
    const fixture = await createFixture({ providerTransientFailures: 3 });

    await expect(
      fixture.service.review({
        candidateId: "run-review-00000001",
        instruction: "Review.",
        model: evidence(),
        reviewedRootHash: fixture.publishedRootHash,
        selectedSkills: fixture.selected,
        selection,
        sourceManifestHash: null,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "provider_transient" }));
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(3);
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(3);
    expect(fixture.cleanup).toHaveBeenCalledTimes(3);
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toContain("Published");
  });

  test.each(["formal", "candidate"] as const)(
    "stops before Review retry when the trusted %s Wiki drifts during backoff",
    async (retryDrift) => {
      const fixture = await createFixture({
        providerTransientFailures: 1,
        retryDrift,
      });

      await expect(
        fixture.service.review({
          candidateId: "run-review-00000001",
          instruction: "Stop before reviewing a drifted baseline.",
          model: evidence(),
          reviewedRootHash: fixture.candidateRootHash,
          reviewWikiPath: fixture.candidateWikiPath,
          selectedSkills: fixture.selected,
          selection,
          sourceManifestHash: null,
        }),
      ).rejects.toEqual(expect.objectContaining({ code: "review_failed" }));
      expect(fixture.processRunner.run).toHaveBeenCalledTimes(1);
      expect(fixture.createHomeLease).toHaveBeenCalledTimes(1);
      expect(fixture.cleanup).toHaveBeenCalledTimes(1);
      await expectFailureSentinelsRemoved(fixture.failedHomePaths);
    },
  );

  test("does not retry a rejected provider review", async () => {
    const fixture = await createFixture({ providerRejectedFailures: 1 });

    await expect(
      fixture.service.review({
        candidateId: "run-review-00000001",
        instruction: "Review.",
        model: evidence(),
        reviewedRootHash: fixture.publishedRootHash,
        selectedSkills: fixture.selected,
        selection,
        sourceManifestHash: null,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "provider_rejected" }));
    expect(fixture.createHomeLease).toHaveBeenCalledTimes(1);
  });

  test("uses a fresh read-only transaction and exact same model binding", async () => {
    const fixture = await createFixture();

    const result = await fixture.service.review({
      candidateId: "run-review-00000001",
      instruction:
        "Update rendering ownership.\n\n# KG_C7_Project_Wiki base policy\nBound once.",
      model: evidence(),
      reviewedRootHash: fixture.publishedRootHash,
      selectedSkills: fixture.selected,
      selection,
      sourceManifestHash: null,
    });

    expect(result).toEqual(
      expect.objectContaining({
        issues: [],
        model: evidence(),
        verdict: "pass",
      }),
    );
    expect(fixture.observedWikiPermissions()).toEqual(["read", "list"]);
    expect(
      fixture.observedRequest().match(/# KG_C7_Project_Wiki base policy/gu),
    ).toHaveLength(1);
    expect(fixture.observedRequest()).toContain(
      "Top-level keys must be exactly binding, issues, type, verdict, version.",
    );
    expect(fixture.observedRequest()).toContain(
      "already-published exact-root recovery target",
    );
    expect(fixture.observedRequest()).toContain(
      "Each issue permits exactly code, message, optional page, and severity.",
    );
    expect(fixture.observedRequest()).toContain(
      "pass requires zero issues; follow_up requires at least one provisional issue and no blocking issue; auto_fixable requires at least one issue and every issue must be minor; requires_user requires at least one issue.",
    );
    expect(fixture.finalize).toHaveBeenCalledTimes(1);
    expect(fixture.cleanup).toHaveBeenCalledTimes(1);
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toContain("Published");
  });

  test("labels an explicit review path as an unpublished candidate", async () => {
    const fixture = await createFixture();

    await fixture.service.review({
      candidateId: "run-review-00000001",
      instruction: "Review candidate semantics.",
      model: evidence(),
      reviewedRootHash: fixture.publishedRootHash,
      reviewWikiPath: fixture.formalWikiPath,
      selectedSkills: fixture.selected,
      selection,
      sourceManifestHash: null,
    });

    expect(fixture.observedRequest()).toContain("unpublished Wiki candidate");
  });

  test("fails closed when the review result finalizer mutates the candidate", async () => {
    const fixture = await createFixture({
      finalizerMutatesCandidate: true,
      finalizerRecovers: true,
      resultFailure: "result_missing",
    });

    await expect(
      fixture.service.review({
        candidateId: "run-review-00000001",
        instruction: "Review without changing the candidate.",
        model: evidence(),
        reviewedRootHash: fixture.publishedRootHash,
        selectedSkills: fixture.selected,
        selection,
        sourceManifestHash: null,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "review_failed" }));
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(2);
    expect(fixture.cleanup).toHaveBeenCalledTimes(1);
    expect(
      await readFile(
        path.join(fixture.formalWikiPath, "quickstart.md"),
        "utf8",
      ),
    ).toContain("Published");
  });

  test.each<ResultFailureStage>([
    "result_missing",
    "result_json_invalid",
    "result_schema_invalid",
    "result_binding_mismatch",
  ])(
    "reports %s and still cleans the review transaction",
    async (failureStage) => {
      const fixture = await createFixture({ resultFailure: failureStage });

      const error = await fixture.service
        .review({
          candidateId: "run-review-00000001",
          instruction: "Review.",
          model: evidence(),
          reviewedRootHash: fixture.publishedRootHash,
          selectedSkills: fixture.selected,
          selection,
          sourceManifestHash: null,
        })
        .catch((caught: unknown) => caught);

      expect(error).toEqual(
        expect.objectContaining({ code: "review_failed", failureStage }),
      );
      expect(fixture.processRunner.run).toHaveBeenCalledTimes(
        failureStage === "result_binding_mismatch" ? 1 : 2,
      );
      expect(JSON.stringify(error)).not.toContain("secret-result-canary");
      expect(fixture.cleanup).toHaveBeenCalledTimes(1);
    },
  );
});

async function createFixture(
  options: {
    finalizerMutatesCandidate?: boolean;
    finalizerRecovers?: boolean;
    providerRejectedFailures?: number;
    providerTransientFailures?: number;
    retryDrift?: "candidate" | "formal";
    resultFailure?: ResultFailureStage;
  } = {},
) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-review-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWikiPath = path.join(runtimeDir, "wiki");
  const candidateWikiPath = path.join(root, "candidate-wiki");
  await mkdir(formalWikiPath, { recursive: true });
  await mkdir(candidateWikiPath, { recursive: true });
  await writeFile(
    path.join(formalWikiPath, "quickstart.md"),
    "---\ntype: Guide\n---\n\n# Published\n",
    "utf8",
  );
  await writeFile(
    path.join(candidateWikiPath, "quickstart.md"),
    "---\ntype: Guide\n---\n\n# Candidate\n",
    "utf8",
  );
  const publishedRootHash = `sha256:${createHash("sha256")
    .update("placeholder")
    .digest("hex")}`;
  const { snapshotMarkdownTree } = await import("../src/snapshot.js");
  const actualRootHash = (await snapshotMarkdownTree(formalWikiPath)).rootHash;
  const candidateRootHash = (await snapshotMarkdownTree(candidateWikiPath))
    .rootHash;
  expect(publishedRootHash).not.toBe(actualRootHash);
  const cleanup = vi.fn<() => Promise<void>>(async () => undefined);
  const finalize = vi.fn(async () => undefined);
  const createHomeLease = vi.fn(async () => {
    const home = await mkdtemp(path.join(root, "review-home-"));
    cleanup.mockImplementationOnce(async () => {
      await rm(home, { force: true, recursive: true });
    });
    return { cleanup, finalize, path: home };
  });
  const selected = selectedSkills();
  let providerTransientFailures = options.providerTransientFailures ?? 0;
  let providerRejectedFailures = options.providerRejectedFailures ?? 0;
  let wikiPermissions: string[] = [];
  let requestMarkdown = "";
  const bindingAttempts: Array<{
    binding: Record<string, unknown>;
    homePath: string;
  }> = [];
  const failedHomePaths: string[] = [];
  const processRunner = {
    run: vi.fn(
      async (input: {
        openWikiHome: string;
        policyPath: string;
        requestFileName?: string;
      }) => {
        const transactionBinding = JSON.parse(
          await readFile(
            path.join(input.openWikiHome, "_c7-control", "in", "binding.json"),
            "utf8",
          ),
        ) as { review: Record<string, unknown> };
        if (input.requestFileName !== "result-finalizer.md") {
          bindingAttempts.push({
            binding: transactionBinding,
            homePath: input.openWikiHome,
          });
        }
        if (providerTransientFailures > 0) {
          providerTransientFailures -= 1;
          failedHomePaths.push(input.openWikiHome);
          await writeFile(
            path.join(input.openWikiHome, "failure-sentinel.txt"),
            "discard this failed Review home\n",
            "utf8",
          );
          throw new C7ProcessError(
            "provider_transient",
            "The provider asked C7 to retry Review.",
          );
        }
        if (providerRejectedFailures > 0) {
          providerRejectedFailures -= 1;
          throw new C7ProcessError(
            "provider_rejected",
            "The provider rejected Review.",
          );
        }
        const policy = JSON.parse(await readFile(input.policyPath, "utf8")) as {
          mounts: Array<{ id: string; permissions: string[] }>;
        };
        wikiPermissions = policy.mounts.find(
          (mount) => mount.id === "wiki",
        )!.permissions;
        requestMarkdown = await readFile(
          path.join(input.openWikiHome, "_c7-control", "in", "request.md"),
          "utf8",
        );
        const binding =
          options.resultFailure === "result_binding_mismatch"
            ? {
                ...transactionBinding.review,
                candidateId: "run-review-wrong0001",
              }
            : transactionBinding.review;
        const resultPath = path.join(
          input.openWikiHome,
          "_c7-control",
          "out",
          "result.json",
        );
        const isFinalizer = input.requestFileName === "result-finalizer.md";
        if (isFinalizer && options.finalizerRecovers) {
          if (options.finalizerMutatesCandidate) {
            await writeFile(
              path.join(input.openWikiHome, "openwiki", "quickstart.md"),
              "# Illicit finalizer mutation\n",
              "utf8",
            );
          }
          await writeFile(
            resultPath,
            `${JSON.stringify({
              binding: transactionBinding.review,
              issues: [],
              type: "review_result",
              verdict: "pass",
              version: 1,
            })}\n`,
            "utf8",
          );
        } else if (options.resultFailure === "result_json_invalid") {
          await writeFile(resultPath, "{secret-result-canary", "utf8");
        } else if (options.resultFailure !== "result_missing") {
          await writeFile(
            resultPath,
            `${JSON.stringify({
              binding,
              issues: [],
              type: "review_result",
              verdict: "pass",
              version: 1,
              ...(options.resultFailure === "result_schema_invalid"
                ? { secret: "secret-result-canary" }
                : {}),
            })}\n`,
            "utf8",
          );
        }
        return { model: evidence(), stderr: "", stdout: "" };
      },
    ),
  };
  const security = { securePrivatePath: vi.fn().mockResolvedValue(undefined) };
  const service = new OpenWikiReviewService({
    formalWikiPath,
    processRunner,
    transactions: new C7TransactionFactory({
      createHomeLease,
      formalWikiPath,
      runtimeDir,
      security,
    }),
    waitBeforeRetry: async () => {
      const targetPath =
        options.retryDrift === "formal"
          ? formalWikiPath
          : options.retryDrift === "candidate"
            ? candidateWikiPath
            : undefined;
      if (targetPath !== undefined) {
        await writeFile(
          path.join(targetPath, "quickstart.md"),
          "---\ntype: Guide\n---\n\n# Drifted during retry backoff\n",
          "utf8",
        );
      }
    },
  });
  return {
    bindingAttempts,
    candidateRootHash,
    candidateWikiPath,
    cleanup,
    createHomeLease,
    failedHomePaths,
    finalize,
    formalWikiPath,
    observedWikiPermissions: () => wikiPermissions,
    observedRequest: () => requestMarkdown,
    publishedRootHash: actualRootHash,
    selected,
    service,
    processRunner,
  };
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

function selectedSkills() {
  const bytes = Buffer.from("# Base\n", "utf8");
  const files = [
    {
      bytes,
      hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
      relativePath: "SKILL.md",
      size: bytes.byteLength,
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
  return { aggregateHash: aggregateSkillHash([skill]), skills: [skill] };
}

function evidence() {
  return {
    providerAccepted: true as const,
    requested: selection,
    sent: selection,
  };
}
