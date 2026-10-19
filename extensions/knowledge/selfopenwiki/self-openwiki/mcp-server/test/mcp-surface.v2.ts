import { describe, expect, test } from "vitest";
import {
  toolAnnotations,
  toolInputSchemas,
  toolOutputSchemas,
} from "../src/contracts.js";

const adaptedTools = [
  "openwiki_begin",
  "openwiki_submit_plan",
  "openwiki_next_page",
  "openwiki_inspect_page_claims",
  "openwiki_submit_page",
  "openwiki_finish",
] as const;

const expectedAnnotations = {
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
} as const;

describe("SelfOpenWiki adapted MCP surface", () => {
  test("defines strict schemas and annotations for every adapted tool", () => {
    for (const name of adaptedTools) {
      expect(toolInputSchemas[name]).toBeDefined();
      expect(toolOutputSchemas[name]).toBeDefined();
      expect(toolAnnotations[name]).toEqual(expectedAnnotations[name]);
    }
  });
});
