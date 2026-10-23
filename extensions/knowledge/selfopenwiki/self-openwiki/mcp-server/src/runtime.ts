import path from "node:path";
import {
  inspectC7Locks,
  readRuntimeConfigState,
  withC7Locks,
  type RuntimeConfig,
} from "./config.js";
import {
  toolInputSchemas,
  toolOutputSchemas,
  type ToolName,
} from "./contracts.js";
import { readCredentialStore } from "./credential-store.js";
import type { ModelVerifier } from "./model-verification.js";
import { sanitizeDiagnostic } from "./process.js";
import type { RuntimeModelService } from "./runtime-model-service.js";
import type { SetupAttemptManager } from "./setup-attempt.js";
import type { C7SkillRegistry } from "./skills.js";
import type { SourceManifestStore } from "./sources.js";
import type { C7ToolRuntime } from "./server.js";
import type { RuntimeCapabilityGate } from "./capabilities.js";
import { snapshotMarkdownTree, readMarkdownPages } from "./snapshot.js";
import { C7PublishError } from "./publish.js";

export type C7RuntimeRecoveryState =
  | "attention"
  | "clean"
  | "recovery_pending"
  | "review_pending"
  | "restore_required"
  | "restore_failed";

type QueryService = {
  query(input: unknown, signal?: AbortSignal): Promise<unknown>;
};
type UpdateService = {
  update(input: unknown, signal?: AbortSignal): Promise<unknown>;
};
type ExternalUpdateService = {
  begin(input: unknown): Promise<unknown>;
  finalize(input: unknown): Promise<unknown>;
  status(): Promise<{
    readonly transactionId: string;
    readonly generation: number;
    readonly state:
      | "candidate_writable"
      | "review_ready"
      | "repair_ready"
      | "attention"
      | "publish_pending";
    readonly nextAction:
      | "resume_candidate"
      | "retry_review"
      | "resolve_attention"
      | "restore";
  } | null>;
};
type PersonalLifecycleService = {
  begin(input: unknown): Promise<unknown>;
  submitPlan(input: unknown): Promise<unknown>;
  nextPage(input: unknown): Promise<unknown>;
  inspectPageClaims(input: unknown): Promise<unknown>;
  submitPage(input: unknown): Promise<unknown>;
  finish(input: unknown): Promise<unknown>;
};

export type SelfOpenWikiVisualizerStatus = {
  readonly id: "selfopenwiki.zxh_wiki_viewer";
  readonly contractSchema: 1;
  readonly launcherPath: string;
  readonly loopbackOnly: true;
  readonly autoOpen: false;
  readonly wikiRootInput: {
    readonly kind: "argument";
    readonly flag: "--wiki-root";
  };
  readonly urlTemplate: "http://127.0.0.1:{port}/wiki/local";
};

export class C7OpenWikiRuntime implements C7ToolRuntime {
  private readonly capabilities: Pick<
    RuntimeCapabilityGate,
    "isToolVerified" | "records"
  >;
  private readonly configPath: string;
  private readonly createQuery: (config: RuntimeConfig) => QueryService;
  private readonly createUpdate: (config: RuntimeConfig) => UpdateService;
  private readonly credentialPath: string;
  private readonly externalUpdate: ExternalUpdateService;
  private readonly modelService: RuntimeModelService;
  private readonly modelVerifier: ModelVerifier;
  private readonly now: () => number;
  private readonly personalLifecycle: PersonalLifecycleService | undefined;
  private readonly onExternalRecoveryResolved:
    | (() => Promise<void> | void)
    | undefined;
  private readonly openWikiRoot: string;
  private readonly recoveryState: () => C7RuntimeRecoveryState;
  private readonly runtimeDir: string;
  private readonly setupManager: SetupAttemptManager;
  private readonly skills: C7SkillRegistry;
  private readonly sources: Pick<SourceManifestStore, "prepare">;
  private readonly versions: { mcpServer: string; openWiki: string };
  private readonly visualizer: SelfOpenWikiVisualizerStatus | undefined;
  private readonly wikiPath: string;

  constructor(options: {
    capabilities: Pick<RuntimeCapabilityGate, "isToolVerified" | "records">;
    configPath: string;
    createQuery(config: RuntimeConfig): QueryService;
    createUpdate(config: RuntimeConfig): UpdateService;
    credentialPath: string;
    externalUpdate: ExternalUpdateService;
    modelService: RuntimeModelService;
    modelVerifier: ModelVerifier;
    now?(): number;
    personalLifecycle?: PersonalLifecycleService;
    onExternalRecoveryResolved?(): Promise<void> | void;
    openWikiRoot: string;
    recoveryState(): C7RuntimeRecoveryState;
    runtimeDir: string;
    setup: SetupAttemptManager;
    skills: C7SkillRegistry;
    sources: Pick<SourceManifestStore, "prepare">;
    versions: { mcpServer: string; openWiki: string };
    visualizer?: SelfOpenWikiVisualizerStatus;
    wikiPath: string;
  }) {
    for (const value of [
      options.configPath,
      options.credentialPath,
      options.openWikiRoot,
      options.runtimeDir,
      options.wikiPath,
    ]) {
      if (!path.isAbsolute(value))
        throw new Error("C7 runtime paths must be absolute.");
    }
    this.capabilities = options.capabilities;
    this.configPath = options.configPath;
    this.createQuery = options.createQuery;
    this.createUpdate = options.createUpdate;
    this.credentialPath = options.credentialPath;
    this.externalUpdate = options.externalUpdate;
    this.modelService = options.modelService;
    this.modelVerifier = options.modelVerifier;
    this.now = options.now ?? Date.now;
    this.personalLifecycle = options.personalLifecycle;
    this.onExternalRecoveryResolved = options.onExternalRecoveryResolved;
    this.openWikiRoot = options.openWikiRoot;
    this.recoveryState = options.recoveryState;
    this.runtimeDir = options.runtimeDir;
    this.setupManager = options.setup;
    this.skills = options.skills;
    this.sources = options.sources;
    this.versions = options.versions;
    this.visualizer = options.visualizer;
    this.wikiPath = options.wikiPath;
  }

  async invoke(
    name: ToolName,
    inputValue: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
    try {
      const input = toolInputSchemas[name].parse(inputValue);
      const output = await this.dispatch(name, input, signal);
      return toolOutputSchemas[name].parse(output);
    } catch (error) {
      return toolOutputSchemas[name].parse(toProtocolFailure(name, error));
    }
  }

  private async dispatch(
    name: ToolName,
    input: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
    switch (name) {
      case "openwiki_status":
        return this.status();
      case "openwiki_begin":
      case "openwiki_submit_plan":
      case "openwiki_next_page":
      case "openwiki_inspect_page_claims":
      case "openwiki_submit_page":
      case "openwiki_finish":
        if (!this.capabilities.isToolVerified(name)) {
          throw codedError("capability_unverified");
        }
        return this.dispatchPersonal(name, input);
      default:
        return this.dispatchNonPersonal(name, input, signal);
    }
  }

  private dispatchPersonal(
    name: Extract<
      ToolName,
      | "openwiki_begin"
      | "openwiki_submit_plan"
      | "openwiki_next_page"
      | "openwiki_inspect_page_claims"
      | "openwiki_submit_page"
      | "openwiki_finish"
    >,
    input: unknown,
  ): Promise<unknown> {
    switch (name) {
      case "openwiki_begin":
        return this.requirePersonalLifecycle().begin(input);
      case "openwiki_submit_plan":
        return this.requirePersonalLifecycle().submitPlan(input);
      case "openwiki_next_page":
        return this.requirePersonalLifecycle().nextPage(input);
      case "openwiki_inspect_page_claims":
        return this.requirePersonalLifecycle().inspectPageClaims(input);
      case "openwiki_submit_page":
        return this.requirePersonalLifecycle().submitPage(input);
      case "openwiki_finish":
        return this.requirePersonalLifecycle().finish(input);
    }
  }

  private async dispatchNonPersonal(
    name: Exclude<
      ToolName,
      | "openwiki_begin"
      | "openwiki_submit_plan"
      | "openwiki_next_page"
      | "openwiki_inspect_page_claims"
      | "openwiki_submit_page"
      | "openwiki_finish"
    >,
    input: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
    switch (name) {
      case "openwiki_setup":
        return this.runSetup(input);
      case "openwiki_prepare_sources":
        return this.prepareSources(input);
      case "openwiki_list_skills":
        return {
          ok: true,
          recovery: { action: "none" },
          skills: this.skills.list(),
          status: "skills_listed",
        };
      case "openwiki_query":
        return this.query(input, signal);
      case "openwiki_read":
        return this.read(input);
      case "openwiki_update":
        return this.update(input, signal);
      case "openwiki_begin_external_update":
      case "openwiki_finalize_external_update": {
        if (
          !this.capabilities.isToolVerified("openwiki_begin_external_update") ||
          !this.capabilities.isToolVerified("openwiki_finalize_external_update")
        ) {
          throw codedError("capability_unverified");
        }
        const confirmedExternalAbort =
          name === "openwiki_finalize_external_update" &&
          isRecord(input) &&
          input.action === "abort" &&
          input.confirmedByUser === true;
        const recoveryState = this.recoveryState();
        if (
          recoveryState !== "clean" &&
          recoveryState !== "attention" &&
          !(recoveryState === "restore_required" && confirmedExternalAbort)
        ) {
          throw codedError("restore_required");
        }
        if (name === "openwiki_begin_external_update") {
          return this.externalUpdate.begin(input);
        }
        const output = await this.externalUpdate.finalize(input);
        if (
          confirmedExternalAbort &&
          isRecord(output) &&
          output.status === "external_update_aborted"
        ) {
          await this.onExternalRecoveryResolved?.();
        }
        return output;
      }
      case "openwiki_set_default_model":
        return this.setDefaultModel(input);
    }
  }

  async status(): Promise<unknown> {
    const locks = await inspectC7Locks(this.runtimeDir);
    if (locks.some((lock) => lock.name === "wiki" && lock.held)) {
      return statusFailure("busy", safeErrorMessage("busy"), "retry");
    }
    const wikiSnapshot = await withC7Locks(this.runtimeDir, ["wiki"], () =>
      snapshotMarkdownTree(this.wikiPath),
    );
    let configState: Awaited<ReturnType<typeof readRuntimeConfigState>> = {
      version: "invalid",
    };
    let legacyEvidenceInvalid = false;
    try {
      configState = await readRuntimeConfigState(this.configPath);
    } catch {
      legacyEvidenceInvalid = true;
    }
    let credentialState: Awaited<ReturnType<typeof readCredentialStore>> = {
      version: "invalid",
    };
    try {
      credentialState = await readCredentialStore(this.credentialPath);
    } catch {
      legacyEvidenceInvalid = true;
    }
    const credential = credentialState.credential;
    const legacyAuthentication = legacyEvidenceInvalid
      ? ({ status: "invalid" } as const)
      : credential === undefined
        ? ({ status: "not_configured" } as const)
        : credential.expiresAtMs <= this.now()
          ? ({ status: "expired" } as const)
          : ({
              expiresAt: new Date(credential.expiresAtMs).toISOString(),
              status: "authorized",
            } as const);
    const legacyInitialized =
      configState.config?.initialized === true &&
      legacyAuthentication.status === "authorized";
    let recoveryState = this.recoveryState();
    const externalPairVerified =
      this.capabilities.isToolVerified("openwiki_begin_external_update") &&
      this.capabilities.isToolVerified("openwiki_finalize_external_update");
    let externalUsable =
      externalPairVerified &&
      (recoveryState === "clean" || recoveryState === "attention");
    let activeTransaction: Awaited<
      ReturnType<ExternalUpdateService["status"]>
    > = null;
    if (externalUsable) {
      try {
        activeTransaction = await this.externalUpdate.status();
      } catch (error) {
        if (isRecord(error) && error.code === "busy") throw error;
        return statusFailure(
          "internal_error",
          "The external transaction state could not be read safely.",
          "restore",
          false,
        );
      }
    }
    if (activeTransaction?.state === "publish_pending") {
      recoveryState = "restore_required";
      externalUsable = false;
    }
    return {
      authRequired: false,
      authentication: { status: "not_required" },
      capabilities: this.capabilities.records(),
      defaultModel: null,
      executionMode: "external_agent",
      externalAgent: {
        activeTransaction,
        ready: externalUsable,
      },
      initialized: externalUsable,
      legacyProvider: {
        authRequired: true,
        authentication: legacyAuthentication,
        available: true,
        defaultModel: legacyInitialized
          ? configState.config!.defaultModel
          : null,
        initialized: legacyInitialized,
        verifiedModels: legacyInitialized
          ? configState.config!.verifiedModels
          : [],
      },
      ok: true,
      paths: {
        openWikiRoot: this.openWikiRoot,
        runtimeRoot: this.runtimeDir,
        wikiRoot: this.wikiPath,
      },
      ...(this.visualizer === undefined ? {} : { visualizer: this.visualizer }),
      recovery: {
        action:
          recoveryState === "clean"
            ? "none"
            : recoveryState === "attention" ||
                recoveryState === "review_pending"
              ? "resolve_attention"
              : "restore",
        ...(recoveryState === "clean"
          ? {}
          : {
              message: "A persisted Wiki recovery obligation needs attention.",
            }),
      },
      runtime: { locks, recoveryState },
      staticCapabilities: [
        {
          available: process.platform === "win32",
          id: "sources.local-paths.win32",
          ...(process.platform === "win32"
            ? {}
            : {
                reason:
                  "Arbitrary local paths are enabled only on verified Windows builds.",
              }),
        },
        {
          available: false,
          id: "power-loss-safe",
          reason:
            "The initial release guarantees process-crash recovery, not power-loss durability.",
        },
      ],
      status: "status",
      version: {
        contractSchema: 2,
        mcpServer: this.versions.mcpServer,
        openWiki: this.versions.openWiki,
      },
      verifiedModels: [],
      wikiRevision: wikiSnapshot.rootHash,
    };
  }

  async setup(inputValue: unknown): Promise<unknown> {
    return this.runSetup(inputValue);
  }

  private async runSetup(inputValue: unknown): Promise<unknown> {
    const input = toolInputSchemas.openwiki_setup.parse(inputValue);
    if (input.action === "start") {
      return this.setupManager.start({
        confirmation: input.confirmation,
        selection: {
          model: input.model,
          reasoningEffort: input.reasoningEffort,
        },
      });
    }
    if (input.action === "complete") {
      return this.setupManager.complete(input.setupAttemptId, input.callback);
    }
    return this.setupManager.cancel(input.setupAttemptId);
  }

  async prepareSources(inputValue: unknown): Promise<unknown> {
    const input = toolInputSchemas.openwiki_prepare_sources.parse(inputValue);
    const prepared = await this.sources.prepare(input.paths);
    return {
      ...prepared,
      files: prepared.files.map((file) => ({
        hash: file.hash,
        path: file.canonicalPath,
        risks: file.risks,
        size: file.size,
      })),
      ok: true,
      recovery: { action: "none" },
      status: "sources_prepared",
    };
  }

  async listSkills(): Promise<unknown> {
    return {
      ok: true,
      recovery: { action: "none" },
      skills: this.skills.list(),
      status: "skills_listed",
    };
  }

  async read(inputValue: unknown): Promise<unknown> {
    const input = toolInputSchemas.openwiki_read.parse(inputValue);
    return withC7Locks(this.runtimeDir, ["operation", "wiki"], async () => {
      if (
        this.recoveryState() !== "clean" &&
        this.recoveryState() !== "attention"
      ) {
        throw codedError("restore_required");
      }
      if ((await this.externalUpdate.status())?.state === "publish_pending") {
        throw codedError("restore_required");
      }
      const result = await readMarkdownPages(
        this.wikiPath,
        input.paths ?? [],
        input.expectedWikiRevision,
      );
      return {
        ok: true,
        status: "wiki_read",
        recovery: { action: "none" },
        ...result,
      };
    });
  }

  async query(input: unknown, signal?: AbortSignal): Promise<unknown> {
    const recoveryState = this.recoveryState();
    if (recoveryState !== "clean" && recoveryState !== "attention") {
      throw codedError("restore_required");
    }
    const config = await requireRuntimeConfig(this.configPath);
    const output = await this.createQuery(config).query(input, signal);
    if (
      recoveryState !== "attention" ||
      !isRecord(output) ||
      output.ok !== true
    ) {
      return output;
    }
    return {
      ...output,
      recovery: {
        action: "none",
        message:
          "A prior published generation has semantic attention recorded for later correction.",
      },
    };
  }

  async update(input: unknown, signal?: AbortSignal): Promise<unknown> {
    if (
      this.recoveryState() !== "clean" &&
      this.recoveryState() !== "attention"
    ) {
      throw codedError("restore_required");
    }
    const config = await requireRuntimeConfig(this.configPath);
    return this.createUpdate(config).update(input, signal);
  }

  async setDefaultModel(inputValue: unknown): Promise<unknown> {
    const input = toolInputSchemas.openwiki_set_default_model.parse(inputValue);
    const result = await this.modelService.verifyAndSetDefault(
      {
        confirmation: input.confirmation,
        selection: {
          model: input.model,
          reasoningEffort: input.reasoningEffort,
        },
      },
      this.modelVerifier,
    );
    return {
      model: result.model,
      ok: true,
      recovery: { action: "none" },
      status: "default_model_changed",
    };
  }

  private requirePersonalLifecycle(): PersonalLifecycleService {
    if (this.personalLifecycle === undefined) {
      throw codedError("capability_unverified");
    }
    return this.personalLifecycle;
  }
}

async function requireRuntimeConfig(
  configPath: string,
): Promise<RuntimeConfig> {
  const state = await readRuntimeConfigState(configPath);
  if (!state.config) throw codedError("setup_required");
  return state.config;
}

function statusFailure(
  code: string,
  message: string,
  action: string,
  retryable = true,
) {
  return {
    error: { code, message, retryable },
    ok: false,
    recovery: { action },
  };
}

function toProtocolFailure(name: ToolName, error: unknown) {
  const publicationFailure =
    error instanceof C7PublishError &&
    (error.code === "publish_failed" || error.code === "restore_failed");
  const rawCode = publicationFailure
    ? "restore_required"
    : isRecord(error) && typeof error.code === "string"
      ? error.code
      : "internal_error";
  const diagnostic = publicationFailure
    ? publicationDiagnostic(error)
    : isRecord(error) && typeof error.diagnostic === "string"
      ? sanitizeDiagnostic(error.diagnostic)
      : undefined;
  const failureStage =
    isRecord(error) && "failureStage" in error ? error.failureStage : undefined;
  const candidate = {
    error: {
      code: rawCode,
      ...(diagnostic || failureStage !== undefined
        ? {
            details: {
              ...(diagnostic ? { diagnostic } : {}),
              ...(failureStage !== undefined ? { failureStage } : {}),
            },
          }
        : {}),
      message: safeErrorMessage(rawCode),
      retryable: isRetryable(rawCode),
    },
    ok: false,
    recovery: { action: recoveryAction(rawCode) },
  };
  const candidateValid = toolOutputSchemas[name].safeParse(candidate).success;
  return candidateValid
    ? candidate
    : {
        error: {
          code: "internal_error",
          message: "The C7 OpenWiki operation failed closed.",
          retryable: false,
        },
        ok: false,
        recovery: { action: "none" },
      };
}

function publicationDiagnostic(error: C7PublishError): string {
  const fields = [`publisher=${error.code}`];
  let cause: unknown = error.cause;
  for (let depth = 0; depth < 4 && isRecord(cause); depth += 1) {
    if (
      typeof cause.code === "string" &&
      /^E[A-Z0-9_]{1,30}$/u.test(cause.code)
    ) {
      fields.push(`cause=${cause.code}`);
      if (
        typeof cause.syscall === "string" &&
        [
          "rename",
          "open",
          "mkdir",
          "read",
          "write",
          "scandir",
          "lstat",
          "stat",
          "unlink",
          "rmdir",
        ].includes(cause.syscall)
      ) {
        fields.push(`syscall=${cause.syscall}`);
      }
      break;
    }
    cause = cause.cause;
  }
  return fields.join("; ");
}

function safeErrorMessage(code: string): string {
  const messages: Record<string, string> = {
    attempt_expired: "The setup attempt expired.",
    attempt_not_found: "The setup attempt was not found.",
    attempt_state_invalid:
      "The setup attempt is not valid in its current state.",
    auth_required: "ChatGPT authorization is required.",
    capability_unverified:
      "This OpenWiki capability has no current matching local verification evidence.",
    busy: "Another C7 OpenWiki operation currently owns the required lock.",
    confirmation_required: "Explicit user confirmation is required.",
    invalid_input: "The request does not match the strict tool contract.",
    model_rejected:
      "The selected model and reasoning effort were not accepted.",
    oauth_failed: "ChatGPT OAuth did not complete.",
    platform_unsupported:
      "This capability is not verified on the current platform.",
    process_failure: "The isolated OpenWiki model process failed.",
    provider_failure: "The selected model provider request failed.",
    restore_required:
      "A prior Wiki recovery or review obligation must be resolved first.",
    wiki_invalid:
      "The formal Wiki cannot be read within the safe Markdown contract.",
    wiki_changed:
      "The Wiki revision changed; reload the page index before reading.",
    skill_manifest_invalid: "The trusted Skill manifest is invalid.",
    skill_untrusted:
      "A requested Skill does not match its trusted package hash.",
    source_changed: "A confirmed source changed and must be prepared again.",
    source_manifest_invalid:
      "The source manifest confirmation is invalid or stale.",
    source_rejected: "The local source selection was rejected by policy.",
    source_too_large: "The local source selection exceeds configured limits.",
  };
  return messages[code] ?? "The C7 OpenWiki operation failed closed.";
}

function recoveryAction(code: string) {
  if (code === "setup_required") return "run_setup";
  if (code === "auth_required" || code === "oauth_failed") return "reauthorize";
  if (code === "confirmation_required") return "confirm_update";
  if (
    code === "restore_required" ||
    code === "restore_failed" ||
    code === "transaction_state_invalid"
  )
    return "restore";
  if (
    code === "source_rejected" ||
    code === "source_changed" ||
    code === "personal_root_invalid" ||
    code === "source_manifest_invalid" ||
    code === "wiki_conflict"
  )
    return "clarify";
  return isRetryable(code) ? "retry" : "none";
}

function isRetryable(code: string): boolean {
  return [
    "attempt_expired",
    "auth_required",
    "busy",
    "oauth_failed",
    "process_failure",
    "provider_failure",
    "source_changed",
    "wiki_conflict",
  ].includes(code);
}

function codedError(code: string): Error & { code: string } {
  return Object.assign(new Error(code), { code });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
