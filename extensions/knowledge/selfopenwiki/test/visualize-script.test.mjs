import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import {
  createVisualizeProcessSpec,
  DEFAULT_VISUALIZER_PORT,
  parseVisualizeArgs,
  runVisualize,
  VISUALIZER_PNPM_VERSION,
  VISUALIZER_RELATIVE_ROOT,
} from "../scripts/visualize.mjs";

test("visualization accepts development, production, and port options", () => {
  assert.deepEqual(parseVisualizeArgs([]), {
    help: false,
    production: false,
    port: DEFAULT_VISUALIZER_PORT,
    wikiRoot: null,
  });
  assert.deepEqual(parseVisualizeArgs(["--production", "--port", "4321"]), {
    help: false,
    production: true,
    port: 4321,
    wikiRoot: null,
  });
  assert.deepEqual(parseVisualizeArgs(["--help"]), {
    help: true,
    production: false,
    port: DEFAULT_VISUALIZER_PORT,
    wikiRoot: null,
  });
  assert.deepEqual(
    parseVisualizeArgs(["--wiki-root", "D:\\wiki_zxh", "--port", "3000"]),
    {
      help: false,
      production: false,
      port: 3000,
      wikiRoot: "D:\\wiki_zxh",
    },
  );
  assert.throws(
    () => parseVisualizeArgs(["--port", "0"]),
    /between 1 and 65535/,
  );
  assert.throws(
    () => parseVisualizeArgs(["--wiki-root", "wiki_zxh"]),
    /absolute/u,
  );
  assert.throws(
    () => parseVisualizeArgs(["--wiki-root"]),
    /requires a value/u,
  );
  assert.throws(
    () => parseVisualizeArgs(["--help", "--production"]),
    /cannot be combined/,
  );
});

test("visualization process binds the configured Wiki root and loopback port", () => {
  const spec = createVisualizeProcessSpec({
    repositoryRoot: "D:\\SelfOpenWiki",
    wikiRoot: "D:\\wiki_zxh",
    production: true,
    port: 4321,
    platform: "win32",
    environment: { PATH: "test-path" },
  });
  assert.deepEqual(spec.args, [
    "/d",
    "/s",
    "/c",
    "corepack.cmd",
    `pnpm@${VISUALIZER_PNPM_VERSION}`,
    "start",
    "--hostname",
    "127.0.0.1",
    "--port",
    "4321",
  ]);
  assert.equal(
    spec.cwd,
    path.join("D:\\SelfOpenWiki", VISUALIZER_RELATIVE_ROOT),
  );
  assert.equal(spec.env.SELFOPENWIKI_WIKI_ROOT, "D:\\wiki_zxh");
  assert.equal(spec.url, "http://127.0.0.1:4321/wiki/local");
});

test("visualization reads storage before starting the viewer", async () => {
  const calls = [];
  const output = [];
  const exitCode = await runVisualize([], {
    environment: { PATH: "test-path" },
    existsSync: () => true,
    readStorageConfig: async () => ({ wikiRoot: "D:\\wiki_zxh" }),
    validateWikiRoot: async (wikiRoot) => wikiRoot,
    spawnVisualizer: async (spec) => {
      calls.push(spec);
      return 0;
    },
    writeStdout: (text) => output.push(text),
    writeStderr: (text) => output.push(text),
  });
  assert.equal(exitCode, 0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].env.SELFOPENWIKI_WIKI_ROOT, "D:\\wiki_zxh");
  assert.match(output.join(""), /zxh_wiki_viewer/);
});

test("visualization accepts the live Wiki root without reading unrelated storage", async () => {
  const calls = [];
  const output = [];
  const exitCode = await runVisualize(["--wiki-root", "D:\\bound-wiki"], {
    environment: { PATH: "test-path" },
    existsSync: () => true,
    readStorageConfig: async () => {
      throw new Error("storage must not be read when Wiki root is explicit");
    },
    validateWikiRoot: async (wikiRoot) => wikiRoot,
    spawnVisualizer: async (spec) => {
      calls.push(spec);
      return 0;
    },
    writeStdout: (text) => output.push(text),
    writeStderr: (text) => output.push(text),
  });
  assert.equal(exitCode, 0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].env.SELFOPENWIKI_WIKI_ROOT, "D:\\bound-wiki");
  assert.equal(calls[0].url, "http://127.0.0.1:3000/wiki/local");
  assert.match(output.join(""), /D:\\bound-wiki/u);
});
