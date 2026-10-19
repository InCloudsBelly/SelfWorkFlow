import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { EphemeralCredentialVault } from "../src/auth.js";
import { ForkedOAuthAttemptFactory } from "../src/oauth-helper.js";

const helperScriptPath = path.resolve(
  import.meta.dirname,
  "fixtures/fake-openwiki.mjs",
);
const builtHelperScriptPath = path.resolve(
  import.meta.dirname,
  "../dist/oauth-helper-child.js",
);
const fakeOAuthModulePath = path.resolve(
  import.meta.dirname,
  "fixtures/fake-oauth-module.mjs",
);
const fakeLoopbackOAuthModulePath = path.resolve(
  import.meta.dirname,
  "fixtures/fake-loopback-oauth-module.mjs",
);
const fakeOAuthHostPath = path.resolve(
  import.meta.dirname,
  "fixtures/fake-oauth-host.mjs",
);
const adapterPaths = {
  rootDir: "D:\\openwikiC7",
  cliPath: "D:\\openwikiC7\\dist\\cli.js",
  oauthModulePath: "D:\\openwikiC7\\dist\\agent\\openai-chatgpt-oauth.js",
};
let savedCanary: string | undefined;

afterEach(() => {
  if (savedCanary === undefined) {
    delete process.env.C7_TEST_SECRET_CANARY;
  } else {
    process.env.C7_TEST_SECRET_CANARY = savedCanary;
  }
});

describe.sequential("private OAuth helper process", () => {
  test("runs the production helper entry against an upstream-compatible OAuth module", async () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-production",
    );
    const factory = new ForkedOAuthAttemptFactory({
      adapterPaths: { ...adapterPaths, oauthModulePath: fakeOAuthModulePath },
      helperScriptPath: builtHelperScriptPath,
      startTimeoutMs: 2_000,
      vault,
    });
    const session = await factory.start({
      setupAttemptId: "attempt-production",
      expiresAt: new Date(Date.now() + 5_000).toISOString(),
    });
    const authorization = await session.authorize(
      "code=sensitive-code&state=bound-state",
    );
    const writer = vi.fn().mockResolvedValue(undefined);
    await vault.persist(authorization.credentialReference, writer);

    expect(writer).toHaveBeenCalledWith(
      expect.objectContaining({ access: "access-secret-canary" }),
    );
  });

  test("exchanges callback and tokens only over IPC via an opaque reference", async () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-12345678",
    );
    const factory = new ForkedOAuthAttemptFactory({
      adapterPaths,
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault,
    });
    const session = await factory.start({
      setupAttemptId: "attempt-12345678",
      expiresAt: new Date(Date.now() + 5_000).toISOString(),
    });

    expect(session.authorizationUrl).toBe(
      "https://auth.openai.com/oauth/authorize?state=bound-state",
    );
    const authorization = await session.authorize(
      "http://localhost:1455/auth/callback?code=sensitive-code&state=bound-state",
    );
    expect(authorization).toEqual({
      credentialReference: "credential-reference-12345678",
    });
    expect(JSON.stringify(authorization)).not.toContain("access-secret");

    const writer = vi.fn().mockResolvedValue(undefined);
    await vault.persist(authorization.credentialReference, writer);
    expect(writer).toHaveBeenCalledWith(
      expect.objectContaining({
        access: "access-secret-canary",
        refresh: "refresh-secret-canary",
      }),
    );
  });

  test("keeps an authorized credential staged after the original attempt expiry", async () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-authorized",
    );
    const factory = new ForkedOAuthAttemptFactory({
      adapterPaths,
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault,
    });
    const expiresAtMs = Date.now() + 700;
    const session = await factory.start({
      setupAttemptId: "attempt-authorized",
      expiresAt: new Date(expiresAtMs).toISOString(),
    });
    const authorization = await session.authorize(
      "http://localhost:1455/auth/callback?code=sensitive-code&state=bound-state",
    );

    await new Promise((resolve) =>
      setTimeout(resolve, Math.max(1, expiresAtMs - Date.now() + 100)),
    );
    expect(vault.has(authorization.credentialReference)).toBe(true);

    const writer = vi.fn().mockResolvedValue(undefined);
    await vault.persist(authorization.credentialReference, writer);
    expect(writer).toHaveBeenCalledTimes(1);
  });

  test("waits for automatic browser callback without sending an empty manual completion", async () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-automatic",
    );
    const factory = new ForkedOAuthAttemptFactory({
      adapterPaths: {
        ...adapterPaths,
        oauthModulePath: path.resolve(
          import.meta.dirname,
          "fixtures/auto-oauth.js",
        ),
      },
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault,
    });
    const session = await factory.start({
      setupAttemptId: "attempt-automatic",
      expiresAt: new Date(Date.now() + 5_000).toISOString(),
    });

    await expect(session.authorize()).resolves.toEqual({
      credentialReference: "credential-reference-automatic",
    });
    await session.cancel();
    expect(vault.has("credential-reference-automatic")).toBe(false);
  });

  test("discards staged credentials on cancellation and expiry", async () => {
    const cancelVault = new EphemeralCredentialVault(
      () => "credential-reference-cancelled",
    );
    const cancelFactory = new ForkedOAuthAttemptFactory({
      adapterPaths,
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault: cancelVault,
    });
    const cancelSession = await cancelFactory.start({
      setupAttemptId: "attempt-cancelled",
      expiresAt: new Date(Date.now() + 5_000).toISOString(),
    });
    const authorization = await cancelSession.authorize(
      "http://localhost:1455/auth/callback?code=sensitive-code&state=bound-state",
    );
    expect(cancelVault.has(authorization.credentialReference)).toBe(true);
    await cancelSession.cancel();
    expect(cancelVault.has(authorization.credentialReference)).toBe(false);

    const expiryVault = new EphemeralCredentialVault(
      () => "credential-reference-expired",
    );
    const expiryFactory = new ForkedOAuthAttemptFactory({
      adapterPaths: {
        ...adapterPaths,
        oauthModulePath: path.resolve(
          import.meta.dirname,
          "fixtures/auto-oauth.js",
        ),
      },
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault: expiryVault,
    });
    await expiryFactory.start({
      setupAttemptId: "attempt-expiring",
      expiresAt: new Date(Date.now() + 500).toISOString(),
    });
    await vi.waitFor(
      () => expect(expiryVault.has("credential-reference-expired")).toBe(true),
      { timeout: 1_000 },
    );
    await vi.waitFor(
      () => expect(expiryVault.has("credential-reference-expired")).toBe(false),
      { timeout: 1_000 },
    );
  });

  test("uses an environment allowlist that excludes parent secrets", async () => {
    savedCanary = process.env.C7_TEST_SECRET_CANARY;
    process.env.C7_TEST_SECRET_CANARY = "parent-secret-must-not-cross";
    const factory = new ForkedOAuthAttemptFactory({
      adapterPaths,
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault: new EphemeralCredentialVault(),
    });

    const session = await factory.start({
      setupAttemptId: "attempt-12345678",
      expiresAt: new Date(Date.now() + 5_000).toISOString(),
    });
    await session.cancel();
  });

  test("cancel terminates the exact helper and makes the session terminal", async () => {
    const factory = new ForkedOAuthAttemptFactory({
      adapterPaths,
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault: new EphemeralCredentialVault(),
    });
    const session = await factory.start({
      setupAttemptId: "attempt-12345678",
      expiresAt: new Date(Date.now() + 5_000).toISOString(),
    });

    await expect(session.cancel()).resolves.toBeUndefined();
    await expect(
      session.authorize(
        "http://localhost:1455/auth/callback?code=sensitive-code&state=bound-state",
      ),
    ).rejects.toThrow(/terminal|closed|cancel/iu);
  });

  test("fails closed on malformed IPC and expiry", async () => {
    const malformed = new ForkedOAuthAttemptFactory({
      adapterPaths: { ...adapterPaths, oauthModulePath: "malformed" },
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault: new EphemeralCredentialVault(),
    });
    await expect(
      malformed.start({
        setupAttemptId: "attempt-12345678",
        expiresAt: new Date(Date.now() + 5_000).toISOString(),
      }),
    ).rejects.toThrow(/protocol|oauth/iu);

    const expired = new ForkedOAuthAttemptFactory({
      adapterPaths,
      helperScriptPath,
      startTimeoutMs: 2_000,
      vault: new EphemeralCredentialVault(),
    });
    await expect(
      expired.start({
        setupAttemptId: "attempt-12345678",
        expiresAt: new Date(Date.now() - 1).toISOString(),
      }),
    ).rejects.toThrow(/expired/iu);
  });

  test("closes the loopback listener after state failure, expiry, and port conflict", async () => {
    const stateFactory = loopbackFactory();
    const stateSession = await stateFactory.start({
      setupAttemptId: "attempt-wrong-state",
      expiresAt: new Date(Date.now() + 5_000).toISOString(),
    });
    await expect(
      stateSession.authorize("code=sensitive-code&state=wrong-state"),
    ).rejects.toThrow(/oauth|failed/iu);
    await expectPortAvailable();

    const expiryFactory = loopbackFactory();
    const expirySession = await expiryFactory.start({
      setupAttemptId: "attempt-loop-expiry",
      expiresAt: new Date(Date.now() + 1_000).toISOString(),
    });
    await expect(expirySession.authorize()).rejects.toThrow(/expired/iu);
    await expectPortAvailable();

    const occupyingServer = http.createServer();
    await listen(occupyingServer);
    try {
      await expect(
        loopbackFactory().start({
          setupAttemptId: "attempt-port-busy",
          expiresAt: new Date(Date.now() + 2_000).toISOString(),
        }),
      ).rejects.toThrow(/oauth|failed/iu);
    } finally {
      await close(occupyingServer);
    }
    await expectPortAvailable();
  });

  test("parent process kill releases helper and localhost listener", async () => {
    const child = spawn(
      process.execPath,
      [fakeOAuthHostPath, builtHelperScriptPath, fakeLoopbackOAuthModulePath],
      {
        serialization: "json",
        stdio: ["ignore", "ignore", "ignore", "ipc"],
        windowsHide: true,
      },
    );
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("host did not become ready")),
        3_000,
      );
      child.once("error", reject);
      child.on("message", (message) => {
        if (
          typeof message === "object" &&
          message !== null &&
          "type" in message &&
          message.type === "ready"
        ) {
          clearTimeout(timeout);
          resolve();
        }
      });
    });
    child.kill();
    await new Promise<void>((resolve) => child.once("exit", () => resolve()));
    await expectPortAvailable();
  });
});

function loopbackFactory() {
  return new ForkedOAuthAttemptFactory({
    adapterPaths: {
      ...adapterPaths,
      oauthModulePath: fakeLoopbackOAuthModulePath,
    },
    helperScriptPath: builtHelperScriptPath,
    startTimeoutMs: 2_000,
    vault: new EphemeralCredentialVault(),
  });
}

async function expectPortAvailable(): Promise<void> {
  await vi.waitFor(
    async () => {
      const server = http.createServer();
      await listen(server);
      await close(server);
    },
    { timeout: 3_000 },
  );
}

function listen(server: http.Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(1455, "localhost", () => resolve());
  });
}

function close(server: http.Server): Promise<void> {
  return new Promise((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
}
