import { randomUUID } from "node:crypto";
import { modelSelectionSchema } from "./contracts.js";
import {
  ModelVerificationError,
  type ModelSelection,
  type ModelVerificationEvidence,
  type ModelVerificationFailureCode,
  type ModelVerifier,
} from "./model-verification.js";

export type OAuthAuthorization = { credentialReference: string };

export interface OAuthAttemptSession {
  authorizationUrl: string;
  authorize(manualCallback?: string): Promise<OAuthAuthorization>;
  cancel(): Promise<void>;
}

export interface OAuthAttemptFactory {
  start(input: {
    expiresAt: string;
    setupAttemptId: string;
  }): Promise<OAuthAttemptSession>;
}

type AttemptState =
  | "oauth_pending"
  | "authorized"
  | "verifying"
  | "verification_failed"
  | "completed"
  | "cancelled"
  | "expired";

type SetupAttempt = {
  abortController: AbortController;
  busy: boolean;
  commitPhase?: "credentials" | "config";
  credentialPersisted: boolean;
  credentialReference?: string;
  expiresAtMs: number;
  expiryTimer: ReturnType<typeof setTimeout>;
  persistenceContext?: unknown;
  selection: ModelSelection;
  session: OAuthAttemptSession;
  setupAttemptId: string;
  state: AttemptState;
  terminalCleanupStarted: boolean;
  terminalRemovalScheduled: boolean;
};

type SetupAttemptManagerOptions = {
  capturePersistenceContext?(): Promise<unknown>;
  completeSetup(input: {
    credentialReference: string;
    evidence: ModelVerificationEvidence;
    persistenceContext?: unknown;
    selection: ModelSelection;
  }): Promise<void>;
  createId?(): string;
  maxAttempts?: number;
  now?(): number;
  oauth: OAuthAttemptFactory;
  persistAuthorizedCredential(
    reference: string,
    persistenceContext?: unknown,
  ): Promise<void>;
  runExclusive?<T>(operation: () => Promise<T>): Promise<T>;
  terminalRetentionMs?: number;
  ttlMs?: number;
  verifier: ModelVerifier;
};

export type SetupCompleteResult =
  | {
      failure: {
        code: ModelVerificationFailureCode;
        message: string;
        retryable: boolean;
      };
      ok: true;
      recovery: { action: "retry" };
      setupAttemptId: string;
      status: "verification_failed";
    }
  | {
      model: ModelVerificationEvidence;
      ok: true;
      recovery: { action: "none" };
      status: "setup_completed";
    };

export function createModelConfirmation(selection: ModelSelection): string {
  return `confirm-model:${selection.model}:${selection.reasoningEffort}`;
}

export class SetupAttemptError extends Error {
  constructor(
    readonly code:
      | "attempt_not_found"
      | "attempt_expired"
      | "attempt_state_invalid"
      | "invalid_input"
      | "oauth_failed",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "SetupAttemptError";
  }
}

export class SetupAttemptManager {
  private readonly attempts = new Map<string, SetupAttempt>();
  private readonly pendingAttemptIds = new Set<string>();
  private readonly capturePersistenceContext: () => Promise<unknown>;
  private readonly completeSetupCallback: SetupAttemptManagerOptions["completeSetup"];
  private readonly createId: () => string;
  private readonly maxAttempts: number;
  private readonly now: () => number;
  private readonly oauth: OAuthAttemptFactory;
  private readonly persistAuthorizedCredential: SetupAttemptManagerOptions["persistAuthorizedCredential"];
  private readonly runExclusive: <T>(operation: () => Promise<T>) => Promise<T>;
  private readonly terminalRetentionMs: number;
  private readonly ttlMs: number;
  private readonly verifier: ModelVerifier;

  constructor(options: SetupAttemptManagerOptions) {
    this.capturePersistenceContext =
      options.capturePersistenceContext ?? (async () => undefined);
    this.completeSetupCallback = options.completeSetup;
    this.createId = options.createId ?? (() => `attempt-${randomUUID()}`);
    this.maxAttempts = options.maxAttempts ?? 32;
    this.now = options.now ?? Date.now;
    this.oauth = options.oauth;
    this.persistAuthorizedCredential = options.persistAuthorizedCredential;
    this.runExclusive =
      options.runExclusive ?? (async (operation) => operation());
    this.terminalRetentionMs = options.terminalRetentionMs ?? 60_000;
    this.ttlMs = options.ttlMs ?? 5 * 60_000;
    this.verifier = options.verifier;
  }

  async start(input: {
    confirmation: string;
    selection: ModelSelection;
  }): Promise<{
    authorizationUrl: string;
    expiresAt: string;
    ok: true;
    recovery: { action: "retry" };
    setupAttemptId: string;
    status: "setup_pending";
  }> {
    const parsedSelection = modelSelectionSchema.safeParse(input.selection);
    if (
      !parsedSelection.success ||
      input.confirmation !== createModelConfirmation(parsedSelection.data)
    ) {
      throw new SetupAttemptError(
        "invalid_input",
        "Setup confirmation must bind the exact model and reasoning effort.",
      );
    }
    if (this.attempts.size + this.pendingAttemptIds.size >= this.maxAttempts) {
      throw new SetupAttemptError(
        "oauth_failed",
        "Too many setup attempts are active or awaiting terminal cleanup.",
      );
    }

    const setupAttemptId = this.createId();
    if (
      !/^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/u.test(setupAttemptId) ||
      this.attempts.has(setupAttemptId) ||
      this.pendingAttemptIds.has(setupAttemptId)
    ) {
      throw new SetupAttemptError(
        "invalid_input",
        "Setup attempt identifier generation failed.",
      );
    }
    this.pendingAttemptIds.add(setupAttemptId);
    try {
      const expiresAtMs = this.now() + this.ttlMs;
      const expiresAt = new Date(expiresAtMs).toISOString();
      const persistenceContext = await this.capturePersistenceContext();
      let session: OAuthAttemptSession;
      try {
        session = await this.oauth.start({ expiresAt, setupAttemptId });
      } catch {
        throw new SetupAttemptError(
          "oauth_failed",
          "Could not start the ChatGPT OAuth helper.",
        );
      }
      if (!isAuthorizationUrl(session.authorizationUrl)) {
        await session.cancel().catch(() => undefined);
        throw new SetupAttemptError(
          "oauth_failed",
          "The ChatGPT OAuth helper returned an invalid authorization URL.",
        );
      }

      this.attempts.set(setupAttemptId, {
        abortController: new AbortController(),
        busy: false,
        credentialPersisted: false,
        expiresAtMs,
        expiryTimer: this.createExpiryTimer(setupAttemptId, expiresAtMs),
        persistenceContext,
        selection: parsedSelection.data,
        session,
        setupAttemptId,
        state: "oauth_pending",
        terminalCleanupStarted: false,
        terminalRemovalScheduled: false,
      });

      return {
        authorizationUrl: session.authorizationUrl,
        expiresAt,
        ok: true,
        recovery: { action: "retry" },
        setupAttemptId,
        status: "setup_pending",
      };
    } finally {
      this.pendingAttemptIds.delete(setupAttemptId);
    }
  }

  async complete(
    setupAttemptId: string,
    manualCallback?: string,
  ): Promise<SetupCompleteResult> {
    return this.runExclusive(() =>
      this.completeExclusive(setupAttemptId, manualCallback),
    );
  }

  private async completeExclusive(
    setupAttemptId: string,
    manualCallback?: string,
  ): Promise<SetupCompleteResult> {
    const attempt = await this.getActiveAttempt(setupAttemptId);
    if (attempt.busy || attempt.state === "verifying") {
      throw new SetupAttemptError(
        "attempt_state_invalid",
        "The setup attempt is already being completed.",
      );
    }
    if (
      attempt.state === "completed" ||
      attempt.state === "cancelled" ||
      attempt.state === "expired"
    ) {
      throw new SetupAttemptError(
        "attempt_state_invalid",
        "The setup attempt is already terminal.",
      );
    }

    attempt.busy = true;
    try {
      if (attempt.state === "oauth_pending") {
        if (
          manualCallback !== undefined &&
          !isCompleteManualCallback(manualCallback)
        ) {
          throw new SetupAttemptError(
            "invalid_input",
            "Manual OAuth completion requires a full callback URL or query containing code and state.",
          );
        }

        let authorization: OAuthAuthorization;
        try {
          authorization = await attempt.session.authorize(manualCallback);
        } catch (error) {
          if (hasErrorCode(error, "attempt_expired")) {
            await this.markExpired(attempt);
            throw new SetupAttemptError(
              "attempt_expired",
              "The setup attempt has expired.",
            );
          }
          this.assertContinuable(attempt);
          throw new SetupAttemptError(
            "oauth_failed",
            "ChatGPT OAuth authorization did not complete.",
          );
        }
        if (!isCredentialReference(authorization.credentialReference)) {
          throw new SetupAttemptError(
            "oauth_failed",
            "ChatGPT OAuth returned an invalid credential reference.",
          );
        }

        attempt.credentialReference = authorization.credentialReference;
        attempt.state = "authorized";
        this.assertContinuable(attempt);
      } else if (manualCallback !== undefined) {
        throw new SetupAttemptError(
          "attempt_state_invalid",
          "A manual callback cannot be resubmitted after authorization.",
        );
      }

      const credentialReference = attempt.credentialReference;
      if (!credentialReference) {
        throw new SetupAttemptError(
          "attempt_state_invalid",
          "The setup attempt has no authorized credential.",
        );
      }
      if (!attempt.credentialPersisted) {
        this.beginCommit(attempt, "credentials");
        try {
          if (attempt.persistenceContext === undefined) {
            await this.persistAuthorizedCredential(credentialReference);
          } else {
            await this.persistAuthorizedCredential(
              credentialReference,
              attempt.persistenceContext,
            );
          }
          attempt.credentialPersisted = true;
        } catch (error) {
          this.endCredentialCommit(attempt);
          if (error instanceof SetupAttemptError) throw error;
          throw new SetupAttemptError(
            "oauth_failed",
            "Authorized ChatGPT credentials could not be persisted.",
          );
        }
        this.endCredentialCommit(attempt);
        this.assertContinuable(attempt);
      }

      attempt.state = "verifying";
      try {
        const model = await this.verifier.verify(
          attempt.selection,
          credentialReference,
          attempt.abortController.signal,
        );
        this.assertContinuable(attempt);
        assertEvidenceMatches(attempt.selection, model);
        this.beginCommit(attempt, "config");
        try {
          await this.completeSetupCallback({
            credentialReference,
            evidence: model,
            ...(attempt.persistenceContext === undefined
              ? {}
              : { persistenceContext: attempt.persistenceContext }),
            selection: attempt.selection,
          });
        } catch (error) {
          attempt.commitPhase = undefined;
          this.rescheduleExpiry(attempt);
          throw error;
        }
        attempt.state = "completed";
        attempt.commitPhase = undefined;
        this.scheduleTerminalRemoval(attempt);
        return {
          model,
          ok: true,
          recovery: { action: "none" },
          status: "setup_completed",
        };
      } catch (error) {
        this.assertContinuable(attempt);
        attempt.state = "verification_failed";
        const failure = toVerificationFailure(error);
        return {
          failure,
          ok: true,
          recovery: { action: "retry" },
          setupAttemptId,
          status: "verification_failed",
        };
      }
    } finally {
      attempt.busy = false;
    }
  }

  async cancel(setupAttemptId: string): Promise<{
    ok: true;
    recovery: { action: "none" };
    setupAttemptId: string;
    status: "setup_cancelled";
  }> {
    const attempt = await this.getActiveAttempt(setupAttemptId);
    if (
      attempt.commitPhase !== undefined ||
      attempt.state === "completed" ||
      attempt.state === "cancelled" ||
      attempt.state === "expired"
    ) {
      throw new SetupAttemptError(
        "attempt_state_invalid",
        "The setup attempt cannot be cancelled in its current state.",
      );
    }
    attempt.state = "cancelled";
    attempt.abortController.abort();
    clearTimeout(attempt.expiryTimer);
    let cleanupError: unknown;
    try {
      await this.cancelSessionWithRetry(attempt.session);
    } catch (error) {
      cleanupError = error;
    } finally {
      this.scheduleTerminalRemoval(attempt);
    }
    if (cleanupError !== undefined) {
      throw new SetupAttemptError(
        "oauth_failed",
        "The setup attempt was cancelled but helper cleanup failed.",
        { cause: cleanupError },
      );
    }
    return {
      ok: true,
      recovery: { action: "none" },
      setupAttemptId,
      status: "setup_cancelled",
    };
  }

  inspect(setupAttemptId: string):
    | {
        expiresAt: string;
        selection: ModelSelection;
        state: AttemptState;
      }
    | undefined {
    const attempt = this.attempts.get(setupAttemptId);
    return attempt
      ? {
          expiresAt: new Date(attempt.expiresAtMs).toISOString(),
          selection: attempt.selection,
          state: attempt.state,
        }
      : undefined;
  }

  private async getActiveAttempt(
    setupAttemptId: string,
  ): Promise<SetupAttempt> {
    const attempt = this.attempts.get(setupAttemptId);
    if (!attempt) {
      throw new SetupAttemptError(
        "attempt_not_found",
        "The setup attempt was not found.",
      );
    }
    if (attempt.state === "expired") {
      throw new SetupAttemptError(
        "attempt_expired",
        "The setup attempt has expired.",
      );
    }
    if (attempt.commitPhase !== undefined) {
      return attempt;
    }
    if (
      this.now() >= attempt.expiresAtMs &&
      attempt.state !== "completed" &&
      attempt.state !== "cancelled"
    ) {
      await this.markExpired(attempt);
      throw new SetupAttemptError(
        "attempt_expired",
        "The setup attempt has expired.",
      );
    }
    return attempt;
  }

  private assertContinuable(attempt: SetupAttempt): void {
    if (attempt.state === "cancelled") {
      throw new SetupAttemptError(
        "attempt_state_invalid",
        "The setup attempt was cancelled while work was in progress.",
      );
    }
    if (attempt.state === "expired" || this.now() >= attempt.expiresAtMs) {
      this.transitionToExpired(attempt);
      throw new SetupAttemptError(
        "attempt_expired",
        "The setup attempt has expired.",
      );
    }
  }

  private beginCommit(
    attempt: SetupAttempt,
    phase: "credentials" | "config",
  ): void {
    this.assertContinuable(attempt);
    if (attempt.commitPhase !== undefined) {
      throw new SetupAttemptError(
        "attempt_state_invalid",
        "The setup attempt already has a commit in progress.",
      );
    }
    attempt.commitPhase = phase;
    clearTimeout(attempt.expiryTimer);
  }

  private endCredentialCommit(attempt: SetupAttempt): void {
    if (attempt.commitPhase === "credentials") {
      attempt.commitPhase = undefined;
      if (attempt.credentialPersisted && this.now() >= attempt.expiresAtMs) {
        attempt.expiresAtMs = this.now() + this.ttlMs;
      }
      this.rescheduleExpiry(attempt);
    }
  }

  private rescheduleExpiry(attempt: SetupAttempt): void {
    clearTimeout(attempt.expiryTimer);
    if (
      attempt.state !== "completed" &&
      attempt.state !== "cancelled" &&
      attempt.state !== "expired" &&
      this.now() < attempt.expiresAtMs
    ) {
      attempt.expiryTimer = this.createExpiryTimerForAttempt(attempt);
    }
  }

  private createExpiryTimer(
    setupAttemptId: string,
    expiresAtMs: number,
  ): ReturnType<typeof setTimeout> {
    const timer = setTimeout(
      () => {
        const attempt = this.attempts.get(setupAttemptId);
        if (
          attempt &&
          attempt.commitPhase === undefined &&
          attempt.state !== "completed" &&
          attempt.state !== "cancelled" &&
          attempt.state !== "expired"
        ) {
          void this.markExpired(attempt);
        }
      },
      Math.max(1, expiresAtMs - this.now()),
    );
    timer.unref();
    return timer;
  }

  private createExpiryTimerForAttempt(
    attempt: SetupAttempt,
  ): ReturnType<typeof setTimeout> {
    const timer = setTimeout(
      () => {
        if (
          attempt.commitPhase === undefined &&
          attempt.state !== "completed" &&
          attempt.state !== "cancelled" &&
          attempt.state !== "expired"
        ) {
          void this.markExpired(attempt);
        }
      },
      Math.max(1, attempt.expiresAtMs - this.now()),
    );
    timer.unref();
    return timer;
  }

  private async markExpired(attempt: SetupAttempt): Promise<void> {
    if (attempt.commitPhase !== undefined) return;
    this.transitionToExpired(attempt);
  }

  private transitionToExpired(attempt: SetupAttempt): void {
    attempt.state = "expired";
    attempt.abortController.abort();
    clearTimeout(attempt.expiryTimer);
    this.scheduleTerminalRemoval(attempt);
    if (!attempt.terminalCleanupStarted) {
      attempt.terminalCleanupStarted = true;
      void this.cancelSessionWithRetry(attempt.session).catch(() => undefined);
    }
  }

  private async cancelSessionWithRetry(
    session: OAuthAttemptSession,
  ): Promise<void> {
    try {
      await session.cancel();
    } catch (error) {
      this.scheduleSessionCancelRetry(session, 3);
      throw error;
    }
  }

  private scheduleSessionCancelRetry(
    session: OAuthAttemptSession,
    remainingAttempts: number,
  ): void {
    if (remainingAttempts <= 0) return;
    const timer = setTimeout(() => {
      void session.cancel().catch(() => {
        this.scheduleSessionCancelRetry(session, remainingAttempts - 1);
      });
    }, 25);
    timer.unref();
  }

  private scheduleTerminalRemoval(attempt: SetupAttempt): void {
    if (attempt.terminalRemovalScheduled) return;
    attempt.terminalRemovalScheduled = true;
    const timer = setTimeout(() => {
      if (this.attempts.get(attempt.setupAttemptId) === attempt) {
        this.attempts.delete(attempt.setupAttemptId);
      }
    }, this.terminalRetentionMs);
    timer.unref();
  }
}

function isAuthorizationUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.searchParams.has("state");
  } catch {
    return false;
  }
}

function isCompleteManualCallback(value: string): boolean {
  const trimmed = value.trim();
  let parameters: URLSearchParams;
  if (/^https?:\/\//iu.test(trimmed)) {
    try {
      const callbackUrl = new URL(trimmed);
      if (
        callbackUrl.protocol !== "http:" ||
        callbackUrl.hostname !== "localhost" ||
        callbackUrl.port !== "1455" ||
        callbackUrl.pathname !== "/auth/callback"
      ) {
        return false;
      }
      parameters = callbackUrl.searchParams;
    } catch {
      return false;
    }
  } else if (trimmed.startsWith("?") || trimmed.includes("=")) {
    parameters = new URLSearchParams(
      trimmed.startsWith("?") ? trimmed.slice(1) : trimmed,
    );
  } else {
    return false;
  }
  return Boolean(parameters.get("code") && parameters.get("state"));
}

function isCredentialReference(value: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._:-]{7,255}$/u.test(value);
}

function assertEvidenceMatches(
  selection: ModelSelection,
  evidence: ModelVerificationEvidence,
): void {
  for (const observed of [evidence.requested, evidence.sent]) {
    if (
      observed.model !== selection.model ||
      observed.reasoningEffort !== selection.reasoningEffort
    ) {
      throw new ModelVerificationError(
        "internal_error",
        false,
        "Model verification evidence did not match the requested selection.",
      );
    }
  }
  if (evidence.providerAccepted !== true) {
    throw new ModelVerificationError(
      "model_rejected",
      false,
      "Provider did not accept the requested model.",
    );
  }
}

function toVerificationFailure(error: unknown): {
  code: ModelVerificationFailureCode;
  message: string;
  retryable: boolean;
} {
  if (error instanceof ModelVerificationError) {
    return {
      code: error.code,
      message:
        error.code === "model_rejected"
          ? "The selected model and reasoning effort were rejected."
          : "The selected model and reasoning effort could not be verified.",
      retryable: error.retryable,
    };
  }
  return {
    code: "internal_error",
    message: "The selected model and reasoning effort could not be verified.",
    retryable: true,
  };
}

function hasErrorCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === code
  );
}
