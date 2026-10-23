import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, expect, test, vi } from "vitest";
import * as bootstrapModule from "../src/bootstrap.js";
import * as capabilities from "../src/capabilities.js";
import {
  bootstrapLiveC7Runtime,
  LiveC7Bootstrap,
} from "../src/live-bootstrap.js";
import { createC7McpServer } from "../src/server.js";

const clients: Client[] = [];
const directories: string[] = [];
afterEach(async () => {
  await Promise.all(clients.splice(0).map((client) => client.close()));
  vi.restoreAllMocks();
  for (const directory of directories.splice(0)) {
    if (
      path.dirname(directory) !== path.resolve(os.tmpdir()) ||
      !path.basename(directory).startsWith("wiki-live-bootstrap-")
    )
      throw new Error("Unexpected test cleanup directory.");
    await rm(directory, { force: true, recursive: true });
  }
});

test("the same MCP connection promotes after verification without a prior status call", async () => {
  const fixture = await connectBootstrap();
  expect((await fixture.call()).isError).toBe(true);
  expect(fixture.bootstrap).not.toHaveBeenCalled();
  fixture.verify();
  const result = await fixture.call();
  expect(result.isError).not.toBe(true);
  expect(result.structuredContent).toMatchObject({
    ok: true,
    status: "skills_listed",
  });
  expect(fixture.bootstrap).toHaveBeenCalledTimes(1);
  await fixture.call();
  expect(fixture.bootstrap).toHaveBeenCalledTimes(1);
});

test("preserves structured status and existing diagnostics while blocked", async () => {
  const fixture = await connectBootstrap();
  const result = await fixture.status();
  expect(result.isError).not.toBe(true);
  expect(result.structuredContent).toMatchObject({
    ok: true,
    paths: statusOutput().paths,
    recovery: {
      action: "retry",
      message: expect.stringContaining("Original startup diagnostic."),
    },
  });
  expect(result.structuredContent).toMatchObject({
    recovery: { message: expect.stringContaining("verification is missing") },
  });
});

test("coalesces concurrent promotion and forwards each input and signal", async () => {
  const fixture = await connectBootstrap();
  fixture.verify();
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started!: () => void;
  const entered = new Promise<void>((resolve) => {
    started = resolve;
  });
  fixture.setBootstrapWait(async () => {
    started();
    await held;
  });
  const first = fixture.call();
  await entered;
  const second = fixture.call();
  release();
  const results = await Promise.all([first, second]);
  for (const result of results)
    expect(result.structuredContent).toMatchObject({ ok: true });
  expect(fixture.bootstrap).toHaveBeenCalledTimes(1);
  expect(fixture.delegate).toHaveBeenCalledTimes(2);
  expect(fixture.delegate).toHaveBeenCalledWith(
    "openwiki_list_skills",
    {},
    expect.any(AbortSignal),
  );
});

test("requires reconnect permanently when the startup binding changes", async () => {
  const fixture = await connectBootstrap();
  fixture.verify();
  fixture.changeBinding("changed");
  const result = await fixture.call();
  expect(result.isError).toBe(true);
  expect(body(result)).toMatchObject({
    error: { code: "capability_unverified" },
    recovery: { message: expect.stringContaining("Reconnect this MCP server") },
  });
  fixture.changeBinding("original");
  expect((await fixture.call()).isError).toBe(true);
  expect(fixture.bootstrap).not.toHaveBeenCalled();
  expect((await fixture.status()).structuredContent).toMatchObject({
    recovery: { message: expect.stringContaining("Reconnect this MCP server") },
  });
});

test.each([
  "buildHash",
  "contractsHash",
  "dependencyHash",
  "matrixHash",
  "moduleHasherHash",
  "defaults.json",
  "sensitive-files.json",
] as const)(
  "captures the actual %s binding even when startup evidence is missing",
  async (part) => {
    const fixture = await factoryFixture();
    const live = await bootstrapLiveC7Runtime(fixture.options);
    await fixture.change(part);
    fixture.verify();
    expect(await live.runtime.invoke("openwiki_list_skills", {})).toMatchObject(
      {
        ok: false,
        recovery: {
          message: expect.stringContaining("Reconnect this MCP server"),
        },
      },
    );
    expect(fixture.bootstrap).toHaveBeenCalledTimes(1);
  },
);

test("allows verified policy-only fingerprint changes to promote", async () => {
  const fixture = await factoryFixture();
  const live = await bootstrapLiveC7Runtime(fixture.options);
  await fixture.change("codeHash");
  await fixture.change("skillHash");
  await fixture.change("testHash");
  await fixture.change("verifierHash");
  fixture.verify();
  expect(await live.runtime.invoke("openwiki_list_skills", {})).toMatchObject({
    ok: true,
  });
  expect(fixture.bootstrap).toHaveBeenCalledTimes(2);
});

test("rejects an executable replacement during initial bootstrap", async () => {
  const fixture = await factoryFixture();
  fixture.bootstrap.mockImplementationOnce(async () => {
    await fixture.change("buildHash");
    return fixture.runtime;
  });
  const live = await bootstrapLiveC7Runtime(fixture.options);
  fixture.verify();
  expect(await live.runtime.invoke("openwiki_list_skills", {})).toMatchObject({
    recovery: { message: expect.stringContaining("Reconnect this MCP server") },
  });
  expect(fixture.bootstrap).toHaveBeenCalledTimes(1);
});

test("rejects startup without a captured executable binding", async () => {
  const fixture = await connectBootstrap(null);
  fixture.verify();
  expect(body(await fixture.call())).toMatchObject({
    recovery: { message: expect.stringContaining("Reconnect this MCP server") },
  });
  expect(fixture.bootstrap).not.toHaveBeenCalled();
});

test("retries bootstrap failure without another verification marker", async () => {
  const fixture = await connectBootstrap();
  fixture.verify();
  fixture.setBootstrapWait(async () => {
    throw new Error("temporary startup failure");
  });
  expect((await fixture.call()).isError).toBe(true);
  fixture.setBootstrapWait(async () => undefined);
  expect((await fixture.call()).structuredContent).toMatchObject({ ok: true });
  expect(fixture.bootstrap).toHaveBeenCalledTimes(2);
});

test("rejects an executable change during promotion before dispatch", async () => {
  const fixture = await connectBootstrap();
  fixture.verify();
  fixture.setBootstrapWait(async () => {
    fixture.changeBinding("changed-during-bootstrap");
  });
  expect(body(await fixture.call())).toMatchObject({
    recovery: { message: expect.stringContaining("Reconnect this MCP server") },
  });
  expect(fixture.delegate).not.toHaveBeenCalled();
});

test("rejects evidence invalidated during bootstrap and later recovers", async () => {
  const fixture = await connectBootstrap();
  fixture.verify();
  fixture.setBootstrapWait(async () => {
    fixture.verify(false);
  });
  expect((await fixture.call()).isError).toBe(true);
  expect(fixture.delegate).not.toHaveBeenCalled();
  fixture.setBootstrapWait(async () => undefined);
  fixture.verify();
  expect((await fixture.call()).structuredContent).toMatchObject({ ok: true });
});

function body(result: unknown) {
  return JSON.parse(
    (result as { content: Array<{ text: string }> }).content[0].text,
  );
}

function statusOutput() {
  return {
    authRequired: false,
    authentication: { status: "not_required" },
    capabilities: [],
    defaultModel: null,
    executionMode: "external_agent",
    externalAgent: { activeTransaction: null, ready: false },
    initialized: false,
    legacyProvider: {
      authRequired: true,
      authentication: { status: "not_configured" },
      available: true,
      defaultModel: null,
      initialized: false,
      verifiedModels: [],
    },
    ok: true,
    paths: {
      openWikiRoot: process.cwd(),
      runtimeRoot: process.cwd(),
      wikiRoot: process.cwd(),
    },
    recovery: { action: "retry", message: "Original startup diagnostic." },
    runtime: { locks: [], recoveryState: "recovery_pending" },
    staticCapabilities: [],
    status: "status",
    version: { contractSchema: 2, mcpServer: "0.1.2", openWiki: "0.7.1" },
    verifiedModels: [],
    wikiRevision: `sha256:${"a".repeat(64)}`,
  };
}

async function factoryFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "wiki-live-bootstrap-"));
  directories.push(root);
  await mkdir(path.join(root, "config"));
  for (const name of ["defaults.json", "sensitive-files.json"])
    await writeFile(path.join(root, "config", name), "initial");
  let verified = false;
  const fingerprint: capabilities.CapabilityFingerprint = {
    buildHash: "build",
    contractsHash: "contracts",
    dependencyHash: "dependency",
    matrixHash: "matrix",
    moduleHasherHash: "hasher",
    codeHash: "code",
    skillHash: "skill",
    testHash: "tests",
    verifierHash: "verifier",
  };
  const gate = new capabilities.RuntimeCapabilityGate(undefined, undefined);
  vi.spyOn(gate, "isToolVerified").mockImplementation(() => verified);
  vi.spyOn(capabilities, "computeCapabilityFingerprint").mockImplementation(
    async () => ({ ...fingerprint }),
  );
  vi.spyOn(capabilities, "loadRuntimeCapabilityGate").mockResolvedValue(gate);
  const runtime = {
    capabilityGate: gate,
    runtime: { invoke: vi.fn(async () => ({ ok: true })) },
  };
  const bootstrap = vi
    .spyOn(bootstrapModule, "bootstrapC7Runtime")
    .mockResolvedValue(runtime);
  return {
    options: { repositoryRoot: root, openWikiRoot: root },
    runtime,
    bootstrap,
    verify: () => {
      verified = true;
    },
    change: async (
      part:
        | keyof capabilities.CapabilityFingerprint
        | "defaults.json"
        | "sensitive-files.json",
    ) => {
      if (part === "defaults.json" || part === "sensitive-files.json")
        await writeFile(path.join(root, "config", part), "changed");
      else fingerprint[part] += "-changed";
    },
  };
}

async function connectBootstrap(startupBinding: string | null = "original") {
  let verified = false;
  let binding = "original";
  let waitForBootstrap = async () => {};
  const initial = {
    capabilityGate: { isToolVerified: () => false },
    runtime: {
      invoke: async (name: string) =>
        name === "openwiki_status"
          ? statusOutput()
          : {
              ok: false,
              error: {
                code: "capability_unverified",
                message: "Initial evidence unavailable.",
                retryable: false,
              },
              recovery: { action: "none" },
            },
    },
  };
  const delegate = vi.fn(async () => ({
    ok: true,
    status: "skills_listed",
    recovery: { action: "none" },
    skills: [],
  }));
  const bootstrap = vi.fn(async () => {
    await waitForBootstrap();
    return {
      capabilityGate: { isToolVerified: () => verified },
      runtime: { invoke: delegate },
    };
  });
  const live = new LiveC7Bootstrap({
    initial,
    startupBinding,
    readBinding: async () => binding,
    loadGate: async () => ({ isToolVerified: () => verified }),
    bootstrap,
  });
  const client = new Client({ name: "live-bootstrap-test", version: "1" });
  const server = createC7McpServer(live);
  const [clientTransport, serverTransport] =
    InMemoryTransport.createLinkedPair();
  await Promise.all([
    server.connect(serverTransport),
    client.connect(clientTransport),
  ]);
  clients.push(client);
  return {
    bootstrap,
    delegate,
    changeBinding: (value: string) => {
      binding = value;
    },
    setBootstrapWait: (wait: () => Promise<void>) => {
      waitForBootstrap = wait;
    },
    verify: (value = true) => {
      verified = value;
    },
    call: () =>
      client.callTool({ name: "openwiki_list_skills", arguments: {} }),
    status: () => client.callTool({ name: "openwiki_status", arguments: {} }),
  };
}
