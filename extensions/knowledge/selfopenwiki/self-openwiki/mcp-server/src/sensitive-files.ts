import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

const sensitivePolicySchema = z.strictObject({
  contentPatterns: z.array(z.string().min(1).max(1_024)).max(128),
  rejectedBaseNames: z.array(z.string().min(1).max(256)).max(256),
  rejectedNamePrefixes: z.array(z.string().min(1).max(256)).max(256),
  rejectedPathSegments: z.array(z.string().min(1).max(256)).max(256),
  rejectedSuffixes: z.array(z.string().min(1).max(256)).max(256),
  version: z.literal(1),
});

export type SensitiveFilePolicy = {
  readonly contentPatterns: readonly RegExp[];
  readonly hash: string;
  readonly rejectedBaseNames: ReadonlySet<string>;
  readonly rejectedNamePrefixes: readonly string[];
  readonly rejectedPathSegments: ReadonlySet<string>;
  readonly rejectedSuffixes: readonly string[];
  readonly version: 1;
};

export class SensitiveSourceError extends Error {
  constructor(
    readonly code: "policy_invalid" | "source_rejected",
    message: string,
  ) {
    super(message);
    this.name = "SensitiveSourceError";
  }
}

export async function loadSensitiveFilePolicy(
  policyPath: string,
): Promise<SensitiveFilePolicy> {
  if (!path.isAbsolute(policyPath)) {
    throw new SensitiveSourceError(
      "policy_invalid",
      "The sensitive-file policy path must be absolute.",
    );
  }
  let bytes: Buffer;
  let value: unknown;
  try {
    bytes = await readFile(policyPath);
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new SensitiveSourceError(
      "policy_invalid",
      "The sensitive-file policy is missing or invalid.",
    );
  }
  const parsed = sensitivePolicySchema.safeParse(value);
  if (!parsed.success) {
    throw new SensitiveSourceError(
      "policy_invalid",
      "The sensitive-file policy does not match schema version 1.",
    );
  }
  let patterns: RegExp[];
  try {
    patterns = parsed.data.contentPatterns.map(
      (pattern) => new RegExp(pattern, "iu"),
    );
  } catch {
    throw new SensitiveSourceError(
      "policy_invalid",
      "The sensitive-file policy contains an invalid matcher.",
    );
  }
  return {
    contentPatterns: patterns,
    hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
    rejectedBaseNames: new Set(
      parsed.data.rejectedBaseNames.map((value) => value.toLowerCase()),
    ),
    rejectedNamePrefixes: parsed.data.rejectedNamePrefixes.map((value) =>
      value.toLowerCase(),
    ),
    rejectedPathSegments: new Set(
      parsed.data.rejectedPathSegments.map((value) => value.toLowerCase()),
    ),
    rejectedSuffixes: parsed.data.rejectedSuffixes.map((value) =>
      value.toLowerCase(),
    ),
    version: 1,
  };
}

export function assertSourcePathNotSensitive(
  sourcePath: string,
  policy: SensitiveFilePolicy,
): void {
  const segments = path
    .normalize(sourcePath)
    .split(/[\\/]+/u)
    .filter(Boolean)
    .map((value) => value.toLowerCase());
  const baseName = segments.at(-1) ?? "";
  if (
    policy.rejectedBaseNames.has(baseName) ||
    policy.rejectedNamePrefixes.some((prefix) => baseName.startsWith(prefix)) ||
    policy.rejectedSuffixes.some((suffix) => baseName.endsWith(suffix)) ||
    segments.some((segment) => policy.rejectedPathSegments.has(segment))
  ) {
    throw new SensitiveSourceError(
      "source_rejected",
      "A requested source matches the hard sensitive-file policy.",
    );
  }
}

export function assertSourceContentNotSensitive(
  text: string,
  policy: SensitiveFilePolicy,
): void {
  if (policy.contentPatterns.some((pattern) => pattern.test(text))) {
    throw new SensitiveSourceError(
      "source_rejected",
      "A requested source contains credential-like content and was rejected.",
    );
  }
}
