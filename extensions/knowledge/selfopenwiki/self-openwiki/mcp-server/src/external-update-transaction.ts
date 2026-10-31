import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
} from "node:fs/promises";
import path from "node:path";
import { confirmedWikiPathsSchema, toolInputSchemas } from "./contracts.js";
import { C7ConfigError, withC7Locks, type C7LockName } from "./config.js";
import {
  createExternalUpdateState,
  computeExternalTerminalResultHash,
  ExternalUpdateTerminalStore,
  parseExternalTerminalPayload,
  recordExternalUpdateFailure,
  readExternalUpdateState,
  transitionExternalUpdateState,
  type ExternalUpdateState,
  type ExternalUpdateTerminalTombstone,
  type ExternalTerminalPayload,
  type VersionedExternalUpdateState,
} from "./external-update-state.js";
import { copyMarkdownTree, snapshotMarkdownTree } from "./snapshot.js";
import {
  computeSkillPackage,
  verifySelectedC7Skills,
  type SelectedC7Skills,
} from "./skills.js";
import { hashSourceSnapshotTree } from "./sources.js";
import {
  computeConfirmedWikiPathsHash,
  computeExternalPublishRunId,
  parseExternalWikiPublishPlan,
  type ExternalWikiPublishPlan,
} from "./publish.js";
import type { MarkdownTreeSnapshot } from "./snapshot.js";
import type { TransactionPathSecurity } from "./transaction.js";
import {
  verifyStablePublication,
  verifyStablePublicationAbort,
} from "./stable-publication.js";
import { validateWikiCandidate } from "./validation.js";

const REQUEST_DOMAIN = "kg-c7:external-request-package:v1";
const BINDING_DOMAIN = "kg-c7:external-update-binding:v1";
const HARD_RULE_DOMAIN = "kg-c7:external-hard-rule-package:v1";
const RESULT_CONTRACT_DOMAIN = "kg-c7:external-candidate-result-contract:v1";
const CANDIDATE_RECEIPT_DOMAIN = "kg-c7:external-candidate-receipt:v1";
const REVIEW_PACKAGE_DOMAIN = "kg-c7:external-review-package:v1";
const REVIEW_RESULT_CONTRACT_DOMAIN =
  "kg-c7:external-review-result-contract:v1";
const REVIEW_RECEIPT_DOMAIN = "kg-c7:external-review-receipt:v1";

export type ExternalUpdateMaterial = {
  readonly id: string;
  readonly source?: string;
  readonly content: string;
};

export type StartExternalUpdateInput = {
  readonly requestId: string;
  readonly sourceManifestId: string | null;
  readonly instruction: string;
  readonly materials?: readonly ExternalUpdateMaterial[];
  readonly expectedWikiRevision: string;
  readonly confirmedWikiPaths: readonly string[];
  readonly skills: SelectedC7Skills;
  readonly hardRulePackage: Buffer;
  readonly candidateResultContract: Buffer;
  readonly sourceSnapshot?: {
    readonly manifestHash: string;
    readonly snapshotPath: string;
    readonly snapshotTreeHash: string;
  };
};

export type ExternalWorkPackage = {
  readonly version: 1;
  readonly transactionId: string;
  readonly generation: number;
  readonly beforeWikiRevision: string;
  readonly sourceManifestHash: string | null;
  readonly sourceTreeHash: string | null;
  readonly skillAggregateHash: string;
  readonly confirmedWikiPaths: readonly string[];
  readonly requestPackage: {
    readonly path: string;
    readonly packageHash: string;
  };
  readonly bindingHash: string;
  readonly candidate: {
    readonly workspaceId: string;
    readonly rootPath: string;
    readonly permissions: readonly ["read", "list", "write"];
    readonly allowedChangedPaths: readonly string[];
  };
  readonly sources: null | {
    readonly rootPath: string;
    readonly permissions: readonly ["read", "list"];
  };
  readonly rules: {
    readonly hardRulePackage: {
      readonly path: string;
      readonly packageHash: string;
    };
    readonly skills: readonly {
      readonly id: string;
      readonly category: "base" | "specialized";
      readonly loadOrder: "base_always_first" | "request_order";
      readonly packageHash: string;
      readonly rootPath: string;
    }[];
    readonly candidateResultContract: {
      readonly path: string;
      readonly schemaHash: string;
    };
  };
};

export type ExternalUpdateWorkspace = {
  readonly state: ExternalUpdateState;
  readonly stateVersion: string;
  readonly workPackage: ExternalWorkPackage;
};

export type ExternalUpdateStartResult =
  | ExternalUpdateWorkspace
  | {
      readonly kind: "terminal";
      readonly terminalPayload: ExternalTerminalPayload;
    };

export type ExternalUpdateResumeResult =
  | ({ readonly kind: "candidate_writable" } & ExternalUpdateWorkspace)
  | {
      readonly kind: "review_ready";
      readonly state: ExternalUpdateState;
      readonly stateVersion: string;
      readonly reviewPackage: ExternalReviewPackage;
      readonly reviewPackageHash: string;
    }
  | {
      readonly kind: "attention";
      readonly state: ExternalUpdateState;
      readonly stateVersion: string;
      readonly issues?: ExternalCandidateReceipt["issues"];
      readonly questions?: ExternalCandidateReceipt["questions"];
    }
  | {
      readonly kind: "terminal";
      readonly terminalPayload: ExternalTerminalPayload;
    };

export type ExternalCandidateReceipt = {
  readonly type: "external_candidate_receipt";
  readonly version: 1;
  readonly transactionId: string;
  readonly generation: number;
  readonly bindingHash: string;
  readonly writerExecutionId: string;
  readonly classification: "minor" | "provisional" | "blocking";
  readonly issues: readonly {
    readonly code: string;
    readonly message: string;
    readonly page?: string;
    readonly severity: "minor" | "provisional" | "blocking";
  }[];
  readonly questions: readonly string[];
  readonly summary: string;
};

export type ExternalReviewPreparationResult =
  | {
      readonly kind: "needs_clarification";
      readonly state: ExternalUpdateState;
      readonly stateVersion: string;
      readonly issues: ExternalCandidateReceipt["issues"];
      readonly questions: ExternalCandidateReceipt["questions"];
    }
  | {
      readonly kind: "review_ready";
      readonly state: ExternalUpdateState;
      readonly stateVersion: string;
      readonly reviewPackage: ExternalReviewPackage;
      readonly reviewPackageHash: string;
    };

export type ExternalReviewPackage = {
  readonly version: 1;
  readonly transactionId: string;
  readonly generation: number;
  readonly bindingHash: string;
  readonly candidateRootHash: string;
  readonly candidateReceiptHash: string;
  readonly requestPackage: {
    readonly path: string;
    readonly packageHash: string;
  };
  readonly sourceManifestHash: string | null;
  readonly skillAggregateHash: string;
  readonly confirmedWikiPaths: readonly string[];
  readonly candidate: {
    readonly rootPath: string;
    readonly permissions: readonly ["read", "list"];
  };
  readonly rules: {
    readonly hardRulePackage: {
      readonly path: string;
      readonly packageHash: string;
    };
    readonly skills: ExternalUpdateState["skills"];
    readonly reviewResultContract: {
      readonly path: string;
      readonly schemaHash: string;
    };
  };
};

export type ExternalReviewSubmissionResult =
  | {
      readonly kind: "repair_ready";
      readonly state: ExternalUpdateState;
      readonly stateVersion: string;
      readonly reviewReceiptHash: string;
      readonly issues: readonly ExternalReviewIssue[];
    }
  | {
      readonly kind: "attention";
      readonly state: ExternalUpdateState;
      readonly stateVersion: string;
      readonly reviewReceiptHash: string;
      readonly issues: readonly ExternalReviewIssue[];
      readonly questions: readonly string[];
    }
  | {
      readonly kind: "terminal";
      readonly terminalPayload: ExternalTerminalPayload;
    };

export type ExternalReviewPublishInput = {
  readonly after: MarkdownTreeSnapshot;
  readonly before: MarkdownTreeSnapshot;
  readonly candidateWikiPath: string;
  readonly plan: ExternalWikiPublishPlan;
};

type ExternalReviewIssue = {
  readonly code: string;
  readonly message: string;
  readonly page?: string;
  readonly severity: "minor" | "provisional" | "blocking";
};

export class C7ExternalUpdateTransactionError extends Error {
  constructor(
    readonly code:
      | "busy"
      | "transaction_invalid"
      | "restore_required"
      | "validation_failed"
      | "wiki_conflict",
    message: string,
  ) {
    super(message);
    this.name = "C7ExternalUpdateTransactionError";
  }
}

export class ExternalUpdateTransactionOwner {
  private readonly runtimeDir: string;
  private canonicalRuntimeDir: string | null = null;
  private runtimeBindingPromise: Promise<{
    canonicalPath: string;
    identity: DirectoryIdentity;
  }> | null = null;
  private readonly formalWikiPath: string;
  private readonly security: TransactionPathSecurity;
  private readonly createTransactionId: () => string;
  private readonly createWorkspaceId: () => string;
  private readonly now: () => Date;
  private readonly faultInjector: (
    point:
      | "after_terminal_state"
      | "after_tombstone"
      | "after_transaction_cleanup"
      | "after_active_pointer_cleanup"
      | "after_review_package"
      | "before_review_receipt"
      | "after_review_receipt"
      | "before_review_cas"
      | "after_review_cas"
      | "after_orphan_journal_quarantine",
  ) => void | Promise<void>;

  constructor(options: {
    runtimeDir: string;
    formalWikiPath: string;
    security: TransactionPathSecurity;
    createTransactionId?(): string;
    createWorkspaceId?(): string;
    now?(): Date;
    faultInjector?(
      point:
        | "after_terminal_state"
        | "after_tombstone"
        | "after_transaction_cleanup"
        | "after_active_pointer_cleanup"
        | "after_review_package"
        | "before_review_receipt"
        | "after_review_receipt"
        | "before_review_cas"
        | "after_review_cas"
        | "after_orphan_journal_quarantine",
    ): void | Promise<void>;
  }) {
    if (
      !path.isAbsolute(options.runtimeDir) ||
      !path.isAbsolute(options.formalWikiPath)
    ) {
      throw invalidTransaction();
    }
    this.runtimeDir = path.resolve(options.runtimeDir);
    this.formalWikiPath = path.resolve(options.formalWikiPath);
    this.security = options.security;
    this.createTransactionId =
      options.createTransactionId ?? (() => `external-${randomUUID()}`);
    this.createWorkspaceId =
      options.createWorkspaceId ?? (() => `workspace-${randomUUID()}`);
    this.now = options.now ?? (() => new Date());
    this.faultInjector = options.faultInjector ?? (() => undefined);
  }

  async start(
    input: StartExternalUpdateInput,
  ): Promise<ExternalUpdateStartResult> {
    return this.withOperationLock(() => this.startLocked(input));
  }

  async recoverUncommittedStart(
    input: StartExternalUpdateInput,
    verifyUnboundStart: () => Promise<boolean>,
  ): Promise<void> {
    return this.withLocks(["operation", "wiki"], async () => {
      try {
        const normalized = validateStartInput(input);
        if (!(await verifyUnboundStart())) throw restoreRequired();
        if (await existsWithoutFollowingLinks(this.activePath()))
          throw restoreRequired();
        const updatesRoot = this.updatesRoot();
        const entries = await readdir(updatesRoot, { withFileTypes: true });
        const pending = entries.filter(
          (entry) => entry.name !== "terminal-index.json",
        );
        if (
          pending.length !== 1 ||
          !pending[0]!.isDirectory() ||
          pending[0]!.isSymbolicLink() ||
          !validId(pending[0]!.name)
        )
          throw restoreRequired();
        const transactionId = pending[0]!.name;
        const terminals = this.terminalStore();
        if (
          (await terminals.find(transactionId)) !== null ||
          (await terminals.findByRequestIdHash(
            hashCanonical("kg-c7:external-request-id:v1", normalized.requestId),
          )) !== null
        )
          throw restoreRequired();
        const transactionRoot = path.join(updatesRoot, transactionId);
        if (!isStrictDescendant(updatesRoot, transactionRoot))
          throw restoreRequired();
        const identity = await inspectRealDirectoryIdentity(transactionRoot);
        if (
          await existsWithoutFollowingLinks(
            path.join(transactionRoot, "state.json"),
          )
        )
          throw restoreRequired();

        const before = await snapshotMarkdownTree(this.formalWikiPath);
        if (before.rootHash !== normalized.expectedWikiRevision)
          throw restoreRequired();
        const expected = new Map<string, { hash: string; size: number }>();
        const addBytes = (relative: string, bytes: Buffer) =>
          expected.set(relative, {
            hash: hashBytes(bytes),
            size: bytes.length,
          });
        const requestBytes = startRequestPackageBytes(normalized);
        addBytes("immutable/request.json", requestBytes);
        addBytes("immutable/hard-rules.md", normalized.hardRulePackage);
        addBytes(
          "immutable/candidate-result-contract.json",
          normalized.candidateResultContract,
        );
        for (const file of before.files)
          expected.set(`generations/1/candidate/${file.relativePath}`, file);
        for (const [index, skill] of normalized.skills.skills.entries()) {
          for (const file of skill.files)
            addBytes(
              `immutable/skills/${String(index).padStart(3, "0")}-${skill.id}/${file.relativePath}`,
              file.bytes,
            );
        }
        const verifiedSource =
          normalized.sourceSnapshot === undefined
            ? undefined
            : {
                rootPath: normalized.sourceSnapshot.snapshotPath,
                identity: await inspectRealDirectoryIdentity(
                  normalized.sourceSnapshot.snapshotPath,
                ),
                treeHash: normalized.sourceSnapshot.snapshotTreeHash,
              };
        if (normalized.sourceSnapshot !== undefined) {
          if (
            (await hashSourceSnapshotTree(
              normalized.sourceSnapshot.snapshotPath,
            )) !== normalized.sourceSnapshot.snapshotTreeHash
          )
            throw restoreRequired();
          for (const [relative, fingerprint] of await fingerprintRegularTree(
            normalized.sourceSnapshot.snapshotPath,
          )) {
            expected.set(`immutable/sources/${relative}`, fingerprint);
          }
          if (
            (await hashSourceSnapshotTree(
              normalized.sourceSnapshot.snapshotPath,
            )) !== normalized.sourceSnapshot.snapshotTreeHash
          )
            throw restoreRequired();
        }
        const validate = async () => {
          if (!(await verifyUnboundStart())) throw restoreRequired();
          await assertNoOtherRecoveryEvidence(
            this.canonicalRuntimeDir ?? this.runtimeDir,
            verifiedSource,
            expected,
          );
          await assertDirectoryIdentity(transactionRoot, identity);
          await assertExpectedInitializationTree(transactionRoot, expected);
          const candidate = await snapshotMarkdownTree(
            path.join(transactionRoot, "generations", "1", "candidate"),
          );
          if (
            candidate.rootHash !== before.rootHash ||
            (await snapshotMarkdownTree(this.formalWikiPath)).rootHash !==
              before.rootHash
          )
            throw restoreRequired();
        };
        await validate();
        // No issued binding is reconstructed. Keep every byte, then start anew
        // from the currently verified sources/Skills through the ordinary path.
        const retainedRoot = path.join(
          this.canonicalRuntimeDir ?? this.runtimeDir,
          "tmp",
        );
        const previousRetainedIdentity =
          await inspectOptionalRealDirectory(retainedRoot);
        await this.ensureRoot(retainedRoot);
        if (previousRetainedIdentity !== null)
          await assertDirectoryIdentity(retainedRoot, previousRetainedIdentity);
        const retainedIdentity =
          await inspectRealDirectoryIdentity(retainedRoot);
        const target = path.join(
          retainedRoot,
          `uncommitted-start-${transactionId}-${randomUUID()}`,
        );
        if (
          !isStrictDescendant(retainedRoot, target) ||
          retainedIdentity.dev !== identity.dev ||
          (await existsWithoutFollowingLinks(target))
        )
          throw restoreRequired();
        await validate();
        await assertDirectoryIdentity(retainedRoot, retainedIdentity);
        await rename(transactionRoot, target);
        await assertDirectoryIdentity(target, {
          ...identity,
          realPath: target,
        });
      } catch {
        throw restoreRequired();
      }
    });
  }

  private async startLocked(
    input: StartExternalUpdateInput,
  ): Promise<ExternalUpdateStartResult> {
    await this.reconcileTerminalCleanup();
    const normalized = validateStartInput(input);
    const inputHash = computeStartInputHash({
      requestId: normalized.requestId,
      sourceManifestId: normalized.sourceManifestId,
      instruction: normalized.instruction,
      materials: normalized.materials,
      expectedWikiRevision: normalized.expectedWikiRevision,
      confirmedWikiPaths: normalized.confirmedWikiPaths,
      sourceManifestHash: normalized.sourceSnapshot?.manifestHash ?? null,
      sourceTreeHash: normalized.sourceSnapshot?.snapshotTreeHash ?? null,
      skillAggregateHash: normalized.skills.aggregateHash,
      skills: normalized.skills.skills.map((skill) => ({
        id: skill.id,
        packageHash: skill.packageHash,
      })),
      hardRulePackageHash: hashDomainBytes(
        HARD_RULE_DOMAIN,
        normalized.hardRulePackage,
      ),
      candidateResultContractSchemaHash: hashDomainBytes(
        RESULT_CONTRACT_DOMAIN,
        normalized.candidateResultContract,
      ),
    });
    const existing = await this.readActivePointer();
    if (existing !== null) {
      const active = await this.readCurrent(existing.transactionId);
      if (
        active.state.requestId === normalized.requestId &&
        active.state.inputHash === inputHash
      )
        return active;
      throw new C7ExternalUpdateTransactionError(
        "busy",
        "Another external update is already active.",
      );
    }
    const retained = await this.terminalStore().findByRequestIdHash(
      hashCanonical("kg-c7:external-request-id:v1", normalized.requestId),
    );
    if (retained !== null) {
      if (retained.inputHash !== inputHash) throw invalidTransaction();
      return { kind: "terminal", terminalPayload: retained.payload };
    }

    const transactionId = this.createTransactionId();
    const workspaceId = this.createWorkspaceId();
    if (!validId(transactionId) || !validId(workspaceId))
      throw invalidTransaction();
    const updatesRoot = this.updatesRoot();
    const transactionRoot = path.join(updatesRoot, transactionId);
    if (!isStrictDescendant(updatesRoot, transactionRoot))
      throw invalidTransaction();
    let created = false;
    try {
      await this.ensureRoot(updatesRoot);
      await mkdir(transactionRoot, { mode: 0o700 });
      created = true;
      await this.security.securePrivatePath({
        directory: true,
        targetPath: transactionRoot,
      });
      const immutableRoot = path.join(transactionRoot, "immutable");
      const skillRoot = path.join(immutableRoot, "skills");
      const generationRoot = path.join(transactionRoot, "generations", "1");
      const candidateRoot = path.join(generationRoot, "candidate");
      for (const directory of [
        immutableRoot,
        skillRoot,
        generationRoot,
        candidateRoot,
      ]) {
        await mkdir(directory, { mode: 0o700, recursive: true });
        await this.security.securePrivatePath({
          directory: true,
          targetPath: directory,
        });
      }

      const before = await snapshotMarkdownTree(this.formalWikiPath);
      if (before.rootHash !== normalized.expectedWikiRevision) {
        throw new C7ExternalUpdateTransactionError(
          "wiki_conflict",
          "The formal Wiki revision changed before the external update began.",
        );
      }
      await copyMarkdownTree(this.formalWikiPath, candidateRoot, before);
      await secureTree(candidateRoot, this.security);

      const requestPackageBytes = startRequestPackageBytes(normalized);
      const requestPackageHash = hashDomainBytes(
        REQUEST_DOMAIN,
        requestPackageBytes,
      );
      const requestPackagePath = path.join(immutableRoot, "request.json");
      await writePrivateFile(
        requestPackagePath,
        requestPackageBytes,
        this.security,
      );

      const hardRulePackagePath = path.join(immutableRoot, "hard-rules.md");
      const hardRulePackageHash = hashDomainBytes(
        HARD_RULE_DOMAIN,
        normalized.hardRulePackage,
      );
      await writePrivateFile(
        hardRulePackagePath,
        normalized.hardRulePackage,
        this.security,
      );
      const candidateResultContractPath = path.join(
        immutableRoot,
        "candidate-result-contract.json",
      );
      const candidateResultContractSchemaHash = hashDomainBytes(
        RESULT_CONTRACT_DOMAIN,
        normalized.candidateResultContract,
      );
      await writePrivateFile(
        candidateResultContractPath,
        normalized.candidateResultContract,
        this.security,
      );

      const skills: ExternalUpdateState["skills"] = [];
      for (const [index, skill] of normalized.skills.skills.entries()) {
        const rootPath = path.join(
          skillRoot,
          `${String(index).padStart(3, "0")}-${skill.id}`,
        );
        await mkdir(rootPath, { mode: 0o700 });
        await this.security.securePrivatePath({
          directory: true,
          targetPath: rootPath,
        });
        for (const file of skill.files) {
          const destination = containedPath(rootPath, file.relativePath);
          await mkdir(path.dirname(destination), {
            mode: 0o700,
            recursive: true,
          });
          await this.security.securePrivatePath({
            directory: true,
            targetPath: path.dirname(destination),
          });
          await writePrivateFile(destination, file.bytes, this.security);
        }
        if (
          (await computeSkillPackage(rootPath)).packageHash !==
          skill.packageHash
        )
          throw invalidTransaction();
        skills.push({
          id: skill.id,
          category: skill.category,
          loadOrder: skill.loadOrder,
          packageHash: skill.packageHash,
          rootPath,
        });
      }

      let sourceRoot: string | null = null;
      if (normalized.sourceSnapshot !== undefined) {
        sourceRoot = path.join(immutableRoot, "sources");
        await mkdir(sourceRoot, { mode: 0o700 });
        await this.security.securePrivatePath({
          directory: true,
          targetPath: sourceRoot,
        });
        await copyRegularTree(
          normalized.sourceSnapshot.snapshotPath,
          sourceRoot,
          this.security,
        );
        if (
          (await hashSourceSnapshotTree(sourceRoot)) !==
          normalized.sourceSnapshot.snapshotTreeHash
        )
          throw invalidTransaction();
      }

      const bindingHash = computeBindingHash({
        transactionId,
        generation: 1,
        workspaceId,
        beforeWikiRevision: before.rootHash,
        requestPackageHash,
        sourceManifestHash: normalized.sourceSnapshot?.manifestHash ?? null,
        sourceTreeHash: normalized.sourceSnapshot?.snapshotTreeHash ?? null,
        skillAggregateHash: normalized.skills.aggregateHash,
        skills: skills.map(({ id, category, loadOrder, packageHash }) => ({
          id,
          category,
          loadOrder,
          packageHash,
        })),
        confirmedWikiPaths: [...normalized.confirmedWikiPaths],
        hardRulePackageHash,
        candidateResultContractSchemaHash,
        inputHash,
      });
      const createdAt = this.now().toISOString();
      const state = await createExternalUpdateState(
        path.join(transactionRoot, "state.json"),
        {
          version: 1,
          transactionId,
          requestId: normalized.requestId,
          requestIdHash: hashCanonical(
            "kg-c7:external-request-id:v1",
            normalized.requestId,
          ),
          inputHash,
          generation: 1,
          stage: "candidate_writable",
          createdAt,
          updatedAt: createdAt,
          beforeWikiRevision: before.rootHash,
          sourceManifestHash: normalized.sourceSnapshot?.manifestHash ?? null,
          sourceTreeHash: normalized.sourceSnapshot?.snapshotTreeHash ?? null,
          skillAggregateHash: normalized.skills.aggregateHash,
          confirmedWikiPaths: [...normalized.confirmedWikiPaths],
          requestPackageHash,
          workspaceId,
          bindingHash,
          transactionRoot,
          requestPackagePath,
          hardRulePackagePath,
          hardRulePackageHash,
          candidateResultContractPath,
          candidateResultContractSchemaHash,
          candidateRoot,
          sourceRoot,
          skills,
          failures: [],
          failureOverflowCount: 0,
          repairSuccessorGeneration: null,
          repairPredecessorBindingHash: null,
          review: null,
          terminalResultHash: null,
          terminalPayload: null,
        },
        this.security,
      );
      await this.commitActivePointer({ transactionId });
      return {
        state: state.state,
        stateVersion: state.version,
        workPackage: toWorkPackage(state.state),
      };
    } catch (error) {
      if (created)
        await rm(transactionRoot, {
          force: true,
          recursive: true,
          maxRetries: 20,
          retryDelay: 25,
        }).catch(() => undefined);
      if (error instanceof C7ExternalUpdateTransactionError) throw error;
      throw invalidTransaction();
    }
  }

  async isRequestAborted(
    requestId: string,
    candidate?: {
      transactionId: string;
      bindingHash: string;
      generation: number;
    },
  ): Promise<boolean> {
    if (!validId(requestId)) throw invalidTransaction();
    // The Run store holds the operation lock. Keep this lookup read-only.
    const terminal = await this.terminalStore().findByRequestIdHash(
      hashCanonical("kg-c7:external-request-id:v1", requestId),
    );
    if (terminal?.status !== "external_update_aborted") return false;
    if (candidate === undefined) return true;
    return (
      terminal.transactionId === candidate.transactionId &&
      (terminal.generation > candidate.generation ||
        (terminal.generation === candidate.generation &&
          terminal.bindingHash === candidate.bindingHash))
    );
  }

  async readActive(): Promise<VersionedExternalUpdateState | null> {
    return this.withOperationLock(() => this.readActiveLocked());
  }

  private async readActiveLocked(): Promise<VersionedExternalUpdateState | null> {
    await this.reconcileTerminalCleanup();
    const active = await this.readActivePointer();
    if (active === null) return null;
    const current = await this.readCurrent(active.transactionId);
    return { state: current.state, version: current.stateVersion };
  }

  async resume(
    transactionId: string,
    bindingHash: string,
  ): Promise<ExternalUpdateResumeResult> {
    return this.withOperationLock(() =>
      this.resumeLocked(transactionId, bindingHash),
    );
  }

  async prepareReview(input: {
    transactionId: string;
    bindingHash: string;
    candidateReceipt: ExternalCandidateReceipt;
    reviewResultContract: Buffer;
  }): Promise<ExternalReviewPreparationResult> {
    return this.withLocks(["operation", "wiki"], () =>
      this.prepareReviewLocked(input),
    );
  }

  private async prepareReviewLocked(input: {
    transactionId: string;
    bindingHash: string;
    candidateReceipt: ExternalCandidateReceipt;
    reviewResultContract: Buffer;
  }): Promise<ExternalReviewPreparationResult> {
    if (
      !validId(input.transactionId) ||
      !/^sha256:[a-f0-9]{64}$/u.test(input.bindingHash)
    ) {
      throw invalidTransaction();
    }
    const active = await this.readActivePointer();
    if (active?.transactionId !== input.transactionId) throw restoreRequired();
    const current = await this.readCurrent(input.transactionId);
    const receipt = input.candidateReceipt;
    if (
      current.state.bindingHash !== input.bindingHash ||
      receipt.transactionId !== current.state.transactionId ||
      receipt.generation !== current.state.generation ||
      receipt.bindingHash !== current.state.bindingHash
    ) {
      throw invalidTransaction();
    }
    const receiptBytes = canonicalJsonBytes(receipt);
    const candidateReceiptHash = hashDomainBytes(
      CANDIDATE_RECEIPT_DOMAIN,
      receiptBytes,
    );
    if (current.state.stage === "review_ready") {
      const review = current.state.review;
      if (
        review === null ||
        review.candidateReceiptHash !== candidateReceiptHash
      ) {
        throw invalidTransaction();
      }
      const receiptPath = candidateReceiptPath(current.state);
      if (!(await readRegularFile(receiptPath)).equals(receiptBytes)) {
        throw restoreRequired();
      }
      const reviewPackage = await readReviewPackage(current.state);
      await verifyPreparedReviewPackage(current.state, reviewPackage);
      return {
        kind: "review_ready",
        state: current.state,
        stateVersion: current.stateVersion,
        reviewPackage,
        reviewPackageHash: review.reviewPackageHash,
      };
    }
    if (current.state.stage === "attention") {
      const retained = await readBlockingCandidateReceipt(current.state);
      if (!retained.equals(receiptBytes)) throw invalidTransaction();
      return clarificationResult(current, receipt);
    }
    if (current.state.stage !== "candidate_writable") {
      throw invalidTransaction();
    }
    if (receipt.classification !== "blocking") {
      const before = await snapshotMarkdownTree(this.formalWikiPath);
      if (before.rootHash !== current.state.beforeWikiRevision) {
        throw new C7ExternalUpdateTransactionError(
          "wiki_conflict",
          "The formal Wiki revision changed before Review preparation.",
        );
      }
      const validation = await validateWikiCandidate({
        allowedChangedPaths: current.state.confirmedWikiPaths,
        beforeSnapshot: before,
        candidateRoot: current.state.candidateRoot,
        ...(current.state.sourceRoot === null
          ? {}
          : { forbiddenSourceRoot: current.state.sourceRoot }),
        requireProvisionalMarker: receipt.classification === "provisional",
      });
      if (!validation.passed) throw validationFailed();
      if (validation.snapshot === undefined) throw validationFailed();
      await verifyImmutableState(current.state).catch(() => {
        throw restoreRequired();
      });
      const [formalAfter, candidateAfter] = await Promise.all([
        snapshotMarkdownTree(this.formalWikiPath),
        snapshotMarkdownTree(current.state.candidateRoot),
      ]);
      if (formalAfter.rootHash !== current.state.beforeWikiRevision) {
        throw new C7ExternalUpdateTransactionError(
          "wiki_conflict",
          "The formal Wiki revision changed during Review preparation.",
        );
      }
      if (candidateAfter.rootHash !== validation.snapshot.rootHash) {
        throw validationFailed();
      }
      if (input.reviewResultContract.byteLength === 0) {
        throw invalidTransaction();
      }
      return this.freezeReview({
        candidateReceiptHash,
        candidateReceiptBytes: receiptBytes,
        candidateRootHash: candidateAfter.rootHash,
        current,
        reviewResultContract: input.reviewResultContract,
      });
    }
    const receiptPath = candidateReceiptPath(current.state);
    const created = await writeOrVerifyPrivateFile(
      receiptPath,
      receiptBytes,
      this.security,
    );
    try {
      const transitioned = await transitionExternalUpdateState({
        statePath: path.join(current.state.transactionRoot, "state.json"),
        expectedVersion: current.stateVersion,
        next: { stage: "attention" },
        now: this.now(),
        security: this.security,
      });
      return clarificationResult(
        {
          state: transitioned.state,
          stateVersion: transitioned.version,
          workPackage: toWorkPackage(transitioned.state),
        },
        receipt,
      );
    } catch (error) {
      if (created)
        await rm(receiptPath, { force: true }).catch(() => undefined);
      throw error;
    }
  }

  private async freezeReview(input: {
    candidateReceiptHash: string;
    candidateReceiptBytes: Buffer;
    candidateRootHash: string;
    current: ExternalUpdateWorkspace;
    reviewResultContract: Buffer;
  }): Promise<ExternalReviewPreparationResult> {
    const state = input.current.state;
    const reviewResultContractPath = path.join(
      state.transactionRoot,
      "immutable",
      "review-result-contract.json",
    );
    const reviewResultContractSchemaHash = hashDomainBytes(
      REVIEW_RESULT_CONTRACT_DOMAIN,
      input.reviewResultContract,
    );
    const receiptPath = candidateReceiptPath(state);
    const reviewPackagePath = path.join(
      path.dirname(state.candidateRoot),
      "review-package.json",
    );
    const reviewPackage = toReviewPackage(state, {
      candidateRootHash: input.candidateRootHash,
      candidateReceiptHash: input.candidateReceiptHash,
      reviewResultContract: {
        path: reviewResultContractPath,
        schemaHash: reviewResultContractSchemaHash,
      },
    });
    const reviewPackageBytes = canonicalJsonBytes(reviewPackage);
    const reviewPackageHash = hashDomainBytes(
      REVIEW_PACKAGE_DOMAIN,
      reviewPackageBytes,
    );
    const cleanupPaths: string[] = [];
    let transitioned = false;
    try {
      if (
        await writeOrVerifyPrivateFile(
          reviewResultContractPath,
          input.reviewResultContract,
          this.security,
        )
      ) {
        cleanupPaths.push(reviewResultContractPath);
      }
      if (
        await writeOrVerifyPrivateFile(
          receiptPath,
          input.candidateReceiptBytes,
          this.security,
        )
      ) {
        cleanupPaths.push(receiptPath);
      }
      if (
        await writeOrVerifyPrivateFile(
          reviewPackagePath,
          reviewPackageBytes,
          this.security,
        )
      ) {
        cleanupPaths.push(reviewPackagePath);
      }
      await this.faultInjector("after_review_package");
      const next = await transitionExternalUpdateState({
        statePath: path.join(state.transactionRoot, "state.json"),
        expectedVersion: input.current.stateVersion,
        next: {
          stage: "review_ready",
          review: {
            candidateRootHash: input.candidateRootHash,
            candidateReceiptHash: input.candidateReceiptHash,
            reviewPackageHash,
            reviewPackagePath,
          },
        },
        now: this.now(),
        security: this.security,
      });
      transitioned = true;
      return {
        kind: "review_ready",
        state: next.state,
        stateVersion: next.version,
        reviewPackage,
        reviewPackageHash,
      };
    } catch (error) {
      if (!transitioned) {
        await Promise.all(
          cleanupPaths.map((candidate) =>
            rm(candidate, { force: true }).catch(() => undefined),
          ),
        );
      }
      if (error instanceof C7ExternalUpdateTransactionError) throw error;
      throw invalidTransaction();
    }
  }

  private async resumeLocked(
    transactionId: string,
    bindingHash: string,
  ): Promise<ExternalUpdateResumeResult> {
    if (
      !validId(transactionId) ||
      !/^sha256:[a-f0-9]{64}$/u.test(bindingHash)
    ) {
      throw invalidTransaction();
    }
    await this.reconcileTerminalCleanup();
    const retainedTerminal = await this.terminalStore().find(transactionId);
    if (
      retainedTerminal !== null &&
      retainedTerminal.bindingHash === bindingHash
    ) {
      return { kind: "terminal", terminalPayload: retainedTerminal.payload };
    }
    const active = await this.readActivePointer();
    if (active === null) {
      throw new C7ExternalUpdateTransactionError(
        "restore_required",
        "The external update transaction is not active.",
      );
    }
    if (active.transactionId !== transactionId) {
      throw new C7ExternalUpdateTransactionError(
        "restore_required",
        "The external update transaction is not active.",
      );
    }
    const current = await this.readCurrent(transactionId);
    const predecessorReplay =
      current.state.stage === "candidate_writable" &&
      current.state.repairSuccessorGeneration === current.state.generation &&
      current.state.repairPredecessorBindingHash === bindingHash;
    if (current.state.bindingHash !== bindingHash && !predecessorReplay)
      throw invalidTransaction();
    if (current.state.stage === "candidate_writable") {
      return { kind: "candidate_writable", ...current };
    }
    if (current.state.stage === "review_ready") {
      const review = current.state.review;
      if (review === null) throw restoreRequired();
      const reviewPackage = await readReviewPackage(current.state).catch(() => {
        throw restoreRequired();
      });
      return {
        kind: "review_ready",
        state: current.state,
        stateVersion: current.stateVersion,
        reviewPackage,
        reviewPackageHash: review.reviewPackageHash,
      };
    }
    if (current.state.stage === "attention") {
      const receipt = await parseOptionalBlockingCandidateReceipt(
        current.state,
      );
      return {
        kind: "attention",
        state: current.state,
        stateVersion: current.stateVersion,
        ...(receipt === null
          ? {}
          : { issues: receipt.issues, questions: receipt.questions }),
      };
    }
    if (current.state.stage === "repair_ready") {
      if (current.state.generation >= 3 || current.state.review === null) {
        throw restoreRequired();
      }
      const generation = (current.state.generation + 1) as 2 | 3;
      const workspaceId = this.createWorkspaceId();
      if (!validId(workspaceId)) throw invalidTransaction();
      const candidateRoot = path.join(
        current.state.transactionRoot,
        "generations",
        String(generation),
        workspaceId,
        "candidate",
      );
      await mkdir(candidateRoot, { mode: 0o700, recursive: true });
      await this.security.securePrivatePath({
        directory: true,
        targetPath: candidateRoot,
      });
      try {
        const frozen = await snapshotMarkdownTree(current.state.candidateRoot);
        await copyMarkdownTree(
          current.state.candidateRoot,
          candidateRoot,
          frozen,
        );
        await secureTree(candidateRoot, this.security);
        const bindingHash = computeBindingHash({
          transactionId: current.state.transactionId,
          generation,
          workspaceId,
          beforeWikiRevision: current.state.beforeWikiRevision,
          requestPackageHash: current.state.requestPackageHash,
          sourceManifestHash: current.state.sourceManifestHash,
          sourceTreeHash: current.state.sourceTreeHash,
          skillAggregateHash: current.state.skillAggregateHash,
          skills: current.state.skills,
          confirmedWikiPaths: current.state.confirmedWikiPaths,
          hardRulePackageHash: current.state.hardRulePackageHash,
          candidateResultContractSchemaHash:
            current.state.candidateResultContractSchemaHash,
          inputHash: current.state.inputHash,
        });
        const transitioned = await transitionExternalUpdateState({
          statePath: path.join(current.state.transactionRoot, "state.json"),
          expectedVersion: current.stateVersion,
          next: {
            stage: "candidate_writable",
            successor: { generation, workspaceId, bindingHash, candidateRoot },
          },
          now: this.now(),
          security: this.security,
        });
        const workspace = {
          state: transitioned.state,
          stateVersion: transitioned.version,
          workPackage: toWorkPackage(transitioned.state),
        };
        return { kind: "candidate_writable", ...workspace };
      } catch (error) {
        await rm(path.join(candidateRoot, ".."), {
          force: true,
          recursive: true,
        }).catch(() => undefined);
        if (error instanceof C7ExternalUpdateTransactionError) throw error;
        throw restoreRequired();
      }
    }
    throw restoreRequired();
  }

  async recordHostFailure(input: {
    transactionId: string;
    bindingHash: string;
    phase: "candidate_writer" | "reviewer";
    code:
      | "host_cancelled"
      | "host_timeout"
      | "host_model_failure"
      | "host_process_failure";
    message: string;
    retryable: boolean;
    reviewPackageHash?: string;
  }): Promise<VersionedExternalUpdateState> {
    return this.withOperationLock(() => this.recordHostFailureLocked(input));
  }

  async submitAndPublish(input: {
    transactionId: string;
    bindingHash: string;
    reviewReceipt: unknown;
    publish(input: ExternalReviewPublishInput): Promise<{
      readonly wikiRevision: string;
    }>;
  }): Promise<ExternalReviewSubmissionResult> {
    return this.withLocks(["operation", "wiki"], () =>
      this.submitAndPublishLocked(input),
    );
  }

  async recoverPublishPending(input: {
    transactionId: string;
    publish(input: ExternalReviewPublishInput): Promise<{
      readonly wikiRevision: string;
    }>;
  }): Promise<Extract<ExternalReviewSubmissionResult, { kind: "terminal" }>> {
    return this.withLocks(["operation", "wiki"], () =>
      this.recoverPublishPendingLocked(input),
    );
  }

  async recoverStartup(input: {
    publish(input: ExternalReviewPublishInput): Promise<{
      readonly wikiRevision: string;
    }>;
  }): Promise<
    | { readonly status: "external_startup_clean" }
    | { readonly status: "external_startup_restore_required" }
  > {
    return this.withLocks(["operation", "wiki"], () =>
      this.recoverStartupLocked(input),
    );
  }

  private async recoverStartupLocked(input: {
    publish(input: ExternalReviewPublishInput): Promise<{
      readonly wikiRevision: string;
    }>;
  }): Promise<
    | { readonly status: "external_startup_clean" }
    | { readonly status: "external_startup_restore_required" }
  > {
    try {
      await this.prepareCanonicalRuntime();
      await this.reconcileTerminalCleanup();
      const active = await this.readActivePointer();
      if (active !== null) {
        const current = await this.readCurrent(active.transactionId);
        if (current.state.stage === "publish_pending") {
          await this.recoverPublishPendingLocked({
            transactionId: current.state.transactionId,
            publish: input.publish,
          });
        }
      }
      const terminalIndex = await this.terminalStore().read();
      for (const tombstone of terminalIndex.tombstones) {
        if (
          (tombstone.status !== "published" &&
            tombstone.status !== "published_with_follow_up") ||
          (tombstone.payload.status !== "published" &&
            tombstone.payload.status !== "published_with_follow_up")
        ) {
          continue;
        }
        const runId = computeExternalPublishRunId({
          bindingHash: tombstone.bindingHash,
          generation: tombstone.generation,
          reviewReceiptHash: tombstone.payload.reviewReceiptHash,
          transactionId: tombstone.transactionId,
        });
        const recoveryRoot = path.join(this.runtimeDir, "recovery");
        const hasJournal = await Promise.all(
          [runId, `${runId}.cleanup`].map((name) =>
            lstat(path.join(recoveryRoot, name)).catch((error) => {
              if (nodeCode(error) === "ENOENT") return null;
              throw restoreRequired();
            }),
          ),
        );
        if (hasJournal.some((stat) => stat !== null)) {
          await this.recoverOrphanPublishedJournal(tombstone.transactionId);
        }
      }
      return { status: "external_startup_clean" };
    } catch {
      return { status: "external_startup_restore_required" };
    }
  }

  private async recoverPublishPendingLocked(input: {
    transactionId: string;
    publish(input: ExternalReviewPublishInput): Promise<{
      readonly wikiRevision: string;
    }>;
  }): Promise<Extract<ExternalReviewSubmissionResult, { kind: "terminal" }>> {
    if (!validId(input.transactionId)) throw invalidTransaction();
    await this.reconcileTerminalCleanup();
    const active = await this.readActivePointer();
    if (active === null) {
      return this.recoverOrphanPublishedJournal(input.transactionId);
    }
    if (active.transactionId !== input.transactionId) throw restoreRequired();
    const current = await this.readCurrent(input.transactionId);
    if (current.state.stage === "published") {
      await this.reconcileTerminalCleanup();
      return this.recoverOrphanPublishedJournal(input.transactionId);
    }
    if (
      current.state.stage !== "publish_pending" ||
      current.state.review === null
    ) {
      throw restoreRequired();
    }
    await verifyImmutableState(current.state).catch(() => {
      throw restoreRequired();
    });
    const candidateReceipt = await readPreparedCandidateReceipt(current.state);
    const reviewReceipt = await readPreparedReviewReceipt(current.state);
    if (
      candidateReceipt.writerExecutionId === reviewReceipt.reviewerExecutionId
    ) {
      throw restoreRequired();
    }
    const reviewReceiptBytes = canonicalJsonBytes(reviewReceipt);
    const reviewReceiptHash = hashDomainBytes(
      REVIEW_RECEIPT_DOMAIN,
      reviewReceiptBytes,
    );
    const candidate = await snapshotMarkdownTree(current.state.candidateRoot);
    if (candidate.rootHash !== current.state.review.candidateRootHash) {
      throw restoreRequired();
    }
    const reviewPackage = await readReviewPackage(current.state);
    const plan = createExternalPublishPlan(
      current.state,
      reviewPackage,
      reviewReceiptHash,
    );
    const formalStat = await lstat(this.formalWikiPath).catch((error) => {
      if (nodeCode(error) === "ENOENT") return null;
      throw restoreRequired();
    });
    if (
      formalStat !== null &&
      (!formalStat.isDirectory() || formalStat.isSymbolicLink())
    ) {
      throw restoreRequired();
    }
    let before: MarkdownTreeSnapshot | null =
      formalStat === null
        ? null
        : await snapshotMarkdownTree(this.formalWikiPath).catch(() => {
            throw restoreRequired();
          });
    if (
      before === null ||
      before.rootHash !== current.state.beforeWikiRevision
    ) {
      const mixed = before !== null && before.rootHash !== candidate.rootHash;
      before = await snapshotMarkdownTree(
        path.join(this.runtimeDir, "recovery", plan.runId, "before"),
      ).catch(() => {
        throw restoreRequired();
      });
      if (before.rootHash !== current.state.beforeWikiRevision) {
        throw restoreRequired();
      }
      if (mixed) {
        const journalPath = path.join(this.runtimeDir, "recovery", plan.runId);
        try {
          const bytes = await readRegularFile(
            path.join(journalPath, "plan.json"),
          );
          const retained = parseExternalWikiPublishPlan(
            JSON.parse(bytes.toString("utf8")),
          );
          if (retained.version !== 5 || !bytes.equals(canonicalJsonBytes(plan)))
            throw restoreRequired();
          await verifyStablePublication({
            formalWikiPath: this.formalWikiPath,
            journalPath,
            plan: retained,
            planHash: hashBytes(bytes),
            before,
            after: candidate,
          });
        } catch {
          throw restoreRequired();
        }
      }
    }
    return this.publishExternalLocked({
      candidate,
      candidateReceipt,
      formal: before,
      input: { publish: input.publish },
      review: current.state.review,
      reviewReceiptHash,
      transitioned: current,
    });
  }

  private async recoverOrphanPublishedJournal(
    transactionId: string,
    historicalReplay = false,
  ): Promise<Extract<ExternalReviewSubmissionResult, { kind: "terminal" }>> {
    const tombstone = await this.terminalStore().find(transactionId);
    if (
      tombstone === null ||
      (tombstone.payload.status !== "published" &&
        tombstone.payload.status !== "published_with_follow_up") ||
      tombstone.resultHash !==
        computeExternalTerminalResultHash(tombstone.payload) ||
      tombstone.bindingHash !== tombstone.payload.bindingHash ||
      tombstone.generation !== tombstone.payload.generation ||
      tombstone.finalWikiRevision !== tombstone.payload.wikiRevision
    ) {
      throw restoreRequired();
    }
    const runId = computeExternalPublishRunId({
      bindingHash: tombstone.bindingHash,
      generation: tombstone.generation,
      reviewReceiptHash: tombstone.payload.reviewReceiptHash,
      transactionId,
    });
    const journalPath = path.join(this.runtimeDir, "recovery", runId);
    const cleanupPath = path.join(
      this.runtimeDir,
      "recovery",
      `${runId}.cleanup`,
    );
    const [journalStat, cleanupStat] = await Promise.all(
      [journalPath, cleanupPath].map((candidate) =>
        lstat(candidate).catch((error) => {
          if (nodeCode(error) === "ENOENT") return null;
          throw restoreRequired();
        }),
      ),
    );
    if (journalStat === null && cleanupStat === null) {
      if (historicalReplay) {
        return { kind: "terminal", terminalPayload: tombstone.payload };
      }
      const formal = await snapshotMarkdownTree(this.formalWikiPath).catch(
        () => {
          throw restoreRequired();
        },
      );
      if (formal.rootHash !== tombstone.finalWikiRevision) {
        throw restoreRequired();
      }
      return { kind: "terminal", terminalPayload: tombstone.payload };
    }
    if (
      (journalStat !== null && cleanupStat !== null) ||
      (journalStat !== null &&
        (!journalStat.isDirectory() || journalStat.isSymbolicLink())) ||
      (cleanupStat !== null &&
        (!cleanupStat.isDirectory() || cleanupStat.isSymbolicLink()))
    ) {
      throw restoreRequired();
    }
    if (cleanupStat !== null) {
      await rm(cleanupPath, {
        force: true,
        recursive: true,
        maxRetries: 20,
        retryDelay: 25,
      });
      return { kind: "terminal", terminalPayload: tombstone.payload };
    }
    const planBytes = await readRegularFile(
      path.join(journalPath, "plan.json"),
    ).catch(() => {
      throw restoreRequired();
    });
    let plan: ExternalWikiPublishPlan;
    try {
      plan = parseExternalWikiPublishPlan(
        JSON.parse(planBytes.toString("utf8")),
      );
    } catch {
      throw restoreRequired();
    }
    if (
      !planBytes.equals(canonicalJsonBytes(plan)) ||
      plan.runId !== runId ||
      plan.transactionId !== transactionId ||
      plan.generation !== tombstone.generation ||
      plan.bindingHash !== tombstone.bindingHash ||
      plan.reviewReceiptHash !== tombstone.payload.reviewReceiptHash ||
      plan.candidateRootHash !== tombstone.payload.candidateRootHash ||
      plan.candidateRootHash !== tombstone.payload.wikiRevision
    ) {
      throw restoreRequired();
    }
    const markerBytes = await readRegularFile(
      path.join(journalPath, "commit.marker"),
    ).catch(() => {
      throw restoreRequired();
    });
    let marker: unknown;
    try {
      marker = JSON.parse(markerBytes.toString("utf8"));
    } catch {
      throw restoreRequired();
    }
    if (
      !validExternalCommitMarker(
        marker,
        runId,
        plan.candidateRootHash,
        planBytes,
      )
    ) {
      throw restoreRequired();
    }
    await verifyTerminalOrphanJournalLayout(
      journalPath,
      plan,
      this.formalWikiPath,
    );
    const formal = await snapshotMarkdownTree(this.formalWikiPath).catch(() => {
      throw restoreRequired();
    });
    if (formal.rootHash !== tombstone.finalWikiRevision)
      throw restoreRequired();
    await rename(journalPath, cleanupPath);
    await this.faultInjector("after_orphan_journal_quarantine");
    await rm(cleanupPath, {
      force: true,
      recursive: true,
      maxRetries: 20,
      retryDelay: 25,
    });
    return { kind: "terminal", terminalPayload: tombstone.payload };
  }

  private async submitAndPublishLocked(input: {
    transactionId: string;
    bindingHash: string;
    reviewReceipt: unknown;
    publish(input: ExternalReviewPublishInput): Promise<{
      readonly wikiRevision: string;
    }>;
  }): Promise<ExternalReviewSubmissionResult> {
    const parsed = toolInputSchemas.openwiki_finalize_external_update.safeParse(
      {
        action: "submit_review",
        transactionId: input.transactionId,
        bindingHash: input.bindingHash,
        reviewReceipt: input.reviewReceipt,
      },
    );
    if (!parsed.success || parsed.data.action !== "submit_review") {
      throw invalidTransaction();
    }
    const receipt = parsed.data.reviewReceipt;
    const receiptBytes = canonicalJsonBytes(receipt);
    const reviewReceiptHash = hashDomainBytes(
      REVIEW_RECEIPT_DOMAIN,
      receiptBytes,
    );
    await this.reconcileTerminalCleanup();
    const retainedTerminal = await this.terminalStore().find(
      input.transactionId,
    );
    if (retainedTerminal !== null) {
      if (
        retainedTerminal.bindingHash !== input.bindingHash ||
        retainedTerminal.generation !== receipt.generation ||
        retainedTerminal.payload.transactionId !== input.transactionId ||
        retainedTerminal.payload.bindingHash !== input.bindingHash ||
        retainedTerminal.payload.generation !== receipt.generation ||
        (retainedTerminal.payload.status !== "published" &&
          retainedTerminal.payload.status !== "published_with_follow_up") ||
        retainedTerminal.payload.reviewReceiptHash !== reviewReceiptHash
      ) {
        throw invalidTransaction();
      }
      await this.reconcileTerminalCleanup();
      return this.recoverOrphanPublishedJournal(input.transactionId, true);
    }
    const active = await this.readActivePointer();
    if (active?.transactionId !== input.transactionId) throw restoreRequired();
    const current = await this.readCurrent(input.transactionId);
    if (
      current.state.bindingHash !== input.bindingHash ||
      receipt.transactionId !== current.state.transactionId ||
      receipt.generation !== current.state.generation ||
      receipt.bindingHash !== current.state.bindingHash
    ) {
      throw invalidTransaction();
    }
    const artifactPath = reviewReceiptPath(current.state);
    if (current.state.stage !== "review_ready") {
      const retained = await readRegularFile(artifactPath).catch(() => {
        throw restoreRequired();
      });
      if (!retained.equals(receiptBytes)) throw invalidTransaction();
      if (current.state.stage === "repair_ready") {
        return {
          kind: "repair_ready",
          state: current.state,
          stateVersion: current.stateVersion,
          reviewReceiptHash,
          issues: receipt.issues,
        };
      }
      if (current.state.stage === "attention") {
        return {
          kind: "attention",
          state: current.state,
          stateVersion: current.stateVersion,
          reviewReceiptHash,
          issues: receipt.issues,
          questions: receipt.issues.map((issue) => issue.message),
        };
      }
      if (current.state.stage === "publish_pending") {
        return this.recoverPublishPendingLocked({
          transactionId: input.transactionId,
          publish: input.publish,
        });
      }
      throw restoreRequired();
    }
    const review = current.state.review;
    if (
      review === null ||
      receipt.reviewPackageHash !== review.reviewPackageHash ||
      receipt.candidateRootHash !== review.candidateRootHash ||
      receipt.candidateReceiptHash !== review.candidateReceiptHash
    ) {
      throw invalidTransaction();
    }
    await verifyImmutableState(current.state).catch(() => {
      throw restoreRequired();
    });
    const candidateReceipt = await readPreparedCandidateReceipt(current.state);
    if (candidateReceipt.writerExecutionId === receipt.reviewerExecutionId) {
      throw invalidTransaction();
    }
    const [formal, candidate] = await Promise.all([
      snapshotMarkdownTree(this.formalWikiPath),
      snapshotMarkdownTree(current.state.candidateRoot),
    ]);
    if (formal.rootHash !== current.state.beforeWikiRevision) {
      throw new C7ExternalUpdateTransactionError(
        "wiki_conflict",
        "The formal Wiki revision changed before Review submission.",
      );
    }
    if (candidate.rootHash !== review.candidateRootHash) {
      throw validationFailed();
    }
    const target = reviewTarget(
      current.state.generation,
      candidateReceipt,
      receipt,
    );
    await this.faultInjector("before_review_receipt");
    await writeOrVerifyPrivateFile(artifactPath, receiptBytes, this.security);
    await this.faultInjector("after_review_receipt");
    await this.faultInjector("before_review_cas");
    const transitioned = await transitionExternalUpdateState({
      statePath: path.join(current.state.transactionRoot, "state.json"),
      expectedVersion: current.stateVersion,
      next: { stage: target },
      now: this.now(),
      security: this.security,
    });
    await this.faultInjector("after_review_cas");
    if (target === "repair_ready") {
      return {
        kind: "repair_ready",
        state: transitioned.state,
        stateVersion: transitioned.version,
        reviewReceiptHash,
        issues: receipt.issues,
      };
    }
    if (target === "attention") {
      return {
        kind: "attention",
        state: transitioned.state,
        stateVersion: transitioned.version,
        reviewReceiptHash,
        issues: receipt.issues,
        questions: receipt.issues.map((issue) => issue.message),
      };
    }
    return this.publishExternalLocked({
      candidate,
      candidateReceipt,
      formal,
      input,
      review,
      reviewReceiptHash,
      transitioned,
    });
  }

  private async publishExternalLocked(input: {
    candidate: MarkdownTreeSnapshot;
    candidateReceipt: ExternalCandidateReceipt;
    formal: MarkdownTreeSnapshot;
    input: {
      publish(input: ExternalReviewPublishInput): Promise<{
        readonly wikiRevision: string;
      }>;
    };
    review: NonNullable<ExternalUpdateState["review"]>;
    reviewReceiptHash: string;
    transitioned: { readonly state: ExternalUpdateState };
  }): Promise<Extract<ExternalReviewSubmissionResult, { kind: "terminal" }>> {
    const state = input.transitioned.state;
    const reviewPackage = await readReviewPackage(state);
    const plan = createExternalPublishPlan(
      state,
      reviewPackage,
      input.reviewReceiptHash,
    );
    const published = await input.input.publish({
      after: input.candidate,
      before: input.formal,
      candidateWikiPath: state.candidateRoot,
      plan,
    });
    if (published.wikiRevision !== input.candidate.rootHash) {
      throw restoreRequired();
    }
    const followUp =
      input.candidateReceipt.classification === "provisional"
        ? input.candidateReceipt.issues.filter(
            (
              issue,
            ): issue is ExternalReviewIssue & {
              readonly severity: "provisional";
            } => issue.severity === "provisional",
          )
        : [];
    const terminalPayload: ExternalTerminalPayload =
      followUp.length === 0
        ? externalPublishedPayload(
            state,
            input.review,
            input.reviewReceiptHash,
            input.candidate.rootHash,
          )
        : {
            ...externalPublishedPayload(
              state,
              input.review,
              input.reviewReceiptHash,
              input.candidate.rootHash,
            ),
            status: "published_with_follow_up",
            followUp,
          };
    await this.completeTerminalLocked({
      transactionId: state.transactionId,
      bindingHash: state.bindingHash,
      terminalPayload,
    });
    await rm(path.join(this.runtimeDir, "recovery", plan.runId), {
      force: true,
      recursive: true,
      maxRetries: 20,
      retryDelay: 25,
    });
    return { kind: "terminal", terminalPayload };
  }

  private async recordHostFailureLocked(input: {
    transactionId: string;
    bindingHash: string;
    phase: "candidate_writer" | "reviewer";
    code:
      | "host_cancelled"
      | "host_timeout"
      | "host_model_failure"
      | "host_process_failure";
    message: string;
    retryable: boolean;
    reviewPackageHash?: string;
  }): Promise<VersionedExternalUpdateState> {
    if (
      !validId(input.transactionId) ||
      !/^sha256:[a-f0-9]{64}$/u.test(input.bindingHash) ||
      input.message.trim().length === 0 ||
      input.message.length > 4_096
    ) {
      throw invalidTransaction();
    }
    const active = await this.readActivePointer();
    if (active?.transactionId !== input.transactionId) throw restoreRequired();
    const current = await this.readCurrent(input.transactionId);
    if (current.state.bindingHash !== input.bindingHash)
      throw invalidTransaction();
    const review = current.state.review;
    const validPhase =
      (input.phase === "candidate_writer" &&
        current.state.stage === "candidate_writable" &&
        input.reviewPackageHash === undefined) ||
      (input.phase === "reviewer" &&
        current.state.stage === "review_ready" &&
        review !== null &&
        input.reviewPackageHash === review.reviewPackageHash);
    if (!validPhase) throw invalidTransaction();
    return recordExternalUpdateFailure({
      statePath: path.join(current.state.transactionRoot, "state.json"),
      expectedVersion: current.stateVersion,
      failure: {
        at: this.now().toISOString(),
        phase: input.phase,
        code: input.code,
        messageHash: hashCanonical(
          "kg-c7:external-host-failure-message:v1",
          input.message,
        ),
        retryable: input.retryable,
      },
      now: this.now(),
      security: this.security,
    });
  }

  async completeTerminal(input: {
    transactionId: string;
    bindingHash: string;
    terminalPayload: unknown;
  }): Promise<ExternalUpdateTerminalTombstone> {
    return this.withLocks(["operation", "wiki"], () =>
      this.completeTerminalLocked(input),
    );
  }

  private async completeTerminalLocked(input: {
    transactionId: string;
    bindingHash: string;
    terminalPayload: unknown;
  }): Promise<ExternalUpdateTerminalTombstone> {
    let payload: ExternalTerminalPayload;
    try {
      payload = parseExternalTerminalPayload(input.terminalPayload);
    } catch {
      throw invalidTransaction();
    }
    if (
      !validId(input.transactionId) ||
      !/^sha256:[a-f0-9]{64}$/u.test(input.bindingHash) ||
      payload.transactionId !== input.transactionId ||
      payload.bindingHash !== input.bindingHash
    ) {
      throw invalidTransaction();
    }
    const status =
      payload.status === "external_update_aborted" ? "aborted" : "published";
    const resultHash = computeExternalTerminalResultHash(payload);
    await this.reconcileTerminalCleanup();
    const replay = await this.terminalStore().find(input.transactionId);
    if (replay !== null) {
      if (
        replay.bindingHash === input.bindingHash &&
        replay.resultHash === resultHash &&
        stableJson(replay.payload) === stableJson(payload)
      ) {
        return replay;
      }
      throw invalidTransaction();
    }
    const active = await this.readActivePointer();
    if (active === null) {
      throw restoreRequired();
    }
    if (active.transactionId !== input.transactionId) throw restoreRequired();
    const current = await this.readCurrent(input.transactionId);
    if (current.state.bindingHash !== input.bindingHash)
      throw invalidTransaction();
    if (
      payload.generation !== current.state.generation ||
      (status === "published" && current.state.stage !== "publish_pending") ||
      (status === "aborted" &&
        (current.state.stage === "published" ||
          current.state.stage === "aborted"))
    ) {
      throw invalidTransaction();
    }
    let abortedWikiRevision = current.state.beforeWikiRevision;
    if (status === "aborted" && current.state.stage === "publish_pending") {
      abortedWikiRevision = await discardPublishPendingRecoveryJournal({
        formalWikiPath: this.formalWikiPath,
        runtimeDir: this.runtimeDir,
        state: current.state,
      });
    }
    const transitioned = await transitionExternalUpdateState({
      statePath: path.join(current.state.transactionRoot, "state.json"),
      expectedVersion: current.stateVersion,
      next: {
        stage: status,
        terminalPayload: payload,
      },
      now: this.now(),
      security: this.security,
    });
    await this.faultInjector("after_terminal_state");
    const tombstone: ExternalUpdateTerminalTombstone = {
      version: 1,
      transactionId: transitioned.state.transactionId,
      requestIdHash: transitioned.state.requestIdHash,
      inputHash: transitioned.state.inputHash,
      bindingHash: transitioned.state.bindingHash,
      resultHash,
      status: payload.status,
      finalWikiRevision:
        payload.status === "external_update_aborted"
          ? abortedWikiRevision
          : payload.wikiRevision,
      generation: transitioned.state.generation,
      completedAt: transitioned.state.updatedAt,
      payload,
    };
    await this.terminalStore().append(tombstone);
    await this.faultInjector("after_tombstone");
    await rm(current.state.transactionRoot, {
      force: true,
      recursive: true,
      maxRetries: 20,
      retryDelay: 25,
    });
    await this.faultInjector("after_transaction_cleanup");
    await rm(this.activePath(), { force: true });
    await this.faultInjector("after_active_pointer_cleanup");
    return tombstone;
  }

  private async reconcileTerminalCleanup(): Promise<void> {
    const active = await this.readActivePointerRaw();
    if (active === null) return;
    const tombstone = await this.terminalStore().find(active.transactionId);
    const transactionRoot = path.join(this.updatesRoot(), active.transactionId);
    const statePath = path.join(transactionRoot, "state.json");
    const transactionStat = await lstat(transactionRoot).catch((error) => {
      if (nodeCode(error) === "ENOENT") return null;
      throw restoreRequired();
    });
    if (
      transactionStat !== null &&
      (!transactionStat.isDirectory() || transactionStat.isSymbolicLink())
    ) {
      throw restoreRequired();
    }
    const stateStat =
      transactionStat === null
        ? null
        : await lstat(statePath).catch((error) => {
            if (nodeCode(error) === "ENOENT") return null;
            throw restoreRequired();
          });
    if (
      stateStat !== null &&
      (!stateStat.isFile() || stateStat.isSymbolicLink())
    ) {
      throw restoreRequired();
    }
    if (transactionStat !== null && stateStat === null) {
      throw restoreRequired();
    }
    const current =
      stateStat === null
        ? null
        : await this.readCurrent(active.transactionId).catch(() => {
            throw restoreRequired();
          });
    if (current !== null) {
      if (
        current.state.stage !== "published" &&
        current.state.stage !== "aborted"
      ) {
        return;
      }
      const payload = current.state.terminalPayload;
      const resultHash = current.state.terminalResultHash;
      if (payload === null || resultHash === null) throw restoreRequired();
      const expected: ExternalUpdateTerminalTombstone = {
        version: 1,
        transactionId: current.state.transactionId,
        requestIdHash: current.state.requestIdHash,
        inputHash: current.state.inputHash,
        bindingHash: current.state.bindingHash,
        resultHash,
        status: payload.status,
        finalWikiRevision:
          payload.status === "external_update_aborted"
            ? current.state.beforeWikiRevision
            : payload.wikiRevision,
        generation: current.state.generation,
        completedAt: current.state.updatedAt,
        payload,
      };
      if (
        tombstone !== null &&
        stableJson(tombstone) !== stableJson(expected)
      ) {
        throw restoreRequired();
      }
      await this.terminalStore().append(expected);
      await rm(transactionRoot, {
        force: true,
        recursive: true,
        maxRetries: 20,
        retryDelay: 25,
      });
      await rm(this.activePath(), { force: true });
      return;
    }
    if (tombstone !== null) {
      await rm(this.activePath(), { force: true });
      return;
    }
    throw restoreRequired();
  }

  private async readCurrent(
    transactionId: string,
  ): Promise<ExternalUpdateWorkspace> {
    try {
      if (!validId(transactionId)) throw new Error();
      const updatesRoot = this.updatesRoot();
      const transactionRoot = path.join(updatesRoot, transactionId);
      if (
        !isStrictDescendant(updatesRoot, transactionRoot) ||
        path.basename(transactionRoot) !== transactionId
      ) {
        throw new Error();
      }
      const updatesIdentity = await inspectRealDirectoryIdentity(updatesRoot);
      const transactionIdentity =
        await inspectRealDirectoryIdentity(transactionRoot);
      if (
        path.basename(transactionIdentity.realPath) !== transactionId ||
        path.dirname(transactionIdentity.realPath).toLowerCase() !==
          updatesIdentity.realPath.toLowerCase()
      ) {
        throw new Error();
      }
      const current = await readExternalUpdateState(
        path.join(transactionRoot, "state.json"),
      );
      if (current.state.transactionId !== transactionId) throw new Error();
      await verifyImmutableState(current.state);
      await assertDirectoryIdentity(transactionRoot, transactionIdentity);
      return {
        state: current.state,
        stateVersion: current.version,
        workPackage: toWorkPackage(current.state),
      };
    } catch {
      throw new C7ExternalUpdateTransactionError(
        "restore_required",
        "The external update state requires recovery.",
      );
    }
  }

  private updatesRoot(): string {
    return path.join(
      this.canonicalRuntimeDir ?? this.runtimeDir,
      "external-updates",
    );
  }
  private activePath(): string {
    return path.join(this.updatesRoot(), "active.json");
  }
  private terminalStore(): ExternalUpdateTerminalStore {
    return new ExternalUpdateTerminalStore({
      rootPath: this.updatesRoot(),
      security: this.security,
    });
  }

  private async withOperationLock<T>(operation: () => Promise<T>): Promise<T> {
    return this.withLocks(["operation"], operation);
  }

  private async withLocks<T>(
    locks: readonly C7LockName[],
    operation: () => Promise<T>,
  ): Promise<T> {
    const maxAttempts = 200;
    const lockRoot = await this.prepareCanonicalRuntime();
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      let callbackEntered = false;
      try {
        return await withC7Locks(lockRoot, locks, async () => {
          callbackEntered = true;
          return operation();
        });
      } catch (error) {
        if (callbackEntered) throw error;
        if (!(await isLockContention(error, lockRoot, locks))) {
          throw error;
        }
        if (attempt === maxAttempts) {
          throw new C7ExternalUpdateTransactionError(
            "busy",
            "Another C7 operation is still active.",
          );
        }
        await delay(Math.min(5 + attempt, 25));
      }
    }
    throw new C7ExternalUpdateTransactionError(
      "busy",
      "Another C7 operation is still active.",
    );
  }

  private async prepareCanonicalRuntime(): Promise<string> {
    const binding = await this.bindCanonicalRuntime();
    const observedCanonical = await realpath(this.runtimeDir).catch(() => {
      throw restoreRequired();
    });
    if (
      observedCanonical.toLowerCase() !== binding.canonicalPath.toLowerCase()
    ) {
      throw restoreRequired();
    }
    await assertDirectoryIdentity(
      binding.canonicalPath,
      binding.identity,
    ).catch(() => {
      throw restoreRequired();
    });
    const updatesRoot = path.join(binding.canonicalPath, "external-updates");
    const updatesIdentity = await inspectOptionalRealDirectory(
      updatesRoot,
    ).catch(() => {
      throw restoreRequired();
    });
    if (updatesIdentity !== null) {
      await this.security.securePrivatePath({
        directory: true,
        targetPath: updatesRoot,
      });
      await assertDirectoryIdentity(updatesRoot, updatesIdentity).catch(() => {
        throw restoreRequired();
      });
    }
    this.canonicalRuntimeDir = binding.canonicalPath;
    return binding.canonicalPath;
  }

  private bindCanonicalRuntime(): Promise<{
    canonicalPath: string;
    identity: DirectoryIdentity;
  }> {
    if (this.runtimeBindingPromise === null) {
      const pending = this.createRuntimeBinding();
      let guarded!: Promise<{
        canonicalPath: string;
        identity: DirectoryIdentity;
      }>;
      guarded = pending.catch((error) => {
        if (this.runtimeBindingPromise === guarded) {
          this.runtimeBindingPromise = null;
        }
        throw error;
      });
      this.runtimeBindingPromise = guarded;
    }
    return this.runtimeBindingPromise;
  }

  private async createRuntimeBinding(): Promise<{
    canonicalPath: string;
    identity: DirectoryIdentity;
  }> {
    await mkdir(this.runtimeDir, { mode: 0o700, recursive: true });
    const canonical = await realpath(this.runtimeDir).catch(() => {
      throw restoreRequired();
    });
    const identity = await inspectRealDirectoryIdentity(canonical).catch(() => {
      throw restoreRequired();
    });
    await this.security.securePrivatePath({
      directory: true,
      targetPath: canonical,
    });
    await assertDirectoryIdentity(canonical, identity).catch(() => {
      throw restoreRequired();
    });
    return { canonicalPath: canonical, identity };
  }

  private async ensureRoot(root: string): Promise<void> {
    await mkdir(root, { mode: 0o700, recursive: true });
    await this.security.securePrivatePath({
      directory: true,
      targetPath: root,
    });
    await assertRealDirectory(root);
  }

  private async readActivePointer(): Promise<{ transactionId: string } | null> {
    return this.readActivePointerRaw();
  }

  private async readActivePointerRaw(): Promise<{
    transactionId: string;
  } | null> {
    let bytes: Buffer;
    try {
      bytes = await readRegularFile(this.activePath());
    } catch (error) {
      if (nodeCode(error) === "ENOENT") {
        const orphan = await this.hasOrphanedActiveDirectory();
        if (orphan) throw restoreRequired();
        return null;
      }
      throw new C7ExternalUpdateTransactionError(
        "restore_required",
        "The external active pointer is unreadable.",
      );
    }
    try {
      const parsed = JSON.parse(bytes.toString("utf8")) as unknown;
      if (
        !isPlainRecord(parsed) ||
        parsed.version !== 1 ||
        !validId(parsed.transactionId) ||
        Object.keys(parsed).length !== 2
      )
        throw new Error();
      return { transactionId: parsed.transactionId };
    } catch {
      throw new C7ExternalUpdateTransactionError(
        "restore_required",
        "The external active pointer is invalid.",
      );
    }
  }

  private async hasOrphanedActiveDirectory(): Promise<boolean> {
    let entries;
    try {
      entries = await readdir(this.updatesRoot(), { withFileTypes: true });
    } catch (error) {
      if (nodeCode(error) === "ENOENT") return false;
      throw restoreRequired();
    }
    for (const entry of entries) {
      if (entry.name === "terminal-index.json") continue;
      if (entry.isSymbolicLink() || !entry.isDirectory()) {
        throw restoreRequired();
      }
      return true;
    }
    return false;
  }

  private async commitActivePointer(pointer: {
    transactionId: string;
  }): Promise<void> {
    const bytes = canonicalJsonBytes({
      version: 1,
      transactionId: pointer.transactionId,
    });
    try {
      await writePrivateFile(this.activePath(), bytes, this.security);
    } catch (error) {
      if (nodeCode(error) === "EEXIST")
        throw new C7ExternalUpdateTransactionError(
          "busy",
          "Another external update is already active.",
        );
      throw error;
    }
  }
}

function validateStartInput(input: StartExternalUpdateInput): Required<
  Omit<StartExternalUpdateInput, "sourceSnapshot">
> & {
  sourceSnapshot?: StartExternalUpdateInput["sourceSnapshot"];
} {
  if (
    !validId(input.requestId) ||
    input.instruction.trim().length === 0 ||
    input.instruction.length > 1_000_000 ||
    input.instruction.includes("\0") ||
    !/^sha256:[a-f0-9]{64}$/u.test(input.expectedWikiRevision)
  )
    throw invalidTransaction();
  const paths = confirmedWikiPathsSchema.safeParse(input.confirmedWikiPaths);
  if (!paths.success) throw invalidTransaction();
  const materials = [...(input.materials ?? [])];
  if (
    materials.length > 64 ||
    materials.some(
      (item) =>
        item.id.trim().length === 0 ||
        item.id.length > 128 ||
        item.content.trim().length === 0 ||
        item.content.length > 1_000_000 ||
        item.content.includes("\0") ||
        (item.source !== undefined &&
          (item.source.trim().length === 0 || item.source.length > 1_024)),
    )
  )
    throw invalidTransaction();
  if (new Set(materials.map((item) => item.id)).size !== materials.length)
    throw invalidTransaction();
  try {
    verifySelectedC7Skills(input.skills);
  } catch {
    throw invalidTransaction();
  }
  if (
    (input.sourceSnapshot === undefined && input.sourceManifestId !== null) ||
    (input.sourceSnapshot !== undefined &&
      (!validId(input.sourceManifestId ?? "") ||
        !path.isAbsolute(input.sourceSnapshot.snapshotPath) ||
        !/^sha256:[a-f0-9]{64}$/u.test(input.sourceSnapshot.manifestHash) ||
        !/^sha256:[a-f0-9]{64}$/u.test(input.sourceSnapshot.snapshotTreeHash)))
  )
    throw invalidTransaction();
  if (
    input.hardRulePackage.byteLength === 0 ||
    input.candidateResultContract.byteLength === 0
  )
    throw invalidTransaction();
  return { ...input, materials, confirmedWikiPaths: paths.data };
}

function toWorkPackage(state: ExternalUpdateState): ExternalWorkPackage {
  return {
    version: 1,
    transactionId: state.transactionId,
    generation: state.generation,
    beforeWikiRevision: state.beforeWikiRevision,
    sourceManifestHash: state.sourceManifestHash,
    sourceTreeHash: state.sourceTreeHash,
    skillAggregateHash: state.skillAggregateHash,
    confirmedWikiPaths: state.confirmedWikiPaths,
    requestPackage: {
      path: state.requestPackagePath,
      packageHash: state.requestPackageHash,
    },
    bindingHash: state.bindingHash,
    candidate: {
      workspaceId: state.workspaceId,
      rootPath: state.candidateRoot,
      permissions: ["read", "list", "write"],
      allowedChangedPaths: state.confirmedWikiPaths,
    },
    sources:
      state.sourceRoot === null
        ? null
        : { rootPath: state.sourceRoot, permissions: ["read", "list"] },
    rules: {
      hardRulePackage: {
        path: state.hardRulePackagePath,
        packageHash: state.hardRulePackageHash,
      },
      skills: state.skills,
      candidateResultContract: {
        path: state.candidateResultContractPath,
        schemaHash: state.candidateResultContractSchemaHash,
      },
    },
  };
}

function toReviewPackage(
  state: ExternalUpdateState,
  input: {
    candidateRootHash: string;
    candidateReceiptHash: string;
    reviewResultContract: { path: string; schemaHash: string };
  },
): ExternalReviewPackage {
  return {
    version: 1,
    transactionId: state.transactionId,
    generation: state.generation,
    bindingHash: state.bindingHash,
    candidateRootHash: input.candidateRootHash,
    candidateReceiptHash: input.candidateReceiptHash,
    requestPackage: {
      path: state.requestPackagePath,
      packageHash: state.requestPackageHash,
    },
    sourceManifestHash: state.sourceManifestHash,
    skillAggregateHash: state.skillAggregateHash,
    confirmedWikiPaths: state.confirmedWikiPaths,
    candidate: {
      rootPath: state.candidateRoot,
      permissions: ["read", "list"],
    },
    rules: {
      hardRulePackage: {
        path: state.hardRulePackagePath,
        packageHash: state.hardRulePackageHash,
      },
      skills: state.skills,
      reviewResultContract: input.reviewResultContract,
    },
  };
}

function candidateReceiptPath(state: ExternalUpdateState): string {
  return path.join(path.dirname(state.candidateRoot), "candidate-receipt.json");
}

function reviewReceiptPath(state: ExternalUpdateState): string {
  return path.join(path.dirname(state.candidateRoot), "review-receipt.json");
}

async function readPreparedCandidateReceipt(
  state: ExternalUpdateState,
): Promise<ExternalCandidateReceipt> {
  if (state.review === null) throw restoreRequired();
  const bytes = await readRegularFile(candidateReceiptPath(state));
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw restoreRequired();
  }
  const parsed = toolInputSchemas.openwiki_finalize_external_update.safeParse({
    action: "prepare_review",
    transactionId: state.transactionId,
    bindingHash: state.bindingHash,
    candidateReceipt: value,
  });
  if (
    !parsed.success ||
    parsed.data.action !== "prepare_review" ||
    parsed.data.candidateReceipt.generation !== state.generation ||
    parsed.data.candidateReceipt.classification === "blocking" ||
    !canonicalJsonBytes(parsed.data.candidateReceipt).equals(bytes) ||
    hashDomainBytes(CANDIDATE_RECEIPT_DOMAIN, bytes) !==
      state.review.candidateReceiptHash
  ) {
    throw restoreRequired();
  }
  return parsed.data.candidateReceipt;
}

async function readPreparedReviewReceipt(state: ExternalUpdateState) {
  if (state.review === null) throw restoreRequired();
  const bytes = await readRegularFile(reviewReceiptPath(state)).catch(() => {
    throw restoreRequired();
  });
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw restoreRequired();
  }
  const parsed = toolInputSchemas.openwiki_finalize_external_update.safeParse({
    action: "submit_review",
    transactionId: state.transactionId,
    bindingHash: state.bindingHash,
    reviewReceipt: value,
  });
  if (
    !parsed.success ||
    parsed.data.action !== "submit_review" ||
    parsed.data.reviewReceipt.generation !== state.generation ||
    parsed.data.reviewReceipt.reviewPackageHash !==
      state.review.reviewPackageHash ||
    parsed.data.reviewReceipt.candidateRootHash !==
      state.review.candidateRootHash ||
    parsed.data.reviewReceipt.candidateReceiptHash !==
      state.review.candidateReceiptHash ||
    !canonicalJsonBytes(parsed.data.reviewReceipt).equals(bytes)
  ) {
    throw restoreRequired();
  }
  return parsed.data.reviewReceipt;
}

function reviewTarget(
  generation: number,
  candidateReceipt: ExternalCandidateReceipt,
  reviewReceipt: {
    readonly verdict:
      | "pass"
      | "follow_up"
      | "changes_requested"
      | "requires_user";
    readonly issues: readonly ExternalReviewIssue[];
  },
): "repair_ready" | "attention" | "publish_pending" {
  if (reviewReceipt.verdict === "changes_requested") {
    return generation < 3 ? "repair_ready" : "attention";
  }
  if (reviewReceipt.verdict === "requires_user") return "attention";
  if (reviewReceipt.verdict === "pass") return "publish_pending";
  return candidateReceipt.classification === "provisional" &&
    reviewReceipt.issues.some((issue) => issue.severity === "provisional") &&
    !reviewReceipt.issues.some((issue) => issue.severity === "blocking")
    ? "publish_pending"
    : "attention";
}

async function discardPublishPendingRecoveryJournal(input: {
  formalWikiPath: string;
  runtimeDir: string;
  state: ExternalUpdateState;
}): Promise<string> {
  const state = input.state;
  if (state.stage !== "publish_pending" || state.review === null) {
    throw restoreRequired();
  }
  await verifyImmutableState(state).catch(() => {
    throw restoreRequired();
  });
  const candidate = await snapshotMarkdownTree(state.candidateRoot).catch(
    () => {
      throw restoreRequired();
    },
  );
  if (candidate.rootHash !== state.review.candidateRootHash) {
    throw restoreRequired();
  }
  const formal = await snapshotMarkdownTree(input.formalWikiPath).catch(() => {
    throw restoreRequired();
  });
  if (formal.rootHash === candidate.rootHash) {
    throw restoreRequired();
  }

  const candidateReceipt = await readPreparedCandidateReceipt(state);
  const reviewReceipt = await readPreparedReviewReceipt(state);
  if (
    candidateReceipt.writerExecutionId === reviewReceipt.reviewerExecutionId
  ) {
    throw restoreRequired();
  }
  const reviewReceiptHash = hashDomainBytes(
    REVIEW_RECEIPT_DOMAIN,
    canonicalJsonBytes(reviewReceipt),
  );
  const plan = createExternalPublishPlan(
    state,
    await readReviewPackage(state),
    reviewReceiptHash,
  );
  const recoveryRoot = path.join(input.runtimeDir, "recovery");
  const journalPath = path.join(recoveryRoot, plan.runId);
  const journalStat = await lstat(journalPath).catch((error) => {
    if (nodeCode(error) === "ENOENT") return null;
    throw restoreRequired();
  });
  if (journalStat === null) return formal.rootHash;
  if (!journalStat.isDirectory() || journalStat.isSymbolicLink()) {
    throw restoreRequired();
  }
  const entries = await readdir(journalPath, { withFileTypes: true }).catch(
    () => {
      throw restoreRequired();
    },
  );
  const names = entries.map((entry) => entry.name).sort();
  const planPath = path.join(journalPath, "plan.json");
  const planBytes = await readRegularFile(planPath).catch(() => {
    throw restoreRequired();
  });
  let persistedPlan: ExternalWikiPublishPlan;
  try {
    persistedPlan = parseExternalWikiPublishPlan(
      JSON.parse(planBytes.toString("utf8")),
    );
  } catch {
    throw restoreRequired();
  }
  if (
    !planBytes.equals(canonicalJsonBytes(persistedPlan)) ||
    stableJson({ ...persistedPlan, version: 5 }) !== stableJson(plan)
  ) {
    throw restoreRequired();
  }
  const [before, after] = await Promise.all(
    ["before", "after"].map((name) =>
      snapshotMarkdownTree(path.join(journalPath, name)).catch(() => {
        throw restoreRequired();
      }),
    ),
  );
  if (
    before.rootHash !== plan.beforeRootHash ||
    after.rootHash !== plan.candidateRootHash
  ) {
    throw restoreRequired();
  }
  if (names.includes("commit.marker")) throw restoreRequired();
  if (persistedPlan.version === 5) {
    try {
      await verifyStablePublicationAbort({
        formalWikiPath: input.formalWikiPath,
        journalPath,
        plan: persistedPlan,
        planHash: hashBytes(planBytes),
        before,
        after,
      });
    } catch {
      throw restoreRequired();
    }
  } else {
    const directories = new Set(["after", "before", "publish"]);
    const isScratch = (name: string) =>
      /^(?:plan\.json|commit\.marker)\.[a-f0-9-]{36}\.tmp$/u.test(name);
    if (
      !["after", "before", "plan.json"].every((name) => names.includes(name)) ||
      entries.some(
        (entry) =>
          entry.isSymbolicLink() ||
          (directories.has(entry.name)
            ? !entry.isDirectory()
            : (entry.name !== "plan.json" && !isScratch(entry.name)) ||
              !entry.isFile()),
      )
    ) {
      throw restoreRequired();
    }
    if (names.includes("publish")) {
      if (
        (await snapshotMarkdownTree(path.join(journalPath, "publish")))
          .rootHash !== plan.candidateRootHash
      )
        throw restoreRequired();
    } else if (formal.rootHash !== before.rootHash) throw restoreRequired();
  }
  if (
    (await snapshotMarkdownTree(input.formalWikiPath)).rootHash !==
    formal.rootHash
  )
    throw restoreRequired();
  await removePrivateRecoveryTree(journalPath);
  return formal.rootHash;
}

async function removePrivateRecoveryTree(rootPath: string): Promise<void> {
  const entries = await readdir(rootPath, { withFileTypes: true }).catch(() => {
    throw restoreRequired();
  });
  for (const entry of entries) {
    const candidate = path.join(rootPath, entry.name);
    const stat = await lstat(candidate).catch((error) => {
      if (nodeCode(error) === "ENOENT") return null;
      throw restoreRequired();
    });
    if (stat === null) continue;
    if (stat.isSymbolicLink() || !stat.isDirectory()) {
      await rm(candidate, { force: true });
    } else {
      await removePrivateRecoveryTree(candidate);
    }
  }
  await rm(rootPath, { force: true, recursive: true }).catch(() => {
    throw restoreRequired();
  });
}

function validExternalCommitMarker(
  value: unknown,
  runId: string,
  candidateRootHash: string,
  planBytes: Uint8Array,
): boolean {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const marker = value as Record<string, unknown>;
  return (
    Object.keys(marker).sort().join(",") ===
      "afterRootHash,planHash,runId,version" &&
    marker.version === 1 &&
    marker.runId === runId &&
    marker.afterRootHash === candidateRootHash &&
    marker.planHash ===
      `sha256:${createHash("sha256").update(planBytes).digest("hex")}`
  );
}

async function verifyTerminalOrphanJournalLayout(
  journalPath: string,
  plan: ExternalWikiPublishPlan,
  formalWikiPath: string,
): Promise<void> {
  if (plan.version === 5) {
    try {
      const before = await snapshotMarkdownTree(
        path.join(journalPath, "before"),
      );
      const after = await snapshotMarkdownTree(path.join(journalPath, "after"));
      if (
        before.rootHash !== plan.beforeRootHash ||
        after.rootHash !== plan.candidateRootHash
      )
        throw restoreRequired();
      await verifyStablePublication({
        formalWikiPath,
        journalPath,
        plan,
        planHash: hashBytes(canonicalJsonBytes(plan)),
        before,
        after,
      });
      return;
    } catch {
      throw restoreRequired();
    }
  }
  let entries;
  try {
    entries = await readdir(journalPath, { withFileTypes: true });
  } catch {
    throw restoreRequired();
  }
  const expected = [
    "after",
    "before",
    "commit.marker",
    "displaced",
    "plan.json",
  ];
  const directories = new Set(["after", "before", "displaced"]);
  const files = new Set(["commit.marker", "plan.json"]);
  if (
    entries
      .map((entry) => entry.name)
      .sort()
      .join(",") !== expected.join(",") ||
    entries.some(
      (entry) =>
        entry.isSymbolicLink() ||
        (directories.has(entry.name) && !entry.isDirectory()) ||
        (files.has(entry.name) && !entry.isFile()),
    )
  ) {
    throw restoreRequired();
  }
  const [after, before, displaced] = await Promise.all(
    ["after", "before", "displaced"].map((name) =>
      snapshotMarkdownTree(path.join(journalPath, name)).catch(() => {
        throw restoreRequired();
      }),
    ),
  );
  if (
    after!.rootHash !== plan.candidateRootHash ||
    before!.rootHash !== plan.beforeRootHash ||
    displaced!.rootHash !== plan.beforeRootHash
  ) {
    throw restoreRequired();
  }
}

function externalPublishedPayload(
  state: ExternalUpdateState,
  review: NonNullable<ExternalUpdateState["review"]>,
  reviewReceiptHash: string,
  wikiRevision: string,
): Extract<ExternalTerminalPayload, { status: "published" }> {
  return {
    ok: true,
    executionMode: "external_agent",
    authRequired: false,
    transactionId: state.transactionId,
    generation: state.generation,
    bindingHash: state.bindingHash,
    recovery: { action: "none" },
    status: "published",
    published: true,
    wikiRevision,
    candidateRootHash: review.candidateRootHash,
    reviewReceiptHash,
    reviewEvidence: "host_attested",
  };
}

function createExternalPublishPlan(
  state: ExternalUpdateState,
  reviewPackage: ExternalReviewPackage,
  reviewReceiptHash: string,
): ExternalWikiPublishPlan {
  if (state.review === null) throw restoreRequired();
  const identity = {
    bindingHash: state.bindingHash,
    generation: state.generation,
    reviewReceiptHash,
    transactionId: state.transactionId,
  };
  return {
    version: 5,
    executionMode: "external_agent",
    runId: computeExternalPublishRunId(identity),
    transactionId: state.transactionId,
    generation: state.generation,
    bindingHash: state.bindingHash,
    inputHash: state.inputHash,
    beforeRootHash: state.beforeWikiRevision,
    candidateRootHash: state.review.candidateRootHash,
    requestPackageHash: state.requestPackageHash,
    candidateReceiptHash: state.review.candidateReceiptHash,
    reviewPackageHash: state.review.reviewPackageHash,
    reviewReceiptHash,
    sourceManifestHash: state.sourceManifestHash,
    sourceTreeHash: state.sourceTreeHash,
    skillAggregateHash: state.skillAggregateHash,
    orderedSkillPackages: state.skills.map(({ id, packageHash }) => ({
      id,
      packageHash,
    })),
    hardRulePackageHash: state.hardRulePackageHash,
    candidateResultContractSchemaHash: state.candidateResultContractSchemaHash,
    reviewResultContractSchemaHash:
      reviewPackage.rules.reviewResultContract.schemaHash,
    confirmedWikiPathsHash: computeConfirmedWikiPathsHash(
      state.confirmedWikiPaths,
    ),
    reviewCompletedBeforePublish: true,
  };
}

function clarificationResult(
  current: ExternalUpdateWorkspace,
  receipt: ExternalCandidateReceipt,
): Extract<ExternalReviewPreparationResult, { kind: "needs_clarification" }> {
  return {
    kind: "needs_clarification",
    state: current.state,
    stateVersion: current.stateVersion,
    issues: receipt.issues,
    questions: receipt.questions,
  };
}

async function readBlockingCandidateReceipt(
  state: ExternalUpdateState,
): Promise<Buffer> {
  const bytes = await readRegularFile(candidateReceiptPath(state));
  await parseBlockingCandidateReceipt(state, bytes);
  return bytes;
}

async function parseBlockingCandidateReceipt(
  state: ExternalUpdateState,
  retainedBytes?: Buffer,
): Promise<ExternalCandidateReceipt> {
  const bytes =
    retainedBytes ?? (await readRegularFile(candidateReceiptPath(state)));
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw restoreRequired();
  }
  const parsed = toolInputSchemas.openwiki_finalize_external_update.safeParse({
    action: "prepare_review",
    transactionId: state.transactionId,
    bindingHash: state.bindingHash,
    candidateReceipt: value,
  });
  if (
    !parsed.success ||
    parsed.data.action !== "prepare_review" ||
    parsed.data.candidateReceipt.classification !== "blocking" ||
    parsed.data.candidateReceipt.generation !== state.generation ||
    !canonicalJsonBytes(parsed.data.candidateReceipt).equals(bytes)
  ) {
    throw restoreRequired();
  }
  return parsed.data.candidateReceipt;
}

async function parseOptionalBlockingCandidateReceipt(
  state: ExternalUpdateState,
): Promise<ExternalCandidateReceipt | null> {
  try {
    return await parseBlockingCandidateReceipt(state);
  } catch (error) {
    if (nodeCode(error) === "ENOENT") return null;
    throw error;
  }
}

async function readReviewPackage(
  state: ExternalUpdateState,
): Promise<ExternalReviewPackage> {
  const review = state.review;
  if (review === null) throw new Error();
  const reviewPackageBytes = await readRegularFile(review.reviewPackagePath);
  if (
    hashDomainBytes(REVIEW_PACKAGE_DOMAIN, reviewPackageBytes) !==
    review.reviewPackageHash
  ) {
    throw new Error();
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(reviewPackageBytes.toString("utf8"));
  } catch {
    throw new Error();
  }
  if (
    (await snapshotMarkdownTree(state.candidateRoot)).rootHash !==
    review.candidateRootHash
  ) {
    throw new Error();
  }
  if (!isPlainRecord(parsed)) throw new Error();
  const task4Keys = [
    "candidateRootHash",
    "candidateReceiptHash",
    "requestPackage",
    "sourceManifestHash",
    "skillAggregateHash",
    "confirmedWikiPaths",
    "candidate",
    "rules",
  ];
  if (task4Keys.some((key) => Object.hasOwn(parsed, key))) {
    await verifyPreparedReviewPackage(state, parsed);
  }
  return parsed as ExternalReviewPackage;
}

async function verifyPreparedReviewPackage(
  state: ExternalUpdateState,
  value: unknown,
): Promise<void> {
  if (!isPlainRecord(value) || state.review === null) throw new Error();
  const reviewResultContractPath = path.join(
    state.transactionRoot,
    "immutable",
    "review-result-contract.json",
  );
  const reviewResultContractSchemaHash = hashDomainBytes(
    REVIEW_RESULT_CONTRACT_DOMAIN,
    await readRegularFile(reviewResultContractPath),
  );
  const expected = toReviewPackage(state, {
    candidateRootHash: state.review.candidateRootHash,
    candidateReceiptHash: state.review.candidateReceiptHash,
    reviewResultContract: {
      path: reviewResultContractPath,
      schemaHash: reviewResultContractSchemaHash,
    },
  });
  if (stableJson(value) !== stableJson(expected)) throw new Error();
}

async function verifyImmutableState(state: ExternalUpdateState): Promise<void> {
  await assertRegularTreeWithoutLinks(state.transactionRoot);
  const requestBytes = await readRegularFile(state.requestPackagePath);
  if (
    hashDomainBytes(REQUEST_DOMAIN, requestBytes) !== state.requestPackageHash
  )
    throw new Error();
  if (
    hashDomainBytes(
      HARD_RULE_DOMAIN,
      await readRegularFile(state.hardRulePackagePath),
    ) !== state.hardRulePackageHash
  )
    throw new Error();
  if (
    hashDomainBytes(
      RESULT_CONTRACT_DOMAIN,
      await readRegularFile(state.candidateResultContractPath),
    ) !== state.candidateResultContractSchemaHash
  )
    throw new Error();
  for (const skill of state.skills) {
    await assertRealDirectory(skill.rootPath);
    if (
      (await computeSkillPackage(skill.rootPath)).packageHash !==
      skill.packageHash
    )
      throw new Error();
  }
  if (computeSkillAggregateHash(state.skills) !== state.skillAggregateHash)
    throw new Error();
  if (
    state.sourceRoot !== null &&
    (await hashSourceSnapshotTree(state.sourceRoot)) !== state.sourceTreeHash
  )
    throw new Error();
  if (state.review !== null) {
    await readReviewPackage(state);
  }
  verifySemanticBindings(state, requestBytes);
}

function verifySemanticBindings(
  state: ExternalUpdateState,
  requestBytes: Buffer,
): void {
  let request: unknown;
  try {
    request = JSON.parse(requestBytes.toString("utf8"));
  } catch {
    throw new Error();
  }
  if (!isPlainRecord(request) || request.version !== 1) throw new Error();
  if (
    typeof request.instruction !== "string" ||
    !Array.isArray(request.materials)
  )
    throw new Error();
  const materials = request.materials.map((value) => {
    if (!isPlainRecord(value)) throw new Error();
    const keys = Object.keys(value).sort();
    const expectedKeys = [
      "byteLength",
      "content",
      "id",
      ...(value.source === undefined ? [] : ["source"]),
    ].sort();
    if (
      stableJson(keys) !== stableJson(expectedKeys) ||
      typeof value.id !== "string" ||
      typeof value.content !== "string" ||
      typeof value.byteLength !== "number" ||
      value.byteLength !== Buffer.byteLength(value.content, "utf8") ||
      (value.source !== undefined && typeof value.source !== "string")
    ) {
      throw new Error();
    }
    return {
      id: value.id,
      ...(value.source === undefined ? {} : { source: value.source }),
      content: value.content,
    };
  });
  if (
    hashCanonical("kg-c7:external-request-id:v1", state.requestId) !==
      state.requestIdHash ||
    computeBindingHash({
      transactionId: state.transactionId,
      generation: state.generation,
      workspaceId: state.workspaceId,
      beforeWikiRevision: state.beforeWikiRevision,
      requestPackageHash: state.requestPackageHash,
      sourceManifestHash: state.sourceManifestHash,
      sourceTreeHash: state.sourceTreeHash,
      skillAggregateHash: state.skillAggregateHash,
      skills: state.skills,
      confirmedWikiPaths: state.confirmedWikiPaths,
      hardRulePackageHash: state.hardRulePackageHash,
      candidateResultContractSchemaHash:
        state.candidateResultContractSchemaHash,
      inputHash: state.inputHash,
    }) !== state.bindingHash ||
    (state.sourceManifestHash === null &&
      computeStartInputHash({
        requestId: state.requestId,
        sourceManifestId: null,
        instruction: request.instruction,
        materials,
        expectedWikiRevision: state.beforeWikiRevision,
        confirmedWikiPaths: state.confirmedWikiPaths,
        sourceManifestHash: null,
        sourceTreeHash: null,
        skillAggregateHash: state.skillAggregateHash,
        skills: state.skills.map((skill) => ({
          id: skill.id,
          packageHash: skill.packageHash,
        })),
        hardRulePackageHash: state.hardRulePackageHash,
        candidateResultContractSchemaHash:
          state.candidateResultContractSchemaHash,
      }) !== state.inputHash)
  ) {
    throw new Error();
  }
}

function computeSkillAggregateHash(
  skills: readonly { id: string; packageHash: string }[],
): string {
  const hasher = createHash("sha256");
  hasher.update("kg-c7-selected-skills-v1\0", "utf8");
  for (const skill of skills) {
    hasher.update(skill.id, "utf8");
    hasher.update("\0", "ascii");
    hasher.update(skill.packageHash, "ascii");
    hasher.update("\0", "ascii");
  }
  return `sha256:${hasher.digest("hex")}`;
}

async function assertRegularTreeWithoutLinks(root: string): Promise<void> {
  const canonicalRoot = await assertRealDirectory(root);
  const { readdir } = await import("node:fs/promises");
  for (const entry of await readdir(canonicalRoot, { withFileTypes: true })) {
    const candidate = path.join(canonicalRoot, entry.name);
    const stat = await lstat(candidate);
    if (entry.isSymbolicLink() || stat.isSymbolicLink()) throw new Error();
    if (entry.isDirectory() && stat.isDirectory()) {
      await assertRegularTreeWithoutLinks(candidate);
    } else if (!entry.isFile() || !stat.isFile()) {
      throw new Error();
    }
  }
}

async function copyRegularTree(
  sourceRoot: string,
  destinationRoot: string,
  security: TransactionPathSecurity,
): Promise<void> {
  const source = await assertRealDirectory(sourceRoot);
  const entries = await import("node:fs/promises").then(({ readdir }) =>
    readdir(source, { withFileTypes: true }),
  );
  entries.sort((a, b) => a.name.localeCompare(b.name, "en"));
  for (const entry of entries) {
    const from = path.join(source, entry.name);
    const to = path.join(destinationRoot, entry.name);
    const stat = await lstat(from);
    if (entry.isSymbolicLink() || stat.isSymbolicLink()) throw new Error();
    if (entry.isDirectory() && stat.isDirectory()) {
      await mkdir(to, { mode: 0o700 });
      await security.securePrivatePath({ directory: true, targetPath: to });
      await copyRegularTree(from, to, security);
    } else if (entry.isFile() && stat.isFile()) {
      await writePrivateFile(to, await readFile(from), security);
    } else throw new Error();
  }
}

async function secureTree(
  root: string,
  security: TransactionPathSecurity,
): Promise<void> {
  const { readdir } = await import("node:fs/promises");
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const candidate = path.join(root, entry.name);
    if (entry.isDirectory()) {
      await security.securePrivatePath({
        directory: true,
        targetPath: candidate,
      });
      await secureTree(candidate, security);
    } else if (entry.isFile())
      await security.securePrivatePath({
        directory: false,
        targetPath: candidate,
      });
    else throw new Error();
  }
}

async function assertRealDirectory(value: string): Promise<string> {
  const stat = await lstat(value);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error();
  return realpath(value);
}

async function readRegularFile(value: string): Promise<Buffer> {
  const before = await lstat(value);
  if (!before.isFile() || before.isSymbolicLink()) throw new Error();
  const handle = await open(value, "r");
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || !sameFileIdentity(before, opened))
      throw new Error();
    const bytes = await handle.readFile();
    const [afterHandle, afterPath] = await Promise.all([
      handle.stat(),
      lstat(value),
    ]);
    if (
      !afterPath.isFile() ||
      afterPath.isSymbolicLink() ||
      !sameFileIdentity(opened, afterHandle) ||
      !sameFileIdentity(opened, afterPath)
    ) {
      throw new Error();
    }
    return bytes;
  } finally {
    await handle.close();
  }
}

type DirectoryIdentity = {
  readonly birthtimeMs: number;
  readonly dev: number;
  readonly ino: number;
  readonly realPath: string;
};

async function inspectRealDirectoryIdentity(
  value: string,
): Promise<DirectoryIdentity> {
  const stat = await lstat(value);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error();
  return {
    birthtimeMs: stat.birthtimeMs,
    dev: stat.dev,
    ino: stat.ino,
    realPath: await realpath(value),
  };
}

async function inspectOptionalRealDirectory(
  value: string,
): Promise<DirectoryIdentity | null> {
  try {
    return await inspectRealDirectoryIdentity(value);
  } catch (error) {
    if (nodeCode(error) === "ENOENT") return null;
    throw error;
  }
}

async function assertDirectoryIdentity(
  value: string,
  expected: DirectoryIdentity,
): Promise<void> {
  const current = await inspectRealDirectoryIdentity(value);
  if (
    current.dev !== expected.dev ||
    current.ino !== expected.ino ||
    current.birthtimeMs !== expected.birthtimeMs ||
    current.realPath.toLowerCase() !== expected.realPath.toLowerCase()
  ) {
    throw new Error();
  }
}

function sameFileIdentity(
  left: { birthtimeMs: number; dev: number; ino: number },
  right: { birthtimeMs: number; dev: number; ino: number },
): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.birthtimeMs === right.birthtimeMs
  );
}

async function writePrivateFile(
  filePath: string,
  bytes: Uint8Array,
  security: TransactionPathSecurity,
): Promise<void> {
  const handle = await open(filePath, "wx", 0o600);
  try {
    await handle.writeFile(bytes);
    await handle.sync();
  } finally {
    await handle.close();
  }
  await security.securePrivatePath({ directory: false, targetPath: filePath });
}

async function writeOrVerifyPrivateFile(
  filePath: string,
  bytes: Uint8Array,
  security: TransactionPathSecurity,
): Promise<boolean> {
  try {
    const existing = await readRegularFile(filePath);
    if (!existing.equals(bytes)) throw restoreRequired();
    return false;
  } catch (error) {
    if (nodeCode(error) !== "ENOENT") throw error;
  }
  try {
    await writePrivateFile(filePath, bytes, security);
    return true;
  } catch (error) {
    await rm(filePath, { force: true }).catch(() => undefined);
    throw error;
  }
}

function containedPath(root: string, relativePath: string): string {
  const parts = relativePath.replace(/\\/gu, "/").split("/");
  if (
    path.isAbsolute(relativePath) ||
    parts.some((part) => part === "" || part === "." || part === "..")
  )
    throw new Error();
  const result = path.resolve(root, ...parts);
  if (!isStrictDescendant(root, result)) throw new Error();
  return result;
}

function canonicalJsonBytes(value: unknown): Buffer {
  return Buffer.from(`${stableJson(value)}\n`, "utf8");
}
function hashCanonical(domain: string, value: unknown): string {
  return hashDomainBytes(domain, Buffer.from(stableJson(value), "utf8"));
}
function computeBindingHash(input: {
  transactionId: string;
  generation: number;
  workspaceId: string;
  beforeWikiRevision: string;
  requestPackageHash: string;
  sourceManifestHash: string | null;
  sourceTreeHash: string | null;
  skillAggregateHash: string;
  skills: readonly {
    id: string;
    category: "base" | "specialized";
    loadOrder: "base_always_first" | "request_order";
    packageHash: string;
  }[];
  confirmedWikiPaths: readonly string[];
  hardRulePackageHash: string;
  candidateResultContractSchemaHash: string;
  inputHash: string;
}): string {
  return hashCanonical(BINDING_DOMAIN, {
    version: 1,
    transactionId: input.transactionId,
    generation: input.generation,
    workspaceId: input.workspaceId,
    beforeWikiRevision: input.beforeWikiRevision,
    requestPackageHash: input.requestPackageHash,
    sourceManifestHash: input.sourceManifestHash,
    sourceTreeHash: input.sourceTreeHash,
    skillAggregateHash: input.skillAggregateHash,
    skills: input.skills.map(({ id, category, loadOrder, packageHash }) => ({
      id,
      category,
      loadOrder,
      packageHash,
    })),
    confirmedWikiPaths: input.confirmedWikiPaths,
    hardRulePackageHash: input.hardRulePackageHash,
    candidateResultContractSchemaHash: input.candidateResultContractSchemaHash,
    inputHash: input.inputHash,
  });
}

function computeStartInputHash(input: {
  requestId: string;
  sourceManifestId: string | null;
  instruction: string;
  materials: readonly unknown[];
  expectedWikiRevision: string;
  confirmedWikiPaths: readonly string[];
  sourceManifestHash: string | null;
  sourceTreeHash: string | null;
  skillAggregateHash: string;
  skills: readonly { id: string; packageHash: string }[];
  hardRulePackageHash: string;
  candidateResultContractSchemaHash: string;
}): string {
  return hashCanonical("kg-c7:external-start-input:v1", input);
}
function hashDomainBytes(domain: string, bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(`${domain}\0`, "utf8").update(bytes).digest("hex")}`;
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function startRequestPackageBytes(
  input: Pick<StartExternalUpdateInput, "instruction" | "materials">,
): Buffer {
  return canonicalJsonBytes({
    version: 1,
    instruction: input.instruction,
    materials: (input.materials ?? []).map((material) => ({
      id: material.id,
      ...(material.source === undefined ? {} : { source: material.source }),
      byteLength: Buffer.byteLength(material.content, "utf8"),
      content: material.content,
    })),
  });
}

async function assertNoOtherRecoveryEvidence(
  runtimeRoot: string,
  verifiedSource:
    | {
        readonly rootPath: string;
        readonly identity: DirectoryIdentity;
        readonly treeHash: string;
      }
    | undefined,
  expectedInitialization: ReadonlyMap<string, { hash: string; size: number }>,
): Promise<void> {
  const verifySource = async () => {
    if (verifiedSource === undefined) return;
    await assertDirectoryIdentity(
      verifiedSource.rootPath,
      verifiedSource.identity,
    );
    if (
      (await hashSourceSnapshotTree(verifiedSource.rootPath)) !==
      verifiedSource.treeHash
    )
      throw restoreRequired();
  };
  await verifySource();
  const rootEntries = await readdir(runtimeRoot);
  if (
    rootEntries.some((name) =>
      /^personal-(?:claims-)?finalization(?:[.]|$)/u.test(name),
    )
  )
    throw restoreRequired();
  for (const name of ["recovery", "attention", "transactions", "temp"]) {
    const directory = path.join(runtimeRoot, name);
    if (
      (await inspectOptionalRealDirectory(directory)) !== null &&
      (await readdir(directory)).length !== 0
    )
      throw restoreRequired();
  }
  const temporary = path.join(runtimeRoot, "tmp");
  if ((await inspectOptionalRealDirectory(temporary)) === null) return;
  const sourceFiles = new Map(
    [...expectedInitialization]
      .filter(([relative]) => relative.startsWith("immutable/sources/"))
      .map(
        ([relative, value]) =>
          [relative.slice("immutable/sources/".length), value] as const,
      ),
  );
  // Source snapshots and retained pre-state copies may remain here. Publication
  // or transaction records have different recovery owners and must stop replay.
  const visit = async (directory: string): Promise<void> => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const candidate = containedPath(directory, entry.name);
      if (
        verifiedSource !== undefined &&
        path.resolve(candidate).toLowerCase() ===
          path.resolve(verifiedSource.rootPath).toLowerCase()
      ) {
        await verifySource();
        continue;
      }
      if (
        directory === temporary &&
        entry.name.startsWith("snapshot-") &&
        verifiedSource !== undefined
      ) {
        await assertExpectedPartialTree(candidate, sourceFiles);
        if (
          (await hashSourceSnapshotTree(candidate)) !== verifiedSource.treeHash
        )
          throw restoreRequired();
        continue;
      }
      if (
        directory === temporary &&
        entry.name.startsWith("uncommitted-start-")
      ) {
        await assertExpectedInitializationTree(candidate, expectedInitialization);
        continue;
      }
      if (
        /^(?:commit[.]marker|attention[.]json|plan[.]json|state[.]json|active[.]json|(?:candidate|review)-receipt[.]json|review-(?:package|result-contract)[.]json|terminal-index[.]json|personal-(?:claims-)?finalization(?:[.]|$))/u.test(
          entry.name,
        )
      )
        throw restoreRequired();
      const target = containedPath(directory, entry.name);
      const stat = await lstat(target);
      if (entry.isSymbolicLink() || stat.isSymbolicLink())
        throw restoreRequired();
      if (stat.isDirectory()) {
        await inspectRealDirectoryIdentity(target);
        await visit(target);
      } else if (!stat.isFile() || stat.nlink !== 1) throw restoreRequired();
    }
  };
  await visit(temporary);
  await verifySource();
}

async function existsWithoutFollowingLinks(value: string): Promise<boolean> {
  try {
    await lstat(value);
    return true;
  } catch (error) {
    if (nodeCode(error) === "ENOENT") return false;
    throw error;
  }
}

async function fingerprintRegularTree(
  root: string,
): Promise<Map<string, { hash: string; size: number }>> {
  const files = new Map<string, { hash: string; size: number }>();
  const walk = async (directory: string, prefix: string) => {
    const identity = await inspectRealDirectoryIdentity(directory);
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const relative = prefix + entry.name;
      const absolute = containedPath(root, relative);
      const stat = await lstat(absolute);
      if (stat.isSymbolicLink()) throw restoreRequired();
      if (stat.isDirectory()) await walk(absolute, relative + "/");
      else {
        if (!stat.isFile() || stat.nlink !== 1) throw restoreRequired();
        const bytes = await readRegularFile(absolute);
        files.set(relative, { size: bytes.length, hash: hashBytes(bytes) });
      }
    }
    await assertDirectoryIdentity(directory, identity);
  };
  await walk(root, "");
  return files;
}

async function assertExpectedInitializationTree(
  root: string,
  expected: ReadonlyMap<string, { hash: string; size: number }>,
): Promise<void> {
  await assertExpectedPartialTree(root, expected, [
    "generations",
    "generations/1",
    "generations/1/candidate",
  ]);
  await inspectRealDirectoryIdentity(
    containedPath(root, "generations/1/candidate"),
  );
  const required = new Set([
    "immutable/request.json",
    "immutable/hard-rules.md",
    "immutable/candidate-result-contract.json",
    ...[...expected.keys()].filter((name) =>
      name.startsWith("generations/1/candidate/"),
    ),
  ]);
  for (const relative of required) {
    const fingerprint = expected.get(relative);
    const bytes = await readRegularFile(containedPath(root, relative));
    if (
      !fingerprint ||
      bytes.length !== fingerprint.size ||
      hashBytes(bytes) !== fingerprint.hash
    )
      throw restoreRequired();
  }
}

async function assertExpectedPartialTree(
  root: string,
  expected: ReadonlyMap<string, { hash: string; size: number }>,
  allowedEmptyDirectories: readonly string[] = [],
): Promise<void> {
  const directories = new Set(allowedEmptyDirectories);
  for (const relative of expected.keys()) {
    const components = relative.split("/");
    for (let count = 1; count < components.length; count++)
      directories.add(components.slice(0, count).join("/"));
  }
  const walk = async (directory: string, prefix: string) => {
    const identity = await inspectRealDirectoryIdentity(directory);
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const relative = prefix + entry.name;
      const absolute = containedPath(root, relative);
      const stat = await lstat(absolute);
      if (stat.isSymbolicLink()) throw restoreRequired();
      if (stat.isDirectory()) {
        if (!directories.has(relative)) throw restoreRequired();
        await walk(absolute, relative + "/");
      } else {
        const fingerprint = expected.get(relative);
        if (
          !fingerprint ||
          !stat.isFile() ||
          stat.nlink !== 1 ||
          stat.size !== fingerprint.size
        )
          throw restoreRequired();
        if (hashBytes(await readRegularFile(absolute)) !== fingerprint.hash)
          throw restoreRequired();
      }
    }
    await assertDirectoryIdentity(directory, identity);
  };
  await walk(root, "");
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (isPlainRecord(value))
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}
function isStrictDescendant(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative !== "" &&
    relative !== ".." &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  );
}
function validId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/u.test(value)
  );
}
function nodeCode(error: unknown): unknown {
  return typeof error === "object" && error !== null && "code" in error
    ? error.code
    : undefined;
}
function invalidTransaction(): C7ExternalUpdateTransactionError {
  return new C7ExternalUpdateTransactionError(
    "transaction_invalid",
    "The external update transaction input or snapshot is invalid.",
  );
}
function restoreRequired(): C7ExternalUpdateTransactionError {
  return new C7ExternalUpdateTransactionError(
    "restore_required",
    "The external update state requires recovery.",
  );
}
function validationFailed(): C7ExternalUpdateTransactionError {
  return new C7ExternalUpdateTransactionError(
    "validation_failed",
    "The external candidate failed deterministic Wiki validation.",
  );
}
function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function isLockContention(
  error: unknown,
  runtimeDir: string,
  locks: readonly C7LockName[],
): Promise<boolean> {
  if (error instanceof C7ConfigError) return error.code === "busy";
  if (typeof error !== "object" || error === null) return false;
  const lockError = error as {
    code?: unknown;
    dest?: unknown;
    path?: unknown;
  };
  if (lockError.code !== "EPERM" && lockError.code !== "EACCES") {
    return false;
  }
  if (
    typeof lockError.path !== "string" ||
    typeof lockError.dest !== "string" ||
    !locks.some(
      (lock) =>
        path
          .basename(lockError.path as string)
          .startsWith(`${lock}.pending.`) &&
        path.basename(lockError.dest as string) === `${lock}.lock`,
    ) ||
    path.dirname(lockError.path).toLowerCase() !==
      path.dirname(lockError.dest).toLowerCase()
  ) {
    return false;
  }
  const [reportedLockRoot, expectedLockRoot] = await Promise.all([
    realpath(path.dirname(lockError.path)).catch(() => null),
    realpath(path.join(runtimeDir, "locks")).catch(() => null),
  ]);
  return (
    reportedLockRoot !== null &&
    expectedLockRoot !== null &&
    reportedLockRoot.toLowerCase() === expectedLockRoot.toLowerCase()
  );
}
