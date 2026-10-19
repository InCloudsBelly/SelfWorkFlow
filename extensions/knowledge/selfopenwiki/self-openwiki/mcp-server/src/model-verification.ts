import { spawn, type ChildProcess } from "node:child_process";
import { lstat } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { modelSelectionSchema } from "./contracts.js";
import type { OpenWikiAdapterPaths } from "./openwiki-adapter.js";

export type ModelSelection = z.infer<typeof modelSelectionSchema>;

export type ModelVerificationEvidence = {
  providerAccepted: true;
  providerReportedModel?: string;
  requested: ModelSelection;
  sent: ModelSelection;
};

export type ModelVerificationFailureCode =
  | "model_rejected"
  | "provider_failure"
  | "process_failure"
  | "platform_unsupported"
  | "internal_error";

export class ModelVerificationError extends Error {
  constructor(
    readonly code: ModelVerificationFailureCode,
    readonly retryable: boolean,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ModelVerificationError";
  }
}

export interface ModelVerifier {
  verify(
    selection: ModelSelection,
    credentialReference: string,
    signal?: AbortSignal,
  ): Promise<ModelVerificationEvidence>;
}

type IsolatedVerifierOptions = {
  adapterPaths: OpenWikiAdapterPaths;
  childScriptPath?: string;
  resolveOpenWikiHome(credentialReference: string): Promise<
    | string
    | {
        cleanup(): Promise<void>;
        finalize?(): Promise<void>;
        path: string;
      }
  >;
  timeoutMs?: number;
};

const childMessageSchema = z.discriminatedUnion("type", [
  z.strictObject({
    evidence: z.strictObject({
      providerAccepted: z.literal(true),
      requested: modelSelectionSchema,
      sent: modelSelectionSchema,
    }),
    type: z.literal("verified"),
  }),
  z.strictObject({
    code: z.enum([
      "model_rejected",
      "provider_failure",
      "process_failure",
      "internal_error",
    ]),
    type: z.literal("failure"),
  }),
]);

export class IsolatedOpenWikiModelVerifier implements ModelVerifier {
  private readonly adapterPaths: OpenWikiAdapterPaths;
  private readonly childScriptPath: string;
  private readonly resolveOpenWikiHome: IsolatedVerifierOptions["resolveOpenWikiHome"];
  private readonly timeoutMs: number;

  constructor(options: IsolatedVerifierOptions) {
    this.adapterPaths = options.adapterPaths;
    this.childScriptPath =
      options.childScriptPath ??
      path.resolve(import.meta.dirname, "model-verification-child.js");
    this.resolveOpenWikiHome = options.resolveOpenWikiHome;
    this.timeoutMs = options.timeoutMs ?? 120_000;
  }

  async verify(
    selection: ModelSelection,
    credentialReference: string,
    signal?: AbortSignal,
  ): Promise<ModelVerificationEvidence> {
    if (signal?.aborted) {
      throw new ModelVerificationError(
        "process_failure",
        true,
        "Model verification was cancelled.",
      );
    }
    const parsedSelection = modelSelectionSchema.safeParse(selection);
    if (!parsedSelection.success) {
      throw new ModelVerificationError(
        "internal_error",
        false,
        "Model verification selection is invalid.",
      );
    }

    let openWikiHome: string;
    let cleanup: () => Promise<void> = async () => undefined;
    let finalize: () => Promise<void> = async () => undefined;
    let processStarted = false;
    try {
      try {
        const resolvedHome =
          await this.resolveOpenWikiHome(credentialReference);
        if (typeof resolvedHome === "string") {
          openWikiHome = resolvedHome;
        } else {
          openWikiHome = resolvedHome.path;
          cleanup = resolvedHome.cleanup;
          finalize = resolvedHome.finalize ?? finalize;
        }
        await Promise.all([
          assertRegularFile(this.childScriptPath, "model verifier child"),
          assertRegularFile(this.adapterPaths.cliPath, "OpenWiki CLI"),
          assertRegularDirectory(openWikiHome, "isolated OpenWiki Home"),
        ]);
      } catch {
        throw new ModelVerificationError(
          "process_failure",
          true,
          "Could not prepare the isolated model verification process.",
        );
      }
      if (signal?.aborted) {
        throw new ModelVerificationError(
          "process_failure",
          true,
          "Model verification was cancelled.",
        );
      }

      let child: ChildProcess;
      try {
        child = spawn(process.execPath, [this.childScriptPath], {
          detached: false,
          env: createVerificationEnvironment(
            openWikiHome,
            parsedSelection.data,
          ),
          serialization: "json",
          stdio: ["ignore", "ignore", "ignore", "ipc"],
          windowsHide: true,
        });
        processStarted = true;
      } catch {
        throw new ModelVerificationError(
          "process_failure",
          true,
          "Model verification process failed to start.",
        );
      }

      return await new Promise<ModelVerificationEvidence>((resolve, reject) => {
        let settled = false;
        const onAbort = () => {
          finish({
            ok: false,
            error: new ModelVerificationError(
              "process_failure",
              true,
              "Model verification was cancelled.",
            ),
          });
        };
        const finish = (
          result:
            | { ok: true; evidence: ModelVerificationEvidence }
            | { ok: false; error: ModelVerificationError },
        ): void => {
          if (settled) return;
          settled = true;
          clearTimeout(timeout);
          signal?.removeEventListener("abort", onAbort);
          if (child.connected) child.disconnect();
          if (child.exitCode === null && child.signalCode === null)
            child.kill();
          void waitForChildExit(child, 2_000).then((exited) => {
            if (!exited) {
              reject(
                new ModelVerificationError(
                  "process_failure",
                  true,
                  "Model verification process did not terminate.",
                ),
              );
            } else if (result.ok) resolve(result.evidence);
            else reject(result.error);
          });
        };
        const timeout = setTimeout(() => {
          finish({
            ok: false,
            error: new ModelVerificationError(
              "process_failure",
              true,
              "Model verification process timed out.",
            ),
          });
        }, this.timeoutMs);
        signal?.addEventListener("abort", onAbort, { once: true });

        child.once("error", () => {
          finish({
            ok: false,
            error: new ModelVerificationError(
              "process_failure",
              true,
              "Model verification process failed to start.",
            ),
          });
        });
        child.once("exit", () => {
          if (!settled) {
            finish({
              ok: false,
              error: new ModelVerificationError(
                "process_failure",
                true,
                "Model verification process exited without a result.",
              ),
            });
          }
        });
        child.on("message", (message) => {
          const parsed = childMessageSchema.safeParse(message);
          if (!parsed.success) {
            finish({
              ok: false,
              error: new ModelVerificationError(
                "internal_error",
                false,
                "Model verification child protocol was invalid.",
              ),
            });
            return;
          }
          if (parsed.data.type === "failure") {
            finish({
              ok: false,
              error: new ModelVerificationError(
                parsed.data.code,
                ["provider_failure", "process_failure"].includes(
                  parsed.data.code,
                ),
                "Model verification did not complete successfully.",
              ),
            });
            return;
          }
          const evidence = parsed.data.evidence;
          if (
            !selectionsEqual(evidence.requested, parsedSelection.data) ||
            !selectionsEqual(evidence.sent, parsedSelection.data)
          ) {
            finish({
              ok: false,
              error: new ModelVerificationError(
                "internal_error",
                false,
                "Model verification observed a model or effort fallback.",
              ),
            });
            return;
          }
          finish({ ok: true, evidence });
        });

        child.send({
          cliPath: this.adapterPaths.cliPath,
          selection: parsedSelection.data,
          type: "verify",
        });
      });
    } finally {
      let finalizationFailed = false;
      try {
        if (processStarted) await finalize();
      } catch {
        finalizationFailed = true;
      }
      try {
        await cleanup();
      } catch {
        finalizationFailed = true;
      }
      if (finalizationFailed) {
        throw new ModelVerificationError(
          "process_failure",
          true,
          "The isolated model verification state could not be finalized safely.",
        );
      }
    }
  }
}

async function assertRegularFile(
  filePath: string,
  label: string,
): Promise<void> {
  if (!path.isAbsolute(filePath)) throw new Error(`${label} is not absolute`);
  const stat = await lstat(filePath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`${label} is not a regular file`);
  }
}

async function assertRegularDirectory(
  directoryPath: string,
  label: string,
): Promise<void> {
  if (!path.isAbsolute(directoryPath)) {
    throw new Error(`${label} is not absolute`);
  }
  const stat = await lstat(directoryPath);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`${label} is not a regular directory`);
  }
}

function createVerificationEnvironment(
  openWikiHome: string,
  selection: ModelSelection,
): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const key of [
    "ComSpec",
    "PATH",
    "Path",
    "PATHEXT",
    "SystemRoot",
    "TEMP",
    "TMP",
    "WINDIR",
  ]) {
    const value = process.env[key];
    if (value !== undefined) environment[key] = value;
  }
  environment.OPENWIKI_HOME = openWikiHome;
  environment.OPENWIKI_MODEL_ID = selection.model;
  environment.OPENWIKI_PROVIDER = "openai-chatgpt";
  environment.OPENWIKI_REASONING_EFFORT = selection.reasoningEffort;
  environment.OPENWIKI_SHELL_MODE = "restricted";
  return environment;
}

function selectionsEqual(left: ModelSelection, right: ModelSelection): boolean {
  return (
    left.model === right.model && left.reasoningEffort === right.reasoningEffort
  );
}

function waitForChildExit(
  child: ChildProcess,
  timeoutMs: number,
): Promise<boolean> {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(false), timeoutMs);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolve(true);
    });
  });
}
