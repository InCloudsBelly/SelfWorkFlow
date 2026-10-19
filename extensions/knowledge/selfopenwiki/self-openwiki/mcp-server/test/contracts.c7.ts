import { describe, expect, test, vi } from "vitest";
import {
  TOOL_NAMES,
  toolAnnotations,
  toolInputSchemas,
  toolOutputSchemas,
} from "../src/contracts.js";

const model = {
  model: "gpt-5.6-sol",
  reasoningEffort: "xhigh",
};
const hash = `sha256:${"a".repeat(64)}`;
const secondHash = `sha256:${"b".repeat(64)}`;
const modelEvidence = {
  providerAccepted: true,
  requested: model,
  sent: model,
};
const recovery = { action: "none" };
const selectedSkills = [{ id: "kg-c7-project-wiki", packageHash: hash }];
const updateOutcomeMetadata = {
  baseWikiRevision: hash,
  changes: [],
  model: modelEvidence,
  questions: [],
  recoveryState: "clean",
  review: { rounds: 1, status: "passed" },
  selectedSkills,
  skillAggregateHash: hash,
  validation: {
    passed: true,
    checks: [{ id: "wiki_tree", status: "passed" }],
  },
};

const requestPackage = {
  path: "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\request.json",
  packageHash: hash,
};
const rules = {
  hardRulePackage: {
    path: "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\rules\\hard-rules.json",
    packageHash: hash,
  },
  skills: [
    {
      id: "kg-c7-project-wiki",
      category: "base",
      loadOrder: "base_always_first",
      packageHash: hash,
      rootPath:
        "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\skills\\kg-c7-project-wiki",
    },
    {
      id: "kg-c7-cpp",
      category: "specialized",
      loadOrder: "request_order",
      packageHash: secondHash,
      rootPath:
        "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\skills\\kg-c7-cpp",
    },
  ],
};
const workPackage = {
  version: 1,
  transactionId: "tx-12345678",
  generation: 1,
  beforeWikiRevision: hash,
  sourceManifestHash: null,
  sourceTreeHash: null,
  skillAggregateHash: hash,
  confirmedWikiPaths: ["architecture/external-agent.md"],
  requestPackage,
  bindingHash: secondHash,
  candidate: {
    workspaceId: "workspace-12345678",
    rootPath:
      "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\candidate",
    permissions: ["read", "list", "write"],
    allowedChangedPaths: ["architecture/external-agent.md"],
  },
  sources: null,
  rules: {
    ...rules,
    candidateResultContract: {
      path: "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\rules\\candidate-result.json",
      schemaHash: hash,
    },
  },
};
const reviewPackage = {
  version: 1,
  transactionId: "tx-12345678",
  generation: 1,
  bindingHash: secondHash,
  candidateRootHash: hash,
  candidateReceiptHash: secondHash,
  requestPackage,
  sourceManifestHash: null,
  skillAggregateHash: hash,
  confirmedWikiPaths: ["architecture/external-agent.md"],
  candidate: {
    rootPath:
      "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\candidate",
    permissions: ["read", "list"],
  },
  rules: {
    ...rules,
    reviewResultContract: {
      path: "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\rules\\review-result.json",
      schemaHash: hash,
    },
  },
};
const candidateReceipt = {
  type: "external_candidate_receipt",
  version: 1,
  transactionId: "tx-12345678",
  generation: 1,
  bindingHash: secondHash,
  writerExecutionId: "writer-12345678",
  classification: "minor",
  issues: [],
  questions: [],
  summary: "Updated the confirmed page from the bound evidence.",
};
const reviewReceipt = {
  type: "external_review_receipt",
  version: 1,
  transactionId: "tx-12345678",
  generation: 1,
  bindingHash: secondHash,
  reviewPackageHash: hash,
  candidateRootHash: hash,
  candidateReceiptHash: secondHash,
  reviewerExecutionId: "reviewer-12345678",
  verdict: "pass",
  issues: [],
};
const externalOutcomeCommon = {
  ok: true,
  executionMode: "external_agent",
  authRequired: false,
  transactionId: "tx-12345678",
  generation: 1,
  bindingHash: secondHash,
  recovery,
};
const personalRunId = "00000000-0000-4000-8000-000000000001";
const personalJobId = "00000000-0000-4000-8000-000000000002";
const personalBinding = {
  runId: personalRunId,
  generation: 1,
  transactionId: "tx-12345678",
  candidateBindingHash: hash,
  candidateRootHash: hash,
  queueHash: hash,
  planHash: hash,
  wikiRevision: hash,
};
const personalCandidate = {
  rootPath:
    "D:\\personal-wiki.selfopenwiki\\transactions\\tx-12345678\\generations\\1\\candidate",
  pagePath: "quickstart.md",
  permissions: ["read", "list", "write"],
};

const validInputs: Record<(typeof TOOL_NAMES)[number], unknown[]> = {
  openwiki_status: [{}],
  openwiki_read: [{}, { paths: ["intro.md"], expectedWikiRevision: hash }],
  openwiki_begin: [{ wikiRoot: "D:\\personal-wiki", mode: "init" }],
  openwiki_submit_plan: [
    {
      confirmedByUser: true,
      runId: personalRunId,
      pages: [
        {
          path: "quickstart.md",
          title: "Wiki quickstart",
          purpose: "Route readers to the personal Wiki taxonomy.",
        },
      ],
    },
  ],
  openwiki_next_page: [{ runId: personalRunId }],
  openwiki_inspect_page_claims: [
    { runId: personalRunId, jobId: personalJobId },
  ],
  openwiki_submit_page: [{ runId: personalRunId, jobId: personalJobId }],
  openwiki_finish: [{ runId: personalRunId }],
  openwiki_setup: [
    {
      action: "start",
      executionMode: "legacy_provider",
      ...model,
      confirmation: "Use gpt-5.6-sol with xhigh",
    },
    {
      action: "complete",
      executionMode: "legacy_provider",
      setupAttemptId: "attempt-12345678",
    },
    {
      action: "complete",
      executionMode: "legacy_provider",
      setupAttemptId: "attempt-12345678",
      callback: "http://localhost:1455/callback?code=secret&state=bound",
    },
    {
      action: "cancel",
      executionMode: "legacy_provider",
      setupAttemptId: "attempt-12345678",
    },
  ],
  openwiki_prepare_sources: [{ paths: ["D:\\project\\README.md"] }],
  openwiki_list_skills: [{}],
  openwiki_query: [
    {
      executionMode: "legacy_provider",
      instruction: "Summarize the renderer.",
    },
    {
      executionMode: "legacy_provider",
      instruction: "Explain this subsystem.",
      materials: [{ id: "note", content: "bounded evidence" }],
      skills: ["kg-c7-cpp"],
      sourceManifestId: "manifest-12345678",
      sourceConfirmation: "confirm:sha256:abc",
      modelOverride: model,
    },
  ],
  openwiki_update: [
    {
      executionMode: "legacy_provider",
      instruction: "Update the renderer page.",
      confirmedByUser: true,
      expectedWikiRevision: hash,
    },
    {
      executionMode: "legacy_provider",
      instruction: "Update the two confirmed Wiki pages.",
      confirmedByUser: true,
      confirmedWikiPaths: ["quickstart.md", "sources/kgpr-source-set.md"],
      expectedWikiRevision: hash,
    },
  ],
  openwiki_begin_external_update: [
    {
      action: "start",
      requestId: "request-12345678",
      confirmedByUser: true,
      instruction: "Update the confirmed external-agent page.",
      confirmedWikiPaths: ["architecture/external-agent.md"],
      expectedWikiRevision: hash,
    },
    {
      action: "start",
      requestId: "request-12345678",
      confirmedByUser: true,
      instruction: "Update from confirmed materials and sources.",
      materials: [{ id: "note", content: "bounded evidence" }],
      skills: ["kg-c7-cpp"],
      sourceManifestId: "manifest-12345678",
      sourceConfirmation: "confirm:sha256:abc",
      confirmedWikiPaths: ["architecture/external-agent.md"],
      expectedWikiRevision: hash,
    },
    {
      action: "resume",
      transactionId: "tx-12345678",
      bindingHash: secondHash,
    },
  ],
  openwiki_finalize_external_update: [
    {
      action: "prepare_review",
      transactionId: "tx-12345678",
      bindingHash: secondHash,
      candidateReceipt,
    },
    {
      action: "submit_review",
      transactionId: "tx-12345678",
      bindingHash: secondHash,
      reviewReceipt,
    },
    {
      action: "report_host_failure",
      transactionId: "tx-12345678",
      bindingHash: secondHash,
      phase: "candidate_writer",
      code: "host_timeout",
      message: "The host writer timed out.",
      retryable: true,
    },
    {
      action: "report_host_failure",
      transactionId: "tx-12345678",
      bindingHash: secondHash,
      phase: "reviewer",
      code: "host_model_failure",
      message: "The host reviewer failed.",
      retryable: true,
      reviewPackageHash: hash,
    },
    {
      action: "abort",
      transactionId: "tx-12345678",
      bindingHash: secondHash,
      confirmedByUser: true,
    },
  ],
  openwiki_set_default_model: [
    {
      executionMode: "legacy_provider",
      ...model,
      confirmation: "Use gpt-5.6-sol with xhigh by default",
    },
  ],
};

const validOutputs: Record<(typeof TOOL_NAMES)[number], unknown> = {
  openwiki_read: {
    ok: true,
    status: "wiki_read",
    recovery,
    revision: hash,
    pages: [],
    knowledge: [],
  },
  openwiki_status: {
    ok: true,
    status: "status",
    version: {
      contractSchema: 2,
      mcpServer: "0.1.0",
      openWiki: "0.3.1",
    },
    executionMode: "external_agent",
    authRequired: false,
    initialized: true,
    authentication: { status: "not_required" },
    defaultModel: null,
    externalAgent: { ready: true, activeTransaction: null },
    legacyProvider: {
      available: true,
      authRequired: true,
      authentication: { status: "not_configured" },
      initialized: false,
      defaultModel: null,
      verifiedModels: [],
    },
    paths: {
      openWikiRoot: "D:\\openwikiC7",
      runtimeRoot: "D:\\openwikiC7\\c7-openwiki\\runtime",
      wikiRoot: "D:\\openwikiC7\\c7-openwiki\\runtime\\wiki",
    },
    visualizer: {
      id: "selfopenwiki.zxh_wiki_viewer",
      contractSchema: 1,
      launcherPath: "D:\\SelfOpenWiki\\Visualize.bat",
      loopbackOnly: true,
      autoOpen: false,
      wikiRootInput: { kind: "argument", flag: "--wiki-root" },
      urlTemplate: "http://127.0.0.1:{port}/wiki/local",
    },
    runtime: {
      locks: [],
      recoveryState: "clean",
    },
    capabilities: [],
    staticCapabilities: [],
    verifiedModels: [],
    wikiRevision: hash,
    recovery,
  },
  openwiki_begin: {
    ok: true,
    protocol: "selfopenwiki:personal-openwiki-v1",
    status: "planning",
    runId: personalRunId,
    wikiRoot: "D:\\personal-wiki",
    runtimeRoot: "D:\\personal-wiki.selfopenwiki",
    wikiRevision: hash,
    skillAggregateHash: hash,
    upstreamCommit: "a".repeat(40),
    binding: {
      wikiRoot: "D:\\personal-wiki",
      runtimeRoot: "D:\\personal-wiki.selfopenwiki",
      wikiRevision: hash,
      markdownWikiRevision: hash,
      skillAggregateHash: hash,
      upstreamCommit: "a".repeat(40),
    },
    recovery,
  },
  openwiki_submit_plan: {
    ok: true,
    protocol: "selfopenwiki:personal-openwiki-v1",
    status: "plan_accepted",
    runId: personalRunId,
    planHash: hash,
    queueHash: hash,
    pageCount: 1,
    binding: personalBinding,
    recovery,
  },
  openwiki_next_page: {
    ok: true,
    protocol: "selfopenwiki:personal-openwiki-v1",
    status: "page_pending",
    runId: personalRunId,
    jobId: personalJobId,
    path: "quickstart.md",
    title: "Wiki quickstart",
    purpose: "Route readers to the personal Wiki taxonomy.",
    seedPaths: [],
    relatedPages: [],
    issueClaims: [],
    candidate: personalCandidate,
    binding: personalBinding,
    recovery,
  },
  openwiki_inspect_page_claims: {
    ok: true,
    protocol: "selfopenwiki:personal-openwiki-v1",
    status: "claims_inspected",
    runId: personalRunId,
    jobId: personalJobId,
    claims: [],
    claimsHash: hash,
    binding: personalBinding,
    recovery,
  },
  openwiki_submit_page: {
    ok: true,
    protocol: "selfopenwiki:personal-openwiki-v1",
    status: "page_accepted",
    runId: personalRunId,
    jobId: personalJobId,
    remainingPages: 0,
    candidateBindingHash: hash,
    pageContentHash: hash,
    claimDecisionHash: hash,
    binding: personalBinding,
    recovery,
  },
  openwiki_finish: {
    ok: true,
    protocol: "selfopenwiki:personal-openwiki-v1",
    status: "complete",
    runId: personalRunId,
    transactionId: "tx-12345678",
    generation: 1,
    published: true,
    wikiRevision: hash,
    beforeWikiHash: hash,
    afterWikiHash: secondHash,
    reviewReceiptHash: secondHash,
    runReceiptHash: hash,
    binding: personalBinding,
    recovery,
  },
  openwiki_setup: {
    ok: true,
    status: "setup_pending",
    setupAttemptId: "attempt-12345678",
    authorizationUrl: "https://auth.openai.com/authorize?state=redacted",
    expiresAt: "2026-08-07T01:00:00.000Z",
    recovery: { action: "retry" },
  },
  openwiki_prepare_sources: {
    ok: true,
    status: "sources_prepared",
    sourceManifestId: "manifest-12345678",
    manifestHash: hash,
    sensitivePolicyVersion: 1,
    sensitivePolicyHash: hash,
    confirmation: "confirm:sha256:abc",
    files: [{ path: "D:\\project\\README.md", size: 10, hash, risks: [] }],
    recovery,
  },
  openwiki_list_skills: {
    ok: true,
    status: "skills_listed",
    skills: [
      {
        category: "base",
        id: "kg-c7-project-wiki",
        description: "Base project Wiki policy.",
        loadOrder: "base_always_first",
        packageHash: hash,
        title: "KG C7 Project Wiki",
        verified: true,
      },
    ],
    recovery,
  },
  openwiki_query: {
    ok: true,
    status: "answered",
    answer: "The renderer is documented.",
    model: modelEvidence,
    selectedSkills,
    skillAggregateHash: hash,
    wikiRevision: hash,
    recovery,
  },
  openwiki_update: {
    ok: true,
    status: "published",
    published: true,
    ...updateOutcomeMetadata,
    recovery,
  },
  openwiki_begin_external_update: {
    ok: true,
    status: "external_update_ready",
    executionMode: "external_agent",
    authRequired: false,
    workPackage,
    recovery,
  },
  openwiki_finalize_external_update: {
    ok: true,
    status: "external_review_ready",
    executionMode: "external_agent",
    authRequired: false,
    transactionId: "tx-12345678",
    generation: 1,
    bindingHash: secondHash,
    candidateRootHash: hash,
    candidateReceiptHash: secondHash,
    reviewPackageHash: hash,
    reviewPackage,
    recovery,
  },
  openwiki_set_default_model: {
    ok: true,
    status: "default_model_changed",
    model: modelEvidence,
    recovery,
  },
};

describe("strict MCP input contracts", () => {
  test("defines personal, safe read and legacy tools", () => {
    expect(TOOL_NAMES).toEqual([
      "openwiki_status",
      "openwiki_read",
      "openwiki_begin",
      "openwiki_submit_plan",
      "openwiki_next_page",
      "openwiki_inspect_page_claims",
      "openwiki_submit_page",
      "openwiki_finish",
      "openwiki_setup",
      "openwiki_prepare_sources",
      "openwiki_list_skills",
      "openwiki_query",
      "openwiki_update",
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
      "openwiki_set_default_model",
    ]);
    expect(Object.keys(toolInputSchemas).sort()).toEqual(
      [...TOOL_NAMES].sort(),
    );
    for (const name of TOOL_NAMES) {
      for (const input of validInputs[name]) {
        expect(toolInputSchemas[name].safeParse(input).success, name).toBe(
          true,
        );
      }
    }
  });

  test("rejects unknown fields for every tool", () => {
    for (const name of TOOL_NAMES) {
      const input = validInputs[name][0] as Record<string, unknown>;
      expect(
        toolInputSchemas[name].safeParse({ ...input, invented: true }).success,
        name,
      ).toBe(false);
    }
  });

  test("keeps setup actions disjoint", () => {
    const schema = toolInputSchemas.openwiki_setup;
    expect(
      schema.safeParse({
        action: "start",
        executionMode: "legacy_provider",
        ...model,
        confirmation: "confirmed",
        callback: "http://localhost/callback?code=x&state=y",
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        action: "complete",
        executionMode: "legacy_provider",
        setupAttemptId: "attempt-12345678",
        model: model.model,
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        action: "cancel",
        executionMode: "legacy_provider",
        setupAttemptId: "attempt-12345678",
        callback: "secret",
      }).success,
    ).toBe(false);
  });

  test("rejects unsupported effort, missing fields, and false confirmation", () => {
    expect(
      toolInputSchemas.openwiki_set_default_model.safeParse({
        executionMode: "legacy_provider",
        model: "gpt-5.6-sol",
        reasoningEffort: "extreme",
        confirmation: "confirmed",
      }).success,
    ).toBe(false);
    expect(toolInputSchemas.openwiki_query.safeParse({}).success).toBe(false);
    expect(
      toolInputSchemas.openwiki_update.safeParse({
        instruction: "write",
        confirmedByUser: false,
      }).success,
    ).toBe(false);
  });

  test("requires source manifest id and confirmation as one bound pair", () => {
    for (const schema of [
      toolInputSchemas.openwiki_query,
      toolInputSchemas.openwiki_update,
    ]) {
      const updateField =
        schema === toolInputSchemas.openwiki_update
          ? {
              executionMode: "legacy_provider",
              confirmedByUser: true,
              expectedWikiRevision: hash,
            }
          : { executionMode: "legacy_provider" };
      expect(
        schema.safeParse({
          instruction: "use sources",
          sourceManifestId: "manifest-12345678",
          ...updateField,
        }).success,
      ).toBe(false);
      expect(
        schema.safeParse({
          instruction: "use sources",
          sourceConfirmation: "confirm:sha256:abc",
          ...updateField,
        }).success,
      ).toBe(false);
    }
  });

  test.each([
    "openwiki_setup",
    "openwiki_query",
    "openwiki_update",
    "openwiki_set_default_model",
  ] as const)("requires the explicit legacy execution mode for %s", (name) => {
    const input = validInputs[name][0] as Record<string, unknown>;
    const { executionMode: _, ...missingMode } = input;
    expect(toolInputSchemas[name].safeParse(missingMode).success).toBe(false);
    expect(
      toolInputSchemas[name].safeParse({
        ...input,
        executionMode: "external_agent",
      }).success,
    ).toBe(false);
  });

  test("keeps external begin start and resume strict and disjoint", () => {
    const schema = toolInputSchemas.openwiki_begin_external_update;
    expect(
      schema.safeParse({
        action: "start",
        requestId: "request-12345678",
        confirmedByUser: true,
        instruction: "Update.",
        confirmedWikiPaths: ["architecture/external-agent.md"],
        expectedWikiRevision: hash,
        modelOverride: model,
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        action: "start",
        requestId: "request-12345678",
        confirmedByUser: true,
        instruction: "Update.",
        confirmedWikiPaths: ["architecture/external-agent.md"],
        expectedWikiRevision: hash,
        executionMode: "external_agent",
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        action: "resume",
        transactionId: "tx-12345678",
        bindingHash: secondHash,
        instruction: "must not be reconstructed",
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        action: "start",
        requestId: "short",
        confirmedByUser: true,
        instruction: "Update.",
        confirmedWikiPaths: ["architecture/external-agent.md"],
        expectedWikiRevision: hash,
      }).success,
    ).toBe(false);
  });

  test("preserves external request text and rejects padded identity fields", () => {
    const schema = toolInputSchemas.openwiki_begin_external_update;
    const start = validInputs.openwiki_begin_external_update[0] as Record<
      string,
      unknown
    >;
    const instruction = "  Update from exact evidence.\n";
    const content = "\tExact material content.  ";
    const sourceConfirmation = `confirm-source:manifest-12345678:${hash}`;
    const parsed = schema.parse({
      ...start,
      instruction,
      materials: [{ id: "material-1", source: "user-note", content }],
      sourceManifestId: "manifest-12345678",
      sourceConfirmation,
    });
    if (parsed.action !== "start") throw new Error("expected start input");

    expect(parsed.instruction).toBe(instruction);
    expect(parsed.materials).toEqual([
      { id: "material-1", source: "user-note", content },
    ]);
    expect(parsed.sourceConfirmation).toBe(sourceConfirmation);
    for (const invalid of [
      { instruction: " \t\n " },
      { materials: [{ id: " material-1", content }] },
      { materials: [{ id: "material-1", source: "user-note ", content }] },
      { sourceConfirmation: ` ${sourceConfirmation}` },
      { sourceConfirmation: `${sourceConfirmation} ` },
    ]) {
      expect(
        schema.safeParse({
          ...start,
          materials: [{ id: "material-1", content }],
          sourceManifestId: "manifest-12345678",
          sourceConfirmation,
          ...invalid,
        }).success,
      ).toBe(false);
    }
  });

  test("keeps legacy text and source parsing behavior unchanged", () => {
    const parsed = toolInputSchemas.openwiki_query.parse({
      executionMode: "legacy_provider",
      instruction: "  Explain the subsystem.  ",
      materials: [
        { id: " note ", source: " user-note ", content: "  evidence  " },
      ],
      sourceManifestId: "manifest-12345678",
      sourceConfirmation: " confirm:sha256:abc ",
    });

    expect(parsed).toMatchObject({
      instruction: "Explain the subsystem.",
      materials: [{ id: "note", source: "user-note", content: "evidence" }],
      sourceConfirmation: "confirm:sha256:abc",
    });
  });

  test("rejects lone surrogates from every external-only user string and accepts scalar pairs", () => {
    const schema = toolInputSchemas.openwiki_begin_external_update;
    const start = validInputs.openwiki_begin_external_update[0] as Record<
      string,
      unknown
    >;
    const sourceManifestId = "manifest-12345678";
    const sourceConfirmation = `confirm-source:${sourceManifestId}:${hash}`;
    const validPair = "🚀";
    const parsed = schema.parse({
      ...start,
      instruction: `  ${validPair} instruction  `,
      materials: [
        {
          id: `material-${validPair}`,
          source: `source-${validPair}`,
          content: `  ${validPair} content  `,
        },
      ],
      sourceManifestId,
      sourceConfirmation: `${sourceConfirmation}-${validPair}`,
    });
    expect(parsed).toMatchObject({
      instruction: `  ${validPair} instruction  `,
      materials: [
        {
          id: `material-${validPair}`,
          source: `source-${validPair}`,
          content: `  ${validPair} content  `,
        },
      ],
      sourceConfirmation: `${sourceConfirmation}-${validPair}`,
    });

    for (const surrogate of ["\ud800", "\udc00"]) {
      for (const invalid of [
        { instruction: `bad-${surrogate}` },
        { materials: [{ id: `material-${surrogate}`, content: "content" }] },
        {
          materials: [
            {
              id: "material-1",
              source: `source-${surrogate}`,
              content: "content",
            },
          ],
        },
        {
          materials: [{ id: "material-1", content: `content-${surrogate}` }],
        },
        { sourceConfirmation: `${sourceConfirmation}-${surrogate}` },
      ]) {
        expect(
          schema.safeParse({
            ...start,
            sourceManifestId,
            sourceConfirmation,
            ...invalid,
          }).success,
        ).toBe(false);
      }
    }
  });

  test("does not change legacy lone-surrogate parsing", () => {
    expect(
      toolInputSchemas.openwiki_query.safeParse({
        executionMode: "legacy_provider",
        instruction: "legacy-\ud800",
        materials: [
          {
            id: "legacy-id",
            source: "legacy-source",
            content: "legacy-\udc00",
          },
        ],
        sourceManifestId: "manifest-12345678",
        sourceConfirmation: "legacy-\ud800",
      }).success,
    ).toBe(true);
  });

  test("keeps finalize actions disjoint from begin resume", () => {
    expect(
      toolInputSchemas.openwiki_finalize_external_update.safeParse({
        action: "resume",
        transactionId: "tx-12345678",
        bindingHash: secondHash,
      }).success,
    ).toBe(false);
  });

  test("rejects begin action accessors and Proxies without executing them", () => {
    assertRejectedWithoutPropertyExecution(
      toolInputSchemas.openwiki_begin_external_update,
      validInputs.openwiki_begin_external_update[0] as Record<string, unknown>,
      "action",
    );
  });

  test("bounds object keys and array length before allocating descriptor tables", () => {
    const schema = toolInputSchemas.openwiki_begin_external_update;
    const valid = validInputs.openwiki_begin_external_update[0] as Record<
      string,
      unknown
    >;
    const objectAtLimit = Object.fromEntries(
      Array.from({ length: 1_024 }, (_, index) => [`key-${index}`, null]),
    );
    const objectOverLimit = Object.fromEntries(
      Array.from({ length: 1_025 }, (_, index) => [`key-${index}`, null]),
    );
    const arrayAtLimit = Array.from({ length: 2_048 }, () => null);
    const arrayOverLimit = new Array(2_049);
    const shortArrayWithTooManyNamedKeys: unknown[] = [];
    Object.assign(
      shortArrayWithTooManyNamedKeys,
      Object.fromEntries(
        Array.from({ length: 2_049 }, (_, index) => [`key-${index}`, null]),
      ),
    );
    expect(shortArrayWithTooManyNamedKeys).toHaveLength(0);
    expect(Reflect.ownKeys(shortArrayWithTooManyNamedKeys)).toHaveLength(2_050);
    const descriptorSpy = vi.spyOn(Object, "getOwnPropertyDescriptors");

    try {
      expect(schema.safeParse({ ...valid, probe: objectAtLimit }).success).toBe(
        false,
      );
      expect(
        descriptorSpy.mock.calls.some(([value]) => value === objectAtLimit),
      ).toBe(true);

      descriptorSpy.mockClear();
      expect(
        schema.safeParse({ ...valid, probe: objectOverLimit }).success,
      ).toBe(false);
      expect(
        descriptorSpy.mock.calls.some(([value]) => value === objectOverLimit),
      ).toBe(false);

      descriptorSpy.mockClear();
      expect(schema.safeParse({ ...valid, probe: arrayAtLimit }).success).toBe(
        false,
      );
      expect(
        descriptorSpy.mock.calls.some(([value]) => value === arrayAtLimit),
      ).toBe(true);

      descriptorSpy.mockClear();
      expect(
        schema.safeParse({ ...valid, probe: arrayOverLimit }).success,
      ).toBe(false);
      expect(
        descriptorSpy.mock.calls.some(([value]) => value === arrayOverLimit),
      ).toBe(false);

      descriptorSpy.mockClear();
      expect(
        schema.safeParse({ ...valid, probe: shortArrayWithTooManyNamedKeys })
          .success,
      ).toBe(false);
      expect(
        descriptorSpy.mock.calls.some(
          ([value]) => value === shortArrayWithTooManyNamedKeys,
        ),
      ).toBe(false);
    } finally {
      descriptorSpy.mockRestore();
    }
  });

  test("rejects finalize action accessors and Proxies without executing them", () => {
    assertRejectedWithoutPropertyExecution(
      toolInputSchemas.openwiki_finalize_external_update,
      validInputs.openwiki_finalize_external_update[0] as Record<
        string,
        unknown
      >,
      "action",
    );
  });

  test("rejects candidate receipt accessors and Proxies without executing them", () => {
    const prepare = validInputs.openwiki_finalize_external_update[0] as Record<
      string,
      unknown
    >;
    assertRejectedWithoutNestedPropertyExecution(
      toolInputSchemas.openwiki_finalize_external_update,
      prepare,
      "candidateReceipt",
      "type",
    );
  });

  test("rejects review receipt accessors and Proxies without executing them", () => {
    const submit = validInputs.openwiki_finalize_external_update[1] as Record<
      string,
      unknown
    >;
    assertRejectedWithoutNestedPropertyExecution(
      toolInputSchemas.openwiki_finalize_external_update,
      submit,
      "reviewReceipt",
      "type",
    );
  });

  test("requires a bound source pair and confirmed external Wiki scope", () => {
    const schema = toolInputSchemas.openwiki_begin_external_update;
    const start = validInputs.openwiki_begin_external_update[0] as Record<
      string,
      unknown
    >;
    expect(
      schema.safeParse({ ...start, confirmedWikiPaths: undefined }).success,
    ).toBe(false);
    expect(
      schema.safeParse({ ...start, sourceManifestId: "manifest-12345678" })
        .success,
    ).toBe(false);
    expect(
      schema.safeParse({ ...start, sourceConfirmation: "confirm:sha256:abc" })
        .success,
    ).toBe(false);
  });

  test("enforces candidate receipt classification relationships", () => {
    const schema = toolInputSchemas.openwiki_finalize_external_update;
    const prepare = validInputs.openwiki_finalize_external_update[0] as Record<
      string,
      unknown
    >;
    expect(
      schema.safeParse({
        ...prepare,
        candidateReceipt: {
          ...candidateReceipt,
          classification: "minor",
          questions: ["Why?"],
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...prepare,
        candidateReceipt: {
          ...candidateReceipt,
          classification: "provisional",
          issues: [],
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...prepare,
        candidateReceipt: {
          ...candidateReceipt,
          classification: "blocking",
          issues: [
            {
              code: "missing_owner",
              message: "The owner is unknown.",
              severity: "blocking",
            },
          ],
          questions: [],
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...prepare,
        candidateReceipt: {
          ...candidateReceipt,
          bindingHash: hash,
        },
      }).success,
    ).toBe(false);
  });

  test("enforces external review receipt verdict relationships", () => {
    const schema = toolInputSchemas.openwiki_finalize_external_update;
    const submit = validInputs.openwiki_finalize_external_update[1] as Record<
      string,
      unknown
    >;
    expect(
      schema.safeParse({
        ...submit,
        reviewReceipt: {
          ...reviewReceipt,
          verdict: "pass",
          issues: [
            {
              code: "unexpected",
              message: "Pass cannot carry issues.",
              severity: "minor",
            },
          ],
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...submit,
        reviewReceipt: {
          ...reviewReceipt,
          verdict: "follow_up",
          issues: [
            {
              code: "blocking_gap",
              message: "This cannot be a follow-up.",
              severity: "blocking",
            },
          ],
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...submit,
        reviewReceipt: {
          ...reviewReceipt,
          verdict: "changes_requested",
          issues: [],
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...submit,
        reviewReceipt: { ...reviewReceipt, bindingHash: hash },
      }).success,
    ).toBe(false);
  });

  test("binds reviewer host failures to the current review package", () => {
    const schema = toolInputSchemas.openwiki_finalize_external_update;
    const reviewerFailure = validInputs.openwiki_finalize_external_update[3] as
      | Record<string, unknown>
      | undefined;
    expect(reviewerFailure).toBeDefined();
    const { reviewPackageHash: _, ...withoutHash } = reviewerFailure!;
    expect(schema.safeParse(withoutHash).success).toBe(false);
    const writerFailure = validInputs.openwiki_finalize_external_update[2] as
      | Record<string, unknown>
      | undefined;
    expect(
      schema.safeParse({ ...writerFailure, reviewPackageHash: hash }).success,
    ).toBe(true);
  });

  test.each([
    [["D:\\wiki\\quickstart.md"], "absolute path"],
    [["sources\\kgpr-source-set.md"], "backslash"],
    [["sources/../quickstart.md"], "parent segment"],
    [["./quickstart.md"], "dot segment"],
    [["quickstart.markdown"], "non-Markdown extension"],
    [["quickstart.md", "quickstart.md"], "duplicate"],
    [["Quickstart.md", "quickstart.md"], "case collision"],
  ])("rejects malformed confirmed Wiki paths: %s (%s)", (paths) => {
    expect(
      toolInputSchemas.openwiki_update.safeParse({
        executionMode: "legacy_provider",
        instruction: "Update the confirmed Wiki pages.",
        confirmedByUser: true,
        confirmedWikiPaths: paths,
        expectedWikiRevision: hash,
      }).success,
    ).toBe(false);
  });
});

describe("strict MCP output contracts", () => {
  test("accepts one success result per tool and rejects unknown fields", () => {
    expect(Object.keys(toolOutputSchemas).sort()).toEqual(
      [...TOOL_NAMES].sort(),
    );
    for (const name of TOOL_NAMES) {
      const output = validOutputs[name] as Record<string, unknown>;
      expect(toolOutputSchemas[name].safeParse(output).success, name).toBe(
        true,
      );
      expect(
        toolOutputSchemas[name].safeParse({ ...output, invented: true })
          .success,
        name,
      ).toBe(false);
    }
  });

  test("keeps external status model-free and tied to local readiness", () => {
    const schema = toolOutputSchemas.openwiki_status;
    const status = validOutputs.openwiki_status as Record<string, unknown>;
    expect(
      schema.safeParse({
        ...status,
        externalAgent: { ready: false, activeTransaction: null },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...status,
        initialized: false,
        externalAgent: { ready: false, activeTransaction: null },
      }).success,
    ).toBe(true);
    expect(schema.safeParse({ ...status, defaultModel: model }).success).toBe(
      false,
    );
    expect(
      schema.safeParse({
        ...status,
        verifiedModels: [
          {
            ...model,
            providerAccepted: true,
            verifiedAt: "2026-08-07T00:00:00.000Z",
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...status,
        externalAgent: {
          ready: true,
          activeTransaction: {
            transactionId: "tx-12345678",
            generation: 1,
            state: "review_ready",
            nextAction: "retry_review",
          },
        },
      }).success,
    ).toBe(true);
  });

  test("accepts only the declared SelfOpenWiki Viewer contract", () => {
    const schema = toolOutputSchemas.openwiki_status;
    const status = validOutputs.openwiki_status as Record<string, unknown>;
    expect(schema.safeParse(status).success).toBe(true);
    for (const visualizer of [
      {
        ...(status.visualizer as Record<string, unknown>),
        id: "openwiki.legacy",
      },
      {
        ...(status.visualizer as Record<string, unknown>),
        loopbackOnly: false,
      },
      {
        ...(status.visualizer as Record<string, unknown>),
        urlTemplate: "http://0.0.0.0:{port}/wiki/local",
      },
      {
        ...(status.visualizer as Record<string, unknown>),
        wikiRootInput: { kind: "argument", flag: "--root" },
      },
      {
        ...(status.visualizer as Record<string, unknown>),
        invented: true,
      },
    ]) {
      expect(schema.safeParse({ ...status, visualizer }).success).toBe(false);
    }
  });

  test("accepts exact external begin outcomes and rejects model evidence", () => {
    const schema = toolOutputSchemas.openwiki_begin_external_update;
    const ready = validOutputs.openwiki_begin_external_update as Record<
      string,
      unknown
    >;
    expect(
      schema.safeParse({ ...ready, status: "external_update_resumed" }).success,
    ).toBe(true);
    expect(schema.safeParse({ ...ready, model: modelEvidence }).success).toBe(
      false,
    );
    expect(
      schema.safeParse({
        ...ready,
        workPackage: {
          ...workPackage,
          candidate: {
            ...workPackage.candidate,
            permissions: ["read", "list"],
          },
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...ready,
        workPackage: {
          ...workPackage,
          candidate: {
            ...workPackage.candidate,
            allowedChangedPaths: ["other.md"],
          },
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...ready,
        workPackage: {
          ...workPackage,
          sourceManifestHash: hash,
          sourceTreeHash: null,
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...ready,
        workPackage: {
          ...workPackage,
          sourceManifestHash: hash,
          sourceTreeHash: secondHash,
          sources: {
            rootPath:
              "D:\\openwikiC7\\runtime\\external-updates\\tx-12345678\\sources",
            permissions: ["read", "list"],
          },
        },
      }).success,
    ).toBe(true);
  });

  test("requires the base Skill first in external writer and review packages", () => {
    const begin = validOutputs.openwiki_begin_external_update as Record<
      string,
      unknown
    >;
    const schema = toolOutputSchemas.openwiki_begin_external_update;
    expect(
      schema.safeParse({
        ...begin,
        workPackage: {
          ...workPackage,
          rules: {
            ...workPackage.rules,
            skills: [...rules.skills].reverse(),
          },
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...begin,
        workPackage: {
          ...workPackage,
          rules: {
            ...workPackage.rules,
            skills: [
              {
                ...rules.skills[0],
                category: "specialized",
                loadOrder: "request_order",
              },
            ],
          },
        },
      }).success,
    ).toBe(false);
  });

  test("accepts every frozen external finalize success outcome", () => {
    const schema = toolOutputSchemas.openwiki_finalize_external_update;
    const reviewReady =
      validOutputs.openwiki_finalize_external_update as Record<string, unknown>;
    expect(
      schema.safeParse({
        ...reviewReady,
        status: "external_review_resumed",
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...externalOutcomeCommon,
        status: "published",
        published: true,
        wikiRevision: hash,
        candidateRootHash: hash,
        reviewReceiptHash: secondHash,
        reviewEvidence: "host_attested",
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ...externalOutcomeCommon,
        status: "published_with_follow_up",
        published: true,
        wikiRevision: hash,
        candidateRootHash: hash,
        reviewReceiptHash: secondHash,
        reviewEvidence: "host_attested",
        followUp: [
          {
            code: "source_label",
            message: "Add a source label later.",
            severity: "provisional",
          },
        ],
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ...externalOutcomeCommon,
        status: "repair_ready",
        published: false,
        nextAction: "resume_candidate",
        reviewReceiptHash: secondHash,
        issues: [
          {
            code: "fix_link",
            message: "Fix the local link.",
            severity: "minor",
          },
        ],
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ...externalOutcomeCommon,
        status: "needs_clarification",
        published: false,
        candidateRetained: true,
        nextAction: "clarify",
        questions: ["Which subsystem owns this claim?"],
        issues: [],
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ...externalOutcomeCommon,
        status: "external_host_failure",
        candidateRetained: true,
        nextAction: "retry_review",
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ...externalOutcomeCommon,
        status: "external_update_aborted",
        published: false,
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({ ...reviewReady, provider: "openai" }).success,
    ).toBe(false);
  });

  test("lets begin resume replay the persisted state but not a fresh Review-ready result", () => {
    const begin = toolOutputSchemas.openwiki_begin_external_update;
    const reviewReady =
      validOutputs.openwiki_finalize_external_update as Record<string, unknown>;
    expect(
      begin.safeParse({
        ...reviewReady,
        status: "external_review_resumed",
      }).success,
    ).toBe(true);
    expect(begin.safeParse(reviewReady).success).toBe(false);
    for (const terminal of [
      {
        ...externalOutcomeCommon,
        status: "published",
        published: true,
        wikiRevision: hash,
        candidateRootHash: hash,
        reviewReceiptHash: secondHash,
        reviewEvidence: "host_attested",
      },
      {
        ...externalOutcomeCommon,
        status: "published_with_follow_up",
        published: true,
        wikiRevision: hash,
        candidateRootHash: hash,
        reviewReceiptHash: secondHash,
        reviewEvidence: "host_attested",
        followUp: [
          {
            code: "source_label",
            message: "Add a source label later.",
            severity: "provisional",
          },
        ],
      },
      {
        ...externalOutcomeCommon,
        status: "needs_clarification",
        published: false,
        candidateRetained: true,
        nextAction: "clarify",
        questions: ["Which subsystem owns this claim?"],
        issues: [],
      },
      {
        ...externalOutcomeCommon,
        status: "external_update_aborted",
        published: false,
      },
    ]) {
      expect(begin.safeParse(terminal).success, terminal.status).toBe(true);
    }
    expect(
      begin.safeParse({
        ...externalOutcomeCommon,
        status: "external_host_failure",
        candidateRetained: true,
        nextAction: "retry_review",
      }).success,
    ).toBe(false);
  });

  test.each([
    "confirmation_required",
    "setup_required",
    "auth_required",
    "provider_failure",
    "model_rejected",
    "process_failure",
    "platform_unsupported",
  ])("keeps legacy/provider error %s out of external tools", (code) => {
    const failure = {
      ok: false,
      error: {
        code,
        message: "This legacy failure must not cross the external protocol.",
        retryable: false,
      },
      recovery: { action: "none" },
    };
    expect(
      toolOutputSchemas.openwiki_begin_external_update.safeParse(failure)
        .success,
    ).toBe(false);
    expect(
      toolOutputSchemas.openwiki_finalize_external_update.safeParse(failure)
        .success,
    ).toBe(false);
  });

  test("uses an external-only error and recovery contract", () => {
    const externalCodes = [
      "invalid_input",
      "busy",
      "capability_unverified",
      "internal_error",
      "transaction_state_invalid",
      "source_rejected",
      "source_manifest_invalid",
      "source_changed",
      "skill_untrusted",
      "validation_failed",
      "restore_required",
      "wiki_conflict",
    ];
    for (const schema of [
      toolOutputSchemas.openwiki_begin_external_update,
      toolOutputSchemas.openwiki_finalize_external_update,
    ]) {
      for (const code of externalCodes) {
        expect(
          schema.safeParse({
            ok: false,
            error: {
              code,
              details: {
                diagnostic: "bounded diagnostic",
                limit: 3,
                lock: "operation",
                paths: ["architecture/external-agent.md"],
                retryAfterMs: 50,
              },
              message: "The external transaction failed closed.",
              retryable: false,
            },
            recovery: { action: "restore" },
          }).success,
          code,
        ).toBe(true);
      }
      const failure = {
        ok: false,
        error: {
          code: "transaction_state_invalid",
          message: "The persisted external state does not match this request.",
          retryable: false,
        },
        recovery: { action: "restore" },
      };
      for (const forbiddenDetails of [
        { providerStatusClass: "5xx" },
        { attemptExpiresAt: "2026-08-12T00:00:00.000Z" },
        { failureStage: "result_schema_invalid" },
      ]) {
        expect(
          schema.safeParse({
            ...failure,
            error: { ...failure.error, details: forbiddenDetails },
          }).success,
        ).toBe(false);
      }
      for (const forbiddenAction of [
        "run_setup",
        "reauthorize",
        "confirm_update",
      ]) {
        expect(
          schema.safeParse({
            ...failure,
            recovery: { action: forbiddenAction },
          }).success,
        ).toBe(false);
      }
      for (const action of [
        "none",
        "retry",
        "clarify",
        "resolve_attention",
        "restore",
      ]) {
        expect(
          schema.safeParse({ ...failure, recovery: { action } }).success,
        ).toBe(true);
      }
    }
    const ready = validOutputs.openwiki_begin_external_update as Record<
      string,
      unknown
    >;
    expect(
      toolOutputSchemas.openwiki_begin_external_update.safeParse({
        ...ready,
        recovery: { action: "reauthorize" },
      }).success,
    ).toBe(false);
  });

  test("does not call a successful model result accepted when the provider was not", () => {
    for (const name of [
      "openwiki_setup",
      "openwiki_query",
      "openwiki_set_default_model",
    ] as const) {
      const output = structuredClone(validOutputs[name]) as Record<
        string,
        unknown
      >;
      if (name === "openwiki_setup") {
        Object.assign(output, {
          status: "setup_completed",
          model: { ...modelEvidence, providerAccepted: false },
        });
        delete output.setupAttemptId;
        delete output.authorizationUrl;
        delete output.expiresAt;
      } else {
        output.model = { ...modelEvidence, providerAccepted: false };
      }
      expect(toolOutputSchemas[name].safeParse(output).success, name).toBe(
        false,
      );
    }
    const status = structuredClone(validOutputs.openwiki_status) as Record<
      string,
      unknown
    >;
    status.verifiedModels = [
      {
        ...model,
        providerAccepted: false,
        verifiedAt: "2026-08-07T00:00:00.000Z",
      },
    ];
    expect(toolOutputSchemas.openwiki_status.safeParse(status).success).toBe(
      false,
    );
  });

  test("rejects model or effort fallback in successful results", () => {
    const fallback = {
      ...modelEvidence,
      sent: { model: "gpt-5.6-terra", reasoningEffort: "high" },
    };
    for (const name of [
      "openwiki_setup",
      "openwiki_query",
      "openwiki_set_default_model",
    ] as const) {
      const output = structuredClone(validOutputs[name]) as Record<
        string,
        unknown
      >;
      if (name === "openwiki_setup") {
        Object.assign(output, { status: "setup_completed", model: fallback });
        delete output.setupAttemptId;
        delete output.authorizationUrl;
        delete output.expiresAt;
      } else {
        output.model = fallback;
      }
      expect(toolOutputSchemas[name].safeParse(output).success, name).toBe(
        false,
      );
    }
  });

  test("allows structured provider failure inside setup verification_failed", () => {
    expect(
      toolOutputSchemas.openwiki_setup.safeParse({
        ok: true,
        status: "verification_failed",
        setupAttemptId: "attempt-12345678",
        failure: {
          code: "provider_failure",
          message: "Provider could not verify this model.",
          retryable: true,
        },
        recovery: { action: "retry" },
      }).success,
    ).toBe(true);
  });

  test("keeps initialized status, paths, and Skill ordering internally consistent", () => {
    const status = structuredClone(validOutputs.openwiki_status) as Record<
      string,
      unknown
    >;
    expect(
      toolOutputSchemas.openwiki_status.safeParse({
        ...status,
        initialized: false,
        defaultModel: null,
      }).success,
    ).toBe(false);
    expect(
      toolOutputSchemas.openwiki_status.safeParse({
        ...status,
        paths: {
          openWikiRoot: "relative",
          runtimeRoot: "relative",
          wikiRoot: "relative",
        },
      }).success,
    ).toBe(false);

    const listed = structuredClone(validOutputs.openwiki_list_skills) as Record<
      string,
      unknown
    >;
    const [base] = listed.skills as Array<Record<string, unknown>>;
    base.loadOrder = "request_order";
    expect(
      toolOutputSchemas.openwiki_list_skills.safeParse(listed).success,
    ).toBe(false);
  });

  test("accepts a whitelisted common error and rejects exception-shaped extras", () => {
    const error = {
      ok: false,
      error: {
        code: "setup_required",
        message: "Run setup first.",
        retryable: true,
      },
      recovery: { action: "run_setup" },
    };
    expect(toolOutputSchemas.openwiki_query.safeParse(error).success).toBe(
      true,
    );
    expect(
      toolOutputSchemas.openwiki_query.safeParse({
        ...error,
        stack: "must not cross the protocol",
      }).success,
    ).toBe(false);
  });

  test("enforces update preflight versus six transaction terminal states", () => {
    const schema = toolOutputSchemas.openwiki_update;
    const published = validOutputs.openwiki_update as Record<string, unknown>;
    expect(
      schema.safeParse({
        ok: false,
        error: {
          code: "confirmation_required",
          message: "Confirm first.",
          retryable: true,
        },
        recovery: { action: "confirm_update" },
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ...published,
        status: "published_with_follow_up",
        review: { rounds: 1, status: "follow_up" },
        followUp: [
          {
            code: "blocking_gap",
            message: "This must not be published.",
            severity: "blocking",
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...published,
        model: {
          ...modelEvidence,
          sent: { model: "gpt-5.6-terra", reasoningEffort: "high" },
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ok: true,
        status: "failed",
        published: false,
        ...updateOutcomeMetadata,
        model: {
          providerAccepted: false,
          requested: model,
          sent: null,
        },
        review: { rounds: 0, status: "not_run" },
        validation: {
          passed: false,
          checks: [{ id: "process", status: "failed" }],
        },
        failure: {
          code: "process_failure",
          message: "OpenWiki process failed.",
          retryable: true,
        },
        recovery: { action: "retry" },
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ok: true,
        status: "failed",
        published: true,
        ...updateOutcomeMetadata,
        recovery: { action: "none" },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ok: true,
        status: "failed",
        published: false,
        ...updateOutcomeMetadata,
        failure: {
          code: "confirmation_required",
          message: "This code is preflight-only.",
          retryable: true,
        },
        recovery: { action: "confirm_update" },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ok: false,
        status: "needs_clarification",
        published: false,
        error: {
          code: "invalid_input",
          message: "bad",
          retryable: false,
        },
        recovery: { action: "clarify" },
      }).success,
    ).toBe(false);

    expect(schema.safeParse(published).success).toBe(true);
    expect(
      schema.safeParse({
        ok: true,
        status: "conflict",
        published: false,
        ...updateOutcomeMetadata,
        baseWikiRevision: `sha256:${"b".repeat(64)}`,
        model: {
          providerAccepted: false,
          requested: model,
          sent: null,
        },
        review: { rounds: 0, status: "not_run" },
        validation: {
          passed: false,
          checks: [{ id: "wiki_revision", status: "failed" }],
        },
        failure: {
          code: "wiki_conflict",
          message: "The formal Wiki changed after confirmation.",
          retryable: true,
        },
        recovery: { action: "retry" },
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ...published,
        status: "published_with_follow_up",
        review: { rounds: 1, status: "follow_up" },
        followUp: [
          {
            code: "needs_source_label",
            message: "Add a source label.",
            severity: "provisional",
          },
        ],
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ok: true,
        status: "needs_clarification",
        published: false,
        ...updateOutcomeMetadata,
        questions: ["Which subsystem owns this API?"],
        review: { rounds: 0, status: "not_run" },
        validation: {
          passed: false,
          checks: [{ id: "blocking_information", status: "failed" }],
        },
        recovery: { action: "clarify" },
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ok: true,
        status: "review_requires_attention",
        published: true,
        baseWikiRevision: hash,
        changes: [],
        model: modelEvidence,
        questions: [],
        recoveryState: "attention",
        review: { rounds: 1, status: "requires_attention" },
        selectedSkills,
        skillAggregateHash: hash,
        validation: {
          passed: true,
          checks: [{ id: "wiki_tree", status: "passed" }],
        },
        issues: [
          {
            code: "scope_ambiguous",
            message: "The ownership statement needs user review.",
            severity: "blocking",
          },
        ],
        recovery: { action: "resolve_attention" },
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ok: true,
        status: "review_requires_attention",
        published: true,
        ...updateOutcomeMetadata,
        issues: [],
        failure: {
          code: "process_failure",
          message: "The review process failed after publish.",
          retryable: true,
        },
        review: { rounds: 0, status: "technical_failure" },
        recoveryState: "review_pending",
        recovery: { action: "resolve_attention" },
      }).success,
    ).toBe(true);
    expect(
      schema.safeParse({
        ...published,
        validation: {
          passed: true,
          checks: [{ id: "wiki_tree", status: "failed" }],
        },
      }).success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...published,
        review: { rounds: 0, status: "not_run" },
      }).success,
    ).toBe(false);
  });

  test("keeps validation_failed out of update preflight errors", () => {
    expect(
      toolOutputSchemas.openwiki_update.safeParse({
        ok: false,
        error: {
          code: "validation_failed",
          message: "Transaction validation failed.",
          retryable: false,
        },
        recovery: { action: "retry" },
      }).success,
    ).toBe(false);
  });
});

describe("MCP annotations", () => {
  test("matches the reviewed side-effect table including safe reads", () => {
    expect(toolAnnotations).toEqual({
      openwiki_read: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_status: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_begin: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_submit_plan: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_next_page: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_inspect_page_claims: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_submit_page: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_finish: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_setup: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: true,
      },
      openwiki_prepare_sources: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
      },
      openwiki_list_skills: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_query: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: true,
      },
      openwiki_update: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: true,
      },
      openwiki_begin_external_update: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_finalize_external_update: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: true,
        openWorldHint: false,
      },
      openwiki_set_default_model: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: true,
      },
    });
  });
});

function assertRejectedWithoutPropertyExecution(
  schema: { safeParse(value: unknown): { success: boolean } },
  valid: Record<string, unknown>,
  property: string,
) {
  let executions = 0;
  const accessor = { ...valid };
  Object.defineProperty(accessor, property, {
    enumerable: true,
    get() {
      executions += 1;
      return valid[property];
    },
  });
  expect(schema.safeParse(accessor).success).toBe(false);
  expect(executions).toBe(0);

  let traps = 0;
  const proxy = new Proxy(
    { ...valid },
    {
      get(target, key, receiver) {
        traps += 1;
        return Reflect.get(target, key, receiver);
      },
      getOwnPropertyDescriptor(target, key) {
        traps += 1;
        return Reflect.getOwnPropertyDescriptor(target, key);
      },
      getPrototypeOf(target) {
        traps += 1;
        return Reflect.getPrototypeOf(target);
      },
      ownKeys(target) {
        traps += 1;
        return Reflect.ownKeys(target);
      },
    },
  );
  expect(schema.safeParse(proxy).success).toBe(false);
  expect(traps).toBe(0);
}

function assertRejectedWithoutNestedPropertyExecution(
  schema: { safeParse(value: unknown): { success: boolean } },
  valid: Record<string, unknown>,
  nestedProperty: string,
  observedProperty: string,
) {
  const nested = valid[nestedProperty] as Record<string, unknown>;
  let executions = 0;
  const accessor = { ...nested };
  Object.defineProperty(accessor, observedProperty, {
    enumerable: true,
    get() {
      executions += 1;
      return nested[observedProperty];
    },
  });
  expect(
    schema.safeParse({ ...valid, [nestedProperty]: accessor }).success,
  ).toBe(false);
  expect(executions).toBe(0);

  let traps = 0;
  const proxy = new Proxy(
    { ...nested },
    {
      get(target, key, receiver) {
        traps += 1;
        return Reflect.get(target, key, receiver);
      },
      getOwnPropertyDescriptor(target, key) {
        traps += 1;
        return Reflect.getOwnPropertyDescriptor(target, key);
      },
      getPrototypeOf(target) {
        traps += 1;
        return Reflect.getPrototypeOf(target);
      },
      ownKeys(target) {
        traps += 1;
        return Reflect.ownKeys(target);
      },
    },
  );
  expect(schema.safeParse({ ...valid, [nestedProperty]: proxy }).success).toBe(
    false,
  );
  expect(traps).toBe(0);
}
