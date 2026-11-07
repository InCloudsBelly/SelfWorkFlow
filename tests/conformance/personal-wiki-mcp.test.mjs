import assert from "node:assert/strict";
import {
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { bindPersonalWikiMcp } from "../../scripts/personal-wiki-mcp.mjs";

const object = (properties, required = Object.keys(properties)) => ({
  type: "object",
  additionalProperties: false,
  properties,
  required,
});
const schemas = {
  openwiki_status: object({}),
  openwiki_prepare_sources: object({
    paths: { type: "array", minItems: 1, items: { type: "string" } },
  }),
  openwiki_begin: object({
    mode: { enum: ["init", "update"] },
    wikiRoot: { type: "string" },
  }),
  openwiki_submit_plan: object({ runId: { type: "string" } }),
  openwiki_next_page: object({ runId: { type: "string" } }),
  openwiki_submit_page: object({ runId: { type: "string" } }),
  openwiki_finish: object(
    {
      runId: { type: "string" },
      reviewReceipt: object({
        reviewerExecutionId: {
          type: "string",
          minLength: 8,
          maxLength: 160,
          pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        },
      }),
    },
    ["runId"],
  ),
};

const response = (status, extra = {}) => ({
  structuredContent: { ok: true, status, ...extra },
});
const rejected = (code, action, retryable = false) => ({
  isError: true,
  content: [
    {
      type: "text",
      text: JSON.stringify({
        ok: false,
        error: { code, retryable, message: "kept in the result artifact" },
        recovery: { action },
      }),
    },
  ],
});
const status = response("status", {
  version: { contractSchema: 2, mcpServer: "0.1.2" },
  executionMode: "external_agent",
  authRequired: false,
  externalAgent: { ready: true },
  paths: {
    wikiRoot: path.resolve("fixture-wiki"),
    runtimeRoot: path.resolve("fixture-wiki-runtime"),
    openWikiRoot: path.resolve("fixture-openwiki"),
  },
});

function fixture(invoke, statusReply = status) {
  const calls = [];
  const client = {
    async callTool({ name, arguments: args }) {
      calls.push({ name, args });
      return name === "openwiki_status" ? statusReply : invoke(name, args);
    },
    async listTools() {
      return {
        tools: Object.entries(schemas).map(([name, inputSchema]) => ({
          name,
          inputSchema,
        })),
      };
    },
    async close() {},
  };
  return { client, calls };
}

async function artifactFolder(t) {
  const root = await realpath(tmpdir());
  const folder = await mkdtemp(path.join(root, "wiki-mcp-"));
  t.after(async () => {
    const resolved = await realpath(folder);
    assert.equal(path.dirname(resolved), root);
    await rm(resolved, { recursive: true });
  });
  return folder;
}

async function request(directory, file, name, args) {
  const filePath = path.join(directory, file + ".request.json");
  await writeFile(filePath, JSON.stringify({ name, args }), { flag: "wx" });
  return filePath;
}

test("preflights source paths and live receipt shape without changing authority", async (t) => {
  const folder = await artifactFolder(t);
  const { client, calls } = fixture((name) =>
    name === "openwiki_prepare_sources"
      ? rejected("source_rejected", "none")
      : response("repair_ready", { nextAction: "resume" }),
  );
  const session = await bindPersonalWikiMcp(client);
  const relative = await request(
    folder,
    "lumen-bad",
    "openwiki_prepare_sources",
    {
      paths: ["Engine/Renderer.cpp"],
    },
  );
  await assert.rejects(session.call(relative), /paths\[0\].*absolute/);
  const malformed = await request(folder, "kgpr-bad", "openwiki_finish", {
    runId: "run-fixture",
    reviewReceipt: { reviewerExecutionId: "/root/kgpr_review" },
  });
  await assert.rejects(session.call(malformed), /reviewerExecutionId/);
  assert.deepEqual(
    calls.map(({ name }) => name),
    ["openwiki_status"],
  );
  await assert.rejects(readFile(path.join(folder, "kgpr-bad.result.json")), {
    code: "ENOENT",
  });

  const permittedShape = await request(
    folder,
    "lumen-absolute",
    "openwiki_prepare_sources",
    {
      paths: [path.resolve(folder, "denied.cpp")],
    },
  );
  const denial = await session.call(permittedShape);
  assert.equal(denial.errorCode, "source_rejected");
  assert.equal(denial.action, "check-source-policy");
  const valid = await request(folder, "kgpr-fixed", "openwiki_finish", {
    runId: "run-fixture",
    reviewReceipt: { reviewerExecutionId: "root:kgpr_review" },
  });
  const repair = await session.call(valid);
  assert.equal(repair.status, "repair_ready");
  assert.equal(repair.nextAction, "resume");
  assert.equal(repair.published, false);
  assert.equal(
    calls.at(-1).args.reviewReceipt.reviewerExecutionId,
    "root:kgpr_review",
  );
});

test("stores full evidence once and reuses a result without redispatch", async (t) => {
  const folder = await artifactFolder(t);
  const { client, calls } = fixture(() =>
    response("review_required", {
      nextAction: "submit_review_receipt",
      reviewPackage: { evidence: "x".repeat(45_000) },
    }),
  );
  const run = await request(folder, "rdg", "openwiki_finish", {
    runId: "run-fixture",
  });
  const first = await (await bindPersonalWikiMcp(client)).call(run);
  assert.equal(first.nextAction, "submit_review_receipt");
  assert.equal(first.published, false);
  assert.ok(JSON.stringify(first).length < 1000);
  const record = JSON.parse(await readFile(first.resultPath, "utf8"));
  assert.equal(record.data.reviewPackage.evidence.length, 45_000);
  const resumed = await (await bindPersonalWikiMcp(client)).call(run);
  assert.equal(resumed.reused, true);
  assert.equal(
    calls.filter(({ name }) => name === "openwiki_finish").length,
    1,
  );
  await writeFile(
    run,
    JSON.stringify({ name: "openwiki_finish", args: { runId: "other-run" } }),
  );
  await assert.rejects(
    (await bindPersonalWikiMcp(client)).call(run),
    /result-conflict/,
  );
});

test("preserves uncertainty after disconnect and never redispatches that attempt", async (t) => {
  const folder = await artifactFolder(t);
  const { client, calls } = fixture(() => {
    throw new Error("Connection closed after the backend received the request");
  });
  const run = await request(folder, "rdg-submit", "openwiki_submit_page", {
    runId: "run-fixture",
  });
  const first = await bindPersonalWikiMcp(client);
  await assert.rejects(first.call(run), /outcome-unconfirmed/);
  const pending = JSON.parse(
    await readFile(path.join(folder, "rdg-submit.result.json"), "utf8"),
  );
  assert.equal(pending.pending, true);
  const resumed = await bindPersonalWikiMcp(client);
  await assert.rejects(resumed.call(run), /outcome-unconfirmed/);
  assert.equal(
    calls.filter(({ name }) => name === "openwiki_submit_page").length,
    1,
  );
});

test("separates lock contention and capability drift from retrying mutations", async (t) => {
  const folder = await artifactFolder(t);
  let release;
  const hold = new Promise((resolve) => {
    release = resolve;
  });
  let entered;
  const dispatched = new Promise((resolve) => {
    entered = resolve;
  });
  const { client, calls } = fixture(async (name) => {
    if (name === "openwiki_submit_page") {
      entered();
      await hold;
      return rejected("busy", "retry", true);
    }
    return rejected("capability_unverified", "retry");
  });
  const session = await bindPersonalWikiMcp(client);
  const submit = await request(folder, "rdg-busy", "openwiki_submit_page", {
    runId: "rdg",
  });
  const finish = await request(folder, "kgpr-drift", "openwiki_finish", {
    runId: "kgpr",
  });
  const pending = session.call(submit);
  await dispatched;
  const concurrent = assert.rejects(session.call(finish), /session-in-use/);
  release();
  const busy = await pending;
  await concurrent;
  assert.equal(busy.action, "wait-for-lock");
  const drift = await session.call(finish);
  assert.equal(drift.action, "verify-capability");
  assert.equal(drift.retryable, false);
  const repeat = await request(folder, "kgpr-new-attempt", "openwiki_finish", {
    runId: "kgpr",
  });
  await assert.rejects(session.call(repeat), /fresh-session-required/);
  assert.equal(calls.length, 3);
});

test("retains finish recovery when the verified server reports a pending Wiki", async (t) => {
  const folder = await artifactFolder(t);
  const { client } = fixture(
    () => response("complete", { published: true }),
    response("status", {
      ...status.structuredContent,
      externalAgent: { ready: false },
      recovery: { action: "retry" },
    }),
  );
  const session = await bindPersonalWikiMcp(client);
  for (const name of [
    "openwiki_begin",
    "openwiki_submit_plan",
    "openwiki_next_page",
    "openwiki_submit_page",
  ]) {
    const file = await request(
      folder,
      name,
      name,
      name === "openwiki_begin"
        ? { mode: "update", wikiRoot: status.structuredContent.paths.wikiRoot }
        : { runId: "run-fixture" },
    );
    await assert.rejects(session.call(file), /personal-wiki-not-ready/);
    await assert.rejects(
      readFile(file.replace(".request.json", ".result.json")),
      { code: "ENOENT" },
    );
  }
  const run = await request(folder, "resume-finish", "openwiki_finish", {
    runId: "run-fixture",
  });
  assert.equal((await session.call(run)).published, true);
});

test("blocks old runtimes and preserves an orphaned staged result", async (t) => {
  const folder = await artifactFolder(t);
  const legacy = fixture(
    () => assert.fail("legacy session dispatched a mutation"),
    response("status", {
      ...status.structuredContent,
      version: { contractSchema: 2, mcpServer: "0.1.1" },
    }),
  );
  await assert.rejects(bindPersonalWikiMcp(legacy.client), /status-unverified/);
  const { client, calls } = fixture(() =>
    assert.fail("orphaned result was ignored"),
  );
  const session = await bindPersonalWikiMcp(client);
  const file = await request(folder, "rdg-orphan", "openwiki_submit_page", {
    runId: "rdg",
  });
  await writeFile(
    path.join(folder, "rdg-orphan.result.json.tmp"),
    "retained evidence",
    { flag: "wx" },
  );
  await assert.rejects(session.call(file), /result-conflict/);
  assert.equal(calls.length, 1);
});

test("keeps the initial status failure classified as lock contention", async () => {
  const { client, calls } = fixture(
    () => assert.fail("status error must stop the bind"),
    rejected("busy", "retry", true),
  );
  await assert.rejects(bindPersonalWikiMcp(client), {
    code: "busy",
    action: "wait-for-lock",
    retryable: true,
  });
  assert.equal(calls.length, 1);
});

test("does not report a stored publication for a different Wiki or runtime", async (t) => {
  const folder = await artifactFolder(t);
  const { client } = fixture(() => response("complete", { published: true }));
  const run = await request(folder, "published", "openwiki_finish", {
    runId: "run-fixture",
  });
  const first = await (await bindPersonalWikiMcp(client)).call(run);
  assert.equal(first.published, true);
  for (const field of ["wikiRoot", "runtimeRoot", "openWikiRoot"]) {
    const next = fixture(
      () => assert.fail("a historical artifact must not dispatch again"),
      response("status", {
        ...status.structuredContent,
        paths: {
          ...status.structuredContent.paths,
          [field]: path.resolve("other-" + field),
        },
      }),
    );
    const rebound = await bindPersonalWikiMcp(next.client);
    await assert.rejects(rebound.call(run), /result-target-conflict/);
    assert.equal(next.calls.length, 1);
  }
});

test("injects the bound Wiki root and rejects another root before dispatch", async (t) => {
  const folder = await artifactFolder(t);
  const { client, calls } = fixture(() =>
    response("planning", {
      runId: "run-fixture",
      wikiRoot: status.structuredContent.paths.wikiRoot,
      runtimeRoot: status.structuredContent.paths.runtimeRoot,
    }),
  );
  const session = await bindPersonalWikiMcp(client);
  const other = await request(folder, "wrong-wiki", "openwiki_begin", {
    mode: "update",
    wikiRoot: path.resolve("another-wiki"),
  });
  await assert.rejects(session.call(other), /wiki-root-mismatch/);
  await assert.rejects(readFile(path.join(folder, "wrong-wiki.result.json")), {
    code: "ENOENT",
  });
  assert.equal(calls.length, 1);

  const run = await request(folder, "bound-wiki", "openwiki_begin", {
    mode: "update",
  });
  const first = await session.call(run);
  assert.equal(first.status, "planning");
  assert.deepEqual(calls.at(-1).args, {
    mode: "update",
    wikiRoot: status.structuredContent.paths.wikiRoot,
  });
  assert.equal((await session.call(run)).reused, true);
  assert.equal(calls.length, 2);
});

test("stops subsequent mutations after a reply puts the Wiki in recovery", async (t) => {
  const folder = await artifactFolder(t);
  const { client, calls } = fixture(() =>
    response("publish_pending", {
      recovery: { action: "restore" },
    }),
  );
  const session = await bindPersonalWikiMcp(client);
  const finish = await request(folder, "pending", "openwiki_finish", {
    runId: "run-fixture",
  });
  assert.equal((await session.call(finish)).action, "restore");
  const plan = await request(folder, "new-plan", "openwiki_submit_plan", {
    runId: "run-fixture",
  });
  await assert.rejects(session.call(plan), /personal-wiki-not-ready/);
  assert.equal(calls.length, 2);
});

test("recovers a complete staged response without another tool call", async (t) => {
  const folder = await artifactFolder(t);
  const { client, calls } = fixture(() =>
    assert.fail("staged response was redispatched"),
  );
  const name = "openwiki_prepare_sources";
  const args = { paths: [path.join(folder, "source.md")] };
  const file = await request(folder, "prepared", name, args);
  const resultPath = path.join(folder, "prepared.result.json");
  const stagePath = resultPath + ".tmp";
  const target = status.structuredContent.paths;
  await writeFile(
    resultPath,
    JSON.stringify({ name, args, target, pending: true }),
    { flag: "wx" },
  );
  const record = {
    name,
    args,
    target,
    isError: false,
    data: response("sources_prepared", { sourceManifestId: "fixture" })
      .structuredContent,
  };
  const session = await bindPersonalWikiMcp(client);
  await writeFile(stagePath, "{", { flag: "wx" });
  await assert.rejects(session.call(file), /outcome-unconfirmed/);
  await writeFile(
    stagePath,
    JSON.stringify({
      ...record,
      target: { ...target, wikiRoot: path.resolve("another-wiki") },
    }),
  );
  await assert.rejects(session.call(file), /result-target-conflict/);
  await writeFile(stagePath, JSON.stringify(record));
  const reopened = await bindPersonalWikiMcp(client);
  const replays = await Promise.all([session.call(file), reopened.call(file)]);
  for (const summary of replays) {
    assert.equal(summary.status, "sources_prepared");
    assert.equal(summary.reused, true);
    assert.equal(summary.resultPath, resultPath);
  }
  assert.deepEqual(JSON.parse(await readFile(resultPath, "utf8")), record);
  await assert.rejects(readFile(stagePath), { code: "ENOENT" });
  assert.equal(calls.length, 2);
});

test("preserves the server's restore action on initial status errors", async () => {
  const { client, calls } = fixture(
    () => assert.fail("status error must stop the bind"),
    rejected("internal_error", "restore"),
  );
  await assert.rejects(bindPersonalWikiMcp(client), {
    code: "internal_error",
    action: "restore",
    recoveryAction: "restore",
    retryable: false,
  });
  assert.equal(calls.length, 1);
});

test("reuses an older begin receipt with an equivalent Wiki root spelling", async (t) => {
  const folder = await artifactFolder(t);
  const { client, calls } = fixture(() =>
    assert.fail("old begin was redispatched"),
  );
  const target = status.structuredContent.paths;
  const alternateRoot =
    process.platform === "win32"
      ? target.wikiRoot.split(path.sep).join("/")
      : target.wikiRoot + "/.";
  assert.notEqual(alternateRoot, target.wikiRoot);
  const name = "openwiki_begin";
  const args = { mode: "update", wikiRoot: alternateRoot };
  const run = await request(folder, "old-begin", name, args);
  const resultPath = path.join(folder, "old-begin.result.json");
  const record = {
    name,
    args,
    target,
    isError: false,
    data: response("planning", {
      wikiRoot: target.wikiRoot,
      runtimeRoot: target.runtimeRoot,
      runId: "run-fixture",
    }).structuredContent,
  };
  await writeFile(resultPath, JSON.stringify(record), { flag: "wx" });
  const session = await bindPersonalWikiMcp(client);
  assert.equal((await session.call(run)).reused, true);
  await writeFile(
    resultPath,
    JSON.stringify({
      ...record,
      data: { ...record.data, wikiRoot: path.resolve("another-wiki") },
    }),
  );
  await assert.rejects(session.call(run), /result-target-conflict/);
  assert.equal(calls.length, 1);
});

test("requires fresh readiness after reusing a same-Wiki recovery reply", async (t) => {
  const folder = await artifactFolder(t);
  const { client, calls } = fixture(() =>
    assert.fail("a write was dispatched"),
  );
  const target = status.structuredContent.paths;
  const session = await bindPersonalWikiMcp(client);
  const name = "openwiki_finish";
  const args = { runId: "run-fixture" };
  const prior = await request(folder, "staged-finish", name, args);
  const resultPath = path.join(folder, "staged-finish.result.json");
  await writeFile(
    resultPath,
    JSON.stringify({ name, args, target, pending: true }),
    { flag: "wx" },
  );
  await writeFile(
    resultPath + ".tmp",
    JSON.stringify({
      name,
      args,
      target,
      isError: false,
      data: response("publish_pending", { recovery: { action: "restore" } })
        .structuredContent,
    }),
    { flag: "wx" },
  );
  const result = await session.call(prior);
  assert.equal(result.action, "restore");
  assert.equal(result.reused, true);
  const plan = await request(folder, "unsafe-plan", "openwiki_submit_plan", {
    runId: "run-fixture",
  });
  await assert.rejects(session.call(plan), /personal-wiki-not-ready/);
  assert.equal(calls.length, 1);
});

test(
  "verifies a Windows case alias using the actual Wiki and runtime directories",
  {
    skip: process.platform !== "win32" && "Windows path identity",
  },
  async (t) => {
    const folder = await artifactFolder(t);
    const wikiRoot = path.join(folder, "Wiki");
    const runtimeRoot = wikiRoot + ".selfopenwiki";
    await mkdir(wikiRoot);
    await mkdir(runtimeRoot);
    const configured = path.join(folder, "wiki");
    const { client, calls } = fixture(
      () =>
        response("planning", { runId: "run-fixture", wikiRoot, runtimeRoot }),
      response("status", {
        ...status.structuredContent,
        paths: {
          ...status.structuredContent.paths,
          wikiRoot: configured,
          runtimeRoot: configured + ".selfopenwiki",
        },
      }),
    );
    const session = await bindPersonalWikiMcp(client);
    const run = await request(folder, "case-alias", "openwiki_begin", {
      mode: "update",
    });
    assert.equal((await session.call(run)).status, "planning");
    assert.equal(calls.at(-1).args.wikiRoot, configured);
    await writeFile(
      run,
      JSON.stringify({
        name: "openwiki_begin",
        args: { mode: "update", wikiRoot },
      }),
    );
    assert.equal((await session.call(run)).reused, true);
    assert.equal(calls.length, 2);
  },
);
