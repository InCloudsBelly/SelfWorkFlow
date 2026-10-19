const SENSITIVE_ENV_KEY = "C7_TEST_SECRET_CANARY";

if (process.env[SENSITIVE_ENV_KEY]) {
  process.send?.({ type: "failure", code: "oauth_failed" });
  process.exit(2);
}

let initialized = false;
let terminal = false;
let expiryTimer;

process.on("message", (message) => {
  if (!message || typeof message !== "object" || terminal) return;

  if (message.type === "initialize" && !initialized) {
    initialized = true;
    if (message.oauthModulePath === "malformed") {
      process.send?.({ type: "invented-message", secret: "must-not-pass" });
      return;
    }
    const delay = Math.max(0, Date.parse(message.expiresAt) - Date.now());
    expiryTimer = setTimeout(() => {
      terminal = true;
      process.send?.({ type: "failure", code: "attempt_expired" });
      process.exit(3);
    }, delay);
    process.send?.({
      type: "ready",
      authorizationUrl:
        "https://auth.openai.com/oauth/authorize?state=bound-state",
    });
    if (String(message.oauthModulePath).endsWith("auto-oauth.js")) {
      setTimeout(sendAuthorized, 25);
    }
    return;
  }

  if (message.type === "complete" && initialized) {
    const callback = new URL(message.callback);
    if (
      callback.searchParams.get("code") !== "sensitive-code" ||
      callback.searchParams.get("state") !== "bound-state"
    ) {
      process.send?.({ type: "failure", code: "oauth_failed" });
      return;
    }
    sendAuthorized();
    return;
  }

  if (message.type === "cancel") {
    terminal = true;
    clearTimeout(expiryTimer);
    process.exit(0);
  }
});

process.on("disconnect", () => process.exit(0));

function sendAuthorized() {
  if (terminal) return;
  terminal = true;
  clearTimeout(expiryTimer);
  process.send?.({
    type: "authorized",
    credential: {
      access: "access-secret-canary",
      refresh: "refresh-secret-canary",
      expiresAtMs: 1_800_000_000_000,
      accountId: "account-private",
      email: null,
      planType: null,
    },
  });
}
