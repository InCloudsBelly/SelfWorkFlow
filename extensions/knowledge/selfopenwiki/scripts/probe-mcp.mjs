#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { readStorageConfig } from "./storage-config.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(
  path.join(root, "self-openwiki/mcp-server/package.json"),
);
const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
const {
  StdioClientTransport,
} = require("@modelcontextprotocol/sdk/client/stdio.js");
const client = new Client({ name: "selfworkflow-wiki-doctor", version: "1.0" });
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [path.join(root, "self-openwiki/mcp-server/dist/index.js")],
  ...(process.env.SELF_OPENWIKI_CONFIG
    ? { env: { SELF_OPENWIKI_CONFIG: process.env.SELF_OPENWIKI_CONFIG } }
    : {}),
  stderr: "pipe",
});
transport.stderr?.on("data", () => {});
const deadline = setTimeout(() => {
  transport.close().catch(() => {});
}, 90_000);
const structured = (result) => {
  const value =
    result.structuredContent ??
    JSON.parse(result.content.find((item) => item.type === "text").text);
  if (result.isError || value.ok !== true)
    throw new Error("Wiki protocol failed.");
  return value;
};
try {
  const storage = await readStorageConfig(
    process.env.SELF_OPENWIKI_CONFIG
      ? { configPath: process.env.SELF_OPENWIKI_CONFIG }
      : {},
  );
  await client.connect(transport);
  const tools = (await client.listTools()).tools.map((tool) => tool.name);
  const status = structured(
    await client.callTool({ name: "openwiki_status", arguments: {} }),
  );
  if (
    status.version?.contractSchema !== 2 ||
    status.executionMode !== "external_agent" ||
    status.authRequired !== false ||
    status.externalAgent?.ready !== true ||
    status.paths?.wikiRoot !== storage.wikiRoot ||
    status.paths?.runtimeRoot !== storage.runtimeRoot ||
    status.paths?.openWikiRoot !== path.join(root, ".work/openwiki") ||
    ![
      "openwiki_read",
      "openwiki_begin",
      "openwiki_submit_plan",
      "openwiki_next_page",
      "openwiki_inspect_page_claims",
      "openwiki_submit_page",
      "openwiki_finish",
    ].every((name) => tools.includes(name)) ||
    !status.capabilities?.some((item) => item.id === "knowledge.read.safe")
  ) {
    throw new Error("Wiki readiness or binding mismatch.");
  }
  const index = structured(
    await client.callTool({ name: "openwiki_read", arguments: {} }),
  );
  const selected = index.pages.find(
    (page) => page.size > 0 && page.size <= 262_144,
  );
  if (selected) {
    const read = structured(
      await client.callTool({
        name: "openwiki_read",
        arguments: {
          paths: [selected.path],
          expectedWikiRevision: index.revision,
        },
      }),
    );
    if (
      read.knowledge.length !== 1 ||
      read.knowledge[0].contentHash !== selected.contentHash ||
      read.knowledge[0].revision !== index.revision
    )
      throw new Error("Wiki read binding mismatch.");
  }
  process.stdout.write(
    JSON.stringify({
      status: "wiki-ready",
      paths: status.paths,
      executionMode: status.executionMode,
      capabilityCount: status.capabilities.length,
      toolNames: tools,
      pageCount: index.pages.length,
      revision: index.revision,
      selectedPageRead: Boolean(selected),
      visualizer: status.visualizer,
    }) + "\n",
  );
} catch {
  process.stderr.write("Wiki live status/read verification failed.\n");
  process.exitCode = 1;
} finally {
  clearTimeout(deadline);
  await client.close().catch(() => {});
  await transport.close().catch(() => {});
}
