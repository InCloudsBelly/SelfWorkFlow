#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { existsSync, realpathSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { runSetup } from "./setup.mjs";
import { runInstall } from "./install.mjs";
import { runVisualize } from "./visualize.mjs";
import { FROZEN_UPSTREAM_COMMIT } from "./materialize-openwiki.mjs";

const moduleRoot = realpathSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));
const help = `SelfWorkflow 可选 Wiki 模块

Manage_SelfWorkFlow_Wiki.bat inspect
Manage_SelfWorkFlow_Wiki.bat setup --with-mcp
Manage_SelfWorkFlow_Wiki.bat install --wiki-root <absolute-root> --confirm-data-safety [--confirm-git-authorization]
Manage_SelfWorkFlow_Wiki.bat visualize --wiki-root <absolute-root>
Manage_SelfWorkFlow_Wiki.bat register [--confirm-plan-hash <returned-hash>]
Manage_SelfWorkFlow_Wiki.bat doctor

阅读 Wiki 不依赖旧运行区。setup 构建工具；install 绑定本机已有 Wiki。
inspect 只检查源码区，不代表宿主 MCP 已切换。
`;

function git(root, args) {
  const env = { ...process.env, GIT_OPTIONAL_LOCKS: "0", GIT_TERMINAL_PROMPT: "0", GIT_CONFIG_NOSYSTEM: "1" };
  for (const key of ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"]) delete env[key];
  return execFileSync("git", args, { cwd: root, env, encoding: "utf8", windowsHide: true, stdio: ["ignore", "pipe", "pipe"] }).trim();
}

export async function inspectModule() {
  const report = {
    moduleRoot, status: "setup-required", hostRegistration: "unverified",
    paths: {
      setup: path.join(moduleRoot, "Setup.bat"),
      install: path.join(moduleRoot, "Install.bat"),
      visualizer: path.join(moduleRoot, "Visualize.bat"),
      mcpEntry: path.join(moduleRoot, "self-openwiki/mcp-server/dist/index.js"),
    },
  };
  try {
    const sourceRoot = realpathSync(git(moduleRoot, ["rev-parse", "--show-toplevel"]));
    const prefix = path.relative(sourceRoot, moduleRoot).split(path.sep).join("/");
    for (const relative of ["upstream/openwiki", "visualizer/zxh_wiki_viewer"]) {
      const upstream = path.join(moduleRoot, relative);
      const listing = git(sourceRoot, ["ls-files", "--stage", "--", `${prefix}/${relative}`]);
      const [mode, commit] = listing.split(/\s+/u);
      if (mode !== "160000" || git(upstream, ["rev-parse", "HEAD"]) !== commit || git(upstream, ["status", "--porcelain", "--untracked-files=all"]) !== "") {
        return { ...report, reason: "upstream-pin-invalid" };
      }
      if (relative === "upstream/openwiki" && commit !== FROZEN_UPSTREAM_COMMIT) return { ...report, reason: "upstream-pin-invalid" };
    }
    const manifest = JSON.parse(readFileSync(path.join(moduleRoot, "patches/openwiki/manifest.json"), "utf8"));
    if (manifest.upstream.commit !== FROZEN_UPSTREAM_COMMIT) return { ...report, reason: "upstream-pin-invalid" };
    const repositoryRoot = path.join(moduleRoot, "self-openwiki");
    const openWikiRoot = path.join(moduleRoot, ".work/openwiki");
    const evidencePath = path.join(repositoryRoot, "runtime/verified-capabilities.json");
    if (![report.paths.mcpEntry, path.join(repositoryRoot, "win32-helper/dist/SelfOpenWiki.Win32Helper.exe"), evidencePath, path.join(openWikiRoot, "dist/cli/cli.js"), path.join(moduleRoot, "visualizer/zxh_wiki_viewer/.next/BUILD_ID")].every(existsSync)) {
      return { ...report, reason: "build-required" };
    }
    const require = createRequire(path.join(repositoryRoot, "mcp-server/package.json"));
    const lock = require("yaml").parse(readFileSync(path.join(sourceRoot, "dependencies/locks/selfopenwiki.lock.yaml"), "utf8"));
    const expected = [
      ["openwiki", "upstream/openwiki", "https://github.com/langchain-ai/openwiki.git"],
      ["wiki-viewer", "visualizer/zxh_wiki_viewer", "https://github.com/InCloudsBelly/zxh_wiki_viewer.git"],
    ];
    if (lock.schemaVersion !== 1 || lock.moduleRoot !== prefix || !Array.isArray(lock.upstreams) || lock.upstreams.length !== 2 || lock.runtimeProfiles?.join(",") !== "knowledge") return { ...report, reason: "module-lock-invalid" };
    for (const [id, relative, url] of expected) {
      const declared = lock.upstreams.find(item => item.id === id);
      if (declared?.path !== `${prefix}/${relative}` || declared.url !== url || declared.revisionSource !== "parent-gitlink" || git(sourceRoot, ["config", "--file", path.join(sourceRoot, ".gitmodules"), "--get", `submodule.${prefix}/${relative}.url`]) !== url) return { ...report, reason: "module-lock-invalid" };
    }
    const { loadRuntimeCapabilityGate } = await import(pathToFileURL(path.join(repositoryRoot, "mcp-server/dist/capabilities.js")).href);
    const { loadPersonalCompatibilityManifest, assertPersonalCompatibility } = await import(pathToFileURL(path.join(repositoryRoot, "mcp-server/dist/personal-skill-adapter.js")).href);
    const { TOOL_NAMES } = await import(pathToFileURL(path.join(repositoryRoot, "mcp-server/dist/contracts.js")).href);
    const gate = await loadRuntimeCapabilityGate({ repositoryRoot, openWikiRoot, evidencePath });
    if (!["openwiki_status", "openwiki_begin", "openwiki_submit_plan", "openwiki_next_page", "openwiki_inspect_page_claims", "openwiki_submit_page", "openwiki_finish"].every(name => gate.isToolVerified(name))) {
      return { ...report, reason: "evidence-stale" };
    }
    await assertPersonalCompatibility(await loadPersonalCompatibilityManifest(repositoryRoot), FROZEN_UPSTREAM_COMMIT, TOOL_NAMES, { repositoryRoot, openWikiRoot });
    return { ...report, status: "source-ready" };
  } catch {
    return { ...report, reason: "source-or-evidence-invalid" };
  }
}

export async function runWikiCommand(argv) {
  const [action, ...args] = argv;
  if (action === undefined || action === "--help" || action === "help") {
    process.stdout.write(help);
    return 0;
  }
  if (action === "inspect" && args.length === 0) {
    process.stdout.write(JSON.stringify(await inspectModule()) + "\n");
    return 0;
  }
  if (action === "setup") return runSetup(args);
  if (action === "install") return runInstall(args);
  if (action === "visualize") return runVisualize(args);
  process.stderr.write("Wiki action invalid. Run Manage_SelfWorkFlow_Wiki.bat --help.\n");
  return 2;
}

if (process.argv[1] !== undefined && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { process.exitCode = await runWikiCommand(process.argv.slice(2)); }
  catch { process.stderr.write("SelfWorkflow Wiki operation failed.\n"); process.exitCode = 2; }
}
