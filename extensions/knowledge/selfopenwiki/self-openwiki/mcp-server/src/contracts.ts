import { z } from "zod";
import path from "node:path";
import { types as utilTypes } from "node:util";

export const TOOL_NAMES = [
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
] as const;

export type ToolName = (typeof TOOL_NAMES)[number];

export const reasoningEffortSchema = z.enum([
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
  "ultra",
]);

const modelNameSchema = z
  .string()
  .min(1)
  .max(128)
  .regex(/^[a-z0-9][a-z0-9._-]*$/u);
const nonEmptyTextSchema = z.string().trim().min(1).max(1_000_000);
const boundedIdSchema = z
  .string()
  .min(8)
  .max(160)
  .regex(/^[A-Za-z0-9][A-Za-z0-9._:-]*$/u);
const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const timestampSchema = z.string().datetime({ offset: true });
const generationSchema = z.number().int().min(1).max(3);
const absolutePathSchema = z
  .string()
  .min(1)
  .max(32_768)
  .refine((value) => path.isAbsolute(value), "path must be absolute");

const MAX_SAFE_INPUT_DEPTH = 8;
const MAX_SAFE_INPUT_NODES = 4_096;
const MAX_SAFE_ARRAY_LENGTH = 2_048;
const MAX_SAFE_OBJECT_KEYS = 1_024;

function withSafePlainInput<T extends z.ZodType>(schema: T) {
  return z.preprocess((value, context) => {
    if (!isSafePlainInput(value)) {
      context.addIssue({
        code: "custom",
        message: "external tool input must be bounded plain JSON data",
      });
      return z.NEVER;
    }
    return value;
  }, schema);
}

function isSafePlainInput(root: unknown): boolean {
  const pending: Array<{ depth: number; value: unknown }> = [
    { depth: 0, value: root },
  ];
  const seen = new WeakSet<object>();
  let visitedNodes = 0;

  while (pending.length > 0) {
    const current = pending.pop()!;
    visitedNodes += 1;
    if (
      current.depth > MAX_SAFE_INPUT_DEPTH ||
      visitedNodes > MAX_SAFE_INPUT_NODES
    ) {
      return false;
    }

    const value = current.value;
    if (
      value === null ||
      value === undefined ||
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      continue;
    }
    if (typeof value !== "object") return false;

    // This must precede every reflective operation because a Proxy can attach
    // executable traps to prototype, key, descriptor, and property reads.
    if (utilTypes.isProxy(value)) return false;
    if (seen.has(value)) return false;
    seen.add(value);

    const isArray = Array.isArray(value);
    const prototype = Object.getPrototypeOf(value);
    if (
      (isArray && prototype !== Array.prototype) ||
      (!isArray && prototype !== Object.prototype && prototype !== null)
    ) {
      return false;
    }

    const ownKeys = Reflect.ownKeys(value);
    if (ownKeys.some((key) => typeof key === "symbol")) return false;
    if (isArray) {
      if (
        (value as unknown[]).length > MAX_SAFE_ARRAY_LENGTH ||
        ownKeys.length > MAX_SAFE_ARRAY_LENGTH + 1
      ) {
        return false;
      }
    } else if (ownKeys.length > MAX_SAFE_OBJECT_KEYS) {
      return false;
    }
    const descriptors = Object.getOwnPropertyDescriptors(value);

    if (isArray) {
      const lengthDescriptor = descriptors.length;
      if (
        lengthDescriptor === undefined ||
        !("value" in lengthDescriptor) ||
        lengthDescriptor.get !== undefined ||
        lengthDescriptor.set !== undefined ||
        !Number.isSafeInteger(lengthDescriptor.value) ||
        lengthDescriptor.value < 0 ||
        lengthDescriptor.value > MAX_SAFE_ARRAY_LENGTH ||
        ownKeys.length !== lengthDescriptor.value + 1
      ) {
        return false;
      }
      for (let index = 0; index < lengthDescriptor.value; index += 1) {
        const descriptor = descriptors[String(index)];
        if (
          descriptor === undefined ||
          !("value" in descriptor) ||
          descriptor.get !== undefined ||
          descriptor.set !== undefined ||
          descriptor.enumerable !== true
        ) {
          return false;
        }
        pending.push({
          depth: current.depth + 1,
          value: descriptor.value,
        });
      }
      continue;
    }

    for (const key of ownKeys as string[]) {
      const descriptor = descriptors[key];
      if (
        descriptor === undefined ||
        !("value" in descriptor) ||
        descriptor.get !== undefined ||
        descriptor.set !== undefined ||
        descriptor.enumerable !== true
      ) {
        return false;
      }
      pending.push({
        depth: current.depth + 1,
        value: descriptor.value,
      });
    }
  }

  return true;
}

const confirmedWikiPathSchema = z
  .string()
  .min(1)
  .max(32_768)
  .superRefine((value, context) => {
    const segments = value.split("/");
    if (
      value.trim() !== value ||
      value.includes("\\") ||
      path.posix.isAbsolute(value) ||
      path.win32.isAbsolute(value) ||
      path.posix.normalize(value) !== value ||
      segments.some((segment) => segment === "." || segment === "..") ||
      !/\.md$/iu.test(value)
    ) {
      context.addIssue({
        code: "custom",
        message:
          "confirmed Wiki paths must be normalized relative Markdown paths",
      });
    }
  });

export const confirmedWikiPathsSchema = z
  .array(confirmedWikiPathSchema)
  .min(1)
  .max(500)
  .superRefine((paths, context) => {
    const normalized = new Set<string>();
    for (const wikiPath of paths) {
      const caseFolded = wikiPath.toLocaleLowerCase("en-US");
      if (normalized.has(caseFolded)) {
        context.addIssue({
          code: "custom",
          message:
            "confirmed Wiki paths must be unique without case collisions",
        });
        return;
      }
      normalized.add(caseFolded);
    }
  });

export const modelSelectionSchema = z.strictObject({
  model: modelNameSchema,
  reasoningEffort: reasoningEffortSchema,
});

const reviewIssueSchema = z.strictObject({
  code: z.string().regex(/^[a-z][a-z0-9_]{0,127}$/u),
  message: z.string().trim().min(1).max(4_096),
  page: z.string().min(1).max(32_768).optional(),
  severity: z.enum(["minor", "provisional", "blocking"]),
});

export const resultFailureStageSchema = z.enum([
  "result_missing",
  "result_json_invalid",
  "result_schema_invalid",
  "result_binding_mismatch",
]);
export type ResultFailureStage = z.infer<typeof resultFailureStageSchema>;

const materialSchema = z.strictObject({
  content: nonEmptyTextSchema,
  id: z.string().trim().min(1).max(128),
  source: z.string().trim().min(1).max(1_024).optional(),
});

const externalPreservingTextSchema = z
  .string()
  .max(1_000_000)
  .refine(
    isUnicodeScalarSequence,
    "text must contain valid Unicode scalar values",
  )
  .refine((value) => value.trim().length > 0, "text must not be blank");
const externalAlreadyTrimmedTextSchema = (maximum: number) =>
  z
    .string()
    .min(1)
    .max(maximum)
    .refine(
      isUnicodeScalarSequence,
      "text must contain valid Unicode scalar values",
    )
    .refine((value) => value === value.trim(), "text must already be trimmed");

function isUnicodeScalarSequence(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const nextCodeUnit = value.charCodeAt(index + 1);
      if (!(nextCodeUnit >= 0xdc00 && nextCodeUnit <= 0xdfff)) {
        return false;
      }
      index += 1;
      continue;
    }
    if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return false;
    }
  }
  return true;
}

const externalMaterialSchema = z.strictObject({
  content: externalPreservingTextSchema,
  id: externalAlreadyTrimmedTextSchema(128),
  source: externalAlreadyTrimmedTextSchema(1_024).optional(),
});

const uniqueSkillsSchema = z
  .array(z.string().regex(/^[a-z][a-z0-9-]{0,127}$/u))
  .max(32)
  .superRefine((skills, context) => {
    if (new Set(skills).size !== skills.length) {
      context.addIssue({
        code: "custom",
        message: "skills must not contain duplicates",
      });
    }
  });

const sourceBindingFields = {
  sourceConfirmation: z.string().trim().min(1).max(512).optional(),
  sourceManifestId: boundedIdSchema.optional(),
};

const externalSourceBindingFields = {
  sourceConfirmation: externalAlreadyTrimmedTextSchema(512).optional(),
  sourceManifestId: boundedIdSchema.optional(),
};

const queryFields = {
  executionMode: z.literal("legacy_provider"),
  instruction: nonEmptyTextSchema,
  materials: z.array(materialSchema).max(64).optional(),
  modelOverride: modelSelectionSchema.optional(),
  skills: uniqueSkillsSchema.optional(),
  ...sourceBindingFields,
};

const statusInputSchema = z.strictObject({});
const setupInputSchema = z.discriminatedUnion("action", [
  z.strictObject({
    action: z.literal("start"),
    executionMode: z.literal("legacy_provider"),
    confirmation: z.string().trim().min(1).max(512),
    model: modelNameSchema,
    reasoningEffort: reasoningEffortSchema,
  }),
  z.strictObject({
    action: z.literal("complete"),
    executionMode: z.literal("legacy_provider"),
    callback: z.string().trim().min(1).max(8_192).optional(),
    setupAttemptId: boundedIdSchema,
  }),
  z.strictObject({
    action: z.literal("cancel"),
    executionMode: z.literal("legacy_provider"),
    setupAttemptId: boundedIdSchema,
  }),
]);
const prepareSourcesInputSchema = z.strictObject({
  paths: z.array(z.string().trim().min(1).max(32_768)).min(1).max(1_024),
});
const listSkillsInputSchema = z.strictObject({});
function withBoundSourceFields<T extends z.ZodRawShape>(shape: T) {
  return z.strictObject(shape).superRefine((value, context) => {
    const sourceFields = value as {
      sourceConfirmation?: unknown;
      sourceManifestId?: unknown;
    };
    const hasManifest = sourceFields.sourceManifestId !== undefined;
    const hasConfirmation = sourceFields.sourceConfirmation !== undefined;
    if (hasManifest !== hasConfirmation) {
      context.addIssue({
        code: "custom",
        message:
          "sourceManifestId and sourceConfirmation must be provided together",
      });
    }
  });
}

const personalPagePathSchema = z
  .string()
  .min(1)
  .max(1_024)
  .superRefine((value, context) => {
    const segments = value.split("/");
    if (
      value.trim() !== value ||
      value.includes("\\") ||
      path.posix.isAbsolute(value) ||
      path.win32.isAbsolute(value) ||
      path.posix.normalize(value) !== value ||
      segments.some(
        (segment) => segment === "" || segment === "." || segment === "..",
      ) ||
      segments.some(isUnsafeWindowsPathSegment) ||
      !value.toLowerCase().endsWith(".md")
    ) {
      context.addIssue({
        code: "custom",
        message:
          "personal page paths must be normalized relative Markdown paths",
      });
    }
  });

function isUnsafeWindowsPathSegment(segment: string): boolean {
  if (
    [...segment].some(
      (character) =>
        character.charCodeAt(0) < 0x20 ||
        character.charCodeAt(0) === 0x7f ||
        '<>:"/\\|?*'.includes(character),
    )
  ) {
    return true;
  }
  if (/[. ]$/u.test(segment)) return true;
  const stem = segment.split(".", 1)[0]!.toUpperCase();
  return /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/u.test(stem);
}

const personalClaimSchema = z.strictObject({
  id: boundedIdSchema.optional(),
  statement: z.string().trim().min(1).max(4_096),
  evidence: z
    .array(
      z.strictObject({
        resource: z
          .string()
          .trim()
          .min(1)
          .max(1_024)
          .regex(
            /^(?:repo|wiki):\/\/[A-Za-z0-9._~:/#?\[\]@!$&'()*+,;=%-]+$/u,
            "claim evidence resources must use repo:// or wiki://",
          ),
      }),
    )
    .min(1)
    .max(64),
});

const personalPagePlanSchema = z.strictObject({
  path: personalPagePathSchema,
  title: z.string().trim().min(1).max(512),
  purpose: z.string().trim().min(1).max(4_096),
  issueClaims: z.array(personalClaimSchema).max(256).optional(),
  seedPaths: z.array(z.string().trim().min(1).max(1_024)).max(128).optional(),
  relatedPages: z.array(personalPagePathSchema).max(64).optional(),
  instructions: z.array(z.string().trim().min(1).max(8_192)).max(64).optional(),
});

const personalBeginInputSchema = withSafePlainInput(
  withBoundSourceFields({
    wikiRoot: absolutePathSchema,
    mode: z.enum(["init", "update"]),
    language: z.string().trim().min(1).max(32).optional(),
    force: z.boolean().optional(),
    skills: uniqueSkillsSchema.optional(),
    ...sourceBindingFields,
  }),
);
const personalSubmitPlanInputSchema = withSafePlainInput(
  z
    .strictObject({
      confirmedByUser: z.literal(true),
      runId: z.string().uuid(),
      pages: z.array(personalPagePlanSchema).max(2_048),
      deletePages: z.array(personalPagePathSchema).max(2_048).optional(),
    })
    .superRefine((value, context) => {
      if (value.pages.length === 0 && (value.deletePages?.length ?? 0) === 0) {
        context.addIssue({
          code: "custom",
          message: "A personal Wiki plan must contain a page or deletion.",
        });
      }
    }),
);
const personalRunInputSchema = withSafePlainInput(
  z.strictObject({ runId: z.string().uuid() }),
);
const personalInspectPageClaimsInputSchema = withSafePlainInput(
  z.strictObject({ runId: z.string().uuid(), jobId: z.string().uuid() }),
);
const personalSubmitPageInputSchema = withSafePlainInput(
  z.strictObject({
    runId: z.string().uuid(),
    jobId: z.string().uuid(),
    confirmedClaimIds: z.array(boundedIdSchema).max(256).optional(),
    claims: z.array(personalClaimSchema).max(256).optional(),
    retractedClaimIds: z.array(boundedIdSchema).max(256).optional(),
  }),
);
const queryInputSchema = withBoundSourceFields(queryFields);
const updateInputSchema = withBoundSourceFields({
  ...queryFields,
  confirmedByUser: z.literal(true),
  confirmedWikiPaths: confirmedWikiPathsSchema.optional(),
  expectedWikiRevision: hashSchema,
});
const setDefaultModelInputSchema = z.strictObject({
  executionMode: z.literal("legacy_provider"),
  confirmation: z.string().trim().min(1).max(512),
  model: modelNameSchema,
  reasoningEffort: reasoningEffortSchema,
});

const beginExternalStartInputSchema = withBoundSourceFields({
  action: z.literal("start"),
  requestId: boundedIdSchema,
  confirmedByUser: z.literal(true),
  instruction: externalPreservingTextSchema,
  materials: z.array(externalMaterialSchema).max(64).optional(),
  skills: uniqueSkillsSchema.optional(),
  ...externalSourceBindingFields,
  confirmedWikiPaths: confirmedWikiPathsSchema,
  expectedWikiRevision: hashSchema,
});
const beginExternalInputSchema = withSafePlainInput(
  z.discriminatedUnion("action", [
    beginExternalStartInputSchema,
    z.strictObject({
      action: z.literal("resume"),
      transactionId: boundedIdSchema,
      bindingHash: hashSchema,
    }),
  ]),
);

const candidateReceiptSchema = z
  .strictObject({
    type: z.literal("external_candidate_receipt"),
    version: z.literal(1),
    transactionId: boundedIdSchema,
    generation: generationSchema,
    bindingHash: hashSchema,
    writerExecutionId: boundedIdSchema,
    classification: z.enum(["minor", "provisional", "blocking"]),
    issues: z.array(reviewIssueSchema).max(256),
    questions: z.array(z.string().trim().min(1).max(4_096)).max(64),
    summary: z.string().trim().min(1).max(16_384),
  })
  .superRefine((receipt, context) => {
    if (
      receipt.classification === "minor" &&
      (receipt.questions.length !== 0 ||
        receipt.issues.some((issue) => issue.severity !== "minor"))
    ) {
      context.addIssue({
        code: "custom",
        message: "minor candidate receipt is inconsistent",
      });
    }
    if (
      receipt.classification === "provisional" &&
      !receipt.issues.some((issue) => issue.severity === "provisional")
    ) {
      context.addIssue({
        code: "custom",
        message: "provisional candidate receipt needs a provisional issue",
      });
    }
    if (
      receipt.classification === "blocking" &&
      (receipt.questions.length === 0 ||
        !receipt.issues.some((issue) => issue.severity === "blocking"))
    ) {
      context.addIssue({
        code: "custom",
        message:
          "blocking candidate receipt needs a blocking issue and a question",
      });
    }
  });

const externalReviewReceiptSchema = z
  .strictObject({
    type: z.literal("external_review_receipt"),
    version: z.literal(1),
    transactionId: boundedIdSchema,
    generation: generationSchema,
    bindingHash: hashSchema,
    reviewPackageHash: hashSchema,
    candidateRootHash: hashSchema,
    candidateReceiptHash: hashSchema,
    reviewerExecutionId: boundedIdSchema,
    verdict: z.enum([
      "pass",
      "follow_up",
      "changes_requested",
      "requires_user",
    ]),
    issues: z.array(reviewIssueSchema).max(256),
  })
  .superRefine((receipt, context) => {
    const severities = new Set(receipt.issues.map((issue) => issue.severity));
    const valid =
      receipt.verdict === "pass"
        ? receipt.issues.length === 0
        : receipt.verdict === "follow_up"
          ? severities.has("provisional") && !severities.has("blocking")
          : receipt.verdict === "changes_requested"
            ? receipt.issues.length > 0 &&
              [...severities].every((severity) => severity === "minor")
            : receipt.issues.length > 0;
    if (!valid) {
      context.addIssue({
        code: "custom",
        message: "external review verdict is inconsistent",
      });
    }
  });

const prepareExternalReviewInputSchema = z
  .strictObject({
    action: z.literal("prepare_review"),
    transactionId: boundedIdSchema,
    bindingHash: hashSchema,
    candidateReceipt: candidateReceiptSchema,
  })
  .superRefine((input, context) => {
    if (
      input.candidateReceipt.transactionId !== input.transactionId ||
      input.candidateReceipt.bindingHash !== input.bindingHash
    ) {
      context.addIssue({
        code: "custom",
        message: "candidate receipt does not match its finalize binding",
      });
    }
  });
const submitExternalReviewInputSchema = z
  .strictObject({
    action: z.literal("submit_review"),
    transactionId: boundedIdSchema,
    bindingHash: hashSchema,
    reviewReceipt: externalReviewReceiptSchema,
  })
  .superRefine((input, context) => {
    if (
      input.reviewReceipt.transactionId !== input.transactionId ||
      input.reviewReceipt.bindingHash !== input.bindingHash
    ) {
      context.addIssue({
        code: "custom",
        message: "review receipt does not match its finalize binding",
      });
    }
  });
const reportExternalHostFailureInputSchema = z
  .strictObject({
    action: z.literal("report_host_failure"),
    transactionId: boundedIdSchema,
    bindingHash: hashSchema,
    phase: z.enum(["candidate_writer", "reviewer"]),
    code: z.enum([
      "host_cancelled",
      "host_timeout",
      "host_model_failure",
      "host_process_failure",
    ]),
    message: z.string().trim().min(1).max(4_096),
    retryable: z.boolean(),
    reviewPackageHash: hashSchema.optional(),
  })
  .superRefine((input, context) => {
    if (input.phase === "reviewer" && input.reviewPackageHash === undefined) {
      context.addIssue({
        code: "custom",
        message: "host failure phase and Review package binding do not match",
      });
    }
  });
const finalizeExternalInputSchema = withSafePlainInput(
  z.discriminatedUnion("action", [
    prepareExternalReviewInputSchema,
    submitExternalReviewInputSchema,
    reportExternalHostFailureInputSchema,
    z.strictObject({
      action: z.literal("abort"),
      transactionId: boundedIdSchema,
      bindingHash: hashSchema,
      confirmedByUser: z.literal(true),
    }),
  ]),
);

const personalFinishInputSchema = withSafePlainInput(
  z
    .strictObject({
      runId: z.string().uuid(),
      candidateReceipt: candidateReceiptSchema.optional(),
      reviewReceipt: externalReviewReceiptSchema.optional(),
    })
    .superRefine((input, context) => {
      if (
        input.candidateReceipt !== undefined &&
        input.reviewReceipt !== undefined
      ) {
        context.addIssue({
          code: "custom",
          message: "finish accepts one receipt phase at a time",
        });
      }
    }),
);

export const toolInputSchemas = {
  openwiki_status: statusInputSchema,
  openwiki_read: withSafePlainInput(
    z.strictObject({
      paths: z
        .array(z.string().min(1).max(32_768))
        .min(1)
        .max(32)
        .refine(
          (values) => new Set(values).size === values.length,
          "paths must be unique",
        )
        .optional(),
      expectedWikiRevision: hashSchema.optional(),
    }),
  ),
  openwiki_begin: personalBeginInputSchema,
  openwiki_submit_plan: personalSubmitPlanInputSchema,
  openwiki_next_page: personalRunInputSchema,
  openwiki_inspect_page_claims: personalInspectPageClaimsInputSchema,
  openwiki_submit_page: personalSubmitPageInputSchema,
  openwiki_finish: personalFinishInputSchema,
  openwiki_setup: setupInputSchema,
  openwiki_prepare_sources: prepareSourcesInputSchema,
  openwiki_list_skills: listSkillsInputSchema,
  openwiki_query: queryInputSchema,
  openwiki_update: updateInputSchema,
  openwiki_begin_external_update: beginExternalInputSchema,
  openwiki_finalize_external_update: finalizeExternalInputSchema,
  openwiki_set_default_model: setDefaultModelInputSchema,
} satisfies Record<ToolName, z.ZodType>;

export const commonErrorCodeSchema = z.enum([
  "invalid_input",
  "setup_required",
  "busy",
  "capability_unverified",
  "auth_required",
  "provider_failure",
  "process_failure",
  "platform_unsupported",
  "internal_error",
]);

const recoveryActionSchema = z.enum([
  "none",
  "retry",
  "run_setup",
  "reauthorize",
  "confirm_update",
  "clarify",
  "resolve_attention",
  "restore",
]);

export const recoverySchema = z.strictObject({
  action: recoveryActionSchema,
  message: z.string().trim().min(1).max(2_048).optional(),
});
const externalRecoverySchema = z.strictObject({
  action: z.enum(["none", "retry", "clarify", "resolve_attention", "restore"]),
  message: z.string().trim().min(1).max(2_048).optional(),
});

const errorDetailsSchema = z.strictObject({
  attemptExpiresAt: timestampSchema.optional(),
  diagnostic: z.string().trim().min(1).max(4_096).optional(),
  failureStage: resultFailureStageSchema.optional(),
  limit: z.number().int().nonnegative().optional(),
  lock: z
    .enum(["operation", "credentials", "config", "wiki", "manifests"])
    .optional(),
  paths: z.array(z.string().max(32_768)).max(1_024).optional(),
  providerStatusClass: z.enum(["4xx", "5xx"]).optional(),
  retryAfterMs: z.number().int().min(0).max(30_000).optional(),
});
const externalErrorDetailsSchema = z.strictObject({
  diagnostic: z.string().trim().min(1).max(4_096).optional(),
  limit: z.number().int().nonnegative().optional(),
  lock: z.enum(["operation", "wiki", "manifests"]).optional(),
  paths: z.array(z.string().max(32_768)).max(1_024).optional(),
  retryAfterMs: z.number().int().min(0).max(30_000).optional(),
});

function protocolFailureSchema<C extends z.ZodType>(code: C) {
  return z.strictObject({
    code,
    details: errorDetailsSchema.optional(),
    message: z.string().trim().min(1).max(4_096),
    retryable: z.boolean(),
  });
}

function errorResultSchema<C extends z.ZodType>(code: C) {
  return z.strictObject({
    error: protocolFailureSchema(code),
    ok: z.literal(false),
    recovery: recoverySchema,
  });
}
function externalErrorResultSchema<C extends z.ZodType>(code: C) {
  return z.strictObject({
    error: z.strictObject({
      code,
      details: externalErrorDetailsSchema.optional(),
      message: z.string().trim().min(1).max(4_096),
      retryable: z.boolean(),
    }),
    ok: z.literal(false),
    recovery: externalRecoverySchema,
  });
}

const setupErrorCodeSchema = z.union([
  commonErrorCodeSchema,
  z.enum([
    "attempt_not_found",
    "attempt_expired",
    "attempt_state_invalid",
    "oauth_failed",
    "model_rejected",
  ]),
]);
const sourceErrorCodeSchema = z.union([
  commonErrorCodeSchema,
  z.enum(["source_rejected", "source_too_large", "source_changed"]),
]);
const skillErrorCodeSchema = z.union([
  commonErrorCodeSchema,
  z.literal("skill_manifest_invalid"),
]);
const queryErrorCodeSchema = z.union([
  commonErrorCodeSchema,
  z.enum([
    "source_rejected",
    "source_manifest_invalid",
    "source_changed",
    "skill_untrusted",
    "model_rejected",
    "restore_required",
  ]),
]);
const updateErrorCodeSchema = z.union([
  commonErrorCodeSchema,
  z.enum([
    "confirmation_required",
    "source_rejected",
    "source_manifest_invalid",
    "source_changed",
    "skill_untrusted",
    "restore_required",
  ]),
]);
const setDefaultErrorCodeSchema = z.union([
  commonErrorCodeSchema,
  z.enum(["confirmation_required", "model_rejected"]),
]);
const externalErrorCodeSchema = z.enum([
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
]);
const setupVerificationFailureCodeSchema = z.enum([
  "model_rejected",
  "provider_failure",
  "process_failure",
  "platform_unsupported",
  "internal_error",
]);
const updateTransactionFailureCodeSchema = z.enum([
  "provider_failure",
  "process_failure",
  "platform_unsupported",
  "internal_error",
  "validation_failed",
  "restore_required",
]);

const modelEvidenceSchema = z
  .strictObject({
    providerAccepted: z.literal(true),
    providerReportedModel: z.string().max(256).optional(),
    requested: modelSelectionSchema,
    sent: modelSelectionSchema,
  })
  .superRefine((evidence, context) => {
    if (!modelSelectionsEqual(evidence.requested, evidence.sent)) {
      context.addIssue({
        code: "custom",
        message: "successful model evidence cannot contain a fallback",
      });
    }
  });
const selectedSkillSchema = z.strictObject({
  id: z.string().regex(/^[a-z][a-z0-9-]{0,127}$/u),
  packageHash: hashSchema,
});
const wikiChangeSchema = z.strictObject({
  afterHash: hashSchema.optional(),
  beforeHash: hashSchema.optional(),
  operation: z.enum(["added", "modified", "deleted", "renamed"]),
  path: z.string().min(1).max(32_768),
  previousPath: z.string().min(1).max(32_768).optional(),
});
const followUpIssueSchema = reviewIssueSchema.extend({
  severity: z.literal("provisional"),
});
const capabilitySchema = z.strictObject({
  id: z.string().regex(/^[a-z][a-z0-9_.-]{0,127}$/u),
  verifiedAt: timestampSchema,
});
const staticCapabilitySchema = z.strictObject({
  available: z.boolean(),
  id: z.string().regex(/^[a-z][a-z0-9_.-]{0,127}$/u),
  reason: z.string().trim().min(1).max(2_048).optional(),
});
const authenticationStatusSchema = z.discriminatedUnion("status", [
  z.strictObject({ status: z.literal("not_configured") }),
  z.strictObject({
    expiresAt: timestampSchema.optional(),
    status: z.literal("authorized"),
  }),
  z.strictObject({ status: z.literal("expired") }),
  z.strictObject({ status: z.literal("invalid") }),
]);
const verifiedModelSchema = z.strictObject({
  ...modelSelectionSchema.shape,
  providerAccepted: z.literal(true),
  providerReportedModel: z.string().max(256).optional(),
  verifiedAt: timestampSchema,
});
const legacyProviderStatusSchema = z
  .strictObject({
    available: z.literal(true),
    authRequired: z.literal(true),
    authentication: authenticationStatusSchema,
    initialized: z.boolean(),
    defaultModel: modelSelectionSchema.nullable(),
    verifiedModels: z.array(verifiedModelSchema),
  })
  .superRefine((status, context) => {
    if (!status.initialized && status.defaultModel !== null) {
      context.addIssue({
        code: "custom",
        message: "uninitialized legacy provider cannot expose a default model",
      });
    }
    if (status.initialized) {
      const defaultModel = status.defaultModel;
      const defaultIsVerified =
        defaultModel !== null &&
        status.verifiedModels.some((candidate) =>
          modelSelectionsEqual(candidate, defaultModel),
        );
      if (status.authentication.status !== "authorized" || !defaultIsVerified) {
        context.addIssue({
          code: "custom",
          message:
            "initialized legacy provider requires authorized authentication and a verified default",
        });
      }
    }
  });
const activeExternalTransactionSchema = z
  .strictObject({
    transactionId: boundedIdSchema,
    generation: generationSchema,
    state: z.enum([
      "candidate_writable",
      "review_ready",
      "repair_ready",
      "attention",
      "publish_pending",
    ]),
    nextAction: z.enum([
      "resume_candidate",
      "retry_review",
      "resolve_attention",
      "restore",
    ]),
  })
  .superRefine((transaction, context) => {
    const expected =
      transaction.state === "review_ready"
        ? "retry_review"
        : transaction.state === "attention"
          ? "resolve_attention"
          : transaction.state === "publish_pending"
            ? "restore"
            : "resume_candidate";
    if (transaction.nextAction !== expected) {
      context.addIssue({
        code: "custom",
        message: "external transaction state and next action do not match",
      });
    }
  });
const recoveryStateSchema = z.enum([
  "attention",
  "clean",
  "recovery_pending",
  "review_pending",
  "restore_required",
  "restore_failed",
]);

const visualizerStatusSchema = z.strictObject({
  id: z.literal("selfopenwiki.zxh_wiki_viewer"),
  contractSchema: z.literal(1),
  launcherPath: absolutePathSchema,
  loopbackOnly: z.literal(true),
  autoOpen: z.literal(false),
  wikiRootInput: z.strictObject({
    kind: z.literal("argument"),
    flag: z.literal("--wiki-root"),
  }),
  urlTemplate: z.literal("http://127.0.0.1:{port}/wiki/local"),
});

const statusSuccessSchema = z
  .strictObject({
    executionMode: z.literal("external_agent"),
    authRequired: z.literal(false),
    authentication: z.strictObject({ status: z.literal("not_required") }),
    capabilities: z.array(capabilitySchema),
    defaultModel: z.null(),
    initialized: z.boolean(),
    externalAgent: z.strictObject({
      ready: z.boolean(),
      activeTransaction: activeExternalTransactionSchema.nullable(),
    }),
    legacyProvider: legacyProviderStatusSchema,
    ok: z.literal(true),
    paths: z.strictObject({
      openWikiRoot: absolutePathSchema,
      runtimeRoot: absolutePathSchema,
      wikiRoot: absolutePathSchema,
    }),
    visualizer: visualizerStatusSchema.optional(),
    recovery: recoverySchema,
    runtime: z.strictObject({
      locks: z.array(
        z.strictObject({
          held: z.boolean(),
          name: z.enum([
            "operation",
            "credentials",
            "config",
            "wiki",
            "manifests",
          ]),
        }),
      ),
      recoveryState: recoveryStateSchema,
    }),
    staticCapabilities: z.array(staticCapabilitySchema),
    status: z.literal("status"),
    version: z.strictObject({
      contractSchema: z.literal(2),
      mcpServer: z.string().min(1).max(128),
      openWiki: z.string().min(1).max(128),
    }),
    verifiedModels: z.array(verifiedModelSchema).max(0),
    wikiRevision: hashSchema,
  })
  .superRefine((status, context) => {
    if (status.initialized !== status.externalAgent.ready) {
      context.addIssue({
        code: "custom",
        message: "external initialization must equal external readiness",
      });
    }
  });

const setupSuccessSchema = z.discriminatedUnion("status", [
  z.strictObject({
    authorizationUrl: z.string().url().max(8_192),
    expiresAt: timestampSchema,
    ok: z.literal(true),
    recovery: recoverySchema,
    setupAttemptId: boundedIdSchema,
    status: z.literal("setup_pending"),
  }),
  z.strictObject({
    expiresAt: timestampSchema,
    ok: z.literal(true),
    recovery: recoverySchema,
    setupAttemptId: boundedIdSchema,
    status: z.literal("setup_authorized"),
  }),
  z.strictObject({
    failure: protocolFailureSchema(setupVerificationFailureCodeSchema),
    ok: z.literal(true),
    recovery: recoverySchema,
    setupAttemptId: boundedIdSchema,
    status: z.literal("verification_failed"),
  }),
  z.strictObject({
    model: modelEvidenceSchema,
    ok: z.literal(true),
    recovery: recoverySchema,
    status: z.literal("setup_completed"),
  }),
  z.strictObject({
    ok: z.literal(true),
    recovery: recoverySchema,
    setupAttemptId: boundedIdSchema,
    status: z.literal("setup_cancelled"),
  }),
]);

const preparedSourceFileSchema = z.strictObject({
  hash: hashSchema,
  path: z.string().min(1).max(32_768),
  risks: z.array(z.string().min(1).max(512)).max(32),
  size: z.number().int().nonnegative(),
});
const prepareSourcesSuccessSchema = z.strictObject({
  confirmation: z.string().min(1).max(512),
  files: z.array(preparedSourceFileSchema),
  manifestHash: hashSchema,
  ok: z.literal(true),
  recovery: recoverySchema,
  sensitivePolicyHash: hashSchema,
  sensitivePolicyVersion: z.number().int().positive(),
  sourceManifestId: boundedIdSchema,
  status: z.literal("sources_prepared"),
});

const listedSkillSchema = z
  .strictObject({
    category: z.enum(["base", "specialized"]),
    description: z.string().max(4_096),
    id: z.string().regex(/^[a-z][a-z0-9-]{0,127}$/u),
    loadOrder: z.enum(["base_always_first", "request_order"]),
    packageHash: hashSchema,
    title: z.string().trim().min(1).max(256),
    verified: z.boolean(),
  })
  .superRefine((skill, context) => {
    const expected =
      skill.category === "base" ? "base_always_first" : "request_order";
    if (skill.loadOrder !== expected) {
      context.addIssue({
        code: "custom",
        message: "Skill category and load order do not match",
      });
    }
  });
const listSkillsSuccessSchema = z.strictObject({
  ok: z.literal(true),
  recovery: recoverySchema,
  skills: z.array(listedSkillSchema),
  status: z.literal("skills_listed"),
});

const externalSkillSchema = z
  .strictObject({
    id: z.string().regex(/^[a-z][a-z0-9-]{0,127}$/u),
    category: z.enum(["base", "specialized"]),
    loadOrder: z.enum(["base_always_first", "request_order"]),
    packageHash: hashSchema,
    rootPath: absolutePathSchema,
  })
  .superRefine((skill, context) => {
    const expected =
      skill.category === "base" ? "base_always_first" : "request_order";
    if (skill.loadOrder !== expected) {
      context.addIssue({
        code: "custom",
        message: "external Skill category and load order do not match",
      });
    }
  });
const orderedExternalSkillsSchema = z
  .array(externalSkillSchema)
  .min(1)
  .max(33)
  .superRefine((skills, context) => {
    const [base, ...specialized] = skills;
    if (
      base?.id !== "kg-c7-project-wiki" ||
      base.category !== "base" ||
      base.loadOrder !== "base_always_first"
    ) {
      context.addIssue({
        code: "custom",
        message: "the kg-c7-project-wiki base Skill must be first",
      });
    }
    if (specialized.some((skill) => skill.category !== "specialized")) {
      context.addIssue({
        code: "custom",
        message: "only the first external Skill may be the base Skill",
      });
    }
    if (new Set(skills.map((skill) => skill.id)).size !== skills.length) {
      context.addIssue({
        code: "custom",
        message: "external Skills must not contain duplicates",
      });
    }
  });
const immutablePackageSchema = z.strictObject({
  path: absolutePathSchema,
  packageHash: hashSchema,
});
const externalRuleFields = {
  hardRulePackage: immutablePackageSchema,
  skills: orderedExternalSkillsSchema,
};
const externalWorkPackageSchema = z
  .strictObject({
    version: z.literal(1),
    transactionId: boundedIdSchema,
    generation: generationSchema,
    beforeWikiRevision: hashSchema,
    sourceManifestHash: hashSchema.nullable(),
    sourceTreeHash: hashSchema.nullable(),
    skillAggregateHash: hashSchema,
    confirmedWikiPaths: confirmedWikiPathsSchema,
    requestPackage: immutablePackageSchema,
    bindingHash: hashSchema,
    candidate: z.strictObject({
      workspaceId: boundedIdSchema,
      rootPath: absolutePathSchema,
      permissions: z.tuple([
        z.literal("read"),
        z.literal("list"),
        z.literal("write"),
      ]),
      allowedChangedPaths: confirmedWikiPathsSchema,
    }),
    sources: z
      .strictObject({
        rootPath: absolutePathSchema,
        permissions: z.tuple([z.literal("read"), z.literal("list")]),
      })
      .nullable(),
    rules: z.strictObject({
      ...externalRuleFields,
      candidateResultContract: z.strictObject({
        path: absolutePathSchema,
        schemaHash: hashSchema,
      }),
    }),
  })
  .superRefine((workPackage, context) => {
    if (
      workPackage.confirmedWikiPaths.length !==
        workPackage.candidate.allowedChangedPaths.length ||
      workPackage.confirmedWikiPaths.some(
        (wikiPath, index) =>
          wikiPath !== workPackage.candidate.allowedChangedPaths[index],
      )
    ) {
      context.addIssue({
        code: "custom",
        message: "candidate changed paths must equal the confirmed Wiki scope",
      });
    }
    const hasManifest = workPackage.sourceManifestHash !== null;
    const hasSourceTree = workPackage.sourceTreeHash !== null;
    if (hasManifest !== hasSourceTree) {
      context.addIssue({
        code: "custom",
        message: "source manifest and source tree hashes must be paired",
      });
    }
    const hasSourceBinding = hasManifest && hasSourceTree;
    if (hasSourceBinding !== (workPackage.sources !== null)) {
      context.addIssue({
        code: "custom",
        message: "source paths and source hashes must be present together",
      });
    }
  });
const externalReviewPackageSchema = z.strictObject({
  version: z.literal(1),
  transactionId: boundedIdSchema,
  generation: generationSchema,
  bindingHash: hashSchema,
  candidateRootHash: hashSchema,
  candidateReceiptHash: hashSchema,
  requestPackage: immutablePackageSchema,
  sourceManifestHash: hashSchema.nullable(),
  skillAggregateHash: hashSchema,
  confirmedWikiPaths: confirmedWikiPathsSchema,
  candidate: z.strictObject({
    rootPath: absolutePathSchema,
    permissions: z.tuple([z.literal("read"), z.literal("list")]),
  }),
  rules: z.strictObject({
    ...externalRuleFields,
    reviewResultContract: z.strictObject({
      path: absolutePathSchema,
      schemaHash: hashSchema,
    }),
  }),
});
const externalSuccessCommon = {
  ok: z.literal(true),
  executionMode: z.literal("external_agent"),
  authRequired: z.literal(false),
  transactionId: boundedIdSchema,
  generation: generationSchema,
  bindingHash: hashSchema,
  recovery: externalRecoverySchema,
};
function externalReviewPackageOutcomeSchema(
  status: "external_review_ready" | "external_review_resumed",
) {
  return z
    .strictObject({
      ...externalSuccessCommon,
      status: z.literal(status),
      candidateRootHash: hashSchema,
      candidateReceiptHash: hashSchema,
      reviewPackageHash: hashSchema,
      reviewPackage: externalReviewPackageSchema,
    })
    .superRefine((result, context) => {
      const reviewPackage = result.reviewPackage;
      if (
        reviewPackage.transactionId !== result.transactionId ||
        reviewPackage.generation !== result.generation ||
        reviewPackage.bindingHash !== result.bindingHash ||
        reviewPackage.candidateRootHash !== result.candidateRootHash ||
        reviewPackage.candidateReceiptHash !== result.candidateReceiptHash
      ) {
        context.addIssue({
          code: "custom",
          message: "Review package does not match its external outcome",
        });
      }
    });
}
const externalPublishedFields = {
  ...externalSuccessCommon,
  published: z.literal(true),
  wikiRevision: hashSchema,
  candidateRootHash: hashSchema,
  reviewReceiptHash: hashSchema,
  reviewEvidence: z.literal("host_attested"),
};
const externalPublishedSchema = z.strictObject({
  ...externalPublishedFields,
  status: z.literal("published"),
});
const externalPublishedWithFollowUpSchema = z.strictObject({
  ...externalPublishedFields,
  status: z.literal("published_with_follow_up"),
  followUp: z.array(followUpIssueSchema).min(1).max(256),
});
const externalNeedsClarificationSchema = z.strictObject({
  ...externalSuccessCommon,
  status: z.literal("needs_clarification"),
  published: z.literal(false),
  candidateRetained: z.literal(true),
  nextAction: z.literal("clarify"),
  issues: z.array(reviewIssueSchema).max(256),
  questions: z.array(z.string().trim().min(1).max(4_096)).min(1).max(64),
});
const externalUpdateAbortedSchema = z.strictObject({
  ...externalSuccessCommon,
  status: z.literal("external_update_aborted"),
  published: z.literal(false),
});
const beginExternalSuccessSchema = z.union([
  z.strictObject({
    ok: z.literal(true),
    status: z.literal("external_update_ready"),
    executionMode: z.literal("external_agent"),
    authRequired: z.literal(false),
    workPackage: externalWorkPackageSchema,
    recovery: externalRecoverySchema,
  }),
  z.strictObject({
    ok: z.literal(true),
    status: z.literal("external_update_resumed"),
    executionMode: z.literal("external_agent"),
    authRequired: z.literal(false),
    workPackage: externalWorkPackageSchema,
    recovery: externalRecoverySchema,
  }),
  externalReviewPackageOutcomeSchema("external_review_resumed"),
  externalPublishedSchema,
  externalPublishedWithFollowUpSchema,
  externalNeedsClarificationSchema,
  externalUpdateAbortedSchema,
]);
const finalizeExternalSuccessSchema = z.union([
  externalReviewPackageOutcomeSchema("external_review_ready"),
  externalPublishedSchema,
  externalPublishedWithFollowUpSchema,
  z.strictObject({
    ...externalSuccessCommon,
    status: z.literal("repair_ready"),
    published: z.literal(false),
    nextAction: z.literal("resume_candidate"),
    reviewReceiptHash: hashSchema,
    issues: z
      .array(reviewIssueSchema.extend({ severity: z.literal("minor") }))
      .min(1)
      .max(256),
  }),
  externalNeedsClarificationSchema,
  z.strictObject({
    ...externalSuccessCommon,
    status: z.literal("external_host_failure"),
    candidateRetained: z.literal(true),
    nextAction: z.enum(["resume_candidate", "retry_review"]),
  }),
  externalUpdateAbortedSchema,
]);

const querySuccessSchema = z.strictObject({
  answer: z.string().max(2_000_000),
  model: modelEvidenceSchema,
  ok: z.literal(true),
  recovery: recoverySchema,
  selectedSkills: z.array(selectedSkillSchema),
  skillAggregateHash: hashSchema,
  sourceManifestHash: hashSchema.optional(),
  status: z.literal("answered"),
  wikiRevision: hashSchema,
});

const updateModelSchema = z.strictObject({
  providerAccepted: z.boolean(),
  providerReportedModel: z.string().max(256).optional(),
  requested: modelSelectionSchema,
  sent: modelSelectionSchema.nullable(),
});
const validationResultSchema = z
  .strictObject({
    checks: z
      .array(
        z.strictObject({
          id: z.string().regex(/^[a-z][a-z0-9_]{0,127}$/u),
          message: z.string().trim().min(1).max(4_096).optional(),
          status: z.enum(["passed", "failed"]),
        }),
      )
      .min(1),
    passed: z.boolean(),
  })
  .superRefine((validation, context) => {
    if (
      validation.passed !==
      validation.checks.every((check) => check.status === "passed")
    ) {
      context.addIssue({
        code: "custom",
        message: "validation summary does not match its checklist",
      });
    }
  });
const reviewResultSchema = z.strictObject({
  issues: z.array(reviewIssueSchema).optional(),
  rounds: z.number().int().min(0).max(3),
  status: z.enum([
    "not_run",
    "passed",
    "follow_up",
    "requires_attention",
    "technical_failure",
  ]),
});
function createUpdateSuccessSchema(baseWikiRevision: z.ZodType) {
  const updateCommonFields = {
    baseWikiRevision,
    changes: z.array(wikiChangeSchema),
    model: updateModelSchema,
    ok: z.literal(true),
    questions: z.array(z.string().trim().min(1).max(4_096)),
    recovery: recoverySchema,
    recoveryState: recoveryStateSchema,
    review: reviewResultSchema,
    selectedSkills: z.array(selectedSkillSchema),
    skillAggregateHash: hashSchema,
    sourceManifestHash: hashSchema.optional(),
    validation: validationResultSchema,
  };
  const reviewRequiresAttentionSchema = z
    .strictObject({
      ...updateCommonFields,
      failure: protocolFailureSchema(
        updateTransactionFailureCodeSchema,
      ).optional(),
      issues: z.array(reviewIssueSchema),
      published: z.literal(true),
      status: z.literal("review_requires_attention"),
    })
    .superRefine((result, context) => {
      if (result.issues.length === 0 && result.failure === undefined) {
        context.addIssue({
          code: "custom",
          message:
            "review_requires_attention needs semantic issues or a technical failure",
        });
      }
    });
  return z
    .union([
      z.strictObject({
        ...updateCommonFields,
        published: z.literal(true),
        status: z.literal("published"),
      }),
      z.strictObject({
        ...updateCommonFields,
        followUp: z.array(followUpIssueSchema).min(1),
        published: z.literal(true),
        status: z.literal("published_with_follow_up"),
      }),
      z.strictObject({
        ...updateCommonFields,
        issues: z.array(reviewIssueSchema).optional(),
        questions: z.array(z.string().trim().min(1).max(4_096)).min(1),
        published: z.literal(false),
        status: z.literal("needs_clarification"),
      }),
      reviewRequiresAttentionSchema,
      z.strictObject({
        ...updateCommonFields,
        failure: protocolFailureSchema(z.literal("wiki_conflict")),
        published: z.literal(false),
        status: z.literal("conflict"),
      }),
      z.strictObject({
        ...updateCommonFields,
        failure: protocolFailureSchema(updateTransactionFailureCodeSchema),
        published: z.literal(false),
        status: z.literal("failed"),
      }),
    ])
    .superRefine((result, context) => {
      if (
        !["conflict", "failed"].includes(result.status) &&
        (result.model.providerAccepted !== true || result.model.sent === null)
      ) {
        context.addIssue({
          code: "custom",
          message:
            "model-driven update outcomes require accepted model evidence",
        });
      }
      const stateIsConsistent =
        result.status === "published"
          ? result.validation.passed &&
            result.review.status === "passed" &&
            result.review.rounds >= 1 &&
            result.questions.length === 0 &&
            result.recoveryState === "clean"
          : result.status === "published_with_follow_up"
            ? result.validation.passed &&
              result.review.status === "follow_up" &&
              result.review.rounds >= 1 &&
              result.recoveryState === "clean"
            : result.status === "needs_clarification"
              ? (!result.validation.passed &&
                  result.review.status === "not_run" &&
                  result.review.rounds === 0) ||
                (result.validation.passed &&
                  result.review.status === "requires_attention" &&
                  result.review.rounds >= 1)
              : result.status === "review_requires_attention"
                ? result.validation.passed &&
                  ["requires_attention", "technical_failure"].includes(
                    result.review.status,
                  ) &&
                  result.recoveryState !== "clean"
                : (!result.validation.passed &&
                    result.review.status === "not_run" &&
                    result.review.rounds === 0) ||
                  (result.validation.passed &&
                    result.review.status === "technical_failure");
      if (!stateIsConsistent) {
        context.addIssue({
          code: "custom",
          message: "update status is inconsistent with validation/review state",
        });
      }
      if (
        result.model.sent !== null &&
        !modelSelectionsEqual(result.model.requested, result.model.sent)
      ) {
        context.addIssue({
          code: "custom",
          message: "update outcomes cannot contain a model or effort fallback",
        });
      }
    });
}

const internalUpdateSuccessSchema = createUpdateSuccessSchema(
  hashSchema.nullable().default(null),
);
const finalizedUpdateSuccessSchema = createUpdateSuccessSchema(hashSchema);

function modelSelectionsEqual(
  left: z.infer<typeof modelSelectionSchema>,
  right: z.infer<typeof modelSelectionSchema>,
): boolean {
  return (
    left.model === right.model && left.reasoningEffort === right.reasoningEffort
  );
}

const setDefaultSuccessSchema = z.strictObject({
  model: modelEvidenceSchema,
  ok: z.literal(true),
  recovery: recoverySchema,
  status: z.literal("default_model_changed"),
});

const personalProtocolSchema = z.literal("selfopenwiki:personal-openwiki-v1");
const personalErrorCodeSchema = z.enum([
  "invalid_input",
  "personal_root_invalid",
  "busy",
  "capability_unverified",
  "upstream_incompatible",
  "source_changed",
  "source_manifest_invalid",
  "skill_untrusted",
  "invalid_state",
  "validation_failed",
  "wiki_conflict",
  "restore_required",
  "internal_error",
]);
const personalErrorResultSchema = externalErrorResultSchema(
  personalErrorCodeSchema,
);
const personalBindingSchema = z.strictObject({
  runId: z.string().uuid(),
  generation: generationSchema,
  transactionId: boundedIdSchema,
  candidateBindingHash: hashSchema,
  candidateRootHash: hashSchema,
  queueHash: hashSchema,
  planHash: hashSchema,
  wikiRevision: hashSchema,
});
const personalBeginBindingSchema = z.strictObject({
  wikiRoot: absolutePathSchema,
  runtimeRoot: absolutePathSchema,
  wikiRevision: hashSchema,
  markdownWikiRevision: hashSchema,
  skillAggregateHash: hashSchema,
  upstreamCommit: z.string().regex(/^[a-f0-9]{40}$/u),
});
const candidateWritePackageSchema = z.strictObject({
  rootPath: absolutePathSchema,
  pagePath: personalPagePathSchema,
  permissions: z.tuple([
    z.literal("read"),
    z.literal("list"),
    z.literal("write"),
  ]),
});
const personalSuccessCommon = {
  ok: z.literal(true),
  protocol: personalProtocolSchema,
  recovery: externalRecoverySchema,
};
const personalBeginSuccessSchema = z.union([
  z.strictObject({
    ...personalSuccessCommon,
    status: z.enum(["planning", "resuming"]),
    runId: z.string().uuid(),
    wikiRoot: absolutePathSchema,
    runtimeRoot: absolutePathSchema,
    wikiRevision: hashSchema,
    skillAggregateHash: hashSchema,
    upstreamCommit: z.string().regex(/^[a-f0-9]{40}$/u),
    binding: personalBeginBindingSchema,
  }),
  z.strictObject({
    ...personalSuccessCommon,
    status: z.literal("noop"),
    wikiRoot: absolutePathSchema,
    runtimeRoot: absolutePathSchema,
    wikiRevision: hashSchema,
    skillAggregateHash: hashSchema,
    upstreamCommit: z.string().regex(/^[a-f0-9]{40}$/u),
  }),
]);
const personalSubmitPlanSuccessSchema = z.strictObject({
  ...personalSuccessCommon,
  status: z.literal("plan_accepted"),
  runId: z.string().uuid(),
  planHash: hashSchema,
  queueHash: hashSchema,
  pageCount: z.number().int().min(0).max(2_048),
  binding: personalBindingSchema,
});
const personalNextPageSuccessSchema = z.union([
  z.strictObject({
    ...personalSuccessCommon,
    status: z.literal("page_pending"),
    runId: z.string().uuid(),
    jobId: z.string().uuid(),
    path: personalPagePathSchema,
    title: z.string().trim().min(1).max(512),
    purpose: z.string().trim().min(1).max(4_096),
    seedPaths: z.array(z.string().trim().min(1).max(1_024)),
    relatedPages: z.array(personalPagePathSchema),
    issueClaims: z.array(personalClaimSchema).max(256),
    candidate: candidateWritePackageSchema,
    binding: personalBindingSchema,
  }),
  z.strictObject({
    ...personalSuccessCommon,
    status: z.literal("queue_complete"),
    runId: z.string().uuid(),
    remainingPages: z.literal(0),
    nextAction: z.literal("finish"),
    binding: personalBindingSchema,
  }),
]);
const personalInspectSuccessSchema = z.strictObject({
  ...personalSuccessCommon,
  status: z.literal("claims_inspected"),
  runId: z.string().uuid(),
  jobId: z.string().uuid(),
  claims: z.array(personalClaimSchema).max(256),
  claimsHash: hashSchema,
  binding: personalBindingSchema,
});
const personalSubmitPageSuccessSchema = z.strictObject({
  ...personalSuccessCommon,
  status: z.literal("page_accepted"),
  runId: z.string().uuid(),
  jobId: z.string().uuid(),
  remainingPages: z.number().int().min(0).max(2_048),
  candidateBindingHash: hashSchema,
  pageContentHash: hashSchema,
  claimDecisionHash: hashSchema,
  binding: personalBindingSchema,
});
const personalFinishSuccessSchema = z.union([
  z.strictObject({
    ...personalSuccessCommon,
    status: z.literal("review_required"),
    nextAction: z.enum(["submit_candidate_receipt", "submit_review_receipt"]),
    runId: z.string().uuid(),
    transactionId: boundedIdSchema,
    generation: generationSchema,
    binding: personalBindingSchema,
    candidateReceiptHash: hashSchema.optional(),
    candidateRootHash: hashSchema.optional(),
    reviewPackageHash: hashSchema.optional(),
    reviewPackage: z.unknown().optional(),
  }),
  z.strictObject({
    ...personalSuccessCommon,
    status: z.literal("publish_pending"),
    runId: z.string().uuid(),
    transactionId: boundedIdSchema,
    generation: generationSchema,
    binding: personalBindingSchema,
  }),
  z.strictObject({
    ...personalSuccessCommon,
    status: z.literal("repair_ready"),
    nextAction: z.literal("resume"),
    runId: z.string().uuid(),
    transactionId: boundedIdSchema,
    generation: generationSchema,
    binding: personalBindingSchema,
    issues: z.array(reviewIssueSchema).max(256),
  }),
  z.strictObject({
    ...personalSuccessCommon,
    status: z.literal("needs_clarification"),
    nextAction: z.enum(["clarify", "abort"]),
    runId: z.string().uuid(),
    transactionId: boundedIdSchema,
    generation: generationSchema,
    candidateRetained: z.literal(true),
    published: z.literal(false),
    binding: personalBindingSchema,
    issues: z.array(reviewIssueSchema).max(256),
    questions: z.array(z.string().trim().min(1).max(4_096)).min(1).max(64),
  }),
  z.strictObject({
    ...personalSuccessCommon,
    status: z.literal("complete"),
    runId: z.string().uuid(),
    transactionId: boundedIdSchema,
    generation: generationSchema,
    published: z.literal(true),
    wikiRevision: hashSchema,
    beforeWikiHash: hashSchema,
    afterWikiHash: hashSchema,
    reviewReceiptHash: hashSchema,
    runReceiptHash: hashSchema,
    followUp: z.array(followUpIssueSchema).min(1).max(256).optional(),
    binding: personalBindingSchema,
  }),
]);

function outputUnion<C extends z.ZodType, S extends z.ZodType>(
  errorCode: C,
  success: S,
) {
  return z.union([errorResultSchema(errorCode), success]);
}

// Update orchestration builds and validates an outcome before the owning
// service attaches its locked Wiki revision. This schema must never cross the
// MCP boundary; the exported tool schema below requires the final revision.
export const internalUpdateOutputSchema = outputUnion(
  updateErrorCodeSchema,
  internalUpdateSuccessSchema,
);

export const toolOutputSchemas = {
  openwiki_status: outputUnion(commonErrorCodeSchema, statusSuccessSchema),
  openwiki_read: outputUnion(
    z.union([
      commonErrorCodeSchema,
      z.enum(["restore_required", "wiki_invalid", "wiki_changed"]),
    ]),
    z.strictObject({
      ok: z.literal(true),
      status: z.literal("wiki_read"),
      recovery: recoverySchema,
      revision: hashSchema,
      pages: z.array(
        z.strictObject({
          path: z.string().min(1),
          size: z.number().int().nonnegative(),
          contentHash: hashSchema,
        }),
      ),
      knowledge: z
        .array(
          z.strictObject({
            content: z.string().max(262_144),
            sourceId: z.string().min(1),
            revision: hashSchema,
            contentHash: hashSchema,
            verificationStatus: z.literal("unverified"),
          }),
        )
        .max(32),
    }),
  ),
  openwiki_begin: z.union([
    personalErrorResultSchema,
    personalBeginSuccessSchema,
  ]),
  openwiki_submit_plan: z.union([
    personalErrorResultSchema,
    personalSubmitPlanSuccessSchema,
  ]),
  openwiki_next_page: z.union([
    personalErrorResultSchema,
    personalNextPageSuccessSchema,
  ]),
  openwiki_inspect_page_claims: z.union([
    personalErrorResultSchema,
    personalInspectSuccessSchema,
  ]),
  openwiki_submit_page: z.union([
    personalErrorResultSchema,
    personalSubmitPageSuccessSchema,
  ]),
  openwiki_finish: z.union([
    personalErrorResultSchema,
    personalFinishSuccessSchema,
  ]),
  openwiki_setup: outputUnion(setupErrorCodeSchema, setupSuccessSchema),
  openwiki_prepare_sources: outputUnion(
    sourceErrorCodeSchema,
    prepareSourcesSuccessSchema,
  ),
  openwiki_list_skills: outputUnion(
    skillErrorCodeSchema,
    listSkillsSuccessSchema,
  ),
  openwiki_query: outputUnion(queryErrorCodeSchema, querySuccessSchema),
  openwiki_update: outputUnion(
    updateErrorCodeSchema,
    finalizedUpdateSuccessSchema,
  ),
  openwiki_begin_external_update: z.union([
    externalErrorResultSchema(externalErrorCodeSchema),
    beginExternalSuccessSchema,
  ]),
  openwiki_finalize_external_update: z.union([
    externalErrorResultSchema(externalErrorCodeSchema),
    finalizeExternalSuccessSchema,
  ]),
  openwiki_set_default_model: outputUnion(
    setDefaultErrorCodeSchema,
    setDefaultSuccessSchema,
  ),
} satisfies Record<ToolName, z.ZodType>;

export type ToolAnnotations = {
  destructiveHint: boolean;
  idempotentHint: boolean;
  openWorldHint: boolean;
  readOnlyHint: boolean;
};

export const toolAnnotations = {
  openwiki_status: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
  openwiki_read: {
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
} satisfies Record<ToolName, ToolAnnotations>;

export type ToolInput<T extends ToolName> = z.infer<
  (typeof toolInputSchemas)[T]
>;
export type ToolOutput<T extends ToolName> = z.infer<
  (typeof toolOutputSchemas)[T]
>;
