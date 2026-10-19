import { mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test } from "vitest";
import { resolveOpenWikiAdapterPaths } from "../src/openwiki-adapter.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("the sole C7-to-OpenWiki adapter", () => {
  test("resolves only the fixed built CLI and OAuth module", async () => {
    const rootDir = await createFakeOpenWiki();
    const canonicalRoot = await realpath(rootDir);

    await expect(resolveOpenWikiAdapterPaths(rootDir)).resolves.toEqual({
      rootDir: canonicalRoot,
      cliPath: path.join(canonicalRoot, "dist", "cli", "cli.js"),
      oauthModulePath: path.join(
        canonicalRoot,
        "dist",
        "agent",
        "openai-chatgpt-oauth.js",
      ),
    });
  });

  test("fails closed for relative, wrong-package, or incomplete roots", async () => {
    await expect(resolveOpenWikiAdapterPaths("relative")).rejects.toThrow(
      /absolute/iu,
    );

    const wrongRoot = await createFakeOpenWiki({ packageName: "impostor" });
    await expect(resolveOpenWikiAdapterPaths(wrongRoot)).rejects.toThrow(
      /package/iu,
    );

    const incompleteRoot = await createFakeOpenWiki({ includeOAuth: false });
    await expect(resolveOpenWikiAdapterPaths(incompleteRoot)).rejects.toThrow(
      /build|oauth/iu,
    );
  });

  test("does not accept caller-selected CLI or OAuth paths", async () => {
    const rootDir = await createFakeOpenWiki();
    const paths = await resolveOpenWikiAdapterPaths(rootDir);

    expect(Object.keys(paths).sort()).toEqual([
      "cliPath",
      "oauthModulePath",
      "rootDir",
    ]);
    expect(paths.cliPath).not.toContain("fake-openwiki.mjs");
    expect(paths.oauthModulePath).not.toContain("fake-openwiki.mjs");
  });
});

async function createFakeOpenWiki(
  options: { includeOAuth?: boolean; packageName?: string } = {},
): Promise<string> {
  const rootDir = await mkdtemp(path.join(os.tmpdir(), "fake-openwiki-"));
  tempDirs.push(rootDir);
  const agentDir = path.join(rootDir, "dist", "agent");
  await mkdir(agentDir, { recursive: true });
  await mkdir(path.join(rootDir, "dist", "cli"), { recursive: true });
  await Promise.all([
    writeFile(
      path.join(rootDir, "package.json"),
      JSON.stringify({ name: options.packageName ?? "openwiki" }),
      "utf8",
    ),
    writeFile(
      path.join(rootDir, "dist", "cli", "cli.js"),
      "export {};\n",
      "utf8",
    ),
  ]);
  if (options.includeOAuth !== false) {
    await writeFile(
      path.join(agentDir, "openai-chatgpt-oauth.js"),
      "export {};\n",
      "utf8",
    );
  }
  return rootDir;
}
