import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createSetupPlan } from "../scripts/setup.mjs";

test("MCP setup refreshes module compatibility before capability verification", () => {
  const plan = createSetupPlan({ repositoryRoot: path.resolve("."), withMcp: true });
  const refresh = plan.findIndex(step => step.args.includes("scripts/refresh-compatibility.mjs"));
  const verify = plan.findIndex(step => step.args.includes("self-openwiki/scripts/verify-capabilities.mts"));
  assert.ok(refresh >= 0, "copied source requires a fresh parent binding");
  assert.ok(refresh < verify, "capability verification must consume the refreshed binding");
});

test("OpenWiki builds do not run the upstream implicit clean hook", () => {
  const plan = createSetupPlan({ repositoryRoot: path.resolve("."), withMcp: true });
  const build = plan.find(step => step.label === "build official OpenWiki");
  assert.deepEqual(build.args.slice(1), ["--config.enable-pre-post-scripts=false", "run", "build"]);
  const verifier = readFileSync(new URL("../self-openwiki/scripts/verify-capabilities.mts", import.meta.url), "utf8");
  assert.ok(verifier.includes('["--config.enable-pre-post-scripts=false", "run", "build"], openWikiRoot'));
});
