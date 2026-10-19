import { spawn, type ChildProcess } from "node:child_process";
import { lstat } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { OpenWikiAdapterPaths } from "./openwiki-adapter.js";
import type { EphemeralCredentialVault } from "./auth.js";
import type {
  OAuthAttemptFactory,
  OAuthAttemptSession,
  OAuthAuthorization,
} from "./setup-attempt.js";

const credentialMessageSchema = z.strictObject({
  access: z.string().min(1).max(1_000_000),
  accountId: z.string().min(1).max(4_096),
  email: z.string().min(1).max(4_096).nullable().optional(),
  expiresAtMs: z.number().int().positive().finite(),
  planType: z.string().min(1).max(256).nullable().optional(),
  refresh: z.string().min(1).max(1_000_000),
});
const helperMessageSchema = z.discriminatedUnion("type", [
  z.strictObject({
    authorizationUrl: z.string().url().max(8_192),
    type: z.literal("ready"),
  }),
  z.strictObject({
    credential: credentialMessageSchema,
    type: z.literal("authorized"),
  }),
  z.strictObject({
    code: z.enum(["oauth_failed", "attempt_expired"]),
    type: z.literal("failure"),
  }),
]);

type ForkedOAuthAttemptFactoryOptions = {
  adapterPaths: OpenWikiAdapterPaths;
  heartbeatMs?: number;
  helperScriptPath?: string;
  startTimeoutMs?: number;
  vault: EphemeralCredentialVault;
};

export class OAuthHelperProcessError extends Error {
  constructor(
    readonly code: "oauth_failed" | "attempt_expired",
    message: string,
  ) {
    super(message);
    this.name = "OAuthHelperProcessError";
  }
}

export class ForkedOAuthAttemptFactory implements OAuthAttemptFactory {
  private readonly adapterPaths: OpenWikiAdapterPaths;
  private readonly heartbeatMs: number;
  private readonly helperScriptPath: string;
  private readonly startTimeoutMs: number;
  private readonly vault: EphemeralCredentialVault;

  constructor(options: ForkedOAuthAttemptFactoryOptions) {
    this.adapterPaths = options.adapterPaths;
    this.heartbeatMs = options.heartbeatMs ?? 15_000;
    this.helperScriptPath =
      options.helperScriptPath ??
      path.resolve(import.meta.dirname, "oauth-helper-child.js");
    this.startTimeoutMs = options.startTimeoutMs ?? 10_000;
    this.vault = options.vault;
  }

  async start(input: {
    expiresAt: string;
    setupAttemptId: string;
  }): Promise<OAuthAttemptSession> {
    if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/u.test(input.setupAttemptId)) {
      throw new OAuthHelperProcessError(
        "oauth_failed",
        "OAuth helper received an invalid setup attempt identifier.",
      );
    }
    const expiresAtMs = Date.parse(input.expiresAt);
    if (!Number.isFinite(expiresAtMs) || expiresAtMs <= Date.now()) {
      throw new OAuthHelperProcessError(
        "attempt_expired",
        "OAuth setup attempt has expired.",
      );
    }
    if (!path.isAbsolute(this.helperScriptPath)) {
      throw new OAuthHelperProcessError(
        "oauth_failed",
        "OAuth helper script path is invalid.",
      );
    }
    let helperStat;
    try {
      helperStat = await lstat(this.helperScriptPath);
    } catch {
      throw new OAuthHelperProcessError(
        "oauth_failed",
        "OAuth helper script is missing.",
      );
    }
    if (!helperStat.isFile() || helperStat.isSymbolicLink()) {
      throw new OAuthHelperProcessError(
        "oauth_failed",
        "OAuth helper script must be a regular non-link file.",
      );
    }

    const child = spawn(process.execPath, [this.helperScriptPath], {
      detached: false,
      env: createHelperEnvironment(),
      serialization: "json",
      stdio: ["ignore", "ignore", "ignore", "ipc"],
      windowsHide: true,
    });
    const session = new ForkedOAuthSession({
      child,
      expiresAtMs,
      heartbeatMs: this.heartbeatMs,
      startTimeoutMs: this.startTimeoutMs,
      vault: this.vault,
    });

    try {
      child.send({
        type: "initialize",
        expiresAt: input.expiresAt,
        oauthModulePath: this.adapterPaths.oauthModulePath,
        setupAttemptId: input.setupAttemptId,
      });
      await session.waitUntilReady();
      return session;
    } catch (error) {
      await session.cancel().catch(() => undefined);
      throw error;
    }
  }
}

class ForkedOAuthSession implements OAuthAttemptSession {
  authorizationUrl = "";
  private authorizationReference: string | undefined;
  private authorizationWaiter: Deferred<OAuthAuthorization> | undefined;
  private readonly child: ChildProcess;
  private readonly expiryTimer: ReturnType<typeof setTimeout>;
  private readonly heartbeatTimer: ReturnType<typeof setInterval>;
  private readonly onChildError = () => {
    this.fail(
      new OAuthHelperProcessError(
        "oauth_failed",
        "OAuth helper process failed.",
      ),
    );
  };
  private readonly onChildExit = () => {
    if (!this.terminal && this.authorizationReference === undefined) {
      this.fail(
        new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper exited before authorization completed.",
        ),
      );
    }
  };
  private readonly onChildMessage = (message: unknown) =>
    this.onMessage(message);
  private failure: OAuthHelperProcessError | undefined;
  private readonly ready = deferred<void>();
  private readonly startTimer: ReturnType<typeof setTimeout>;
  private terminal = false;
  private readonly vault: EphemeralCredentialVault;

  constructor(options: {
    child: ChildProcess;
    expiresAtMs: number;
    heartbeatMs: number;
    startTimeoutMs: number;
    vault: EphemeralCredentialVault;
  }) {
    this.child = options.child;
    this.vault = options.vault;
    this.startTimer = setTimeout(() => {
      this.fail(
        new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper did not become ready in time.",
        ),
      );
    }, options.startTimeoutMs);
    this.expiryTimer = setTimeout(
      () => {
        this.expire(
          new OAuthHelperProcessError(
            "attempt_expired",
            "OAuth setup attempt has expired.",
          ),
        );
      },
      Math.max(1, options.expiresAtMs - Date.now()),
    );
    this.heartbeatTimer = setInterval(() => {
      if (!this.terminal && this.child.connected) {
        this.child.send({ type: "heartbeat" }, () => undefined);
      }
    }, options.heartbeatMs);
    this.heartbeatTimer.unref();

    this.child.on("message", this.onChildMessage);
    this.child.once("error", this.onChildError);
    this.child.once("exit", this.onChildExit);
  }

  async waitUntilReady(): Promise<void> {
    return this.ready.promise;
  }

  async authorize(manualCallback?: string): Promise<OAuthAuthorization> {
    if (this.failure) {
      throw this.failure;
    }
    if (this.terminal && this.authorizationReference === undefined) {
      throw new OAuthHelperProcessError(
        "oauth_failed",
        "OAuth helper session is terminal.",
      );
    }
    if (this.authorizationReference) {
      clearTimeout(this.expiryTimer);
      return { credentialReference: this.authorizationReference };
    }
    if (this.authorizationWaiter) {
      throw new OAuthHelperProcessError(
        "oauth_failed",
        "OAuth helper authorization is already pending.",
      );
    }

    const waiter = deferred<OAuthAuthorization>();
    this.authorizationWaiter = waiter;
    if (manualCallback !== undefined) {
      if (!this.child.connected) {
        this.fail(
          new OAuthHelperProcessError(
            "oauth_failed",
            "OAuth helper IPC is closed.",
          ),
        );
      } else {
        this.child.send(
          { callback: manualCallback, type: "complete" },
          (error) => {
            if (!error) return;
            this.fail(
              new OAuthHelperProcessError(
                "oauth_failed",
                "OAuth helper IPC send failed.",
              ),
            );
          },
        );
      }
    }
    const authorization = await waiter.promise;
    clearTimeout(this.expiryTimer);
    return authorization;
  }

  async cancel(): Promise<void> {
    if (this.authorizationReference !== undefined) {
      this.vault.discard(this.authorizationReference);
      this.authorizationReference = undefined;
    }
    if (!this.terminal) {
      this.terminal = true;
      this.ready.reject(
        new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper session was cancelled.",
        ),
      );
      this.authorizationWaiter?.reject(
        new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper session was cancelled.",
        ),
      );
    }
    this.clearTimers();
    this.disposeChildListeners();
    this.authorizationWaiter = undefined;
    if (this.child.connected) {
      this.child.send({ type: "cancel" }, () => undefined);
    }
    await waitForExit(this.child, 500);
    if (this.child.exitCode === null && this.child.signalCode === null) {
      if (!this.child.kill()) {
        throw new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper process could not be terminated.",
        );
      }
      await waitForExit(this.child, 500);
    }
    if (this.child.exitCode === null && this.child.signalCode === null) {
      throw new OAuthHelperProcessError(
        "oauth_failed",
        "OAuth helper process did not terminate.",
      );
    }
  }

  private onMessage(message: unknown): void {
    if (this.terminal) {
      return;
    }
    const parsed = helperMessageSchema.safeParse(message);
    if (!parsed.success) {
      this.fail(
        new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper protocol message was invalid.",
        ),
      );
      return;
    }

    if (parsed.data.type === "ready") {
      if (
        this.authorizationUrl !== "" ||
        !isSafeAuthorizationUrl(parsed.data.authorizationUrl)
      ) {
        this.fail(
          new OAuthHelperProcessError(
            "oauth_failed",
            "OAuth helper readiness message was invalid.",
          ),
        );
        return;
      }
      this.authorizationUrl = parsed.data.authorizationUrl;
      clearTimeout(this.startTimer);
      this.ready.resolve();
      return;
    }

    if (parsed.data.type === "failure") {
      this.fail(
        new OAuthHelperProcessError(
          parsed.data.code,
          parsed.data.code === "attempt_expired"
            ? "OAuth setup attempt has expired."
            : "OAuth authorization failed.",
        ),
      );
      return;
    }

    if (this.authorizationReference !== undefined) {
      this.fail(
        new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper sent credentials more than once.",
        ),
      );
      return;
    }
    if (this.authorizationUrl === "") {
      this.fail(
        new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper sent credentials before becoming ready.",
        ),
      );
      return;
    }
    try {
      this.authorizationReference = this.vault.stage(parsed.data.credential);
    } catch {
      this.fail(
        new OAuthHelperProcessError(
          "oauth_failed",
          "OAuth helper returned invalid credentials.",
        ),
      );
      return;
    }
    const authorization = {
      credentialReference: this.authorizationReference,
    };
    this.authorizationWaiter?.resolve(authorization);
    this.authorizationWaiter = undefined;
    this.terminal = true;
    clearTimeout(this.startTimer);
    clearInterval(this.heartbeatTimer);
    this.disposeChildListeners();
    if (this.child.connected) {
      this.child.disconnect();
    }
  }

  private expire(error: OAuthHelperProcessError): void {
    if (this.authorizationReference !== undefined) {
      this.vault.discard(this.authorizationReference);
      this.authorizationReference = undefined;
    }
    this.failure = error;
    this.terminal = true;
    this.clearTimers();
    this.disposeChildListeners();
    this.ready.reject(error);
    this.authorizationWaiter?.reject(error);
    this.authorizationWaiter = undefined;
    if (this.child.connected) {
      this.child.disconnect();
    }
    if (this.child.exitCode === null && this.child.signalCode === null) {
      this.child.kill();
    }
  }

  private fail(error: OAuthHelperProcessError): void {
    if (this.terminal) {
      return;
    }
    this.failure = error;
    this.terminal = true;
    if (this.authorizationReference !== undefined) {
      this.vault.discard(this.authorizationReference);
      this.authorizationReference = undefined;
    }
    this.clearTimers();
    this.disposeChildListeners();
    this.ready.reject(error);
    this.authorizationWaiter?.reject(error);
    this.authorizationWaiter = undefined;
    if (this.child.connected) {
      this.child.disconnect();
    }
    if (this.child.exitCode === null && this.child.signalCode === null) {
      this.child.kill();
    }
  }

  private clearTimers(): void {
    clearTimeout(this.startTimer);
    clearTimeout(this.expiryTimer);
    clearInterval(this.heartbeatTimer);
  }

  private disposeChildListeners(): void {
    this.child.off("message", this.onChildMessage);
    this.child.off("error", this.onChildError);
    this.child.off("exit", this.onChildExit);
  }
}

function createHelperEnvironment(): NodeJS.ProcessEnv {
  const allowedKeys = [
    "ComSpec",
    "PATH",
    "Path",
    "PATHEXT",
    "SystemRoot",
    "TEMP",
    "TMP",
    "WINDIR",
  ] as const;
  const environment: NodeJS.ProcessEnv = {};
  for (const key of allowedKeys) {
    const value = process.env[key];
    if (value !== undefined) {
      environment[key] = value;
    }
  }
  return environment;
}

function isSafeAuthorizationUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      url.hostname === "auth.openai.com" &&
      url.pathname === "/oauth/authorize" &&
      url.searchParams.has("state")
    );
  } catch {
    return false;
  }
}

type Deferred<T> = {
  promise: Promise<T>;
  reject(error: unknown): void;
  resolve(value: T): void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

function waitForExit(child: ChildProcess, timeoutMs: number): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const timeout = setTimeout(resolve, timeoutMs);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolve();
    });
  });
}
