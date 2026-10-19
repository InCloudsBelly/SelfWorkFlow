import { EphemeralCredentialVault } from "../../dist/auth.js";
import { ForkedOAuthAttemptFactory } from "../../dist/oauth-helper.js";

const [helperScriptPath, oauthModulePath] = process.argv.slice(2);
const factory = new ForkedOAuthAttemptFactory({
  adapterPaths: {
    rootDir: process.cwd(),
    cliPath: oauthModulePath,
    oauthModulePath,
  },
  helperScriptPath,
  startTimeoutMs: 2_000,
  vault: new EphemeralCredentialVault(),
});

await factory.start({
  setupAttemptId: "attempt-host-kill",
  expiresAt: new Date(Date.now() + 30_000).toISOString(),
});
process.send?.({ type: "ready" });
await new Promise(() => undefined);
