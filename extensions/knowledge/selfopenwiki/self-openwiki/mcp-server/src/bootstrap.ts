import { createHash } from "node:crypto";
import { lstat, mkdir, open, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { EphemeralCredentialVault } from "./auth.js";
import {
  loadRuntimeCapabilityGate,
  type RuntimeCapabilityGate,
} from "./capabilities.js";
import { C7ConfigError, recoverStaleC7Locks, withC7Locks } from "./config.js";
import { createCredentialStoreHomeLease } from "./credential-store.js";
import { TOOL_NAMES, type ToolName } from "./contracts.js";
import { IsolatedOpenWikiModelVerifier } from "./model-verification.js";
import type { ModelVerifier } from "./model-verification.js";
import { resolveOpenWikiAdapterPaths } from "./openwiki-adapter.js";
import {
  C7PersonalGateway,
  OfficialLifecycleAdapter,
} from "./official-lifecycle-adapter.js";
import { ForkedOAuthAttemptFactory } from "./oauth-helper.js";
import { VerifiedPrivatePathSecurity } from "./permissions.js";
import { OpenWikiProcessRunner } from "./process.js";
import { OpenWikiExternalUpdateService } from "./external-update.js";
import { ExternalUpdateTransactionOwner } from "./external-update-transaction.js";
import { inspectPersistedReviewAttention, WikiPublisher } from "./publish.js";
import { OpenWikiQueryService } from "./query.js";
import { WikiRecoveryService, type WikiRecoveryResult } from "./recovery.js";
import { OpenWikiReviewService } from "./review.js";
import {
  createRuntimeSetupManager,
  RuntimeModelService,
} from "./runtime-model-service.js";
import type { SetupAttemptManager } from "./setup-attempt.js";
import {
  C7OpenWikiRuntime,
  type C7RuntimeRecoveryState,
  type SelfOpenWikiVisualizerStatus,
} from "./runtime.js";
import type { C7ToolRuntime } from "./server.js";
import { createLiveWikiPolicy } from "./live-policy.js";
import { PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT } from "./personal-skill-adapter.js";
import { PersonalWikiLifecycle } from "./personal-wiki-lifecycle.js";
import { FilePersonalClaimsResolver } from "./personal-claims.js";
import { PersonalWikiRootResolver } from "./personal-wiki-root.js";
import { PersonalRunStoreRouter } from "./personal-run-store.js";

async function assertNonReparseDirectory(
  targetPath: string,
  label: string,
  allowMissingLeaf: boolean,
): Promise<void> {
  const absolute = path.resolve(targetPath);
  const root = path.parse(absolute).root;
  const segments = path
    .relative(root, absolute)
    .split(path.sep)
    .filter(Boolean);
  let current = root;
  for (const [index, segment] of segments.entries()) {
    current = path.join(current, segment);
    try {
      const stats = await lstat(current);
      if (stats.isSymbolicLink()) {
        throw new Error(`${label} cannot contain a link or junction.`);
      }
      if (index === segments.length - 1 && !stats.isDirectory()) {
        throw new Error(`${label} must be a directory.`);
      }
    } catch (error) {
      if (
        hasErrorCode(error, "ENOENT") &&
        allowMissingLeaf &&
        index === segments.length - 1
      ) {
        return;
      }
      throw error;
    }
  }
}

async function readVisualizerStatus(
  visualizerPath: string | undefined,
): Promise<SelfOpenWikiVisualizerStatus | undefined> {
  if (visualizerPath === undefined || !path.isAbsolute(visualizerPath)) {
    return undefined;
  }
  const launcherPath = path.resolve(visualizerPath);
  try {
    const stats = await lstat(launcherPath);
    if (!stats.isFile() || stats.isSymbolicLink()) return undefined;
  } catch {
    return undefined;
  }
  return {
    id: "selfopenwiki.zxh_wiki_viewer",
    contractSchema: 1,
    launcherPath,
    loopbackOnly: true,
    autoOpen: false,
    wikiRootInput: { kind: "argument", flag: "--wiki-root" },
    urlTemplate: "http://127.0.0.1:{port}/wiki/local",
  };
}
import { snapshotMarkdownTree } from "./snapshot.js";
import { SourceManifestStore } from "./sources.js";
import { C7TransactionFactory } from "./transaction.js";
import { recoverAbandonedTransactions } from "./transaction-recovery.js";
import { OpenWikiUpdateService, type UpdateProcessRunner } from "./update.js";
import { TrustedWin32SourceHelper } from "./win32-helper.js";

export type C7BootstrapResult = {
  readonly capabilityGate: RuntimeCapabilityGate;
  readonly runtime: C7ToolRuntime;
};

type StartupExternalRecoveryState = "clean" | "restore_required";

export async function rehydrateStartupRecovery(options: {
  externalTransactions: Pick<ExternalUpdateTransactionOwner, "recoverStartup">;
  legacyRecovery: Pick<WikiRecoveryService, "recoverAll">;
  publisher: Pick<WikiPublisher, "publishExternal">;
  runtimeDir: string;
}): Promise<{
  externalState: StartupExternalRecoveryState;
  legacyResults: readonly WikiRecoveryResult[];
}> {
  return withC7Locks(
    options.runtimeDir,
    ["operation", "credentials", "wiki"],
    async () => {
      try {
        const external = await options.externalTransactions.recoverStartup({
          publish: async (input) => {
            const published = await options.publisher.publishExternal(input);
            return { wikiRevision: published.after.rootHash };
          },
        });
        if (external.status === "external_startup_restore_required") {
          return { externalState: "restore_required", legacyResults: [] };
        }
        if (await containsExternalRecoveryArtifact(options.runtimeDir)) {
          return { externalState: "restore_required", legacyResults: [] };
        }
      } catch {
        return { externalState: "restore_required", legacyResults: [] };
      }
      return {
        externalState: "clean",
        legacyResults: await options.legacyRecovery.recoverAll(),
      };
    },
  );
}

export async function bootstrapC7Runtime(
  options: {
    openWikiRoot?: string;
    repositoryRoot?: string;
    runtimeDir?: string;
    wikiRoot?: string;
    evidencePath?: string;
    visualizerPath?: string;
  } = {},
): Promise<C7BootstrapResult> {
  const repositoryRoot = path.resolve(
    options.repositoryRoot ?? path.resolve(import.meta.dirname, "../.."),
  );
  const openWikiRoot = path.resolve(
    options.openWikiRoot ??
      path.resolve(repositoryRoot, "..", ".work", "openwiki"),
  );
  const defaultRuntimeDir = path.join(repositoryRoot, "runtime");
  const runtimeDir = path.resolve(options.runtimeDir ?? defaultRuntimeDir);
  if (
    !options.wikiRoot &&
    !pathsEqual(runtimeDir, defaultRuntimeDir) &&
    !isWithin(defaultRuntimeDir, runtimeDir)
  ) {
    throw new Error(
      "The C7 runtime directory must stay inside its repository runtime root.",
    );
  }
  const wikiPath = path.resolve(
    options.wikiRoot ?? path.join(runtimeDir, "wiki"),
  );
  await assertNonReparseDirectory(
    wikiPath,
    "Wiki root",
    options.wikiRoot === undefined,
  );
  if (options.wikiRoot === undefined) {
    await mkdir(wikiPath, { mode: 0o700, recursive: true });
    await assertNonReparseDirectory(wikiPath, "Wiki root", false);
  }
  const evidencePath = path.resolve(
    options.evidencePath ??
      path.join(defaultRuntimeDir, "verified-capabilities.json"),
  );
  const visualizer = await readVisualizerStatus(options.visualizerPath);
  const capabilityGate = await loadRuntimeCapabilityGate({
    evidencePath,
    openWikiRoot,
    repositoryRoot,
  });
  const versions = await readVersions(repositoryRoot, openWikiRoot);
  const externalPairVerified =
    capabilityGate.isToolVerified("openwiki_begin_external_update") &&
    capabilityGate.isToolVerified("openwiki_finalize_external_update");
  const personalLifecycleVerified = [
    "openwiki_begin",
    "openwiki_submit_plan",
    "openwiki_next_page",
    "openwiki_inspect_page_claims",
    "openwiki_submit_page",
    "openwiki_finish",
  ].every((name) => capabilityGate.isToolVerified(name as ToolName));
  if (
    !capabilityGate.isToolVerified("openwiki_setup") &&
    !externalPairVerified &&
    !personalLifecycleVerified
  ) {
    return {
      capabilityGate,
      runtime: new MinimalStatusRuntime({
        capabilityGate,
        openWikiRoot,
        runtimeDir,
        versions,
        visualizer,
        wikiPath,
      }),
    };
  }

  const helperPath = path.join(
    repositoryRoot,
    "win32-helper",
    "dist",
    "SelfOpenWiki.Win32Helper.exe",
  );
  const helper = new TrustedWin32SourceHelper({
    executablePath: helperPath,
    expectedHash: await hashFile(helperPath),
  });
  const security = new VerifiedPrivatePathSecurity({ win32Helper: helper });
  await assertNonReparseDirectory(runtimeDir, "runtime root", true);
  await mkdir(runtimeDir, { mode: 0o700, recursive: true });
  await assertNonReparseDirectory(runtimeDir, "runtime root", false);
  await security.securePrivatePath({ directory: true, targetPath: runtimeDir });
  await assertNonReparseDirectory(wikiPath, "Wiki root", false);
  await security.securePrivatePath({ directory: true, targetPath: wikiPath });

  const configPath = path.join(runtimeDir, "config.json");
  const credentialPath = path.join(runtimeDir, "credentials.json");
  const vault = new EphemeralCredentialVault();
  const modelService = new RuntimeModelService({
    configPath,
    credentialPath,
    privatePathSecurity: security,
    runtimeDir,
    vault,
  });
  let modelVerifier: ModelVerifier;
  let setup: SetupAttemptManager;
  let processRunner: UpdateProcessRunner;
  if (capabilityGate.isToolVerified("openwiki_setup")) {
    const adapterPaths = await resolveOpenWikiAdapterPaths(openWikiRoot);
    modelVerifier = new IsolatedOpenWikiModelVerifier({
      adapterPaths,
      resolveOpenWikiHome: async (reference) => {
        const lease = await modelService.resolveOpenWikiHome(reference);
        return {
          cleanup: lease.cleanup,
          finalize: async () => {
            await lease.finalize?.();
          },
          path: lease.path,
        };
      },
    });
    setup = createRuntimeSetupManager({
      oauth: new ForkedOAuthAttemptFactory({ adapterPaths, vault }),
      service: modelService,
      verifier: modelVerifier,
    });
    processRunner = new OpenWikiProcessRunner({
      childScriptPath: path.join(import.meta.dirname, "process-child.js"),
      cliPath: adapterPaths.cliPath,
      expectedChildHash: await hashFile(
        path.join(import.meta.dirname, "process-child.js"),
      ),
      expectedCliHash: await hashFile(adapterPaths.cliPath),
    });
  } else {
    const unavailable = async (): Promise<never> => {
      throw Object.assign(new Error("capability_unverified"), {
        code: "capability_unverified",
      });
    };
    modelVerifier = { verify: unavailable };
    setup = {
      cancel: unavailable,
      complete: unavailable,
      start: unavailable,
    } as unknown as SetupAttemptManager;
    processRunner = { run: unavailable };
  }
  const sources = new SourceManifestStore({
    copier: helper,
    policyPath: path.join(repositoryRoot, "config", "sensitive-files.json"),
    runtimeDir,
  });
  const policy = await createLiveWikiPolicy({
    repositoryRoot,
    openWikiRoot,
    evidencePath,
    capabilityGate,
  });
  const skills = policy.skills;
  const externalTransactions = new ExternalUpdateTransactionOwner({
    formalWikiPath: wikiPath,
    runtimeDir,
    security,
  });
  const transactions = new C7TransactionFactory({
    createHomeLease: () =>
      createCredentialStoreHomeLease(runtimeDir, credentialPath, security),
    formalWikiPath: wikiPath,
    runtimeDir,
    security,
  });
  const publisher = new WikiPublisher({
    formalWikiPath: wikiPath,
    runtimeDir,
    security,
  });
  const externalUpdate = new OpenWikiExternalUpdateService({
    publisher,
    sensitivePolicyPath: path.join(
      repositoryRoot,
      "config",
      "sensitive-files.json",
    ),
    skills,
    sources,
    transactions: externalTransactions,
  });
  const createPersonalExternalUpdate = (
    personalWikiPath: string,
    personalRuntimeDir: string,
  ) => {
    const personalTransactions = new ExternalUpdateTransactionOwner({
      formalWikiPath: personalWikiPath,
      runtimeDir: personalRuntimeDir,
      security,
    });
    const personalPublisher = new WikiPublisher({
      formalWikiPath: personalWikiPath,
      runtimeDir: personalRuntimeDir,
      security,
    });
    const service = new OpenWikiExternalUpdateService({
      publisher: personalPublisher,
      sensitivePolicyPath: path.join(
        repositoryRoot,
        "config",
        "sensitive-files.json",
      ),
      skills,
      sources,
      transactions: personalTransactions,
    });
    return Object.assign(service, {
      recoverStartup: async () =>
        personalTransactions.recoverStartup({
          publish: async (input) => {
            const published = await personalPublisher.publishExternal(input);
            return { wikiRevision: published.after.rootHash };
          },
        }),
    });
  };
  const personalRunStore = new PersonalRunStoreRouter({
    isRunAborted: (run) =>
      new ExternalUpdateTransactionOwner({
        formalWikiPath: run.wikiRoot,
        runtimeDir: run.runtimeRoot,
        security,
      }).isRequestAborted(
        run.runId,
        run.candidate === undefined
          ? undefined
          : {
              transactionId: run.candidate.transactionId,
              bindingHash: run.candidate.candidateBindingHash,
              generation: run.candidate.generation,
            },
      ),
  });
  personalRunStore.bindRoot(runtimeDir);
  const personalLifecycle = new PersonalWikiLifecycle({
    c7: new C7PersonalGateway({
      createExternalUpdate: createPersonalExternalUpdate,
      externalUpdate,
    }),
    rootResolver: new PersonalWikiRootResolver({ repositoryRoot }),
    runStore: personalRunStore,
    claimsResolver: new FilePersonalClaimsResolver(),
    skillAdapter: policy.personalSkill,
    upstreamCommit: PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT,
  });
  const officialLifecycle = new OfficialLifecycleAdapter(personalLifecycle);
  const reviewer = new OpenWikiReviewService({
    formalWikiPath: wikiPath,
    processRunner,
    transactions,
  });
  const recovery = new WikiRecoveryService({
    formalWikiPath: wikiPath,
    runtimeDir,
    security,
  });
  const recoveryTracker = new RecoveryTracker();
  await recoverStaleC7Locks(runtimeDir);
  const startupRecovery = await rehydrateStartupRecovery({
    externalTransactions,
    legacyRecovery: {
      recoverAll: async () => {
        const transactionRecovery =
          await recoverAbandonedTransactions(runtimeDir);
        if (transactionRecovery.state === "restore_failed") {
          recoveryTracker.markRestoreFailed();
          return [];
        }
        const results = await recovery.recoverAll();
        await recoveryTracker.initialize(results, { publisher, reviewer });
        if (recoveryTracker.state === "clean") {
          recoveryTracker.state = await inspectPersistedReviewAttention({
            formalWikiPath: wikiPath,
            runtimeDir,
          });
        }
        return results;
      },
    },
    publisher,
    runtimeDir,
  });
  if (startupRecovery.externalState === "restore_required") {
    recoveryTracker.markRestoreRequired();
  }

  const common = {
    formalWikiPath: wikiPath,
    processRunner,
    runtimeDir,
    sensitivePolicyPath: path.join(
      repositoryRoot,
      "config",
      "sensitive-files.json",
    ),
    skills,
    sources,
    transactions,
  };
  const runtime = new C7OpenWikiRuntime({
    capabilities: policy.capabilities,
    configPath,
    createQuery: (config) => new OpenWikiQueryService({ ...common, config }),
    createUpdate: (config) => {
      const service = new OpenWikiUpdateService({
        ...common,
        config,
        publisher,
        reviewer,
      });
      return {
        update: async (input, signal) => {
          const output = await service.update(input, signal);
          recoveryTracker.observe(output);
          return output;
        },
      };
    },
    credentialPath,
    externalUpdate,
    modelService,
    modelVerifier,
    onExternalRecoveryResolved: async () => {
      const recoveryRoot = path.join(runtimeDir, "recovery");
      const entries = await readdir(recoveryRoot).catch((error) => {
        if (hasErrorCode(error, "ENOENT")) return [];
        throw error;
      });
      if (entries.length > 0) {
        recoveryTracker.markRestoreRequired();
        return;
      }
      recoveryTracker.state = await inspectPersistedReviewAttention({
        formalWikiPath: wikiPath,
        runtimeDir,
      });
    },
    openWikiRoot,
    personalLifecycle: officialLifecycle,
    recoveryState: () => recoveryTracker.state,
    runtimeDir,
    setup,
    skills,
    sources,
    versions,
    visualizer,
    wikiPath,
  });
  return { capabilityGate, runtime: policy.wrap(runtime) };
}

class RecoveryTracker {
  state: C7RuntimeRecoveryState = "recovery_pending";

  markRestoreFailed(): void {
    this.state = "restore_failed";
  }

  markRestoreRequired(): void {
    this.state = "restore_required";
  }

  observe(value: unknown): void {
    if (
      typeof value !== "object" ||
      value === null ||
      !("recoveryState" in value)
    ) {
      return;
    }
    const next = (value as { recoveryState?: unknown }).recoveryState;
    if (
      next === "attention" ||
      next === "clean" ||
      next === "review_pending" ||
      next === "restore_failed" ||
      next === "restore_required"
    ) {
      this.state = next;
    }
  }

  async initialize(
    results: readonly WikiRecoveryResult[],
    dependencies: {
      publisher: WikiPublisher;
      reviewer: OpenWikiReviewService;
    },
  ): Promise<void> {
    if (results.some((result) => result.recoveryState === "restore_failed")) {
      this.state = "restore_failed";
      return;
    }
    for (const result of results) {
      const obligation = result.reviewObligation;
      if (!result.reviewPending) continue;
      if (!result.reviewReady || !obligation) {
        this.state = "review_pending";
        return;
      }
      try {
        const model = {
          providerAccepted: true as const,
          requested: obligation.model,
          sent: obligation.model,
        };
        const review = await dependencies.reviewer.review({
          candidateId: obligation.candidateId,
          instruction: obligation.instruction,
          model,
          reviewedRootHash: obligation.publishedRootHash,
          selectedSkills: obligation.selectedSkills,
          selection: obligation.model,
          sourceManifestHash: obligation.sourceManifestHash,
          ...(obligation.sourceSnapshot
            ? { sourceSnapshot: obligation.sourceSnapshot }
            : {}),
        });
        if (review.verdict === "pass" || review.verdict === "follow_up") {
          await dependencies.publisher.completeReview({
            expectedRootHash: obligation.publishedRootHash,
            journalPath: obligation.journalPath,
          });
        } else {
          await dependencies.publisher.completeReviewWithAttention({
            expectedRootHash: obligation.publishedRootHash,
            issues: review.issues,
            journalPath: obligation.journalPath,
          });
          this.state = "attention";
        }
      } catch {
        this.state = "review_pending";
        return;
      }
    }
    if (this.state !== "attention") this.state = "clean";
  }
}

class MinimalStatusRuntime implements C7ToolRuntime {
  constructor(
    private readonly options: {
      capabilityGate: RuntimeCapabilityGate;
      openWikiRoot: string;
      runtimeDir: string;
      versions: { mcpServer: string; openWiki: string };
      visualizer?: SelfOpenWikiVisualizerStatus;
      wikiPath: string;
    },
  ) {}

  async invoke(name: ToolName): Promise<unknown> {
    if (name !== "openwiki_status") {
      return {
        error: {
          code: "capability_unverified",
          message: "The requested capability is not verified on this build.",
          retryable: false,
        },
        ok: false,
        recovery: { action: "none" },
      };
    }
    let wikiRevision: string;
    try {
      wikiRevision = await withC7Locks(
        this.options.runtimeDir,
        ["wiki"],
        async () =>
          (await snapshotMarkdownTree(this.options.wikiPath)).rootHash,
      );
    } catch (error) {
      if (error instanceof C7ConfigError && error.code === "busy") {
        return {
          error: {
            code: "busy",
            message:
              "The Wiki is busy; minimal status could not read a stable revision.",
            retryable: true,
          },
          ok: false,
          recovery: { action: "retry" },
        };
      }
      throw error;
    }
    return {
      authRequired: false,
      authentication: { status: "not_required" },
      capabilities: this.options.capabilityGate.records(),
      defaultModel: null,
      executionMode: "external_agent",
      externalAgent: { activeTransaction: null, ready: false },
      initialized: false,
      legacyProvider: {
        authRequired: true,
        authentication: { status: "not_configured" },
        available: true,
        defaultModel: null,
        initialized: false,
        verifiedModels: [],
      },
      ok: true,
      paths: {
        openWikiRoot: this.options.openWikiRoot,
        runtimeRoot: this.options.runtimeDir,
        wikiRoot: this.options.wikiPath,
      },
      ...(this.options.visualizer === undefined
        ? {}
        : { visualizer: this.options.visualizer }),
      recovery: {
        action: "none",
        message:
          "Only minimal status is available until capability verification succeeds.",
      },
      runtime: {
        locks: ["operation", "credentials", "config", "wiki", "manifests"].map(
          (lock) => ({ held: false, name: lock }),
        ),
        recoveryState: "recovery_pending",
      },
      staticCapabilities: [
        {
          available: false,
          id: "runtime.verified",
          reason:
            this.options.capabilityGate.failureReason ??
            "Capability evidence is unavailable.",
        },
      ],
      status: "status",
      version: {
        contractSchema: 2,
        ...this.options.versions,
      },
      verifiedModels: [],
      wikiRevision,
    };
  }
}

async function readVersions(repositoryRoot: string, openWikiRoot: string) {
  const [mcpPackage, openWikiPackage] = await Promise.all([
    readPackage(path.join(repositoryRoot, "mcp-server", "package.json")),
    readPackage(path.join(openWikiRoot, "package.json")),
  ]);
  return { mcpServer: mcpPackage, openWiki: openWikiPackage };
}

async function readPackage(packagePath: string): Promise<string> {
  const value = JSON.parse(await readFile(packagePath, "utf8")) as {
    version?: unknown;
  };
  if (typeof value.version !== "string" || value.version.length === 0) {
    throw new Error("Package version is invalid.");
  }
  return value.version;
}

async function hashFile(filePath: string): Promise<string> {
  return `sha256:${createHash("sha256")
    .update(await readFile(filePath))
    .digest("hex")}`;
}

async function containsExternalRecoveryArtifact(
  runtimeDir: string,
): Promise<boolean> {
  const maximumPlanBytes = 4 * 1024 * 1024;
  const recoveryRoot = path.join(runtimeDir, "recovery");
  let recoveryIdentity: DirectoryPathIdentity;
  try {
    recoveryIdentity = await readDirectoryPathIdentity(recoveryRoot);
  } catch (error) {
    if (hasErrorCode(error, "ENOENT")) return false;
    return true;
  }
  let entries;
  try {
    entries = await readdir(recoveryRoot, { withFileTypes: true });
  } catch (error) {
    if (hasErrorCode(error, "ENOENT")) return true;
    throw error;
  }
  const entryNames = entries.map((entry) => entry.name).sort();
  const journalIdentities: {
    readonly identity: DirectoryPathIdentity;
    readonly journalPath: string;
  }[] = [];
  for (const entry of entries) {
    if (
      /^run-external-[a-f0-9]{64}(?:\.initializing(?:\.cleanup)?|\.cleanup)?$/u.test(
        entry.name,
      )
    ) {
      return true;
    }
    if (
      entry.name.startsWith("run-") &&
      (!entry.isDirectory() || entry.isSymbolicLink())
    ) {
      return true;
    }
    if (
      !entry.isDirectory() ||
      entry.isSymbolicLink() ||
      !/^run-[A-Za-z0-9._:-]{8,160}$/u.test(entry.name)
    ) {
      continue;
    }
    const journalPath = path.join(recoveryRoot, entry.name);
    let journalIdentity: DirectoryPathIdentity;
    try {
      journalIdentity = await readDirectoryPathIdentity(journalPath);
    } catch {
      return true;
    }
    journalIdentities.push({ identity: journalIdentity, journalPath });
    const planPath = path.join(journalPath, "plan.json");
    const planStat = await lstat(planPath).catch((error) => {
      if (hasErrorCode(error, "ENOENT")) return null;
      throw error;
    });
    if (planStat === null) continue;
    if (!planStat.isFile() || planStat.isSymbolicLink()) {
      return true;
    }
    const planText = await readStablePlanText(
      planPath,
      planStat,
      maximumPlanBytes,
    );
    if (planText === null || hasExternalPlanDiscriminator(planText)) {
      return true;
    }
    if (
      !(await matchesDirectoryPathIdentity(recoveryRoot, recoveryIdentity)) ||
      !(await matchesDirectoryPathIdentity(journalPath, journalIdentity))
    ) {
      return true;
    }
  }
  if (!(await matchesDirectoryPathIdentity(recoveryRoot, recoveryIdentity))) {
    return true;
  }
  const finalEntries = await readdir(recoveryRoot, {
    withFileTypes: true,
  }).catch(() => null);
  if (
    finalEntries === null ||
    stableStringList(finalEntries.map((entry) => entry.name)) !==
      stableStringList(entryNames)
  ) {
    return true;
  }
  for (const journal of journalIdentities) {
    if (
      !(await matchesDirectoryPathIdentity(
        journal.journalPath,
        journal.identity,
      ))
    ) {
      return true;
    }
  }
  return !(await matchesDirectoryPathIdentity(recoveryRoot, recoveryIdentity));
}

type DirectoryPathIdentity = {
  readonly birthtimeMs: number;
  readonly dev: number;
  readonly ino: number;
};

async function readDirectoryPathIdentity(
  directoryPath: string,
): Promise<DirectoryPathIdentity> {
  const stat = await lstat(directoryPath);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error();
  return { birthtimeMs: stat.birthtimeMs, dev: stat.dev, ino: stat.ino };
}

async function matchesDirectoryPathIdentity(
  directoryPath: string,
  expected: DirectoryPathIdentity,
): Promise<boolean> {
  try {
    const current = await readDirectoryPathIdentity(directoryPath);
    return sameFileIdentity(current, expected);
  } catch {
    return false;
  }
}

function stableStringList(values: readonly string[]): string {
  return JSON.stringify([...values].sort());
}

function hasExternalPlanDiscriminator(value: string): boolean {
  let index = skipJsonWhitespace(value, 0);
  if (value[index] !== "{") return true;
  index = skipJsonWhitespace(value, index + 1);
  if (value[index] === "}") {
    return skipJsonWhitespace(value, index + 1) !== value.length;
  }
  let sawVersion = false;
  let sawExecutionMode = false;
  while (index < value.length) {
    const key = scanJsonString(value, index);
    if (key === null) return true;
    index = skipJsonWhitespace(value, key.end);
    if (value[index] !== ":") return true;
    const scanned = scanJsonValue(value, index + 1);
    if (scanned === null) return true;
    if (key.decoded === "version") {
      if (sawVersion) return true;
      sawVersion = true;
      if (scanned.kind === "number" && Number(scanned.raw) === 4) return true;
    } else if (key.decoded === "executionMode") {
      if (sawExecutionMode) return true;
      sawExecutionMode = true;
      if (scanned.kind === "string" && scanned.decoded === "external_agent") {
        return true;
      }
    }
    index = skipJsonWhitespace(value, scanned.end);
    if (value[index] === "}") {
      return skipJsonWhitespace(value, index + 1) !== value.length;
    }
    if (value[index] !== ",") return true;
    index = skipJsonWhitespace(value, index + 1);
    if (value[index] === "}") return true;
  }
  return true;
}

async function readStablePlanText(
  planPath: string,
  beforePath: {
    readonly birthtimeMs: number;
    readonly dev: number;
    readonly ino: number;
    readonly size: number;
  },
  maximumBytes: number,
): Promise<string | null> {
  const handle = await open(planPath, "r");
  try {
    const beforeHandle = await handle.stat();
    if (
      !beforeHandle.isFile() ||
      !sameFileIdentity(beforePath, beforeHandle) ||
      beforeHandle.size > maximumBytes
    ) {
      return null;
    }
    const bytes = Buffer.allocUnsafe(maximumBytes + 1);
    let length = 0;
    while (length < bytes.byteLength) {
      const read = await handle.read(
        bytes,
        length,
        bytes.byteLength - length,
        length,
      );
      if (read.bytesRead === 0) break;
      length += read.bytesRead;
    }
    const [afterHandle, afterPath] = await Promise.all([
      handle.stat(),
      lstat(planPath),
    ]);
    if (
      !afterHandle.isFile() ||
      !afterPath.isFile() ||
      afterPath.isSymbolicLink() ||
      !sameFileIdentity(beforePath, beforeHandle) ||
      !sameFileIdentity(beforeHandle, afterHandle) ||
      !sameFileIdentity(afterHandle, afterPath) ||
      beforePath.size !== beforeHandle.size ||
      beforeHandle.size !== afterHandle.size ||
      afterHandle.size !== afterPath.size ||
      length !== afterHandle.size ||
      length > maximumBytes
    ) {
      return null;
    }
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(
        bytes.subarray(0, length),
      );
    } catch {
      return null;
    }
  } finally {
    await handle.close();
  }
}

function sameFileIdentity(
  left: {
    readonly birthtimeMs: number;
    readonly dev: number;
    readonly ino: number;
  },
  right: {
    readonly birthtimeMs: number;
    readonly dev: number;
    readonly ino: number;
  },
): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.birthtimeMs === right.birthtimeMs
  );
}

type JsonValueScan =
  | { readonly end: number; readonly kind: "number"; readonly raw: string }
  | { readonly decoded: string; readonly end: number; readonly kind: "string" }
  | { readonly end: number; readonly kind: "other" };

type JsonFrame =
  | {
      readonly kind: "array";
      state: "comma_or_end" | "value" | "value_or_end";
    }
  | {
      readonly kind: "object";
      state: "colon" | "comma_or_end" | "key" | "key_or_end" | "value";
    };

function scanJsonValue(value: string, start: number): JsonValueScan | null {
  const index = skipJsonWhitespace(value, start);
  const character = value[index];
  if (character === '"') {
    const scanned = scanJsonString(value, index);
    return scanned === null ? null : { ...scanned, kind: "string" };
  }
  const number = scanJsonNumber(value, index);
  if (number !== null) return number;
  for (const literal of ["true", "false", "null"] as const) {
    if (value.startsWith(literal, index)) {
      return { end: index + literal.length, kind: "other" };
    }
  }
  if (character !== "{" && character !== "[") return null;
  const stack: JsonFrame[] = [
    character === "{"
      ? { kind: "object", state: "key_or_end" }
      : { kind: "array", state: "value_or_end" },
  ];
  let cursor = index + 1;
  while (stack.length > 0) {
    const frame = stack[stack.length - 1]!;
    cursor = skipJsonWhitespace(value, cursor);
    if (frame.kind === "object") {
      if (frame.state === "key_or_end" || frame.state === "key") {
        if (frame.state === "key_or_end" && value[cursor] === "}") {
          stack.pop();
          cursor += 1;
          continue;
        }
        const key = scanJsonString(value, cursor);
        if (key === null) return null;
        cursor = key.end;
        frame.state = "colon";
        continue;
      }
      if (frame.state === "colon") {
        cursor = skipJsonWhitespace(value, cursor);
        if (value[cursor] !== ":") return null;
        cursor += 1;
        frame.state = "value";
        continue;
      }
      if (frame.state === "value") {
        frame.state = "comma_or_end";
        const nested = beginNestedJsonValue(value, cursor, stack);
        if (nested === null) return null;
        cursor = nested;
        continue;
      }
      if (value[cursor] === "}") {
        stack.pop();
        cursor += 1;
        continue;
      }
      if (value[cursor] !== ",") return null;
      cursor += 1;
      frame.state = "key";
      continue;
    }
    if (frame.state === "value_or_end" || frame.state === "value") {
      if (frame.state === "value_or_end" && value[cursor] === "]") {
        stack.pop();
        cursor += 1;
        continue;
      }
      frame.state = "comma_or_end";
      const nested = beginNestedJsonValue(value, cursor, stack);
      if (nested === null) return null;
      cursor = nested;
      continue;
    }
    if (value[cursor] === "]") {
      stack.pop();
      cursor += 1;
      continue;
    }
    if (value[cursor] !== ",") return null;
    cursor += 1;
    frame.state = "value";
  }
  return { end: cursor, kind: "other" };
}

function beginNestedJsonValue(
  value: string,
  start: number,
  stack: JsonFrame[],
): number | null {
  const index = skipJsonWhitespace(value, start);
  if (value[index] === "{") {
    stack.push({ kind: "object", state: "key_or_end" });
    return index + 1;
  }
  if (value[index] === "[") {
    stack.push({ kind: "array", state: "value_or_end" });
    return index + 1;
  }
  if (value[index] === '"') return scanJsonString(value, index)?.end ?? null;
  const number = scanJsonNumber(value, index);
  if (number !== null) return number.end;
  for (const literal of ["true", "false", "null"] as const) {
    if (value.startsWith(literal, index)) return index + literal.length;
  }
  return null;
}

function scanJsonString(
  value: string,
  start: number,
): { readonly decoded: string; readonly end: number } | null {
  if (value[start] !== '"') return null;
  let index = start + 1;
  while (index < value.length) {
    const code = value.charCodeAt(index);
    if (code === 0x22) {
      const end = index + 1;
      try {
        const decoded = JSON.parse(value.slice(start, end)) as unknown;
        return typeof decoded === "string" ? { decoded, end } : null;
      } catch {
        return null;
      }
    }
    if (code < 0x20) return null;
    if (code !== 0x5c) {
      index += 1;
      continue;
    }
    index += 1;
    const escaped = value[index];
    if (escaped === "u") {
      if (!/^[a-fA-F0-9]{4}$/u.test(value.slice(index + 1, index + 5))) {
        return null;
      }
      index += 5;
      continue;
    }
    if (escaped === undefined || !'"\\/bfnrt'.includes(escaped)) return null;
    index += 1;
  }
  return null;
}

function scanJsonNumber(value: string, start: number): JsonValueScan | null {
  const pattern = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/uy;
  pattern.lastIndex = start;
  const match = pattern.exec(value);
  return match === null
    ? null
    : { end: pattern.lastIndex, kind: "number", raw: match[0] };
}

function skipJsonWhitespace(value: string, start: number): number {
  let index = start;
  while (
    value[index] === " " ||
    value[index] === "\n" ||
    value[index] === "\r" ||
    value[index] === "\t"
  ) {
    index += 1;
  }
  return index;
}

function hasErrorCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === code
  );
}

function isWithin(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}

function pathsEqual(left: string, right: string): boolean {
  return process.platform === "win32"
    ? path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase()
    : path.resolve(left) === path.resolve(right);
}
