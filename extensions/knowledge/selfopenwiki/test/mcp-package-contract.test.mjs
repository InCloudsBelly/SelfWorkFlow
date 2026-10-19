import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";

const packageRoot = path.resolve("self-openwiki", "mcp-server");

async function requirePath(relative) {
  await access(path.join(packageRoot, relative));
}

test("SelfOpenWiki owns an independent MCP package outside the upstream submodule", async () => {
  await requirePath("package.json");
  await requirePath("src/index.ts");
  await requirePath("src/server.ts");
  const packageJson = JSON.parse(await readFile(path.join(packageRoot, "package.json"), "utf8"));
  assert.equal(packageJson.name, "self-openwiki-mcp");
  assert.equal(packageJson.bin["self-openwiki-mcp"], "dist/index.js");
  assert.equal(packageJson.dependencies["@modelcontextprotocol/sdk"], "1.30.0");
});

test("the public MCP entry binds the configured Wiki root instead of an embedded wiki child", async () => {
  const entry = await readFile(path.join(packageRoot, "src/index.ts"), "utf8");
  assert.match(entry, /SELF_OPENWIKI_CONFIG/u);
  assert.doesNotMatch(entry, /C7_OPENWIKI_RUNTIME_DIR|runtimeDir,\s*"wiki"/u);
  const bootstrap = await readFile(path.join(packageRoot, "src/bootstrap.ts"), "utf8");
  assert.match(bootstrap, /wikiRoot\?: string/u);
  assert.match(bootstrap, /options\.wikiRoot/u);
});
