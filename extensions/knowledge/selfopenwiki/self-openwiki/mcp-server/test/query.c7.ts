import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { toolOutputSchemas } from "../src/contracts.js";
import { C7ProcessError } from "../src/process.js";
import { OpenWikiQueryService } from "../src/query.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import { C7TransactionFactory } from "../src/transaction.js";
import { hashSourceSnapshotTree } from "../src/sources.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type C7SkillRegistry,
  type SelectedC7Skill,
  type SelectedC7Skills,
} from "../src/skills.js";

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

describe("openwiki_query isolation", () => {
  test("answers from a temporary Wiki while the formal Wiki stays byte-identical", async () => {
    const fixture = await createFixture();

    const result = await fixture.service.query({
      executionMode: "legacy_provider",
      instruction: "Explain the rendering ownership.",
      materials: [{ content: "A local design note.", id: "note-1" }],
    });

    expect(toolOutputSchemas.openwiki_query.parse(result)).toEqual(result);
    expect(result).toEqual(
      expect.objectContaining({
        answer: "The renderer owns the lifetime.",
        model: {
          providerAccepted: true,
          requested: selection,
          sent: selection,
        },
        ok: true,
        skillAggregateHash: fixture.skills.aggregateHash,
        status: "answered",
        wikiRevision: (await snapshotMarkdownTree(fixture.formalWikiPath))
          .rootHash,
      }),
    );
    expect(
      await readFile(path.join(fixture.formalWikiPath, "index.md"), "utf8"),
    ).toBe("# Formal\n");
    expect(fixture.processRunner.run).toHaveBeenCalledTimes(1);
    expect(fixture.stageDuringRun()).toBe("running");
    expect(fixture.finalize).toHaveBeenCalledTimes(1);
    expect(fixture.cleanup).toHaveBeenCalledTimes(1);
    expect(fixture.capturedRequest()).toContain(
      "Explain the rendering ownership.",
    );
    expect(fixture.capturedRequest()).toContain(
      "KG_C7_Project_Wiki base policy",
    );
  });

  test("verifies a bound source manifest and reports its exact hash", async () => {
    const fixture = await createFixture({ withSource: true });
    const manifestHash = `sha256:${"e".repeat(64)}`;

    const result = await fixture.service.query({
      executionMode: "legacy_provider",
      instruction: "Trace the local source.",
      sourceConfirmation: "confirm-source:source-12345678:bound",
      sourceManifestId: "source-12345678",
    });

    expect(result).toEqual(
      expect.objectContaining({ sourceManifestHash: manifestHash }),
    );
    expect(fixture.verifySource).toHaveBeenCalledWith({
      confirmation: "confirm-source:source-12345678:bound",
      sourceManifestId: "source-12345678",
    });
    expect(fixture.sourceCleanup).toHaveBeenCalledTimes(1);
  });

  test("rejects credential-like materials before creating a transaction", async () => {
    const fixture = await createFixture();

    await expect(
      fixture.service.query({
        executionMode: "legacy_provider",
        instruction: "Summarize this.",
        materials: [
          {
            content: "Authorization: Bearer secret-token-canary",
            id: "unsafe",
          },
        ],
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "source_rejected" }));
    expect(fixture.processRunner.run).not.toHaveBeenCalled();
    expect(fixture.createHomeLease).not.toHaveBeenCalled();
    expect(JSON.stringify(await fixture.safeRuntimeFiles())).not.toContain(
      "secret-token-canary",
    );
  });

  test.each<ResultFailureStage>([
    "result_missing",
    "result_json_invalid",
    "result_schema_invalid",
    "result_binding_mismatch",
  ])(
    "reports %s without weakening isolation or exposing result content",
    async (failureStage) => {
      const fixture = await createFixture({ resultFailure: failureStage });

      const error = await fixture.service
        .query({
          executionMode: "legacy_provider",
          instruction: "Answer exactly.",
        })
        .catch((caught: unknown) => caught);

      expect(error).toEqual(
        expect.objectContaining({ code: "process_failure", failureStage }),
      );
      expect(JSON.stringify(error)).not.toContain("secret-result-canary");
      expect(fixture.finalize).toHaveBeenCalledTimes(1);
      expect(fixture.cleanup).toHaveBeenCalledTimes(1);
      expect(
        await readFile(path.join(fixture.formalWikiPath, "index.md"), "utf8"),
      ).toBe("# Formal\n");
    },
  );

  test("reports source snapshot cleanup failure without changing the formal Wiki", async () => {
    const fixture = await createFixture({
      sourceCleanupFails: true,
      withSource: true,
    });

    await expect(
      fixture.service.query({
        executionMode: "legacy_provider",
        instruction: "Query bound source.",
        sourceConfirmation: "confirm-source:source-12345678:bound",
        sourceManifestId: "source-12345678",
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "process_failure" }));
    expect(
      await readFile(path.join(fixture.formalWikiPath, "index.md"), "utf8"),
    ).toBe("# Formal\n");
  });

  test("preserves a bounded sanitized process diagnostic for failure analysis", async () => {
    const fixture = await createFixture();
    fixture.processRunner.run.mockRejectedValueOnce(
      new C7ProcessError(
        "process_failed",
        "The isolated OpenWiki process failed.",
        "stage=cli-import Authorization: Bearer secret-token-canary",
      ),
    );

    const error = await fixture.service
      .query({
        executionMode: "legacy_provider",
        instruction: "Answer exactly.",
      })
      .catch((caught: unknown) => caught);

    expect(error).toEqual(
      expect.objectContaining({
        code: "process_failure",
        diagnostic: "stage=cli-import Authorization: Bearer [REDACTED]",
      }),
    );
    expect(JSON.stringify(error)).not.toContain("secret-token-canary");
  });
});

async function createFixture(
  options: {
    resultFailure?: ResultFailureStage;
    sourceCleanupFails?: boolean;
    withSource?: boolean;
  } = {},
) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-query-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWikiPath = path.join(runtimeDir, "wiki");
  const sensitivePolicyPath = path.join(root, "sensitive.json");
  const sourceSnapshotPath = path.join(root, "source-snapshot");
  await mkdir(formalWikiPath, { recursive: true });
  await mkdir(path.join(sourceSnapshotPath, "000000"), { recursive: true });
  await writeFile(path.join(formalWikiPath, "index.md"), "# Formal\n", "utf8");
  await writeFile(
    path.join(sourceSnapshotPath, "000000", "sample.cpp"),
    "int X;\n",
    "utf8",
  );
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
  const cleanup = vi.fn(async () => undefined);
  const finalize = vi.fn().mockResolvedValue(undefined);
  let homePath = "";
  let request = "";
  let stageDuringRun = "";
  const createHomeLease = vi.fn(async () => {
    homePath = await mkdtemp(path.join(root, "query-home-"));
    await writeFile(
      path.join(homePath, ".env"),
      "managed credential\n",
      "utf8",
    );
    cleanup.mockImplementationOnce(async () => {
      await rm(homePath, { force: true, recursive: true });
    });
    return { cleanup, finalize, path: homePath };
  });
  const transactions = new C7TransactionFactory({
    createHomeLease,
    createRunId: () => "run-12345678",
    formalWikiPath,
    runtimeDir,
    security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
  });
  const skills = selectedSkills();
  const skillRegistry: C7SkillRegistry = {
    list: () => [],
    select: vi.fn(() => skills),
  };
  const sourceCleanup = vi.fn(async () => {
    if (options.sourceCleanupFails) throw new Error("cleanup failed");
  });
  const sourceSnapshotTreeHash =
    await hashSourceSnapshotTree(sourceSnapshotPath);
  const verifySource = vi.fn(async () => ({
    cleanup: sourceCleanup,
    files: [],
    manifestHash: `sha256:${"e".repeat(64)}`,
    snapshotPath: sourceSnapshotPath,
    snapshotTreeHash: sourceSnapshotTreeHash,
  }));
  const processRunner = {
    run: vi.fn(async (input: { openWikiHome: string }) => {
      const transactionState = JSON.parse(
        await readFile(
          path.join(runtimeDir, "transactions", "run-12345678", "state.json"),
          "utf8",
        ),
      ) as { stage: string };
      stageDuringRun = transactionState.stage;
      request = await readFile(
        path.join(input.openWikiHome, "_c7-control", "in", "request.md"),
        "utf8",
      );
      const binding = JSON.parse(
        await readFile(
          path.join(input.openWikiHome, "_c7-control", "in", "binding.json"),
          "utf8",
        ),
      ) as Record<string, unknown>;
      await writeFile(
        path.join(input.openWikiHome, "openwiki", "index.md"),
        "# Mutated only in temp\n",
        "utf8",
      );
      const resultPath = path.join(
        input.openWikiHome,
        "_c7-control",
        "out",
        "result.json",
      );
      if (options.resultFailure === "result_json_invalid") {
        await writeFile(resultPath, "{secret-result-canary", "utf8");
      } else if (options.resultFailure !== "result_missing") {
        const result =
          options.resultFailure === "result_schema_invalid"
            ? {
                binding,
                secret: "secret-result-canary",
                type: "query_result",
                version: 1,
              }
            : {
                answer: "The renderer owns the lifetime.",
                binding:
                  options.resultFailure === "result_binding_mismatch"
                    ? { ...binding, version: 999 }
                    : binding,
                type: "query_result",
                version: 1,
              };
        await writeFile(resultPath, `${JSON.stringify(result)}\n`, "utf8");
      }
      return {
        model: {
          providerAccepted: true as const,
          requested: selection,
          sent: selection,
        },
        stderr: "",
        stdout: "ignored free text",
      };
    }),
  };
  const service = new OpenWikiQueryService({
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
    runtimeDir,
    sensitivePolicyPath,
    skills: skillRegistry,
    sources: { verify: verifySource },
    transactions,
  });
  return {
    capturedRequest: () => request,
    cleanup,
    createHomeLease,
    finalize,
    formalWikiPath,
    processRunner,
    safeRuntimeFiles: async () => {
      const files: string[] = [];
      for (const candidate of [formalWikiPath, runtimeDir]) {
        files.push(candidate);
      }
      return files;
    },
    service,
    skills,
    stageDuringRun: () => stageDuringRun,
    sourceCleanup,
    verifySource,
  };
}

function selectedSkills(): SelectedC7Skills {
  const bytes = Buffer.from("# Base\n", "utf8");
  const fileHash = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
  const files = [
    {
      bytes,
      hash: fileHash,
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
