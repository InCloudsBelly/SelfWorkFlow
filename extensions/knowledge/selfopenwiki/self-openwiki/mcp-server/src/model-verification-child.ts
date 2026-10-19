import { lstat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

type Selection = { model: string; reasoningEffort: string };
type ObservedRequest = {
  accepted: boolean;
  request: Selection | null;
  status?: number;
};

let initialized = false;
process.once("disconnect", () => process.exit(0));
process.on("message", (message: unknown) => {
  if (initialized) {
    fail();
    return;
  }
  initialized = true;
  void run(message);
});

async function run(message: unknown): Promise<void> {
  if (!isInitializeMessage(message)) {
    fail();
    return;
  }
  const home = process.env.OPENWIKI_HOME;
  if (!home || !path.isAbsolute(home)) {
    fail();
    return;
  }

  try {
    await assertRegularFile(message.cliPath);
    const observed: ObservedRequest[] = [];
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      if (isCodexResponsesRequest(input)) {
        const observation: ObservedRequest = {
          accepted: false,
          request: parseObservedRequest(init?.body),
        };
        observed.push(observation);
        try {
          const response = await originalFetch(input, init);
          observation.status = response.status;
          observation.accepted = response.ok;
          return response;
        } catch (error) {
          throw error;
        }
      }
      return originalFetch(input, init);
    };

    try {
      process.chdir(home);
      process.argv = [
        process.execPath,
        message.cliPath,
        "--print",
        "--mode",
        "personal",
        "--model-id",
        message.selection.model,
        "C7 model verification smoke. Reply briefly without using tools.",
      ];
      process.exitCode = 0;
      await import(`${pathToFileURL(message.cliPath).href}?c7-smoke=1`);
    } finally {
      globalThis.fetch = originalFetch;
    }

    if (process.exitCode !== 0 || observed.length === 0) {
      fail("process_failure");
      return;
    }
    if (
      observed.some(
        (observation) =>
          observation.request === null ||
          !selectionsEqual(observation.request, message.selection),
      )
    ) {
      fail("internal_error");
      return;
    }

    const finalRequest = observed[observed.length - 1];
    if (!finalRequest.accepted) {
      fail(
        finalRequest.status !== undefined &&
          [400, 404, 422].includes(finalRequest.status)
          ? "model_rejected"
          : "provider_failure",
      );
      return;
    }
    const sent = finalRequest.request;
    if (sent === null) {
      fail("internal_error");
      return;
    }
    process.send?.({
      type: "verified",
      evidence: {
        providerAccepted: true,
        requested: message.selection,
        sent,
      },
    });
  } catch {
    fail("process_failure");
  }
}

function isInitializeMessage(message: unknown): message is {
  cliPath: string;
  selection: Selection;
  type: "verify";
} {
  if (!isRecord(message)) return false;
  if (
    Object.keys(message).sort().join(",") !== "cliPath,selection,type" ||
    message.type !== "verify" ||
    typeof message.cliPath !== "string" ||
    !path.isAbsolute(message.cliPath) ||
    !isRecord(message.selection)
  ) {
    return false;
  }
  return (
    Object.keys(message.selection).sort().join(",") ===
      "model,reasoningEffort" &&
    typeof message.selection.model === "string" &&
    /^[a-z0-9][a-z0-9._-]{0,127}$/u.test(message.selection.model) &&
    typeof message.selection.reasoningEffort === "string" &&
    ["low", "medium", "high", "xhigh", "max", "ultra"].includes(
      message.selection.reasoningEffort,
    )
  );
}

async function assertRegularFile(filePath: string): Promise<void> {
  const stat = await lstat(filePath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error("invalid file");
  }
}

function isCodexResponsesRequest(input: Parameters<typeof fetch>[0]): boolean {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
  return (
    url.startsWith("https://chatgpt.com/backend-api/codex") &&
    url.includes("/responses")
  );
}

function parseObservedRequest(
  body: BodyInit | null | undefined,
): Selection | null {
  if (typeof body !== "string") return null;
  try {
    const parsed = JSON.parse(body) as unknown;
    if (
      !isRecord(parsed) ||
      typeof parsed.model !== "string" ||
      !isRecord(parsed.reasoning) ||
      typeof parsed.reasoning.effort !== "string"
    ) {
      return null;
    }
    return {
      model: parsed.model,
      reasoningEffort: parsed.reasoning.effort,
    };
  } catch {
    return null;
  }
}

function selectionsEqual(left: Selection, right: Selection): boolean {
  return (
    left.model === right.model && left.reasoningEffort === right.reasoningEffort
  );
}

function fail(
  code:
    | "model_rejected"
    | "provider_failure"
    | "process_failure"
    | "internal_error" = "internal_error",
): void {
  process.send?.({ type: "failure", code });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
