import { createHash } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { TOOL_NAMES, type ToolName } from "./contracts.js";
import type { C7CapabilityGate } from "./server.js";

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const matrixEntrySchema = z.strictObject({
  capabilities: z.array(z.string().regex(/^[a-z][a-z0-9.-]+$/u)).min(1),
  implementation: z.string().min(1),
  name: z.enum(TOOL_NAMES),
  schema: z.string().min(1),
  tests: z.array(z.string().min(1)).min(1),
});
const matrixSchema = z.strictObject({
  tools: z.array(matrixEntrySchema).length(TOOL_NAMES.length),
  version: z.literal(1),
});
const fingerprintSchema = z.strictObject({
  buildHash: hashSchema,
  codeHash: hashSchema,
  contractsHash: hashSchema,
  dependencyHash: hashSchema,
  matrixHash: hashSchema,
  skillHash: hashSchema,
  testHash: hashSchema,
  verifierHash: hashSchema,
});
const evidenceSchema = z.strictObject({
  arch: z.string().min(1),
  buildId: z.string().uuid(),
  fingerprint: fingerprintSchema,
  generatedBy: z.literal("scripts/verify-capabilities.mts"),
  node: z.string().min(1),
  platform: z.string().min(1),
  reports: z.strictObject({
    build: z.literal("passed"),
    skillEval: z.literal("passed"),
    tests: z.literal("passed"),
    win32Integration: z.literal("passed"),
  }),
  tools: z.array(z.enum(TOOL_NAMES)).length(TOOL_NAMES.length),
  verifiedAt: z.string().datetime({ offset: true }),
  verifierVersion: z.literal(1),
  version: z.literal(1),
});

export type CapabilityFingerprint = z.infer<typeof fingerprintSchema>;

export type VerifiedCapabilityRecord = {
  readonly id: string;
  readonly verifiedAt: string;
};

export class RuntimeCapabilityGate implements C7CapabilityGate {
  constructor(
    private readonly matrix: z.infer<typeof matrixSchema> | undefined,
    private readonly evidence: z.infer<typeof evidenceSchema> | undefined,
    readonly failureReason?: string,
  ) {}

  isToolVerified(name: ToolName): boolean {
    return (
      this.matrix !== undefined &&
      this.evidence !== undefined &&
      this.evidence.tools.includes(name)
    );
  }

  records(): readonly VerifiedCapabilityRecord[] {
    if (!this.matrix || !this.evidence) return [];
    const ids = new Set<string>();
    for (const tool of this.matrix.tools) {
      for (const capability of tool.capabilities) ids.add(capability);
    }
    return [...ids]
      .sort()
      .map((id) => ({ id, verifiedAt: this.evidence!.verifiedAt }));
  }
}

export async function loadRuntimeCapabilityGate(options: {
  computeFingerprint?(input: {
    openWikiRoot: string;
    repositoryRoot: string;
  }): Promise<CapabilityFingerprint>;
  evidencePath: string;
  openWikiRoot: string;
  repositoryRoot: string;
}): Promise<RuntimeCapabilityGate> {
  try {
    const matrixPath = path.join(
      options.repositoryRoot,
      "config",
      "capability-matrix.json",
    );
    const matrix = matrixSchema.parse(
      JSON.parse(await readFile(matrixPath, "utf8")),
    );
    await validateMatrix(matrix, options.repositoryRoot);
    const evidence = evidenceSchema.parse(
      JSON.parse(await readFile(options.evidencePath, "utf8")),
    );
    if (
      evidence.platform !== process.platform ||
      evidence.arch !== process.arch ||
      evidence.node !== process.version ||
      !sameOrderedValues(evidence.tools, TOOL_NAMES)
    ) {
      throw new Error("Capability evidence host or tool set does not match.");
    }
    const current = await (
      options.computeFingerprint ?? computeCapabilityFingerprint
    )({
      openWikiRoot: options.openWikiRoot,
      repositoryRoot: options.repositoryRoot,
    });
    if (!sameFingerprint(current, evidence.fingerprint)) {
      throw new Error("Capability evidence is stale.");
    }
    return new RuntimeCapabilityGate(matrix, evidence);
  } catch {
    return new RuntimeCapabilityGate(
      undefined,
      undefined,
      "Capability evidence is missing, invalid, or stale.",
    );
  }
}

export async function computeCapabilityFingerprint(options: {
  openWikiRoot: string;
  repositoryRoot: string;
}): Promise<CapabilityFingerprint> {
  const repositoryRoot = path.resolve(options.repositoryRoot);
  const openWikiRoot = path.resolve(options.openWikiRoot);
  const codeHash = await hashPathSet(repositoryRoot, [
    "mcp-server/src",
    "config/defaults.json",
    "config/sensitive-files.json",
    "config/trusted-skills.json",
    "config/personal-openwiki-compatibility.json",
    "openwiki-skills",
    ...(await optionalRelativePaths(repositoryRoot, ["agent-skills"])),
  ]);
  const upstreamCodeHash = await hashPathSet(
    openWikiRoot,
    await optionalRelativePaths(openWikiRoot, [
      "src/integrations/core/protocol.ts",
      "src/integrations/core/session-manager.ts",
      "src/integrations/mcp/server.ts",
      "src/claims/core/types.ts",
      "src/claims/core/mutations.ts",
      "src/claims/brains/code/preflight.ts",
      "src/generation/repository-run.ts",
      "src/generation/run-state.ts",
      "src/version.ts",
      "src/cli/cli.tsx",
    ]),
  );
  const buildHash = await hashPathSet(repositoryRoot, [
    "mcp-server/dist",
    "win32-helper/dist/SelfOpenWiki.Win32Helper.exe",
  ]);
  const upstreamBuildHash = await hashPathSet(
    openWikiRoot,
    await optionalRelativePaths(openWikiRoot, [
      "dist/integrations/core/protocol.js",
      "dist/integrations/core/session-manager.js",
      "dist/integrations/mcp/server.js",
      "dist/claims/core/types.js",
      "dist/generation/repository-run.js",
      "dist/generation/run-state.js",
      "dist/version.js",
      "dist/cli/cli.js",
    ]),
  );
  return {
    buildHash: combineHashes("kg-c7-build-v1", [buildHash, upstreamBuildHash]),
    codeHash: combineHashes("kg-c7-code-v1", [codeHash, upstreamCodeHash]),
    contractsHash: await hashPathSet(repositoryRoot, [
      "mcp-server/src/contracts.ts",
    ]),
    dependencyHash: await hashPathSet(repositoryRoot, [
      "mcp-server/package.json",
      "mcp-server/pnpm-lock.yaml",
    ]),
    matrixHash: await hashPathSet(repositoryRoot, [
      "config/capability-matrix.json",
    ]),
    skillHash: await hashPathSet(repositoryRoot, [
      "config/trusted-skills.json",
      "config/personal-openwiki-compatibility.json",
      "openwiki-skills",
    ]),
    testHash: await hashPathSet(repositoryRoot, [
      "mcp-server/test",
      "mcp-server/vitest.config.ts",
    ]),
    verifierHash: await hashPathSet(repositoryRoot, [
      "mcp-server/scripts/smoke-mcp.mjs",
      "scripts/verify-capabilities.mts",
    ]),
  };
}

export async function validateCapabilityMatrix(options: {
  repositoryRoot: string;
}): Promise<void> {
  const matrix = matrixSchema.parse(
    JSON.parse(
      await readFile(
        path.join(options.repositoryRoot, "config", "capability-matrix.json"),
        "utf8",
      ),
    ),
  );
  await validateMatrix(matrix, options.repositoryRoot);
}

async function validateMatrix(
  matrix: z.infer<typeof matrixSchema>,
  repositoryRoot: string,
): Promise<void> {
  if (
    !sameOrderedValues(
      matrix.tools.map((tool) => tool.name),
      TOOL_NAMES,
    )
  ) {
    throw new Error("Capability matrix tool order or coverage is invalid.");
  }
  const capabilities = new Set<string>();
  for (const tool of matrix.tools) {
    for (const capability of tool.capabilities) {
      if (capabilities.has(capability)) {
        throw new Error("Capability matrix contains duplicate capability ids.");
      }
      capabilities.add(capability);
    }
    await Promise.all([
      assertAnchoredFile(repositoryRoot, tool.implementation),
      assertAnchoredFile(repositoryRoot, tool.schema),
      ...tool.tests.map((testPath) =>
        assertRegularFile(repositoryRoot, testPath),
      ),
    ]);
  }
}

async function assertAnchoredFile(
  root: string,
  reference: string,
): Promise<void> {
  const [relativePath, anchor] = reference.split("#");
  if (!relativePath || !anchor) throw new Error("Invalid matrix reference.");
  await assertRegularFile(root, relativePath);
  const text = await readFile(path.join(root, relativePath), "utf8");
  if (!text.includes(anchor))
    throw new Error("Unknown matrix implementation anchor.");
}

async function assertRegularFile(
  root: string,
  relativePath: string,
): Promise<void> {
  const absolutePath = contained(root, relativePath);
  const stat = await lstat(absolutePath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error("Capability matrix references a non-regular file.");
  }
}

async function hashPathSet(
  root: string,
  relativePaths: readonly string[],
): Promise<string> {
  const files: Array<{ bytes: Buffer; relativePath: string }> = [];
  for (const relativePath of relativePaths) {
    const absolutePath = contained(root, relativePath);
    await collectFiles(root, absolutePath, files);
  }
  files.sort((left, right) =>
    left.relativePath < right.relativePath
      ? -1
      : left.relativePath > right.relativePath
        ? 1
        : 0,
  );
  const seen = new Set<string>();
  const hasher = createHash("sha256");
  hasher.update("kg-c7-capability-path-set-v1\0", "utf8");
  for (const file of files) {
    if (seen.has(file.relativePath)) continue;
    seen.add(file.relativePath);
    hasher.update(file.relativePath, "utf8");
    hasher.update("\0", "ascii");
    hasher.update(String(file.bytes.byteLength), "ascii");
    hasher.update("\0", "ascii");
    hasher.update(file.bytes);
    hasher.update("\0", "ascii");
  }
  return `sha256:${hasher.digest("hex")}`;
}

async function collectFiles(
  root: string,
  current: string,
  files: Array<{ bytes: Buffer; relativePath: string }>,
): Promise<void> {
  const stat = await lstat(current);
  if (stat.isSymbolicLink())
    throw new Error("Capability inputs cannot contain links.");
  if (stat.isFile()) {
    files.push({
      bytes: await readFile(current),
      relativePath: path.relative(root, current).split(path.sep).join("/"),
    });
    return;
  }
  if (!stat.isDirectory())
    throw new Error("Capability inputs must be regular.");
  const entries = await readdir(current, { withFileTypes: true });
  entries.sort((left, right) => (left.name < right.name ? -1 : 1));
  for (const entry of entries) {
    await collectFiles(root, path.join(current, entry.name), files);
  }
}

async function optionalRelativePaths(
  root: string,
  candidates: readonly string[],
): Promise<string[]> {
  const present: string[] = [];
  for (const candidate of candidates) {
    try {
      await lstat(contained(root, candidate));
      present.push(candidate);
    } catch (error) {
      if (!isMissing(error)) throw error;
    }
  }
  return present;
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}

function contained(root: string, relativePath: string): string {
  if (path.isAbsolute(relativePath)) throw new Error("Path must be relative.");
  const candidate = path.resolve(root, relativePath);
  const relative = path.relative(root, candidate);
  if (
    relative === "" ||
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new Error("Capability path escapes its root.");
  }
  return candidate;
}

function combineHashes(domain: string, hashes: readonly string[]): string {
  const hasher = createHash("sha256");
  hasher.update(`${domain}\0`, "utf8");
  for (const hash of hashes) {
    hasher.update(hash, "ascii");
    hasher.update("\0", "ascii");
  }
  return `sha256:${hasher.digest("hex")}`;
}

function sameOrderedValues(
  left: readonly string[],
  right: readonly string[],
): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

function sameFingerprint(
  left: CapabilityFingerprint,
  right: CapabilityFingerprint,
): boolean {
  return (
    Object.keys(fingerprintSchema.shape) as Array<keyof CapabilityFingerprint>
  ).every((key) => left[key] === right[key]);
}
