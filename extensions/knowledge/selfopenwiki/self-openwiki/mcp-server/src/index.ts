#!/usr/bin/env node
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import path from "node:path";
import { bootstrapC7Runtime } from "./bootstrap.js";
import { createC7McpServer } from "./server.js";
// @ts-expect-error The repository-owned ESM config seam is JavaScript by design.
import { readStorageConfig } from "../../../scripts/storage-config.mjs";

try {
  // The MCP package is nested below the SelfOpenWiki host root. Keep the
  // repository root at `self-openwiki/` so config, skills, and the helper are
  // resolved from the same immutable source tree as the capability evidence.
  const repositoryRoot = path.resolve(import.meta.dirname, "../..");
  const hostRoot = path.resolve(repositoryRoot, "..");
  const storage = await readStorageConfig(
    process.env.SELF_OPENWIKI_CONFIG
      ? { configPath: process.env.SELF_OPENWIKI_CONFIG }
      : {},
  );
  const bootstrapped = await bootstrapC7Runtime({
    openWikiRoot:
      process.env.SELF_OPENWIKI_OPENWIKI_ROOT ??
      path.join(hostRoot, ".work", "openwiki"),
    repositoryRoot,
    runtimeDir: storage.runtimeRoot,
    wikiRoot: storage.wikiRoot,
    visualizerPath:
      process.env.SELF_OPENWIKI_VISUALIZER ?? path.join(hostRoot, "Visualize.bat"),
    ...(process.env.SELF_OPENWIKI_EVIDENCE_PATH
      ? { evidencePath: process.env.SELF_OPENWIKI_EVIDENCE_PATH }
      : {}),
  });
  const server = createC7McpServer({
    capabilityGate: bootstrapped.capabilityGate,
    runtime: bootstrapped.runtime,
  });
  await server.connect(new StdioServerTransport());
} catch {
  process.stderr.write("SelfOpenWiki MCP failed to start safely.\n");
  process.exitCode = 1;
}
