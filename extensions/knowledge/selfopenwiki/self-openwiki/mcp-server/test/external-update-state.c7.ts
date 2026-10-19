import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";

const lockAcquisitionInjection = vi.hoisted(() => ({
  createError: null as null | ((runtimeDir: string) => Error),
}));

vi.mock("../src/config.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/config.js")>();
  return {
    ...actual,
    async withC7Locks<T>(
      runtimeDir: string,
      locks: Parameters<typeof actual.withC7Locks<T>>[1],
      operation: () => Promise<T>,
    ): Promise<T> {
      if (lockAcquisitionInjection.createError !== null) {
        const createError = lockAcquisitionInjection.createError;
        lockAcquisitionInjection.createError = null;
        await (
          await import("node:fs/promises")
        ).mkdir(path.join(runtimeDir, "locks"), { recursive: true });
        throw createError(runtimeDir);
      }
      return actual.withC7Locks(runtimeDir, locks, operation);
    },
  };
});

import {
  createExternalUpdateState,
  computeExternalTerminalResultHash,
  ExternalUpdateTerminalStore,
  EXTERNAL_TERMINAL_INDEX_MAX_BYTES,
  EXTERNAL_TERMINAL_PAYLOAD_MAX_BYTES,
  parseExternalTerminalPayload,
  readExternalUpdateState,
  recordExternalUpdateFailure,
  transitionExternalUpdateState,
} from "../src/external-update-state.js";
import { C7ConfigError, withC7Locks } from "../src/config.js";

const roots: string[] = [];

afterEach(async () => {
  lockAcquisitionInjection.createError = null;
  await Promise.all(
    roots.splice(0).map((root) => rm(root, { force: true, recursive: true })),
  );
});

describe("external update state", () => {
  test("creates, reads, and advances a strict state with expected-version CAS", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "c7-external-state-"));
    roots.push(root);
    const transactionRoot = path.join(
      root,
      "external-updates",
      "external-12345678",
    );
    const statePath = path.join(transactionRoot, "state.json");
    const security = {
      securePrivatePath: vi.fn().mockResolvedValue(undefined),
    };
    const created = await createExternalUpdateState(
      statePath,
      stateFixture(transactionRoot),
      security,
    );

    expect(await readExternalUpdateState(statePath)).toEqual(created);
    const advanced = await transitionExternalUpdateState({
      statePath,
      expectedVersion: created.version,
      next: { stage: "review_ready", review: reviewFixture(transactionRoot) },
      now: new Date("2026-08-12T00:01:00.000Z"),
      security,
    });
    expect(advanced.state.stage).toBe("review_ready");
    await expect(
      transitionExternalUpdateState({
        statePath,
        expectedVersion: created.version,
        next: { stage: "attention" },
        now: new Date("2026-08-12T00:02:00.000Z"),
        security,
      }),
    ).rejects.toMatchObject({ code: "stale_state" });
  });

  test.each(["create", "transition", "record_failure"] as const)(
    "cannot %s outside the runtime operation lock",
    async (operation) => {
      const runtimeDir = await mkdtemp(
        path.join(os.tmpdir(), "c7-external-state-lock-"),
      );
      roots.push(runtimeDir);
      const transactionRoot = path.join(
        runtimeDir,
        "external-updates",
        "external-12345678",
      );
      const statePath = path.join(transactionRoot, "state.json");
      const security = {
        securePrivatePath: vi.fn().mockResolvedValue(undefined),
      };
      const state = stateFixture(transactionRoot);
      const created =
        operation === "create"
          ? null
          : await createExternalUpdateState(statePath, state, security);

      await expectOperationLockBlocks(runtimeDir, async () => {
        if (operation === "create") {
          await createExternalUpdateState(statePath, state, security);
          return;
        }
        if (operation === "transition") {
          await transitionExternalUpdateState({
            statePath,
            expectedVersion: created!.version,
            next: { stage: "attention" },
            now: new Date("2026-08-12T00:01:00.000Z"),
            security,
          });
          return;
        }
        await recordExternalUpdateFailure({
          statePath,
          expectedVersion: created!.version,
          failure: {
            at: "2026-08-12T00:01:00.000Z",
            code: "host_timeout",
            messageHash: `sha256:${"a".repeat(64)}`,
            phase: "candidate_writer",
            retryable: true,
          },
          now: new Date("2026-08-12T00:01:00.000Z"),
          security,
        });
      });
    },
  );

  test("keeps all production state mutations statically closed to the transaction owner", async () => {
    const sourceRoot = path.resolve(import.meta.dirname, "../src");
    const protectedNames = [
      "ExternalUpdateTerminalStore",
      "createExternalUpdateState",
      "transitionExternalUpdateState",
      "recordExternalUpdateFailure",
    ];
    const unexpected: string[] = [];
    for (const entry of await readdir(sourceRoot, { withFileTypes: true })) {
      if (
        !entry.isFile() ||
        !entry.name.endsWith(".ts") ||
        entry.name === "external-update-state.ts" ||
        entry.name === "external-update-transaction.ts"
      ) {
        continue;
      }
      const source = await readFile(path.join(sourceRoot, entry.name), "utf8");
      if (protectedNames.some((name) => source.includes(name))) {
        unexpected.push(entry.name);
      }
    }
    expect(unexpected).toEqual([]);
  });
});

describe("external terminal tombstones", () => {
  test("retains only 256 tombstones and folds deterministic evictions", async () => {
    const [leftRoot, rightRoot] = await Promise.all([
      fixtureRoot(),
      fixtureRoot(),
    ]);
    const security = {
      securePrivatePath: vi.fn().mockResolvedValue(undefined),
    };
    const left = new ExternalUpdateTerminalStore({
      rootPath: leftRoot,
      security,
    });
    const right = new ExternalUpdateTerminalStore({
      rootPath: rightRoot,
      security,
    });
    for (let index = 0; index < 258; index += 1) {
      const tombstone = tombstoneFixture(index);
      await left.append(tombstone);
      await right.append(tombstone);
    }

    const leftIndex = await left.read();
    expect(leftIndex).toEqual(await right.read());
    expect(leftIndex).toMatchObject({
      version: 1,
      evictedCount: 2,
      priorAggregateChainRoot: expect.stringMatching(/^sha256:/u),
    });
    expect(leftIndex.tombstones).toHaveLength(256);
    expect(await left.find("external-00000002")).toEqual(
      leftIndex.tombstones[0],
    );
    expect(await left.find("external-00000000")).toBeNull();
  }, 60_000);

  test("preserves the prior index when an append fails before atomic rename", async () => {
    const root = await fixtureRoot();
    const security = {
      securePrivatePath: vi.fn().mockResolvedValue(undefined),
    };
    const store = new ExternalUpdateTerminalStore({ rootPath: root, security });
    await store.append(tombstoneFixture(0));
    const before = await store.read();
    const failing = new ExternalUpdateTerminalStore({
      rootPath: root,
      security,
      faultInjector(point) {
        if (point === "before_rename") throw new Error("fault");
      },
    });

    await expect(failing.append(tombstoneFixture(1))).rejects.toThrow("fault");
    expect(await store.read()).toEqual(before);
  });

  test("does not retry a terminal-store callback-owned busy failure", async () => {
    const root = await fixtureRoot();
    let callbackCount = 0;
    const callbackError = new C7ConfigError("busy", "callback busy");
    const store = new ExternalUpdateTerminalStore({
      rootPath: root,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
      faultInjector(point) {
        if (point === "before_rename") {
          callbackCount += 1;
          throw callbackError;
        }
      },
    });

    await expect(store.append(tombstoneFixture(0))).rejects.toBe(callbackError);
    expect(callbackCount).toBe(1);
  });

  test.each(["EPERM", "EACCES"] as const)(
    "retries an exact Win32 operation-lock acquisition %s",
    async (code) => {
      const root = await fixtureRoot();
      const store = new ExternalUpdateTerminalStore({
        rootPath: root,
        security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
      });
      lockAcquisitionInjection.createError = (runtimeDir) =>
        operationLockError(runtimeDir, code);

      await expect(store.append(tombstoneFixture(0))).resolves.toMatchObject({
        transactionId: "external-00000000",
      });
    },
  );

  test("does not retry an acquisition EPERM outside the exact lock root", async () => {
    const root = await fixtureRoot();
    const store = new ExternalUpdateTerminalStore({
      rootPath: root,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
    });
    const expectedError = operationLockError(
      path.join(path.dirname(root), "wrong-runtime"),
      "EPERM",
    );
    lockAcquisitionInjection.createError = () => expectedError;

    await expect(store.append(tombstoneFixture(0))).rejects.toBe(expectedError);
  });

  test("does not retry a callback-owned operation-looking EPERM", async () => {
    const root = await fixtureRoot();
    let callbackCount = 0;
    const expectedError = operationLockError(path.dirname(root), "EPERM");
    const store = new ExternalUpdateTerminalStore({
      rootPath: root,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
      faultInjector(point) {
        if (point === "before_rename") {
          callbackCount += 1;
          throw expectedError;
        }
      },
    });

    await expect(store.append(tombstoneFixture(0))).rejects.toBe(expectedError);
    expect(callbackCount).toBe(1);
  });

  test("rejects a linked terminal index replacement", async () => {
    const root = await fixtureRoot();
    const store = new ExternalUpdateTerminalStore({
      rootPath: root,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
    });
    await store.append(tombstoneFixture(0));
    const indexPath = path.join(root, "terminal-index.json");
    const targetPath = path.join(root, "terminal-index-target.json");
    const { rename, symlink } = await import("node:fs/promises");
    await rename(indexPath, targetPath);
    await symlink(targetPath, indexPath, "file");

    await expect(store.read()).rejects.toMatchObject({ code: "invalid_state" });
  });

  test("does not lose concurrent appends from independent terminal stores", async () => {
    const root = await fixtureRoot();
    const security = {
      securePrivatePath: vi.fn().mockResolvedValue(undefined),
    };
    const left = new ExternalUpdateTerminalStore({ rootPath: root, security });
    const right = new ExternalUpdateTerminalStore({ rootPath: root, security });

    await Promise.all([
      left.append(tombstoneFixture(0)),
      right.append(tombstoneFixture(1)),
    ]);

    expect(
      (await left.read()).tombstones
        .map(({ transactionId }) => transactionId)
        .sort(),
    ).toEqual(["external-00000000", "external-00000001"]);
  });

  test("accepts public-schema maximum terminal payload within the 16 MiB ceiling", () => {
    const payload = publishedFollowUpPayload(256, 4_096);
    const parsed = parseExternalTerminalPayload(payload);
    const bytes = Buffer.byteLength(stableJson(parsed), "utf8");

    expect(bytes).toBeLessThan(EXTERNAL_TERMINAL_PAYLOAD_MAX_BYTES);
    expect(parsed).toEqual(payload);
  });

  test("proves the public terminal schema canonical upper bound remains below 16 MiB", () => {
    const maximum = publishedFollowUpPayload(256, 4_096, {
      codeLength: 128,
      idLength: 160,
      pageLength: 32_768,
    });
    expect(parseExternalTerminalPayload(maximum)).toEqual(maximum);
    expect(Buffer.byteLength(stableJson(maximum), "utf8")).toBeLessThan(
      EXTERNAL_TERMINAL_PAYLOAD_MAX_BYTES,
    );
    expect(() =>
      parseExternalTerminalPayload(
        publishedFollowUpPayload(257, 4_096, {
          codeLength: 128,
          idLength: 160,
          pageLength: 32_768,
        }),
      ),
    ).toThrow();
  });

  test("evicts oldest legal near-maximum entries at the real 64 MiB index bound", async () => {
    const root = await fixtureRoot();
    const store = new ExternalUpdateTerminalStore({
      rootPath: root,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
    });
    const payload = publishedFollowUpPayload(256, 4_096, {
      codeLength: 128,
      idLength: 160,
      pageLength: 32_768,
    });
    const perEntryBytes = Buffer.byteLength(stableJson(payload), "utf8");
    const appendCount = Math.ceil(
      EXTERNAL_TERMINAL_INDEX_MAX_BYTES / perEntryBytes,
    );
    expect(appendCount).toBeLessThan(256);
    for (let index = 0; index < appendCount; index += 1) {
      await store.append(largeTombstoneFixture(index));
    }

    const index = await store.read();
    expect(index.tombstones.length).toBeLessThan(appendCount);
    expect(Buffer.byteLength(stableJson(index), "utf8")).toBeLessThanOrEqual(
      EXTERNAL_TERMINAL_INDEX_MAX_BYTES,
    );
    expect(index.evictedCount).toBeGreaterThan(0);
    expect(index.tombstones[0]?.transactionId).toBe("external-00000001");
    expect(index.priorAggregateChainRoot).toMatch(/^sha256:/u);
  }, 60_000);

  test.each(["payload", "resultHash", "inputHash"] as const)(
    "fails closed after terminal index %s tamper",
    async (field) => {
      const root = await fixtureRoot();
      const store = new ExternalUpdateTerminalStore({
        rootPath: root,
        security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
      });
      const tombstone = tombstoneFixture(0);
      await store.append(tombstone);
      const indexPath = path.join(root, "terminal-index.json");
      const persisted = JSON.parse(await readFile(indexPath, "utf8")) as {
        tombstones: Array<Record<string, unknown>>;
      };
      const target = persisted.tombstones[0]!;
      if (field === "payload") {
        target.payload = {
          ...(target.payload as Record<string, unknown>),
          transactionId: "external-tampered",
        };
      } else {
        target[field] = `sha256:${"f".repeat(64)}`;
      }
      await writeFile(indexPath, `${JSON.stringify(persisted)}\n`, "utf8");

      await expect(store.read()).rejects.toMatchObject({
        code: expect.stringMatching(/^(invalid_state|restore_required)$/u),
      });
      await expect(store.find(tombstone.transactionId)).rejects.toMatchObject({
        code: expect.stringMatching(/^(invalid_state|restore_required)$/u),
      });
    },
  );
});

function stateFixture(transactionRoot: string) {
  const hash = (character: string) => `sha256:${character.repeat(64)}`;
  const candidateRoot = path.join(
    transactionRoot,
    "generations",
    "1",
    "candidate",
  );
  const immutableRoot = path.join(transactionRoot, "immutable");
  return {
    version: 1 as const,
    transactionId: "external-12345678",
    requestId: "request-12345678",
    requestIdHash: hash("1"),
    inputHash: hash("2"),
    generation: 1,
    stage: "candidate_writable" as const,
    createdAt: "2026-08-12T00:00:00.000Z",
    updatedAt: "2026-08-12T00:00:00.000Z",
    beforeWikiRevision: hash("3"),
    sourceManifestHash: null,
    sourceTreeHash: null,
    skillAggregateHash: hash("4"),
    confirmedWikiPaths: ["index.md"],
    requestPackageHash: hash("5"),
    workspaceId: "workspace-12345678",
    bindingHash: hash("6"),
    transactionRoot,
    requestPackagePath: path.join(immutableRoot, "request.json"),
    hardRulePackagePath: path.join(immutableRoot, "hard-rules.md"),
    hardRulePackageHash: hash("7"),
    candidateResultContractPath: path.join(
      immutableRoot,
      "candidate-result-contract.json",
    ),
    candidateResultContractSchemaHash: hash("8"),
    candidateRoot,
    sourceRoot: null,
    skills: [
      {
        id: "kg-c7-project-wiki",
        category: "base" as const,
        loadOrder: "base_always_first" as const,
        packageHash: hash("9"),
        rootPath: path.join(immutableRoot, "skills", "000-kg-c7-project-wiki"),
      },
    ],
    failures: [],
    failureOverflowCount: 0,
    repairSuccessorGeneration: null,
    repairPredecessorBindingHash: null,
    review: null,
    terminalResultHash: null,
    terminalPayload: null,
  };
}

function reviewFixture(transactionRoot: string) {
  const hash = (character: string) => `sha256:${character.repeat(64)}`;
  return {
    candidateRootHash: hash("a"),
    candidateReceiptHash: hash("b"),
    reviewPackageHash: hash("c"),
    reviewPackagePath: path.join(
      transactionRoot,
      "generations",
      "1",
      "review-package.json",
    ),
  };
}

async function fixtureRoot(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-terminal-index-"));
  roots.push(root);
  return path.join(root, "external-updates");
}

function tombstoneFixture(index: number) {
  const suffix = String(index).padStart(8, "0");
  const hash = (character: string) =>
    `sha256:${character.repeat(63)}${(index % 16).toString(16)}`;
  const transactionId = `external-${suffix}`;
  const bindingHash = hash("2");
  const payload = {
    ok: true as const,
    executionMode: "external_agent" as const,
    authRequired: false as const,
    transactionId,
    generation: 1,
    bindingHash,
    recovery: { action: "none" as const },
    status: "external_update_aborted" as const,
    published: false as const,
  };
  return {
    version: 1 as const,
    transactionId,
    requestIdHash: hash("1"),
    inputHash: hash("3"),
    bindingHash,
    resultHash: computeExternalTerminalResultHash(payload),
    status: "external_update_aborted" as const,
    finalWikiRevision: hash("4"),
    generation: 1,
    completedAt: "2026-08-12T00:00:00.000Z",
    payload,
  };
}

function publishedFollowUpPayload(
  issueCount: number,
  messageLength: number,
  options?: { codeLength: number; idLength: number; pageLength: number },
) {
  const hash = (character: string) => `sha256:${character.repeat(64)}`;
  const id = (prefix: string) =>
    `${prefix}${"x".repeat(Math.max(0, (options?.idLength ?? prefix.length) - prefix.length))}`;
  return {
    ok: true as const,
    executionMode: "external_agent" as const,
    authRequired: false as const,
    transactionId: id("external-"),
    generation: 1,
    bindingHash: hash("1"),
    recovery: { action: "none" as const },
    status: "published_with_follow_up" as const,
    published: true as const,
    wikiRevision: hash("2"),
    candidateRootHash: hash("3"),
    reviewReceiptHash: hash("4"),
    reviewEvidence: "host_attested" as const,
    followUp: Array.from({ length: issueCount }, (_, index) => ({
      code: `i${String(index).padStart(3, "0")}${"x".repeat(Math.max(0, (options?.codeLength ?? 4) - 4))}`,
      message: "x".repeat(messageLength),
      ...(options === undefined
        ? {}
        : { page: "p".repeat(options.pageLength) }),
      severity: "provisional" as const,
    })),
  };
}

function largeTombstoneFixture(index: number) {
  const suffix = String(index).padStart(8, "0");
  const transactionId = `external-${suffix}`;
  const payload = {
    ...publishedFollowUpPayload(256, 4_096, {
      codeLength: 128,
      idLength: 160,
      pageLength: 32_768,
    }),
    transactionId,
  };
  const digest = (label: string) =>
    `sha256:${createHash("sha256").update(`${label}:${index}`).digest("hex")}`;
  return {
    version: 1 as const,
    transactionId,
    requestIdHash: digest("request"),
    inputHash: digest("input"),
    bindingHash: payload.bindingHash,
    resultHash: computeExternalTerminalResultHash(payload),
    status: "published_with_follow_up" as const,
    finalWikiRevision: payload.wikiRevision,
    generation: 1,
    completedAt: "2026-08-12T00:00:00.000Z",
    payload,
  };
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

function operationLockError(
  runtimeDir: string,
  code: "EACCES" | "EPERM",
): Error {
  const lockRoot = path.join(runtimeDir, "locks");
  return Object.assign(new Error(`${code}: operation lock rename`), {
    code,
    dest: path.join(lockRoot, "operation.lock"),
    path: path.join(lockRoot, "operation.pending.1234.injected"),
    syscall: "rename",
  });
}

async function expectOperationLockBlocks(
  runtimeDir: string,
  operation: () => Promise<void>,
): Promise<void> {
  let markAcquired!: () => void;
  let release!: () => void;
  const acquired = new Promise<void>((resolve) => {
    markAcquired = resolve;
  });
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const lock = withC7Locks(runtimeDir, ["operation"], async () => {
    markAcquired();
    await held;
  });
  await acquired;
  try {
    await expect(operation()).rejects.toMatchObject({ code: "busy" });
  } finally {
    release();
    await lock;
  }
}
