import { readFile } from "node:fs/promises";
import { z } from "zod";
import {
  confirmedWikiPathsSchema,
  modelSelectionSchema,
  type ResultFailureStage,
} from "./contracts.js";

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const issueSchema = z.strictObject({
  code: z.string().regex(/^[a-z][a-z0-9_]{0,127}$/u),
  message: z.string().trim().min(1).max(4_096),
  page: z.string().min(1).max(32_768).optional(),
  severity: z.enum(["minor", "provisional", "blocking"]),
});
export const updateBindingSchema = z.strictObject({
  beforeWikiRootHash: hashSchema,
  confirmedWikiPaths: confirmedWikiPathsSchema.nullable(),
  model: modelSelectionSchema,
  operation: z.enum(["repair", "update"]),
  skillAggregateHash: hashSchema,
  sourceManifestHash: hashSchema.nullable(),
  sourceTreeHash: hashSchema.nullable(),
  version: z.literal(1),
});
export const reviewBindingSchema = z.strictObject({
  candidateId: z.string().regex(/^run-[A-Za-z0-9._:-]{8,160}$/u),
  model: modelSelectionSchema,
  reviewedRootHash: hashSchema,
  skillAggregateHash: hashSchema,
  sourceManifestHash: hashSchema.nullable(),
  version: z.literal(1),
});

export const UPDATE_RESULT_CONTRACT = [
  "Write one JSON object with no Markdown fence or surrounding text.",
  "Top-level keys must be exactly binding, classification, issues, questions, summary, type, version. Set type to update_result and version to 1. Copy /_c7-control/in/binding.json exactly into binding.",
  "classification must be minor, provisional, or blocking. summary must contain 1 to 16384 characters.",
  "Each issue permits exactly code, message, optional page, and severity. code must match ^[a-z][a-z0-9_]{0,127}$; message must contain 1 to 4096 characters; page, when present, must contain 1 to 32768 characters; severity must be minor, provisional, or blocking. issues may contain at most 256 entries. Do not add any other top-level or issue fields.",
  "questions may contain at most 64 strings, each containing 1 to 4096 characters.",
  "minor requires zero questions and every issue must be minor; provisional requires at least one provisional issue; blocking requires at least one blocking issue and at least one question.",
  'Exact shape: {"binding":<exact binding object>,"classification":"minor|provisional|blocking","issues":[{"code":"snake_case","message":"specific finding","page":"optional/wiki.md","severity":"minor|provisional|blocking"}],"questions":["specific blocking question"],"summary":"concise completed-work summary","type":"update_result","version":1}',
].join("\n");

export const REVIEW_RESULT_CONTRACT = [
  "Write one JSON object with no Markdown fence or surrounding text. Copy the review object from /_c7-control/in/binding.json exactly into result.binding.",
  "Top-level keys must be exactly binding, issues, type, verdict, version. Set type to review_result and version to 1. Verdict must be pass, follow_up, auto_fixable, or requires_user.",
  "Each issue permits exactly code, message, optional page, and severity. code must match ^[a-z][a-z0-9_]{0,127}$; message must contain 1 to 4096 characters; page, when present, must contain 1 to 32768 characters; severity must be minor, provisional, or blocking. Do not add any other top-level or issue fields.",
  "pass requires zero issues; follow_up requires at least one provisional issue and no blocking issue; auto_fixable requires at least one issue and every issue must be minor; requires_user requires at least one issue.",
  'Exact shape: {"binding":<exact review object>,"issues":[{"code":"snake_case","message":"specific finding","page":"optional/wiki.md","severity":"minor|provisional|blocking"}],"type":"review_result","verdict":"pass|follow_up|auto_fixable|requires_user","version":1}',
].join("\n");

const updateResultSchema = z
  .strictObject({
    binding: updateBindingSchema,
    classification: z.enum(["minor", "provisional", "blocking"]),
    issues: z.array(issueSchema).max(256),
    questions: z.array(z.string().trim().min(1).max(4_096)).max(64),
    summary: z.string().trim().min(1).max(16_384),
    type: z.literal("update_result"),
    version: z.literal(1),
  })
  .superRefine((result, context) => {
    if (
      result.classification === "minor" &&
      (result.questions.length !== 0 ||
        result.issues.some((issue) => issue.severity !== "minor"))
    ) {
      context.addIssue({
        code: "custom",
        message: "minor result is inconsistent",
      });
    }
    if (
      result.classification === "provisional" &&
      !result.issues.some((issue) => issue.severity === "provisional")
    ) {
      context.addIssue({
        code: "custom",
        message: "provisional result needs a provisional issue",
      });
    }
    if (
      result.classification === "blocking" &&
      (result.questions.length === 0 ||
        !result.issues.some((issue) => issue.severity === "blocking"))
    ) {
      context.addIssue({
        code: "custom",
        message: "blocking result needs a blocking issue and a question",
      });
    }
  });

const reviewResultSchema = z
  .strictObject({
    binding: reviewBindingSchema,
    issues: z.array(issueSchema).max(256),
    type: z.literal("review_result"),
    verdict: z.enum(["pass", "follow_up", "auto_fixable", "requires_user"]),
    version: z.literal(1),
  })
  .superRefine((result, context) => {
    const severities = new Set(result.issues.map((issue) => issue.severity));
    const valid =
      result.verdict === "pass"
        ? result.issues.length === 0
        : result.verdict === "follow_up"
          ? severities.has("provisional") && !severities.has("blocking")
          : result.verdict === "auto_fixable"
            ? result.issues.length > 0 &&
              [...severities].every((severity) => severity === "minor")
            : result.issues.length > 0;
    if (!valid) {
      context.addIssue({
        code: "custom",
        message: "review verdict is inconsistent",
      });
    }
  });

export type UpdateModelResult = z.infer<typeof updateResultSchema>;
export type ReviewModelResult = z.infer<typeof reviewResultSchema>;

export class C7RunResultError extends Error {
  constructor(
    readonly code: "result_invalid",
    message: string,
    readonly failureStage: ResultFailureStage,
  ) {
    super(message);
    this.name = "C7RunResultError";
  }
}

export function parseUpdateModelResult(
  value: unknown,
  expectedBinding: unknown,
): UpdateModelResult {
  const result = updateResultSchema.safeParse(value);
  const expected = updateBindingSchema.safeParse(expectedBinding);
  if (!result.success) throw invalidResult("result_schema_invalid");
  if (
    !expected.success ||
    stableJson(result.data.binding) !== stableJson(expected.data)
  )
    throw invalidResult("result_binding_mismatch");
  return result.data;
}

export function parseReviewModelResult(
  value: unknown,
  expectedBinding: unknown,
): ReviewModelResult {
  const result = reviewResultSchema.safeParse(value);
  const expected = reviewBindingSchema.safeParse(expectedBinding);
  if (!result.success) throw invalidResult("result_schema_invalid");
  if (
    !expected.success ||
    stableJson(result.data.binding) !== stableJson(expected.data)
  )
    throw invalidResult("result_binding_mismatch");
  return result.data;
}

export async function readModelResultJson(filePath: string): Promise<unknown> {
  let text: string;
  try {
    text = await readFile(filePath, "utf8");
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") {
      throw invalidResult("result_missing");
    }
    throw error;
  }
  try {
    return JSON.parse(text);
  } catch {
    throw invalidResult("result_json_invalid");
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

function invalidResult(failureStage: ResultFailureStage): C7RunResultError {
  return new C7RunResultError(
    "result_invalid",
    "The model result did not satisfy the strict transaction protocol.",
    failureStage,
  );
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}
