import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { withC7Locks } from "../../dist/config.js";
import { OpenWikiExternalUpdateService } from "../../dist/external-update.js";
import { ExternalUpdateTransactionOwner } from "../../dist/external-update-transaction.js";
import { WikiPublisher } from "../../dist/publish.js";

const input = JSON.parse(await readFile(process.argv[2], "utf8"));
const distRootA = path.join(path.dirname(input.runtimeDir), "dist-lock-a");
const distRootB = path.join(path.dirname(input.runtimeDir), "dist-lock-b");
await Promise.all([
  mkdir(distRootA, { recursive: true }),
  mkdir(distRootB, { recursive: true }),
]);
let crossRootCallbackRan = false;
let rootBoundContextVerified = false;
try {
  await withC7Locks(distRootA, ["operation"], () =>
    withC7Locks(distRootB, ["operation"], async () => {
      crossRootCallbackRan = true;
    }),
  );
} catch (error) {
  rootBoundContextVerified =
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "invalid_config";
}
if (!rootBoundContextVerified || crossRootCallbackRan) {
  process.stdout.write(
    `${JSON.stringify({ code: "stale_dist", ok: false })}\n`,
  );
  process.exit(0);
}
const security = {
  async securePrivatePath() {},
};
const transactions = new ExternalUpdateTransactionOwner({
  formalWikiPath: input.formalWikiPath,
  runtimeDir: input.runtimeDir,
  security,
});
const publisher = new WikiPublisher({
  formalWikiPath: input.formalWikiPath,
  runtimeDir: input.runtimeDir,
  security,
  fault(point) {
    if (point === input.publishFaultPoint) process.exit(86);
  },
});
const service = new OpenWikiExternalUpdateService({
  publisher,
  sensitivePolicyPath: path.join(input.runtimeDir, "unused-policy.json"),
  skills: {
    select() {
      throw new Error("The finalize child must not select Skills.");
    },
  },
  sources: {
    verify() {
      throw new Error("The finalize child must not verify sources.");
    },
  },
  transactions,
});

try {
  const result = await service.finalize(input.submitInput);
  process.stdout.write(`${JSON.stringify({ ok: true, result })}\n`);
} catch (error) {
  process.stdout.write(
    `${JSON.stringify({
      code:
        typeof error === "object" && error !== null && "code" in error
          ? error.code
          : "unknown",
      name: error instanceof Error ? error.name : "unknown",
      ok: false,
    })}\n`,
  );
}
