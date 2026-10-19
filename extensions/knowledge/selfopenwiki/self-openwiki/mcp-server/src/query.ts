import { readFile } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import {
  resolveModelSelection,
  withC7Locks,
  type RuntimeConfig,
} from "./config.js";
import {
  modelSelectionSchema,
  toolInputSchemas,
  toolOutputSchemas,
  type ResultFailureStage,
} from "./contracts.js";
import type { ModelVerificationEvidence } from "./model-verification.js";
import { C7ProcessError } from "./process.js";
import { C7RunResultError, readModelResultJson } from "./run-result.js";
import type { SourceManifestStore } from "./sources.js";
import {
  composeSkillContract,
  type C7SkillRegistry,
  type SelectedC7Skills,
} from "./skills.js";
import {
  assertSourceContentNotSensitive,
  loadSensitiveFilePolicy,
  SensitiveSourceError,
} from "./sensitive-files.js";
import { assertMarkdownTreeVersion, C7SnapshotError } from "./snapshot.js";
import type {
  C7TransactionFactory,
  C7TransactionOperation,
} from "./transaction.js";

export type QueryProcessRunner = {
  run(input: {
    cwd: string;
    openWikiHome: string;
    operation: C7TransactionOperation;
    policyPath: string;
    selection: ModelVerificationEvidence["requested"];
    signal?: AbortSignal;
  }): Promise<{
    model: ModelVerificationEvidence;
    stderr: string;
    stdout: string;
  }>;
};

export class C7QueryError extends Error {
  constructor(
    readonly code:
      | "invalid_input"
      | "process_failure"
      | "source_rejected"
      | "wiki_changed",
    message: string,
    readonly diagnostic?: string,
    readonly failureStage?: ResultFailureStage,
  ) {
    super(message);
    this.name = "C7QueryError";
  }
}

export class OpenWikiQueryService {
  private readonly config: RuntimeConfig;
  private readonly formalWikiPath: string;
  private readonly processRunner: QueryProcessRunner;
  private readonly runtimeDir: string;
  private readonly sensitivePolicyPath: string;
  private readonly skills: C7SkillRegistry;
  private readonly sources: Pick<SourceManifestStore, "verify">;
  private readonly transactions: C7TransactionFactory;

  constructor(options: {
    config: RuntimeConfig;
    formalWikiPath: string;
    processRunner: QueryProcessRunner;
    runtimeDir: string;
    sensitivePolicyPath: string;
    skills: C7SkillRegistry;
    sources: Pick<SourceManifestStore, "verify">;
    transactions: C7TransactionFactory;
  }) {
    if (
      !path.isAbsolute(options.formalWikiPath) ||
      !path.isAbsolute(options.runtimeDir) ||
      !path.isAbsolute(options.sensitivePolicyPath)
    ) {
      throw new C7QueryError(
        "invalid_input",
        "The query service paths must be absolute.",
      );
    }
    this.config = options.config;
    this.formalWikiPath = options.formalWikiPath;
    this.processRunner = options.processRunner;
    this.runtimeDir = options.runtimeDir;
    this.sensitivePolicyPath = options.sensitivePolicyPath;
    this.skills = options.skills;
    this.sources = options.sources;
    this.transactions = options.transactions;
  }

  async query(inputValue: unknown, signal?: AbortSignal): Promise<unknown> {
    const input = parseQueryInput(inputValue);
    const policy = await loadSensitiveFilePolicy(
      this.sensitivePolicyPath,
    ).catch((error: unknown) => {
      throw mapQueryError(error);
    });
    try {
      assertSourceContentNotSensitive(input.instruction, policy);
      for (const material of input.materials ?? []) {
        assertSourceContentNotSensitive(material.content, policy);
      }
    } catch (error) {
      throw mapQueryError(error);
    }

    const selection = resolveModelSelection(
      this.config,
      input.modelOverride,
    ).selection;
    let selected: SelectedC7Skills;
    try {
      selected = this.skills.select(input.skills ?? []);
    } catch (error) {
      throw mapQueryError(error);
    }

    let sourceSnapshot:
      | Awaited<ReturnType<SourceManifestStore["verify"]>>
      | undefined;
    if (input.sourceManifestId !== undefined) {
      sourceSnapshot = await this.sources.verify({
        confirmation: input.sourceConfirmation!,
        sourceManifestId: input.sourceManifestId,
      });
    }
    const requestMarkdown = renderQueryRequest(input, selected);
    let queryResult: unknown;
    let queryFailure: unknown;
    try {
      queryResult = await withC7Locks(
        this.runtimeDir,
        ["operation"],
        async () => {
          let workspace:
            | Awaited<ReturnType<C7TransactionFactory["create"]>>
            | undefined;
          let result: unknown;
          let operationError: unknown;
          try {
            result = await withC7Locks(this.runtimeDir, ["wiki"], async () => {
              workspace = await this.transactions.create({
                operation: "query",
                requestMarkdown,
                selection,
                skills: selected,
                ...(sourceSnapshot
                  ? {
                      sourceSnapshot: {
                        manifestHash: sourceSnapshot.manifestHash,
                        snapshotPath: sourceSnapshot.snapshotPath,
                        snapshotTreeHash: sourceSnapshot.snapshotTreeHash,
                      },
                    }
                  : {}),
              });
              await workspace.transitionStage("running");
              const processResult = await this.processRunner.run({
                cwd: workspace.homePath,
                openWikiHome: workspace.homePath,
                operation: "query",
                policyPath: workspace.policyPath,
                selection,
                signal,
              });
              assertExactModelEvidence(selection, processResult.model);
              await workspace.transitionStage("model_complete");
              await assertMarkdownTreeVersion(
                this.formalWikiPath,
                workspace.beforeWiki,
              );
              const binding = parseJson(
                await readFile(
                  path.join(
                    workspace.homePath,
                    "_c7-control",
                    "in",
                    "binding.json",
                  ),
                  "utf8",
                ),
              );
              const modelResult = queryModelResultSchema.safeParse(
                await readModelResultJson(
                  path.join(
                    workspace.homePath,
                    "_c7-control",
                    "out",
                    "result.json",
                  ),
                ),
              );
              if (!modelResult.success) {
                throw new C7QueryError(
                  "process_failure",
                  "The OpenWiki query result does not match its strict schema.",
                  undefined,
                  "result_schema_invalid",
                );
              }
              if (
                stableJson(modelResult.data.binding) !== stableJson(binding)
              ) {
                throw new C7QueryError(
                  "process_failure",
                  "The OpenWiki query result is not bound to this transaction.",
                  undefined,
                  "result_binding_mismatch",
                );
              }
              const output = toolOutputSchemas.openwiki_query.parse({
                answer: modelResult.data.answer,
                model: processResult.model,
                ok: true,
                recovery: { action: "none" },
                selectedSkills: selected.skills.map((skill) => ({
                  id: skill.id,
                  packageHash: skill.packageHash,
                })),
                skillAggregateHash: selected.aggregateHash,
                ...(sourceSnapshot
                  ? { sourceManifestHash: sourceSnapshot.manifestHash }
                  : {}),
                status: "answered",
                wikiRevision: workspace.beforeWiki.rootHash,
              });
              await workspace.transitionStage("completed");
              return output;
            });
          } catch (error) {
            operationError = error;
            if (workspace !== undefined) {
              await workspace.transitionStage("failed").catch(() => undefined);
            }
          }

          if (workspace !== undefined) {
            try {
              await workspace.finalizeCredentials();
            } catch (error) {
              operationError ??= error;
            }
            try {
              await workspace.cleanup();
            } catch (error) {
              operationError ??= error;
            }
          }
          if (operationError !== undefined) throw mapQueryError(operationError);
          return result;
        },
      );
    } catch (error) {
      queryFailure = error;
    }
    try {
      await sourceSnapshot?.cleanup();
    } catch (error) {
      queryFailure ??= error;
    }
    if (queryFailure !== undefined) throw mapQueryError(queryFailure);
    return queryResult;
  }
}

const queryModelResultSchema = z.strictObject({
  answer: z.string().max(2_000_000),
  binding: z.unknown(),
  type: z.literal("query_result"),
  version: z.literal(1),
});

function parseQueryInput(value: unknown) {
  const parsed = toolInputSchemas.openwiki_query.safeParse(value);
  if (!parsed.success) {
    throw new C7QueryError(
      "invalid_input",
      "The openwiki_query input is invalid.",
    );
  }
  return parsed.data;
}

function renderQueryRequest(
  input: ReturnType<typeof parseQueryInput>,
  selected: SelectedC7Skills,
): string {
  const materials = (input.materials ?? []).map((material) =>
    [
      `### Material ${JSON.stringify(material.id)}`,
      ...(material.source
        ? [`Source label: ${JSON.stringify(material.source)}`]
        : []),
      "```text",
      material.content.replace(/```/gu, "` ` `"),
      "```",
    ].join("\n"),
  );
  return [
    "# C7 bound query transaction",
    "Answer from the temporary Wiki and confirmed evidence only. Do not modify /openwiki, /sources, /skills, or /_c7-control/in.",
    "Write exactly one strict JSON object to /_c7-control/out/result.json with version=1, type=query_result, answer, and an exact copy of /_c7-control/in/binding.json under binding. Do not add other output files.",
    "## User instruction",
    input.instruction,
    ...(materials.length > 0 ? ["## Ephemeral materials", ...materials] : []),
    "## Mandatory C7 Skill contract",
    composeSkillContract(selected.skills),
  ].join("\n\n");
}

function assertExactModelEvidence(
  selection: z.infer<typeof modelSelectionSchema>,
  evidence: ModelVerificationEvidence,
): void {
  if (
    evidence.providerAccepted !== true ||
    evidence.requested.model !== selection.model ||
    evidence.requested.reasoningEffort !== selection.reasoningEffort ||
    evidence.sent.model !== selection.model ||
    evidence.sent.reasoningEffort !== selection.reasoningEffort
  ) {
    throw new C7QueryError(
      "process_failure",
      "The OpenWiki query model evidence did not match the requested selection.",
    );
  }
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    throw new C7QueryError(
      "process_failure",
      "The OpenWiki query produced invalid structured output.",
    );
  }
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function mapQueryError(error: unknown): C7QueryError {
  if (error instanceof C7QueryError) return error;
  if (error instanceof SensitiveSourceError) {
    return new C7QueryError(
      "source_rejected",
      "The query contains credential-like material and was rejected.",
    );
  }
  if (error instanceof C7SnapshotError) {
    return new C7QueryError(
      "wiki_changed",
      "The formal Wiki changed during the isolated query.",
    );
  }
  if (error instanceof C7RunResultError) {
    return new C7QueryError(
      "process_failure",
      "The OpenWiki query result did not satisfy its strict protocol.",
      undefined,
      error.failureStage,
    );
  }
  if (error instanceof C7ProcessError) {
    return new C7QueryError(
      "process_failure",
      "The isolated OpenWiki query failed.",
      error.diagnostic,
    );
  }
  return new C7QueryError(
    "process_failure",
    "The isolated OpenWiki query failed.",
  );
}
