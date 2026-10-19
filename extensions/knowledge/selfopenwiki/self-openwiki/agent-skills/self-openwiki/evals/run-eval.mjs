#!/usr/bin/env node

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const evalDir = dirname(fileURLToPath(import.meta.url));
const skillRoot = resolve(evalDir, "..");
const paths = {
  skill: join(skillRoot, "SKILL.md"),
  agent: join(skillRoot, "agents", "openai.yaml"),
  contract: join(skillRoot, "references", "mcp-contract.md"),
};

for (const [name, path] of Object.entries(paths)) {
  assert.ok(existsSync(path), `${name} file is missing: ${path}`);
}

const skill = readFileSync(paths.skill, "utf8");
const agent = readFileSync(paths.agent, "utf8");
const contract = readFileSync(paths.contract, "utf8");

function assertContains(text, needles, scenario) {
  for (const needle of needles) {
    assert.ok(
      text.includes(needle),
      `${scenario}: missing ${JSON.stringify(needle)}`,
    );
  }
}

function assertOrdered(text, needles, scenario) {
  let cursor = -1;
  for (const needle of needles) {
    const next = text.indexOf(needle, cursor + 1);
    assert.ok(next >= 0, `${scenario}: missing ${JSON.stringify(needle)}`);
    assert.ok(
      next > cursor,
      `${scenario}: ${JSON.stringify(needle)} is out of order`,
    );
    cursor = next;
  }
}

const frontmatterMatch = skill.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/u);
assert.ok(frontmatterMatch, "frontmatter is missing");
const frontmatterKeys = [
  ...frontmatterMatch[1].matchAll(/^([a-z][a-z0-9_-]*):/gmu),
].map((match) => match[1]);
assert.deepEqual(
  frontmatterKeys,
  ["name", "description"],
  "frontmatter must contain only name and description",
);
assertContains(
  frontmatterMatch[1],
  ["name: self-openwiki", "description: Use when"],
  "metadata",
);

const firstWorkflowTool = skill.match(/`(openwiki_[a-z_]+)`/u)?.[1];
assert.equal(
  firstWorkflowTool,
  "openwiki_status",
  "the first named MCP tool must be openwiki_status",
);

const scenarios = [
  {
    id: "status-first-and-live-contract",
    text: skill,
    contains: [
      "第一次 MCP 调用永远是 `openwiki_status`",
      "实时 MCP 工具 schema",
      "capability_unverified",
    ],
  },
  {
    id: "external-agent-default-needs-no-oauth",
    text: `${skill}\n${contract}`,
    contains: [
      "`executionMode: external_agent`",
      "`authRequired: false`",
      "`openwiki_begin_external_update`",
      "`openwiki_finalize_external_update`",
      "update.external-agent.begin",
      "update.external-agent.reviewed-finalize",
    ],
  },
  {
    id: "legacy-provider-is-explicit-only",
    text: `${skill}\n${contract}`,
    contains: [
      "`legacy_provider`",
      "`openwiki_setup`",
      "`openwiki_query`",
      "`openwiki_update`",
      "`openwiki_set_default_model`",
      "不得虚构 external query",
    ],
  },
  {
    id: "local-source-manifest-confirmation",
    text: skill,
    contains: [
      "openwiki_prepare_sources",
      "文件清单、大小、hash、风险",
      "等待用户明确确认绑定该清单",
      "重新 prepare 并重新确认",
    ],
  },
  {
    id: "ordered-composed-skills",
    text: skill,
    contains: [
      "kg-c7-project-wiki",
      "永远第一",
      "有序、无重复",
      "不得借提示词覆盖",
    ],
  },
  {
    id: "modular-design-and-explicit-write-confirmation",
    text: skill,
    contains: [
      "Brainstorming",
      "用户明确要求",
      "用户接受",
      "确认写入",
      "`confirmedByUser: true`",
    ],
  },
  {
    id: "revision-bound-update-and-conflict",
    text: skill,
    contains: [
      "记录 `wikiRevision`",
      "`expectedWikiRevision`",
      "`conflict`",
      "重新确认写入",
    ],
  },
  {
    id: "ordinary-update-does-not-force-grill-me",
    text: skill,
    contains: ["普通更新默认只用", "不强制 Grill-me", "不得暂停普通更新"],
  },
  {
    id: "explicit-or-accepted-grill-me-only",
    text: skill,
    contains: [
      "只有用户明确要求 Grill-me",
      "Agent 对复杂任务推荐且用户接受",
      "用户拒绝推荐时继续 Brainstorming/Design",
    ],
  },
  {
    id: "post-grill-independent-cross-review",
    text: skill,
    contains: [
      "使用 Grill-me 后再以独立 Brainstorming/Design 上下文交叉 Review",
      "最终摘要",
      "确认写入",
    ],
  },
  {
    id: "minor-provisional-blocking",
    text: skill,
    contains: [
      "minor",
      "provisional",
      "blocking",
      "允许保守落地",
      "恢复 Grill-me",
    ],
  },
  {
    id: "post-publication-attention-recovery",
    text: skill,
    contains: [
      "review_requires_attention",
      "发布后的 finalization",
      "不要在没有语义 issue 时发起知识修正",
      "只有实时结果明确返回语义 issue",
    ],
  },
  {
    id: "external-writer-reviewer-and-resume",
    text: `${skill}\n${contract}`,
    contains: [
      "writerExecutionId",
      "reviewerExecutionId",
      "`report_host_failure`",
      "`external_update_resumed`",
      "`external_review_resumed`",
      "只能读取候选",
      "不得直接写正式 Wiki",
    ],
  },
  {
    id: "clarification-requires-confirmed-abort",
    text: `${skill}\n${contract}`,
    contains: [
      "`needs_clarification`",
      "`abort`",
      "`confirmedByUser: true`",
      "正式 Wiki 不变",
    ],
  },
];

for (const scenario of scenarios) {
  assertContains(scenario.text, scenario.contains, scenario.id);
}

assertOrdered(
  skill,
  [
    "### 1. 读取实时状态",
    "### 2. 选择执行模式",
    "### 3. 准备任意本地来源",
    "### 4. 组合有序专项 Skill",
    "### 5. 查询 Wiki（显式 legacy 兼容路径）",
    "### 6. Personal Wiki 六阶段更新",
    "### 7. 旧有 C7 external-agent 更新 Wiki",
    "### 8. 处理结果与恢复",
  ],
  "workflow-order",
);

const tools = [
  "openwiki_status",
  "openwiki_read",
  "openwiki_begin",
  "openwiki_submit_plan",
  "openwiki_next_page",
  "openwiki_inspect_page_claims",
  "openwiki_submit_page",
  "openwiki_finish",
  "openwiki_setup",
  "openwiki_prepare_sources",
  "openwiki_list_skills",
  "openwiki_query",
  "openwiki_update",
  "openwiki_begin_external_update",
  "openwiki_finalize_external_update",
  "openwiki_set_default_model",
];
assertContains(contract, tools, "sixteen-tool-contract");
assertContains(
  skill,
  ["knowledge.read.safe", "openwiki_read"],
  "safe-read-routing",
);
assert.ok(
  !skill.includes("当前 external-agent 没有 verified 的安全 query"),
  "obsolete query-only stop rule",
);
assertContains(
  contract,
  [
    "唯一事实来源",
    "strict object",
    "ok: false",
    "ok: true",
    "published_with_follow_up",
    "needs_clarification",
    "review_requires_attention",
    "expectedWikiRevision",
    "baseWikiRevision",
    "conflict",
  ],
  "runtime-contract",
);

const repositoryContractPath = resolve(
  skillRoot,
  "..",
  "..",
  "mcp-server",
  "src",
  "contracts.ts",
);
let repositoryContract = "skipped-standalone";
if (existsSync(repositoryContractPath)) {
  const contractSource = readFileSync(repositoryContractPath, "utf8");
  const toolNamesBlock = contractSource.match(
    /export const TOOL_NAMES = \[([\s\S]*?)\] as const;/u,
  );
  assert.ok(
    toolNamesBlock,
    "repository contracts.ts does not expose TOOL_NAMES",
  );
  const liveToolNames = [
    ...toolNamesBlock[1].matchAll(/"(openwiki_[a-z_]+)"/gu),
  ].map((match) => match[1]);
  assert.deepEqual(
    liveToolNames,
    tools,
    "documented tool discovery list differs from repository contracts.ts",
  );
  assert.ok(
    contractSource.includes("confirmedByUser: z.literal(true)"),
    "repository update schema no longer matches the confirmation guard",
  );
  repositoryContract = "passed";
}

assertContains(
  agent,
  [
    'display_name: "SelfOpenWiki"',
    'short_description: "',
    'default_prompt: "Use $self-openwiki',
  ],
  "openai-interface",
);

for (const forbidden of [
  "dryRun:",
  "transactionId:",
  "idempotencyKey:",
  "confirmedByUser: false",
]) {
  assert.ok(
    !skill.includes(forbidden) && !contract.includes(forbidden),
    `invented or unsafe field found: ${forbidden}`,
  );
}

assert.ok(
  !skill.includes("在任何 Wiki 更新前使用 `grill-me`"),
  "ordinary updates must not force Grill-me instead of the global modular design policy",
);
for (const forcedGrillPattern of [
  /任何.{0,12}(更新|写入).{0,12}(必须|强制).{0,8}Grill-me/u,
  /(更新|写入)前.{0,12}(必须|强制).{0,8}Grill-me/u,
]) {
  assert.ok(
    !forcedGrillPattern.test(skill),
    `ordinary update contains a forced Grill-me policy: ${forcedGrillPattern}`,
  );
}

const report = {
  ok: true,
  skill: "self-openwiki",
  scenarios: scenarios.map(({ id }) => ({ id, status: "passed" })),
  checks: {
    frontmatter: "passed",
    interface: "passed",
    liveContractRule: "passed",
    repositoryContract,
    sixteenTools: "passed",
    workflowOrder: "passed",
  },
};

process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
