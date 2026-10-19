import { createRequire } from "node:module";
import { createC7McpServer } from "../../extensions/knowledge/selfopenwiki/self-openwiki/mcp-server/dist/server.js";

const require = createRequire(new URL("../../extensions/knowledge/selfopenwiki/self-openwiki/mcp-server/package.json", import.meta.url));
const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
const { InMemoryTransport } = require("@modelcontextprotocol/sdk/inMemory.js");
let input = "";
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
const server = createC7McpServer({
  capabilityGate: { isToolVerified: () => true },
  runtime: { invoke: async (_name, arguments_) => ({
    ok: true, status: "external_update_aborted", authRequired: false,
    executionMode: "external_agent", published: false, recovery: { action: "none" },
    transactionId: arguments_.transactionId, generation: 1, bindingHash: arguments_.bindingHash,
  }) },
});
const client = new Client({ name: "python-abort-contract-test", version: "1" });
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
try {
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  const result = await client.callTool(request);
  process.stdout.write(JSON.stringify(result.structuredContent ?? JSON.parse(result.content[0].text)));
} finally {
  await client.close();
  await server.close();
}
