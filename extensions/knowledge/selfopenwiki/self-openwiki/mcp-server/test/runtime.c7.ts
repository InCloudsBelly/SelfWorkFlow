import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { bootstrapC7Runtime } from "../src/bootstrap.js";
import * as capabilitiesModule from "../src/capabilities.js";
import type { RuntimeCapabilityGate } from "../src/capabilities.js";
import type { RuntimeModelService } from "../src/runtime-model-service.js";
import {
  C7OpenWikiRuntime,
  type C7RuntimeRecoveryState,
} from "../src/runtime.js";
import { C7QueryError } from "../src/query.js";
import { C7PublishError } from "../src/publish.js";
import { toolOutputSchemas } from "../src/contracts.js";
import type { SetupAttemptManager } from "../src/setup-attempt.js";
import { withC7Locks } from "../src/config.js";

const tempDirs: string[] = [];

afterEach(async () => {
  vi.restoreAllMocks();
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("C7 production runtime recovery gates", () => {
  test("blocks reads and readiness for durable publish_pending even when memory is clean", async () => {
    const fixture = await createFixture();
    fixture.setRecoveryState("clean");
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.externalStatus.mockResolvedValue({
      state: "publish_pending",
      nextAction: "restore",
      transactionId: "external-12345678",
      generation: 1,
    });
    await expect(
      fixture.runtime.invoke("openwiki_read", {}),
    ).resolves.toMatchObject({
      ok: false,
      error: { code: "restore_required" },
    });
    await expect(
      fixture.runtime.invoke("openwiki_status", {}),
    ).resolves.toMatchObject({
      ok: true,
      initialized: false,
      externalAgent: { ready: false },
      recovery: { action: "restore" },
      runtime: { recoveryState: "restore_required" },
    });
  });

  test("does not read while another operation holds the publication locks", async () => {
    const fixture = await createFixture();
    let entered!: () => void;
    let release!: () => void;
    const acquired = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    const holding = withC7Locks(
      fixture.runtimeDir,
      ["operation", "wiki"],
      async () => {
        entered();
        await released;
      },
    );
    await acquired;
    try {
      await expect(
        fixture.runtime.invoke("openwiki_read", {}),
      ).resolves.toMatchObject({ ok: false, error: { code: "busy" } });
    } finally {
      release();
      await holding;
    }
    await expect(
      fixture.runtime.invoke("openwiki_read", {}),
    ).resolves.toMatchObject({ ok: true });
  });

  test("reads bound Wiki pages without provider credentials or a transaction", async () => {
    const fixture = await createFixture();
    await rm(fixture.configPath, { force: true });
    await rm(fixture.credentialPath, { force: true });
    await writeFile(
      path.join(fixture.runtimeDir, "wiki", "intro.md"),
      "hello wiki\n",
    );
    const before = await readFile(
      path.join(fixture.runtimeDir, "wiki", "intro.md"),
    );

    const index = toolOutputSchemas.openwiki_read.parse(
      await fixture.runtime.invoke("openwiki_read", {}),
    );
    if (!index.ok) throw new Error("expected Wiki index");
    expect(index.ok).toBe(true);
    expect(index.pages).toContainEqual(
      expect.objectContaining({ path: "intro.md", size: 11 }),
    );
    const result = toolOutputSchemas.openwiki_read.parse(
      await fixture.runtime.invoke("openwiki_read", {
        paths: ["intro.md"],
        expectedWikiRevision: index.revision,
      }),
    );
    if (!result.ok) throw new Error("expected Wiki read");
    expect(result).toEqual(
      expect.objectContaining({
        ok: true,
        status: "wiki_read",
        revision: index.revision,
        knowledge: [
          expect.objectContaining({
            content: "hello wiki\n",
            sourceId: "selfopenwiki:intro.md",
            revision: index.revision,
            verificationStatus: "unverified",
          }),
        ],
      }),
    );
    expect(result.knowledge[0]?.contentHash).toMatch(/^sha256:[a-f0-9]{64}$/u);
    expect(
      await readFile(path.join(fixture.runtimeDir, "wiki", "intro.md")),
    ).toEqual(before);
    expect(fixture.createQuery).not.toHaveBeenCalled();
    expect(fixture.externalBegin).not.toHaveBeenCalled();
  });

  test("rejects a stale Wiki read revision and paths outside formal Markdown", async () => {
    const fixture = await createFixture();
    const index = toolOutputSchemas.openwiki_read.parse(
      await fixture.runtime.invoke("openwiki_read", {}),
    );
    if (!index.ok) throw new Error("expected Wiki index");
    await writeFile(
      path.join(fixture.runtimeDir, "wiki", "changed.md"),
      "new\n",
    );
    await expect(
      fixture.runtime.invoke("openwiki_read", {
        expectedWikiRevision: index.revision,
      }),
    ).resolves.toEqual(
      expect.objectContaining({
        ok: false,
        error: expect.objectContaining({ code: "wiki_changed" }),
      }),
    );
    for (const page of [
      "../outside.md",
      ".git/config",
      ".claims/page.json",
      "C:/private.md",
    ]) {
      await expect(
        fixture.runtime.invoke("openwiki_read", { paths: [page] }),
      ).resolves.toEqual(
        expect.objectContaining({
          ok: false,
          error: expect.objectContaining({ code: "wiki_invalid" }),
        }),
      );
    }
  });

  test("rejects oversized, invalid UTF-8 and linked Wiki read content", async () => {
    const fixture = await createFixture();
    const page = path.join(fixture.runtimeDir, "wiki", "bad.md");
    await writeFile(page, Buffer.alloc(262_145, 65));
    await expect(
      fixture.runtime.invoke("openwiki_read", { paths: ["bad.md"] }),
    ).resolves.toEqual(
      expect.objectContaining({
        ok: false,
        error: expect.objectContaining({ code: "wiki_invalid" }),
      }),
    );
    await writeFile(page, Buffer.from([0xff]));
    await expect(
      fixture.runtime.invoke("openwiki_read", { paths: ["bad.md"] }),
    ).resolves.toEqual(
      expect.objectContaining({
        ok: false,
        error: expect.objectContaining({ code: "wiki_invalid" }),
      }),
    );
    await rm(page);
    const outside = path.join(fixture.runtimeDir, "outside.md");
    await writeFile(outside, "private\n");
    await symlink(outside, page, "file");
    await expect(
      fixture.runtime.invoke("openwiki_read", { paths: ["bad.md"] }),
    ).resolves.toEqual(
      expect.objectContaining({
        ok: false,
        error: expect.objectContaining({ code: "wiki_invalid" }),
      }),
    );
  });

  test("indexes a large page and reads a small page while enforcing selected-body limits", async () => {
    const fixture = await createFixture();
    await writeFile(
      path.join(fixture.runtimeDir, "wiki", "large.md"),
      Buffer.alloc(262_145, 65),
    );
    await writeFile(
      path.join(fixture.runtimeDir, "wiki", "small.md"),
      "small\n",
    );
    const index = toolOutputSchemas.openwiki_read.parse(
      await fixture.runtime.invoke("openwiki_read", {}),
    );
    expect(index.ok).toBe(true);
    if (!index.ok) throw new Error("expected index with large page");
    expect(index.pages).toContainEqual(
      expect.objectContaining({ path: "large.md", size: 262_145 }),
    );
    const result = await fixture.runtime.invoke("openwiki_read", {
      paths: ["small.md"],
      expectedWikiRevision: index.revision,
    });
    expect(result).toMatchObject({
      ok: true,
      knowledge: [{ content: "small\n" }],
    });
    await expect(
      fixture.runtime.invoke("openwiki_read", { paths: ["large.md"] }),
    ).resolves.toMatchObject({ ok: false, error: { code: "wiki_invalid" } });
    expect(fixture.createQuery).not.toHaveBeenCalled();
    expect(fixture.externalBegin).not.toHaveBeenCalled();
  });

  test("reports the validated SelfOpenWiki Viewer launcher in status", async () => {
    const fixture = await createFixture();
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.externalStatus.mockResolvedValueOnce(null);

    await expect(
      fixture.runtime.invoke("openwiki_status", {}),
    ).resolves.toEqual(
      expect.objectContaining({
        visualizer: {
          id: "selfopenwiki.zxh_wiki_viewer",
          contractSchema: 1,
          launcherPath: fixture.visualizerPath,
          loopbackOnly: true,
          autoOpen: false,
          wikiRootInput: { kind: "argument", flag: "--wiki-root" },
          urlTemplate: "http://127.0.0.1:{port}/wiki/local",
        },
      }),
    );
  });

  test("reports truthful external status without legacy config or credentials", async () => {
    const fixture = await createFixture();
    await rm(fixture.configPath, { force: true });
    await rm(fixture.credentialPath, { force: true });
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.externalStatus.mockResolvedValueOnce(null);

    await expect(
      fixture.runtime.invoke("openwiki_status", {}),
    ).resolves.toEqual(
      expect.objectContaining({
        authRequired: false,
        authentication: { status: "not_required" },
        defaultModel: null,
        executionMode: "external_agent",
        externalAgent: { activeTransaction: null, ready: true },
        initialized: true,
        legacyProvider: {
          authRequired: true,
          authentication: { status: "not_configured" },
          available: true,
          defaultModel: null,
          initialized: false,
          verifiedModels: [],
        },
        verifiedModels: [],
        version: expect.objectContaining({ contractSchema: 2 }),
      }),
    );
  });

  test("nests invalid legacy evidence without changing external authentication", async () => {
    const fixture = await createFixture();
    await writeFile(fixture.configPath, "{invalid", "utf8");
    await writeFile(fixture.credentialPath, "{invalid", "utf8");
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.externalStatus.mockResolvedValueOnce(null);

    await expect(
      fixture.runtime.invoke("openwiki_status", {}),
    ).resolves.toEqual(
      expect.objectContaining({
        authRequired: false,
        authentication: { status: "not_required" },
        executionMode: "external_agent",
        externalAgent: { activeTransaction: null, ready: true },
        legacyProvider: expect.objectContaining({
          authentication: { status: "invalid" },
          initialized: false,
        }),
      }),
    );
  });

  test.each([
    [
      "both",
      ["openwiki_begin_external_update", "openwiki_finalize_external_update"],
      true,
      1,
    ],
    ["begin only", ["openwiki_begin_external_update"], false, 0],
    ["finalize only", ["openwiki_finalize_external_update"], false, 0],
    ["neither", [], false, 0],
  ] as const)(
    "derives external readiness from the complete pair: %s",
    async (_label, tools, ready, statusCalls) => {
      const fixture = await createFixture();
      fixture.setVerifiedTools([...tools]);
      fixture.externalStatus.mockResolvedValueOnce(null);

      const result = (await fixture.runtime.invoke("openwiki_status", {})) as {
        externalAgent: { ready: boolean };
        initialized: boolean;
      };

      expect(result.externalAgent.ready).toBe(ready);
      expect(result.initialized).toBe(ready);
      expect(fixture.externalStatus).toHaveBeenCalledTimes(statusCalls);
    },
  );

  test("fails status closed when the bounded external owner status is unreadable", async () => {
    const fixture = await createFixture();
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.externalStatus.mockRejectedValueOnce(
      new Error("secret owner path"),
    );

    await expect(
      fixture.runtime.invoke("openwiki_status", {}),
    ).resolves.toEqual({
      error: {
        code: "internal_error",
        message: "The external transaction state could not be read safely.",
        retryable: false,
      },
      ok: false,
      recovery: { action: "restore" },
    });
  });

  test("keeps external owner lock contention as busy and retryable", async () => {
    const fixture = await createFixture();
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.externalStatus.mockRejectedValueOnce(
      Object.assign(new Error("busy"), { code: "busy" }),
    );

    await expect(
      fixture.runtime.invoke("openwiki_status", {}),
    ).resolves.toEqual({
      error: {
        code: "busy",
        message:
          "Another C7 OpenWiki operation currently owns the required lock.",
        retryable: true,
      },
      ok: false,
      recovery: { action: "retry" },
    });
  });

  test.each([
    ["candidate_writable", "resume_candidate"],
    ["review_ready", "retry_review"],
    ["repair_ready", "resume_candidate"],
    ["attention", "resolve_attention"],
    ["publish_pending", "restore"],
  ] as const)(
    "reports bounded active external state %s",
    async (state, nextAction) => {
      const fixture = await createFixture();
      fixture.setVerifiedTools([
        "openwiki_begin_external_update",
        "openwiki_finalize_external_update",
      ]);
      fixture.externalStatus.mockResolvedValueOnce({
        generation: 1,
        nextAction,
        state,
        transactionId: "external-12345678",
      });

      const result = (await fixture.runtime.invoke("openwiki_status", {})) as {
        externalAgent: { activeTransaction: unknown };
      };
      expect(result.externalAgent.activeTransaction).toEqual({
        generation: 1,
        nextAction,
        state,
        transactionId: "external-12345678",
      });
    },
  );

  test("dispatches external begin without config, credentials, or legacy model services", async () => {
    const fixture = await createFixture();
    await rm(fixture.configPath, { force: true });
    await rm(fixture.credentialPath, { force: true });
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.externalBegin.mockResolvedValueOnce(
      externalReadyOutcome(fixture.runtimeDir),
    );

    const result = await fixture.runtime.invoke(
      "openwiki_begin_external_update",
      {
        action: "start",
        confirmedByUser: true,
        confirmedWikiPaths: ["index.md"],
        expectedWikiRevision: hash("1"),
        instruction: "Refresh the project Wiki.",
        requestId: "request-12345678",
      },
    );

    expect(result).toEqual(externalReadyOutcome(fixture.runtimeDir));
    expect(fixture.externalBegin).toHaveBeenCalledTimes(1);
    expect(fixture.createQuery).not.toHaveBeenCalled();
    expect(fixture.createUpdate).not.toHaveBeenCalled();
    expect(fixture.modelVerify).not.toHaveBeenCalled();
  });

  test("dispatches the adapted personal begin through its lifecycle owner", async () => {
    const fixture = await createFixture();
    fixture.setVerifiedTools([
      "openwiki_begin",
      "openwiki_submit_plan",
      "openwiki_next_page",
      "openwiki_inspect_page_claims",
      "openwiki_submit_page",
      "openwiki_finish",
    ]);
    const expected = personalBeginOutcome(fixture.runtimeDir);
    fixture.personalBegin.mockResolvedValueOnce(expected);

    const result = await fixture.runtime.invoke("openwiki_begin", {
      mode: "update",
      wikiRoot: path.join(fixture.runtimeDir, "personal-wiki"),
    });

    expect(result).toEqual(expected);
    expect(fixture.personalBegin).toHaveBeenCalledWith({
      mode: "update",
      wikiRoot: path.join(fixture.runtimeDir, "personal-wiki"),
    });
  });

  test("fails closed for a direct personal lifecycle call without verified capability evidence", async () => {
    const fixture = await createFixture();

    await expect(
      fixture.runtime.invoke("openwiki_begin", {
        mode: "update",
        wikiRoot: path.join(fixture.runtimeDir, "personal-wiki"),
      }),
    ).resolves.toEqual({
      error: {
        code: "capability_unverified",
        message:
          "This OpenWiki capability has no current matching local verification evidence.",
        retryable: false,
      },
      ok: false,
      recovery: { action: "none" },
    });
    expect(fixture.personalBegin).not.toHaveBeenCalled();
  });

  test.each(externalFinalizeInputs())(
    "dispatches external finalize action $action through the same service",
    async (input) => {
      const fixture = await createFixture();
      fixture.setRecoveryState("clean");
      fixture.setVerifiedTools([
        "openwiki_begin_external_update",
        "openwiki_finalize_external_update",
      ]);
      const outcome = externalAbortedOutcome();
      fixture.externalFinalize.mockResolvedValueOnce(outcome);

      await expect(
        fixture.runtime.invoke("openwiki_finalize_external_update", input),
      ).resolves.toEqual(outcome);
      expect(fixture.externalFinalize).toHaveBeenCalledWith(input);
      expect(fixture.externalBegin).not.toHaveBeenCalled();
      expect(fixture.createQuery).not.toHaveBeenCalled();
      expect(fixture.createUpdate).not.toHaveBeenCalled();
      expect(fixture.modelVerify).not.toHaveBeenCalled();
    },
  );

  test.each([
    ["begin only", ["openwiki_begin_external_update"]],
    ["finalize only", ["openwiki_finalize_external_update"]],
    ["neither", []],
  ] as const)(
    "rejects both external tools before service invocation with a partial pair: %s",
    async (_label, tools) => {
      const fixture = await createFixture();
      fixture.setRecoveryState("clean");
      fixture.setVerifiedTools([...tools]);

      for (const [name, input] of [
        [
          "openwiki_begin_external_update",
          {
            action: "resume",
            bindingHash: hash("2"),
            transactionId: "external-12345678",
          },
        ],
        ["openwiki_finalize_external_update", externalFinalizeInputs()[3]],
      ] as const) {
        await expect(fixture.runtime.invoke(name, input)).resolves.toEqual(
          expect.objectContaining({
            error: expect.objectContaining({ code: "capability_unverified" }),
            ok: false,
          }),
        );
      }
      expect(fixture.externalBegin).not.toHaveBeenCalled();
      expect(fixture.externalFinalize).not.toHaveBeenCalled();
    },
  );

  test("blocks begin and finalize before service invocation while recovery is unresolved", async () => {
    const fixture = await createFixture();
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.setRecoveryState("restore_required");

    await expect(
      fixture.runtime.invoke("openwiki_begin_external_update", {
        action: "resume",
        bindingHash: hash("2"),
        transactionId: "external-12345678",
      }),
    ).resolves.toEqual(
      expect.objectContaining({
        error: expect.objectContaining({ code: "restore_required" }),
        ok: false,
      }),
    );
    await expect(
      fixture.runtime.invoke(
        "openwiki_finalize_external_update",
        externalFinalizeInputs()[1],
      ),
    ).resolves.toEqual(
      expect.objectContaining({
        error: expect.objectContaining({ code: "restore_required" }),
        ok: false,
      }),
    );
    expect(fixture.externalBegin).not.toHaveBeenCalled();
    expect(fixture.externalFinalize).not.toHaveBeenCalled();
  });

  test("allows only a confirmed abort during restore_required and resolves recovery", async () => {
    const fixture = await createFixture();
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.setRecoveryState("restore_required");
    fixture.externalFinalize.mockResolvedValueOnce(externalAbortedOutcome());
    fixture.externalStatus.mockResolvedValueOnce(null);

    await expect(
      fixture.runtime.invoke(
        "openwiki_finalize_external_update",
        externalFinalizeInputs()[3],
      ),
    ).resolves.toEqual(externalAbortedOutcome());
    expect(fixture.externalFinalize).toHaveBeenCalledTimes(1);
    expect(fixture.externalRecoveryResolved).toHaveBeenCalledTimes(1);
    await expect(
      fixture.runtime.invoke("openwiki_status", {}),
    ).resolves.toEqual(
      expect.objectContaining({
        externalAgent: { activeTransaction: null, ready: true },
        runtime: expect.objectContaining({ recoveryState: "clean" }),
      }),
    );
  });

  test("does not expose an external writable package while startup recovery is unresolved", async () => {
    const fixture = await createFixture();
    fixture.setVerifiedTools([
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
    ]);
    fixture.setRecoveryState("restore_required");

    const result = (await fixture.runtime.invoke(
      "openwiki_begin_external_update",
      {
        action: "resume",
        bindingHash: hash("2"),
        transactionId: "external-12345678",
      },
    )) as { error: { code: string }; ok: boolean };

    expect(result).toEqual(
      expect.objectContaining({
        error: expect.objectContaining({ code: "restore_required" }),
        ok: false,
      }),
    );
    expect(fixture.externalBegin).not.toHaveBeenCalled();
  });

  test("rejects a runtime override outside the repository runtime root", async () => {
    const outside = await mkdtemp(
      path.join(os.tmpdir(), "c7-runtime-outside-"),
    );
    tempDirs.push(outside);
    const repositoryRoot = path.resolve(import.meta.dirname, "../..");

    await expect(
      bootstrapC7Runtime({ repositoryRoot, runtimeDir: outside }),
    ).rejects.toThrow("must stay inside");
  });

  test("minimal status fails closed while the Wiki lock is held", async () => {
    const repositoryRoot = path.resolve(import.meta.dirname, "../..");
    const runtimeRoot = path.join(repositoryRoot, "runtime");
    await mkdir(runtimeRoot, { recursive: true });
    const runtimeDir = await mkdtemp(path.join(runtimeRoot, "minimal-status-"));
    tempDirs.push(runtimeDir);
    await mkdir(path.join(runtimeDir, "locks", "wiki.lock"), {
      recursive: true,
    });
    const bootstrapped = await bootstrapC7Runtime({
      repositoryRoot,
      runtimeDir,
    });

    await expect(
      bootstrapped.runtime.invoke("openwiki_status", {}),
    ).resolves.toEqual(
      expect.objectContaining({
        error: expect.objectContaining({ code: "busy" }),
        ok: false,
      }),
    );
  });

  test.each([
    [
      "verified pair",
      ["openwiki_begin_external_update", "openwiki_finalize_external_update"],
      true,
    ],
    ["partial pair", ["openwiki_begin_external_update"], false],
  ] as const)(
    "bootstrap composes external availability from a %s without setup",
    async (_label, verified, expectedReady) => {
      const repositoryRoot = path.resolve(import.meta.dirname, "../..");
      const runtimeRoot = path.join(repositoryRoot, "runtime");
      await mkdir(runtimeRoot, { recursive: true });
      const runtimeDir = await mkdtemp(
        path.join(runtimeRoot, "task7-bootstrap-"),
      );
      tempDirs.push(runtimeDir);
      const openWikiRoot = await mkdtemp(
        path.join(os.tmpdir(), "openwiki-task7-"),
      );
      tempDirs.push(openWikiRoot);
      await mkdir(path.join(openWikiRoot, "dist", "agent"), {
        recursive: true,
      });
      await writeFile(
        path.join(openWikiRoot, "package.json"),
        JSON.stringify({
          name: "openwiki",
          version: (
            JSON.parse(
              await readFile(
                path.resolve(
                  repositoryRoot,
                  "..",
                  ".work",
                  "openwiki",
                  "package.json",
                ),
                "utf8",
              ),
            ) as { version: string }
          ).version,
        }),
      );
      await writeFile(
        path.join(openWikiRoot, ".selfopenwiki-materialization.json"),
        await readFile(
          path.resolve(
            repositoryRoot,
            "..",
            ".work",
            "openwiki",
            ".selfopenwiki-materialization.json",
          ),
        ),
      );
      await writeFile(
        path.join(openWikiRoot, "dist", "cli.js"),
        "export {};\n",
      );
      await writeFile(
        path.join(openWikiRoot, "dist", "agent", "openai-chatgpt-oauth.js"),
        "export {};\n",
      );
      const verifiedSet = new Set<string>(verified);
      vi.spyOn(
        capabilitiesModule,
        "loadRuntimeCapabilityGate",
      ).mockResolvedValue({
        failureReason: "setup is unverified",
        isToolVerified: (name: string) => verifiedSet.has(name),
        records: () => [],
      } as unknown as RuntimeCapabilityGate);

      const bootstrapped = await bootstrapC7Runtime({
        openWikiRoot,
        repositoryRoot,
        runtimeDir,
      });
      const status = (await bootstrapped.runtime.invoke(
        "openwiki_status",
        {},
      )) as {
        externalAgent: { ready: boolean };
      };
      expect(status.externalAgent.ready).toBe(expectedReady);
      const begin = (await bootstrapped.runtime.invoke(
        "openwiki_begin_external_update",
        {
          action: "resume",
          bindingHash: hash("2"),
          transactionId: "external-12345678",
        },
      )) as { error?: { code: string } };
      if (!expectedReady) {
        expect(begin.error?.code).toBe("capability_unverified");
      }
    },
  );

  test("reports semantic attention, allows a confirmed correction, and blocks technical review debt", async () => {
    const fixture = await createFixture();

    const status = (await fixture.runtime.invoke("openwiki_status", {})) as {
      ok: boolean;
      recovery: { action: string };
      runtime: { recoveryState: string };
      wikiRevision: string;
    };
    expect(status.ok).toBe(true);
    expect(status.runtime.recoveryState).toBe("attention");
    expect(status.recovery.action).toBe("resolve_attention");
    expect(status.wikiRevision).toMatch(/^sha256:[a-f0-9]{64}$/u);

    await expect(
      fixture.runtime.update({
        confirmedByUser: true,
        expectedWikiRevision: status.wikiRevision,
        instruction: "Fix.",
      }),
    ).resolves.toEqual({ recoveryState: "clean", status: "updated" });
    expect(fixture.update).toHaveBeenCalledTimes(1);

    fixture.setRecoveryState("review_pending");
    await expect(
      fixture.runtime.update({
        confirmedByUser: true,
        expectedWikiRevision: status.wikiRevision,
        instruction: "Fix.",
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "restore_required" }));
    expect(fixture.update).toHaveBeenCalledTimes(1);
  });

  test("allows read-only query during semantic attention and returns an explicit warning", async () => {
    const fixture = await createFixture();

    const result = (await fixture.runtime.query({ instruction: "Read." })) as {
      recovery: { action: string; message: string };
    };

    expect(result.recovery.action).toBe("none");
    expect(result.recovery.message).toContain("semantic attention");
    expect(fixture.query).toHaveBeenCalledTimes(1);
  });

  test("fails status closed instead of reading a Wiki during an active Wiki lock", async () => {
    const fixture = await createFixture();
    await mkdir(path.join(fixture.runtimeDir, "locks", "wiki.lock"), {
      recursive: true,
    });

    const result = (await fixture.runtime.invoke("openwiki_status", {})) as {
      error: { code: string };
      ok: boolean;
    };

    expect(result.ok).toBe(false);
    expect(result.error.code).toBe("busy");
  });

  test.each(["publish_failed", "restore_failed"] as const)(
    "returns a safe recovery obligation for %s instead of a generic error",
    async (code) => {
      const fixture = await createFixture();
      fixture.setVerifiedTools(["openwiki_begin"]);
      fixture.personalBegin.mockRejectedValueOnce(
        new C7PublishError(code, "token=secret-publish-canary", {
          cause: Object.assign(
            new Error("C:\\private-source\\secret-canary.md"),
            { code: "EPERM", syscall: "rename", path: "C:\\private-source" },
          ),
        }),
      );
      const result = await fixture.runtime.invoke("openwiki_begin", {
        mode: "update",
        wikiRoot: path.join(fixture.runtimeDir, "wiki"),
      });
      expect(result).toMatchObject({
        ok: false,
        recovery: { action: "restore" },
        error: {
          code: "restore_required",
          retryable: false,
          details: {
            diagnostic: `publisher=${code}; cause=EPERM; syscall=rename`,
          },
        },
      });
      expect(JSON.stringify(result)).not.toMatch(/secret|private-source|stack/);
      expect(toolOutputSchemas.openwiki_begin.safeParse(result).success).toBe(
        true,
      );
    },
  );

  test("returns a bounded sanitized diagnostic for process failures", async () => {
    const fixture = await createFixture();
    fixture.query.mockRejectedValueOnce(
      Object.assign(
        new C7QueryError(
          "process_failure",
          "The isolated OpenWiki query failed.",
          "stage=cli-import token=secret-token-canary",
        ),
        { failureStage: "result_schema_invalid" },
      ),
    );

    const result = (await fixture.runtime.invoke("openwiki_query", {
      executionMode: "legacy_provider",
      instruction: "Read.",
    })) as {
      error: {
        details?: { diagnostic?: string; failureStage?: string };
      };
      ok: boolean;
    };

    expect(result.ok).toBe(false);
    expect(result.error.details?.diagnostic).toBe(
      "stage=cli-import token=[REDACTED]",
    );
    expect(result.error.details?.failureStage).toBe("result_schema_invalid");
    expect(JSON.stringify(result)).not.toContain("secret-token-canary");
  });
});

async function createFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-runtime-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const wikiPath = path.join(runtimeDir, "wiki");
  const configPath = path.join(runtimeDir, "config.json");
  const credentialPath = path.join(runtimeDir, "credentials.json");
  const visualizerPath = path.join(root, "Visualize.bat");
  await mkdir(wikiPath, { recursive: true });
  await writeFile(visualizerPath, "@echo off\n", "utf8");
  const selection = { model: "gpt-5.6-sol", reasoningEffort: "xhigh" };
  await writeFile(
    configPath,
    `${JSON.stringify({
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
    })}\n`,
    "utf8",
  );
  await writeFile(
    credentialPath,
    `${JSON.stringify({
      access: "test-access-token",
      accountId: "account-12345678",
      email: null,
      expiresAtMs: Date.now() + 60_000,
      planType: null,
      refresh: "test-refresh-token",
      schemaVersion: 1,
    })}\n`,
    "utf8",
  );
  let recoveryState: C7RuntimeRecoveryState = "attention";
  const update = vi.fn(async () => ({
    recoveryState: "clean",
    status: "updated",
  }));
  const query = vi.fn(async () => ({
    answer: "Current knowledge.",
    ok: true,
    recovery: { action: "none" },
    status: "answered",
  }));
  const createQuery = vi.fn(() => ({ query }));
  const createUpdate = vi.fn(() => ({ update }));
  const externalBegin = vi.fn();
  const externalFinalize = vi.fn();
  const externalRecoveryResolved = vi.fn(() => {
    recoveryState = "clean";
  });
  const externalStatus = vi.fn();
  const personalBegin = vi.fn();
  const modelVerify = vi.fn();
  const verifiedTools = new Set<string>();
  const capabilities = {
    isToolVerified: vi.fn((name: string) => verifiedTools.has(name)),
    records: vi.fn(() =>
      [...verifiedTools].map((name) => ({
        id:
          name === "openwiki_begin_external_update"
            ? "update.external-agent.begin"
            : "update.external-agent.reviewed-finalize",
        verifiedAt: "2026-08-07T00:00:00.000Z",
      })),
    ),
  };
  const runtime = new C7OpenWikiRuntime({
    capabilities: capabilities as unknown as RuntimeCapabilityGate,
    configPath,
    createQuery,
    createUpdate,
    credentialPath,
    externalUpdate: {
      begin: externalBegin,
      finalize: externalFinalize,
      status: externalStatus,
    },
    modelService: {} as RuntimeModelService,
    modelVerifier: { verify: modelVerify },
    onExternalRecoveryResolved: externalRecoveryResolved,
    openWikiRoot: root,
    recoveryState: () => recoveryState,
    runtimeDir,
    setup: {} as SetupAttemptManager,
    skills: { list: () => [], select: vi.fn() },
    sources: { prepare: vi.fn() },
    versions: { mcpServer: "0.1.0", openWiki: "0.1.0" },
    visualizer: {
      id: "selfopenwiki.zxh_wiki_viewer",
      contractSchema: 1,
      launcherPath: visualizerPath,
      loopbackOnly: true,
      autoOpen: false,
      wikiRootInput: { kind: "argument", flag: "--wiki-root" },
      urlTemplate: "http://127.0.0.1:{port}/wiki/local",
    },
    wikiPath,
    personalLifecycle: {
      begin: personalBegin,
    },
  } as never);
  return {
    configPath,
    createQuery,
    createUpdate,
    credentialPath,
    externalBegin,
    externalFinalize,
    externalRecoveryResolved,
    externalStatus,
    modelVerify,
    personalBegin,
    query,
    runtime,
    runtimeDir,
    visualizerPath,
    setVerifiedTools(tools: readonly string[]) {
      verifiedTools.clear();
      for (const tool of tools) verifiedTools.add(tool);
    },
    setRecoveryState(value: C7RuntimeRecoveryState) {
      recoveryState = value;
    },
    update,
  };
}

function personalBeginOutcome(runtimeDir: string) {
  return {
    ok: true as const,
    protocol: "selfopenwiki:personal-openwiki-v1" as const,
    recovery: { action: "none" as const },
    status: "planning" as const,
    runId: "11111111-1111-4111-8111-111111111111",
    wikiRoot: path.join(runtimeDir, "personal-wiki"),
    runtimeRoot: path.join(runtimeDir, "personal-wiki.selfopenwiki"),
    wikiRevision: hash("a"),
    skillAggregateHash: hash("b"),
    upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    binding: {
      wikiRoot: path.join(runtimeDir, "personal-wiki"),
      runtimeRoot: path.join(runtimeDir, "personal-wiki.selfopenwiki"),
      wikiRevision: hash("a"),
      markdownWikiRevision: hash("a"),
      skillAggregateHash: hash("b"),
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    },
  };
}

function externalReadyOutcome(runtimeDir: string) {
  const transactionRoot = path.join(
    runtimeDir,
    "external-updates",
    "external-12345678",
  );
  const immutableRoot = path.join(transactionRoot, "immutable");
  const candidateRoot = path.join(
    transactionRoot,
    "generations",
    "1",
    "candidate",
  );
  return {
    authRequired: false as const,
    executionMode: "external_agent" as const,
    ok: true as const,
    recovery: { action: "none" as const },
    status: "external_update_ready" as const,
    workPackage: {
      beforeWikiRevision: hash("1"),
      bindingHash: hash("2"),
      candidate: {
        allowedChangedPaths: ["index.md"],
        permissions: ["read", "list", "write"] as const,
        rootPath: candidateRoot,
        workspaceId: "workspace-12345678",
      },
      confirmedWikiPaths: ["index.md"],
      generation: 1,
      requestPackage: {
        packageHash: hash("3"),
        path: path.join(immutableRoot, "request.json"),
      },
      rules: {
        candidateResultContract: {
          path: path.join(immutableRoot, "candidate-result-contract.json"),
          schemaHash: hash("4"),
        },
        hardRulePackage: {
          packageHash: hash("5"),
          path: path.join(immutableRoot, "hard-rules.md"),
        },
        skills: [
          {
            category: "base" as const,
            id: "kg-c7-project-wiki",
            loadOrder: "base_always_first" as const,
            packageHash: hash("6"),
            rootPath: path.join(immutableRoot, "skills", "000-base"),
          },
        ],
      },
      skillAggregateHash: hash("7"),
      sourceManifestHash: null,
      sourceTreeHash: null,
      sources: null,
      transactionId: "external-12345678",
      version: 1 as const,
    },
  };
}

function externalAbortedOutcome() {
  return {
    authRequired: false as const,
    bindingHash: hash("2"),
    executionMode: "external_agent" as const,
    generation: 1,
    ok: true as const,
    published: false as const,
    recovery: { action: "none" as const },
    status: "external_update_aborted" as const,
    transactionId: "external-12345678",
  };
}

function externalFinalizeInputs() {
  return [
    {
      action: "prepare_review" as const,
      bindingHash: hash("2"),
      candidateReceipt: {
        bindingHash: hash("2"),
        classification: "minor" as const,
        generation: 1,
        issues: [],
        questions: [],
        summary: "Candidate complete.",
        transactionId: "external-12345678",
        type: "external_candidate_receipt" as const,
        version: 1 as const,
        writerExecutionId: "writer-12345678",
      },
      transactionId: "external-12345678",
    },
    {
      action: "submit_review" as const,
      bindingHash: hash("2"),
      reviewReceipt: {
        bindingHash: hash("2"),
        candidateReceiptHash: hash("3"),
        candidateRootHash: hash("4"),
        generation: 1,
        issues: [],
        reviewerExecutionId: "reviewer-12345678",
        reviewPackageHash: hash("5"),
        transactionId: "external-12345678",
        type: "external_review_receipt" as const,
        verdict: "pass" as const,
        version: 1 as const,
      },
      transactionId: "external-12345678",
    },
    {
      action: "report_host_failure" as const,
      bindingHash: hash("2"),
      code: "host_timeout" as const,
      message: "The Host timed out.",
      phase: "candidate_writer" as const,
      retryable: true,
      transactionId: "external-12345678",
    },
    {
      action: "abort" as const,
      bindingHash: hash("2"),
      confirmedByUser: true as const,
      transactionId: "external-12345678",
    },
  ];
}

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}
