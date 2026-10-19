import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { recoverAbandonedTransactions } from "../src/transaction-recovery.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("abandoned transaction recovery", () => {
  test("scrubs credential canaries before removing a dead transaction Home", async () => {
    const fixture = await createFixture();
    const afterScrub = vi.fn(async (envPath: string) => {
      expect(await readFile(envPath, "utf8")).toBe("");
    });

    const result = await recoverAbandonedTransactions(fixture.runtimeDir, {
      afterScrub,
      isProcessAlive: () => false,
    });

    expect(result).toEqual({
      cleanedHomes: 1,
      cleanedTransactions: 1,
      state: "clean",
    });
    expect(afterScrub).toHaveBeenCalledTimes(1);
    await expect(access(fixture.homePath)).rejects.toBeDefined();
    await expect(access(fixture.transactionDir)).rejects.toBeDefined();
  });

  test("preserves evidence and fails closed for a path-mismatched state", async () => {
    const fixture = await createFixture({ invalidHomePath: true });

    const result = await recoverAbandonedTransactions(fixture.runtimeDir, {
      isProcessAlive: () => false,
    });

    expect(result.state).toBe("restore_failed");
    await expect(access(fixture.transactionDir)).resolves.toBeUndefined();
    await expect(access(fixture.homePath)).resolves.toBeUndefined();
  });

  test("does not remove a transaction whose owning process is still live", async () => {
    const fixture = await createFixture();

    const result = await recoverAbandonedTransactions(fixture.runtimeDir, {
      isProcessAlive: () => true,
    });

    expect(result.state).toBe("restore_failed");
    await expect(access(fixture.transactionDir)).resolves.toBeUndefined();
  });
});

async function createFixture(options: { invalidHomePath?: boolean } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-txn-recovery-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const transactionDir = path.join(
    runtimeDir,
    "transactions",
    "run-abandoned-12345678",
  );
  const homePath = path.join(runtimeDir, "temp", "openwiki-smoke-abandoned");
  await mkdir(path.join(homePath, "openwiki"), { recursive: true });
  await mkdir(transactionDir, { recursive: true });
  await writeFile(
    path.join(homePath, ".env"),
    "OPENAI_CHATGPT_ACCESS_TOKEN=access-secret-canary\n",
    "utf8",
  );
  const createdAt = "2026-08-07T00:00:00.000Z";
  await writeFile(
    path.join(transactionDir, "state.json"),
    `${JSON.stringify(
      {
        beforeWikiRootHash: `sha256:${"a".repeat(64)}`,
        createdAt,
        generation: 1,
        homePath: options.invalidHomePath
          ? path.join(root, "outside-home")
          : homePath,
        model: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
        operation: "update",
        pid: 2_147_483_647,
        policyPath: path.join(transactionDir, "run-policy.json"),
        reviewRequired: true,
        runId: "run-abandoned-12345678",
        skillAggregateHash: `sha256:${"b".repeat(64)}`,
        sourceManifestHash: null,
        stage: "running",
        updatedAt: createdAt,
        version: 1,
        wikiPath: path.join(
          options.invalidHomePath ? path.join(root, "outside-home") : homePath,
          "openwiki",
        ),
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
  await writeFile(path.join(transactionDir, "run-policy.json"), "{}\n", "utf8");
  return { homePath, runtimeDir, transactionDir };
}
