import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { lstat, readFile } from "node:fs/promises";
import path from "node:path";
import { TextDecoder } from "node:util";
import { z } from "zod";
import { computeSkillPackage } from "./skills.js";
import {
  TOOL_NAMES,
  toolAnnotations,
  toolInputSchemas,
  toolOutputSchemas,
} from "./contracts.js";
import { toolDescriptions } from "./server.js";
import { canonicalPersonalJson } from "./personal-wiki-lifecycle.js";
import type {
  PersonalSkillAdapter as PersonalSkillAdapterPort,
  PersonalSkillBinding,
} from "./personal-wiki-lifecycle.js";

const PERSONAL_SKILL_ID = "self-openwiki";
const BASE_SKILL_ID = "kg-c7-project-wiki";
const REGISTERED_PERSONAL_SKILLS = new Set([
  "kg-c7-project-wiki",
  "personal-wiki",
]);
export const PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT =
  "d1c7fc75a6a906da258cd94dbcb1602f98516480";
const textDecoder = new TextDecoder("utf-8", { fatal: true });
const compatibilityHashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const toolBindingSchema = z.strictObject({
  annotationHash: compatibilityHashSchema,
  descriptionHash: compatibilityHashSchema,
  implementation: z.string().min(1),
  inputHash: compatibilityHashSchema,
  outputHash: compatibilityHashSchema,
});
const compatibilityManifestSchema = z.strictObject({
  build: z.strictObject({
    adapterSetHash: compatibilityHashSchema,
    generatedMarkerHash: compatibilityHashSchema,
    lockfileHash: compatibilityHashSchema,
    parentCommit: z.string().regex(/^[a-f0-9]{40}$/u),
    parentSourceManifestHash: compatibilityHashSchema,
  }),
  c7: z.strictObject({
    publisherVersion: z.string().min(1),
    transactionVersion: z.string().min(1),
  }),
  capabilities: z.array(z.unknown()).min(1),
  discoveryOrder: z.array(z.string().min(1)).min(1),
  protocol: z.strictObject({
    adapted: z.literal("selfopenwiki:personal-openwiki-v1"),
    official: z.literal("openwiki-repository-v0.5"),
  }),
  schemaVersion: z.literal(2),
  skill: z.strictObject({
    composition: z.array(z.string().min(1)).min(1),
    id: z.literal("self-openwiki"),
    packageHash: compatibilityHashSchema,
    path: z.literal("self-openwiki/agent-skills/self-openwiki"),
    version: z.literal("2.0.0"),
  }),
  toolBindings: z.record(z.string(), toolBindingSchema),
  upstream: z.strictObject({
    commit: z.string().regex(/^[a-f0-9]{40}$/u),
    packageVersion: z.string().min(1),
    url: z.literal("https://github.com/langchain-ai/openwiki.git"),
  }),
});

const PERSONAL_TOOL_NAMES = [
  "openwiki_begin",
  "openwiki_submit_plan",
  "openwiki_next_page",
  "openwiki_inspect_page_claims",
  "openwiki_submit_page",
  "openwiki_finish",
] as const;
const ADAPTER_SOURCE_PATHS = [
  "mcp-server/src/contracts.ts",
  "mcp-server/src/external-update-state.ts",
  "mcp-server/src/external-update-transaction.ts",
  "mcp-server/src/official-lifecycle-adapter.ts",
  "mcp-server/src/personal-candidate-marker.ts",
  "mcp-server/src/personal-claims.ts",
  "mcp-server/src/personal-run-store.ts",
  "mcp-server/src/personal-wiki-snapshot.ts",
  "mcp-server/src/personal-skill-adapter.ts",
  "mcp-server/src/personal-wiki-lifecycle.ts",
  "mcp-server/src/personal-wiki-root.ts",
  "mcp-server/src/publish.ts",
  "mcp-server/src/recovery.ts",
  "mcp-server/src/runtime.ts",
  "mcp-server/src/server.ts",
  "mcp-server/src/transaction.ts",
  "mcp-server/src/transaction-recovery.ts",
] as const;

export type PersonalCompatibilityManifest = z.infer<
  typeof compatibilityManifestSchema
>;

const PERSONAL_TOOL_IMPLEMENTATIONS = {
  openwiki_begin: "mcp-server/src/official-lifecycle-adapter.ts#begin",
  openwiki_submit_plan:
    "mcp-server/src/official-lifecycle-adapter.ts#submitPlan",
  openwiki_next_page: "mcp-server/src/official-lifecycle-adapter.ts#nextPage",
  openwiki_inspect_page_claims:
    "mcp-server/src/official-lifecycle-adapter.ts#inspectPageClaims",
  openwiki_submit_page:
    "mcp-server/src/official-lifecycle-adapter.ts#submitPage",
  openwiki_finish: "mcp-server/src/official-lifecycle-adapter.ts#finish",
} as const;

export function computePersonalToolBindings(): PersonalCompatibilityManifest["toolBindings"] {
  return Object.fromEntries(
    PERSONAL_TOOL_NAMES.map((name) => [
      name,
      {
        annotationHash: hashCanonicalValue(toolAnnotations[name]),
        descriptionHash: hashCanonicalValue(toolDescriptions[name]),
        implementation: PERSONAL_TOOL_IMPLEMENTATIONS[name],
        inputHash: hashCanonicalValue(z.toJSONSchema(toolInputSchemas[name])),
        outputHash: hashCanonicalValue(z.toJSONSchema(toolOutputSchemas[name])),
      },
    ]),
  );
}

export async function loadPersonalCompatibilityManifest(
  repositoryRoot: string,
): Promise<PersonalCompatibilityManifest> {
  const manifestPath = path.join(
    path.resolve(repositoryRoot),
    "config",
    "personal-openwiki-compatibility.json",
  );
  const bytes = await readFile(manifestPath);
  const text = textDecoder.decode(bytes);
  const parsed = JSON.parse(text);
  if (text !== `${canonicalPersonalJson(parsed)}\n`) {
    throw new Error("The personal compatibility manifest is not canonical.");
  }
  return compatibilityManifestSchema.parse(parsed);
}

export async function assertPersonalCompatibility(
  manifest: PersonalCompatibilityManifest,
  expectedUpstreamCommit: string,
  toolNames: readonly string[],
  options: {
    expectedModuleHasherHash: string;
    openWikiRoot: string;
    repositoryRoot: string;
  },
): Promise<void> {
  if (manifest.upstream.commit !== expectedUpstreamCommit) {
    throw new Error("Personal compatibility upstream revision is stale.");
  }
  if (
    manifest.discoveryOrder.length !== toolNames.length ||
    manifest.discoveryOrder.some((name, index) => name !== toolNames[index])
  ) {
    throw new Error("Personal compatibility discovery order is stale.");
  }
  const expectedPersonalTools = [...PERSONAL_TOOL_NAMES];
  if (
    Object.keys(manifest.toolBindings).length !==
      expectedPersonalTools.length ||
    expectedPersonalTools.some(
      (name) => manifest.toolBindings[name] === undefined,
    )
  ) {
    throw new Error("Personal compatibility tool bindings are incomplete.");
  }
  const packageJson = JSON.parse(
    await readFile(
      path.join(path.resolve(options.openWikiRoot), "package.json"),
      "utf8",
    ),
  ) as { version?: unknown };
  if (packageJson.version !== manifest.upstream.packageVersion) {
    throw new Error(
      "Personal compatibility OpenWiki package version is stale.",
    );
  }
  const skillPackage = await computeSkillPackage(
    path.join(
      path.resolve(options.repositoryRoot),
      "agent-skills",
      "self-openwiki",
    ),
  );
  if (manifest.skill.packageHash !== skillPackage.packageHash) {
    throw new Error("Personal compatibility Skill package hash is stale.");
  }
  const adapterSetHash = await computeAdapterSetHash(options.repositoryRoot);
  if (manifest.build.adapterSetHash !== adapterSetHash) {
    throw new Error("Personal compatibility adapter source hash is stale.");
  }
  const generatedMarkerHash = await hashFile(
    path.join(
      path.resolve(options.openWikiRoot),
      ".selfopenwiki-materialization.json",
    ),
  );
  if (manifest.build.generatedMarkerHash !== generatedMarkerHash) {
    throw new Error("Personal compatibility materialization marker is stale.");
  }
  const lockfileHash = await hashFile(
    path.join(
      path.resolve(options.repositoryRoot),
      "mcp-server",
      "pnpm-lock.yaml",
    ),
  );
  if (manifest.build.lockfileHash !== lockfileHash) {
    throw new Error("Personal compatibility lockfile hash is stale.");
  }
  const parentRoot = path.resolve(options.repositoryRoot, "..");
  // Parent commit and staging are provenance only; runtime binds module content.
  const parentSourceManifestHash = await computeModuleSourceManifestHash(
    parentRoot,
    options.expectedModuleHasherHash,
  );
  if (manifest.build.parentSourceManifestHash !== parentSourceManifestHash) {
    throw new Error("Personal compatibility parent source manifest is stale.");
  }
  for (const name of PERSONAL_TOOL_NAMES) {
    const binding = manifest.toolBindings[name];
    if (binding === undefined)
      throw new Error("Personal tool binding is missing.");
    const expected = computePersonalToolBindings()[name];
    if (canonicalPersonalJson(binding) !== canonicalPersonalJson(expected)) {
      throw new Error(
        `Personal compatibility implementation mapping is stale: ${name}.`,
      );
    }
    const [implementationPath, anchor] = binding.implementation.split("#");
    if (!implementationPath || !anchor) {
      throw new Error(
        `Personal compatibility implementation binding is invalid: ${name}.`,
      );
    }
    const source = await readFile(
      path.join(path.resolve(options.repositoryRoot), implementationPath),
      "utf8",
    );
    if (!source.includes(anchor)) {
      throw new Error(
        `Personal compatibility implementation anchor is stale: ${name}.`,
      );
    }
  }
}

export async function computeModuleSourceManifestHash(
  parentRoot: string,
  expectedModuleHasherHash: string,
): Promise<string> {
  const scriptPath = path.resolve(
    parentRoot,
    "scripts",
    "parent-source-manifest.mjs",
  );
  try {
    const stats = await lstat(scriptPath);
    if (!stats.isFile() || stats.isSymbolicLink() || stats.size > 1024 * 1024)
      throw new Error("The module hash helper is not a regular bounded file.");
    const trustedSource = await readFile(scriptPath);
    const trustedHash = `sha256:${createHash("sha256").update(trustedSource).digest("hex")}`;
    if (trustedHash !== expectedModuleHasherHash)
      throw new Error("The module hash helper changed after verification.");
    const invocation = Buffer.from(
      `\nprocess.stdout.write(JSON.stringify({hash:(await computeModuleSourceManifest(${JSON.stringify(path.resolve(parentRoot))})).hash})+"\\n");\n`,
    );
    const stdout = await new Promise<string>((resolve, reject) => {
      const child = spawn(process.execPath, ["--input-type=module", "-"], {
        env: sanitizedGitEnvironment(),
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      });
      const chunks: Buffer[] = [];
      let size = 0;
      child.stdout.on("data", (chunk: Buffer) => {
        size += chunk.byteLength;
        if (size > 16 * 1024 * 1024) {
          child.kill();
          reject(new Error("The module hash helper output is too large."));
        } else {
          chunks.push(chunk);
        }
      });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code !== 0) reject(new Error("The module hash helper failed."));
        else resolve(Buffer.concat(chunks).toString("utf8"));
      });
      child.stdin.on("error", reject);
      child.stdin.end(Buffer.concat([trustedSource, invocation]));
    });
    const parsed = JSON.parse(stdout) as { hash?: unknown };
    if (
      typeof parsed.hash !== "string" ||
      !/^sha256:[a-f0-9]{64}$/u.test(parsed.hash)
    ) {
      throw new Error(
        "The parent source manifest helper returned an invalid hash.",
      );
    }
    return parsed.hash;
  } catch (error) {
    throw new Error("The parent source manifest could not be verified.", {
      cause: error,
    });
  }
}

export async function computeAdapterSetHash(
  repositoryRoot: string,
): Promise<string> {
  const root = path.resolve(repositoryRoot);
  const entries = await Promise.all(
    [...ADAPTER_SOURCE_PATHS].map(async (relativePath) => {
      const bytes = await readFile(path.join(root, relativePath));
      const digest = createHash("sha256").update(bytes).digest();
      return { bytes, digest, relativePath };
    }),
  );
  entries.sort((left, right) =>
    Buffer.from(left.relativePath, "utf8").compare(
      Buffer.from(right.relativePath, "utf8"),
    ),
  );
  const hasher = createHash("sha256");
  hasher.update("selfopenwiki-adapter-set-v1\0", "utf8");
  for (const entry of entries) {
    const pathBytes = Buffer.from(entry.relativePath, "utf8");
    const length = Buffer.alloc(4);
    length.writeUInt32BE(pathBytes.byteLength, 0);
    hasher.update(length);
    hasher.update(pathBytes);
    hasher.update(entry.digest);
    const size = Buffer.alloc(8);
    size.writeBigUInt64BE(BigInt(entry.bytes.byteLength), 0);
    hasher.update(size);
  }
  return `sha256:${hasher.digest("hex")}`;
}

async function hashFile(filePath: string): Promise<string> {
  return `sha256:${createHash("sha256")
    .update(await readFile(filePath))
    .digest("hex")}`;
}

function hashCanonicalValue(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(canonicalPersonalJson(value), "utf8")
    .digest("hex")}`;
}

function sanitizedGitEnvironment(): NodeJS.ProcessEnv {
  const environment = { ...process.env };
  for (const key of [
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_ASKPASS",
    "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PROXY_COMMAND",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_WORK_TREE",
  ]) {
    delete environment[key];
  }
  const nullDevice = process.platform === "win32" ? "NUL" : "/dev/null";
  environment.GIT_CONFIG_COUNT = "0";
  environment.GIT_CONFIG_GLOBAL = nullDevice;
  environment.GIT_CONFIG_NOSYSTEM = "1";
  environment.GIT_CONFIG_SYSTEM = nullDevice;
  environment.GIT_OPTIONAL_LOCKS = "0";
  environment.GIT_TERMINAL_PROMPT = "0";
  return environment;
}

export class PersonalSkillError extends Error {
  constructor(
    readonly code: "skill_untrusted",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "PersonalSkillError";
  }
}

export class PersonalSkillAdapter implements PersonalSkillAdapterPort {
  private readonly expectedCompatibilityManifestHash: string | undefined;
  private readonly skillPath: string;
  private readonly upstreamCommit: string;
  private readonly expectedPackageHash: string | undefined;
  private readonly expectedBasePackageHash: string | undefined;

  constructor(options: {
    expectedCompatibilityManifestHash?: string;
    expectedPackageHash?: string;
    expectedBasePackageHash?: string;
    skillPath: string;
    upstreamCommit: string;
  }) {
    if (
      !path.isAbsolute(options.skillPath) ||
      options.upstreamCommit !== PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT
    ) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The personal Skill binding is not absolute and revision-bound.",
      );
    }
    this.skillPath = options.skillPath;
    this.upstreamCommit = options.upstreamCommit;
    if (
      options.expectedPackageHash !== undefined &&
      !/^sha256:[a-f0-9]{64}$/u.test(options.expectedPackageHash)
    ) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The personal Skill package hash is invalid.",
      );
    }
    this.expectedPackageHash = options.expectedPackageHash;
    if (
      options.expectedBasePackageHash !== undefined &&
      !/^sha256:[a-f0-9]{64}$/u.test(options.expectedBasePackageHash)
    ) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The base Skill package hash is invalid.",
      );
    }
    this.expectedBasePackageHash = options.expectedBasePackageHash;
    if (
      options.expectedCompatibilityManifestHash !== undefined &&
      !/^sha256:[a-f0-9]{64}$/u.test(options.expectedCompatibilityManifestHash)
    ) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The personal compatibility manifest hash is invalid.",
      );
    }
    this.expectedCompatibilityManifestHash =
      options.expectedCompatibilityManifestHash;
  }

  async resolve(
    requestedSkills: readonly string[],
  ): Promise<PersonalSkillBinding> {
    if (
      requestedSkills.some((id) => !/^[a-z][a-z0-9-]{0,127}$/u.test(id)) ||
      new Set(requestedSkills).size !== requestedSkills.length ||
      requestedSkills.some((id) => !REGISTERED_PERSONAL_SKILLS.has(id)) ||
      requestedSkills.includes(BASE_SKILL_ID)
    ) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The requested personal Skill is not registered in the adaptation layer.",
      );
    }
    const stat = await lstat(this.skillPath).catch((error: unknown) => {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The checked-in personal Skill is missing or unreadable.",
        { cause: error },
      );
    });
    if (!stat.isFile() || stat.isSymbolicLink()) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The checked-in personal Skill must be a regular non-link file.",
      );
    }
    const bytes = await readFile(this.skillPath).catch((error: unknown) => {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The checked-in personal Skill could not be read.",
        { cause: error },
      );
    });
    try {
      textDecoder.decode(bytes);
    } catch (error) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The checked-in personal Skill is not valid UTF-8.",
        { cause: error },
      );
    }
    const packageRoot = path.dirname(this.skillPath);
    const packageSnapshot = await computeSkillPackage(packageRoot).catch(
      (error: unknown) => {
        throw new PersonalSkillError(
          "skill_untrusted",
          "The personal Skill package is invalid.",
          { cause: error },
        );
      },
    );
    if (
      this.expectedPackageHash !== undefined &&
      packageSnapshot.packageHash !== this.expectedPackageHash
    ) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The personal Skill package does not match its compatibility binding.",
      );
    }
    const basePackage = await computeSkillPackage(
      path.resolve(packageRoot, "..", "..", "openwiki-skills", BASE_SKILL_ID),
    ).catch((error: unknown) => {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The pinned OpenWiki base Skill package is invalid.",
        { cause: error },
      );
    });
    if (
      this.expectedBasePackageHash !== undefined &&
      basePackage.packageHash !== this.expectedBasePackageHash
    ) {
      throw new PersonalSkillError(
        "skill_untrusted",
        "The base Skill package changed during this run.",
      );
    }
    const hasher = createHash("sha256");
    hasher.update("selfopenwiki:personal-skill-binding-v1\0", "utf8");
    hasher.update(this.upstreamCommit, "ascii");
    hasher.update("\0", "ascii");
    hasher.update(BASE_SKILL_ID, "utf8");
    hasher.update("\0", "ascii");
    hasher.update(basePackage.packageHash, "ascii");
    hasher.update("\0", "ascii");
    hasher.update(PERSONAL_SKILL_ID, "utf8");
    hasher.update("\0", "ascii");
    hasher.update(packageSnapshot.packageHash, "ascii");
    hasher.update("\0", "ascii");
    for (const id of requestedSkills) {
      hasher.update(id, "utf8");
      hasher.update("\0", "ascii");
    }
    hasher.update(String(bytes.byteLength), "ascii");
    hasher.update("\0", "ascii");
    hasher.update(bytes);
    return {
      ...(this.expectedCompatibilityManifestHash === undefined
        ? {}
        : {
            compatibilityManifestHash: this.expectedCompatibilityManifestHash,
          }),
      skillAggregateHash: `sha256:${hasher.digest("hex")}`,
      skillIds: [BASE_SKILL_ID, PERSONAL_SKILL_ID, ...requestedSkills],
    };
  }
}
