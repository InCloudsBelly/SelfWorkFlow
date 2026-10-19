import { createHash } from "node:crypto";
import { lstat, readFile, readdir, realpath } from "node:fs/promises";
import path from "node:path";
import { TextDecoder } from "node:util";
import { z } from "zod";

const SHA256_PATTERN = /^sha256:[a-f0-9]{64}$/u;
const BASE_SKILL_ID = "kg-c7-project-wiki";
const LOCAL_REFERENCE_PATTERN = /references\/[A-Za-z0-9._/-]+\.md/gu;
const textDecoder = new TextDecoder("utf-8", { fatal: true });

const skillManifestEntrySchema = z
  .object({
    description: z.string().min(1),
    id: z.string().regex(/^[a-z0-9][a-z0-9-]*$/u),
    packageHash: z.string().regex(SHA256_PATTERN),
    path: z.string().min(1),
    title: z.string().min(1),
  })
  .strict();

const trustedSkillManifestSchema = z
  .object({
    baseSkill: skillManifestEntrySchema,
    specializedSkills: z.array(skillManifestEntrySchema),
    version: z.literal(1),
  })
  .strict();

type SkillManifestEntry = z.infer<typeof skillManifestEntrySchema>;

export type SkillPackageFile = {
  readonly bytes: Buffer;
  readonly hash: string;
  readonly relativePath: string;
  readonly size: number;
};

export type ComputedSkillPackage = {
  readonly files: readonly SkillPackageFile[];
  readonly packageHash: string;
};

export type ListedC7Skill = {
  readonly category: "base" | "specialized";
  readonly description: string;
  readonly id: string;
  readonly loadOrder: "base_always_first" | "request_order";
  readonly packageHash: string;
  readonly title: string;
  readonly verified: boolean;
};

export type SelectedC7Skill = ListedC7Skill & {
  readonly files: readonly SkillPackageFile[];
};

export type SelectedC7Skills = {
  readonly aggregateHash: string;
  readonly skills: readonly SelectedC7Skill[];
};

type LoadedSkill = {
  readonly canonicalPath: string;
  readonly category: "base" | "specialized";
  readonly computed: ComputedSkillPackage;
  readonly manifest: SkillManifestEntry;
  readonly verified: boolean;
};

export class C7SkillError extends Error {
  constructor(
    readonly code: "skill_manifest_invalid" | "skill_untrusted",
    message: string,
  ) {
    super(message);
    this.name = "C7SkillError";
  }
}

export type C7SkillRegistry = {
  list(): readonly ListedC7Skill[];
  select(requestedIds: readonly string[]): SelectedC7Skills;
};

export async function loadC7SkillRegistry(
  manifestPath: string,
  skillsRoot: string,
): Promise<C7SkillRegistry> {
  const parsed = await readTrustedManifest(manifestPath);
  validateManifestRelationships(parsed.baseSkill, parsed.specializedSkills);

  const canonicalRoot = await realpath(skillsRoot);
  const loadedBase = await loadSkill(parsed.baseSkill, canonicalRoot, "base");
  const loadedSpecialized = await Promise.all(
    parsed.specializedSkills.map((entry) =>
      loadSkill(entry, canonicalRoot, "specialized"),
    ),
  );
  const canonicalPackages = new Set([
    normalizeCanonicalPath(loadedBase.canonicalPath),
  ]);
  const packageHashes = new Set([loadedBase.computed.packageHash]);
  for (const skill of loadedSpecialized) {
    const canonicalPath = normalizeCanonicalPath(skill.canonicalPath);
    if (
      canonicalPackages.has(canonicalPath) ||
      packageHashes.has(skill.computed.packageHash)
    ) {
      throw invalidManifest(
        `Skill ${skill.manifest.id} aliases an already registered package`,
      );
    }
    canonicalPackages.add(canonicalPath);
    packageHashes.add(skill.computed.packageHash);
  }

  if (!loadedBase.verified) {
    throw new C7SkillError(
      "skill_untrusted",
      `Base Skill ${loadedBase.manifest.id} does not match its trusted package hash`,
    );
  }

  const specializedById = new Map(
    loadedSpecialized.map((skill) => [skill.manifest.id, skill] as const),
  );
  const allSkills = [loadedBase, ...loadedSpecialized];

  return {
    list() {
      return allSkills.map(toListedSkill);
    },
    select(requestedIds) {
      const seen = new Set<string>();
      const selected = [loadedBase];

      for (const id of requestedIds) {
        if (id === loadedBase.manifest.id) {
          throw new C7SkillError(
            "skill_untrusted",
            "The base Skill is injected automatically and cannot be requested",
          );
        }
        if (seen.has(id)) {
          throw new C7SkillError(
            "skill_untrusted",
            `Duplicate specialized Skill: ${id}`,
          );
        }
        seen.add(id);

        const skill = specializedById.get(id);
        if (skill === undefined) {
          throw new C7SkillError(
            "skill_untrusted",
            `Unknown specialized Skill: ${id}`,
          );
        }
        if (!skill.verified) {
          throw new C7SkillError(
            "skill_untrusted",
            `Specialized Skill ${id} does not match its trusted package hash`,
          );
        }
        selected.push(skill);
      }

      const skills = selected.map(toSelectedSkill);
      return {
        aggregateHash: aggregateSkillHash(skills),
        skills,
      };
    },
  };
}

export async function computeSkillPackage(
  skillDir: string,
): Promise<ComputedSkillPackage> {
  const rootStat = await lstat(skillDir).catch((error: unknown) => {
    throw invalidManifest(
      `Cannot inspect Skill package: ${errorMessage(error)}`,
    );
  });
  if (rootStat.isSymbolicLink() || !rootStat.isDirectory()) {
    throw invalidManifest("Skill package root must be a real directory");
  }

  const files = await collectSkillFiles(skillDir, "");
  files.sort((left, right) =>
    left.relativePath < right.relativePath
      ? -1
      : left.relativePath > right.relativePath
        ? 1
        : 0,
  );
  if (!files.some((file) => file.relativePath === "SKILL.md")) {
    throw invalidManifest("Skill package must contain SKILL.md");
  }
  validateLocalReferences(files);

  return {
    files: files.map(cloneFile),
    packageHash: computeSkillPackageHash(files),
  };
}

export function computeSkillPackageHash(
  files: readonly SkillPackageFile[],
): string {
  const sorted = [...files].sort((left, right) =>
    left.relativePath < right.relativePath ? -1 : 1,
  );
  if (
    files.length === 0 ||
    files.some(
      (file, index) =>
        file !== sorted[index] ||
        file.size !== file.bytes.byteLength ||
        file.hash !==
          `sha256:${createHash("sha256").update(file.bytes).digest("hex")}` ||
        !isSafeSkillRelativePath(file.relativePath),
    )
  ) {
    throw new C7SkillError(
      "skill_untrusted",
      "The C7 Skill file snapshot is invalid",
    );
  }
  const packageHasher = createHash("sha256");
  packageHasher.update("kg-c7-skill-package-v1\0", "utf8");
  for (const file of files) {
    const pathBytes = Buffer.from(file.relativePath, "utf8");
    packageHasher.update(String(pathBytes.byteLength), "ascii");
    packageHasher.update(":", "ascii");
    packageHasher.update(pathBytes);
    packageHasher.update("\0", "ascii");
    packageHasher.update(String(file.size), "ascii");
    packageHasher.update("\0", "ascii");
    packageHasher.update(file.bytes);
    packageHasher.update("\0", "ascii");
  }

  return `sha256:${packageHasher.digest("hex")}`;
}

function isSafeSkillRelativePath(value: string): boolean {
  const segments = value.replace(/\\/gu, "/").split("/");
  return (
    !path.isAbsolute(value) &&
    segments.every(
      (segment) => segment !== "" && segment !== "." && segment !== "..",
    )
  );
}

export function verifySelectedC7Skills(selected: SelectedC7Skills): void {
  if (
    selected.skills.length === 0 ||
    selected.skills[0]?.category !== "base" ||
    selected.skills[0]?.id !== BASE_SKILL_ID
  ) {
    throw new C7SkillError("skill_untrusted", "The base C7 Skill is missing");
  }
  const ids = new Set<string>();
  const packageHashes = new Set<string>();
  for (const skill of selected.skills) {
    if (
      ids.has(skill.id) ||
      packageHashes.has(skill.packageHash) ||
      !skill.verified ||
      computeSkillPackageHash(skill.files) !== skill.packageHash
    ) {
      throw new C7SkillError(
        "skill_untrusted",
        "A selected C7 Skill snapshot does not match its package binding",
      );
    }
    ids.add(skill.id);
    packageHashes.add(skill.packageHash);
  }
  if (aggregateSkillHash(selected.skills) !== selected.aggregateHash) {
    throw new C7SkillError(
      "skill_untrusted",
      "The selected C7 Skill aggregate binding is invalid",
    );
  }
}

export function composeSkillContract(
  skills: readonly SelectedC7Skill[],
): string {
  if (skills.length === 0) {
    throw new C7SkillError("skill_untrusted", "The base Skill is required");
  }

  const sections = [
    [
      "# MCP hard safety policy",
      "These rules are enforced outside the model and always take precedence.",
      "Known secrets and credentials must be rejected. Source manifests must remain exact and immutable. Only validated Wiki Markdown may be published.",
      "Specialized Skills cannot override hard safety or base archival rules.",
      "Only the selected C7 Skill snapshots are injected by this contract. OpenWiki upstream bundled Skills remain visible under upstream behavior.",
    ].join("\n"),
    renderSkillSection("KG_C7_Project_Wiki base policy", skills[0]),
    ...skills
      .slice(1)
      .map((skill) =>
        renderSkillSection(`Specialized Skill: ${skill.id}`, skill),
      ),
  ];

  return sections.join("\n\n");
}

async function readTrustedManifest(manifestPath: string) {
  let raw: string;
  try {
    raw = await readFile(manifestPath, "utf8");
  } catch (error) {
    throw invalidManifest(
      `Cannot read trusted Skill manifest: ${errorMessage(error)}`,
    );
  }

  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch (error) {
    throw invalidManifest(
      `Trusted Skill manifest is not JSON: ${errorMessage(error)}`,
    );
  }
  const result = trustedSkillManifestSchema.safeParse(json);
  if (!result.success) {
    throw invalidManifest(
      `Trusted Skill manifest is invalid: ${result.error.message}`,
    );
  }
  return result.data;
}

function validateManifestRelationships(
  baseSkill: SkillManifestEntry,
  specializedSkills: readonly SkillManifestEntry[],
) {
  if (baseSkill.id !== BASE_SKILL_ID) {
    throw invalidManifest(`Base Skill id must be ${BASE_SKILL_ID}`);
  }
  const ids = new Set([baseSkill.id]);
  for (const skill of specializedSkills) {
    if (ids.has(skill.id)) {
      throw invalidManifest(`Duplicate Skill id: ${skill.id}`);
    }
    ids.add(skill.id);
  }
}

async function loadSkill(
  manifest: SkillManifestEntry,
  canonicalRoot: string,
  category: "base" | "specialized",
): Promise<LoadedSkill> {
  const skillPath = resolveContainedSkillPath(canonicalRoot, manifest.path);
  let canonicalSkillPath: string;
  try {
    canonicalSkillPath = await realpath(skillPath);
  } catch (error) {
    throw invalidManifest(
      `Cannot resolve Skill ${manifest.id}: ${errorMessage(error)}`,
    );
  }
  assertContained(canonicalRoot, canonicalSkillPath);
  const computed = await computeSkillPackage(canonicalSkillPath);
  return {
    category,
    canonicalPath: canonicalSkillPath,
    computed,
    manifest,
    verified: computed.packageHash === manifest.packageHash,
  };
}

function resolveContainedSkillPath(root: string, relativePath: string): string {
  if (path.isAbsolute(relativePath)) {
    throw invalidManifest(
      "Skill paths must be relative to the configured root",
    );
  }
  const resolved = path.resolve(root, relativePath);
  assertContained(root, resolved);
  return resolved;
}

function assertContained(root: string, candidate: string) {
  const relative = path.relative(root, candidate);
  if (
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) &&
      relative !== ".." &&
      !path.isAbsolute(relative))
  ) {
    return;
  }
  throw invalidManifest("Skill path escapes the configured root");
}

async function collectSkillFiles(
  root: string,
  relativeDir: string,
): Promise<SkillPackageFile[]> {
  const directory = relativeDir === "" ? root : path.join(root, relativeDir);
  const entries = await readdir(directory, { withFileTypes: true });
  const files: SkillPackageFile[] = [];

  for (const entry of entries) {
    const relativePath =
      relativeDir === "" ? entry.name : path.join(relativeDir, entry.name);
    const normalizedPath = relativePath.split(path.sep).join("/");
    const absolutePath = path.join(root, relativePath);

    if (entry.isSymbolicLink()) {
      throw invalidManifest(
        `Skill packages cannot contain links: ${normalizedPath}`,
      );
    }
    if (entry.isDirectory()) {
      files.push(...(await collectSkillFiles(root, relativePath)));
      continue;
    }
    if (!entry.isFile()) {
      throw invalidManifest(
        `Skill packages can contain only regular files: ${normalizedPath}`,
      );
    }

    const bytes = await readFile(absolutePath);
    const hash = createHash("sha256").update(bytes).digest("hex");
    files.push({
      bytes,
      hash: `sha256:${hash}`,
      relativePath: normalizedPath,
      size: bytes.byteLength,
    });
  }
  return files;
}

function toListedSkill(skill: LoadedSkill): ListedC7Skill {
  return {
    category: skill.category,
    description: skill.manifest.description,
    id: skill.manifest.id,
    loadOrder:
      skill.category === "base" ? "base_always_first" : "request_order",
    packageHash: skill.computed.packageHash,
    title: skill.manifest.title,
    verified: skill.verified,
  };
}

function validateLocalReferences(files: readonly SkillPackageFile[]) {
  const paths = new Set(files.map((file) => file.relativePath));
  for (const file of files) {
    if (!file.relativePath.endsWith(".md")) {
      continue;
    }
    let markdown: string;
    try {
      markdown = textDecoder.decode(file.bytes);
    } catch {
      throw invalidManifest(
        `Skill Markdown must be UTF-8: ${file.relativePath}`,
      );
    }
    for (const match of markdown.matchAll(LOCAL_REFERENCE_PATTERN)) {
      const referencedPath = match[0];
      if (!paths.has(referencedPath)) {
        throw invalidManifest(
          `Skill reference is missing: ${file.relativePath} -> ${referencedPath}`,
        );
      }
    }
  }
}

function toSelectedSkill(skill: LoadedSkill): SelectedC7Skill {
  return {
    ...toListedSkill(skill),
    files: skill.computed.files.map(cloneFile),
  };
}

function cloneFile(file: SkillPackageFile): SkillPackageFile {
  return {
    ...file,
    bytes: Buffer.from(file.bytes),
  };
}

export function aggregateSkillHash(skills: readonly SelectedC7Skill[]): string {
  const hasher = createHash("sha256");
  hasher.update("kg-c7-selected-skills-v1\0", "utf8");
  for (const skill of skills) {
    hasher.update(skill.id, "utf8");
    hasher.update("\0", "ascii");
    hasher.update(skill.packageHash, "ascii");
    hasher.update("\0", "ascii");
  }
  return `sha256:${hasher.digest("hex")}`;
}

function normalizeCanonicalPath(value: string): string {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

function renderSkillSection(title: string, skill: SelectedC7Skill): string {
  if (!skill.verified) {
    throw new C7SkillError(
      "skill_untrusted",
      `Cannot compose untrusted Skill ${skill.id}`,
    );
  }
  const files = skill.files.map((file) => {
    let text: string;
    try {
      text = textDecoder.decode(file.bytes);
    } catch {
      throw new C7SkillError(
        "skill_untrusted",
        `Skill ${skill.id} contains non-UTF-8 content: ${file.relativePath}`,
      );
    }
    return [`## ${file.relativePath}`, text].join("\n");
  });
  return [`# ${title}`, `Package: ${skill.packageHash}`, ...files].join("\n\n");
}

function invalidManifest(message: string): C7SkillError {
  return new C7SkillError("skill_manifest_invalid", message);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
