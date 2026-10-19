import http from "node:http";
import { randomBytes } from "node:crypto";

export function loginWithChatGPT(openUrl, onReady) {
  const state = randomBytes(16).toString("hex");
  return new Promise((resolve, reject) => {
    let settled = false;
    const server = http.createServer((request, response) => {
      const url = new URL(request.url ?? "", "http://localhost:1455");
      if (url.pathname !== "/auth/callback") {
        response.writeHead(404).end();
        return;
      }
      if (url.searchParams.get("state") !== state) {
        response.writeHead(400).end();
        return;
      }
      const code = url.searchParams.get("code");
      if (!code) {
        response.writeHead(400).end();
        return;
      }
      response.writeHead(200).end();
      finish(code);
    });
    const finish = (code) => {
      if (settled) return;
      settled = true;
      server.close();
      resolve({
        access: `access-${code}`,
        refresh: "refresh-secret-canary",
        expiresAtMs: 1_900_000_000_000,
        accountId: "account-private",
        email: null,
        planType: null,
      });
    };
    server.once("error", reject);
    server.listen(1455, "localhost", () => {
      const authorizationUrl = `https://auth.openai.com/oauth/authorize?state=${state}&code_challenge=fake-pkce-challenge`;
      openUrl(authorizationUrl);
      onReady?.({
        submitManual(input) {
          const parameters = input.startsWith("http")
            ? new URL(input).searchParams
            : new URLSearchParams(
                input.startsWith("?") ? input.slice(1) : input,
              );
          if (parameters.get("state") !== state) return "state mismatch";
          const code = parameters.get("code");
          if (!code) return "missing code";
          finish(code);
          return null;
        },
      });
    });
  });
}
