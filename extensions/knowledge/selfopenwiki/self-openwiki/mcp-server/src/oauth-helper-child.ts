import { lstat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

type ChatGptLoginHandle = {
  submitManual(input: string): string | null;
};

type ChatGptCredential = {
  access: string;
  accountId: string;
  email?: string | null;
  expiresAtMs: number;
  planType?: string | null;
  refresh: string;
};

type OAuthModule = {
  loginWithChatGPT(
    openUrl: (url: string) => void,
    onReady?: (handle: ChatGptLoginHandle) => void,
  ): Promise<ChatGptCredential>;
};

const LEASE_MS = 45_000;
let initialized = false;
let manualCallbackConsumed = false;
let loginHandle: ChatGptLoginHandle | undefined;
let terminal = false;
let expiryTimer: ReturnType<typeof setTimeout> | undefined;
let leaseTimer: ReturnType<typeof setTimeout> | undefined;

process.on("message", (message: unknown) => {
  void handleMessage(message);
});
process.once("disconnect", exitImmediately);

async function handleMessage(message: unknown): Promise<void> {
  if (terminal || !isRecord(message) || typeof message.type !== "string") {
    return;
  }

  if (message.type === "initialize") {
    if (initialized || !isInitializeMessage(message)) {
      failAndExit();
      return;
    }
    initialized = true;
    const expiresAtMs = Date.parse(message.expiresAt);
    if (!Number.isFinite(expiresAtMs) || expiresAtMs <= Date.now()) {
      failAndExit("attempt_expired");
      return;
    }
    expiryTimer = setTimeout(
      () => failAndExit("attempt_expired"),
      expiresAtMs - Date.now(),
    );
    resetLease();
    void beginLogin(message.oauthModulePath);
    return;
  }

  if (!initialized) {
    failAndExit();
    return;
  }
  resetLease();

  if (message.type === "heartbeat") {
    return;
  }
  if (message.type === "cancel") {
    exitImmediately();
    return;
  }
  if (message.type === "complete") {
    if (
      manualCallbackConsumed ||
      typeof message.callback !== "string" ||
      !isCompleteManualCallback(message.callback) ||
      !loginHandle
    ) {
      failAndExit();
      return;
    }
    manualCallbackConsumed = true;
    const error = loginHandle.submitManual(message.callback);
    if (error !== null) {
      failAndExit();
    }
    return;
  }

  failAndExit();
}

async function beginLogin(oauthModulePath: string): Promise<void> {
  try {
    await assertRegularModule(oauthModulePath);
    const imported = (await import(
      pathToFileURL(oauthModulePath).href
    )) as Partial<OAuthModule>;
    if (typeof imported.loginWithChatGPT !== "function") {
      failAndExit();
      return;
    }
    const credential = await imported.loginWithChatGPT(
      (authorizationUrl) => {
        if (!terminal && isSafeAuthorizationUrl(authorizationUrl)) {
          process.send?.({ type: "ready", authorizationUrl });
        } else {
          failAndExit();
        }
      },
      (handle) => {
        loginHandle = handle;
      },
    );
    if (!terminal && isCredential(credential)) {
      terminal = true;
      clearTimers();
      loginHandle = undefined;
      process.send?.({ type: "authorized", credential });
    } else if (!terminal) {
      failAndExit();
    }
  } catch {
    failAndExit();
  }
}

function isInitializeMessage(
  message: Record<string, unknown>,
): message is Record<string, unknown> & {
  expiresAt: string;
  oauthModulePath: string;
  setupAttemptId: string;
} {
  return (
    Object.keys(message).sort().join(",") ===
      "expiresAt,oauthModulePath,setupAttemptId,type" &&
    typeof message.expiresAt === "string" &&
    typeof message.oauthModulePath === "string" &&
    path.isAbsolute(message.oauthModulePath) &&
    typeof message.setupAttemptId === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/u.test(message.setupAttemptId)
  );
}

async function assertRegularModule(modulePath: string): Promise<void> {
  const stat = await lstat(modulePath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error("invalid module");
  }
}

function isCompleteManualCallback(value: string): boolean {
  const trimmed = value.trim();
  let parameters: URLSearchParams;
  if (/^https?:\/\//iu.test(trimmed)) {
    try {
      const url = new URL(trimmed);
      if (
        url.protocol !== "http:" ||
        url.hostname !== "localhost" ||
        url.port !== "1455" ||
        url.pathname !== "/auth/callback"
      ) {
        return false;
      }
      parameters = url.searchParams;
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

function isCredential(value: unknown): value is ChatGptCredential {
  if (!isRecord(value)) {
    return false;
  }
  const allowed = [
    "access",
    "accountId",
    "email",
    "expiresAtMs",
    "planType",
    "refresh",
  ];
  if (Object.keys(value).some((key) => !allowed.includes(key))) {
    return false;
  }
  return (
    typeof value.access === "string" &&
    value.access.length > 0 &&
    typeof value.refresh === "string" &&
    value.refresh.length > 0 &&
    typeof value.accountId === "string" &&
    value.accountId.length > 0 &&
    typeof value.expiresAtMs === "number" &&
    Number.isInteger(value.expiresAtMs) &&
    value.expiresAtMs > 0 &&
    (value.email === undefined ||
      value.email === null ||
      typeof value.email === "string") &&
    (value.planType === undefined ||
      value.planType === null ||
      typeof value.planType === "string")
  );
}

function resetLease(): void {
  if (leaseTimer) {
    clearTimeout(leaseTimer);
  }
  leaseTimer = setTimeout(exitImmediately, LEASE_MS);
}

function failAndExit(
  code: "oauth_failed" | "attempt_expired" = "oauth_failed",
): void {
  if (terminal) {
    return;
  }
  terminal = true;
  clearTimers();
  loginHandle = undefined;
  process.send?.({ type: "failure", code }, () => process.exit(1));
}

function exitImmediately(): void {
  terminal = true;
  clearTimers();
  loginHandle = undefined;
  process.exit(0);
}

function clearTimers(): void {
  if (expiryTimer) clearTimeout(expiryTimer);
  if (leaseTimer) clearTimeout(leaseTimer);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
