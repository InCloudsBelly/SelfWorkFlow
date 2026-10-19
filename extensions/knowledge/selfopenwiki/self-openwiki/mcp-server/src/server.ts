import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import type { ToolName } from "./contracts.js";
import {
  TOOL_NAMES,
  toolAnnotations,
  toolInputSchemas,
  toolOutputSchemas,
} from "./contracts.js";

export interface C7CapabilityGate {
  isToolVerified(name: ToolName): boolean;
}

export interface C7ToolRuntime {
  invoke(
    name: ToolName,
    input: unknown,
    signal?: AbortSignal,
  ): Promise<unknown>;
}

export const toolDescriptions: Record<ToolName, string> = {
  openwiki_status:
    "Read initialization, authentication, model, recovery, lock, path, and verified capability status without exposing credentials.",
  openwiki_read:
    "List formal Wiki pages or read up to 32 revision-bound Markdown pages without a provider or update transaction. Evidence remains semantically unverified.",
  openwiki_begin:
    "Start or resume the adapted personal Wiki page-job lifecycle for an explicit independent Git Wiki root.",
  openwiki_submit_plan:
    "Submit the canonical personal Wiki page plan and durably create its ordered PageJob queue.",
  openwiki_next_page:
    "Return the next personal Wiki PageJob, its Claim issues, and the isolated candidate write package.",
  openwiki_inspect_page_claims:
    "Return the complete current Claim set for one personal Wiki PageJob before intentional revision or retraction.",
  openwiki_submit_page:
    "Validate the assigned candidate Markdown page and submit only sparse Claim decisions; formal Wiki publication remains in C7.",
  openwiki_finish:
    "Finish a personal Wiki run through the C7 candidate receipt, independent review, CAS publication, and recovery gates.",
  openwiki_setup:
    "Start, complete, or cancel the first-run ChatGPT OAuth setup and verify the exact selected model and reasoning effort before initialization.",
  openwiki_prepare_sources:
    "Inspect supported local code and text documents, reject sensitive or unsupported files, and return an immutable confirmation-bound source manifest.",
  openwiki_list_skills:
    "List the mandatory KG_C7_Project_Wiki base Skill and trusted optional specialized Skills with their verified package hashes.",
  openwiki_query:
    "Run a read-only isolated OpenWiki model transaction against the current Wiki and optional confirmed source manifest without publishing changes.",
  openwiki_update:
    "Generate and validate a user-confirmed Wiki update, review a private candidate before one publication, and preserve crash recovery.",
  openwiki_begin_external_update:
    "Start or resume a hash-bound local external-Agent candidate transaction without invoking a provider model or requiring C7 authentication.",
  openwiki_finalize_external_update:
    "Prepare deterministic candidate review, submit a host-attested review receipt, report a recoverable host failure, or explicitly abort an external update.",
  openwiki_set_default_model:
    "Verify an explicitly confirmed model and reasoning effort with the current ChatGPT account, then atomically replace the runtime default.",
};

export function createC7McpServer(options: {
  capabilityGate: C7CapabilityGate;
  runtime: C7ToolRuntime;
}): Server {
  const server = new Server(
    { name: "self-openwiki", version: "0.1.2" },
    { capabilities: { tools: {} } },
  );
  const tools = TOOL_NAMES.map(toolDefinition);

  server.setRequestHandler(ListToolsRequestSchema, () => ({ tools }));
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    const name = parseToolName(request.params.name);
    if (name === undefined) {
      return protocolCallError("Unknown C7 OpenWiki tool.", "invalid_input");
    }
    const input = toolInputSchemas[name].safeParse(
      request.params.arguments ?? {},
    );
    if (!input.success) {
      return protocolCallError(
        "The tool input does not match its strict schema.",
        "invalid_input",
      );
    }
    try {
      const output =
        name === "openwiki_status" ||
        options.capabilityGate.isToolVerified(name)
          ? await options.runtime.invoke(name, input.data, extra.signal)
          : capabilityUnverified();
      const parsed = toolOutputSchemas[name].parse(output);
      if (parsed.ok === false) {
        return {
          content: [{ type: "text" as const, text: JSON.stringify(parsed) }],
          isError: true as const,
        };
      }
      return {
        content: [{ type: "text" as const, text: JSON.stringify(parsed) }],
        structuredContent: parsed,
      };
    } catch {
      return protocolCallError(
        "The tool failed closed because its structured result was invalid.",
        "internal_error",
      );
    }
  });
  return server;
}

function toolDefinition(name: ToolName): Tool {
  const inputSchema = {
    ...(z.toJSONSchema(toolInputSchemas[name]) as Tool["inputSchema"]),
    type: "object" as const,
  };
  const outputSchema = {
    ...(z.toJSONSchema(toolOutputSchemas[name]) as Tool["outputSchema"]),
    type: "object" as const,
  };
  return {
    annotations: toolAnnotations[name],
    description: toolDescriptions[name],
    inputSchema,
    name,
    outputSchema,
    title: name,
  };
}

function parseToolName(value: string): ToolName | undefined {
  return (TOOL_NAMES as readonly string[]).includes(value)
    ? (value as ToolName)
    : undefined;
}

function protocolCallError(
  message: string,
  code: "internal_error" | "invalid_input",
) {
  const failure = {
    error: {
      code,
      message,
      retryable: false,
    },
    ok: false,
    recovery: { action: code === "invalid_input" ? "none" : "retry" },
  } as const;
  return {
    content: [{ type: "text" as const, text: JSON.stringify(failure) }],
    isError: true as const,
  };
}

function capabilityUnverified() {
  return {
    error: {
      code: "capability_unverified",
      message:
        "This OpenWiki capability has no current matching local verification evidence.",
      retryable: false,
    },
    ok: false,
    recovery: {
      action: "none",
      message: "Run the repository capability verifier before using this tool.",
    },
  };
}
