import { beforeEach, describe, expect, test, vi, type Mock } from "vitest";
import {
  ModelVerificationError,
  type ModelSelection,
  type ModelVerificationEvidence,
} from "../src/model-verification.js";
import {
  createModelConfirmation,
  SetupAttemptManager,
  type OAuthAuthorization,
  type OAuthAttemptSession,
} from "../src/setup-attempt.js";

const selection: ModelSelection = {
  model: "gpt-5.6-sol",
  reasoningEffort: "xhigh",
};
const evidence: ModelVerificationEvidence = {
  providerAccepted: true,
  requested: selection,
  sent: selection,
  providerReportedModel: "gpt-5.6-sol-2026-08-01",
};

let now: number;
let oauthSession: OAuthAttemptSession;
let authorize: Mock<(manualCallback?: string) => Promise<OAuthAuthorization>>;
let cancelOAuth: Mock<() => Promise<void>>;
let verify: Mock<
  (
    selection: ModelSelection,
    credentialReference: string,
  ) => Promise<ModelVerificationEvidence>
>;
let persistAuthorizedCredential: Mock<(reference: string) => Promise<void>>;
let completeSetup: Mock<
  (input: {
    credentialReference: string;
    evidence: ModelVerificationEvidence;
    selection: ModelSelection;
  }) => Promise<void>
>;

beforeEach(() => {
  now = Date.parse("2026-08-07T00:00:00.000Z");
  authorize = vi.fn().mockResolvedValue({
    credentialReference: "credential-version-1",
  });
  cancelOAuth = vi.fn().mockResolvedValue(undefined);
  oauthSession = {
    authorizationUrl:
      "https://auth.openai.com/oauth/authorize?state=bound-state",
    authorize,
    cancel: cancelOAuth,
  };
  verify = vi.fn().mockResolvedValue(evidence);
  persistAuthorizedCredential = vi.fn().mockResolvedValue(undefined);
  completeSetup = vi.fn().mockResolvedValue(undefined);
});

describe("first-configuration setup state machine", () => {
  test("binds start confirmation to the exact model and effort", async () => {
    const manager = createManager();

    await expect(
      manager.start({ confirmation: "confirmed", selection }),
    ).rejects.toEqual(expect.objectContaining({ code: "invalid_input" }));

    await expect(
      manager.start({
        confirmation: createModelConfirmation(selection),
        selection,
      }),
    ).resolves.toEqual({
      ok: true,
      status: "setup_pending",
      setupAttemptId: "attempt-12345678",
      authorizationUrl: oauthSession.authorizationUrl,
      expiresAt: "2026-08-07T00:05:00.000Z",
      recovery: { action: "retry" },
    });
  });

  test("rejects bare codes and incomplete manual callbacks before OAuth IPC", async () => {
    const manager = createManager();
    await start(manager);

    for (const callback of [
      "bare-code",
      "code=only",
      "state=only",
      "http://localhost:1455/auth/callback?code=only",
      "https://attacker.example/callback?code=secret&state=bound-state",
      "http://localhost:1455/wrong?code=secret&state=bound-state",
    ]) {
      await expect(
        manager.complete("attempt-12345678", callback),
      ).rejects.toEqual(expect.objectContaining({ code: "invalid_input" }));
    }
    expect(authorize).not.toHaveBeenCalled();
  });

  test("persists OAuth, verifies the exact selection, then completes setup", async () => {
    const manager = createManager();
    await start(manager);
    const callback =
      "http://localhost:1455/auth/callback?code=sensitive&state=bound-state";

    await expect(
      manager.complete("attempt-12345678", callback),
    ).resolves.toEqual({
      ok: true,
      status: "setup_completed",
      model: evidence,
      recovery: { action: "none" },
    });

    expect(authorize).toHaveBeenCalledWith(callback);
    expect(persistAuthorizedCredential).toHaveBeenCalledWith(
      "credential-version-1",
    );
    expect(verify).toHaveBeenCalledWith(
      selection,
      "credential-version-1",
      expect.any(AbortSignal),
    );
    expect(completeSetup).toHaveBeenCalledWith({
      credentialReference: "credential-version-1",
      evidence,
      selection,
    });
    expect(manager.inspect("attempt-12345678")).toEqual(
      expect.objectContaining({ state: "completed" }),
    );
  });

  test("does not initialize or downgrade when verification fails", async () => {
    verify.mockRejectedValueOnce(
      new ModelVerificationError(
        "model_rejected",
        false,
        "provider detail must not become protocol",
      ),
    );
    const manager = createManager();
    await start(manager);

    await expect(manager.complete("attempt-12345678")).resolves.toEqual({
      ok: true,
      status: "verification_failed",
      setupAttemptId: "attempt-12345678",
      failure: {
        code: "model_rejected",
        message: "The selected model and reasoning effort were rejected.",
        retryable: false,
      },
      recovery: { action: "retry" },
    });
    expect(persistAuthorizedCredential).toHaveBeenCalledTimes(1);
    expect(completeSetup).not.toHaveBeenCalled();
    expect(verify).toHaveBeenCalledTimes(1);
    expect(verify).toHaveBeenCalledWith(
      selection,
      "credential-version-1",
      expect.any(AbortSignal),
    );
  });

  test("retries only the original smoke after verification failure", async () => {
    verify
      .mockRejectedValueOnce(
        new ModelVerificationError("provider_failure", true, "temporary"),
      )
      .mockResolvedValueOnce(evidence);
    const manager = createManager();
    await start(manager);
    await manager.complete("attempt-12345678");

    await expect(manager.complete("attempt-12345678")).resolves.toEqual(
      expect.objectContaining({ status: "setup_completed", model: evidence }),
    );
    expect(authorize).toHaveBeenCalledTimes(1);
    expect(persistAuthorizedCredential).toHaveBeenCalledTimes(1);
    expect(verify).toHaveBeenCalledTimes(2);
    expect(verify.mock.calls).toEqual([
      [selection, "credential-version-1", expect.any(AbortSignal)],
      [selection, "credential-version-1", expect.any(AbortSignal)],
    ]);
  });

  test("retries credential persistence without consuming OAuth twice", async () => {
    persistAuthorizedCredential
      .mockRejectedValueOnce(new Error("temporary storage failure"))
      .mockResolvedValueOnce(undefined);
    const manager = createManager();
    await start(manager);

    await expect(manager.complete("attempt-12345678")).rejects.toEqual(
      expect.objectContaining({ code: "oauth_failed" }),
    );
    await expect(manager.complete("attempt-12345678")).resolves.toEqual(
      expect.objectContaining({ status: "setup_completed" }),
    );
    expect(authorize).toHaveBeenCalledTimes(1);
    expect(persistAuthorizedCredential).toHaveBeenCalledTimes(2);
    expect(verify).toHaveBeenCalledTimes(1);
  });

  test("expires and cancels attempts without reusing terminal state", async () => {
    const manager = createManager();
    await start(manager);
    now += 5 * 60_000;

    await expect(manager.complete("attempt-12345678")).rejects.toEqual(
      expect.objectContaining({ code: "attempt_expired" }),
    );
    expect(cancelOAuth).toHaveBeenCalledTimes(1);

    const second = createManager("attempt-abcdefgh");
    await second.start({
      confirmation: createModelConfirmation(selection),
      selection,
    });
    await expect(second.cancel("attempt-abcdefgh")).resolves.toEqual({
      ok: true,
      status: "setup_cancelled",
      setupAttemptId: "attempt-abcdefgh",
      recovery: { action: "none" },
    });
    await expect(second.complete("attempt-abcdefgh")).rejects.toEqual(
      expect.objectContaining({ code: "attempt_state_invalid" }),
    );
  });

  test("preserves helper expiry instead of collapsing it to oauth_failed", async () => {
    authorize.mockRejectedValueOnce(
      Object.assign(new Error("expired"), { code: "attempt_expired" }),
    );
    const manager = createManager();
    await start(manager);

    await expect(manager.complete("attempt-12345678")).rejects.toEqual(
      expect.objectContaining({ code: "attempt_expired" }),
    );
    expect(manager.inspect("attempt-12345678")).toEqual(
      expect.objectContaining({ state: "expired" }),
    );
  });

  test("does not complete setup when verification crosses the attempt expiry", async () => {
    let resolveVerification!: (value: ModelVerificationEvidence) => void;
    verify.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveVerification = resolve;
        }),
    );
    const manager = createManager();
    await start(manager);
    const completion = manager.complete("attempt-12345678");
    await vi.waitFor(() => expect(verify).toHaveBeenCalledTimes(1));
    now += 5 * 60_000;
    resolveVerification(evidence);

    await expect(completion).rejects.toEqual(
      expect.objectContaining({ code: "attempt_expired" }),
    );
    expect(completeSetup).not.toHaveBeenCalled();
  });

  test("evicts an attempt first observed expired after verification", async () => {
    let resolveVerification!: (value: ModelVerificationEvidence) => void;
    verify.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveVerification = resolve;
        }),
    );
    const manager = new SetupAttemptManager({
      completeSetup,
      createId: () => "attempt-12345678",
      maxAttempts: 1,
      now: () => now,
      oauth: { start: vi.fn().mockResolvedValue(oauthSession) },
      persistAuthorizedCredential,
      terminalRetentionMs: 10,
      ttlMs: 5 * 60_000,
      verifier: { verify },
    });
    await start(manager);
    const completion = manager.complete("attempt-12345678");
    await vi.waitFor(() => expect(verify).toHaveBeenCalledTimes(1));
    now += 5 * 60_000;
    resolveVerification(evidence);

    await expect(completion).rejects.toEqual(
      expect.objectContaining({ code: "attempt_expired" }),
    );
    await vi.waitFor(
      () => expect(manager.inspect("attempt-12345678")).toBeUndefined(),
      { timeout: 1_000 },
    );
    await expect(
      manager.start({
        confirmation: createModelConfirmation(selection),
        selection,
      }),
    ).resolves.toEqual(expect.objectContaining({ status: "setup_pending" }));
  });

  test("allows cancellation while verification is in flight", async () => {
    let rejectVerification!: (error: Error) => void;
    verify.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectVerification = reject;
        }),
    );
    const manager = createManager();
    await start(manager);
    const completion = manager.complete("attempt-12345678");
    await vi.waitFor(() => expect(verify).toHaveBeenCalledTimes(1));

    await expect(manager.cancel("attempt-12345678")).resolves.toEqual(
      expect.objectContaining({ status: "setup_cancelled" }),
    );
    rejectVerification(new Error("cancelled"));
    await expect(completion).rejects.toEqual(
      expect.objectContaining({ code: "attempt_state_invalid" }),
    );
    expect(completeSetup).not.toHaveBeenCalled();
    expect(manager.inspect("attempt-12345678")).toEqual(
      expect.objectContaining({ state: "cancelled" }),
    );
  });

  test("rejects cancellation after credential persistence reaches its commit point", async () => {
    let resolvePersistence!: () => void;
    persistAuthorizedCredential.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolvePersistence = resolve;
        }),
    );
    const manager = createManager();
    await start(manager);
    const completion = manager.complete("attempt-12345678");
    await vi.waitFor(() =>
      expect(persistAuthorizedCredential).toHaveBeenCalledTimes(1),
    );

    await expect(manager.cancel("attempt-12345678")).rejects.toEqual(
      expect.objectContaining({ code: "attempt_state_invalid" }),
    );
    resolvePersistence();
    await expect(completion).resolves.toEqual(
      expect.objectContaining({ status: "setup_completed" }),
    );
  });

  test("lets a valid credential commit cross OAuth TTL and continue verification", async () => {
    let resolvePersistence!: () => void;
    persistAuthorizedCredential.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolvePersistence = resolve;
        }),
    );
    const manager = createManager();
    await start(manager);
    const completion = manager.complete("attempt-12345678");
    await vi.waitFor(() =>
      expect(persistAuthorizedCredential).toHaveBeenCalledTimes(1),
    );
    now += 5 * 60_000;
    resolvePersistence();

    await expect(completion).resolves.toEqual(
      expect.objectContaining({ status: "setup_completed" }),
    );
    expect(verify).toHaveBeenCalledTimes(1);
    expect(completeSetup).toHaveBeenCalledTimes(1);
  });

  test("makes final config commit an atomic terminal transition", async () => {
    let resolveConfigCommit!: () => void;
    completeSetup.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveConfigCommit = resolve;
        }),
    );
    const manager = createManager();
    await start(manager);
    const completion = manager.complete("attempt-12345678");
    await vi.waitFor(() => expect(completeSetup).toHaveBeenCalledTimes(1));
    now += 5 * 60_000;

    await expect(manager.cancel("attempt-12345678")).rejects.toEqual(
      expect.objectContaining({ code: "attempt_state_invalid" }),
    );
    resolveConfigCommit();
    await expect(completion).resolves.toEqual(
      expect.objectContaining({ status: "setup_completed" }),
    );
    expect(manager.inspect("attempt-12345678")).toEqual(
      expect.objectContaining({ state: "completed" }),
    );
  });

  test("bounds attempt storage and evicts terminal attempts", async () => {
    const manager = new SetupAttemptManager({
      completeSetup,
      createId: () => "attempt-12345678",
      maxAttempts: 1,
      now: () => now,
      oauth: { start: vi.fn().mockResolvedValue(oauthSession) },
      persistAuthorizedCredential,
      terminalRetentionMs: 10,
      ttlMs: 5 * 60_000,
      verifier: { verify },
    });
    await start(manager);
    await expect(
      manager.start({
        confirmation: createModelConfirmation(selection),
        selection,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "oauth_failed" }));

    await manager.cancel("attempt-12345678");
    await vi.waitFor(
      () => expect(manager.inspect("attempt-12345678")).toBeUndefined(),
      { timeout: 1_000 },
    );
  });

  test("reserves capacity before concurrent setup startup awaits", async () => {
    let releaseCapture!: () => void;
    const capturePersistenceContext = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          releaseCapture = resolve;
        }),
    );
    const manager = new SetupAttemptManager({
      capturePersistenceContext,
      completeSetup,
      createId: () => "attempt-12345678",
      maxAttempts: 1,
      now: () => now,
      oauth: { start: vi.fn().mockResolvedValue(oauthSession) },
      persistAuthorizedCredential,
      verifier: { verify },
    });

    const first = manager.start({
      confirmation: createModelConfirmation(selection),
      selection,
    });
    await vi.waitFor(() =>
      expect(capturePersistenceContext).toHaveBeenCalledTimes(1),
    );
    await expect(
      manager.start({
        confirmation: createModelConfirmation(selection),
        selection,
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "oauth_failed" }));

    releaseCapture();
    await expect(first).resolves.toEqual(
      expect.objectContaining({ status: "setup_pending" }),
    );
  });

  test("evicts cancelled attempts and retries helper cleanup after cleanup failure", async () => {
    cancelOAuth
      .mockRejectedValueOnce(new Error("transient helper cleanup failure"))
      .mockResolvedValue(undefined);
    const manager = new SetupAttemptManager({
      completeSetup,
      createId: () => "attempt-12345678",
      maxAttempts: 1,
      now: () => now,
      oauth: { start: vi.fn().mockResolvedValue(oauthSession) },
      persistAuthorizedCredential,
      terminalRetentionMs: 10,
      verifier: { verify },
    });
    await start(manager);

    await expect(manager.cancel("attempt-12345678")).rejects.toEqual(
      expect.objectContaining({ code: "oauth_failed" }),
    );
    await vi.waitFor(
      () => {
        expect(cancelOAuth).toHaveBeenCalledTimes(2);
        expect(manager.inspect("attempt-12345678")).toBeUndefined();
      },
      { timeout: 1_000 },
    );
    await expect(
      manager.start({
        confirmation: createModelConfirmation(selection),
        selection,
      }),
    ).resolves.toEqual(expect.objectContaining({ status: "setup_pending" }));
  });
});

function createManager(id = "attempt-12345678"): SetupAttemptManager {
  return new SetupAttemptManager({
    completeSetup,
    createId: () => id,
    now: () => now,
    oauth: { start: vi.fn().mockResolvedValue(oauthSession) },
    persistAuthorizedCredential,
    ttlMs: 5 * 60_000,
    verifier: { verify },
  });
}

async function start(manager: SetupAttemptManager): Promise<void> {
  await manager.start({
    confirmation: createModelConfirmation(selection),
    selection,
  });
}
