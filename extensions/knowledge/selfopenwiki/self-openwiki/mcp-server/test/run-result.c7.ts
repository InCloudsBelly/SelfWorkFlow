import { describe, expect, test } from "vitest";
import {
  parseReviewModelResult,
  parseUpdateModelResult,
} from "../src/run-result.js";

const binding = {
  beforeWikiRootHash: `sha256:${"d".repeat(64)}`,
  confirmedWikiPaths: null,
  model: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
  operation: "update",
  skillAggregateHash: `sha256:${"a".repeat(64)}`,
  sourceManifestHash: null,
  sourceTreeHash: null,
  version: 1,
};

describe("bound model result protocol", () => {
  test("accepts strict update and review results with exact bindings", () => {
    const update = parseUpdateModelResult(
      {
        binding,
        classification: "provisional",
        issues: [
          {
            code: "owner_unverified",
            message: "Runtime owner still needs confirmation.",
            severity: "provisional",
          },
        ],
        questions: ["Who owns the runtime?"],
        summary: "Updated the architecture notes.",
        type: "update_result",
        version: 1,
      },
      binding,
    );
    const reviewBinding = {
      candidateId: "run-review-00000001",
      model: binding.model,
      reviewedRootHash: `sha256:${"b".repeat(64)}`,
      skillAggregateHash: binding.skillAggregateHash,
      sourceManifestHash: null,
      version: 1,
    };
    const review = parseReviewModelResult(
      {
        binding: reviewBinding,
        issues: [],
        type: "review_result",
        verdict: "pass",
        version: 1,
      },
      reviewBinding,
    );

    expect(update.classification).toBe("provisional");
    expect(review.verdict).toBe("pass");
  });

  test.each([
    [
      { ...binding, sourceTreeHash: `sha256:${"c".repeat(64)}` },
      "binding",
      "result_binding_mismatch",
    ],
    [binding, "unknown field", "result_schema_invalid"],
  ])(
    "classifies an invalid update result without weakening validation: %s",
    (actualBinding, mode, failureStage) => {
      const value: Record<string, unknown> = {
        binding: actualBinding,
        classification: "minor",
        issues: [],
        questions: [],
        summary: "Done.",
        type: "update_result",
        version: 1,
      };
      if (mode === "unknown field") value.invented = true;

      expect(() => parseUpdateModelResult(value, binding)).toThrowError(
        expect.objectContaining({ code: "result_invalid", failureStage }),
      );
    },
  );

  test("requires blocking updates and requires-user reviews to carry actionable questions/issues", () => {
    expect(() =>
      parseUpdateModelResult(
        {
          binding,
          classification: "blocking",
          issues: [],
          questions: [],
          summary: "Blocked.",
          type: "update_result",
          version: 1,
        },
        binding,
      ),
    ).toThrowError(expect.objectContaining({ code: "result_invalid" }));
  });

  test("binds the exact confirmed Wiki path set and rejects a valid-path substitution", () => {
    const confirmedBinding = {
      ...binding,
      confirmedWikiPaths: ["quickstart.md", "sources/kgpr-source-set.md"],
    };
    const value = {
      binding: confirmedBinding,
      classification: "minor" as const,
      issues: [],
      questions: [],
      summary: "Updated exactly the confirmed pages.",
      type: "update_result" as const,
      version: 1 as const,
    };

    expect(parseUpdateModelResult(value, confirmedBinding).binding).toEqual(
      confirmedBinding,
    );
    expect(() =>
      parseUpdateModelResult(value, {
        ...confirmedBinding,
        confirmedWikiPaths: ["quickstart.md"],
      }),
    ).toThrowError(
      expect.objectContaining({
        code: "result_invalid",
        failureStage: "result_binding_mismatch",
      }),
    );
  });
});
