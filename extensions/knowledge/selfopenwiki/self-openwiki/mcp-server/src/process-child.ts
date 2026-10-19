import { lstat } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

type Selection = { model: string; reasoningEffort: string };
type InitializeMessage = {
  cliPath: string;
  operation: "query" | "repair" | "review" | "update";
  requestFileName: "request.md" | "result-finalizer.md";
  responsesUrlPrefix: string;
  runId: string;
  selection: Selection;
  type: "run";
};

type ObservedRequest = {
  accepted: boolean;
  request: Selection | null;
  retryAfterMs?: number;
  status: number | null;
};

let initialized = false;
process.once("disconnect", () => process.exit(1));
process.on("message", (message: unknown) => {
  if (initialized || !isInitializeMessage(message)) {
    process.exit(1);
    return;
  }
  initialized = true;
  void run(message);
});

async function run(message: InitializeMessage): Promise<void> {
  let stage = "cli-validation";
  try {
    await assertRegularFile(message.cliPath);
    stage = "fetch-observer-install";
    const observed: ObservedRequest[] = [];
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      if (!isResponsesRequest(input, message.responsesUrlPrefix)) {
        return originalFetch(input, init);
      }
      const observation: ObservedRequest = {
        accepted: false,
        request: parseObservedRequest(init?.body),
        status: null,
      };
      observed.push(observation);
      const response = await originalFetch(input, init);
      observation.accepted = response.ok;
      observation.status = response.status;
      observation.retryAfterMs = parseRetryAfter(
        response.headers.get("retry-after"),
      );
      return response;
    };

    try {
      stage = "cli-import";
      process.chdir(requireAbsoluteHome());
      process.argv = buildOpenWikiArgv(message);
      process.exitCode = 0;
      await import(
        `${pathToFileURL(message.cliPath).href}?c7-run=${encodeURIComponent(message.runId)}`
      );
    } finally {
      globalThis.fetch = originalFetch;
    }

    if (observed.length === 0) {
      sendAndExit({
        code: "process_failed",
        runId: message.runId,
        type: "failed",
      });
      return;
    }
    if (
      observed.some(
        (entry) =>
          entry.request === null ||
          !selectionsEqual(entry.request, message.selection),
      )
    ) {
      sendAndExit({
        code: "model_mismatch",
        runId: message.runId,
        type: "failed",
      });
      return;
    }
    const finalRequest = observed.at(-1)!;
    if (!finalRequest.accepted || finalRequest.request === null) {
      const status = finalRequest.status;
      if (status !== null && status >= 400 && status <= 599) {
        sendAndExit({
          code: providerFailureCodeForStatus(status),
          providerStatusClass: status >= 500 ? "5xx" : "4xx",
          ...(finalRequest.retryAfterMs === undefined
            ? {}
            : { retryAfterMs: finalRequest.retryAfterMs }),
          runId: message.runId,
          type: "failed",
        });
        return;
      }
      sendAndExit({
        code: "process_failed",
        runId: message.runId,
        type: "failed",
      });
      return;
    }
    if (process.exitCode !== 0) {
      sendAndExit({
        code: "process_failed",
        providerAccepted: true,
        runId: message.runId,
        type: "failed",
      });
      return;
    }
    sendAndExit({
      evidence: {
        providerAccepted: true,
        requested: message.selection,
        sent: finalRequest.request,
      },
      runId: message.runId,
      type: "completed",
    });
  } catch (error) {
    const errorText =
      error instanceof Error
        ? `${error.name}: ${error.message}`
        : "UnknownError";
    process.stderr.write(
      `${sanitizeDiagnostic(`stage=${stage}; error=${errorText}`)}\n`,
    );
    sendAndExit({
      code: "process_failed",
      runId: message.runId,
      type: "failed",
    });
  }
}

function providerFailureCodeForStatus(
  status: number,
): "provider_rejected" | "provider_transient" {
  return status === 408 || status === 429 || status >= 500
    ? "provider_transient"
    : "provider_rejected";
}

function parseRetryAfter(value: string | null): number | undefined {
  if (value === null) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(30_000, Math.round(seconds * 1_000));
  }
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return undefined;
  return Math.min(30_000, Math.max(0, timestamp - Date.now()));
}

function sanitizeDiagnostic(value: string): string {
  return value
    .slice(0, 2_048)
    .replace(/(Authorization\s*:\s*Bearer\s+)\S+/giu, "$1[REDACTED]")
    .replace(
      /\b(?:sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b/gu,
      "[REDACTED]",
    )
    .replace(
      /(token|secret|password|cookie)\s*[=:]\s*[^\s,;]+/giu,
      "$1=[REDACTED]",
    );
}

function buildOpenWikiArgv(message: InitializeMessage): string[] {
  return [
    process.execPath,
    message.cliPath,
    "code",
    "--print",
    ...(message.operation === "update" || message.operation === "repair"
      ? ["--update"]
      : []),
    "--modelId",
    message.selection.model,
    `Read and execute the bound C7 request in _c7-control/in/${message.requestFileName}.`,
  ];
}

function requireAbsoluteHome(): string {
  const home = process.env.OPENWIKI_HOME;
  if (!home || !path.isAbsolute(home)) throw new Error("invalid home");
  return home;
}

function isInitializeMessage(value: unknown): value is InitializeMessage {
  if (!isRecord(value)) return false;
  if (
    Object.keys(value).sort().join(",") !==
      "cliPath,operation,requestFileName,responsesUrlPrefix,runId,selection,type" ||
    value.type !== "run" ||
    typeof value.cliPath !== "string" ||
    !path.isAbsolute(value.cliPath) ||
    !["query", "repair", "review", "update"].includes(
      String(value.operation),
    ) ||
    !["request.md", "result-finalizer.md"].includes(
      String(value.requestFileName),
    ) ||
    typeof value.runId !== "string" ||
    !/^[a-f0-9-]{36}$/u.test(value.runId) ||
    !isAllowedResponsesPrefix(value.responsesUrlPrefix) ||
    !isRecord(value.selection)
  ) {
    return false;
  }
  return (
    Object.keys(value.selection).sort().join(",") === "model,reasoningEffort" &&
    typeof value.selection.model === "string" &&
    /^[a-z0-9][a-z0-9._-]{0,127}$/u.test(value.selection.model) &&
    typeof value.selection.reasoningEffort === "string" &&
    ["low", "medium", "high", "xhigh", "max", "ultra"].includes(
      value.selection.reasoningEffort,
    )
  );
}

function isAllowedResponsesPrefix(value: unknown): value is string {
  return (
    value === "https://chatgpt.com/backend-api/codex" ||
    value === "data:application/json"
  );
}

function isResponsesRequest(
  input: Parameters<typeof fetch>[0],
  prefix: string,
): boolean {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
  return prefix === "data:application/json"
    ? url.startsWith(prefix)
    : url.startsWith(prefix) && url.includes("/responses");
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

function sendAndExit(message: Record<string, unknown>): void {
  if (!process.connected || process.send === undefined) {
    process.exit(1);
    return;
  }
  process.send(message, () => {
    process.disconnect();
    process.exit(message.type === "completed" ? 0 : 1);
  });
}

async function assertRegularFile(filePath: string): Promise<void> {
  const stat = await lstat(filePath);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("invalid file");
}

function selectionsEqual(left: Selection, right: Selection): boolean {
  return (
    left.model === right.model && left.reasoningEffort === right.reasoningEffort
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
