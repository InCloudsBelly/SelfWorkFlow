import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  readTransactionState,
  transitionTransactionState,
} from "../src/transaction-state.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("transaction state journal", () => {
  test("advances only through allowed stages with atomic generation CAS", async () => {
    const statePath = await createState();
    const before = await readTransactionState(statePath);
    const security = {
      securePrivatePath: vi.fn().mockResolvedValue(undefined),
    };

    const running = await transitionTransactionState(
      statePath,
      before.version,
      "running",
      new Date("2026-08-07T00:01:00.000Z"),
      security,
    );

    expect(running.state).toEqual(
      expect.objectContaining({
        generation: 2,
        stage: "running",
        updatedAt: "2026-08-07T00:01:00.000Z",
      }),
    );
    expect(security.securePrivatePath).toHaveBeenCalledWith({
      directory: false,
      targetPath: expect.stringContaining(".tmp"),
    });
    await expect(
      transitionTransactionState(
        statePath,
        before.version,
        "model_complete",
        new Date(),
        security,
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "stale_state" }));
  });

  test("rejects skipped, reversed, and post-terminal transitions", async () => {
    const statePath = await createState();
    const before = await readTransactionState(statePath);
    const security = {
      securePrivatePath: vi.fn().mockResolvedValue(undefined),
    };

    await expect(
      transitionTransactionState(
        statePath,
        before.version,
        "published_review_pending",
        new Date(),
        security,
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "transition_invalid" }));
    const failed = await transitionTransactionState(
      statePath,
      before.version,
      "failed",
      new Date("2026-08-07T00:01:00.000Z"),
      security,
    );
    await expect(
      transitionTransactionState(
        statePath,
        failed.version,
        "running",
        new Date("2026-08-07T00:02:00.000Z"),
        security,
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "transition_invalid" }));
  });

  test("rejects unknown fields and content whose hash changed externally", async () => {
    const statePath = await createState();
    const before = await readTransactionState(statePath);
    const parsed = JSON.parse(await readFile(statePath, "utf8")) as Record<
      string,
      unknown
    >;
    await writeFile(
      statePath,
      `${JSON.stringify({ ...parsed, invented: true }, null, 2)}\n`,
      "utf8",
    );

    await expect(readTransactionState(statePath)).rejects.toEqual(
      expect.objectContaining({ code: "invalid_state" }),
    );
    await expect(
      transitionTransactionState(
        statePath,
        before.version,
        "running",
        new Date(),
        { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "invalid_state" }));
  });
});

async function createState(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-state-"));
  tempDirs.push(root);
  const statePath = path.join(root, "state.json");
  const hash = (character: string) => `sha256:${character.repeat(64)}`;
  const state = {
    beforeWikiRootHash: hash("a"),
    createdAt: "2026-08-07T00:00:00.000Z",
    generation: 1,
    homePath: path.join(root, "home"),
    model: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
    operation: "update",
    pid: process.pid,
    policyPath: path.join(root, "policy.json"),
    reviewRequired: true,
    runId: "run-12345678",
    skillAggregateHash: hash("b"),
    sourceManifestHash: null,
    stage: "prepared",
    updatedAt: "2026-08-07T00:00:00.000Z",
    version: 1,
    wikiPath: path.join(root, "home", "openwiki"),
  };
  const bytes = Buffer.from(`${JSON.stringify(state, null, 2)}\n`, "utf8");
  expect(`sha256:${createHash("sha256").update(bytes).digest("hex")}`).toMatch(
    /^sha256:[a-f0-9]{64}$/u,
  );
  await writeFile(statePath, bytes);
  return statePath;
}
