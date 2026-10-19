import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  realpath,
  rm,
} from "node:fs/promises";
import path from "node:path";
import type { TemporaryOpenWikiHome } from "./credential-store.js";
import { confirmedWikiPathsSchema, modelSelectionSchema } from "./contracts.js";
import type { ModelSelection } from "./model-verification.js";
import {
  REVIEW_RESULT_CONTRACT,
  reviewBindingSchema,
  UPDATE_RESULT_CONTRACT,
} from "./run-result.js";
import { hashSourceSnapshotTree } from "./sources.js";
import {
  copyMarkdownTree,
  snapshotMarkdownTree,
  type MarkdownTreeSnapshot,
} from "./snapshot.js";
import { verifySelectedC7Skills, type SelectedC7Skills } from "./skills.js";
import {
  readTransactionState,
  transitionTransactionState,
  type C7TransactionStage,
  type C7TransactionState,
} from "./transaction-state.js";

export type C7TransactionOperation = "query" | "repair" | "review" | "update";

export interface TransactionPathSecurity {
  securePrivatePath(input: {
    directory: boolean;
    targetPath: string;
  }): Promise<unknown>;
}

export type C7TransactionWorkspace = {
  readonly beforeWiki: MarkdownTreeSnapshot;
  cleanup(): Promise<void>;
  finalizeCredentials(): Promise<void>;
  readonly homePath: string;
  readonly policyPath: string;
  readonly resultFinalizer: {
    readonly policyPath: string;
    readonly requestFileName: "result-finalizer.md";
  } | null;
  readonly runId: string;
  readonly statePath: string;
  readonly transactionDir: string;
  transitionStage(stage: C7TransactionStage): Promise<C7TransactionState>;
  readonly wikiPath: string;
};

export class C7TransactionError extends Error {
  constructor(
    readonly code: "transaction_invalid" | "transaction_prepare_failed",
    message: string,
  ) {
    super(message);
    this.name = "C7TransactionError";
  }
}

export class C7TransactionFactory {
  private readonly createHomeLease: () => Promise<TemporaryOpenWikiHome>;
  private readonly createRunId: () => string;
  private readonly formalWikiPath: string;
  private readonly now: () => Date;
  private readonly runtimeDir: string;
  private readonly security: TransactionPathSecurity;

  constructor(options: {
    createHomeLease(): Promise<TemporaryOpenWikiHome>;
    createRunId?(): string;
    formalWikiPath: string;
    now?(): Date;
    runtimeDir: string;
    security: TransactionPathSecurity;
  }) {
    if (
      !path.isAbsolute(options.formalWikiPath) ||
      !path.isAbsolute(options.runtimeDir)
    ) {
      throw new C7TransactionError(
        "transaction_invalid",
        "C7 transaction paths must be absolute.",
      );
    }
    this.createHomeLease = options.createHomeLease;
    this.createRunId = options.createRunId ?? (() => `run-${randomUUID()}`);
    this.formalWikiPath = options.formalWikiPath;
    this.now = options.now ?? (() => new Date());
    this.runtimeDir = options.runtimeDir;
    this.security = options.security;
  }

  async create(input: {
    baseWiki?: {
      path: string;
      rootHash: string;
    };
    confirmedWikiPaths?: readonly string[];
    operation: C7TransactionOperation;
    requestMarkdown: string;
    reviewBinding?: unknown;
    selection: ModelSelection;
    skills: SelectedC7Skills;
    sourceSnapshot?: {
      manifestHash: string;
      snapshotPath: string;
      snapshotTreeHash: string;
    };
  }): Promise<C7TransactionWorkspace> {
    const parsedSelection = modelSelectionSchema.safeParse(input.selection);
    const parsedReviewBinding = reviewBindingSchema.safeParse(
      input.reviewBinding,
    );
    if (
      !parsedSelection.success ||
      !/^(?:query|repair|review|update)$/u.test(input.operation) ||
      input.requestMarkdown.length === 0 ||
      Buffer.byteLength(input.requestMarkdown, "utf8") > 1024 * 1024 ||
      input.requestMarkdown.includes("\0")
    ) {
      throw new C7TransactionError(
        "transaction_invalid",
        "The C7 transaction request is invalid.",
      );
    }
    if ((input.operation === "review") !== parsedReviewBinding.success) {
      throw new C7TransactionError(
        "transaction_invalid",
        "Review transactions require one strict review binding.",
      );
    }
    if (
      input.baseWiki !== undefined &&
      input.operation !== "review" &&
      input.operation !== "repair"
    ) {
      throw new C7TransactionError(
        "transaction_invalid",
        "Candidate Wiki bases are valid only for review and repair transactions.",
      );
    }
    if (
      input.baseWiki !== undefined &&
      (!path.isAbsolute(input.baseWiki.path) ||
        !/^sha256:[a-f0-9]{64}$/u.test(input.baseWiki.rootHash))
    ) {
      throw new C7TransactionError(
        "transaction_invalid",
        "The candidate Wiki base binding is invalid.",
      );
    }
    const carriesUpdateBinding =
      input.operation === "update" || input.operation === "repair";
    let confirmedWikiPaths: string[] | null | undefined;
    if (carriesUpdateBinding) {
      const parsedConfirmedWikiPaths = confirmedWikiPathsSchema
        .nullable()
        .safeParse(input.confirmedWikiPaths ?? null);
      if (!parsedConfirmedWikiPaths.success) {
        throw new C7TransactionError(
          "transaction_invalid",
          "The confirmed Wiki path binding is invalid.",
        );
      }
      confirmedWikiPaths = parsedConfirmedWikiPaths.data;
    } else if (input.confirmedWikiPaths !== undefined) {
      throw new C7TransactionError(
        "transaction_invalid",
        "Confirmed Wiki paths are valid only for update transactions.",
      );
    }
    assertSelectedSkills(input.skills);
    if (
      input.sourceSnapshot !== undefined &&
      (!path.isAbsolute(input.sourceSnapshot.snapshotPath) ||
        !/^sha256:[a-f0-9]{64}$/u.test(input.sourceSnapshot.manifestHash) ||
        !/^sha256:[a-f0-9]{64}$/u.test(input.sourceSnapshot.snapshotTreeHash))
    ) {
      throw new C7TransactionError(
        "transaction_invalid",
        "The C7 source snapshot binding is invalid.",
      );
    }

    const runId = this.createRunId();
    if (!/^run-[A-Za-z0-9._:-]{8,160}$/u.test(runId)) {
      throw new C7TransactionError(
        "transaction_invalid",
        "The C7 transaction identifier is invalid.",
      );
    }
    const lease = await this.createHomeLease();
    const transactionRoot = path.join(this.runtimeDir, "transactions");
    const transactionDir = path.join(transactionRoot, runId);
    let transactionCreated = false;
    try {
      await mkdir(transactionRoot, { mode: 0o700, recursive: true });
      await this.security.securePrivatePath({
        directory: true,
        targetPath: transactionRoot,
      });
      await mkdir(transactionDir, { mode: 0o700 });
      transactionCreated = true;
      await this.security.securePrivatePath({
        directory: true,
        targetPath: transactionDir,
      });

      const homePath = await canonicalDirectory(lease.path, "temporary Home");
      await this.security.securePrivatePath({
        directory: true,
        targetPath: homePath,
      });
      const wikiPath = path.join(homePath, "openwiki");
      const sourcesPath = path.join(homePath, "sources");
      const upstreamSkillsPath = path.join(homePath, "skills");
      const conversationHistoryPath = path.join(
        homePath,
        "conversation_history",
      );
      const controlInPath = path.join(homePath, "_c7-control", "in");
      const controlOutPath = path.join(homePath, "_c7-control", "out");
      const c7SkillsPath = path.join(controlInPath, "c7-skills");
      for (const directory of [
        wikiPath,
        sourcesPath,
        upstreamSkillsPath,
        conversationHistoryPath,
        path.dirname(controlInPath),
        controlInPath,
        c7SkillsPath,
        controlOutPath,
      ]) {
        await mkdir(directory, { mode: 0o700 });
        await this.security.securePrivatePath({
          directory: true,
          targetPath: directory,
        });
      }

      await mkdir(this.formalWikiPath, { mode: 0o700, recursive: true });
      const baseWikiPath = input.baseWiki?.path ?? this.formalWikiPath;
      const beforeWiki = await snapshotMarkdownTree(baseWikiPath);
      if (
        input.baseWiki !== undefined &&
        beforeWiki.rootHash !== input.baseWiki.rootHash
      ) {
        throw new C7TransactionError(
          "transaction_prepare_failed",
          "The candidate Wiki base changed before the transaction was prepared.",
        );
      }
      await copyMarkdownTree(baseWikiPath, wikiPath, beforeWiki);
      await secureRegularTree(wikiPath, this.security);

      let sourceTreeHash: string | null = null;
      if (input.sourceSnapshot !== undefined) {
        sourceTreeHash = await copyRegularTree(
          input.sourceSnapshot.snapshotPath,
          sourcesPath,
          input.sourceSnapshot.snapshotTreeHash,
          this.security,
        );
      }
      await writeSkillSnapshots(c7SkillsPath, input.skills, this.security);

      const requestPath = path.join(controlInPath, "request.md");
      await writePrivateFile(
        requestPath,
        Buffer.from(input.requestMarkdown, "utf8"),
        this.security,
      );
      await writePrivateFile(
        path.join(controlInPath, "binding.json"),
        jsonBytes({
          beforeWikiRootHash: beforeWiki.rootHash,
          ...(carriesUpdateBinding ? { confirmedWikiPaths } : {}),
          model: parsedSelection.data,
          operation: input.operation,
          ...(parsedReviewBinding.success
            ? { review: parsedReviewBinding.data }
            : {}),
          skillAggregateHash: input.skills.aggregateHash,
          sourceManifestHash: input.sourceSnapshot?.manifestHash ?? null,
          sourceTreeHash,
          version: 1,
        }),
        this.security,
      );

      const policyPath = path.join(transactionDir, "run-policy.json");
      const writableWiki =
        input.operation === "update" || input.operation === "repair";
      await writePrivateFile(
        policyPath,
        await runPolicyBytes({
          controlInPath,
          controlOutPath,
          conversationHistoryPath,
          homePath,
          sourcesPath,
          upstreamSkillsPath,
          wikiPath,
          writableWiki,
        }),
        this.security,
      );
      let resultFinalizer: C7TransactionWorkspace["resultFinalizer"] = null;
      if (
        input.operation === "update" ||
        input.operation === "repair" ||
        input.operation === "review"
      ) {
        const requestFileName = "result-finalizer.md" as const;
        await writePrivateFile(
          path.join(controlInPath, requestFileName),
          Buffer.from(renderResultFinalizerRequest(input.operation), "utf8"),
          this.security,
        );
        const resultFinalizerPolicyPath = path.join(
          transactionDir,
          "result-finalizer-policy.json",
        );
        await writePrivateFile(
          resultFinalizerPolicyPath,
          await runPolicyBytes({
            controlInPath,
            controlOutPath,
            conversationHistoryPath,
            homePath,
            sourcesPath,
            upstreamSkillsPath,
            wikiPath,
            writableWiki: false,
          }),
          this.security,
        );
        resultFinalizer = {
          policyPath: resultFinalizerPolicyPath,
          requestFileName,
        };
      }

      const statePath = path.join(transactionDir, "state.json");
      const createdAt = this.now().toISOString();
      await writePrivateFile(
        statePath,
        jsonBytes({
          beforeWikiRootHash: beforeWiki.rootHash,
          createdAt,
          generation: 1,
          homePath,
          model: parsedSelection.data,
          operation: input.operation,
          pid: process.pid,
          policyPath,
          reviewRequired: writableWiki,
          runId,
          skillAggregateHash: input.skills.aggregateHash,
          sourceManifestHash: input.sourceSnapshot?.manifestHash ?? null,
          stage: "prepared",
          updatedAt: createdAt,
          version: 1,
          wikiPath,
        }),
        this.security,
      );
      let stateVersion = (await readTransactionState(statePath)).version;
      const now = this.now;
      const security = this.security;

      let cleaned = false;
      let credentialsFinalized = false;
      return {
        beforeWiki,
        async cleanup() {
          if (cleaned) return;
          await lease.cleanup();
          await rm(transactionDir, {
            force: true,
            maxRetries: 20,
            recursive: true,
            retryDelay: 25,
          });
          cleaned = true;
        },
        async finalizeCredentials() {
          if (credentialsFinalized) return;
          await lease.finalize?.();
          credentialsFinalized = true;
        },
        homePath,
        policyPath,
        resultFinalizer,
        runId,
        statePath,
        transactionDir,
        async transitionStage(stage) {
          const transitioned = await transitionTransactionState(
            statePath,
            stateVersion,
            stage,
            now(),
            security,
          );
          stateVersion = transitioned.version;
          return transitioned.state;
        },
        wikiPath,
      };
    } catch (error) {
      await lease.cleanup().catch(() => undefined);
      if (transactionCreated) {
        await rm(transactionDir, {
          force: true,
          maxRetries: 20,
          recursive: true,
          retryDelay: 25,
        }).catch(() => undefined);
      }
      if (error instanceof C7TransactionError) throw error;
      throw new C7TransactionError(
        "transaction_prepare_failed",
        "The isolated C7 transaction could not be prepared.",
      );
    }
  }
}

async function runPolicyBytes(input: {
  controlInPath: string;
  controlOutPath: string;
  conversationHistoryPath: string;
  homePath: string;
  sourcesPath: string;
  upstreamSkillsPath: string;
  wikiPath: string;
  writableWiki: boolean;
}): Promise<Buffer> {
  return jsonBytes({
    disableConnectors: true,
    mounts: [
      {
        id: "wiki",
        path: await realpath(input.wikiPath),
        permissions: input.writableWiki
          ? ["read", "list", "write"]
          : ["read", "list"],
      },
      {
        id: "sources",
        path: await realpath(input.sourcesPath),
        permissions: ["read", "list"],
      },
      {
        id: "skills",
        path: await realpath(input.upstreamSkillsPath),
        permissions: ["read", "list"],
      },
      {
        id: "conversation-history",
        path: await realpath(input.conversationHistoryPath),
        permissions: ["read", "list", "write"],
      },
      {
        id: "control-in",
        path: await realpath(input.controlInPath),
        permissions: ["read", "list"],
      },
      {
        id: "control-out",
        path: await realpath(input.controlOutPath),
        permissions: ["read", "list", "write"],
      },
    ],
    rootDir: input.homePath,
    synchronizeWikiIndexes: false,
    version: 1,
  });
}

function renderResultFinalizerRequest(
  operation: "repair" | "review" | "update",
): string {
  const isReview = operation === "review";
  return [
    `# C7 bounded ${isReview ? "review" : "update"} result finalizer`,
    `The main ${isReview ? "review" : "update"} pass has completed and the candidate Wiki is read-only.`,
    "Read /_c7-control/in/request.md, /_c7-control/in/binding.json, the candidate /openwiki, and confirmed read-only evidence only as needed.",
    "Do not modify /openwiki, sources, Skills, the original request, or binding. Do not expand or redo the update.",
    `Write exactly one strict ${isReview ? "review_result" : "update_result"} JSON object to /_c7-control/out/result.json.`,
    isReview ? REVIEW_RESULT_CONTRACT : UPDATE_RESULT_CONTRACT,
  ].join("\n\n");
}

type RegularTreeSnapshot = {
  files: Array<{ hash: string; relativePath: string; size: number }>;
  rootHash: string;
};

async function copyRegularTree(
  sourceRoot: string,
  destinationRoot: string,
  expectedSourceTreeHash: string,
  security: TransactionPathSecurity,
): Promise<string> {
  if ((await hashSourceSnapshotTree(sourceRoot)) !== expectedSourceTreeHash) {
    throw new Error("Source snapshot tree does not match its bound hash.");
  }
  const before = await snapshotRegularTree(sourceRoot);
  for (const file of before.files) {
    const sourcePath = containedPath(sourceRoot, file.relativePath);
    const destinationPath = containedPath(destinationRoot, file.relativePath);
    const bytes = await readFile(sourcePath);
    if (bytes.byteLength !== file.size || hashBytes(bytes) !== file.hash) {
      throw new Error("Source snapshot changed while it was copied.");
    }
    await mkdir(path.dirname(destinationPath), {
      mode: 0o700,
      recursive: true,
    });
    await security.securePrivatePath({
      directory: true,
      targetPath: path.dirname(destinationPath),
    });
    await writePrivateFile(destinationPath, bytes, security);
  }
  const afterSource = await snapshotRegularTree(sourceRoot);
  const copied = await snapshotRegularTree(destinationRoot);
  if (
    afterSource.rootHash !== before.rootHash ||
    copied.rootHash !== before.rootHash ||
    (await hashSourceSnapshotTree(sourceRoot)) !== expectedSourceTreeHash ||
    (await hashSourceSnapshotTree(destinationRoot)) !== expectedSourceTreeHash
  ) {
    throw new Error("Source snapshot changed while it was copied.");
  }
  return expectedSourceTreeHash;
}

async function snapshotRegularTree(root: string): Promise<RegularTreeSnapshot> {
  const canonicalRoot = await canonicalDirectory(root, "source snapshot");
  const files: RegularTreeSnapshot["files"] = [];
  await collectRegularFiles(canonicalRoot, "", files);
  files.sort((left, right) =>
    left.relativePath < right.relativePath ? -1 : 1,
  );
  const hasher = createHash("sha256");
  hasher.update("kg-c7-regular-tree-v1\0", "utf8");
  for (const file of files) {
    hasher.update(file.relativePath, "utf8");
    hasher.update("\0", "ascii");
    hasher.update(String(file.size), "ascii");
    hasher.update("\0", "ascii");
    hasher.update(file.hash, "ascii");
    hasher.update("\0", "ascii");
  }
  return { files, rootHash: `sha256:${hasher.digest("hex")}` };
}

async function collectRegularFiles(
  root: string,
  relativeDirectory: string,
  files: RegularTreeSnapshot["files"],
): Promise<void> {
  const directory =
    relativeDirectory === "" ? root : path.join(root, relativeDirectory);
  const entries = await readdir(directory, { withFileTypes: true });
  entries.sort((left, right) => (left.name < right.name ? -1 : 1));
  for (const entry of entries) {
    const relativePath =
      relativeDirectory === ""
        ? entry.name
        : path.join(relativeDirectory, entry.name);
    const normalized = relativePath.split(path.sep).join("/");
    const absolutePath = path.join(root, relativePath);
    const stat = await lstat(absolutePath);
    if (entry.isSymbolicLink() || stat.isSymbolicLink()) {
      throw new Error("Transaction snapshots cannot contain links.");
    }
    if (entry.isDirectory() && stat.isDirectory()) {
      await collectRegularFiles(root, relativePath, files);
      continue;
    }
    if (!entry.isFile() || !stat.isFile()) {
      throw new Error("Transaction snapshots require regular files.");
    }
    const bytes = await readFile(absolutePath);
    files.push({
      hash: hashBytes(bytes),
      relativePath: normalized,
      size: bytes.byteLength,
    });
  }
}

async function writeSkillSnapshots(
  skillsRoot: string,
  selected: SelectedC7Skills,
  security: TransactionPathSecurity,
): Promise<void> {
  const seen = new Set<string>();
  for (const skill of selected.skills) {
    if (!skill.verified || seen.has(skill.id)) {
      throw new Error("Selected Skill snapshots are invalid.");
    }
    seen.add(skill.id);
    const skillRoot = path.join(skillsRoot, skill.id);
    await mkdir(skillRoot, { mode: 0o700 });
    await security.securePrivatePath({
      directory: true,
      targetPath: skillRoot,
    });
    for (const file of skill.files) {
      if (
        file.size !== file.bytes.byteLength ||
        file.hash !== hashBytes(file.bytes)
      ) {
        throw new Error("Selected Skill file evidence is invalid.");
      }
      const destination = containedPath(skillRoot, file.relativePath);
      await mkdir(path.dirname(destination), { mode: 0o700, recursive: true });
      await security.securePrivatePath({
        directory: true,
        targetPath: path.dirname(destination),
      });
      await writePrivateFile(destination, file.bytes, security);
    }
  }
}

async function secureRegularTree(
  root: string,
  security: TransactionPathSecurity,
): Promise<void> {
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    const candidate = path.join(root, entry.name);
    if (entry.isDirectory()) {
      await security.securePrivatePath({
        directory: true,
        targetPath: candidate,
      });
      await secureRegularTree(candidate, security);
    } else if (entry.isFile()) {
      await security.securePrivatePath({
        directory: false,
        targetPath: candidate,
      });
    } else {
      throw new Error("The copied Wiki contains an unsupported file object.");
    }
  }
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

async function canonicalDirectory(
  value: string,
  label: string,
): Promise<string> {
  if (!path.isAbsolute(value)) throw new Error(`${label} must be absolute.`);
  const stat = await lstat(value);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`${label} must be a regular non-link directory.`);
  }
  return realpath(value);
}

function containedPath(root: string, relativePath: string): string {
  const segments = relativePath.replace(/\\/gu, "/").split("/");
  if (
    path.isAbsolute(relativePath) ||
    segments.some(
      (segment) => segment === "" || segment === "." || segment === "..",
    )
  ) {
    throw new Error("A transaction snapshot path is invalid.");
  }
  const candidate = path.resolve(root, ...segments);
  const relative = path.relative(root, candidate);
  if (
    relative === "" ||
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new Error("A transaction snapshot path escapes its root.");
  }
  return candidate;
}

function assertSelectedSkills(skills: SelectedC7Skills): void {
  try {
    verifySelectedC7Skills(skills);
  } catch {
    throw new C7TransactionError(
      "transaction_invalid",
      "The selected C7 Skill snapshot is invalid.",
    );
  }
}

function jsonBytes(value: unknown): Buffer {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
