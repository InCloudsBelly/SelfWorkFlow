import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { C7TransactionFactory } from "../src/transaction.js";
import { hashSourceSnapshotTree } from "../src/sources.js";
import {
  aggregateSkillHash,
  computeSkillPackageHash,
  type SelectedC7Skill,
  type SelectedC7Skills,
} from "../src/skills.js";
import { readTransactionState } from "../src/transaction-state.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";

const tempDirs: string[] = [];
const selection = { model: "gpt-5.6-sol", reasoningEffort: "xhigh" as const };

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("C7 transaction workspace", () => {
  test("copies an exact candidate base instead of the formal Wiki for review", async () => {
    const fixture = await createFixture();
    const candidateWikiPath = path.join(fixture.root, "candidate-wiki");
    await mkdir(candidateWikiPath);
    await writeFile(
      path.join(candidateWikiPath, "index.md"),
      "# Candidate Wiki\n",
      "utf8",
    );
    const candidate = await snapshotMarkdownTree(candidateWikiPath);

    const workspace = await fixture.factory.create({
      baseWiki: { path: candidateWikiPath, rootHash: candidate.rootHash },
      operation: "review",
      requestMarkdown: "# Review candidate\n",
      reviewBinding: {
        candidateId: "run-review-00000001",
        model: selection,
        reviewedRootHash: candidate.rootHash,
        skillAggregateHash: selectedSkills().aggregateHash,
        sourceManifestHash: null,
        version: 1,
      },
      selection,
      skills: selectedSkills(),
    });

    expect(
      await readFile(path.join(workspace.wikiPath, "index.md"), "utf8"),
    ).toBe("# Candidate Wiki\n");
    await workspace.cleanup();
  });

  test("rejects a candidate base whose exact root changed", async () => {
    const fixture = await createFixture();
    const candidateWikiPath = path.join(fixture.root, "candidate-wiki");
    await mkdir(candidateWikiPath);
    await writeFile(
      path.join(candidateWikiPath, "index.md"),
      "# Candidate Wiki\n",
      "utf8",
    );

    await expect(
      fixture.factory.create({
        baseWiki: {
          path: candidateWikiPath,
          rootHash: `sha256:${"f".repeat(64)}`,
        },
        operation: "review",
        requestMarkdown: "# Review candidate\n",
        reviewBinding: {
          candidateId: "run-review-00000001",
          model: selection,
          reviewedRootHash: `sha256:${"f".repeat(64)}`,
          skillAggregateHash: selectedSkills().aggregateHash,
          sourceManifestHash: null,
          version: 1,
        },
        selection,
        skills: selectedSkills(),
      }),
    ).rejects.toEqual(
      expect.objectContaining({ code: "transaction_prepare_failed" }),
    );
  });

  test.each([
    ["query", ["read", "list"]],
    ["review", ["read", "list"]],
    ["update", ["read", "list", "write"]],
    ["repair", ["read", "list", "write"]],
  ] as const)(
    "prepares an isolated %s Home and exact run policy",
    async (operation, wikiPermissions) => {
      const fixture = await createFixture();
      const confirmedWikiPaths = [
        "quickstart.md",
        "sources/kgpr-source-set.md",
      ];
      const workspace = await fixture.factory.create({
        operation,
        requestMarkdown: "# Bound request\nUse the confirmed evidence.\n",
        ...(operation === "update" || operation === "repair"
          ? { confirmedWikiPaths }
          : {}),
        ...(operation === "review"
          ? {
              reviewBinding: {
                candidateId: "run-review-00000001",
                model: selection,
                reviewedRootHash: `sha256:${"e".repeat(64)}`,
                skillAggregateHash: selectedSkills().aggregateHash,
                sourceManifestHash: `sha256:${"a".repeat(64)}`,
                version: 1,
              },
            }
          : {}),
        selection,
        skills: selectedSkills(),
        sourceSnapshot: {
          manifestHash: `sha256:${"a".repeat(64)}`,
          snapshotPath: fixture.sourceSnapshot,
          snapshotTreeHash: await hashSourceSnapshotTree(
            fixture.sourceSnapshot,
          ),
        },
      });

      expect(
        await readFile(path.join(workspace.wikiPath, "index.md"), "utf8"),
      ).toBe("# Formal Wiki\n");
      expect(
        await readFile(
          path.join(workspace.homePath, "sources", "000000", "sample.cpp"),
          "utf8",
        ),
      ).toBe("int Value = 7;\n");
      expect(
        await readFile(
          path.join(
            workspace.homePath,
            "_c7-control",
            "in",
            "c7-skills",
            "kg-c7-project-wiki",
            "SKILL.md",
          ),
          "utf8",
        ),
      ).toBe("# Base\n");
      await expect(
        access(
          path.join(
            workspace.homePath,
            "skills",
            "kg-c7-project-wiki",
            "SKILL.md",
          ),
        ),
      ).rejects.toBeDefined();
      const requestMarkdown = await readFile(
        path.join(workspace.homePath, "_c7-control", "in", "request.md"),
        "utf8",
      );
      expect(requestMarkdown).toContain("Bound request");
      expect(requestMarkdown).not.toContain("synchronizeWikiIndexes");
      const binding = JSON.parse(
        await readFile(
          path.join(workspace.homePath, "_c7-control", "in", "binding.json"),
          "utf8",
        ),
      ) as Record<string, unknown>;
      if (operation === "update" || operation === "repair") {
        expect(binding.confirmedWikiPaths).toEqual(confirmedWikiPaths);
      } else {
        expect(binding).not.toHaveProperty("confirmedWikiPaths");
      }

      const policy = JSON.parse(
        await readFile(workspace.policyPath, "utf8"),
      ) as {
        mounts: Array<{ id: string; path: string; permissions: string[] }>;
        rootDir: string;
        synchronizeWikiIndexes: boolean;
      };
      expect(policy.synchronizeWikiIndexes).toBe(false);
      expect(path.resolve(policy.rootDir)).toBe(
        path.resolve(workspace.homePath),
      );
      expect(
        policy.mounts.map((mount) => [mount.id, mount.permissions]),
      ).toEqual([
        ["wiki", wikiPermissions],
        ["sources", ["read", "list"]],
        ["skills", ["read", "list"]],
        ["conversation-history", ["read", "list", "write"]],
        ["control-in", ["read", "list"]],
        ["control-out", ["read", "list", "write"]],
      ]);
      expect(policy.mounts.some((mount) => mount.path.endsWith(".env"))).toBe(
        false,
      );
      expect(path.dirname(workspace.policyPath)).toBe(workspace.transactionDir);
      if (
        operation === "update" ||
        operation === "repair" ||
        operation === "review"
      ) {
        expect(workspace.resultFinalizer).not.toBeNull();
        const finalizer = workspace.resultFinalizer!;
        expect(finalizer.requestFileName).toBe("result-finalizer.md");
        const finalizerRequest = await readFile(
          path.join(
            workspace.homePath,
            "_c7-control",
            "in",
            finalizer.requestFileName,
          ),
          "utf8",
        );
        expect(finalizerRequest).toContain("candidate Wiki is read-only");
        expect(finalizerRequest).not.toContain("synchronizeWikiIndexes");
        const finalizerPolicy = JSON.parse(
          await readFile(finalizer.policyPath, "utf8"),
        ) as {
          mounts: Array<{
            id: string;
            permissions: string[];
          }>;
          synchronizeWikiIndexes: boolean;
        };
        expect(finalizerPolicy.synchronizeWikiIndexes).toBe(false);
        expect(
          finalizerPolicy.mounts.find((mount) => mount.id === "wiki")
            ?.permissions,
        ).toEqual(["read", "list"]);
        expect(
          finalizerPolicy.mounts.find((mount) => mount.id === "control-out")
            ?.permissions,
        ).toEqual(["read", "list", "write"]);
      } else {
        expect(workspace.resultFinalizer).toBeNull();
      }

      const state = JSON.parse(
        await readFile(workspace.statePath, "utf8"),
      ) as Record<string, unknown>;
      expect(state).toEqual(
        expect.objectContaining({
          beforeWikiRootHash: workspace.beforeWiki.rootHash,
          operation,
          pid: process.pid,
          runId: "run-12345678",
          stage: "prepared",
          version: 1,
        }),
      );
      expect(JSON.stringify(state)).not.toContain("access-secret-canary");
      expect(fixture.securePrivatePath).toHaveBeenCalled();

      await workspace.transitionStage("running");
      await workspace.transitionStage("model_complete");
      const transitioned = await readTransactionState(workspace.statePath);
      expect(transitioned.state).toEqual(
        expect.objectContaining({ generation: 3, stage: "model_complete" }),
      );

      await workspace.finalizeCredentials();
      expect(fixture.finalize).toHaveBeenCalledTimes(1);
      await workspace.cleanup();
      expect(fixture.cleanup).toHaveBeenCalledTimes(1);
      await expect(access(workspace.transactionDir)).rejects.toBeDefined();
    },
  );

  test("cleans the credential Home and transaction directory when preparation fails", async () => {
    const fixture = await createFixture({ failSecurityOn: "run-policy.json" });

    await expect(
      fixture.factory.create({
        operation: "query",
        requestMarkdown: "# Request\n",
        selection,
        skills: selectedSkills(),
      }),
    ).rejects.toEqual(
      expect.objectContaining({ code: "transaction_prepare_failed" }),
    );
    expect(fixture.cleanup).toHaveBeenCalledTimes(1);
    const transactionRoot = path.join(fixture.runtimeDir, "transactions");
    const entries = await readdir(transactionRoot).catch(() => []);
    expect(entries).toEqual([]);
  });

  test("rejects selected Skill package and aggregate hashes that are not bound to exact bytes", async () => {
    const fixture = await createFixture();
    const selected = selectedSkills();
    const tampered = {
      aggregateHash: selected.aggregateHash,
      skills: [
        {
          ...selected.skills[0]!,
          packageHash: `sha256:${"f".repeat(64)}`,
        },
      ],
    };

    await expect(
      fixture.factory.create({
        operation: "query",
        requestMarkdown: "# Request\n",
        selection,
        skills: tampered,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "transaction_invalid" }));
    expect(fixture.createHomeLease).not.toHaveBeenCalled();
  });
});

async function createFixture(options: { failSecurityOn?: string } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-transaction-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWikiPath = path.join(runtimeDir, "wiki");
  const sourceSnapshot = path.join(root, "source-snapshot");
  const home = path.join(root, "lease-home");
  await mkdir(formalWikiPath, { recursive: true });
  await mkdir(path.join(sourceSnapshot, "000000"), { recursive: true });
  await mkdir(home);
  await writeFile(
    path.join(formalWikiPath, "index.md"),
    "# Formal Wiki\n",
    "utf8",
  );
  await writeFile(
    path.join(sourceSnapshot, "000000", "sample.cpp"),
    "int Value = 7;\n",
    "utf8",
  );
  await writeFile(
    path.join(home, ".env"),
    "OPENAI_CHATGPT_ACCESS_TOKEN=access-secret-canary\n",
    "utf8",
  );
  const cleanup = vi.fn(async () => {
    await rm(home, { force: true, recursive: true });
  });
  const finalize = vi.fn().mockResolvedValue(undefined);
  const securePrivatePath = vi.fn(
    async ({ targetPath }: { targetPath: string }) => {
      if (
        options.failSecurityOn &&
        targetPath.endsWith(options.failSecurityOn)
      ) {
        throw new Error("security verification failed");
      }
    },
  );
  const createHomeLease = vi.fn(async () => ({
    cleanup,
    finalize,
    path: home,
  }));
  const factory = new C7TransactionFactory({
    createHomeLease,
    createRunId: () => "run-12345678",
    formalWikiPath,
    now: () => new Date("2026-08-07T00:00:00.000Z"),
    runtimeDir,
    security: { securePrivatePath },
  });
  return {
    cleanup,
    createHomeLease,
    factory,
    finalize,
    runtimeDir,
    root,
    securePrivatePath,
    sourceSnapshot,
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
      size: bytes.byteLength,
    },
  ];
  const skill: SelectedC7Skill = {
    category: "base",
    description: "Base Skill",
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
import { createHash } from "node:crypto";
