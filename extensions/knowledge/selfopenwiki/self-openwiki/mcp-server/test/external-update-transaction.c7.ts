import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import { aggregateSkillHash, computeSkillPackageHash } from "../src/skills.js";
import {
  C7ConfigError,
  recoverStaleC7Locks,
  withC7Locks,
} from "../src/config.js";
import { ExternalUpdateTransactionOwner } from "../src/external-update-transaction.js";
import {
  computeExternalTerminalResultHash,
  transitionExternalUpdateState,
} from "../src/external-update-state.js";
import { hashSourceSnapshotTree } from "../src/sources.js";
import { computeExternalPublishRunId, WikiPublisher } from "../src/publish.js";
import {
  FilePersonalRunStore,
  type PersonalRunState,
} from "../src/personal-run-store.js";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) => rm(root, { force: true, recursive: true })),
  );
});

describe("external update transaction owner", () => {
  test.each([
    { version: 4, faultPoint: "after_plan" },
    { version: 4, faultPoint: "after_install" },
    { version: 5, faultPoint: "after_plan" },
    { version: 5, faultPoint: "after_stable_mode" },
    { version: 5, faultPoint: "after_displace" },
    { version: 5, faultPoint: "after_install" },
  ] as const)(
    "safely aborts a rolled-back v$version publication after $faultPoint",
    async ({ version, faultPoint }) => {
      const fixture = await createFixture();
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const prepared = await prepareMinorReview(owner, fixture);
      const before = await snapshotMarkdownTree(fixture.options.formalWikiPath);
      const receipt = reviewReceiptFor(prepared, {
        verdict: "pass",
        issues: [],
      });
      const publisher = new WikiPublisher({
        ...fixture.options,
        fault(point) {
          if (point === faultPoint) throw new Error("publication failed");
        },
      });
      await expect(
        owner.submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: async (input) => ({
            wikiRevision: (
              await publisher.publishExternal({
                ...input,
                plan: { ...input.plan, version },
              })
            ).after.rootHash,
          }),
        }),
      ).rejects.toMatchObject({ code: "publish_failed" });
      expect(
        await snapshotMarkdownTree(fixture.options.formalWikiPath),
      ).toEqual(before);
      await expect(
        owner.completeTerminal({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          terminalPayload: abortedPayload(prepared),
        }),
      ).resolves.toMatchObject({
        status: "external_update_aborted",
        finalWikiRevision: before.rootHash,
      });
      expect(await owner.readActive()).toBeNull();
      expect(
        await snapshotMarkdownTree(fixture.options.formalWikiPath),
      ).toEqual(before);
    },
  );

  test.each([false, true])(
    "preserves a partial v5 publication on abort (mode retained: %s)",
    async (modeRetained) => {
      const fixture = await createFixture();
      fixture.input.confirmedWikiPaths.push("quickstart.md");
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const prepared = await prepareMinorReview(owner, fixture, true);
      const receipt = reviewReceiptFor(prepared, {
        verdict: "pass",
        issues: [],
      });
      const publisher = new WikiPublisher({
        ...fixture.options,
        fault(point) {
          if (point === (modeRetained ? "after_stable_mode" : "after_plan"))
            throw new Error("retained before journal");
        },
      });
      await expect(
        owner.submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: async (input) => ({
            wikiRevision: (await publisher.publishExternal(input)).after
              .rootHash,
          }),
        }),
      ).rejects.toMatchObject({ code: "publish_failed" });
      await writeFile(
        path.join(fixture.options.formalWikiPath, "index.md"),
        await readFile(path.join(prepared.state.candidateRoot, "index.md")),
      );
      const partial = await snapshotMarkdownTree(
        fixture.options.formalWikiPath,
      );
      await expect(
        owner.completeTerminal({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          terminalPayload: abortedPayload(prepared),
        }),
      ).rejects.toMatchObject({ code: "restore_required" });
      expect((await owner.readActive())?.state.stage).toBe("publish_pending");
      expect(
        await snapshotMarkdownTree(fixture.options.formalWikiPath),
      ).toEqual(partial);
    },
  );

  test.each(
    (
      [
        "after_plan",
        "after_stable_mode",
        "after_displace",
        "before_marker_rename",
        "after_marker",
      ] as const
    ).flatMap((publishFaultPoint) =>
      [false, true].map((upgrade) => ({
        publishFaultPoint,
        upgrade,
        expectedState:
          publishFaultPoint === "after_displace"
            ? "mixed"
            : ["before_marker_rename", "after_marker"].includes(
                  publishFaultPoint,
                )
              ? "after"
              : "before",
      })),
    ),
  )(
    "cold-recovers a real v5 process exit at $publishFaultPoint with its original review receipt (v4 upgrade: $upgrade)",
    async ({ publishFaultPoint, upgrade, expectedState }) => {
      const fixture = await createFixture();
      fixture.input.confirmedWikiPaths.push("quickstart.md");
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const prepared = await prepareMinorReview(owner, fixture, true);
      const receipt = reviewReceiptFor(prepared, {
        verdict: "pass",
        issues: [],
      });
      const request = {
        action: "submit_review",
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        reviewReceipt: receipt,
      };
      if (upgrade) {
        const oldPublisher = new WikiPublisher({
          ...fixture.options,
          fault: (point) => {
            if (point === "after_plan")
              throw new Error("old pending publication");
          },
        });
        await expect(
          owner.submitAndPublish({
            ...request,
            publish: async (input) => ({
              wikiRevision: (
                await oldPublisher.publishExternal({
                  ...input,
                  plan: { ...input.plan, version: 4 },
                })
              ).after.rootHash,
            }),
          }),
        ).rejects.toMatchObject({ code: "publish_failed" });
      }
      const inputPath = path.join(
        path.dirname(fixture.options.runtimeDir),
        "child-input.json",
      );
      await writeFile(
        inputPath,
        JSON.stringify({
          ...fixture.options,
          submitInput: request,
          publishFaultPoint,
        }),
      );
      const child = spawnSync(
        process.execPath,
        [
          path.join(
            import.meta.dirname,
            "fixtures",
            "external-finalize-child.mjs",
          ),
          inputPath,
        ],
        { encoding: "utf8", timeout: 20_000 },
      );
      expect({
        status: child.status,
        error: child.error?.message,
        stdout: child.stdout,
        stderr: child.stderr,
      }).toEqual({ status: 86, error: undefined, stdout: "", stderr: "" });
      expect(await recoverStaleC7Locks(fixture.options.runtimeDir)).toEqual(
        expect.arrayContaining(["operation", "wiki"]),
      );
      const interrupted = await snapshotMarkdownTree(
        fixture.options.formalWikiPath,
      );
      expect(
        interrupted.rootHash === prepared.state.beforeWikiRevision
          ? "before"
          : interrupted.rootHash === prepared.state.review!.candidateRootHash
            ? "after"
            : "mixed",
      ).toBe(expectedState);
      const publisher = new WikiPublisher(fixture.options);
      const recovered = await new ExternalUpdateTransactionOwner({
        ...fixture.options,
        now: () => new Date(),
      }).recoverPublishPending({
        transactionId: prepared.state.transactionId,
        publish: async (input) => ({
          wikiRevision: (await publisher.publishExternal(input)).after.rootHash,
        }),
      });
      expect(recovered.terminalPayload).toMatchObject({
        status: "published",
        reviewReceiptHash: independentReviewReceiptHash(receipt),
        wikiRevision: prepared.state.review!.candidateRootHash,
      });
      expect(await owner.readActive()).toBeNull();
      expect(
        (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
      ).toBe(prepared.state.review!.candidateRootHash);
    },
    30_000,
  );

  test("cold personal begin survives C7 start and confirmed abort before attachCandidate", async () => {
    const fixture = await createFixture();
    const runtimeRoot = `${fixture.options.formalWikiPath}.selfopenwiki`;
    const owner = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      runtimeDir: runtimeRoot,
    });
    const input = {
      mode: "update" as const,
      force: true,
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: fixture.input.expectedWikiRevision,
      wikiRoot: fixture.options.formalWikiPath,
      runtimeRoot,
    };
    const options = {
      runtimeRoot: input.runtimeRoot,
      isRunAborted: (run: PersonalRunState) =>
        owner.isRequestAborted(run.runId),
    };
    const store = new FilePersonalRunStore(options);
    const begun = await store.begin(input);
    if (begun.status !== "planning") throw new Error("expected Run");
    const started = asWorkspace(
      await owner.start({ ...fixture.input, requestId: begun.runId }),
    );
    // Simulate process loss here: C7 start is durable, Run attach has not happened.
    await owner.completeTerminal({
      transactionId: started.state.transactionId,
      bindingHash: started.state.bindingHash,
      terminalPayload: abortedPayload(started),
    });
    const next = await new FilePersonalRunStore(options).begin(input);
    expect(next.status).toBe("planning");
    expect("runId" in next && next.runId).not.toBe(begun.runId);
    expect((await store.read(begun.runId)).candidate).toBeUndefined();
  });
  test("rehydrates owner-only external startup state without reacquiring locks", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const publish = vi.fn();

    const result = await owner.recoverStartup({ publish });

    expect(result).toEqual({ status: "external_startup_clean" });
    expect(Object.keys(result)).toEqual(["status"]);
    expect((await owner.readActive())?.state.transactionId).toBe(
      created.state.transactionId,
    );
    expect(publish).not.toHaveBeenCalled();
  });

  test(
    "direct startup recovery acquires the existing operation and Wiki locks",
    { timeout: 10_000 },
    async () => {
      const fixture = await createFixture();
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      await owner.start(fixture.input);
      let entered!: () => void;
      const lockEntered = new Promise<void>((resolve) => {
        entered = resolve;
      });
      let release!: () => void;
      const held = new Promise<void>((resolve) => {
        release = resolve;
      });
      const holder = withC7Locks(
        fixture.options.runtimeDir,
        ["operation", "wiki"],
        async () => {
          entered();
          await held;
        },
      );
      await lockEntered;

      await expect(
        owner.recoverStartup({ publish: vi.fn() }),
      ).rejects.toMatchObject({ code: "busy" });
      release();
      await holder;
      await expect(owner.recoverStartup({ publish: vi.fn() })).resolves.toEqual(
        { status: "external_startup_clean" },
      );
    },
  );

  test("fails startup closed when an active immutable snapshot is missing", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    await rm(created.state.hardRulePackagePath);

    const result = await owner.recoverStartup({
      publish: vi.fn(),
    });

    expect(result).toEqual({
      status: "external_startup_restore_required",
    });
    await expect(lstat(created.state.transactionRoot)).resolves.toMatchObject(
      {},
    );
  });

  test("rejects a self-consistent state whose transaction identity differs from its root", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const statePath = path.join(created.state.transactionRoot, "state.json");
    const persisted = JSON.parse(await readFile(statePath, "utf8")) as Record<
      string,
      unknown
    >;
    persisted.transactionId = "external-87654321";
    persisted.bindingHash = expectedBindingHash(persisted as never);
    await writeFile(statePath, `${stableJson(persisted)}\n`, "utf8");
    const fresh = new ExternalUpdateTransactionOwner(fixture.options);

    await expect(fresh.recoverStartup({ publish: vi.fn() })).resolves.toEqual({
      status: "external_startup_restore_required",
    });
    await expect(fresh.start(fixture.input)).rejects.toMatchObject({
      code: "restore_required",
    });
    await expect(lstat(created.state.transactionRoot)).resolves.toMatchObject(
      {},
    );
    await expect(
      lstat(
        path.join(
          fixture.options.runtimeDir,
          "external-updates",
          "active.json",
        ),
      ),
    ).resolves.toMatchObject({});
  });

  test("does not terminalize a self-consistent terminal state rebound to another transaction", async () => {
    const fixture = await createFixture();
    const failing = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      faultInjector(point) {
        if (point === "after_terminal_state") {
          throw new Error("process loss after terminal state");
        }
      },
    });
    const created = asWorkspace(await failing.start(fixture.input));
    await expect(
      failing.completeTerminal({
        transactionId: created.state.transactionId,
        bindingHash: created.state.bindingHash,
        terminalPayload: abortedPayload(created),
      }),
    ).rejects.toThrow("process loss after terminal state");
    const statePath = path.join(created.state.transactionRoot, "state.json");
    const persisted = JSON.parse(await readFile(statePath, "utf8")) as Record<
      string,
      unknown
    >;
    persisted.transactionId = "external-87654321";
    persisted.bindingHash = expectedBindingHash(persisted as never);
    persisted.terminalPayload = {
      ...(persisted.terminalPayload as Record<string, unknown>),
      transactionId: persisted.transactionId,
      bindingHash: persisted.bindingHash,
    };
    persisted.terminalResultHash = computeExternalTerminalResultHash(
      persisted.terminalPayload as never,
    );
    await writeFile(statePath, `${stableJson(persisted)}\n`, "utf8");
    const terminalIndexPath = path.join(
      fixture.options.runtimeDir,
      "external-updates",
      "terminal-index.json",
    );
    await expect(lstat(terminalIndexPath)).rejects.toMatchObject({
      code: "ENOENT",
    });

    await expect(
      new ExternalUpdateTransactionOwner(fixture.options).recoverStartup({
        publish: vi.fn(),
      }),
    ).resolves.toEqual({ status: "external_startup_restore_required" });
    await expect(lstat(terminalIndexPath)).rejects.toMatchObject({
      code: "ENOENT",
    });
    await expect(lstat(created.state.transactionRoot)).resolves.toMatchObject(
      {},
    );
    await expect(
      lstat(
        path.join(
          fixture.options.runtimeDir,
          "external-updates",
          "active.json",
        ),
      ),
    ).resolves.toMatchObject({});
  });

  test.each([4, 5] as const)(
    "enumerates retained tombstones inside the owner to clean an orphan v%d journal",
    async (version) => {
      const fixture = await createFixture();
      const faultingOwner = new ExternalUpdateTransactionOwner({
        ...fixture.options,
        faultInjector(point) {
          if (point === "after_active_pointer_cleanup") {
            throw new Error("response lost after terminal cleanup");
          }
        },
      });
      const prepared = await prepareMinorReview(faultingOwner, fixture);
      const receipt = reviewReceiptFor(prepared, {
        verdict: "pass",
        issues: [],
      });
      const publisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
      });
      await expect(
        faultingOwner.submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: async (input) => {
            const result = await publisher.publishExternal({
              ...input,
              plan: { ...input.plan, version },
            });
            return { wikiRevision: result.after.rootHash };
          },
        }),
      ).rejects.toThrow("response lost after terminal cleanup");
      const runId = computeExternalPublishRunId({
        bindingHash: prepared.state.bindingHash,
        generation: prepared.state.generation,
        reviewReceiptHash: independentReviewReceiptHash(receipt),
        transactionId: prepared.state.transactionId,
      });
      const publish = vi.fn();

      const recovered = await new ExternalUpdateTransactionOwner(
        fixture.options,
      ).recoverStartup({ publish });

      expect(recovered).toEqual({ status: "external_startup_clean" });
      expect(publish).not.toHaveBeenCalled();
      await expect(
        lstat(path.join(fixture.options.runtimeDir, "recovery", runId)),
      ).rejects.toMatchObject({ code: "ENOENT" });
    },
  );

  test("creates one candidate and replays an identical request without credentials", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);

    const first = asWorkspace(await owner.start(fixture.input));
    const replay = asWorkspace(await owner.start(fixture.input));

    expect(replay).toEqual(first);
    expect(first.state.stage).toBe("candidate_writable");
    expect(first.workPackage.candidate.rootPath).toContain(
      path.join("external-updates", first.state.transactionId),
    );
    expect(JSON.stringify(first)).not.toMatch(/model|provider|credential/iu);
  });

  test("linearizes synchronized identical starts across independent owners", async () => {
    const fixture = await createFixture();
    const barrier = twoPartyBarrier();
    const first = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      createTransactionId: () => "external-owner-one",
      createWorkspaceId: () => "workspace-owner-one",
    });
    const second = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      createTransactionId: () => "external-owner-two",
      createWorkspaceId: () => "workspace-owner-two",
    });

    const [leftResult, rightResult] = await Promise.all([
      barrier().then(() => first.start(fixture.input)),
      barrier().then(() => second.start(fixture.input)),
    ]);
    const left = asWorkspace(leftResult);
    const right = asWorkspace(rightResult);

    expect(right).toEqual(left);
    const entries = await directoryNames(
      path.join(fixture.options.runtimeDir, "external-updates"),
    );
    expect(entries.filter((entry) => entry.startsWith("external-"))).toEqual([
      left.state.transactionId,
    ]);
  });

  test("linearizes synchronized conflicting starts to one winner and busy", async () => {
    const fixture = await createFixture();
    const barrier = twoPartyBarrier();
    const owners = ["one", "two"].map(
      (suffix) =>
        new ExternalUpdateTransactionOwner({
          ...fixture.options,
          createTransactionId: () => `external-owner-${suffix}`,
          createWorkspaceId: () => `workspace-owner-${suffix}`,
        }),
    );

    const results = await Promise.allSettled([
      barrier().then(() => owners[0]!.start(fixture.input)),
      barrier().then(() =>
        owners[1]!.start({
          ...fixture.input,
          requestId: "request-conflicting",
          instruction: "Conflicting request",
        }),
      ),
    ]);

    expect(
      results.filter((result) => result.status === "fulfilled"),
    ).toHaveLength(1);
    expect(results.filter((result) => result.status === "rejected")).toEqual([
      expect.objectContaining({
        reason: expect.objectContaining({ code: "busy" }),
      }),
    ]);
  });

  test("binds the exact ordered request and server-owned package layout", async () => {
    const fixture = await createFixture();
    const workspace = asWorkspace(
      await new ExternalUpdateTransactionOwner(fixture.options).start(
        fixture.input,
      ),
    );

    const requestBytes = await readFile(
      workspace.workPackage.requestPackage.path,
    );
    expect(JSON.parse(requestBytes.toString("utf8"))).toEqual({
      instruction: "Refresh the project overview.",
      materials: [
        {
          byteLength: 8,
          content: "Evidence",
          id: "material-1",
        },
      ],
      version: 1,
    });
    expect(workspace.workPackage).toMatchObject({
      candidate: {
        allowedChangedPaths: ["index.md"],
        permissions: ["read", "list", "write"],
      },
      confirmedWikiPaths: ["index.md"],
      rules: {
        skills: [
          {
            category: "base",
            id: "kg-c7-project-wiki",
            loadOrder: "base_always_first",
          },
        ],
      },
      sources: null,
    });
    expect(await lstat(workspace.workPackage.candidate.rootPath)).toMatchObject(
      {},
    );
  });

  test("freezes exact request whitespace with the canonical package hash", async () => {
    const fixture = await createFixture();
    const instruction = "  Refresh 🚀.\n";
    const content = "\tEvidence 🚀  ";
    const workspace = asWorkspace(
      await new ExternalUpdateTransactionOwner(fixture.options).start({
        ...fixture.input,
        instruction,
        materials: [{ id: "material-🚀", source: "user-🚀", content }],
      }),
    );

    const expectedBytes = Buffer.from(
      '{"instruction":"  Refresh 🚀.\\n","materials":[{"byteLength":16,"content":"\\tEvidence 🚀  ","id":"material-🚀","source":"user-🚀"}],"version":1}\n',
      "utf8",
    );
    expect(await readFile(workspace.workPackage.requestPackage.path)).toEqual(
      expectedBytes,
    );
    expect(workspace.workPackage.requestPackage.packageHash).toBe(
      "sha256:a18990d1167c3cb0053119db5f0f77d35e43f9726556600d9e32c8e55a796f77",
    );
  });

  test("rejects a conflicting request while one candidate is active", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    await owner.start(fixture.input);

    await expect(
      owner.start({ ...fixture.input, instruction: "A conflicting request" }),
    ).rejects.toMatchObject({ code: "busy" });
  });

  test("binds the manifest ID across restarted active replay without resume inference", async () => {
    const fixture = await createFixture();
    const input = await sourceBoundInput(fixture);
    const created = asWorkspace(
      await new ExternalUpdateTransactionOwner(fixture.options).start(input),
    );
    const restarted = new ExternalUpdateTransactionOwner(fixture.options);

    expect(asWorkspace(await restarted.start(input))).toEqual(created);
    await expect(
      restarted.start({ ...input, sourceManifestId: "source-manifest-two" }),
    ).rejects.toMatchObject({ code: "busy" });
    await expect(
      restarted.resume(created.state.transactionId, created.state.bindingHash),
    ).resolves.toMatchObject({
      kind: "candidate_writable",
      state: { transactionId: created.state.transactionId },
    });
  });

  test("rehydrates exact packages and rejects immutable snapshot tamper", async () => {
    const fixture = await createFixture();
    const firstOwner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await firstOwner.start(fixture.input));
    const restarted = await new ExternalUpdateTransactionOwner(
      fixture.options,
    ).resume(created.state.transactionId, created.state.bindingHash);
    expect(restarted).toEqual({ kind: "candidate_writable", ...created });

    await writeFile(created.workPackage.requestPackage.path, "{}\n", "utf8");
    await expect(
      new ExternalUpdateTransactionOwner(fixture.options).readActive(),
    ).rejects.toMatchObject({ code: "restore_required" });
  });

  test.each([
    { label: "unsourced", sourced: false },
    { label: "sourced", sourced: true },
  ])(
    "rejects $label active input-hash tamper on fresh-owner read and resume without deleting evidence",
    async ({ sourced }) => {
      const fixture = await createFixture();
      const input = sourced ? await sourceBoundInput(fixture) : fixture.input;
      const created = asWorkspace(
        await new ExternalUpdateTransactionOwner(fixture.options).start(input),
      );
      const statePath = path.join(created.state.transactionRoot, "state.json");
      const state = JSON.parse(await readFile(statePath, "utf8")) as Record<
        string,
        unknown
      >;
      await writeFile(
        statePath,
        `${JSON.stringify({ ...state, inputHash: hash("f") })}\n`,
        "utf8",
      );

      const freshOwner = new ExternalUpdateTransactionOwner(fixture.options);
      await expect(freshOwner.readActive()).rejects.toMatchObject({
        code: "restore_required",
      });
      await expect(
        freshOwner.resume(
          created.state.transactionId,
          created.state.bindingHash,
        ),
      ).rejects.toMatchObject({ code: "restore_required" });
      await expect(lstat(created.state.transactionRoot)).resolves.toMatchObject(
        {},
      );
      await expect(
        lstat(
          path.join(
            fixture.options.runtimeDir,
            "external-updates",
            "active.json",
          ),
        ),
      ).resolves.toMatchObject({});
    },
  );

  test.each([
    "after_recover_move_after_to_publish",
    "after_recover_restore_before",
  ] as const)(
    "recovers again after process loss at %s in V4 journal reconciliation",
    async (recoveryFault) => {
      const fixture = await createFixture();
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const prepared = await prepareMinorReview(owner, fixture);
      const receipt = reviewReceiptFor(prepared, {
        verdict: "pass",
        issues: [],
      });
      const firstPublisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
        fault(point) {
          if (point === "after_plan") throw new Error("persist crash journal");
        },
      });
      await expect(
        owner.submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: async (input) => {
            const result = await firstPublisher.publishExternal({
              ...input,
              plan: { ...input.plan, version: 4 },
            });
            return { wikiRevision: result.after.rootHash };
          },
        }),
      ).rejects.toMatchObject({ code: "publish_failed" });
      const runId = computeExternalPublishRunId({
        bindingHash: prepared.state.bindingHash,
        generation: prepared.state.generation,
        reviewReceiptHash: independentReviewReceiptHash(receipt),
        transactionId: prepared.state.transactionId,
      });
      const journalPath = path.join(
        fixture.options.runtimeDir,
        "recovery",
        runId,
      );
      await rename(
        fixture.options.formalWikiPath,
        path.join(journalPath, "displaced"),
      );
      await rename(
        path.join(journalPath, "publish"),
        fixture.options.formalWikiPath,
      );
      const recoveryPublisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
        fault(point) {
          if (point === recoveryFault) throw new Error(`fault:${point}`);
        },
      });
      await expect(
        new ExternalUpdateTransactionOwner(
          fixture.options,
        ).recoverPublishPending({
          transactionId: prepared.state.transactionId,
          publish: async (input) => {
            const result = await recoveryPublisher.publishExternal(input);
            return { wikiRevision: result.after.rootHash };
          },
        }),
      ).rejects.toMatchObject({ code: "publish_failed" });

      const finalPublisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
      });
      const recovered = await new ExternalUpdateTransactionOwner(
        fixture.options,
      ).recoverPublishPending({
        transactionId: prepared.state.transactionId,
        publish: async (input) => {
          const result = await finalPublisher.publishExternal(input);
          return { wikiRevision: result.after.rootHash };
        },
      });

      expect(recovered.terminalPayload).toMatchObject({ status: "published" });
      expect(
        (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
      ).toBe(prepared.state.review!.candidateRootHash);
      await expect(lstat(journalPath)).rejects.toMatchObject({
        code: "ENOENT",
      });
    },
  );

  test.each([
    "after_terminal_state",
    "after_tombstone",
    "after_transaction_cleanup",
    "after_active_pointer_cleanup",
  ] as const)(
    "cleans an exact V4 journal after terminal cleanup crashes at %s",
    async (faultPoint) => {
      const fixture = await createFixture();
      const faultingOwner = new ExternalUpdateTransactionOwner({
        ...fixture.options,
        faultInjector(point) {
          if (point === faultPoint) {
            throw new Error("process loss after durable tombstone");
          }
        },
      });
      const prepared = await prepareMinorReview(faultingOwner, fixture);
      const receipt = reviewReceiptFor(prepared, {
        verdict: "pass",
        issues: [],
      });
      const publisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
      });
      await expect(
        faultingOwner.submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: async (input) => {
            const result = await publisher.publishExternal(input);
            return { wikiRevision: result.after.rootHash };
          },
        }),
      ).rejects.toThrow("process loss after durable tombstone");
      const runId = computeExternalPublishRunId({
        bindingHash: prepared.state.bindingHash,
        generation: prepared.state.generation,
        reviewReceiptHash: independentReviewReceiptHash(receipt),
        transactionId: prepared.state.transactionId,
      });
      if (
        faultPoint === "after_terminal_state" ||
        faultPoint === "after_tombstone"
      ) {
        await expect(
          lstat(prepared.state.transactionRoot),
        ).resolves.toMatchObject({});
      } else {
        await expect(
          lstat(prepared.state.transactionRoot),
        ).rejects.toMatchObject({
          code: "ENOENT",
        });
      }
      await expect(
        lstat(path.join(fixture.options.runtimeDir, "recovery", runId)),
      ).resolves.toMatchObject({});

      if (faultPoint === "after_active_pointer_cleanup") {
        const cleanupFaultOwner = new ExternalUpdateTransactionOwner({
          ...fixture.options,
          faultInjector(point) {
            if (point === "after_orphan_journal_quarantine") {
              throw new Error("process loss during orphan journal deletion");
            }
          },
        });
        await expect(
          cleanupFaultOwner.recoverPublishPending({
            transactionId: prepared.state.transactionId,
            publish: vi.fn(),
          }),
        ).rejects.toThrow("process loss during orphan journal deletion");
        await expect(
          lstat(path.join(fixture.options.runtimeDir, "recovery", runId)),
        ).rejects.toMatchObject({ code: "ENOENT" });
        await expect(
          lstat(
            path.join(
              fixture.options.runtimeDir,
              "recovery",
              `${runId}.cleanup`,
            ),
          ),
        ).resolves.toMatchObject({});
        const cleanupPath = path.join(
          fixture.options.runtimeDir,
          "recovery",
          `${runId}.cleanup`,
        );
        await rm(path.join(cleanupPath, "plan.json"));
        await rm(path.join(cleanupPath, "commit.marker"));
        await rm(path.join(cleanupPath, "after"), { recursive: true });
      }

      const replayPublish = vi.fn();
      const recovered = await new ExternalUpdateTransactionOwner(
        fixture.options,
      ).submitAndPublish({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        reviewReceipt: receipt,
        publish: replayPublish,
      });
      expect(replayPublish).not.toHaveBeenCalled();
      if (recovered.kind !== "terminal") throw new Error("expected terminal");

      expect(recovered.terminalPayload).toMatchObject({
        status: "published",
        reviewReceiptHash: independentReviewReceiptHash(receipt),
      });
      if (faultPoint === "after_active_pointer_cleanup") {
        const publish = vi.fn();
        await expect(
          new ExternalUpdateTransactionOwner(fixture.options).submitAndPublish({
            transactionId: prepared.state.transactionId,
            bindingHash: prepared.state.bindingHash,
            reviewReceipt: receipt,
            publish,
          }),
        ).resolves.toEqual(recovered);
        expect(publish).not.toHaveBeenCalled();
      }
      await expect(
        lstat(path.join(fixture.options.runtimeDir, "recovery", runId)),
      ).rejects.toMatchObject({ code: "ENOENT" });
    },
  );

  test("rejects a linked candidate path on restart without exposing it", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const target = `${created.workPackage.candidate.rootPath}-target`;
    await renameDirectory(created.workPackage.candidate.rootPath, target);
    await createDirectoryLink(target, created.workPackage.candidate.rootPath);

    await expect(
      new ExternalUpdateTransactionOwner(fixture.options).readActive(),
    ).rejects.toMatchObject({ code: "restore_required" });
  });

  test("rejects a linked active pointer without consuming its target", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    await owner.start(fixture.input);
    const activePath = path.join(
      fixture.options.runtimeDir,
      "external-updates",
      "active.json",
    );
    const targetPath = path.join(
      fixture.options.runtimeDir,
      "external-updates",
      "active-target.json",
    );
    const { rename, symlink } = await import("node:fs/promises");
    await rename(activePath, targetPath);
    await symlink(targetPath, activePath, "file");

    await expect(owner.readActive()).rejects.toMatchObject({
      code: "restore_required",
    });
    await expect(readFile(targetPath, "utf8")).resolves.toContain(
      "transactionId",
    );
  });

  test("uses one canonical runtime identity through a directory alias", async () => {
    const fixture = await createFixture();
    const directOwner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await directOwner.start(fixture.input));
    const alias = path.join(
      path.dirname(fixture.options.runtimeDir),
      "runtime-alias",
    );
    await createDirectoryLink(fixture.options.runtimeDir, alias);
    const aliasOwner = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      runtimeDir: alias,
    });

    expect(await aliasOwner.readActive()).toMatchObject({
      state: { transactionId: created.state.transactionId },
    });
  });

  test("fails closed when a bound runtime alias is redirected", async () => {
    const fixture = await createFixture();
    await mkdir(fixture.options.runtimeDir, { recursive: true });
    const root = path.dirname(fixture.options.runtimeDir);
    const alias = path.join(root, "runtime-bound-alias");
    await createDirectoryLink(fixture.options.runtimeDir, alias);
    const owner = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      runtimeDir: alias,
    });
    const created = asWorkspace(await owner.start(fixture.input));
    const replacement = path.join(root, "runtime-replacement");
    await mkdir(replacement, { recursive: true });
    await rm(alias, { force: true, recursive: true });
    await createDirectoryLink(replacement, alias);

    await expect(owner.readActive()).rejects.toMatchObject({
      code: "restore_required",
    });
    await expect(
      lstat(
        path.join(
          fixture.options.runtimeDir,
          "external-updates",
          "active.json",
        ),
      ),
    ).resolves.toMatchObject({});
    await expect(lstat(created.state.transactionRoot)).resolves.toMatchObject(
      {},
    );
  });

  test("rejects a linked transaction root without exposing a workspace", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const target = `${created.state.transactionRoot}-target`;
    await renameDirectory(created.state.transactionRoot, target);
    await createDirectoryLink(target, created.state.transactionRoot);

    await expect(
      owner.resume(created.state.transactionId, created.state.bindingHash),
    ).rejects.toMatchObject({ code: "restore_required" });
  });

  test("rejects links introduced anywhere inside the writable candidate", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const outside = path.join(
      path.dirname(created.workPackage.candidate.rootPath),
      "outside.md",
    );
    await writeFile(outside, "outside\n", "utf8");
    const { symlink } = await import("node:fs/promises");
    await symlink(
      outside,
      path.join(created.workPackage.candidate.rootPath, "linked.md"),
      "file",
    );

    await expect(
      new ExternalUpdateTransactionOwner(fixture.options).readActive(),
    ).rejects.toMatchObject({ code: "restore_required" });
  });

  test("resumes the same writable package and never creates a new generation", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));

    const resumed = await new ExternalUpdateTransactionOwner(
      fixture.options,
    ).resume(created.state.transactionId, created.state.bindingHash);

    expect(resumed).toEqual({
      kind: "candidate_writable",
      state: created.state,
      stateVersion: created.stateVersion,
      workPackage: created.workPackage,
    });
  });

  test("returns only the exact persisted read-only Review package for review-ready", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const reviewPackage = {
      version: 1,
      transactionId: created.state.transactionId,
      generation: 1,
      bindingHash: created.state.bindingHash,
    };
    const reviewPath = path.join(
      created.state.transactionRoot,
      "review-package.json",
    );
    const reviewBytes = Buffer.from(`${stableJson(reviewPackage)}\n`, "utf8");
    await writeFile(reviewPath, reviewBytes);
    const reviewHash = domainHash(
      "kg-c7:external-review-package:v1",
      reviewBytes,
    );
    const transitioned = await transitionExternalUpdateState({
      statePath: path.join(created.state.transactionRoot, "state.json"),
      expectedVersion: created.stateVersion,
      next: {
        stage: "review_ready",
        review: {
          candidateRootHash: await candidateRootHash(
            created.workPackage.candidate.rootPath,
          ),
          candidateReceiptHash: domainHash(
            "kg-c7:external-candidate-receipt:v1",
            Buffer.from("receipt", "utf8"),
          ),
          reviewPackageHash: reviewHash,
          reviewPackagePath: reviewPath,
        },
      },
      now: new Date("2026-08-12T00:01:00.000Z"),
      security: fixture.options.security,
    });

    const resumed = await new ExternalUpdateTransactionOwner(
      fixture.options,
    ).resume(created.state.transactionId, created.state.bindingHash);
    expect(resumed).toEqual({
      kind: "review_ready",
      state: transitioned.state,
      stateVersion: transitioned.version,
      reviewPackage,
      reviewPackageHash: reviewHash,
    });
    expect(JSON.stringify(resumed)).not.toContain(
      '"permissions":["read","list","write"]',
    );
  });

  test("records at most sixteen sanitized failures without changing semantic state", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    for (let index = 0; index < 18; index += 1) {
      await owner.recordHostFailure({
        transactionId: created.state.transactionId,
        bindingHash: created.state.bindingHash,
        phase: "candidate_writer",
        code: "host_timeout",
        message: `secret failure ${index}`,
        retryable: true,
      });
    }
    const active = await owner.readActive();
    expect(active?.state).toMatchObject({
      stage: "candidate_writable",
      failures: expect.arrayContaining([
        expect.not.objectContaining({ message: expect.anything() }),
      ]),
      failureOverflowCount: 2,
    });
    expect(active?.state.failures).toHaveLength(16);
    expect(JSON.stringify(active?.state)).not.toContain("secret failure");
  });

  test("creates exactly one fresh repair generation and replays that successor", async () => {
    const fixture = await createFixture();
    const wikiRoot = await realpath(fixture.options.formalWikiPath);
    const runtimeRoot = `${wikiRoot}.selfopenwiki`;
    const owner = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      runtimeDir: runtimeRoot,
      createWorkspaceId: vi
        .fn()
        .mockReturnValueOnce("workspace-12345678")
        .mockReturnValueOnce("workspace-22222222"),
      now: vi
        .fn()
        .mockReturnValueOnce(new Date("2026-08-12T00:00:00.000Z"))
        .mockReturnValue(new Date("2026-08-12T00:03:00.000Z")),
    });
    const runInput = {
      mode: "update" as const,
      force: true,
      requestedSkills: [],
      skillIds: ["self-openwiki"],
      skillAggregateHash: hash("b"),
      wikiRevision: fixture.input.expectedWikiRevision,
      wikiRoot,
      runtimeRoot,
    };
    const runOptions = {
      runtimeRoot,
      isRunAborted: (run: PersonalRunState) =>
        owner.isRequestAborted(
          run.runId,
          run.candidate === undefined
            ? undefined
            : {
                transactionId: run.candidate.transactionId,
                bindingHash: run.candidate.candidateBindingHash,
                generation: run.candidate.generation,
              },
        ),
    };
    const runStore = new FilePersonalRunStore(runOptions);
    const begun = await runStore.begin(runInput);
    if (begun.status !== "planning") throw new Error("expected Run");
    const created = asWorkspace(
      await owner.start({ ...fixture.input, requestId: begun.runId }),
    );
    await runStore.attachCandidate(begun.runId, {
      transactionId: created.state.transactionId,
      generation: 1,
      candidateBindingHash: created.state.bindingHash,
      candidateRoot: created.state.candidateRoot,
      candidateRootHash: hash("d"),
      wikiRevision: fixture.input.expectedWikiRevision,
    });
    const reviewPackage = {
      version: 1,
      transactionId: created.state.transactionId,
    };
    const reviewPath = path.join(
      created.state.transactionRoot,
      "review-package.json",
    );
    const reviewBytes = Buffer.from(`${stableJson(reviewPackage)}\n`, "utf8");
    await writeFile(reviewPath, reviewBytes);
    const reviewReady = await transitionExternalUpdateState({
      statePath: path.join(created.state.transactionRoot, "state.json"),
      expectedVersion: created.stateVersion,
      next: {
        stage: "review_ready",
        review: {
          candidateRootHash: await candidateRootHash(
            created.state.candidateRoot,
          ),
          candidateReceiptHash: domainHash(
            "kg-c7:external-candidate-receipt:v1",
            Buffer.from("receipt"),
          ),
          reviewPackageHash: domainHash(
            "kg-c7:external-review-package:v1",
            reviewBytes,
          ),
          reviewPackagePath: reviewPath,
        },
      },
      now: new Date("2026-08-12T00:01:00.000Z"),
      security: fixture.options.security,
    });
    const repairReady = await transitionExternalUpdateState({
      statePath: path.join(created.state.transactionRoot, "state.json"),
      expectedVersion: reviewReady.version,
      next: { stage: "repair_ready" },
      now: new Date("2026-08-12T00:02:00.000Z"),
      security: fixture.options.security,
    });

    const successor = await owner.resume(
      created.state.transactionId,
      repairReady.state.bindingHash,
    );
    expect(successor).toMatchObject({
      kind: "candidate_writable",
      state: {
        generation: 2,
        workspaceId: "workspace-22222222",
        stage: "candidate_writable",
      },
    });
    if (successor.kind !== "candidate_writable") throw new Error("unexpected");
    expect(created.state.bindingHash).toBe(expectedBindingHash(created.state));
    expect(successor.state.inputHash).toBe(created.state.inputHash);
    expect(successor.state.bindingHash).toBe(
      expectedBindingHash(successor.state),
    );
    expect(successor.state.bindingHash).not.toBe(created.state.bindingHash);
    expect(
      await owner.resume(
        created.state.transactionId,
        successor.state.bindingHash,
      ),
    ).toEqual(successor);
    // Simulate process loss before the Run can attach the durable successor.
    await owner.completeTerminal({
      transactionId: successor.state.transactionId,
      bindingHash: successor.state.bindingHash,
      terminalPayload: abortedPayload(successor),
    });
    const next = await new FilePersonalRunStore(runOptions).begin(runInput);
    expect(next.status).toBe("planning");
    expect("runId" in next && next.runId).not.toBe(begun.runId);
    expect((await runStore.read(begun.runId)).candidate?.generation).toBe(1);
  });

  test.each(["predecessor", "successor"] as const)(
    "rejects repair %s input-hash tamper without deleting evidence",
    async (stage) => {
      const fixture = await createFixture();
      const owner = new ExternalUpdateTransactionOwner({
        ...fixture.options,
        createWorkspaceId: vi
          .fn()
          .mockReturnValueOnce("workspace-12345678")
          .mockReturnValueOnce("workspace-22222222"),
        now: vi
          .fn()
          .mockReturnValueOnce(new Date("2026-08-12T00:00:00.000Z"))
          .mockReturnValue(new Date("2026-08-12T00:03:00.000Z")),
      });
      const created = asWorkspace(await owner.start(fixture.input));
      const repairReady = await moveToRepairReady(
        created,
        fixture.options.security,
      );
      const current =
        stage === "predecessor"
          ? repairReady
          : await owner
              .resume(
                created.state.transactionId,
                repairReady.state.bindingHash,
              )
              .then((result) => {
                if (result.kind !== "candidate_writable") {
                  throw new Error("expected successor");
                }
                return result;
              });
      await overwriteInputHash(current.state.transactionRoot, hash("f"));

      await expect(
        new ExternalUpdateTransactionOwner(fixture.options).resume(
          current.state.transactionId,
          current.state.bindingHash,
        ),
      ).rejects.toMatchObject({ code: "restore_required" });
      await expect(lstat(current.state.transactionRoot)).resolves.toMatchObject(
        {},
      );
    },
  );

  test("linearizes concurrent repair resumes to one exact successor", async () => {
    const fixture = await createFixture();
    const setupOwner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await setupOwner.start(fixture.input));
    const repairReady = await moveToRepairReady(
      created,
      fixture.options.security,
    );
    const barrier = twoPartyBarrier();
    const owners = ["one", "two"].map(
      (suffix) =>
        new ExternalUpdateTransactionOwner({
          ...fixture.options,
          createWorkspaceId: () => `workspace-repair-${suffix}`,
          now: () => new Date("2026-08-12T00:03:00.000Z"),
        }),
    );

    const [left, right] = await Promise.all([
      barrier().then(() =>
        owners[0]!.resume(
          created.state.transactionId,
          repairReady.state.bindingHash,
        ),
      ),
      barrier().then(() =>
        owners[1]!.resume(
          created.state.transactionId,
          repairReady.state.bindingHash,
        ),
      ),
    ]);

    expect(right).toEqual(left);
    expect(left).toMatchObject({
      kind: "candidate_writable",
      state: { generation: 2 },
    });
  });

  test("fails closed when a committed active directory loses its pointer", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    await rm(
      path.join(fixture.options.runtimeDir, "external-updates", "active.json"),
    );

    const restarted = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      createTransactionId: () => "external-22222222",
    });
    await expect(restarted.start(fixture.input)).rejects.toMatchObject({
      code: "restore_required",
    });
    await expect(
      lstat(
        path.join(
          fixture.options.runtimeDir,
          "external-updates",
          "external-22222222",
        ),
      ),
    ).rejects.toMatchObject({ code: "ENOENT" });
    expect(created.state.candidateRoot).toContain("external-12345678");
  });

  test("aborts durably, removes bulky snapshots, and replays its tombstone", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const terminalPayload = abortedPayload(created);

    const tombstone = await owner.completeTerminal({
      transactionId: created.state.transactionId,
      bindingHash: created.state.bindingHash,
      terminalPayload,
    });

    await expect(lstat(created.state.transactionRoot)).rejects.toMatchObject({
      code: "ENOENT",
    });
    expect(await owner.readActive()).toBeNull();
    expect(
      await owner.resume(
        created.state.transactionId,
        created.state.bindingHash,
      ),
    ).toEqual({ kind: "terminal", terminalPayload });
    expect(tombstone.payload).toEqual(terminalPayload);
  });

  test("hashes the parsed canonical terminal payload with the frozen golden domain", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const payload = abortedPayload(created);

    const tombstone = await owner.completeTerminal({
      transactionId: created.state.transactionId,
      bindingHash: created.state.bindingHash,
      terminalPayload: payload,
    });

    const canonicalText =
      '{"authRequired":false,"bindingHash":"sha256:d94e881128a67b7e388aa325d0a779c874d1d45fb1b16bf6c000eba0a7b63f3e","executionMode":"external_agent","generation":1,"ok":true,"published":false,"recovery":{"action":"none"},"status":"external_update_aborted","transactionId":"external-12345678"}';
    expect(stableJson(payload)).toBe(canonicalText);
    expect("resultHash" in payload).toBe(false);
    expect(tombstone.resultHash).toBe(
      domainHash(
        "kg-c7:external-terminal-result:v1",
        Buffer.from(canonicalText, "utf8"),
      ),
    );
    expect(tombstone.resultHash).toBe(
      "sha256:d08f42784096cfce12013a6ce96c0d6fc37b96b0d315b9605477d2c15aba6195",
    );
  });

  test("rejects nonterminal, extra-hash, and mismatched terminal payloads", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const aborted = abortedPayload(created);
    const attempts = [
      { ...aborted, status: "needs_clarification" },
      { ...aborted, resultHash: hash("f") },
      { ...aborted, transactionId: "external-mismatch" },
    ];

    for (const terminalPayload of attempts) {
      await expect(
        owner.completeTerminal({
          transactionId: created.state.transactionId,
          bindingHash: created.state.bindingHash,
          terminalPayload,
        }),
      ).rejects.toMatchObject({ code: "transaction_invalid" });
    }
    expect((await owner.readActive())?.state.stage).toBe("candidate_writable");
  });

  test("returns retained terminal payload for exact start replay and rejects input drift", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    const terminalPayload = abortedPayload(created);
    await owner.completeTerminal({
      transactionId: created.state.transactionId,
      bindingHash: created.state.bindingHash,
      terminalPayload,
    });

    expect(await owner.start(fixture.input)).toEqual({
      kind: "terminal",
      terminalPayload,
    });
    await expect(
      owner.start({ ...fixture.input, instruction: "drifted request" }),
    ).rejects.toMatchObject({ code: "transaction_invalid" });
  });

  test("binds the manifest ID across restarted retained terminal replay", async () => {
    const fixture = await createFixture();
    const input = await sourceBoundInput(fixture);
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(input));
    const terminalPayload = abortedPayload(created);
    await owner.completeTerminal({
      transactionId: created.state.transactionId,
      bindingHash: created.state.bindingHash,
      terminalPayload,
    });
    const restarted = new ExternalUpdateTransactionOwner(fixture.options);

    await expect(restarted.start(input)).resolves.toEqual({
      kind: "terminal",
      terminalPayload,
    });
    await expect(
      restarted.start({ ...input, sourceManifestId: "source-manifest-two" }),
    ).rejects.toMatchObject({ code: "transaction_invalid" });
  });

  test("does not retry a callback-owned busy failure", async () => {
    const fixture = await createFixture();
    let callbackCount = 0;
    const callbackError = new C7ConfigError("busy", "callback busy");
    const owner = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      faultInjector(point) {
        if (point === "after_terminal_state") {
          callbackCount += 1;
          throw callbackError;
        }
      },
    });
    const created = asWorkspace(await owner.start(fixture.input));

    await expect(
      owner.completeTerminal({
        transactionId: created.state.transactionId,
        bindingHash: created.state.bindingHash,
        terminalPayload: abortedPayload(created),
      }),
    ).rejects.toBe(callbackError);
    expect(callbackCount).toBe(1);
  });

  for (const point of [
    "after_terminal_state",
    "after_tombstone",
    "after_transaction_cleanup",
    "after_active_pointer_cleanup",
  ] as const) {
    test(`reconciles terminal completion after ${point}`, async () => {
      const fixture = await createFixture();
      const failing = new ExternalUpdateTransactionOwner({
        ...fixture.options,
        faultInjector(observed) {
          if (observed === point) throw new Error(`fault:${point}`);
        },
      });
      const created = asWorkspace(await failing.start(fixture.input));
      const terminalPayload = abortedPayload(created);
      await expect(
        failing.completeTerminal({
          transactionId: created.state.transactionId,
          bindingHash: created.state.bindingHash,
          terminalPayload,
        }),
      ).rejects.toThrow(`fault:${point}`);

      const recovered = new ExternalUpdateTransactionOwner(fixture.options);
      const replayed = await recovered.completeTerminal({
        transactionId: created.state.transactionId,
        bindingHash: created.state.bindingHash,
        terminalPayload,
      });
      expect(replayed.payload).toEqual(terminalPayload);
      expect(await recovered.readActive()).toBeNull();
      await expect(lstat(created.state.transactionRoot)).rejects.toMatchObject({
        code: "ENOENT",
      });
    });
  }

  test("preserves active recovery evidence when a tombstoned state is corrupt", async () => {
    const fixture = await createFixture();
    const failing = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      faultInjector(point) {
        if (point === "after_tombstone") throw new Error("fault:tombstone");
      },
    });
    const created = asWorkspace(await failing.start(fixture.input));
    const terminalPayload = abortedPayload(created);
    await expect(
      failing.completeTerminal({
        transactionId: created.state.transactionId,
        bindingHash: created.state.bindingHash,
        terminalPayload,
      }),
    ).rejects.toThrow("fault:tombstone");
    const statePath = path.join(created.state.transactionRoot, "state.json");
    await writeFile(statePath, "{corrupt", "utf8");

    await expect(
      new ExternalUpdateTransactionOwner(fixture.options).resume(
        created.state.transactionId,
        created.state.bindingHash,
      ),
    ).rejects.toMatchObject({ code: "restore_required" });
    await expect(lstat(created.state.transactionRoot)).resolves.toMatchObject(
      {},
    );
    await expect(
      lstat(
        path.join(
          fixture.options.runtimeDir,
          "external-updates",
          "active.json",
        ),
      ),
    ).resolves.toMatchObject({});
  });

  test("preserves active recovery evidence when only tombstoned state.json is missing", async () => {
    const fixture = await createFixture();
    const failing = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      faultInjector(point) {
        if (point === "after_tombstone") throw new Error("fault:tombstone");
      },
    });
    const created = asWorkspace(await failing.start(fixture.input));
    await expect(
      failing.completeTerminal({
        transactionId: created.state.transactionId,
        bindingHash: created.state.bindingHash,
        terminalPayload: abortedPayload(created),
      }),
    ).rejects.toThrow("fault:tombstone");
    await rm(path.join(created.state.transactionRoot, "state.json"));

    const restarted = new ExternalUpdateTransactionOwner(fixture.options);
    await expect(
      restarted.resume(created.state.transactionId, created.state.bindingHash),
    ).rejects.toMatchObject({ code: "restore_required" });
    await expect(restarted.start(fixture.input)).rejects.toMatchObject({
      code: "restore_required",
    });
    await expect(lstat(created.state.transactionRoot)).resolves.toMatchObject(
      {},
    );
    await expect(
      lstat(
        path.join(
          fixture.options.runtimeDir,
          "external-updates",
          "active.json",
        ),
      ),
    ).resolves.toMatchObject({});
  });

  test("fails closed when an active pointer has neither state nor matching tombstone", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    await rm(created.state.transactionRoot, { recursive: true });

    await expect(
      new ExternalUpdateTransactionOwner(fixture.options).resume(
        created.state.transactionId,
        created.state.bindingHash,
      ),
    ).rejects.toMatchObject({ code: "restore_required" });
  });

  test("keeps attention active and retains its candidate until explicit abort", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const created = asWorkspace(await owner.start(fixture.input));
    await transitionExternalUpdateState({
      statePath: path.join(created.state.transactionRoot, "state.json"),
      expectedVersion: created.stateVersion,
      next: { stage: "attention" },
      now: new Date("2026-08-12T00:01:00.000Z"),
      security: fixture.options.security,
    });

    expect(
      await owner.resume(
        created.state.transactionId,
        created.state.bindingHash,
      ),
    ).toMatchObject({
      kind: "attention",
    });
    await expect(lstat(created.state.candidateRoot)).resolves.toMatchObject({});
  });

  test("binds a strict external Review receipt and maps minor changes to repair-ready without publishing", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const publish = vi.fn();
    const reviewReceipt = reviewReceiptFor(prepared, {
      verdict: "changes_requested",
      issues: [
        {
          code: "clarify_wording",
          message: "Clarify the wording.",
          severity: "minor",
        },
      ],
    });

    const result = await owner.submitAndPublish({
      transactionId: prepared.state.transactionId,
      bindingHash: prepared.state.bindingHash,
      reviewReceipt,
      publish,
    });

    expect(result).toMatchObject({
      kind: "repair_ready",
      reviewReceiptHash: independentReviewReceiptHash(reviewReceipt),
      state: { stage: "repair_ready" },
    });
    expect(publish).not.toHaveBeenCalled();
    expect(await readFile(reviewReceiptPath(prepared.state), "utf8")).toBe(
      `${stableJson(reviewReceipt)}\n`,
    );
    expect(
      (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
    ).toBe(prepared.state.beforeWikiRevision);
  });

  test("rejects the same writer and Reviewer execution identity before changing state", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const reviewReceipt = reviewReceiptFor(prepared, {
      reviewerExecutionId: "writer-execution-12345678",
      verdict: "pass",
      issues: [],
    });

    await expect(
      owner.submitAndPublish({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        reviewReceipt,
        publish: vi.fn(),
      }),
    ).rejects.toMatchObject({ code: "transaction_invalid" });
    expect((await owner.readActive())?.state.stage).toBe("review_ready");
    await expect(
      lstat(reviewReceiptPath(prepared.state)),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });

  test("freezes the external Review receipt canonical hash domain without a self hash", async () => {
    const receipt = {
      type: "external_review_receipt" as const,
      version: 1 as const,
      transactionId: "external-12345678",
      generation: 1,
      bindingHash: hash("a"),
      reviewPackageHash: hash("b"),
      candidateRootHash: hash("c"),
      candidateReceiptHash: hash("d"),
      reviewerExecutionId: "reviewer-execution-12345678",
      verdict: "pass" as const,
      issues: [],
    };
    const bytes = Buffer.from(`${stableJson(receipt)}\n`, "utf8");

    expect(Object.hasOwn(receipt, "reviewReceiptHash")).toBe(false);
    expect(bytes.toString("utf8")).toBe(
      '{"bindingHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","candidateReceiptHash":"sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","candidateRootHash":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","generation":1,"issues":[],"reviewPackageHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","reviewerExecutionId":"reviewer-execution-12345678","transactionId":"external-12345678","type":"external_review_receipt","verdict":"pass","version":1}\n',
    );
    expect(independentReviewReceiptHash(receipt)).toBe(
      "sha256:f28074bf050cf4e5388f0a6c7e5ec735dfc10a96e92999abe53c40870e1768ed",
    );
    expect(domainHash("kg-c7:external-review-receipt:v2", bytes)).not.toBe(
      independentReviewReceiptHash(receipt),
    );
  });

  test.each([
    ["generation", 2],
    ["reviewPackageHash", hash("1")],
    ["candidateRootHash", hash("2")],
    ["candidateReceiptHash", hash("3")],
  ] as const)(
    "rejects Review receipt %s drift without persisting an artifact or changing formal Wiki",
    async (field, value) => {
      const fixture = await createFixture();
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const prepared = await prepareMinorReview(owner, fixture);
      const receipt = {
        ...reviewReceiptFor(prepared, { verdict: "pass", issues: [] }),
        [field]: value,
      };

      await expect(
        owner.submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: vi.fn(),
        }),
      ).rejects.toMatchObject({ code: "transaction_invalid" });
      expect((await owner.readActive())?.state.stage).toBe("review_ready");
      await expect(
        lstat(reviewReceiptPath(prepared.state)),
      ).rejects.toMatchObject({ code: "ENOENT" });
      expect(
        (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
      ).toBe(prepared.state.beforeWikiRevision);
    },
  );

  test("rejects accessor and Proxy Review receipts without executing user code", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    let observations = 0;
    const accessor = Object.defineProperty({}, "type", {
      enumerable: true,
      get() {
        observations += 1;
        return "external_review_receipt";
      },
    });
    const proxy = new Proxy(
      {},
      {
        ownKeys() {
          observations += 1;
          return [];
        },
      },
    );

    for (const reviewReceipt of [accessor, proxy]) {
      await expect(
        owner.submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt,
          publish: vi.fn(),
        }),
      ).rejects.toMatchObject({ code: "transaction_invalid" });
    }
    expect(observations).toBe(0);
  });

  test("replays one exact Review receipt and rejects a conflicting receipt", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, {
      verdict: "changes_requested",
      issues: [{ code: "repair", message: "Repair it.", severity: "minor" }],
    });
    const input = {
      transactionId: prepared.state.transactionId,
      bindingHash: prepared.state.bindingHash,
      reviewReceipt: receipt,
      publish: vi.fn(),
    };

    const first = await owner.submitAndPublish(input);
    expect(await owner.submitAndPublish(input)).toEqual(first);
    await expect(
      owner.submitAndPublish({
        ...input,
        reviewReceipt: {
          ...receipt,
          issues: [
            { code: "other", message: "Other repair.", severity: "minor" },
          ],
        },
      }),
    ).rejects.toMatchObject({ code: "transaction_invalid" });
  });

  test.each([
    "before_review_receipt",
    "after_review_receipt",
    "before_review_cas",
    "after_review_cas",
  ] as const)("replays safely after %s", async (faultPoint) => {
    const fixture = await createFixture();
    let armed = false;
    const faulting = new ExternalUpdateTransactionOwner({
      ...fixture.options,
      faultInjector(point) {
        if (armed && point === faultPoint) throw new Error(`fault:${point}`);
      },
    });
    const prepared = await prepareMinorReview(faulting, fixture);
    armed = true;
    const receipt = reviewReceiptFor(prepared, {
      verdict: "changes_requested",
      issues: [{ code: "repair", message: "Repair it.", severity: "minor" }],
    });
    const input = {
      transactionId: prepared.state.transactionId,
      bindingHash: prepared.state.bindingHash,
      reviewReceipt: receipt,
      publish: vi.fn(),
    };

    await expect(faulting.submitAndPublish(input)).rejects.toThrow(
      `fault:${faultPoint}`,
    );
    const replay = await new ExternalUpdateTransactionOwner(
      fixture.options,
    ).submitAndPublish(input);
    expect(replay).toMatchObject({
      kind: "repair_ready",
      reviewReceiptHash: independentReviewReceiptHash(receipt),
      state: { stage: "repair_ready" },
    });
    expect(
      (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
    ).toBe(prepared.state.beforeWikiRevision);
  });

  test("keeps operation and Wiki locks through publish callback and terminal completion", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, { verdict: "pass", issues: [] });
    let releasePublish!: () => void;
    const publishReleased = new Promise<void>((resolve) => {
      releasePublish = resolve;
    });
    let publishEntered!: () => void;
    const entered = new Promise<void>((resolve) => {
      publishEntered = resolve;
    });
    const publish = vi.fn(
      async (input: {
        after: { rootHash: string };
        plan: Record<string, unknown>;
      }) => {
        expect(input.plan).toMatchObject({
          version: 5,
          executionMode: "external_agent",
          transactionId: prepared.state.transactionId,
          reviewReceiptHash: independentReviewReceiptHash(receipt),
          reviewCompletedBeforePublish: true,
        });
        expect(JSON.stringify(input.plan)).not.toMatch(
          /model|reviewPending|reviewInstruction/iu,
        );
        publishEntered();
        await publishReleased;
        return { wikiRevision: input.after.rootHash };
      },
    );
    const submitting = owner.submitAndPublish({
      transactionId: prepared.state.transactionId,
      bindingHash: prepared.state.bindingHash,
      reviewReceipt: receipt,
      publish,
    });
    await Promise.race([
      entered,
      submitting.then(() => {
        throw new Error("submission completed before the publisher callback");
      }),
    ]);
    await expect(
      withC7Locks(
        fixture.options.runtimeDir,
        ["operation", "wiki"],
        async () => "entered",
      ),
    ).rejects.toMatchObject({ code: "busy" });
    releasePublish();

    const result = await submitting;
    expect(result).toMatchObject({
      kind: "terminal",
      terminalPayload: {
        status: "published",
        reviewEvidence: "host_attested",
        reviewReceiptHash: independentReviewReceiptHash(receipt),
      },
    });
    await expect(
      withC7Locks(
        fixture.options.runtimeDir,
        ["operation", "wiki"],
        async () => "entered",
      ),
    ).resolves.toBe("entered");
    expect(publish).toHaveBeenCalledTimes(1);
    await expect(lstat(prepared.state.transactionRoot)).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  test("retains publish-pending state and exact receipt when the callback fails", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, { verdict: "pass", issues: [] });
    const publish = vi
      .fn()
      .mockRejectedValue(new Error("publisher unavailable"));

    await expect(
      owner.submitAndPublish({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        reviewReceipt: receipt,
        publish,
      }),
    ).rejects.toThrow("publisher unavailable");
    expect(publish).toHaveBeenCalledTimes(1);
    expect((await owner.readActive())?.state.stage).toBe("publish_pending");
    expect(await readFile(reviewReceiptPath(prepared.state), "utf8")).toBe(
      `${stableJson(receipt)}\n`,
    );
    expect(
      (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
    ).toBe(prepared.state.beforeWikiRevision);

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
          const result = await publisher.publishExternal(input);
          return { wikiRevision: result.after.rootHash };
        },
      }),
    ).resolves.toMatchObject({
      kind: "terminal",
      terminalPayload: { status: "published" },
    });
  });

  test("aborts a confirmed publish-pending conflict without changing the formal Wiki", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, { verdict: "pass", issues: [] });
    const publisher = new WikiPublisher({
      formalWikiPath: fixture.options.formalWikiPath,
      runtimeDir: fixture.options.runtimeDir,
      security: fixture.options.security,
      fault(point) {
        if (point === "after_plan") throw new Error("publisher unavailable");
      },
    });

    await expect(
      owner.submitAndPublish({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        reviewReceipt: receipt,
        publish: async (input) => {
          const result = await publisher.publishExternal(input);
          return { wikiRevision: result.after.rootHash };
        },
      }),
    ).rejects.toMatchObject({ code: "publish_failed" });
    expect((await owner.readActive())?.state.stage).toBe("publish_pending");

    await writeFile(
      path.join(fixture.options.formalWikiPath, "index.md"),
      "---\ntype: Guide\n---\n\n# Independently changed\n",
      "utf8",
    );
    const formalBeforeAbort = await snapshotMarkdownTree(
      fixture.options.formalWikiPath,
    );

    const aborted = await owner.completeTerminal({
      transactionId: prepared.state.transactionId,
      bindingHash: prepared.state.bindingHash,
      terminalPayload: abortedPayload(prepared),
    });

    expect(aborted).toMatchObject({
      status: "external_update_aborted",
      finalWikiRevision: formalBeforeAbort.rootHash,
      payload: { status: "external_update_aborted" },
    });
    await expect(owner.readActive()).resolves.toBeNull();
    await expect(lstat(prepared.state.transactionRoot)).rejects.toMatchObject({
      code: "ENOENT",
    });
    await expect(
      snapshotMarkdownTree(fixture.options.formalWikiPath),
    ).resolves.toEqual(formalBeforeAbort);

    const runId = computeExternalPublishRunId({
      bindingHash: prepared.state.bindingHash,
      generation: prepared.state.generation,
      reviewReceiptHash: independentReviewReceiptHash(receipt),
      transactionId: prepared.state.transactionId,
    });
    await expect(
      lstat(path.join(fixture.options.runtimeDir, "recovery", runId)),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });

  test("keeps a publish-pending transaction when the formal Wiki already equals the candidate", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, { verdict: "pass", issues: [] });
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
          const result = await publisher.publishExternal(input);
          throw new Error(`memory loss after ${result.after.rootHash}`);
        },
      }),
    ).rejects.toThrow("memory loss after");

    await expect(
      owner.completeTerminal({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        terminalPayload: abortedPayload(prepared),
      }),
    ).rejects.toMatchObject({ code: "restore_required" });
    expect((await owner.readActive())?.state.stage).toBe("publish_pending");
    await expect(lstat(prepared.state.transactionRoot)).resolves.toMatchObject(
      {},
    );
  });

  test("keeps a publish-pending transaction when its Review receipt is damaged", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, { verdict: "pass", issues: [] });
    const publish = vi
      .fn()
      .mockRejectedValue(new Error("publisher unavailable"));

    await expect(
      owner.submitAndPublish({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        reviewReceipt: receipt,
        publish,
      }),
    ).rejects.toThrow("publisher unavailable");
    await rm(reviewReceiptPath(prepared.state));
    await writeFile(
      path.join(fixture.options.formalWikiPath, "index.md"),
      "---\ntype: Guide\n---\n\n# Independently changed\n",
      "utf8",
    );

    await expect(
      owner.completeTerminal({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        terminalPayload: abortedPayload(prepared),
      }),
    ).rejects.toMatchObject({ code: "restore_required" });
    expect((await owner.readActive())?.state.stage).toBe("publish_pending");
  });

  test("recovers a marker-after external publication from fixed receipts without a Reviewer", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, { verdict: "pass", issues: [] });
    const publisher = new WikiPublisher({
      formalWikiPath: fixture.options.formalWikiPath,
      runtimeDir: fixture.options.runtimeDir,
      security: fixture.options.security,
    });
    const publishThenLoseMemory = async (
      input: Parameters<WikiPublisher["publishExternal"]>[0],
    ) => {
      await publisher.publishExternal(input);
      throw new Error("simulated process loss after marker");
    };

    await expect(
      owner.submitAndPublish({
        transactionId: prepared.state.transactionId,
        bindingHash: prepared.state.bindingHash,
        reviewReceipt: receipt,
        publish: publishThenLoseMemory,
      }),
    ).rejects.toThrow("simulated process loss after marker");
    expect((await owner.readActive())?.state.stage).toBe("publish_pending");

    const recovered = await new ExternalUpdateTransactionOwner(
      fixture.options,
    ).recoverPublishPending({
      transactionId: prepared.state.transactionId,
      publish: async (input) => {
        const result = await publisher.publishExternal(input);
        return { wikiRevision: result.after.rootHash };
      },
    });

    expect(recovered).toMatchObject({
      kind: "terminal",
      terminalPayload: {
        status: "published",
        reviewEvidence: "host_attested",
        reviewReceiptHash: independentReviewReceiptHash(receipt),
      },
    });
    expect(
      await owner.start({
        ...fixture.input,
        expectedWikiRevision: prepared.state.beforeWikiRevision,
      }),
    ).toMatchObject({ kind: "terminal" });
    await expect(lstat(prepared.state.transactionRoot)).rejects.toMatchObject({
      code: "ENOENT",
    });
    const runId = computeExternalPublishRunId({
      bindingHash: prepared.state.bindingHash,
      generation: prepared.state.generation,
      reviewReceiptHash: independentReviewReceiptHash(receipt),
      transactionId: prepared.state.transactionId,
    });
    await expect(
      lstat(path.join(fixture.options.runtimeDir, "recovery", runId)),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });

  test.each([
    "after_displace",
    "after_install",
    "before_marker_rename",
  ] as const)(
    "reconciles a persisted %s external crash before retrying the same run",
    async (crashPoint) => {
      const fixture = await createFixture();
      const owner = new ExternalUpdateTransactionOwner(fixture.options);
      const prepared = await prepareMinorReview(owner, fixture);
      const receipt = reviewReceiptFor(prepared, {
        verdict: "pass",
        issues: [],
      });
      const crashingPublisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
        fault(point) {
          if (point === "after_plan") throw new Error("persist crash journal");
        },
      });
      await expect(
        owner.submitAndPublish({
          transactionId: prepared.state.transactionId,
          bindingHash: prepared.state.bindingHash,
          reviewReceipt: receipt,
          publish: async (input) => {
            const result = await crashingPublisher.publishExternal({
              ...input,
              plan: { ...input.plan, version: 4 },
            });
            return { wikiRevision: result.after.rootHash };
          },
        }),
      ).rejects.toMatchObject({ code: "publish_failed" });
      const runId = computeExternalPublishRunId({
        bindingHash: prepared.state.bindingHash,
        generation: prepared.state.generation,
        reviewReceiptHash: independentReviewReceiptHash(receipt),
        transactionId: prepared.state.transactionId,
      });
      const journalPath = path.join(
        fixture.options.runtimeDir,
        "recovery",
        runId,
      );
      const displacedPath = path.join(journalPath, "displaced");
      const publishPath = path.join(journalPath, "publish");
      await rename(fixture.options.formalWikiPath, displacedPath);
      if (crashPoint !== "after_displace") {
        await rename(publishPath, fixture.options.formalWikiPath);
      }

      const publisher = new WikiPublisher({
        formalWikiPath: fixture.options.formalWikiPath,
        runtimeDir: fixture.options.runtimeDir,
        security: fixture.options.security,
      });
      const recovered = await new ExternalUpdateTransactionOwner(
        fixture.options,
      ).recoverPublishPending({
        transactionId: prepared.state.transactionId,
        publish: async (input) => {
          const result = await publisher.publishExternal(input);
          return { wikiRevision: result.after.rootHash };
        },
      });

      expect(recovered.terminalPayload).toMatchObject({ status: "published" });
      expect(
        (await snapshotMarkdownTree(fixture.options.formalWikiPath)).rootHash,
      ).toBe(prepared.state.review!.candidateRootHash);
      await expect(lstat(journalPath)).rejects.toMatchObject({
        code: "ENOENT",
      });
    },
  );

  test("fails closed when marker-after recovery loses its fixed Review receipt", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareMinorReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, { verdict: "pass", issues: [] });
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
          throw new Error("memory loss");
        },
      }),
    ).rejects.toThrow("memory loss");
    await rm(reviewReceiptPath(prepared.state));

    await expect(
      new ExternalUpdateTransactionOwner(fixture.options).recoverPublishPending(
        {
          transactionId: prepared.state.transactionId,
          publish: async (input) => {
            const result = await publisher.publishExternal(input);
            return { wikiRevision: result.after.rootHash };
          },
        },
      ),
    ).rejects.toMatchObject({ code: "restore_required" });
    expect((await owner.readActive())?.state.stage).toBe("publish_pending");
    await expect(lstat(prepared.state.transactionRoot)).resolves.toMatchObject(
      {},
    );
  });

  test("rebuilds the exact ordered provisional follow-up from the frozen candidate receipt", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareProvisionalReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, { verdict: "pass", issues: [] });
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
          throw new Error("memory loss");
        },
      }),
    ).rejects.toThrow("memory loss");

    const recovered = await new ExternalUpdateTransactionOwner(
      fixture.options,
    ).recoverPublishPending({
      transactionId: prepared.state.transactionId,
      publish: async (input) => {
        const result = await publisher.publishExternal(input);
        return { wikiRevision: result.after.rootHash };
      },
    });

    expect(recovered.terminalPayload).toMatchObject({
      status: "published_with_follow_up",
      followUp: prepared.candidateReceipt.issues,
      reviewEvidence: "host_attested",
    });
  });

  test("publishes a provisional candidate when follow-up Review has provisional and minor issues", async () => {
    const fixture = await createFixture();
    const owner = new ExternalUpdateTransactionOwner(fixture.options);
    const prepared = await prepareProvisionalReview(owner, fixture);
    const receipt = reviewReceiptFor(prepared, {
      verdict: "follow_up",
      issues: [
        {
          code: "verify_claim",
          message: "Verify the provisional claim.",
          severity: "provisional",
        },
        {
          code: "wording",
          message: "Polish wording later.",
          severity: "minor",
        },
      ],
    });
    const publish = vi.fn(async (input: { after: { rootHash: string } }) => ({
      wikiRevision: input.after.rootHash,
    }));

    const result = await owner.submitAndPublish({
      transactionId: prepared.state.transactionId,
      bindingHash: prepared.state.bindingHash,
      reviewReceipt: receipt,
      publish,
    });

    expect(result).toMatchObject({
      kind: "terminal",
      terminalPayload: {
        status: "published_with_follow_up",
        followUp: prepared.candidateReceipt.issues,
      },
    });
    expect(publish).toHaveBeenCalledTimes(1);
  });
});

async function createFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-external-owner-"));
  roots.push(root);
  const runtimeDir = path.join(root, "runtime");
  const formalWikiPath = path.join(runtimeDir, "wiki");
  await mkdir(formalWikiPath, { recursive: true });
  await writeFile(path.join(formalWikiPath, "index.md"), "# Home\n", "utf8");
  const before = await snapshotMarkdownTree(formalWikiPath);
  const bytes = Buffer.from("# Base Skill\n", "utf8");
  const file = {
    relativePath: "SKILL.md",
    bytes,
    size: bytes.byteLength,
    hash: `sha256:${(await import("node:crypto")).createHash("sha256").update(bytes).digest("hex")}`,
  };
  const baseSkill = {
    id: "kg-c7-project-wiki",
    category: "base" as const,
    loadOrder: "base_always_first" as const,
    packageHash: computeSkillPackageHash([file]),
    verified: true,
    description: "base",
    title: "base",
    files: [file],
  };
  return {
    options: {
      runtimeDir,
      formalWikiPath,
      security: { securePrivatePath: vi.fn().mockResolvedValue(undefined) },
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

async function sourceBoundInput(
  fixture: Awaited<ReturnType<typeof createFixture>>,
) {
  const snapshotPath = path.join(
    path.dirname(fixture.options.runtimeDir),
    "source-snapshot",
  );
  await mkdir(snapshotPath, { recursive: true });
  await writeFile(
    path.join(snapshotPath, "evidence.md"),
    "# Evidence\n",
    "utf8",
  );
  return {
    ...fixture.input,
    sourceManifestId: "source-manifest-one",
    sourceSnapshot: {
      manifestHash: hash("c"),
      snapshotPath,
      snapshotTreeHash: await hashSourceSnapshotTree(snapshotPath),
    },
  };
}

async function renameDirectory(from: string, to: string): Promise<void> {
  const { rename } = await import("node:fs/promises");
  await rename(from, to);
}

async function createDirectoryLink(
  target: string,
  linkPath: string,
): Promise<void> {
  const { symlink } = await import("node:fs/promises");
  await symlink(
    target,
    linkPath,
    process.platform === "win32" ? "junction" : "dir",
  );
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

function domainHash(domain: string, bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(`${domain}\0`, "utf8").update(bytes).digest("hex")}`;
}

async function candidateRootHash(root: string): Promise<string> {
  return (await snapshotMarkdownTree(root)).rootHash;
}

function asWorkspace(
  result: Awaited<ReturnType<ExternalUpdateTransactionOwner["start"]>>,
) {
  if ("kind" in result) throw new Error("expected active workspace");
  return result;
}

function abortedPayload(created: {
  state: {
    transactionId: string;
    generation: number;
    bindingHash: string;
  };
}) {
  return {
    ok: true as const,
    executionMode: "external_agent" as const,
    authRequired: false as const,
    transactionId: created.state.transactionId,
    generation: created.state.generation,
    bindingHash: created.state.bindingHash,
    recovery: { action: "none" as const },
    status: "external_update_aborted" as const,
    published: false as const,
  };
}

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}

async function prepareMinorReview(
  owner: ExternalUpdateTransactionOwner,
  fixture: Awaited<ReturnType<typeof createFixture>>,
  twoPages = false,
) {
  await writeFile(
    path.join(fixture.options.formalWikiPath, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n",
    "utf8",
  );
  await writeFile(
    path.join(fixture.options.formalWikiPath, "quickstart.md"),
    "---\ntype: Guide\n---\n\n# Quickstart\n\nSee [home](./index.md).\n",
    "utf8",
  );
  const expectedWikiRevision = (
    await snapshotMarkdownTree(fixture.options.formalWikiPath)
  ).rootHash;
  const created = asWorkspace(
    await owner.start({ ...fixture.input, expectedWikiRevision }),
  );
  await writeFile(
    path.join(created.state.candidateRoot, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n\nUpdated knowledge.\n",
    "utf8",
  );
  if (twoPages)
    await writeFile(
      path.join(created.state.candidateRoot, "quickstart.md"),
      "---\ntype: Guide\n---\n\n# Quickstart updated\n\nSee [home](./index.md).\n",
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

async function prepareProvisionalReview(
  owner: ExternalUpdateTransactionOwner,
  fixture: Awaited<ReturnType<typeof createFixture>>,
) {
  await writeFile(
    path.join(fixture.options.formalWikiPath, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n",
    "utf8",
  );
  await writeFile(
    path.join(fixture.options.formalWikiPath, "quickstart.md"),
    "---\ntype: Guide\n---\n\n# Quickstart\n\nSee [home](./index.md).\n",
    "utf8",
  );
  const expectedWikiRevision = (
    await snapshotMarkdownTree(fixture.options.formalWikiPath)
  ).rootHash;
  const created = asWorkspace(
    await owner.start({ ...fixture.input, expectedWikiRevision }),
  );
  await writeFile(
    path.join(created.state.candidateRoot, "index.md"),
    "---\ntype: Guide\nstatus: provisional\n---\n\n# Home\n",
    "utf8",
  );
  const candidateReceipt = {
    type: "external_candidate_receipt" as const,
    version: 1 as const,
    transactionId: created.state.transactionId,
    generation: created.state.generation,
    bindingHash: created.state.bindingHash,
    writerExecutionId: "writer-execution-12345678",
    classification: "provisional" as const,
    issues: [
      {
        code: "verify_first",
        message: "Verify the first provisional claim.",
        severity: "provisional" as const,
      },
      {
        code: "verify_second",
        message: "Verify the second provisional claim.",
        page: "index.md",
        severity: "provisional" as const,
      },
    ],
    questions: [],
    summary: "Candidate contains explicitly provisional knowledge.",
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
  prepared: {
    state: Awaited<ReturnType<typeof prepareMinorReview>>["state"];
    reviewPackageHash: string;
  },
  overrides: {
    reviewerExecutionId?: string;
    verdict: "pass" | "follow_up" | "changes_requested" | "requires_user";
    issues: readonly {
      code: string;
      message: string;
      page?: string;
      severity: "minor" | "provisional" | "blocking";
    }[];
  },
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
    reviewerExecutionId:
      overrides.reviewerExecutionId ?? "reviewer-execution-12345678",
    verdict: overrides.verdict,
    issues: overrides.issues,
  };
}

function independentReviewReceiptHash(value: unknown): string {
  return domainHash(
    "kg-c7:external-review-receipt:v1",
    Buffer.from(`${stableJson(value)}\n`, "utf8"),
  );
}

function reviewReceiptPath(
  state: ReturnType<typeof asWorkspace>["state"],
): string {
  return path.join(path.dirname(state.candidateRoot), "review-receipt.json");
}

function expectedBindingHash(
  state: ReturnType<typeof asWorkspace>["state"],
): string {
  return domainHash(
    "kg-c7:external-update-binding:v1",
    Buffer.from(
      stableJson({
        version: 1,
        transactionId: state.transactionId,
        generation: state.generation,
        workspaceId: state.workspaceId,
        beforeWikiRevision: state.beforeWikiRevision,
        requestPackageHash: state.requestPackageHash,
        sourceManifestHash: state.sourceManifestHash,
        sourceTreeHash: state.sourceTreeHash,
        skillAggregateHash: state.skillAggregateHash,
        skills: state.skills.map(
          ({ id, category, loadOrder, packageHash }) => ({
            id,
            category,
            loadOrder,
            packageHash,
          }),
        ),
        confirmedWikiPaths: state.confirmedWikiPaths,
        hardRulePackageHash: state.hardRulePackageHash,
        candidateResultContractSchemaHash:
          state.candidateResultContractSchemaHash,
        inputHash: state.inputHash,
      }),
      "utf8",
    ),
  );
}

async function overwriteInputHash(
  transactionRoot: string,
  inputHash: string,
): Promise<void> {
  const statePath = path.join(transactionRoot, "state.json");
  const state = JSON.parse(await readFile(statePath, "utf8")) as Record<
    string,
    unknown
  >;
  await writeFile(
    statePath,
    `${JSON.stringify({ ...state, inputHash })}\n`,
    "utf8",
  );
}

async function moveToRepairReady(
  created: ReturnType<typeof asWorkspace>,
  security: {
    securePrivatePath(input: {
      directory: boolean;
      targetPath: string;
    }): Promise<unknown>;
  },
) {
  const reviewPackage = {
    version: 1,
    transactionId: created.state.transactionId,
  };
  const reviewPath = path.join(
    created.state.transactionRoot,
    "review-package.json",
  );
  const reviewBytes = Buffer.from(`${stableJson(reviewPackage)}\n`, "utf8");
  await writeFile(reviewPath, reviewBytes);
  const reviewReady = await transitionExternalUpdateState({
    statePath: path.join(created.state.transactionRoot, "state.json"),
    expectedVersion: created.stateVersion,
    next: {
      stage: "review_ready",
      review: {
        candidateRootHash: await candidateRootHash(created.state.candidateRoot),
        candidateReceiptHash: domainHash(
          "kg-c7:external-candidate-receipt:v1",
          Buffer.from("receipt"),
        ),
        reviewPackageHash: domainHash(
          "kg-c7:external-review-package:v1",
          reviewBytes,
        ),
        reviewPackagePath: reviewPath,
      },
    },
    now: new Date("2026-08-12T00:01:00.000Z"),
    security,
  });
  return transitionExternalUpdateState({
    statePath: path.join(created.state.transactionRoot, "state.json"),
    expectedVersion: reviewReady.version,
    next: { stage: "repair_ready" },
    now: new Date("2026-08-12T00:02:00.000Z"),
    security,
  });
}

function twoPartyBarrier(): () => Promise<void> {
  let arrivals = 0;
  let release!: () => void;
  const ready = new Promise<void>((resolve) => {
    release = resolve;
  });
  return async () => {
    arrivals += 1;
    if (arrivals === 2) release();
    await ready;
  };
}

async function directoryNames(root: string): Promise<string[]> {
  const { readdir } = await import("node:fs/promises");
  return (await readdir(root, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}
