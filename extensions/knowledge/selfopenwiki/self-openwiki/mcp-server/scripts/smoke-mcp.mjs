#!/usr/bin/env node

import { createHash, randomUUID } from "node:crypto";
import { execFileSync, spawn } from "node:child_process";
import {
  lstat,
  mkdir,
  mkdtemp,
  open,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  getDefaultEnvironment,
  StdioClientTransport,
} from "@modelcontextprotocol/sdk/client/stdio.js";

const MAX_EVIDENCE_BYTES = 1024 * 1024;
const serverRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const repositoryRoot = path.dirname(serverRoot);
const smokeRoot = path.resolve(repositoryRoot, "..", "..");
const runtimeRoot = path.join(repositoryRoot, "runtime");
const expectedStagedPath = path.join(runtimeRoot, ".verified-capabilities.tmp");
const stagedPath = path.resolve(
  process.env.SELF_OPENWIKI_STAGED_CAPABILITY_EVIDENCE_PATH ?? "",
);
if (stagedPath !== expectedStagedPath) {
  throw new Error("The staged capability evidence path is invalid.");
}

await mkdir(runtimeRoot, { recursive: true });
const temporaryRuntime = await mkdtemp(
  path.join(smokeRoot, "self-openwiki-smoke-"),
);
const wikiRoot = temporaryRuntime;
const storageRuntimeRoot = `${wikiRoot}.selfopenwiki`;
const smokeId = randomUUID();
const temporaryEvidencePath = path.join(
  runtimeRoot,
  `smoke-evidence-${smokeId}.json`,
);
const storageConfigPath = path.join(
  runtimeRoot,
  `smoke-storage-config-${smokeId}.json`,
);
const client = new Client({
  name: `self-openwiki-smoke-${randomUUID()}`,
  version: "1.0.0",
});
const transport = new StdioClientTransport({
  args: [path.join(serverRoot, "dist", "index.js")],
  command: process.execPath,
  cwd: repositoryRoot,
  env: {
    ...getDefaultEnvironment(),
    SELF_OPENWIKI_CONFIG: storageConfigPath,
    SELF_OPENWIKI_EVIDENCE_PATH: temporaryEvidencePath,
    SELF_OPENWIKI_OPENWIKI_ROOT: path.join(
      repositoryRoot,
      "..",
      ".work",
      "openwiki",
    ),
  },
  stderr: "pipe",
});
let stderr = "";
transport.stderr?.on("data", (chunk) => {
  if (stderr.length < 64 * 1024) stderr += String(chunk);
});

try {
  await copyExactStagedEvidence(stagedPath, temporaryEvidencePath);
  await writeFile(
    storageConfigPath,
    `${JSON.stringify({
      schemaVersion: 1,
      generation: 1,
      wikiRoot,
      runtimeRoot: storageRuntimeRoot,
    })}\n`,
    { encoding: "utf8", flag: "wx" },
  );
  await writeInitialWiki(wikiRoot);
  await withTimeout(client.connect(transport), 20_000);

  const listed = await withTimeout(client.listTools(), 20_000);
  const expectedTools = [
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
  if (
    JSON.stringify(listed.tools.map((tool) => tool.name)) !==
    JSON.stringify(expectedTools)
  ) {
    throw new Error("The stdio MCP server did not expose the exact tool set.");
  }

  const statusBefore = await call("openwiki_status", {});
  assertExternalStatus(statusBefore);
  const readIndex = await call("openwiki_read", {});
  assertStatus(readIndex, "wiki_read");
  const readPage = await call("openwiki_read", {
    paths: ["index.md"],
    expectedWikiRevision: readIndex.revision,
  });
  assertStatus(readPage, "wiki_read");
  if (
    readPage.knowledge.length !== 1 ||
    readPage.knowledge[0].revision !== readIndex.revision ||
    readPage.knowledge[0].content !==
      (await readFile(path.join(wikiRoot, "index.md"), "utf8"))
  ) {
    throw new Error(
      "Built MCP safe reading did not preserve its exact page binding.",
    );
  }
  const initialRevision = statusBefore.wikiRevision;
  const started = await call("openwiki_begin_external_update", {
    action: "start",
    requestId: "smoke-request-12345678",
    confirmedByUser: true,
    instruction: "Refresh the smoke-tested project overview.",
    materials: [
      {
        id: "smoke-material-1",
        source: "built-stdio-smoke",
        content: "The verified external Agent flow updates the overview.",
      },
    ],
    confirmedWikiPaths: ["index.md"],
    expectedWikiRevision: initialRevision,
  });
  assertStatus(started, "external_update_ready");
  const transactionId = started.workPackage?.transactionId;
  const generation = started.workPackage?.generation;
  const bindingHash = started.workPackage?.bindingHash;
  const candidateRoot = started.workPackage?.candidate?.rootPath;
  assertString(transactionId, "transactionId");
  assertNumber(generation, "generation");
  assertHash(bindingHash, "bindingHash");
  assertString(candidateRoot, "candidate root");
  assertDescendant(candidateRoot, storageRuntimeRoot);

  const writerFailure = await call("openwiki_finalize_external_update", {
    action: "report_host_failure",
    transactionId,
    bindingHash,
    phase: "candidate_writer",
    code: "host_process_failure",
    message: "The smoke writer exited before producing a receipt.",
    retryable: true,
  });
  assertStatus(writerFailure, "external_host_failure");

  const writerResumed = await call("openwiki_begin_external_update", {
    action: "resume",
    transactionId,
    bindingHash,
  });
  assertStatus(writerResumed, "external_update_resumed");
  if (
    writerResumed.workPackage?.bindingHash !== bindingHash ||
    writerResumed.workPackage?.candidate?.rootPath !== candidateRoot
  ) {
    throw new Error("Writer resume did not preserve the exact work package.");
  }
  await writeFile(
    path.join(candidateRoot, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n\nThe external Agent smoke flow published this revision.\n\nSee [Quickstart](./quickstart.md).\n",
    "utf8",
  );

  const writerExecutionId = "writer-smoke-12345678";
  const prepared = await call("openwiki_finalize_external_update", {
    action: "prepare_review",
    transactionId,
    bindingHash,
    candidateReceipt: {
      type: "external_candidate_receipt",
      version: 1,
      transactionId,
      generation,
      bindingHash,
      writerExecutionId,
      classification: "minor",
      issues: [],
      questions: [],
      summary: "Updated the confirmed overview page.",
    },
  });
  assertStatus(prepared, "external_review_ready");
  assertHash(prepared.reviewPackageHash, "reviewPackageHash");
  assertHash(prepared.candidateRootHash, "candidateRootHash");
  assertHash(prepared.candidateReceiptHash, "candidateReceiptHash");
  if (
    prepared.reviewPackage?.candidate?.permissions?.join(",") !== "read,list"
  ) {
    throw new Error(
      "The Reviewer package did not expose read-only permissions.",
    );
  }

  const reviewerFailure = await call("openwiki_finalize_external_update", {
    action: "report_host_failure",
    transactionId,
    bindingHash,
    phase: "reviewer",
    code: "host_timeout",
    message: "The smoke Reviewer timed out before returning a receipt.",
    retryable: true,
    reviewPackageHash: prepared.reviewPackageHash,
  });
  assertStatus(reviewerFailure, "external_host_failure");

  const reviewResumed = await call("openwiki_begin_external_update", {
    action: "resume",
    transactionId,
    bindingHash,
  });
  assertStatus(reviewResumed, "external_review_resumed");
  if (
    reviewResumed.reviewPackageHash !== prepared.reviewPackageHash ||
    reviewResumed.candidateRootHash !== prepared.candidateRootHash ||
    reviewResumed.candidateReceiptHash !== prepared.candidateReceiptHash
  ) {
    throw new Error(
      "Reviewer resume did not preserve the exact Review package.",
    );
  }

  const reviewerExecutionId = "reviewer-smoke-12345678";
  if (reviewerExecutionId === writerExecutionId) {
    throw new Error("Writer and Reviewer execution IDs must be independent.");
  }
  const published = await call("openwiki_finalize_external_update", {
    action: "submit_review",
    transactionId,
    bindingHash,
    reviewReceipt: {
      type: "external_review_receipt",
      version: 1,
      transactionId,
      generation,
      bindingHash,
      reviewPackageHash: reviewResumed.reviewPackageHash,
      candidateRootHash: reviewResumed.candidateRootHash,
      candidateReceiptHash: reviewResumed.candidateReceiptHash,
      reviewerExecutionId,
      verdict: "pass",
      issues: [],
    },
  });
  assertStatus(published, "published");
  if (
    published.published !== true ||
    published.reviewEvidence !== "host_attested"
  ) {
    throw new Error(
      "The external Review did not publish with host attestation.",
    );
  }

  const statusAfter = await call("openwiki_status", {});
  assertExternalStatus(statusAfter);
  if (
    statusAfter.wikiRevision === initialRevision ||
    statusAfter.wikiRevision !== published.wikiRevision ||
    statusAfter.externalAgent?.activeTransaction !== null
  ) {
    throw new Error("The formal Wiki revision did not commit exactly once.");
  }
  const formalIndex = await readFile(path.join(wikiRoot, "index.md"), "utf8");
  if (!formalIndex.includes("external Agent smoke flow published")) {
    throw new Error(
      "The reviewed candidate was not installed in the formal Wiki.",
    );
  }

  const personalBegin = await call("openwiki_begin", {
    mode: "update",
    wikiRoot,
  });
  assertStatus(personalBegin, "planning");
  const personalRunId = personalBegin.runId;
  assertString(personalRunId, "personal runId");
  const personalPlan = await call("openwiki_submit_plan", {
    confirmedByUser: true,
    pages: [
      {
        path: "index.md",
        title: "Home",
        purpose: "Refresh the personal Wiki home page.",
      },
    ],
    runId: personalRunId,
  });
  assertStatus(personalPlan, "plan_accepted");
  const personalPage = await call("openwiki_next_page", {
    runId: personalRunId,
  });
  assertStatus(personalPage, "page_pending");
  const personalJobId = personalPage.jobId;
  const personalCandidateRoot = personalPage.candidate.rootPath;
  assertString(personalJobId, "personal jobId");
  assertString(personalCandidateRoot, "personal candidate root");
  assertDescendant(personalCandidateRoot, storageRuntimeRoot);
  const personalClaims = await call("openwiki_inspect_page_claims", {
    jobId: personalJobId,
    runId: personalRunId,
  });
  assertStatus(personalClaims, "claims_inspected");
  await writeFile(
    path.join(personalCandidateRoot, "index.md"),
    "---\ntype: concept\ntitle: Home\ndescription: Personal Wiki home page.\ntags: [home]\n---\n\n# Home\n\nThe personal six-stage flow was verified.\n",
    "utf8",
  );
  const personalPageAccepted = await call("openwiki_submit_page", {
    jobId: personalJobId,
    runId: personalRunId,
  });
  assertStatus(personalPageAccepted, "page_accepted");
  const personalReviewRequired = await call("openwiki_finish", {
    runId: personalRunId,
  });
  assertStatus(personalReviewRequired, "review_required");
  if (
    personalReviewRequired.nextAction !== "submit_candidate_receipt" ||
    personalReviewRequired.generation !== 1
  ) {
    throw new Error("The personal six-stage flow did not stop at C7 review.");
  }
  const personalCandidatePrepared = await call("openwiki_finish", {
    candidateReceipt: {
      type: "external_candidate_receipt",
      version: 1,
      transactionId: personalReviewRequired.transactionId,
      generation: personalReviewRequired.generation,
      bindingHash: personalReviewRequired.binding.candidateBindingHash,
      writerExecutionId: "personal-writer-smoke-12345678",
      classification: "minor",
      issues: [],
      questions: [],
      summary: "The personal six-stage candidate is ready for review.",
    },
    runId: personalRunId,
  });
  assertStatus(personalCandidatePrepared, "review_required");
  if (personalCandidatePrepared.nextAction !== "submit_review_receipt") {
    throw new Error(
      "The personal candidate did not produce a C7 review package.",
    );
  }
  const personalPublished = await call("openwiki_finish", {
    reviewReceipt: {
      type: "external_review_receipt",
      version: 1,
      transactionId: personalReviewRequired.transactionId,
      generation: personalReviewRequired.generation,
      bindingHash: personalReviewRequired.binding.candidateBindingHash,
      reviewPackageHash: personalCandidatePrepared.reviewPackageHash,
      candidateRootHash: personalCandidatePrepared.candidateRootHash,
      candidateReceiptHash: personalCandidatePrepared.candidateReceiptHash,
      reviewerExecutionId: "personal-reviewer-smoke-12345678",
      verdict: "pass",
      issues: [],
    },
    runId: personalRunId,
  });
  assertStatus(personalPublished, "complete");
  if (personalPublished.published !== true) {
    throw new Error("The personal C7 review did not publish the candidate.");
  }

  process.stderr.write(
    `Verified built stdio external flow: ${JSON.stringify({
      bindingHash,
      candidateReceiptHash: prepared.candidateReceiptHash,
      candidateRootHash: prepared.candidateRootHash,
      finalWikiRevision: published.wikiRevision,
      initialWikiRevision: initialRevision,
      reviewPackageHash: prepared.reviewPackageHash,
      status: published.status,
      transactionId,
    })}\n`,
  );
} catch (error) {
  throw new Error(
    `${error instanceof Error ? error.message : "Unknown stdio smoke failure."}${stderr ? ` Child stderr: ${stderr.trim()}` : ""}`,
  );
} finally {
  await closeMcpTransport(client, transport);
  await rm(temporaryRuntime, {
    force: true,
    maxRetries: 20,
    recursive: true,
    retryDelay: 25,
  });
  await rm(storageRuntimeRoot, {
    force: true,
    maxRetries: 20,
    recursive: true,
    retryDelay: 25,
  });
  await rm(temporaryEvidencePath, { force: true });
  await rm(storageConfigPath, { force: true });
}

/**
 * StdioClientTransport normally closes the direct child, but a timed-out
 * probe can leave the close handshake unresolved. On Windows the MCP server
 * may also have descendants, so force-close the exact recorded process tree.
 */
async function closeMcpTransport(client, transport) {
  const pid = transport.pid;
  await Promise.race([
    client.close().catch(() => undefined),
    new Promise((resolve) => setTimeout(resolve, 2_000)),
  ]);
  if (pid === null || pid === undefined) return;
  await terminateProcessTree(pid).catch(() => undefined);
}

async function terminateProcessTree(pid) {
  if (process.platform !== "win32") {
    try {
      process.kill(-pid, "SIGKILL");
    } catch {
      // The process already exited.
    }
    return;
  }
  const systemRoot = process.env.SystemRoot ?? process.env.WINDIR;
  if (!systemRoot) return;
  const taskkill = spawn(
    path.join(systemRoot, "System32", "taskkill.exe"),
    ["/PID", String(pid), "/T", "/F"],
    {
      env: { SystemRoot: systemRoot, WINDIR: systemRoot },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  await new Promise((resolve) => {
    taskkill.once("error", resolve);
    taskkill.once("close", resolve);
  });
}

async function copyExactStagedEvidence(sourcePath, destinationPath) {
  const beforePath = await lstat(sourcePath, { bigint: true });
  if (
    beforePath.isSymbolicLink() ||
    !beforePath.isFile() ||
    beforePath.size > BigInt(MAX_EVIDENCE_BYTES)
  ) {
    throw new Error("The staged capability evidence is invalid.");
  }
  const source = await open(sourcePath, "r");
  try {
    const beforeHandle = await source.stat({ bigint: true });
    assertSameRegularFile(beforePath, beforeHandle);
    const bytes = await readHandleBytes(source, Number(beforeHandle.size));
    const afterHandle = await source.stat({ bigint: true });
    const afterPath = await lstat(sourcePath, { bigint: true });
    assertSameRegularFile(beforeHandle, afterHandle);
    assertSameRegularFile(afterHandle, afterPath);
    const sourceHash = sha256(bytes);

    const destination = await open(destinationPath, "wx", 0o600);
    try {
      await destination.writeFile(bytes);
      await destination.sync();
    } finally {
      await destination.close();
    }
    const copied = await readFile(destinationPath);
    if (!copied.equals(bytes) || sha256(copied) !== sourceHash) {
      throw new Error("The copied capability evidence does not match staging.");
    }
  } finally {
    await source.close();
  }
}

async function writeInitialWiki(root) {
  await mkdir(root, { recursive: true });
  await writeFile(
    path.join(root, "quickstart.md"),
    "---\ntype: Guide\n---\n\n# Quickstart\n\nSee [Home](./index.md).\n",
    "utf8",
  );
  await writeFile(
    path.join(root, "index.md"),
    "---\ntype: Guide\n---\n\n# Home\n",
    "utf8",
  );
  runGit(root, ["init", "--initial-branch=main"]);
  runGit(root, ["config", "user.email", "smoke@example.invalid"]);
  runGit(root, ["config", "user.name", "SelfOpenWiki Smoke"]);
  runGit(root, ["add", "index.md", "quickstart.md"]);
  runGit(root, ["commit", "-m", "initialize smoke Wiki"]);
}

function runGit(cwd, args) {
  execFileSync("git", ["-c", "core.hooksPath=NUL", ...args], {
    cwd,
    env: {
      ...process.env,
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_TERMINAL_PROMPT: "0",
    },
    stdio: "ignore",
    windowsHide: true,
  });
}

async function call(name, args) {
  let result;
  try {
    result = await withTimeout(
      client.callTool({ name, arguments: args }),
      30_000,
    );
  } catch (error) {
    throw new Error(
      `${name} MCP call did not complete: ${error instanceof Error ? error.message : String(error)}`,
      { cause: error },
    );
  }
  if (
    result.isError === true ||
    typeof result.structuredContent !== "object" ||
    result.structuredContent === null ||
    result.structuredContent.ok !== true
  ) {
    throw new Error(
      `The ${name} stdio call failed: ${JSON.stringify({
        content: result.content,
        isError: result.isError,
        structuredContent: result.structuredContent,
      })}`,
    );
  }
  return result.structuredContent;
}

function assertExternalStatus(status) {
  const ids = new Set(
    Array.isArray(status.capabilities)
      ? status.capabilities.map((capability) => capability?.id)
      : [],
  );
  if (
    status.status !== "status" ||
    status.version?.contractSchema !== 2 ||
    status.executionMode !== "external_agent" ||
    status.authRequired !== false ||
    status.authentication?.status !== "not_required" ||
    status.defaultModel !== null ||
    !Array.isArray(status.verifiedModels) ||
    status.verifiedModels.length !== 0 ||
    status.initialized !== true ||
    status.externalAgent?.ready !== true ||
    !ids.has("update.external-agent.begin") ||
    !ids.has("update.external-agent.reviewed-finalize")
  ) {
    throw new Error(
      `The external status is not truthful: ${JSON.stringify(status)}`,
    );
  }
  assertHash(status.wikiRevision, "wikiRevision");
}

function assertStatus(value, expected) {
  if (value.status !== expected) {
    throw new Error(`Expected ${expected}, received ${JSON.stringify(value)}`);
  }
}

function assertString(value, name) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`The ${name} is missing from the MCP result.`);
  }
}

function assertNumber(value, name) {
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`The ${name} is missing from the MCP result.`);
  }
}

function assertHash(value, name) {
  if (typeof value !== "string" || !/^sha256:[a-f0-9]{64}$/u.test(value)) {
    throw new Error(`The ${name} is not a canonical SHA-256 value.`);
  }
}

function assertDescendant(candidate, root) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  if (
    relative === "" ||
    relative.startsWith("..") ||
    path.isAbsolute(relative)
  ) {
    throw new Error("The candidate root escaped the temporary runtime.");
  }
}

function assertSameRegularFile(expected, actual) {
  if (
    !expected.isFile() ||
    expected.isSymbolicLink() ||
    !actual.isFile() ||
    actual.isSymbolicLink() ||
    expected.dev !== actual.dev ||
    expected.ino !== actual.ino ||
    expected.size !== actual.size ||
    actual.size > BigInt(MAX_EVIDENCE_BYTES)
  ) {
    throw new Error("The staged capability evidence changed while being read.");
  }
}

async function readHandleBytes(handle, size) {
  const bytes = Buffer.alloc(size);
  let offset = 0;
  while (offset < size) {
    const { bytesRead } = await handle.read(
      bytes,
      offset,
      size - offset,
      offset,
    );
    if (bytesRead === 0) {
      throw new Error("The staged capability evidence was truncated.");
    }
    offset += bytesRead;
  }
  return bytes;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function withTimeout(promise, timeoutMs) {
  let timeout;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error("The stdio MCP smoke check timed out.")),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
}
