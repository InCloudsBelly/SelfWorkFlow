export function loginWithChatGPT(openUrl, onReady) {
  return new Promise((resolve) => {
    onReady?.({
      submitManual(input) {
        const callback = input.startsWith("http")
          ? new URL(input).searchParams
          : new URLSearchParams(input.startsWith("?") ? input.slice(1) : input);
        if (
          callback.get("code") !== "sensitive-code" ||
          callback.get("state") !== "bound-state"
        ) {
          return "state mismatch";
        }
        resolve({
          access: "access-secret-canary",
          refresh: "refresh-secret-canary",
          expiresAtMs: 1_800_000_000_000,
          accountId: "account-private",
          email: null,
          planType: null,
        });
        return null;
      },
    });
    openUrl("https://auth.openai.com/oauth/authorize?state=bound-state");
  });
}
