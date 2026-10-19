import { randomUUID } from "node:crypto";
import { lstat, mkdir, open, readFile, rename, rm } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const uuidSchema = z.string().uuid();

export const personalCandidateMarkerSchema = z
  .strictObject({
    candidateRoot: z
      .string()
      .min(1)
      .refine((value) => path.isAbsolute(value)),
    candidateRootHash: hashSchema,
    candidateBindingHash: hashSchema,
    claimDecisionHash: hashSchema,
    createdAt: z.string().datetime({ offset: true }),
    generation: z.number().int().min(1).max(3),
    jobId: uuidSchema,
    pageContentHash: hashSchema,
    pagePath: z.string().min(1).max(1_024),
    pagePathHash: hashSchema,
    runId: uuidSchema,
    state: z.enum(["accepted", "candidate_written"]),
    transactionId: z.string().min(8).max(160),
    type: z.literal("selfopenwiki:candidate-page-marker-v1"),
    updatedAt: z.string().datetime({ offset: true }),
    version: z.literal(1),
    writerExecutionId: z.string().min(8).max(160),
  })
  .superRefine((value, context) => {
    if (
      value.pagePath.includes("\\") ||
      value.pagePath.startsWith("/") ||
      !value.pagePath.toLowerCase().endsWith(".md") ||
      value.pagePath
        .split("/")
        .some(
          (segment) =>
            ["", ".", ".."].includes(segment) ||
            [...segment].some(
              (character) =>
                character.charCodeAt(0) < 0x20 ||
                character.charCodeAt(0) === 0x7f ||
                '<>:"/\\|?*'.includes(character),
            ) ||
            /[. ]$/u.test(segment) ||
            /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$/iu.test(segment),
        )
    ) {
      context.addIssue({
        code: "custom",
        message: "candidate marker pagePath must be a relative Markdown path",
      });
    }
  });

export type PersonalCandidateMarker = z.infer<
  typeof personalCandidateMarkerSchema
>;

export class PersonalCandidateMarkerError extends Error {
  constructor(
    readonly code: "invalid_state",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "PersonalCandidateMarkerError";
  }
}

export async function writePersonalCandidateMarker(
  markerPath: string,
  marker: PersonalCandidateMarker,
): Promise<void> {
  if (!path.isAbsolute(markerPath)) {
    throw invalidMarker("The candidate marker path must be absolute.");
  }
  const parsed = personalCandidateMarkerSchema.safeParse(marker);
  if (!parsed.success) {
    throw invalidMarker("The candidate marker is invalid.");
  }
  await atomicWrite(markerPath, `${canonicalJson(parsed.data)}\n`);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export async function readPersonalCandidateMarker(
  markerPath: string,
): Promise<PersonalCandidateMarker | null> {
  if (!path.isAbsolute(markerPath)) {
    throw invalidMarker("The candidate marker path must be absolute.");
  }
  let value: unknown;
  try {
    value = JSON.parse(await readFile(markerPath, "utf8"));
  } catch (error) {
    if (isMissing(error)) return null;
    throw invalidMarker("The candidate marker is unreadable.", error);
  }
  const parsed = personalCandidateMarkerSchema.safeParse(value);
  if (!parsed.success) throw invalidMarker("The candidate marker is invalid.");
  return parsed.data;
}

export async function transitionPersonalCandidateMarker(
  markerPath: string,
  state: "accepted",
  updatedAt: string,
): Promise<PersonalCandidateMarker> {
  const marker = await readPersonalCandidateMarker(markerPath);
  if (marker === null) throw invalidMarker("The candidate marker is missing.");
  if (marker.state === "accepted") return marker;
  const next = personalCandidateMarkerSchema.parse({
    ...marker,
    state,
    updatedAt,
  });
  await writePersonalCandidateMarker(markerPath, next);
  return next;
}

async function atomicWrite(filePath: string, content: string): Promise<void> {
  const directory = path.dirname(filePath);
  await assertNoLinkAncestors(directory);
  const existingTarget = await lstat(filePath).catch((error: unknown) => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (existingTarget?.isSymbolicLink()) {
    throw invalidMarker(
      "The candidate marker path cannot be a link or junction.",
    );
  }
  await mkdir(directory, { mode: 0o700, recursive: true });
  const temporaryPath = path.join(
    directory,
    `.${path.basename(filePath)}.${randomUUID()}.tmp`,
  );
  try {
    const handle = await open(temporaryPath, "wx", 0o600);
    try {
      await handle.writeFile(content, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporaryPath, filePath);
  } catch (error) {
    await rm(temporaryPath, { force: true }).catch(() => undefined);
    throw error;
  }
}

async function assertNoLinkAncestors(directory: string): Promise<void> {
  let current = path.parse(directory).root;
  for (const segment of path
    .relative(current, directory)
    .split(path.sep)
    .filter(Boolean)) {
    current = path.join(current, segment);
    const stat = await lstat(current).catch((error: unknown) => {
      if (isMissing(error)) return null;
      throw error;
    });
    if (stat === null) return;
    if (stat.isSymbolicLink() || !stat.isDirectory()) {
      throw invalidMarker(
        "The candidate marker directory cannot contain a link or junction.",
      );
    }
  }
}

function invalidMarker(
  message: string,
  cause?: unknown,
): PersonalCandidateMarkerError {
  return new PersonalCandidateMarkerError("invalid_state", message, { cause });
}

function isMissing(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "ENOENT"
  );
}
