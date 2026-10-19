import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  C7ProcessError,
  DEFAULT_OPENWIKI_PROCESS_TIMEOUT_MS,
  OpenWikiProcessRunner,
  providerFailureCodeForAcceptedDiagnostic,
  providerFailureCodeForStatus,
} from "../src/process.js";

const tempDirs: string[] = [];
const selection = { model: "gpt-5.6-sol", reasoningEffort: "xhigh" as const };
const standardRetryRequestDiagnostic =
  "An error occurred while processing your request. You can retry your request, or contact us through our help center at help.openai.com if the error persists. Please include the request ID 61ce5681-fee2-479a-8d24-aab1a3252379 in your message.";
const standardRetryRequestNearMatches = [
  standardRetryRequestDiagnostic.replace(
    "61ce5681-fee2-479a-8d24-aab1a3252379",
    "61CE5681-FEE2-479A-8D24-AAB1A3252379",
  ),
  standardRetryRequestDiagnostic.replace(
    "61ce5681-fee2-479a-8d24-aab1a3252379",
    "61ce5681fee2479a8d24aab1a3252379",
  ),
  standardRetryRequestDiagnostic.replace(
    "request ID 61ce5681-fee2-479a-8d24-aab1a3252379",
    "request ID",
  ),
  standardRetryRequestDiagnostic.replace(" You can retry your request,", ""),
  `prefix: ${standardRetryRequestDiagnostic}`,
  `${standardRetryRequestDiagnostic} suffix`,
  `provider notice\n${standardRetryRequestDiagnostic}`,
  `${standardRetryRequestDiagnostic}\nunexpected detail`,
  `${standardRetryRequestDiagnostic}\n\n`,
  `${standardRetryRequestDiagnostic}\r\n\r\n`,
  ` ${standardRetryRequestDiagnostic}`,
  `${standardRetryRequestDiagnostic} `,
  standardRetryRequestDiagnostic.toLowerCase(),
  `authentication failed\n${standardRetryRequestDiagnostic}`,
  `${standardRetryRequestDiagnostic}\ncontent rejected`,
  `local timeout\n${standardRetryRequestDiagnostic}`,
];

afterEach(async () => {
  delete process.env.C7_PARENT_SECRET_CANARY;
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("isolated OpenWiki process runner", () => {
  test.each([
    "Our servers are currently overloaded. Please try again later.",
    "Our servers are currently overloaded. Please try again later.\n",
    "Our servers are currently overloaded. Please try again later.\r\n",
  ])("classifies the exact accepted in-band overload diagnostic", (value) => {
    expect(providerFailureCodeForAcceptedDiagnostic(value)).toBe(
      "provider_transient",
    );
  });

  test("classifies the exact accepted standard retry-request diagnostic", () => {
    expect(
      providerFailureCodeForAcceptedDiagnostic(standardRetryRequestDiagnostic),
    ).toBe("provider_transient");
  });

  test.each(standardRetryRequestNearMatches)(
    "does not classify a near-match standard retry-request diagnostic: %s",
    (value) => {
      expect(providerFailureCodeForAcceptedDiagnostic(value)).toBeUndefined();
    },
  );

  test.each([
    "prefix: Our servers are currently overloaded. Please try again later.",
    "Our servers are currently overloaded. Please try again later. suffix",
    "Our servers are currently overloaded. Please try again later.\n\n",
    "authentication failed\nOur servers are currently overloaded. Please try again later.",
    "Our servers are currently overloaded. Please try again later.\ncontent rejected",
    "timeout\nOur servers are currently overloaded. Please try again later.",
    " Our servers are currently overloaded. Please try again later.",
    "Our servers are currently overloaded. Please try again later. ",
    "our servers are currently overloaded. please try again later.",
    "The server failed; retry later.",
  ])("does not classify a near-match diagnostic: %s", (value) => {
    expect(providerFailureCodeForAcceptedDiagnostic(value)).toBeUndefined();
  });

  test.each([
    [408, "provider_transient"],
    [429, "provider_transient"],
    [500, "provider_transient"],
    [503, "provider_transient"],
    [400, "provider_rejected"],
    [401, "provider_rejected"],
  ] as const)("classifies provider HTTP %i as %s", (status, expected) => {
    expect(providerFailureCodeForStatus(status)).toBe(expected);
  });

  test("allows one isolated model process to run for 45 minutes by default", () => {
    expect(DEFAULT_OPENWIKI_PROCESS_TIMEOUT_MS).toBe(45 * 60_000);
  });

  test("classifies an accepted exact in-band overload without inventing HTTP evidence", async () => {
    const fixture = await createFixture(`
      ${successfulObservedRequest()}
      process.stderr.write("Our servers are currently overloaded. Please try again later.\\n");
      process.exitCode = 1;
    `);

    const error = await fixture
      .runner()
      .run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "update",
        policyPath: fixture.policyPath,
        selection,
      })
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(C7ProcessError);
    expect(error).toEqual(
      expect.objectContaining({
        code: "provider_transient",
        diagnostic:
          "Our servers are currently overloaded. Please try again later.\n",
        providerStatusClass: undefined,
        retryAfterMs: undefined,
      }),
    );
  });

  test("classifies an accepted standard retry-request process without inventing HTTP evidence", async () => {
    const fixture = await createFixture(`
      ${successfulObservedRequest()}
      process.stderr.write(${JSON.stringify(`${standardRetryRequestDiagnostic}\n`)});
      process.exitCode = 1;
    `);

    const error = await fixture
      .runner()
      .run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "update",
        policyPath: fixture.policyPath,
        selection,
      })
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(C7ProcessError);
    expect(error).toEqual(
      expect.objectContaining({
        code: "provider_transient",
        diagnostic: `${standardRetryRequestDiagnostic}\n`,
        providerStatusClass: undefined,
        retryAfterMs: undefined,
      }),
    );
  });

  test.each(standardRetryRequestNearMatches)(
    "keeps an accepted standard retry-request near match terminal: %s",
    async (diagnostic) => {
      const fixture = await createFixture(`
        ${successfulObservedRequest()}
        process.stderr.write(${JSON.stringify(diagnostic)});
        process.exitCode = 1;
      `);

      await expect(
        fixture.runner().run({
          cwd: fixture.home,
          openWikiHome: fixture.home,
          operation: "update",
          policyPath: fixture.policyPath,
          selection,
        }),
      ).rejects.toEqual(expect.objectContaining({ code: "process_failed" }));
    },
  );

  test("rejects accepted-process failure carrying HTTP status or retry evidence", async () => {
    const fixture = await createFixture(`
      const originalSend = process.send.bind(process);
      process.send = (message, callback) => {
        originalSend({
          ...message,
          providerStatusClass: "5xx",
          retryAfterMs: 1000
        }, callback);
        return true;
      };
      ${successfulObservedRequest()}
      process.stderr.write("Our servers are currently overloaded. Please try again later.\\n");
      process.exitCode = 1;
    `);

    await expect(
      fixture.runner().run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "update",
        policyPath: fixture.policyPath,
        selection,
      }),
    ).rejects.toEqual(
      expect.objectContaining({
        code: "process_failed",
        providerStatusClass: undefined,
        retryAfterMs: undefined,
      }),
    );
  });

  test.each(["invalid-first", "invalid-second"] as const)(
    "does not combine accepted evidence across terminal IPC messages: %s",
    async (order) => {
      const fixture = await createFixture(`
        const originalSend = process.send.bind(process);
        process.send = (message, callback) => {
          const invalid = {
            ...message,
            code: "provider_transient",
            providerAccepted: true
          };
          if (${JSON.stringify(order)} === "invalid-first") {
            originalSend(invalid);
            originalSend(message, callback);
          } else {
            originalSend(message);
            originalSend(invalid, callback);
          }
          return true;
        };
        ${successfulObservedRequest()}
        process.stderr.write("Our servers are currently overloaded. Please try again later.\\n");
        process.exitCode = 1;
      `);

      await expect(
        fixture
          .runner({
            terminateProcessTree: async () => new Promise<void>(() => {}),
          })
          .run({
            cwd: fixture.home,
            openWikiHome: fixture.home,
            operation: "review",
            policyPath: fixture.policyPath,
            selection,
          }),
      ).rejects.toEqual(expect.objectContaining({ code: "process_failed" }));
    },
  );

  test.each([
    "authentication failed\\nOur servers are currently overloaded. Please try again later.",
    "Our servers are currently overloaded. Please try again later.\\ncontent rejected",
    "timeout\\nOur servers are currently overloaded. Please try again later.",
    "prefix: Our servers are currently overloaded. Please try again later.",
  ])(
    "keeps an accepted mixed or prefixed diagnostic terminal: %s",
    async (diagnostic) => {
      const fixture = await createFixture(`
      ${successfulObservedRequest()}
      process.stderr.write(${JSON.stringify(diagnostic)});
      process.exitCode = 1;
    `);

      await expect(
        fixture.runner().run({
          cwd: fixture.home,
          openWikiHome: fixture.home,
          operation: "review",
          policyPath: fixture.policyPath,
          selection,
        }),
      ).rejects.toEqual(expect.objectContaining({ code: "process_failed" }));
    },
  );

  test("does not classify overload text without an accepted request", async () => {
    const fixture = await createFixture(`
      process.stderr.write("Our servers are currently overloaded. Please try again later.\\n");
      process.exitCode = 1;
    `);

    await expect(
      fixture.runner().run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "query",
        policyPath: fixture.policyPath,
        selection,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "process_failed" }));
  });

  test("keeps model mismatch authoritative over overload text", async () => {
    const fixture = await createFixture(`
      await fetch("data:application/json,%7B%7D", {
        method: "POST",
        body: JSON.stringify({
          model: "gpt-fallback",
          reasoning: { effort: process.env.OPENWIKI_REASONING_EFFORT }
        })
      });
      process.stderr.write("Our servers are currently overloaded. Please try again later.\\n");
      process.exitCode = 1;
    `);

    await expect(
      fixture.runner().run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "query",
        policyPath: fixture.policyPath,
        selection,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "model_mismatch" }));
  });

  test("does not turn overload stderr from a successful CLI into a failure", async () => {
    const fixture = await createFixture(`
      ${successfulObservedRequest()}
      process.stderr.write("Our servers are currently overloaded. Please try again later.\\n");
    `);

    const result = await fixture.runner().run({
      cwd: fixture.home,
      openWikiHome: fixture.home,
      operation: "query",
      policyPath: fixture.policyPath,
      selection,
    });

    expect(result.exitCode).toBe(0);
    expect(result.model.providerAccepted).toBe(true);
  });

  test("uses a fixed CLI, argument array, and minimal child environment", async () => {
    const fixture = await createFixture(`
      ${successfulObservedRequest()}
      const selected = [
        "OPENWIKI_HOME", "OPENWIKI_PROVIDER", "OPENWIKI_REASONING_EFFORT",
        "OPENWIKI_RUN_POLICY_FILE", "OPENWIKI_SHELL_MODE",
        "OPENWIKI_TELEMETRY_DISABLED", "C7_PARENT_SECRET_CANARY"
      ];
      process.stdout.write(JSON.stringify({
        argv: process.argv.slice(2),
        cwd: process.cwd(),
        env: Object.fromEntries(selected.map((key) => [key, process.env[key]]))
      }));
    `);
    process.env.C7_PARENT_SECRET_CANARY = "must-not-cross";
    const runner = fixture.runner();

    const result = await runner.run({
      cwd: fixture.home,
      openWikiHome: fixture.home,
      operation: "query",
      policyPath: fixture.policyPath,
      selection,
    });
    const observed = JSON.parse(result.stdout) as {
      argv: string[];
      cwd: string;
      env: Record<string, string | undefined>;
    };

    expect(observed.argv).toEqual([
      "code",
      "--print",
      "--modelId",
      selection.model,
      "Read and execute the bound C7 request in _c7-control/in/request.md.",
    ]);
    const canonicalHome = await realpath(fixture.home);
    expect(path.resolve(observed.cwd).toLowerCase()).toBe(
      path.resolve(canonicalHome).toLowerCase(),
    );
    expect(observed.env).toEqual({
      OPENWIKI_HOME: canonicalHome,
      OPENWIKI_PROVIDER: "openai-chatgpt",
      OPENWIKI_REASONING_EFFORT: "xhigh",
      OPENWIKI_RUN_POLICY_FILE: fixture.policyPath,
      OPENWIKI_SHELL_MODE: "restricted",
      OPENWIKI_TELEMETRY_DISABLED: "1",
    });
    expect(observed.env).not.toHaveProperty("C7_PARENT_SECRET_CANARY");
    expect(result.model).toEqual({
      providerAccepted: true,
      requested: selection,
      sent: selection,
    });
  });

  test("adds update only for mutating model passes", async () => {
    const fixture = await createFixture(
      `${successfulObservedRequest()}
       process.stdout.write(JSON.stringify(process.argv.slice(2)));`,
    );
    const result = await fixture.runner().run({
      cwd: fixture.home,
      openWikiHome: fixture.home,
      operation: "repair",
      policyPath: fixture.policyPath,
      selection,
    });

    expect(JSON.parse(result.stdout)).toEqual([
      "code",
      "--print",
      "--update",
      "--modelId",
      selection.model,
      "Read and execute the bound C7 request in _c7-control/in/request.md.",
    ]);
  });

  test("runs the bounded result finalizer request without update mode", async () => {
    const fixture = await createFixture(
      `${successfulObservedRequest()}
       process.stdout.write(JSON.stringify(process.argv.slice(2)));`,
    );

    const result = await fixture.runner().run({
      cwd: fixture.home,
      openWikiHome: fixture.home,
      operation: "query",
      policyPath: fixture.policyPath,
      requestFileName: "result-finalizer.md",
      selection,
    });

    expect(JSON.parse(result.stdout)).toEqual([
      "code",
      "--print",
      "--modelId",
      selection.model,
      "Read and execute the bound C7 request in _c7-control/in/result-finalizer.md.",
    ]);
  });

  test("fails closed on CLI tampering before process execution", async () => {
    const fixture = await createFixture(
      "process.stdout.write('should-not-run');",
    );
    await writeFile(fixture.cliPath, "process.stdout.write('tampered');\n");

    await expect(
      fixture.runner().run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "query",
        policyPath: fixture.policyPath,
        selection,
      }),
    ).rejects.toEqual(
      expect.objectContaining({ code: "untrusted_executable" }),
    );
  });

  test("reports the sanitized child stage when CLI import fails", async () => {
    const fixture = await createFixture(
      'throw new Error("simulated import failure token=secret-token-canary");',
    );

    const error = await fixture
      .runner()
      .run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "query",
        policyPath: fixture.policyPath,
        selection,
      })
      .catch((caught: unknown) => caught);

    expect(error).toEqual(
      expect.objectContaining({
        code: "process_failed",
        diagnostic: expect.stringContaining("stage=cli-import"),
      }),
    );
    expect(error).toBeInstanceOf(C7ProcessError);
    if (!(error instanceof C7ProcessError)) {
      throw new Error("Expected C7ProcessError.");
    }
    expect(error.diagnostic).toContain("simulated import failure");
    expect(JSON.stringify(error)).not.toContain("secret-token-canary");
  });

  test("bounds output, terminates the process tree, and redacts diagnostics", async () => {
    const fixture = await createFixture(`
      ${successfulObservedRequest()}
      process.stderr.write("Authorization: Bearer secret-token-canary\\n");
      process.stdout.write("x".repeat(4096));
      setTimeout(() => process.exit(1), 50);
    `);
    const terminateProcessTree = vi.fn(async (pid: number) => {
      try {
        process.kill(pid);
      } catch {}
    });

    const error = await fixture
      .runner({ maxOutputBytes: 128, terminateProcessTree })
      .run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "review",
        policyPath: fixture.policyPath,
        selection,
      })
      .catch((caught: unknown) => caught);

    expect(error).toEqual(expect.objectContaining({ code: "output_limit" }));
    expect(JSON.stringify(error)).not.toContain("secret-token-canary");
    expect(terminateProcessTree).toHaveBeenCalledTimes(1);
  });

  test("times out and terminates only the spawned process tree", async () => {
    const fixture = await createFixture("setInterval(() => {}, 1000);");
    const terminateProcessTree = vi.fn(async (_pid: number) => undefined);

    await expect(
      fixture.runner({ terminateProcessTree, timeoutMs: 25 }).run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "query",
        policyPath: fixture.policyPath,
        selection,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "timeout" }));
    expect(terminateProcessTree).toHaveBeenCalledTimes(1);
    expect(terminateProcessTree.mock.calls[0]?.[0]).toEqual(expect.any(Number));
  });

  test("cancels and terminates only the spawned process tree", async () => {
    const fixture = await createFixture("setInterval(() => {}, 1000);");
    const terminateProcessTree = vi.fn(async (pid: number) => {
      try {
        process.kill(pid);
      } catch {}
    });
    const controller = new AbortController();
    const pending = fixture.runner({ terminateProcessTree }).run({
      cwd: fixture.home,
      openWikiHome: fixture.home,
      operation: "query",
      policyPath: fixture.policyPath,
      selection,
      signal: controller.signal,
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    controller.abort();

    await expect(pending).rejects.toEqual(
      expect.objectContaining({ code: "aborted" }),
    );
    expect(terminateProcessTree).toHaveBeenCalledTimes(1);
  });

  test("rejects a successful CLI run when the final provider request changes the model binding", async () => {
    const fixture = await createFixture(`
      await fetch("data:application/json,%7B%7D", {
        method: "POST",
        body: JSON.stringify({
          model: "gpt-fallback",
          reasoning: { effort: process.env.OPENWIKI_REASONING_EFFORT }
        })
      });
    `);

    await expect(
      fixture.runner().run({
        cwd: fixture.home,
        openWikiHome: fixture.home,
        operation: "query",
        policyPath: fixture.policyPath,
        selection,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "model_mismatch" }));
  });
});

async function createFixture(source: string): Promise<{
  cliPath: string;
  home: string;
  policyPath: string;
  runner(options?: {
    maxOutputBytes?: number;
    terminateProcessTree?(pid: number): Promise<void>;
    timeoutMs?: number;
  }): OpenWikiProcessRunner;
}> {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-process-"));
  tempDirs.push(root);
  const home = path.join(root, "home");
  const cliPath = path.join(root, "fake-openwiki.mjs");
  const policyPath = path.join(root, "run-policy.json");
  await mkdir(home);
  await writeFile(cliPath, source, "utf8");
  await writeFile(policyPath, "{}\n", "utf8");
  const expectedCliHash = `sha256:${createHash("sha256")
    .update(await readFile(cliPath))
    .digest("hex")}`;
  const childScriptPath = path.resolve(
    import.meta.dirname,
    "../dist/process-child.js",
  );
  const expectedChildHash = `sha256:${createHash("sha256")
    .update(await readFile(childScriptPath))
    .digest("hex")}`;
  return {
    cliPath,
    home,
    policyPath,
    runner: (options = {}) =>
      new OpenWikiProcessRunner({
        childScriptPath,
        cliPath,
        expectedChildHash,
        expectedCliHash,
        maxOutputBytes: options.maxOutputBytes,
        nodePath: process.execPath,
        responsesUrlPrefix: "data:application/json",
        terminateProcessTree: options.terminateProcessTree,
        timeoutMs: options.timeoutMs,
      }),
  };
}

function successfulObservedRequest(): string {
  return `
    await fetch("data:application/json,%7B%7D", {
      method: "POST",
      body: JSON.stringify({
        model: process.env.OPENWIKI_MODEL_ID,
        reasoning: { effort: process.env.OPENWIKI_REASONING_EFFORT }
      })
    });
  `;
}
