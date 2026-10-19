import { writeFile } from "node:fs/promises";
import path from "node:path";

const home = process.env.OPENWIKI_HOME;
const model = process.env.OPENWIKI_MODEL_ID;
const effort = process.env.OPENWIKI_REASONING_EFFORT;

if (!home || !model || !effort) {
  process.exitCode = 1;
} else {
  await writeFile(
    path.join(home, "smoke-observed.json"),
    JSON.stringify({
      home,
      model,
      effort,
      provider: process.env.OPENWIKI_PROVIDER,
      shellMode: process.env.OPENWIKI_SHELL_MODE,
      parentSecretPresent: Boolean(process.env.C7_TEST_SECRET_CANARY),
      pid: process.pid,
    }),
    "utf8",
  );

  if (model === "gpt-test-hang") {
    await new Promise((resolve) => setTimeout(resolve, 10_000));
  } else if (model === "gpt-test-process-failure") {
    process.exitCode = 1;
  } else {
    const sentModel = model === "gpt-test-fallback" ? "fallback-model" : model;
    const status =
      model === "gpt-test-401" ? 401 : model === "gpt-test-429" ? 429 : 200;
    try {
      await fetch("https://chatgpt.com/backend-api/codex/responses", {
        method: "POST",
        body: JSON.stringify({
          model: sentModel,
          reasoning: { effort },
          input: [{ role: "user", content: "C7 smoke" }],
        }),
        ...(model === "gpt-test-abort"
          ? { signal: AbortSignal.abort() }
          : { dispatcher: staticDispatcher(status) }),
      });
    } catch {
      // The parent verifier must observe and reject this request failure.
    }
    if (model === "gpt-test-malformed-final") {
      await fetch("https://chatgpt.com/backend-api/codex/responses", {
        method: "POST",
        body: JSON.stringify({ model: sentModel }),
        dispatcher: staticDispatcher(200),
      });
    }
    process.exitCode = 0;
  }
}

function staticDispatcher(status) {
  return {
    dispatch(_options, handler) {
      queueMicrotask(() => {
        handler.onConnect(() => undefined, null);
        handler.onHeaders(
          status,
          ["content-type", "application/json"],
          () => undefined,
          String(status),
        );
        handler.onData(Buffer.from("{}"));
        handler.onComplete([]);
      });
      return true;
    },
    close() {
      return Promise.resolve();
    },
    destroy() {
      return Promise.resolve();
    },
  };
}
