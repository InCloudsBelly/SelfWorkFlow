import { lstat, readFile, rename, stat, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual } from "node:util";

const packageUrl = new URL(
  "../extensions/knowledge/selfopenwiki/self-openwiki/mcp-server/package.json",
  import.meta.url,
);
const require = createRequire(packageUrl);
const timeout = 900_000;
const readyOnly = new Set([
  "openwiki_begin",
  "openwiki_submit_plan",
  "openwiki_next_page",
  "openwiki_submit_page",
]);
const recoveryActions = new Map([
  ["busy", "wait-for-lock"],
  ["capability_unverified", "verify-capability"],
  ["internal_error", "check-run-state"],
  ["source_rejected", "check-source-policy"],
]);
const configOverrides = [
  "SELF_OPENWIKI_CONFIG",
  "SELF_OPENWIKI_OPENWIKI_ROOT",
  "SELF_OPENWIKI_VISUALIZER",
  "SELF_OPENWIKI_EVIDENCE_PATH",
];

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

async function readJson(file) {
  return JSON.parse((await readFile(file, "utf8")).replace(/^\uFEFF/u, ""));
}

function unpack(response) {
  const isError = response.isError === true;
  const data =
    response.structuredContent ??
    JSON.parse(
      response.content?.find(({ type }) => type === "text")?.text ?? "null",
    );
  if (
    !isObject(data) ||
    data.ok !== !isError ||
    (isError
      ? typeof data.error?.code !== "string"
      : typeof data.status !== "string")
  ) {
    throw new Error("wiki-mcp-invalid-response");
  }
  return { data, isError };
}

function actionFor(data) {
  const action = data.recovery?.action;
  if (action !== undefined && action !== "none" && action !== "retry")
    return action;
  return recoveryActions.get(data.error?.code) ?? action;
}

function summarize(resultPath, record, reused) {
  const { name, data, isError } = record;
  const errorCode = data.error?.code;
  const recoveryAction = data.recovery?.action;
  return {
    resultPath,
    reused,
    isError,
    status: data.status,
    nextAction: data.nextAction,
    errorCode,
    retryable: data.error?.retryable,
    recoveryAction,
    action: actionFor(data),
    published:
      name === "openwiki_finish" &&
      !isError &&
      data.status === "complete" &&
      data.published === true,
  };
}

async function sameBoundPath(value, bound) {
  if (value === bound) return true;
  if (typeof value !== "string" || !path.isAbsolute(value)) return false;
  if (process.platform === "win32" && path.parse(value).root.length === 1) {
    return false;
  }
  const normalized = path.resolve(value);
  const expected = path.resolve(bound);
  if (normalized === expected) return true;
  if (
    process.platform !== "win32" ||
    normalized.toLowerCase() !== expected.toLowerCase()
  ) {
    return false;
  }
  // Windows directories can opt into case-sensitive names. Verify aliases by identity.
  try {
    const [actual, target] = await Promise.all([
      stat(value, { bigint: true }),
      stat(bound, { bigint: true }),
    ]);
    return (
      actual.isDirectory() &&
      target.isDirectory() &&
      actual.ino !== 0n &&
      actual.ino === target.ino &&
      actual.dev === target.dev
    );
  } catch {
    return false;
  }
}

async function checkResultBinding(record, request, target, filePath) {
  if (!isObject(record) || record.name !== request.name) {
    throw new Error("wiki-mcp-result-conflict: " + filePath);
  }
  if (!isDeepStrictEqual(record.target, target)) {
    throw new Error("wiki-mcp-result-target-conflict: " + filePath);
  }
  const args =
    record.name === "openwiki_begin" &&
    (await sameBoundPath(record.args?.wikiRoot, target.wikiRoot))
      ? { ...record.args, wikiRoot: target.wikiRoot }
      : record.args;
  if (!isDeepStrictEqual(args, request.args)) {
    throw new Error("wiki-mcp-result-conflict: " + filePath);
  }
}

async function checkCompletedResult(record, filePath) {
  if (record.pending === true || typeof record.isError !== "boolean") {
    throw new Error("wiki-mcp-result-conflict: " + filePath);
  }
  unpack({ structuredContent: record.data, isError: record.isError });
  if (
    record.name === "openwiki_begin" &&
    !record.isError &&
    (!(await sameBoundPath(record.data.wikiRoot, record.target.wikiRoot)) ||
      !(await sameBoundPath(
        record.data.runtimeRoot,
        record.target.runtimeRoot,
      )))
  ) {
    throw new Error("wiki-mcp-result-target-conflict: " + filePath);
  }
}

async function promoteResult(resultPath, pending, record) {
  const stagePath = resultPath + ".tmp";
  const current = await readJson(resultPath);
  if (isDeepStrictEqual(current, record)) return;
  if (!isDeepStrictEqual(current, pending)) {
    throw new Error("wiki-mcp-result-conflict: " + resultPath);
  }
  try {
    await rename(stagePath, resultPath);
  } catch (error) {
    const latest = await readJson(resultPath);
    // A writer or another recovery caller may have committed the same response.
    if (isDeepStrictEqual(latest, record)) return;
    if (!isDeepStrictEqual(latest, pending)) {
      throw new Error("wiki-mcp-result-conflict: " + resultPath);
    }
    if (error.code === "ENOENT") {
      throw new Error("wiki-mcp-outcome-unconfirmed: " + resultPath);
    }
    throw new Error("wiki-mcp-response-staged: " + stagePath, { cause: error });
  }
}

async function retainedResult(resultPath, request, target, observeReadiness) {
  let record;
  try {
    record = await readJson(resultPath);
  } catch (error) {
    if (error.code === "ENOENT") return undefined;
    if (error instanceof SyntaxError) {
      throw new Error("wiki-mcp-result-conflict: " + resultPath);
    }
    throw error;
  }
  await checkResultBinding(record, request, target, resultPath);
  if (record.pending === true) {
    const stagePath = resultPath + ".tmp";
    let staged;
    try {
      staged = await readJson(stagePath);
    } catch (error) {
      if (error instanceof SyntaxError) {
        throw new Error("wiki-mcp-outcome-unconfirmed: " + resultPath);
      }
      if (error.code !== "ENOENT") throw error;
    }
    if (staged === undefined) {
      // The temporary name disappears when a concurrent writer promotes it.
      record = await readJson(resultPath);
      await checkResultBinding(record, request, target, resultPath);
      if (record.pending === true) {
        throw new Error("wiki-mcp-outcome-unconfirmed: " + resultPath);
      }
    } else {
      await checkResultBinding(staged, request, target, stagePath);
      await checkCompletedResult(staged, stagePath);
      observeReadiness(staged);
      await promoteResult(resultPath, record, staged);
      return staged;
    }
  }
  await checkCompletedResult(record, resultPath);
  observeReadiness(record);
  return record;
}

function checkSourcePaths(paths) {
  const invalid = paths.findIndex((item) => {
    const value = item.trim();
    return process.platform === "win32"
      ? !/^[A-Za-z]:[\\/]/u.test(value)
      : !path.isAbsolute(value);
  });
  if (invalid !== -1) {
    throw new Error(
      "wiki-mcp-invalid-input: paths[" +
        invalid +
        "] must be an absolute local path",
    );
  }
}

async function invoke(client, name, args) {
  return unpack(
    await client.callTool({ name, arguments: args }, undefined, { timeout }),
  );
}

export async function bindPersonalWikiMcp(client) {
  const { data: status, isError } = await invoke(client, "openwiki_status", {});
  if (isError) {
    const { code, retryable } = status.error;
    throw Object.assign(new Error("wiki-mcp-status-failed: " + code), {
      code,
      retryable,
      recoveryAction: status.recovery?.action,
      action: actionFor(status),
    });
  }
  const target = {
    wikiRoot: status.paths?.wikiRoot,
    runtimeRoot: status.paths?.runtimeRoot,
    openWikiRoot: status.paths?.openWikiRoot,
  };
  const version = /^(\d+)\.(\d+)\.(\d+)$/u.exec(
    status.version?.mcpServer ?? "",
  );
  const current =
    version &&
    (Number(version[1]) > 0 ||
      Number(version[2]) > 1 ||
      (Number(version[2]) === 1 && Number(version[3]) >= 2));
  if (
    status.status !== "status" ||
    !Object.values(target).every(
      (value) => typeof value === "string" && path.isAbsolute(value),
    ) ||
    !current ||
    status.version?.contractSchema !== 2 ||
    status.executionMode !== "external_agent" ||
    status.authRequired !== false ||
    typeof status.externalAgent?.ready !== "boolean"
  ) {
    throw new Error("wiki-mcp-personal-status-unverified");
  }

  const {
    AjvJsonSchemaValidator,
  } = require("@modelcontextprotocol/sdk/validation/ajv");
  const validator = new AjvJsonSchemaValidator();
  const { tools, nextCursor } = await client.listTools();
  if (nextCursor !== undefined)
    throw new Error("wiki-mcp-tool-list-incomplete");
  const schemas = new Map(
    tools.map(({ name, inputSchema }) => [name, inputSchema]),
  );
  const validators = new Map();
  let inFlight = false;
  let freshSessionRequired = false;
  let publishReady = status.externalAgent.ready;

  function observeReadiness(record) {
    const { data, name } = record;
    if (
      (name === "openwiki_status" && data.externalAgent?.ready === false) ||
      data.status === "publish_pending" ||
      data.recovery?.action === "restore"
    ) {
      publishReady = false;
    }
  }

  async function call(requestPath) {
    if (inFlight) throw new Error("wiki-mcp-session-in-use");
    inFlight = true;
    try {
      if (
        !path.isAbsolute(requestPath) ||
        !requestPath.endsWith(".request.json")
      ) {
        throw new Error("wiki-mcp-request-path-invalid");
      }
      let request = await readJson(requestPath).catch((error) => {
        if (error instanceof SyntaxError)
          throw new Error("wiki-mcp-request-invalid");
        throw error;
      });
      if (
        !isObject(request) ||
        Object.keys(request).length !== 2 ||
        typeof request.name !== "string" ||
        !isObject(request.args)
      ) {
        throw new Error("wiki-mcp-request-invalid");
      }
      if (request.name === "openwiki_begin") {
        if (
          request.args.wikiRoot !== undefined &&
          !(await sameBoundPath(request.args.wikiRoot, target.wikiRoot))
        ) {
          throw new Error("wiki-mcp-wiki-root-mismatch");
        }
        request = {
          name: request.name,
          args: { ...request.args, wikiRoot: target.wikiRoot },
        };
      }
      const { name, args } = request;
      const resultPath = requestPath.replace(
        /\.request\.json$/u,
        ".result.json",
      );
      const retained = await retainedResult(
        resultPath,
        request,
        target,
        observeReadiness,
      );
      if (retained !== undefined) return summarize(resultPath, retained, true);
      if (freshSessionRequired)
        throw new Error("wiki-mcp-fresh-session-required");
      if (!publishReady && readyOnly.has(name)) {
        throw new Error("wiki-mcp-personal-wiki-not-ready");
      }

      const schema = schemas.get(name);
      if (schema === undefined) throw new Error("wiki-mcp-tool-unavailable");
      if (!validators.has(name))
        validators.set(name, validator.getValidator(schema));
      const checked = validators.get(name)(args);
      if (!checked.valid) {
        throw new Error(
          "wiki-mcp-invalid-input: " + checked.errorMessage.slice(0, 320),
        );
      }
      if (name === "openwiki_prepare_sources") checkSourcePaths(args.paths);

      const responsePath = resultPath + ".tmp";
      const staged = await lstat(responsePath).catch((error) => {
        if (error.code === "ENOENT") return undefined;
        throw error;
      });
      if (staged !== undefined)
        throw new Error("wiki-mcp-result-conflict: " + responsePath);

      // The exclusive marker survives both a lost response and a restarted client.
      const pending = { name, args, target, pending: true };
      try {
        await writeFile(resultPath, JSON.stringify(pending), {
          flag: "wx",
          flush: true,
        });
      } catch (error) {
        if (error.code !== "EEXIST") throw error;
        const other = await retainedResult(
          resultPath,
          request,
          target,
          observeReadiness,
        );
        if (other !== undefined) return summarize(resultPath, other, true);
        throw new Error("wiki-mcp-result-conflict: " + resultPath);
      }

      let record;
      try {
        const result = await invoke(client, name, args);
        if (result.data.error?.code === "capability_unverified") {
          freshSessionRequired = true;
        }
        record = { name, args, target, ...result };
        await writeFile(responsePath, JSON.stringify(record, null, 2), {
          flag: "wx",
          flush: true,
        });
      } catch {
        freshSessionRequired = true;
        throw new Error("wiki-mcp-outcome-unconfirmed: " + resultPath);
      }
      try {
        await checkCompletedResult(record, responsePath);
        observeReadiness(record);
        await promoteResult(resultPath, pending, record);
      } catch (error) {
        freshSessionRequired = true;
        throw error;
      }
      return summarize(resultPath, record, false);
    } finally {
      inFlight = false;
    }
  }

  return { status, call, close: () => client.close() };
}

export async function openPersonalWikiMcp() {
  const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
  const {
    StdioClientTransport,
  } = require("@modelcontextprotocol/sdk/client/stdio.js");
  const client = new Client({
    name: "selfworkflow-personal-wiki",
    version: "1.0",
  });
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [fileURLToPath(new URL("dist/index.js", packageUrl))],
    env: Object.fromEntries(
      configOverrides
        .filter((key) => process.env[key] !== undefined)
        .map((key) => [key, process.env[key]]),
    ),
    stderr: "pipe",
  });
  transport.stderr?.resume();
  try {
    await client.connect(transport);
    return await bindPersonalWikiMcp(client);
  } catch (error) {
    await client.close().catch(() => {});
    throw error;
  }
}
