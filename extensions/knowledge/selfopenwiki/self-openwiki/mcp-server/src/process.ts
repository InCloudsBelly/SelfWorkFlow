import { spawn, type ChildProcess } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import path from "node:path";
import { modelSelectionSchema } from "./contracts.js";
import type { ModelSelection } from "./model-verification.js";
import type { ModelVerificationEvidence } from "./model-verification.js";

export const DEFAULT_OPENWIKI_PROCESS_TIMEOUT_MS = 45 * 60_000;

export type OpenWikiProcessOperation = "query" | "repair" | "review" | "update";
export type OpenWikiRequestFileName = "request.md" | "result-finalizer.md";

export type OpenWikiProcessResult = {
  readonly exitCode: 0;
  readonly model: ModelVerificationEvidence;
  readonly stderr: string;
  readonly stdout: string;
};

export class C7ProcessError extends Error {
  readonly diagnostic?: string;

  constructor(
    readonly code:
      | "aborted"
      | "model_mismatch"
      | "output_limit"
      | "process_failed"
      | "provider_rejected"
      | "provider_transient"
      | "timeout"
      | "untrusted_executable",
    message: string,
    diagnostic?: string,
    readonly retryAfterMs?: number,
    readonly providerStatusClass?: "4xx" | "5xx",
  ) {
    super(message);
    this.name = "C7ProcessError";
    this.diagnostic = diagnostic ? sanitizeDiagnostic(diagnostic) : undefined;
  }
}

export class OpenWikiProcessRunner {
  private readonly cliPath: string;
  private readonly childScriptPath: string;
  private readonly expectedChildHash: string;
  private readonly expectedCliHash: string;
  private readonly maxOutputBytes: number;
  private readonly nodePath: string;
  private readonly responsesUrlPrefix:
    | "data:application/json"
    | "https://chatgpt.com/backend-api/codex";
  private readonly terminateProcessTree: (pid: number) => Promise<void>;
  private readonly timeoutMs: number;

  constructor(options: {
    childScriptPath: string;
    cliPath: string;
    expectedChildHash: string;
    expectedCliHash: string;
    maxOutputBytes?: number;
    nodePath?: string;
    responsesUrlPrefix?: "data:application/json";
    terminateProcessTree?(pid: number): Promise<void>;
    timeoutMs?: number;
  }) {
    if (
      !path.isAbsolute(options.cliPath) ||
      !path.isAbsolute(options.childScriptPath) ||
      !path.isAbsolute(options.nodePath ?? process.execPath) ||
      !/^sha256:[a-f0-9]{64}$/u.test(options.expectedChildHash) ||
      !/^sha256:[a-f0-9]{64}$/u.test(options.expectedCliHash)
    ) {
      throw new C7ProcessError(
        "untrusted_executable",
        "The OpenWiki process executable binding is invalid.",
      );
    }
    this.cliPath = options.cliPath;
    this.childScriptPath = options.childScriptPath;
    this.expectedChildHash = options.expectedChildHash;
    this.expectedCliHash = options.expectedCliHash;
    this.maxOutputBytes = options.maxOutputBytes ?? 1024 * 1024;
    this.nodePath = options.nodePath ?? process.execPath;
    this.responsesUrlPrefix =
      options.responsesUrlPrefix ?? "https://chatgpt.com/backend-api/codex";
    this.terminateProcessTree =
      options.terminateProcessTree ?? terminateProcessTree;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_OPENWIKI_PROCESS_TIMEOUT_MS;
    if (
      !Number.isSafeInteger(this.maxOutputBytes) ||
      this.maxOutputBytes < 1 ||
      !Number.isSafeInteger(this.timeoutMs) ||
      this.timeoutMs < 1
    ) {
      throw new C7ProcessError(
        "process_failed",
        "The OpenWiki process limits are invalid.",
      );
    }
  }

  async run(input: {
    cwd: string;
    openWikiHome: string;
    operation: OpenWikiProcessOperation;
    policyPath: string;
    requestFileName?: OpenWikiRequestFileName;
    selection: ModelSelection;
    signal?: AbortSignal;
  }): Promise<OpenWikiProcessResult> {
    if (input.signal?.aborted) {
      throw new C7ProcessError(
        "aborted",
        "The OpenWiki process was cancelled.",
      );
    }
    const parsedSelection = modelSelectionSchema.safeParse(input.selection);
    if (!parsedSelection.success) {
      throw new C7ProcessError(
        "process_failed",
        "The OpenWiki model selection is invalid.",
      );
    }
    const requestFileName = input.requestFileName ?? "request.md";
    if (
      requestFileName !== "request.md" &&
      requestFileName !== "result-finalizer.md"
    ) {
      throw new C7ProcessError(
        "process_failed",
        "The OpenWiki request file binding is invalid.",
      );
    }
    const [cwd, openWikiHome] = await Promise.all([
      canonicalDirectory(input.cwd, "transaction working directory"),
      canonicalDirectory(input.openWikiHome, "temporary OpenWiki Home"),
    ]);
    if (!pathsEqual(cwd, openWikiHome)) {
      throw new C7ProcessError(
        "process_failed",
        "The OpenWiki process must run at the temporary Home root.",
      );
    }
    await Promise.all([
      this.assertTrustedExecutable(),
      assertHasExpectedHash(
        this.childScriptPath,
        this.expectedChildHash,
        "C7 process child",
      ),
      assertRegularNonLinkFile(this.nodePath, "Node executable"),
      assertRegularNonLinkFile(input.policyPath, "run policy"),
    ]);
    if (input.signal?.aborted) {
      throw new C7ProcessError(
        "aborted",
        "The OpenWiki process was cancelled.",
      );
    }

    const runId = randomUUID();
    const child = spawn(this.nodePath, [this.childScriptPath], {
      cwd,
      detached: process.platform !== "win32",
      env: createChildEnvironment({
        home: openWikiHome,
        policyPath: input.policyPath,
        selection: parsedSelection.data,
      }),
      shell: false,
      stdio: ["ignore", "pipe", "pipe", "ipc"],
      windowsHide: true,
    });
    const result = this.waitForResult(
      child,
      input.signal,
      runId,
      parsedSelection.data,
    );
    try {
      child.send(
        {
          cliPath: this.cliPath,
          operation: input.operation,
          requestFileName,
          responsesUrlPrefix: this.responsesUrlPrefix,
          runId,
          selection: parsedSelection.data,
          type: "run",
        },
        (error) => {
          if (error) child.emit("error", error);
        },
      );
    } catch {
      void result.catch(() => undefined);
      if (child.pid === undefined) {
        child.kill();
      } else {
        await this.terminateProcessTree(child.pid).catch(() => child.kill());
      }
      throw new C7ProcessError(
        "process_failed",
        "The isolated OpenWiki process could not receive its bound request.",
      );
    }
    return result;
  }

  private async assertTrustedExecutable(): Promise<void> {
    await assertRegularNonLinkFile(this.cliPath, "OpenWiki CLI");
    const actual = `sha256:${createHash("sha256")
      .update(await readFile(this.cliPath))
      .digest("hex")}`;
    if (actual !== this.expectedCliHash) {
      throw new C7ProcessError(
        "untrusted_executable",
        "The OpenWiki CLI does not match verified capability evidence.",
      );
    }
  }

  private waitForResult(
    child: ChildProcess,
    signal: AbortSignal | undefined,
    runId: string,
    requested: ModelSelection,
  ): Promise<OpenWikiProcessResult> {
    return new Promise((resolve, reject) => {
      const stdout: Buffer[] = [];
      const stderr: Buffer[] = [];
      let outputBytes = 0;
      let failureCode: C7ProcessError["code"] | undefined;
      let modelEvidence: ModelVerificationEvidence | undefined;
      let providerAcceptedProcessFailure = false;
      let providerStatusClass: "4xx" | "5xx" | undefined;
      let retryAfterMs: number | undefined;
      let terminalMessageObserved = false;
      let terminalProtocolInvalid = false;
      let terminationStarted = false;
      let settled = false;

      const requestTermination = (code: C7ProcessError["code"]): void => {
        failureCode ??= code;
        if (terminationStarted) return;
        terminationStarted = true;
        const pid = child.pid;
        if (pid === undefined) {
          child.kill();
          return;
        }
        void this.terminateProcessTree(pid)
          .catch(() => undefined)
          .finally(() => {
            if (child.exitCode === null && child.signalCode === null)
              child.kill();
          });
      };
      const collect = (target: Buffer[], chunk: Buffer): void => {
        outputBytes += chunk.byteLength;
        const remaining = Math.max(
          0,
          this.maxOutputBytes - buffered(stdout) - buffered(stderr),
        );
        if (remaining > 0) target.push(chunk.subarray(0, remaining));
        if (outputBytes > this.maxOutputBytes) {
          requestTermination("output_limit");
        }
      };
      child.stdout?.on("data", (chunk: Buffer) => collect(stdout, chunk));
      child.stderr?.on("data", (chunk: Buffer) => collect(stderr, chunk));
      child.on("message", (message: unknown) => {
        const invalidateTerminalProtocol = (): void => {
          terminalProtocolInvalid = true;
          failureCode = "process_failed";
          modelEvidence = undefined;
          providerAcceptedProcessFailure = false;
          providerStatusClass = undefined;
          retryAfterMs = undefined;
          requestTermination("process_failed");
        };
        if (terminalMessageObserved) {
          invalidateTerminalProtocol();
          return;
        }
        terminalMessageObserved = true;
        const parsed = parseChildMessage(message, runId, requested);
        if (parsed.type === "invalid") {
          invalidateTerminalProtocol();
        } else if (parsed.type === "failed") {
          providerAcceptedProcessFailure = parsed.providerAccepted === true;
          providerStatusClass = parsed.providerStatusClass;
          retryAfterMs = parsed.retryAfterMs;
          requestTermination(parsed.code);
        } else if (modelEvidence !== undefined) {
          requestTermination("process_failed");
        } else {
          modelEvidence = parsed.evidence;
        }
      });

      const timeout = setTimeout(
        () => requestTermination("timeout"),
        this.timeoutMs,
      );
      timeout.unref();
      const abort = (): void => requestTermination("aborted");
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();

      const finish = (
        outcome: { error: C7ProcessError } | { result: OpenWikiProcessResult },
      ): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        signal?.removeEventListener("abort", abort);
        if ("error" in outcome) reject(outcome.error);
        else resolve(outcome.result);
      };
      child.once("error", (error) => {
        requestTermination(failureCode ?? "process_failed");
        finish({
          error: new C7ProcessError(
            failureCode ?? "process_failed",
            "The isolated OpenWiki process could not start.",
            sanitizeDiagnostic(error.name),
          ),
        });
      });
      child.once("close", (code) => {
        const stdoutText = sanitizeDiagnostic(
          Buffer.concat(stdout).toString("utf8"),
        );
        const stderrText = sanitizeDiagnostic(
          Buffer.concat(stderr).toString("utf8"),
        );
        if (failureCode !== undefined) {
          const terminalFailureCode =
            failureCode === "process_failed" &&
            providerAcceptedProcessFailure &&
            !terminalProtocolInvalid
              ? (providerFailureCodeForAcceptedDiagnostic(stderrText) ??
                failureCode)
              : failureCode;
          finish({
            error: new C7ProcessError(
              terminalFailureCode,
              processFailureMessage(terminalFailureCode),
              stderrText,
              retryAfterMs,
              providerStatusClass,
            ),
          });
          return;
        }
        if (code !== 0) {
          finish({
            error: new C7ProcessError(
              "process_failed",
              "The isolated OpenWiki process failed.",
              stderrText,
            ),
          });
          return;
        }
        if (modelEvidence === undefined) {
          finish({
            error: new C7ProcessError(
              "process_failed",
              "The isolated OpenWiki process did not provide request-bound model evidence.",
              stderrText,
            ),
          });
          return;
        }
        finish({
          result: {
            exitCode: 0,
            model: modelEvidence,
            stderr: stderrText,
            stdout: stdoutText,
          },
        });
      });
    });
  }
}

function processFailureMessage(code: C7ProcessError["code"]): string {
  switch (code) {
    case "timeout":
      return "The isolated OpenWiki process timed out.";
    case "aborted":
      return "The isolated OpenWiki process was cancelled.";
    case "output_limit":
      return "The isolated OpenWiki process exceeded its output limit.";
    case "model_mismatch":
      return "The isolated OpenWiki process changed the bound model selection.";
    case "provider_transient":
      return "The provider temporarily rejected the bound OpenWiki request.";
    case "provider_rejected":
      return "The provider rejected the bound OpenWiki request.";
    default:
      return "The isolated OpenWiki process failed its bound protocol.";
  }
}

async function assertHasExpectedHash(
  filePath: string,
  expectedHash: string,
  label: string,
): Promise<void> {
  await assertRegularNonLinkFile(filePath, label);
  const actual = `sha256:${createHash("sha256")
    .update(await readFile(filePath))
    .digest("hex")}`;
  if (actual !== expectedHash) {
    throw new C7ProcessError(
      "untrusted_executable",
      `${label} does not match verified capability evidence.`,
    );
  }
}

type ParsedChildMessage =
  | { type: "invalid" }
  | {
      code:
        | "model_mismatch"
        | "process_failed"
        | "provider_rejected"
        | "provider_transient";
      providerStatusClass?: "4xx" | "5xx";
      providerAccepted?: true;
      retryAfterMs?: number;
      type: "failed";
    }
  | { evidence: ModelVerificationEvidence; type: "completed" };

function parseChildMessage(
  value: unknown,
  runId: string,
  requested: ModelSelection,
): ParsedChildMessage {
  if (
    !isRecord(value) ||
    value.runId !== runId ||
    typeof value.type !== "string"
  ) {
    return { type: "invalid" };
  }
  if (value.type === "failed") {
    if (
      [
        "model_mismatch",
        "process_failed",
        "provider_rejected",
        "provider_transient",
      ].includes(String(value.code)) &&
      (value.providerStatusClass === undefined ||
        value.providerStatusClass === "4xx" ||
        value.providerStatusClass === "5xx") &&
      (value.providerAccepted === undefined ||
        (value.providerAccepted === true &&
          value.code === "process_failed" &&
          value.providerStatusClass === undefined &&
          value.retryAfterMs === undefined)) &&
      (value.retryAfterMs === undefined ||
        (Number.isInteger(value.retryAfterMs) &&
          Number(value.retryAfterMs) >= 0 &&
          Number(value.retryAfterMs) <= 30_000))
    ) {
      return {
        code: value.code as Exclude<
          C7ProcessError["code"],
          "aborted" | "output_limit" | "timeout" | "untrusted_executable"
        >,
        ...(value.providerAccepted === true
          ? { providerAccepted: true as const }
          : {}),
        ...(value.providerStatusClass === undefined
          ? {}
          : { providerStatusClass: value.providerStatusClass }),
        ...(value.retryAfterMs === undefined
          ? {}
          : { retryAfterMs: Number(value.retryAfterMs) }),
        type: "failed",
      };
    }
    return { type: "invalid" };
  }
  if (
    value.type !== "completed" ||
    !isRecord(value.evidence) ||
    value.evidence.providerAccepted !== true ||
    !isSelection(value.evidence.requested) ||
    !isSelection(value.evidence.sent) ||
    !selectionsEqual(value.evidence.requested, requested) ||
    !selectionsEqual(value.evidence.sent, requested)
  ) {
    return { type: "invalid" };
  }
  return {
    evidence: {
      providerAccepted: true,
      requested: value.evidence.requested,
      sent: value.evidence.sent,
    },
    type: "completed",
  };
}

export function providerFailureCodeForStatus(
  status: number,
): "provider_rejected" | "provider_transient" {
  if (!Number.isInteger(status) || status < 400 || status > 599) {
    throw new C7ProcessError(
      "process_failed",
      "The provider status is invalid.",
    );
  }
  return status === 408 || status === 429 || status >= 500
    ? "provider_transient"
    : "provider_rejected";
}

export function providerFailureCodeForAcceptedDiagnostic(
  diagnostic: string,
): "provider_transient" | undefined {
  const normalized = diagnostic.replace(/\r\n?/gu, "\n").replace(/\n$/u, "");
  return normalized ===
    "Our servers are currently overloaded. Please try again later." ||
    /^An error occurred while processing your request\. You can retry your request, or contact us through our help center at help\.openai\.com if the error persists\. Please include the request ID [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12} in your message\.$/u.test(
      normalized,
    )
    ? "provider_transient"
    : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSelection(value: unknown): value is ModelSelection {
  return modelSelectionSchema.safeParse(value).success;
}

function selectionsEqual(left: ModelSelection, right: ModelSelection): boolean {
  return (
    left.model === right.model && left.reasoningEffort === right.reasoningEffort
  );
}

function createChildEnvironment(input: {
  home: string;
  policyPath: string;
  selection: ModelSelection;
}): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const key of [
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
  ] as const) {
    const value = process.env[key];
    if (value !== undefined) environment[key] = value;
  }
  return {
    ...environment,
    DO_NOT_TRACK: "1",
    NO_COLOR: "1",
    OPENWIKI_HOME: input.home,
    OPENWIKI_MODEL_ID: input.selection.model,
    OPENWIKI_PROVIDER: "openai-chatgpt",
    OPENWIKI_REASONING_EFFORT: input.selection.reasoningEffort,
    OPENWIKI_RUN_POLICY_FILE: input.policyPath,
    OPENWIKI_SHELL_MODE: "restricted",
    OPENWIKI_TELEMETRY_DISABLED: "1",
  };
}

async function canonicalDirectory(
  value: string,
  label: string,
): Promise<string> {
  if (!path.isAbsolute(value)) {
    throw new C7ProcessError("process_failed", `${label} must be absolute.`);
  }
  let stat;
  try {
    stat = await lstat(value);
  } catch (error) {
    throw new C7ProcessError(
      "process_failed",
      `${label} is missing.`,
      sanitizeDiagnostic(error instanceof Error ? error.name : "Error"),
    );
  }
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new C7ProcessError(
      "process_failed",
      `${label} must be a regular non-link directory.`,
    );
  }
  return realpath(value);
}

async function assertRegularNonLinkFile(
  value: string,
  label: string,
): Promise<void> {
  if (!path.isAbsolute(value)) {
    throw new C7ProcessError(
      "untrusted_executable",
      `${label} path must be absolute.`,
    );
  }
  let stat;
  try {
    stat = await lstat(value);
  } catch {
    throw new C7ProcessError("untrusted_executable", `${label} is missing.`);
  }
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new C7ProcessError(
      "untrusted_executable",
      `${label} must be a regular non-link file.`,
    );
  }
}

async function terminateProcessTree(pid: number): Promise<void> {
  if (process.platform !== "win32") {
    process.kill(-pid, "SIGKILL");
    return;
  }
  const systemRoot = process.env.SystemRoot ?? process.env.WINDIR;
  if (!systemRoot) throw new Error("Windows system root is unavailable.");
  const taskkillPath = path.join(systemRoot, "System32", "taskkill.exe");
  const taskkill = spawn(taskkillPath, ["/PID", String(pid), "/T", "/F"], {
    env: { SystemRoot: systemRoot, WINDIR: systemRoot },
    shell: false,
    stdio: "ignore",
    windowsHide: true,
  });
  await new Promise<void>((resolve, reject) => {
    taskkill.once("error", reject);
    taskkill.once("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error("Windows process-tree termination failed."));
    });
  });
}

export function sanitizeDiagnostic(value: string): string {
  return value
    .slice(0, 4096)
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

function buffered(chunks: readonly Buffer[]): number {
  return chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
}

function pathsEqual(left: string, right: string): boolean {
  return process.platform === "win32"
    ? left.toLowerCase() === right.toLowerCase()
    : left === right;
}
