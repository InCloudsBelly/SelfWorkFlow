import {
  readRuntimeConfigState,
  withC7Locks,
  writeRuntimeConfigAtomic,
  type RuntimeConfig,
  type VersionedRuntimeConfig,
} from "./config.js";
import {
  createCredentialStoreHomeLease,
  readManagedCredentialEnv,
  readCredentialStore,
  writeCredentialStoreAtomic,
  type PrivatePathSecurity,
  type TemporaryOpenWikiHome,
} from "./credential-store.js";
import type { EphemeralCredentialVault } from "./auth.js";
import {
  type ModelSelection,
  type ModelVerificationEvidence,
  type ModelVerifier,
} from "./model-verification.js";
import {
  createModelConfirmation,
  SetupAttemptManager,
  type OAuthAttemptFactory,
} from "./setup-attempt.js";

type SetupPersistenceContext = {
  config: RuntimeConfig | undefined;
  configVersion: string;
  credentialVersion: string;
};

type RuntimeModelServiceOptions = {
  configPath: string;
  credentialPath: string;
  now?(): number;
  privatePathSecurity: PrivatePathSecurity;
  runtimeDir: string;
  vault: EphemeralCredentialVault;
};

export class RuntimeModelService {
  private readonly configPath: string;
  private readonly credentialPath: string;
  private readonly now: () => number;
  private readonly privatePathSecurity: PrivatePathSecurity;
  private readonly persistedReferences = new Set<string>();
  private readonly runtimeDir: string;
  private readonly verificationCredentialTransitions = new Map<
    string,
    { from: string; to: string }
  >();
  private readonly vault: EphemeralCredentialVault;

  constructor(options: RuntimeModelServiceOptions) {
    this.configPath = options.configPath;
    this.credentialPath = options.credentialPath;
    this.now = options.now ?? Date.now;
    this.privatePathSecurity = options.privatePathSecurity;
    this.runtimeDir = options.runtimeDir;
    this.vault = options.vault;
  }

  async captureSetupState(): Promise<SetupPersistenceContext> {
    const [config, credential] = await Promise.all([
      readRuntimeConfigState(this.configPath),
      readCredentialStore(this.credentialPath),
    ]);
    return {
      config: config.config,
      configVersion: config.version,
      credentialVersion: credential.version,
    };
  }

  async persistAuthorizedCredential(
    credentialReference: string,
    contextValue: unknown,
  ): Promise<void> {
    const context = assertSetupContext(contextValue);
    await this.vault.persist(credentialReference, async (credential) => {
      const written = await writeCredentialStoreAtomic(
        this.runtimeDir,
        this.credentialPath,
        credential,
        context.credentialVersion,
        this.privatePathSecurity,
      );
      context.credentialVersion = written.version;
    });
    this.persistedReferences.add(credentialReference);
  }

  async completeSetup(input: {
    credentialReference: string;
    evidence: ModelVerificationEvidence;
    persistenceContext?: unknown;
    selection: ModelSelection;
  }): Promise<void> {
    const context = assertSetupContext(input.persistenceContext);
    assertModelEvidence(input.selection, input.evidence);
    if (!this.persistedReferences.has(input.credentialReference)) {
      throw new Error("Setup credential reference is not persisted.");
    }

    const config: RuntimeConfig = {
      defaultModel: input.selection,
      generation: (context.config?.generation ?? 0) + 1,
      initialized: true,
      provider: "openai-chatgpt",
      schemaVersion: 1,
      verifiedModels: [verifiedRecord(input.evidence, this.now())],
    };
    await writeRuntimeConfigAtomic(
      this.configPath,
      config,
      context.configVersion,
      {
        securePrivatePath: this.privatePathSecurity.securePrivatePath.bind(
          this.privatePathSecurity,
        ),
      },
    );
    this.persistedReferences.delete(input.credentialReference);
    this.verificationCredentialTransitions.delete(input.credentialReference);
  }

  async resolveOpenWikiHome(
    credentialReference: string,
  ): Promise<TemporaryOpenWikiHome> {
    if (
      credentialReference !== "runtime-credential" &&
      !this.persistedReferences.has(credentialReference)
    ) {
      throw new Error(
        "Credential reference is not available for verification.",
      );
    }
    const before = await readCredentialStore(this.credentialPath);
    if (!before.credential) {
      throw new Error("Managed ChatGPT credentials are unavailable.");
    }
    const lease = await createCredentialStoreHomeLease(
      this.runtimeDir,
      this.credentialPath,
      this.privatePathSecurity,
    );
    const afterLeaseCreation = await readCredentialStore(this.credentialPath);
    if (afterLeaseCreation.version !== before.version) {
      await lease.cleanup();
      throw new Error(
        "ChatGPT credentials changed while preparing verification.",
      );
    }
    return {
      cleanup: lease.cleanup,
      finalize: async () => {
        const temporaryCredential = await readManagedCredentialEnv(lease.path);
        const refreshExpected = !credentialsEqual(
          before.credential!,
          temporaryCredential,
        );
        const committed = await lease.finalize?.();
        if (refreshExpected) {
          if (!committed || committed.fromVersion !== before.version) {
            throw new Error(
              "Model verification credential refresh evidence is invalid.",
            );
          }
          this.verificationCredentialTransitions.set(credentialReference, {
            from: committed.fromVersion,
            to: committed.toVersion,
          });
        } else if (committed) {
          throw new Error(
            "Model verification reported an unexpected credential refresh.",
          );
        }
        return committed;
      },
      path: lease.path,
    };
  }

  async verifyAndSetDefault(
    input: {
      confirmation: string;
      selection: ModelSelection;
    },
    verifier: ModelVerifier,
  ): Promise<{
    config: VersionedRuntimeConfig;
    model: ModelVerificationEvidence;
  }> {
    if (input.confirmation !== createModelConfirmation(input.selection)) {
      throw new Error(
        "Default-model confirmation does not match the selection.",
      );
    }

    return withC7Locks(this.runtimeDir, ["operation"], async () => {
      const [configState, credentialState] = await Promise.all([
        readRuntimeConfigState(this.configPath),
        readCredentialStore(this.credentialPath),
      ]);
      if (!configState.config || !credentialState.credential) {
        throw new Error("OpenWiki setup is incomplete.");
      }

      this.verificationCredentialTransitions.delete("runtime-credential");
      const evidence = await verifier.verify(
        input.selection,
        "runtime-credential",
      );
      assertModelEvidence(input.selection, evidence);

      const credentialAfterSmoke = await readCredentialStore(
        this.credentialPath,
      );
      if (credentialAfterSmoke.version !== credentialState.version) {
        const transition =
          this.verificationCredentialTransitions.get("runtime-credential");
        this.verificationCredentialTransitions.delete("runtime-credential");
        if (
          transition?.from !== credentialState.version ||
          transition.to !== credentialAfterSmoke.version
        ) {
          throw new Error(
            "ChatGPT credentials changed during model verification.",
          );
        }
      }

      const withoutCurrent = configState.config.verifiedModels.filter(
        (candidate) =>
          candidate.model !== input.selection.model ||
          candidate.reasoningEffort !== input.selection.reasoningEffort,
      );
      const next: RuntimeConfig = {
        ...configState.config,
        defaultModel: input.selection,
        generation: configState.config.generation + 1,
        verifiedModels: [
          ...withoutCurrent,
          verifiedRecord(evidence, this.now()),
        ],
      };
      const config = await writeRuntimeConfigAtomic(
        this.configPath,
        next,
        configState.version,
        {
          securePrivatePath: this.privatePathSecurity.securePrivatePath.bind(
            this.privatePathSecurity,
          ),
        },
      );
      return { config, model: evidence };
    });
  }

  runExclusive<T>(operation: () => Promise<T>): Promise<T> {
    return withC7Locks(this.runtimeDir, ["operation"], operation);
  }
}

function credentialsEqual(
  left: NonNullable<
    Awaited<ReturnType<typeof readCredentialStore>>["credential"]
  >,
  right: NonNullable<
    Awaited<ReturnType<typeof readCredentialStore>>["credential"]
  >,
): boolean {
  return (
    left.access === right.access &&
    left.refresh === right.refresh &&
    left.expiresAtMs === right.expiresAtMs &&
    left.accountId === right.accountId &&
    (left.email ?? null) === (right.email ?? null) &&
    (left.planType ?? null) === (right.planType ?? null)
  );
}

export function createRuntimeSetupManager(options: {
  createId?(): string;
  now?(): number;
  oauth: OAuthAttemptFactory;
  service: RuntimeModelService;
  ttlMs?: number;
  verifier: ModelVerifier;
}): SetupAttemptManager {
  return new SetupAttemptManager({
    capturePersistenceContext: () => options.service.captureSetupState(),
    completeSetup: (input) => options.service.completeSetup(input),
    createId: options.createId,
    now: options.now,
    oauth: options.oauth,
    persistAuthorizedCredential: (reference, context) =>
      options.service.persistAuthorizedCredential(reference, context),
    runExclusive: (operation) => options.service.runExclusive(operation),
    ttlMs: options.ttlMs,
    verifier: options.verifier,
  });
}

function assertSetupContext(value: unknown): SetupPersistenceContext {
  if (
    typeof value !== "object" ||
    value === null ||
    !("configVersion" in value) ||
    typeof value.configVersion !== "string" ||
    !("credentialVersion" in value) ||
    typeof value.credentialVersion !== "string" ||
    !("config" in value)
  ) {
    throw new Error("Setup persistence context is invalid.");
  }
  return value as SetupPersistenceContext;
}

function assertModelEvidence(
  selection: ModelSelection,
  evidence: ModelVerificationEvidence,
): void {
  if (
    evidence.providerAccepted !== true ||
    evidence.requested.model !== selection.model ||
    evidence.requested.reasoningEffort !== selection.reasoningEffort ||
    evidence.sent.model !== selection.model ||
    evidence.sent.reasoningEffort !== selection.reasoningEffort
  ) {
    throw new Error(
      "Model verification evidence does not match the selection.",
    );
  }
}

function verifiedRecord(
  evidence: ModelVerificationEvidence,
  now: number,
): RuntimeConfig["verifiedModels"][number] {
  return {
    model: evidence.sent.model,
    providerAccepted: true,
    ...(evidence.providerReportedModel
      ? { providerReportedModel: evidence.providerReportedModel }
      : {}),
    reasoningEffort: evidence.sent.reasoningEffort,
    verifiedAt: new Date(now).toISOString(),
  };
}
