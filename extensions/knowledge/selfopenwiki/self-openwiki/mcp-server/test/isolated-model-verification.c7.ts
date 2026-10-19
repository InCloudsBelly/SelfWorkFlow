import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  IsolatedOpenWikiModelVerifier,
  type ModelSelection,
} from "../src/model-verification.js";

const tempDirs: string[] = [];
const childScriptPath = path.resolve(
  import.meta.dirname,
  "../dist/model-verification-child.js",
);
const fakeCliPath = path.resolve(
  import.meta.dirname,
  "fixtures/fake-smoke-cli.mjs",
);
const selection: ModelSelection = {
  model: "gpt-5.6-sol",
  reasoningEffort: "xhigh",
};

afterEach(async () => {
  delete process.env.C7_TEST_SECRET_CANARY;
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("fresh-process OpenWiki model verification", () => {
  test("sets isolated Home before CLI import and observes the final request boundary", async () => {
    const home = await createHome();
    process.env.C7_TEST_SECRET_CANARY = "must-not-cross";
    const originalHome = process.env.OPENWIKI_HOME;
    const verifier = createVerifier(home);

    await expect(
      verifier.verify(selection, "credential-reference-12345678"),
    ).resolves.toEqual({
      providerAccepted: true,
      requested: selection,
      sent: selection,
    });

    expect(process.env.OPENWIKI_HOME).toBe(originalHome);
    const observed = JSON.parse(
      await readFile(path.join(home, "smoke-observed.json"), "utf8"),
    );
    expect(observed).toEqual({
      home,
      model: selection.model,
      effort: selection.reasoningEffort,
      provider: "openai-chatgpt",
      shellMode: "restricted",
      parentSecretPresent: false,
      pid: expect.any(Number),
    });
    expect(isProcessAlive(observed.pid)).toBe(false);
  });

  test("rejects process failure and observed fallback without downgrade", async () => {
    const home = await createHome();
    const verifier = createVerifier(home);

    await expect(
      verifier.verify(
        { model: "gpt-test-process-failure", reasoningEffort: "high" },
        "credential-reference-12345678",
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "process_failure" }));
    await expect(
      verifier.verify(
        { model: "gpt-test-fallback", reasoningEffort: "high" },
        "credential-reference-12345678",
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "internal_error" }));
  });

  test("requires a successful final provider response", async () => {
    const home = await createHome();
    const verifier = createVerifier(home);

    for (const model of ["gpt-test-abort", "gpt-test-401", "gpt-test-429"]) {
      await expect(
        verifier.verify(
          { model, reasoningEffort: "high" },
          "credential-reference-12345678",
        ),
      ).rejects.toEqual(expect.objectContaining({ code: "provider_failure" }));
    }
  });

  test("rejects an unparseable final Codex request after a successful request", async () => {
    const home = await createHome();
    const verifier = createVerifier(home);

    await expect(
      verifier.verify(
        { model: "gpt-test-malformed-final", reasoningEffort: "high" },
        "credential-reference-12345678",
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "internal_error" }));
  });

  test("terminates a timed-out verifier child", async () => {
    const home = await createHome();
    const verifier = createVerifier(home, 150);

    await expect(
      verifier.verify(
        { model: "gpt-test-hang", reasoningEffort: "low" },
        "credential-reference-12345678",
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "process_failure" }));
  });

  test("cleans a prepared Home when cancellation arrives before spawn", async () => {
    const home = await createHome();
    const cleanup = vi.fn().mockResolvedValue(undefined);
    const controller = new AbortController();
    let releaseHome!: () => void;
    const homeReady = new Promise<void>((resolve) => {
      releaseHome = resolve;
    });
    const verifier = new IsolatedOpenWikiModelVerifier({
      adapterPaths: {
        rootDir: path.dirname(fakeCliPath),
        cliPath: fakeCliPath,
        oauthModulePath: fakeCliPath,
      },
      childScriptPath,
      resolveOpenWikiHome: async () => {
        await homeReady;
        return { cleanup, path: home };
      },
    });
    const verification = verifier.verify(
      selection,
      "credential-reference-12345678",
      controller.signal,
    );
    controller.abort();
    releaseHome();

    await expect(verification).rejects.toEqual(
      expect.objectContaining({ code: "process_failure" }),
    );
    expect(cleanup).toHaveBeenCalledTimes(1);
    await expect(
      readFile(path.join(home, "smoke-observed.json")),
    ).rejects.toBeDefined();
  });

  test("cleans a secret-bearing Home when preparation validation fails", async () => {
    const home = await createHome();
    const cleanup = vi.fn().mockResolvedValue(undefined);
    const verifier = new IsolatedOpenWikiModelVerifier({
      adapterPaths: {
        rootDir: path.dirname(fakeCliPath),
        cliPath: path.join(home, "missing-cli.mjs"),
        oauthModulePath: fakeCliPath,
      },
      childScriptPath,
      resolveOpenWikiHome: async () => ({ cleanup, path: home }),
    });

    await expect(
      verifier.verify(selection, "credential-reference-12345678"),
    ).rejects.toEqual(expect.objectContaining({ code: "process_failure" }));
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  test("still cleans the Home when refresh finalization fails", async () => {
    const home = await createHome();
    const cleanup = vi.fn().mockResolvedValue(undefined);
    const verifier = new IsolatedOpenWikiModelVerifier({
      adapterPaths: {
        rootDir: path.dirname(fakeCliPath),
        cliPath: fakeCliPath,
        oauthModulePath: fakeCliPath,
      },
      childScriptPath,
      resolveOpenWikiHome: async () => ({
        cleanup,
        finalize: vi.fn().mockRejectedValue(new Error("CAS conflict")),
        path: home,
      }),
    });

    await expect(
      verifier.verify(selection, "credential-reference-12345678"),
    ).rejects.toEqual(expect.objectContaining({ code: "process_failure" }));
    expect(cleanup).toHaveBeenCalledTimes(1);
  });
});

function createVerifier(
  home: string,
  timeoutMs = 2_000,
): IsolatedOpenWikiModelVerifier {
  return new IsolatedOpenWikiModelVerifier({
    adapterPaths: {
      rootDir: path.dirname(fakeCliPath),
      cliPath: fakeCliPath,
      oauthModulePath: fakeCliPath,
    },
    childScriptPath,
    resolveOpenWikiHome: async (reference) => {
      if (reference !== "credential-reference-12345678") {
        throw new Error("unknown credential reference");
      }
      return home;
    },
    timeoutMs,
  });
}

async function createHome(): Promise<string> {
  const home = await mkdtemp(path.join(os.tmpdir(), "c7-smoke-home-"));
  tempDirs.push(home);
  return home;
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
