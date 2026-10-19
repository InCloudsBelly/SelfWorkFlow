import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, describe, expect, test, vi } from "vitest";
import { TOOL_NAMES, toolAnnotations } from "../src/contracts.js";
import {
  createC7McpServer,
  type C7CapabilityGate,
  type C7ToolRuntime,
} from "../src/server.js";

const clients: Client[] = [];

function textContent(result: unknown): string {
  const content =
    typeof result === "object" && result !== null && "content" in result
      ? result.content
      : undefined;
  const first = Array.isArray(content) ? content[0] : undefined;
  if (
    first === null ||
    typeof first !== "object" ||
    !("text" in first) ||
    typeof first.text !== "string"
  ) {
    throw new Error("Expected an MCP text content block.");
  }
  return first.text;
}

afterEach(async () => {
  await Promise.all(clients.splice(0).map((client) => client.close()));
});

describe("C7 OpenWiki MCP server", () => {
  test("discovers exactly sixteen strict tools with the declared annotations", async () => {
    const fixture = await connectFixture();

    const listed = await fixture.client.listTools();

    expect(listed.tools.map((tool) => tool.name)).toEqual(TOOL_NAMES);
    for (const tool of listed.tools) {
      expect(tool.description).toEqual(expect.any(String));
      expect(tool.description!.length).toBeGreaterThan(30);
      expect(tool.inputSchema.type).toBe("object");
      const alternatives = [
        ...((tool.inputSchema.oneOf as Array<Record<string, unknown>>) ?? []),
        ...((tool.inputSchema.anyOf as Array<Record<string, unknown>>) ?? []),
      ];
      expect(
        tool.inputSchema.additionalProperties === false ||
          (alternatives.length > 0 &&
            alternatives.every(
              (schema) => schema.additionalProperties === false,
            )),
      ).toBe(true);
      expect(tool.outputSchema).toEqual(
        expect.objectContaining({ type: "object" }),
      );
      expect(tool.annotations).toEqual(
        toolAnnotations[tool.name as keyof typeof toolAnnotations],
      );
    }
    const update = listed.tools.find((tool) => tool.name === "openwiki_update");
    expect(update?.description).toContain(
      "review a private candidate before one publication",
    );
    const revisionSchemas = collectNamedProperties(
      update?.outputSchema,
      "baseWikiRevision",
    );
    expect(revisionSchemas.length).toBeGreaterThan(0);
    for (const schema of revisionSchemas) {
      expect(JSON.stringify(schema)).not.toContain('"null"');
    }
    const begin = listed.tools.find(
      (tool) => tool.name === "openwiki_begin_external_update",
    );
    const finalize = listed.tools.find(
      (tool) => tool.name === "openwiki_finalize_external_update",
    );
    expect(begin?.description).toContain("local external-Agent candidate");
    expect(finalize?.description).toContain("host-attested review receipt");
    expect(begin?.annotations).toEqual({
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: true,
      openWorldHint: false,
    });
    expect(finalize?.annotations).toEqual(begin?.annotations);
  });

  test("blocks unverified capabilities at the handler boundary", async () => {
    const runtime: C7ToolRuntime = { invoke: vi.fn() };
    const fixture = await connectFixture({
      gate: { isToolVerified: (name) => name === "openwiki_status" },
      runtime,
    });

    const result = await fixture.client.callTool({
      name: "openwiki_query",
      arguments: {
        executionMode: "legacy_provider",
        instruction: "What changed?",
      },
    });

    expect(result.isError).toBe(true);
    expect(result.structuredContent).toBeUndefined();
    expect(JSON.parse(textContent(result))).toEqual(
      expect.objectContaining({
        error: expect.objectContaining({ code: "capability_unverified" }),
        ok: false,
      }),
    );
    expect(runtime.invoke).not.toHaveBeenCalled();
  });

  test.each([
    [
      "openwiki_begin_external_update",
      {
        action: "start",
        requestId: "request-12345678",
        confirmedByUser: true,
        instruction: "Update the confirmed page.",
        confirmedWikiPaths: ["architecture/external-agent.md"],
        expectedWikiRevision: `sha256:${"a".repeat(64)}`,
      },
    ],
    [
      "openwiki_finalize_external_update",
      {
        action: "abort",
        transactionId: "tx-12345678",
        bindingHash: `sha256:${"b".repeat(64)}`,
        confirmedByUser: true,
      },
    ],
  ] as const)(
    "gates the new %s handler before runtime dispatch",
    async (name, args) => {
      const runtime: C7ToolRuntime = { invoke: vi.fn() };
      const fixture = await connectFixture({
        gate: { isToolVerified: () => false },
        runtime,
      });

      const result = await fixture.client.callTool({
        name,
        arguments: args,
      });

      expect(result.isError).toBe(true);
      expect(result.structuredContent).toBeUndefined();
      expect(JSON.parse(textContent(result))).toEqual(
        expect.objectContaining({
          error: expect.objectContaining({ code: "capability_unverified" }),
          ok: false,
        }),
      );
      expect(runtime.invoke).not.toHaveBeenCalled();
    },
  );

  test("validates runtime output before returning structured content", async () => {
    const runtime: C7ToolRuntime = {
      invoke: vi.fn().mockResolvedValue({ ok: true, status: "invented" }),
    };
    const fixture = await connectFixture({ runtime });

    const result = await fixture.client.callTool({
      name: "openwiki_status",
      arguments: {},
    });
    expect(result.isError).toBe(true);
    expect(result.structuredContent).toBeUndefined();
  });

  test("returns a whitelisted result failure stage to the MCP caller", async () => {
    const runtime: C7ToolRuntime = {
      invoke: vi.fn().mockResolvedValue({
        error: {
          code: "process_failure",
          details: { failureStage: "result_schema_invalid" },
          message: "The isolated OpenWiki model process failed.",
          retryable: true,
        },
        ok: false,
        recovery: { action: "retry" },
      }),
    };
    const fixture = await connectFixture({ runtime });

    const result = await fixture.client.callTool({
      name: "openwiki_query",
      arguments: {
        executionMode: "legacy_provider",
        instruction: "Read the current Wiki.",
      },
    });

    expect(result.isError).toBe(true);
    expect(result.structuredContent).toBeUndefined();
    expect(JSON.parse(textContent(result))).toEqual(
      expect.objectContaining({
        error: expect.objectContaining({
          code: "process_failure",
          details: { failureStage: "result_schema_invalid" },
        }),
      }),
    );
  });

  test("rejects an unknown result failure stage at the MCP boundary", async () => {
    const runtime: C7ToolRuntime = {
      invoke: vi.fn().mockResolvedValue({
        error: {
          code: "process_failure",
          details: { failureStage: "result_contents_with_secrets" },
          message: "The isolated OpenWiki model process failed.",
          retryable: true,
        },
        ok: false,
        recovery: { action: "retry" },
      }),
    };
    const fixture = await connectFixture({ runtime });

    const result = await fixture.client.callTool({
      name: "openwiki_query",
      arguments: {
        executionMode: "legacy_provider",
        instruction: "Read the current Wiki.",
      },
    });

    expect(result.isError).toBe(true);
    expect(result.structuredContent).toBeUndefined();
  });

  test("rejects unknown input fields before invoking runtime", async () => {
    const runtime: C7ToolRuntime = { invoke: vi.fn() };
    const fixture = await connectFixture({ runtime });

    const result = await fixture.client.callTool({
      name: "openwiki_status",
      arguments: { surprise: true },
    });
    expect(result.isError).toBe(true);
    expect(runtime.invoke).not.toHaveBeenCalled();
  });

  test("returns protocol input failures as a JSON error envelope", async () => {
    const runtime: C7ToolRuntime = { invoke: vi.fn() };
    const fixture = await connectFixture({ runtime });

    const result = await fixture.client.callTool({
      name: "openwiki_begin",
      arguments: { wikiRoot: "relative", mode: "update" },
    });

    expect(result.isError).toBe(true);
    expect(result.structuredContent).toBeUndefined();
    expect(JSON.parse(textContent(result))).toEqual({
      error: {
        code: "invalid_input",
        message: "The tool input does not match its strict schema.",
        retryable: false,
      },
      ok: false,
      recovery: { action: "none" },
    });
    expect(runtime.invoke).not.toHaveBeenCalled();
  });

  test("rejects an update without an expected Wiki revision before invoking runtime", async () => {
    const runtime: C7ToolRuntime = { invoke: vi.fn() };
    const fixture = await connectFixture({ runtime });

    const result = await fixture.client.callTool({
      name: "openwiki_update",
      arguments: {
        executionMode: "legacy_provider",
        confirmedByUser: true,
        instruction: "Update.",
      },
    });

    expect(result.isError).toBe(true);
    expect(runtime.invoke).not.toHaveBeenCalled();
  });

  test("returns a schema-valid stale revision conflict from the tool boundary", async () => {
    const hash = `sha256:${"a".repeat(64)}`;
    const runtime: C7ToolRuntime = {
      invoke: vi.fn().mockResolvedValue({
        baseWikiRevision: hash,
        changes: [],
        failure: {
          code: "wiki_conflict",
          message: "The formal Wiki changed after confirmation.",
          retryable: true,
        },
        model: {
          providerAccepted: false,
          requested: { model: "gpt-5.6-sol", reasoningEffort: "xhigh" },
          sent: null,
        },
        ok: true,
        published: false,
        questions: [],
        recovery: { action: "retry" },
        recoveryState: "clean",
        review: { rounds: 0, status: "not_run" },
        selectedSkills: [],
        skillAggregateHash: `sha256:${"c".repeat(64)}`,
        status: "conflict",
        validation: {
          checks: [
            { id: "wiki_revision", message: "Stale.", status: "failed" },
          ],
          passed: false,
        },
      }),
    };
    const fixture = await connectFixture({ runtime });

    const result = await fixture.client.callTool({
      name: "openwiki_update",
      arguments: {
        executionMode: "legacy_provider",
        confirmedByUser: true,
        expectedWikiRevision: `sha256:${"b".repeat(64)}`,
        instruction: "Update.",
      },
    });

    expect(result.isError).not.toBe(true);
    expect(result.structuredContent).toEqual(
      expect.objectContaining({ baseWikiRevision: hash, status: "conflict" }),
    );
    expect(runtime.invoke).toHaveBeenCalledTimes(1);
  });
});

function collectNamedProperties(
  value: unknown,
  name: string,
): Array<Record<string, unknown>> {
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectNamedProperties(item, name));
  }
  if (typeof value !== "object" || value === null) return [];
  const record = value as Record<string, unknown>;
  const properties = record.properties;
  const direct =
    typeof properties === "object" &&
    properties !== null &&
    typeof (properties as Record<string, unknown>)[name] === "object" &&
    (properties as Record<string, unknown>)[name] !== null
      ? [
          (properties as Record<string, unknown>)[name] as Record<
            string,
            unknown
          >,
        ]
      : [];
  return [
    ...direct,
    ...Object.values(record).flatMap((item) =>
      collectNamedProperties(item, name),
    ),
  ];
}

async function connectFixture(
  options: {
    gate?: C7CapabilityGate;
    runtime?: C7ToolRuntime;
  } = {},
) {
  const [clientTransport, serverTransport] =
    InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "c7-test-client", version: "1.0.0" });
  clients.push(client);
  const server = createC7McpServer({
    capabilityGate:
      options.gate ??
      ({ isToolVerified: () => true } satisfies C7CapabilityGate),
    runtime: options.runtime ?? { invoke: vi.fn() },
  });
  await Promise.all([
    server.connect(serverTransport),
    client.connect(clientTransport),
  ]);
  return { client, server };
}
