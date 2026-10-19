import { lstat, readFile, realpath } from "node:fs/promises";
import path from "node:path";

export type OpenWikiAdapterPaths = {
  cliPath: string;
  oauthModulePath: string;
  rootDir: string;
};

/**
 * Resolve the only two upstream OpenWiki implementation paths C7 may invoke.
 * The optional root exists solely for dependency injection in tests; MCP tool
 * input never reaches this function.
 */
export async function resolveOpenWikiAdapterPaths(
  rootOverride?: string,
): Promise<OpenWikiAdapterPaths> {
  const requestedRoot = rootOverride ?? (await findOpenWikiRoot());
  if (!path.isAbsolute(requestedRoot)) {
    throw new Error("OpenWiki package root must be an absolute path.");
  }

  const rootDir = await canonicalDirectory(requestedRoot, "OpenWiki root");
  await assertOpenWikiPackage(rootDir);

  const cliPath = path.join(rootDir, "dist", "cli", "cli.js");
  const oauthModulePath = path.join(
    rootDir,
    "dist",
    "agent",
    "openai-chatgpt-oauth.js",
  );
  await Promise.all([
    assertRegularNonLinkFile(rootDir, cliPath, "OpenWiki CLI build"),
    assertRegularNonLinkFile(rootDir, oauthModulePath, "OpenWiki OAuth build"),
  ]);

  return { cliPath, oauthModulePath, rootDir };
}

async function findOpenWikiRoot(): Promise<string> {
  let current = path.resolve(import.meta.dirname);
  for (;;) {
    const packagePath = path.join(current, "package.json");
    try {
      const value = JSON.parse(await readFile(packagePath, "utf8")) as {
        name?: unknown;
      };
      if (value.name === "openwiki") {
        return current;
      }
    } catch {
      // Keep walking. The final error does not expose package contents.
    }

    const parent = path.dirname(current);
    if (parent === current) {
      throw new Error("Could not locate the containing OpenWiki package.");
    }
    current = parent;
  }
}

async function assertOpenWikiPackage(rootDir: string): Promise<void> {
  let value: unknown;
  try {
    value = JSON.parse(
      await readFile(path.join(rootDir, "package.json"), "utf8"),
    );
  } catch (error) {
    throw new Error("OpenWiki package metadata is missing or invalid.", {
      cause: error,
    });
  }
  if (
    typeof value !== "object" ||
    value === null ||
    !("name" in value) ||
    value.name !== "openwiki"
  ) {
    throw new Error("OpenWiki package metadata has the wrong package name.");
  }
}

async function canonicalDirectory(
  value: string,
  label: string,
): Promise<string> {
  let stat;
  try {
    stat = await lstat(value);
  } catch (error) {
    throw new Error(`${label} is missing.`, { cause: error });
  }
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`${label} must be a regular non-link directory.`);
  }
  return realpath(value);
}

async function assertRegularNonLinkFile(
  rootDir: string,
  filePath: string,
  label: string,
): Promise<void> {
  const relative = path.relative(rootDir, filePath);
  if (
    relative === "" ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new Error(`${label} escapes the OpenWiki package.`);
  }

  let current = rootDir;
  for (const segment of relative.split(path.sep)) {
    current = path.join(current, segment);
    let stat;
    try {
      stat = await lstat(current);
    } catch (error) {
      throw new Error(`${label} is missing from the OpenWiki build.`, {
        cause: error,
      });
    }
    if (stat.isSymbolicLink()) {
      throw new Error(`${label} cannot contain a symbolic link or junction.`);
    }
    if (current === filePath && !stat.isFile()) {
      throw new Error(`${label} must be a regular file.`);
    }
  }
}
