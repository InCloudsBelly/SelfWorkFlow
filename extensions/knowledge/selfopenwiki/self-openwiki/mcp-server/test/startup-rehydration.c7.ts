import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import {
  appendFile,
  mkdir,
  mkdtemp,
  readdir,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { rehydrateStartupRecovery } from "../src/bootstrap.js";
import { ExternalUpdateTransactionOwner } from "../src/external-update-transaction.js";
import { computeExternalPublishRunId } from "../src/publish.js";
import { WikiPublisher } from "../src/publish.js";
import { OpenWikiProcessRunner } from "../src/process.js";
import { OpenWikiReviewService } from "../src/review.js";
import { RuntimeModelService } from "../src/runtime-model-service.js";
import { WikiRecoveryService } from "../src/recovery.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import { aggregateSkillHash, computeSkillPackageHash } from "../src/skills.js";

const planReadFault = vi.hoisted(() => ({
  run: null as null | (() => Promise<void>),
}));
const planCloseFault = vi.hoisted(() => ({
  run: null as null | (() => Promise<void>),
}));
const recoveryReaddirFault = vi.hoisted(() => ({
  run: null as null | (() => Promise<void>),
}));

vi.mock("node:fs/promises", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:fs/promises")>();
  const runPlanReadFault = async (filePath: unknown) => {
    if (
      planReadFault.run !== null &&
      typeof filePath === "string" &&
      /(?:^|[\\/])plan\.json$/u.test(filePath)
    ) {
      const fault = planReadFault.run;
      planReadFault.run = null;
      await fault();
    }
  };
  return {
    ...original,
    async readdir(...args: Parameters<typeof original.readdir>) {
      const result = await original.readdir(...args);
      if (recoveryReaddirFault.run !== null) {
        const fault = recoveryReaddirFault.run;
        recoveryReaddirFault.run = null;
        await fault();
      }
      return result;
    },
    async open(...args: Parameters<typeof original.open>) {
      const handle = await original.open(...args);
      return new Proxy(handle, {
        get(target, property) {
          if (property === "close") {
            return async () => {
              await target.close();
              if (planCloseFault.run !== null) {
                const fault = planCloseFault.run;
                planCloseFault.run = null;
                await fault();
              }
            };
          }
          if (property === "read") {
            return async (...readArgs: Parameters<typeof target.read>) => {
              const result = await target.read(...readArgs);
              await runPlanReadFault(args[0]);
              return result;
            };
          }
          const value = Reflect.get(target, property, target) as unknown;
          return typeof value === "function" ? value.bind(target) : value;
        },
      });
    },
    async readFile(...args: Parameters<typeof original.readFile>) {
      const result = await original.readFile(...args);
      await runPlanReadFault(args[0]);
      return result;
    },
  };
});

const tempDirs: string[] = [];

afterEach(async () => {
  planReadFault.run = null;
  planCloseFault.run = null;
  recoveryReaddirFault.run = null;
  vi.restoreAllMocks();
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("external startup rehydration orchestration", () => {
  test("completes real marker-after V4 recovery without a legacy model pipeline", async () => {
    const fixture = await createExternalOwnerFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared);
    const publisher = new WikiPublisher({
      formalWikiPath: fixture.options.formalWikiPath,
      runtimeDir: fixture.options.runtimeDir,
      security: fixture.options.security,
    });
    await expect(
      owner.submitAndPublish({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        reviewReceipt: receipt,
        publish: async (input) => {
          await publisher.publishExternal(input);
          throw new Error("simulated response loss after marker");
        },
      }),
    ).rejects.toThrow("simulated response loss after marker");
    const legacyRecoverAll = vi.fn(async () => []);
    const reviewer = vi.spyOn(OpenWikiReviewService.prototype, "review");
    const model = vi.spyOn(
      RuntimeModelService.prototype,
      "resolveOpenWikiHome",
    );
    const providerOrFinalizer = vi.spyOn(
      OpenWikiProcessRunner.prototype,
      "run",
    );

    const startupOwner = new ExternalUpdateTransactionOwner(fixture.options);
    const startupRecover = vi.spyOn(startupOwner, "recoverStartup");
    const result = await rehydrateStartupRecovery({
      externalTransactions: startupOwner,
      legacyRecovery: { recoverAll: legacyRecoverAll },
      publisher,
      runtimeDir: fixture.options.runtimeDir,
    });

    expect(startupRecover).toHaveBeenCalledTimes(1);
    expect(await startupRecover.mock.results[0]!.value).toEqual({
      status: "external_startup_clean",
    });
    expect(result.externalState).toBe("clean");
    expect(
      (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
    ).toBe(prepared.state.review!.candidateRootHash);
    expect(legacyRecoverAll).toHaveBeenCalledTimes(1);
    for (const spy of [reviewer, model, providerOrFinalizer]) {
      expect(spy).not.toHaveBeenCalled();
    }
  });

  test.each(["candidate_writable", "review_ready"] as const)(
    "retains a valid %s external transaction without invoking publication",
    async (stage) => {
      const fixture = await createExternalOwnerFixture();
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const created = asWorkspace(await owner.start(fixture.input));
      if (stage === "review_ready") {
        await prepareReview(owner, created);
      }
      const publishExternal = vi.fn();
      const recoverStartup = vi.spyOn(owner, "recoverStartup");

      const result = await rehydrateStartupRecovery({
        externalTransactions: owner,
        legacyRecovery: { recoverAll: async () => [] },
        publisher: { publishExternal },
        runtimeDir: fixture.options.runtimeDir,
      });

      expect(result.externalState).toBe("clean");
      expect((await owner.readActive())?.state.stage).toBe(stage);
      expect(recoverStartup).toHaveBeenCalledTimes(1);
      expect(publishExternal).not.toHaveBeenCalled();
    },
  );

  test("recovers external publication before an exact mixed legacy recovery", async () => {
    const fixture = await createFixture();
    const externalRunId = externalRun("a");
    const legacyRunId = "run-legacy-12345678";
    await Promise.all([
      mkdir(path.join(fixture.recoveryRoot, externalRunId)),
      mkdir(path.join(fixture.recoveryRoot, legacyRunId)),
    ]);
    const order: string[] = [];
    const publishExternal = vi.fn(async () => {
      order.push("publisher");
      return { after: { rootHash: hash("c") } } as never;
    });
    const recoverStartup = vi.fn(async (input) => {
      order.push("external");
      await input.publish({} as never);
      await rm(path.join(fixture.recoveryRoot, externalRunId), {
        recursive: true,
      });
      return { status: "external_startup_clean" } as const;
    });
    const recoverAll = vi.fn(async () => {
      order.push("legacy");
      expect((await readdir(fixture.recoveryRoot)).sort()).toEqual([
        legacyRunId,
      ]);
      return [
        {
          recoveryState: "clean" as const,
          reviewPending: false,
          runId: legacyRunId,
        },
      ];
    });

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup,
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal },
      runtimeDir: fixture.runtimeDir,
    });

    expect(result.externalState).toBe("clean");
    expect(result.legacyResults).toHaveLength(1);
    expect(order).toEqual(["external", "publisher", "legacy"]);
    expect(recoverStartup).toHaveBeenCalledTimes(1);
  });

  test(
    "keeps one operation-to-wiki envelope through residual scan and legacy recovery",
    { timeout: 15_000 },
    async () => {
      const fixture = await createExternalOwnerFixture();
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const prepared = await prepareMinorReview(owner, fixture);
      const receipt = reviewReceiptFor(prepared);
      const publisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
      });
      const recoveryRoot = path.join(fixture.options.runtimeDir, "recovery");
      await mkdir(recoveryRoot, { recursive: true });
      const legacyRunId = "run-legacy-12345678";
      await mkdir(path.join(recoveryRoot, legacyRunId));
      let releaseLegacy!: () => void;
      const legacyBlocked = new Promise<void>((resolve) => {
        releaseLegacy = resolve;
      });
      let legacyEntered!: () => void;
      const atLegacy = new Promise<void>((resolve) => {
        legacyEntered = resolve;
      });
      const recovery = rehydrateStartupRecovery({
        externalTransactions: owner,
        legacyRecovery: {
          recoverAll: vi.fn(async () => {
            legacyEntered();
            await legacyBlocked;
            return [];
          }),
        },
        publisher,
        runtimeDir: fixture.options.runtimeDir,
      });
      await atLegacy;
      const publishDuringLock = vi.fn(async (input) => {
        const result = await publisher.publishExternal(input);
        return { wikiRevision: result.after.rootHash };
      });
      await expect(
        new ExternalUpdateTransactionOwner(fixture.options).submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: publishDuringLock,
        }),
      ).rejects.toMatchObject({ code: "busy" });

      expect(publishDuringLock).not.toHaveBeenCalled();
      expect(await readdir(recoveryRoot)).toEqual([legacyRunId]);
      releaseLegacy();
      await recovery;
      let observedV4Journal = false;
      const retryPublish = vi.fn(async (input) => {
        const result = await publisher.publishExternal(input);
        observedV4Journal = (await readdir(recoveryRoot)).some((name) =>
          name.startsWith("run-external-"),
        );
        return { wikiRevision: result.after.rootHash };
      });
      await expect(
        new ExternalUpdateTransactionOwner(fixture.options).submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: retryPublish,
        }),
      ).resolves.toMatchObject({ kind: "terminal" });
      expect(retryPublish).toHaveBeenCalledTimes(1);
      expect(observedV4Journal).toBe(true);
    },
  );

  test(
    "production rehydration blocks a real child finalize through legacy recovery",
    { timeout: 20_000 },
    async () => {
      const fixture = await createLegacyCommittedFixture();
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const prepared = await prepareMinorReview(owner, fixture);
      const publisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
      });
      const legacyRecovery = new WikiRecoveryService({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
      });
      const childInputPath = path.join(
        fixture.options.runtimeDir,
        "child-input.json",
      );
      await writeFile(
        childInputPath,
        JSON.stringify({
          formalWikiPath: fixture.options.formalWikiPath,
          runtimeDir: fixture.options.runtimeDir,
          submitInput: {
            action: "submit_review",
            bindingHash: prepared.state.bindingHash,
            reviewReceipt: reviewReceiptFor(prepared),
            transactionId: prepared.state.transactionId,
          },
        }),
      );
      const childPath = path.join(
        import.meta.dirname,
        "fixtures",
        "external-finalize-child.mjs",
      );

      let releaseLegacy!: () => void;
      const legacyBlocked = new Promise<void>((resolve) => {
        releaseLegacy = resolve;
      });
      let legacyEntered!: () => void;
      const atLegacy = new Promise<void>((resolve) => {
        legacyEntered = resolve;
      });
      const startup = rehydrateStartupRecovery({
        externalTransactions: owner,
        legacyRecovery: {
          recoverAll: async () => {
            legacyEntered();
            await legacyBlocked;
            return legacyRecovery.recoverAll();
          },
        },
        publisher,
        runtimeDir: fixture.options.runtimeDir,
      });
      await atLegacy;

      const blocked = await runFinalizeChild(childPath, childInputPath);
      expect(blocked).toMatchObject({ ok: false, code: "busy" });
      const recoveryEntries = await readdir(
        path.join(fixture.options.runtimeDir, "recovery"),
      ).catch(() => []);
      expect(
        recoveryEntries.filter((entry) => entry.startsWith("run-external-")),
      ).toEqual([]);

      releaseLegacy();
      await expect(startup).resolves.toMatchObject({
        externalState: "clean",
        legacyResults: [
          {
            recoveryState: "review_pending",
            reviewPending: true,
            runId: fixture.runId,
          },
        ],
      });

      const retried = await runFinalizeChild(childPath, childInputPath);
      expect(retried).toMatchObject({
        ok: true,
        result: { published: true, status: "published" },
      });
      expect(
        (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
      ).toBe(prepared.state.review!.candidateRootHash);
    },
  );

  test("delegates a V3-only recovery root to the unchanged legacy recovery", async () => {
    const fixture = await createFixture();
    const legacyRunId = "run-legacy-12345678";
    await mkdir(path.join(fixture.recoveryRoot, legacyRunId));
    const recoverAll = vi.fn(async () => [
      {
        recoveryState: "clean" as const,
        reviewPending: false,
        runId: legacyRunId,
      },
    ]);
    const recoverStartup = vi.fn(async () => ({
      status: "external_startup_clean" as const,
    }));

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup,
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal: vi.fn() },
      runtimeDir: fixture.runtimeDir,
    });

    expect(result).toEqual({
      externalState: "clean",
      legacyResults: [
        {
          recoveryState: "clean",
          reviewPending: false,
          runId: legacyRunId,
        },
      ],
    });
    expect(recoverStartup).toHaveBeenCalledTimes(1);
    expect(recoverAll).toHaveBeenCalledTimes(1);
  });

  test.each(["v3-only", "mixed-v3-v4"] as const)(
    "runs real %s startup recovery without manufacturing a V4 Review obligation",
    async (mode) => {
      const legacy = await createLegacyCommittedFixture();
      const startupOwner = new ExternalUpdateTransactionOwner(legacy.options);
      const publisher = new WikiPublisher({
        formalWikiPath: legacy.options.formalWikiPath,
        runtimeDir: legacy.options.runtimeDir,
        security: legacy.options.security,
      });
      if (mode === "mixed-v3-v4") {
        const faultingOwner = new ExternalUpdateTransactionOwner({
          ...legacy.options,
          faultInjector(point) {
            if (point === "after_active_pointer_cleanup") {
              throw new Error("startup response lost after terminal cleanup");
            }
          },
        });
        const prepared = await prepareNoopReview(faultingOwner, legacy);
        await expect(
          faultingOwner.submitAndPublish({
            transactionId: prepared.state.transactionId,
            bindingHash: prepared.state.bindingHash,
            reviewReceipt: reviewReceiptFor(prepared),
            publish: async (input) => {
              const result = await publisher.publishExternal(input);
              return { wikiRevision: result.after.rootHash };
            },
          }),
        ).rejects.toThrow("startup response lost after terminal cleanup");
        expect(
          (
            await readdir(path.join(legacy.options.runtimeDir, "recovery"))
          ).filter((entry) => entry.startsWith("run-external-")),
        ).toHaveLength(1);
      }
      const recovery = new WikiRecoveryService({
        formalWikiPath: legacy.options.formalWikiPath,
        runtimeDir: legacy.options.runtimeDir,
        security: legacy.options.security,
      });

      const result = await rehydrateStartupRecovery({
        externalTransactions: startupOwner,
        legacyRecovery: recovery,
        publisher,
        runtimeDir: legacy.options.runtimeDir,
      });

      expect(result.externalState).toBe("clean");
      expect(result.legacyResults).toEqual([
        expect.objectContaining({
          recoveryState: "review_pending",
          reviewPending: true,
          runId: legacy.runId,
        }),
      ]);
      expect(result.legacyResults[0]!.reviewObligation).toMatchObject({
        model: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
      });
      expect(
        (
          await readdir(path.join(legacy.options.runtimeDir, "recovery"))
        ).filter((entry) => entry.startsWith("run-external-")),
      ).toEqual([]);
    },
  );

  test.each(["", ".initializing", ".initializing.cleanup", ".cleanup"])(
    "fails closed on deterministic external recovery root suffix %j",
    async (suffix) => {
      const fixture = await createFixture();
      await mkdir(
        path.join(fixture.recoveryRoot, `${externalRun("b")}${suffix}`),
      );
      const recoverAll = vi.fn(async () => []);
      const recoverStartup = vi.fn(async () => ({
        status: "external_startup_clean" as const,
      }));

      const result = await rehydrateStartupRecovery({
        externalTransactions: {
          recoverStartup,
        },
        legacyRecovery: { recoverAll },
        publisher: { publishExternal: vi.fn() },
        runtimeDir: fixture.runtimeDir,
      });

      expect(result).toEqual({
        externalState: "restore_required",
        legacyResults: [],
      });
      expect(recoverStartup).toHaveBeenCalledTimes(1);
      expect(recoverAll).not.toHaveBeenCalled();
    },
  );

  test("fails closed on an oversized external recovery plan without reading it", async () => {
    const fixture = await createFixture();
    const journal = path.join(fixture.recoveryRoot, "run-unknown-oversized");
    await mkdir(journal);
    await writeFile(
      path.join(journal, "plan.json"),
      `{"version":4,"executionMode":"external_agent","padding":"${"x".repeat(4 * 1024 * 1024)}"}`,
    );
    const recoverAll = vi.fn(async () => []);

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup: vi.fn(async () => ({
          status: "external_startup_clean" as const,
        })),
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal: vi.fn() },
      runtimeDir: fixture.runtimeDir,
    });

    expect(result).toEqual({
      externalState: "restore_required",
      legacyResults: [],
    });
    expect(recoverAll).not.toHaveBeenCalled();
  });

  test.each(["directory", "symlink"] as const)(
    "fails closed on a %s external recovery plan entry",
    async (entryKind) => {
      const fixture = await createFixture();
      const journal = path.join(
        fixture.recoveryRoot,
        `run-unknown-${entryKind}-plan`,
      );
      const planPath = path.join(journal, "plan.json");
      await mkdir(journal);
      if (entryKind === "directory") {
        await mkdir(planPath);
      } else {
        const target = path.join(fixture.runtimeDir, "plan-target");
        await mkdir(target);
        await symlink(
          target,
          planPath,
          process.platform === "win32" ? "junction" : "dir",
        );
      }
      const recoverAll = vi.fn(async () => []);

      const result = await rehydrateStartupRecovery({
        externalTransactions: {
          recoverStartup: vi.fn(async () => ({
            status: "external_startup_clean" as const,
          })),
        },
        legacyRecovery: { recoverAll },
        publisher: { publishExternal: vi.fn() },
        runtimeDir: fixture.runtimeDir,
      });

      expect(result).toEqual({
        externalState: "restore_required",
        legacyResults: [],
      });
      expect(recoverAll).not.toHaveBeenCalled();
    },
  );

  test("fails closed on an unknown run journal root junction", async () => {
    const fixture = await createFixture();
    const target = path.join(fixture.runtimeDir, "linked-journal-target");
    await mkdir(target);
    await writeFile(path.join(target, "plan.json"), '{"version":3}');
    await symlink(
      target,
      path.join(fixture.recoveryRoot, "run-unknown-linked-root"),
      process.platform === "win32" ? "junction" : "dir",
    );
    const recoverAll = vi.fn(async () => []);

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup: vi.fn(async () => ({
          status: "external_startup_clean" as const,
        })),
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal: vi.fn() },
      runtimeDir: fixture.runtimeDir,
    });

    expect(result).toEqual({
      externalState: "restore_required",
      legacyResults: [],
    });
    expect(recoverAll).not.toHaveBeenCalled();
  });

  test.each([
    ["duplicate version", '{"version":4,"version":3}'],
    [
      "duplicate execution mode",
      '{"executionMode":"external_agent","executionMode":"legacy"}',
    ],
    ["escaped version key", '{"\\u0076ersion":4}'],
    [
      "escaped execution mode key and value",
      '{"execu\\u0074ionMode":"external_\\u0061gent"}',
    ],
    ["integer version", '{"version":4}'],
    ["decimal version", '{"version":4.0}'],
    ["exponent version", '{"version":4e0}'],
  ] as const)(
    "fails closed on %s discriminator syntax",
    async (_label, plan) => {
      const fixture = await createFixture();
      const journal = path.join(
        fixture.recoveryRoot,
        "run-unknown-discriminator",
      );
      await mkdir(journal);
      await writeFile(path.join(journal, "plan.json"), plan);
      const recoverAll = vi.fn(async () => []);

      const result = await rehydrateStartupRecovery({
        externalTransactions: {
          recoverStartup: vi.fn(async () => ({
            status: "external_startup_clean" as const,
          })),
        },
        legacyRecovery: { recoverAll },
        publisher: { publishExternal: vi.fn() },
        runtimeDir: fixture.runtimeDir,
      });

      expect(result).toEqual({
        externalState: "restore_required",
        legacyResults: [],
      });
      expect(recoverAll).not.toHaveBeenCalled();
    },
  );

  test.each(["replacement", "growth", "truncation"] as const)(
    "fails closed when plan.json undergoes %s while being read",
    async (mutation) => {
      const fixture = await createFixture();
      const journal = path.join(
        fixture.recoveryRoot,
        "run-unknown-racing-plan",
      );
      const planPath = path.join(journal, "plan.json");
      await mkdir(journal);
      await writeFile(planPath, '{"version":3}');
      planReadFault.run = async () => {
        if (mutation === "replacement") {
          await rename(planPath, path.join(journal, "plan.before.json"));
          await writeFile(planPath, '{"version":3}');
        } else if (mutation === "growth") {
          await appendFile(planPath, " ");
        } else {
          await writeFile(planPath, "{}");
        }
      };
      const recoverAll = vi.fn(async () => []);

      const result = await rehydrateStartupRecovery({
        externalTransactions: {
          recoverStartup: vi.fn(async () => ({
            status: "external_startup_clean" as const,
          })),
        },
        legacyRecovery: { recoverAll },
        publisher: { publishExternal: vi.fn() },
        runtimeDir: fixture.runtimeDir,
      });

      expect(result).toEqual({
        externalState: "restore_required",
        legacyResults: [],
      });
      expect(recoverAll).not.toHaveBeenCalled();
    },
  );

  test("fails closed when a journal root becomes a junction after plan inspection", async () => {
    const fixture = await createFixture();
    const journalName = "run-unknown-parent-race";
    const journal = path.join(fixture.recoveryRoot, journalName);
    const movedJournal = path.join(fixture.runtimeDir, "moved-journal");
    await mkdir(journal);
    await writeFile(path.join(journal, "plan.json"), '{"version":3}');
    planCloseFault.run = async () => {
      await rename(journal, movedJournal);
      await symlink(
        movedJournal,
        journal,
        process.platform === "win32" ? "junction" : "dir",
      );
    };
    const recoverAll = vi.fn(async () => []);

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup: vi.fn(async () => ({
          status: "external_startup_clean" as const,
        })),
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal: vi.fn() },
      runtimeDir: fixture.runtimeDir,
    });

    expect(planCloseFault.run).toBeNull();
    expect(result).toEqual({
      externalState: "restore_required",
      legacyResults: [],
    });
    expect(recoverAll).not.toHaveBeenCalled();
  });

  test("fails closed when the recovery root becomes a junction after final entry enumeration", async () => {
    const fixture = await createFixture();
    const journal = path.join(fixture.recoveryRoot, "run-parent-final-race");
    const movedRecoveryRoot = path.join(fixture.runtimeDir, "moved-recovery");
    await mkdir(journal);
    await writeFile(path.join(journal, "plan.json"), '{"version":3}');
    planCloseFault.run = async () => {
      recoveryReaddirFault.run = async () => {
        await rename(fixture.recoveryRoot, movedRecoveryRoot);
        await symlink(
          movedRecoveryRoot,
          fixture.recoveryRoot,
          process.platform === "win32" ? "junction" : "dir",
        );
      };
    };
    const recoverAll = vi.fn(async () => []);

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup: vi.fn(async () => ({
          status: "external_startup_clean" as const,
        })),
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal: vi.fn() },
      runtimeDir: fixture.runtimeDir,
    });

    expect(planCloseFault.run).toBeNull();
    expect(recoveryReaddirFault.run).toBeNull();
    expect(result).toEqual({
      externalState: "restore_required",
      legacyResults: [],
    });
    expect(recoverAll).not.toHaveBeenCalled();
  });

  test.each([
    { executionMode: "external_agent", version: 5 },
    { executionMode: "unknown", version: 4 },
  ])("fails closed on a V4-shaped unknown plan %#", async (plan) => {
    const fixture = await createFixture();
    const runId = "run-unknown-12345678";
    const journal = path.join(fixture.recoveryRoot, runId);
    await mkdir(journal);
    await writeFile(path.join(journal, "plan.json"), JSON.stringify(plan));
    const recoverAll = vi.fn();

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup: vi.fn(async () => ({
          status: "external_startup_clean" as const,
        })),
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal: vi.fn() },
      runtimeDir: fixture.runtimeDir,
    });

    expect(result.externalState).toBe("restore_required");
    expect(result.legacyResults).toEqual([]);
    expect(recoverAll).not.toHaveBeenCalled();
  });

  test("fails closed on a truncated external-agent plan discriminator", async () => {
    const fixture = await createFixture();
    const journal = path.join(fixture.recoveryRoot, "run-unknown-12345678");
    await mkdir(journal);
    await writeFile(
      path.join(journal, "plan.json"),
      '{"version":4,"executionMode":"external_agent"',
    );
    const recoverAll = vi.fn(async () => []);

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup: vi.fn(async () => ({
          status: "external_startup_clean" as const,
        })),
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal: vi.fn() },
      runtimeDir: fixture.runtimeDir,
    });

    expect(result).toEqual({
      externalState: "restore_required",
      legacyResults: [],
    });
    expect(recoverAll).not.toHaveBeenCalled();
  });

  test("uses a strict retained tombstone to reconcile a quarantined external journal", async () => {
    const fixture = await createFixture();
    const tombstone = {
      bindingHash: hash("d"),
      generation: 1,
      payload: {
        reviewReceiptHash: hash("e"),
        status: "published",
      },
      status: "published",
      transactionId: "external-12345678",
    };
    const runId = computeExternalPublishRunId({
      bindingHash: tombstone.bindingHash,
      generation: tombstone.generation,
      reviewReceiptHash: tombstone.payload.reviewReceiptHash,
      transactionId: tombstone.transactionId,
    });
    await mkdir(path.join(fixture.recoveryRoot, `${runId}.cleanup`));
    const recoverStartup = vi.fn(async () => {
      await rm(path.join(fixture.recoveryRoot, `${runId}.cleanup`), {
        recursive: true,
      });
      return { status: "external_startup_clean" } as const;
    });
    const recoverAll = vi.fn(async () => []);

    const result = await rehydrateStartupRecovery({
      externalTransactions: {
        recoverStartup,
      },
      legacyRecovery: { recoverAll },
      publisher: { publishExternal: vi.fn() },
      runtimeDir: fixture.runtimeDir,
    });

    expect(result.externalState).toBe("clean");
    expect(recoverStartup).toHaveBeenCalledTimes(1);
    expect(recoverAll).toHaveBeenCalledTimes(1);
  });
});

async function runFinalizeChild(
  childPath: string,
  inputPath: string,
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [childPath, inputPath], {
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    child.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
    child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
    child.once("error", reject);
    child.once("close", (code) => {
      const output = Buffer.concat(stdout).toString("utf8").trim();
      if (code !== 0 || output.length === 0) {
        resolve({
          code: "child_failed",
          exitCode: code,
          ok: false,
          stderr: Buffer.concat(stderr).toString("utf8"),
        });
        return;
      }
      try {
        resolve(JSON.parse(output) as Record<string, unknown>);
      } catch (error) {
        reject(error);
      }
    });
  });
}

async function createFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-startup-rehydrate-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const recoveryRoot = path.join(runtimeDir, "recovery");
  await mkdir(recoveryRoot, { recursive: true });
  return { recoveryRoot, runtimeDir };
}

function externalRun(character: string): string {
  return `run-external-${character.repeat(64)}`;
}

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}

async function createExternalOwnerFixture() {
  const fixture = await createFixture();
  const formalWikiPath = path.join(fixture.runtimeDir, "wiki");
  await mkdir(formalWikiPath, { recursive: true });
  await writeFile(
    path.join(formalWikiPath, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n",
    "utf8",
  );
  await writeFile(
    path.join(formalWikiPath, "quickstart.md"),
    "---\ntype: Guide\n---\n\n# Quickstart\n\nSee [home](./index.md).\n",
    "utf8",
  );
  const before = await snapshotMarkdownTree(formalWikiPath);
  const bytes = Buffer.from("# Base Skill\n", "utf8");
  const skillFile = {
    relativePath: "SKILL.md",
    bytes,
    size: bytes.byteLength,
    hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
  };
  const baseSkill = {
    id: "kg-c7-project-wiki",
    category: "base" as const,
    loadOrder: "base_always_first" as const,
    packageHash: computeSkillPackageHash([skillFile]),
    verified: true,
    description: "base",
    title: "base",
    files: [skillFile],
  };
  const security = { securePrivatePath: vi.fn().mockResolvedValue(undefined) };
  return {
    options: {
      runtimeDir: fixture.runtimeDir,
      formalWikiPath,
      security,
      createTransactionId: () => "external-12345678",
      createWorkspaceId: () => "workspace-12345678",
      now: () => new Date("2026-08-12T00:00:00.000Z"),
    },
    input: {
      requestId: "request-12345678",
      sourceManifestId: null,
      instruction: "Refresh the project overview.",
      materials: [{ id: "material-1", content: "Evidence" }],
      expectedWikiRevision: before.rootHash,
      confirmedWikiPaths: ["index.md"],
      skills: {
        aggregateHash: aggregateSkillHash([baseSkill]),
        skills: [baseSkill],
      },
      hardRulePackage: Buffer.from("hard rules\n", "utf8"),
      candidateResultContract: Buffer.from('{"version":1}\n', "utf8"),
    },
  };
}

async function createLegacyCommittedFixture() {
  const fixture = await createExternalOwnerFixture();
  const security = { async securePrivatePath() {} };
  const options = { ...fixture.options, security };
  const candidateWikiPath = path.join(
    fixture.options.runtimeDir,
    "legacy-candidate",
  );
  await mkdir(candidateWikiPath);
  await writeFile(
    path.join(candidateWikiPath, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n",
  );
  await writeFile(
    path.join(candidateWikiPath, "quickstart.md"),
    "---\ntype: Guide\n---\n\n# Quickstart\n\nSee [home](./index.md).\n",
  );
  const selectedSkills = fixture.input.skills;
  const publisher = new WikiPublisher({
    formalWikiPath: options.formalWikiPath,
    runtimeDir: options.runtimeDir,
    security,
  });
  const runId = "run-legacy-real-12345678";
  await publisher.publish({
    after: await snapshotMarkdownTree(candidateWikiPath),
    before: await snapshotMarkdownTree(fixture.options.formalWikiPath),
    binding: {
      model: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
      skillAggregateHash: selectedSkills.aggregateHash,
      sourceManifestHash: null,
      sourceTreeHash: null,
    },
    candidateWikiPath,
    review: {
      instruction: "Review the legacy Wiki publication.",
      selectedSkills,
    },
    runId,
  });
  return {
    ...fixture,
    options,
    input: {
      ...fixture.input,
      expectedWikiRevision: (
        await snapshotMarkdownTree(fixture.options.formalWikiPath)
      ).rootHash,
    },
    runId,
  };
}

function asWorkspace(
  result: Awaited<ReturnType<ExternalUpdateTransactionOwner["start"]>>,
) {
  if ("kind" in result) throw new Error("expected active workspace");
  return result;
}

async function prepareReview(
  owner: ExternalUpdateTransactionOwner,
  created: ReturnType<typeof asWorkspace>,
) {
  await writeFile(
    path.join(created.state.candidateRoot, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n\nUpdated knowledge.\n",
    "utf8",
  );
  const candidateReceipt = {
    type: "external_candidate_receipt" as const,
    version: 1 as const,
    transactionId: created.state.transactionId,
    generation: created.state.generation,
    bindingHash: created.state.bindingHash,
    writerExecutionId: "writer-execution-12345678",
    classification: "minor" as const,
    issues: [],
    questions: [],
    summary: "Candidate ready for independent Review.",
  };
  const result = await owner.prepareReview({
    transactionId: created.state.transactionId,
    bindingHash: created.state.bindingHash,
    candidateReceipt,
    reviewResultContract: Buffer.from('{"version":1}\n', "utf8"),
  });
  if (result.kind !== "review_ready") throw new Error("expected review-ready");
  return { ...result, candidateReceipt };
}

async function prepareMinorReview(
  owner: ExternalUpdateTransactionOwner,
  fixture: {
    readonly input: Parameters<ExternalUpdateTransactionOwner["start"]>[0];
  },
) {
  const created = asWorkspace(await owner.start(fixture.input));
  return prepareReview(owner, created);
}

async function prepareNoopReview(
  owner: ExternalUpdateTransactionOwner,
  fixture: {
    readonly input: Parameters<ExternalUpdateTransactionOwner["start"]>[0];
  },
) {
  const created = asWorkspace(await owner.start(fixture.input));
  const candidateReceipt = {
    type: "external_candidate_receipt" as const,
    version: 1 as const,
    transactionId: created.state.transactionId,
    generation: created.state.generation,
    bindingHash: created.state.bindingHash,
    writerExecutionId: "writer-execution-12345678",
    classification: "minor" as const,
    issues: [],
    questions: [],
    summary: "Exact candidate ready for independent Review.",
  };
  const result = await owner.prepareReview({
    transactionId: created.state.transactionId,
    bindingHash: created.state.bindingHash,
    candidateReceipt,
    reviewResultContract: Buffer.from('{"version":1}\n', "utf8"),
  });
  if (result.kind !== "review_ready") throw new Error("expected review-ready");
  return { ...result, candidateReceipt };
}

function reviewReceiptFor(
  prepared: Awaited<ReturnType<typeof prepareMinorReview>>,
) {
  return {
    type: "external_review_receipt" as const,
    version: 1 as const,
    transactionId: prepared.state.transactionId,
    generation: prepared.state.generation,
    bindingHash: prepared.state.bindingHash,
    reviewPackageHash: prepared.reviewPackageHash,
    candidateRootHash: prepared.state.review!.candidateRootHash,
    candidateReceiptHash: prepared.state.review!.candidateReceiptHash,
    reviewerExecutionId: "reviewer-execution-12345678",
    verdict: "pass" as const,
    issues: [],
  };
}
