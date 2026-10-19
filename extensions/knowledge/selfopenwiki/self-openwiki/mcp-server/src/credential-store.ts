import { createHash, randomUUID } from "node:crypto";
import { mkdir, mkdtemp, open, readFile, rename, rm } from "node:fs/promises";
import path from "node:path";
import { chatGptCredentialSchema, type ChatGptCredential } from "./auth.js";
import { withC7Locks } from "./config.js";

export type CredentialStoreSnapshot = {
  readonly credential?: ChatGptCredential;
  readonly version: string;
};

export type CredentialRefreshTransition = {
  readonly fromVersion: string;
  readonly toVersion: string;
};

export type TemporaryOpenWikiHome = {
  cleanup(): Promise<void>;
  finalize?(): Promise<CredentialRefreshTransition | undefined>;
  readonly path: string;
};

export interface PrivatePathSecurity {
  securePrivatePath(input: {
    directory: boolean;
    targetPath: string;
  }): Promise<unknown>;
}

export class C7CredentialStoreError extends Error {
  constructor(
    readonly code: "invalid_credentials" | "stale_version" | "write_failed",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "C7CredentialStoreError";
  }
}

export async function readCredentialStore(
  credentialPath: string,
): Promise<CredentialStoreSnapshot> {
  assertAbsolute(credentialPath, "credential store");
  let bytes: Buffer;
  try {
    bytes = await readFile(credentialPath);
  } catch (error) {
    if (hasErrorCode(error, "ENOENT")) return { version: "missing" };
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The managed ChatGPT credential store is unreadable.",
      { cause: error },
    );
  }
  return {
    credential: parseCredentialFile(bytes),
    version: hashBytes(bytes),
  };
}

export async function writeCredentialStoreAtomic(
  runtimeDir: string,
  credentialPath: string,
  credential: unknown,
  expectedVersion: string,
  security?: PrivatePathSecurity,
): Promise<CredentialStoreSnapshot> {
  assertAbsolute(runtimeDir, "runtime directory");
  assertContained(runtimeDir, credentialPath);
  const parsed = chatGptCredentialSchema.safeParse(credential);
  if (!parsed.success) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The ChatGPT credential payload is invalid.",
    );
  }

  return withC7Locks(runtimeDir, ["credentials"], async () => {
    const current = await readCredentialStore(credentialPath);
    if (current.version !== expectedVersion) {
      throw new C7CredentialStoreError(
        "stale_version",
        "The managed ChatGPT credential store changed concurrently.",
      );
    }

    const directory = path.dirname(credentialPath);
    await mkdir(directory, { mode: 0o700, recursive: true });
    await security?.securePrivatePath({
      directory: true,
      targetPath: directory,
    });
    const bytes = Buffer.from(
      `${JSON.stringify({ schemaVersion: 1, ...parsed.data }, null, 2)}\n`,
      "utf8",
    );
    const temporaryPath = path.join(
      directory,
      `.credentials.${randomUUID()}.tmp`,
    );
    try {
      const handle = await open(temporaryPath, "wx", 0o600);
      try {
        await handle.writeFile(bytes);
        await handle.sync();
      } finally {
        await handle.close();
      }
      await security?.securePrivatePath({
        directory: false,
        targetPath: temporaryPath,
      });
      await rename(temporaryPath, credentialPath);
    } catch (error) {
      await rm(temporaryPath, { force: true });
      throw new C7CredentialStoreError(
        "write_failed",
        "The managed ChatGPT credential store could not be committed.",
        { cause: error },
      );
    }
    return { credential: { ...parsed.data }, version: hashBytes(bytes) };
  });
}

export async function createTemporaryOpenWikiHome(
  runtimeDir: string,
  credential: ChatGptCredential,
  security?: PrivatePathSecurity,
): Promise<TemporaryOpenWikiHome> {
  assertAbsolute(runtimeDir, "runtime directory");
  const parsed = chatGptCredentialSchema.safeParse(credential);
  if (!parsed.success) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The ChatGPT credential payload is invalid.",
    );
  }
  const temporaryRoot = path.join(runtimeDir, "temp");
  await mkdir(temporaryRoot, { mode: 0o700, recursive: true });
  const home = await mkdtemp(path.join(temporaryRoot, "openwiki-smoke-"));
  try {
    await security?.securePrivatePath({ directory: true, targetPath: home });
    const envPath = path.join(home, ".env");
    const handle = await open(envPath, "wx", 0o600);
    try {
      await handle.writeFile(renderManagedEnv(parsed.data), "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await security?.securePrivatePath({
      directory: false,
      targetPath: envPath,
    });
  } catch (error) {
    await rm(home, { force: true, recursive: true });
    throw new C7CredentialStoreError(
      "write_failed",
      "An isolated OpenWiki Home could not be created.",
      { cause: error },
    );
  }

  let cleaned = false;
  return {
    async cleanup() {
      if (cleaned) return;
      const envPath = path.join(home, ".env");
      try {
        const handle = await open(envPath, "r+");
        try {
          await handle.truncate(0);
          await handle.sync();
        } finally {
          await handle.close();
        }
      } catch (error) {
        if (!hasErrorCode(error, "ENOENT")) {
          // Deletion below is still attempted. A successful recursive removal
          // makes a separate scrub failure irrelevant.
        }
      }
      await rm(home, {
        force: true,
        maxRetries: 20,
        recursive: true,
        retryDelay: 25,
      });
      cleaned = true;
    },
    path: home,
  };
}

export async function createCredentialStoreHomeLease(
  runtimeDir: string,
  credentialPath: string,
  security?: PrivatePathSecurity,
): Promise<TemporaryOpenWikiHome> {
  const snapshot = await readCredentialStore(credentialPath);
  if (!snapshot.credential) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "Managed ChatGPT credentials are unavailable.",
    );
  }
  const home = await createTemporaryOpenWikiHome(
    runtimeDir,
    snapshot.credential,
    security,
  );
  return {
    cleanup: home.cleanup,
    async finalize() {
      const refreshed = await readManagedCredentialEnv(home.path);
      if (credentialsEqual(snapshot.credential!, refreshed)) return;
      const committed = await writeCredentialStoreAtomic(
        runtimeDir,
        credentialPath,
        refreshed,
        snapshot.version,
        security,
      );
      return {
        fromVersion: snapshot.version,
        toVersion: committed.version,
      };
    },
    path: home.path,
  };
}

export async function readManagedCredentialEnv(
  openWikiHome: string,
): Promise<ChatGptCredential> {
  assertAbsolute(openWikiHome, "OpenWiki Home");
  let text: string;
  try {
    text = await readFile(path.join(openWikiHome, ".env"), "utf8");
  } catch (error) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The isolated OpenWiki credential file is unreadable.",
      { cause: error },
    );
  }
  const managed = new Map<string, string>();
  const allowed = new Set([
    "OPENAI_CHATGPT_ACCESS_TOKEN",
    "OPENAI_CHATGPT_REFRESH_TOKEN",
    "OPENAI_CHATGPT_EXPIRES_AT",
    "OPENAI_CHATGPT_ACCOUNT_ID",
    "OPENAI_CHATGPT_EMAIL",
    "OPENAI_CHATGPT_PLAN",
  ]);
  for (const rawLine of text.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (line === "" || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator <= 0) continue;
    const key = line.slice(0, separator).trim();
    if (!allowed.has(key)) continue;
    if (managed.has(key)) {
      throw new C7CredentialStoreError(
        "invalid_credentials",
        "The isolated OpenWiki credential file has duplicate managed fields.",
      );
    }
    managed.set(key, parseEnvValue(line.slice(separator + 1).trim()));
  }
  const expiresAtText = managed.get("OPENAI_CHATGPT_EXPIRES_AT");
  const parsed = chatGptCredentialSchema.safeParse({
    access: managed.get("OPENAI_CHATGPT_ACCESS_TOKEN"),
    accountId: managed.get("OPENAI_CHATGPT_ACCOUNT_ID"),
    ...(managed.has("OPENAI_CHATGPT_EMAIL")
      ? { email: managed.get("OPENAI_CHATGPT_EMAIL") }
      : { email: null }),
    expiresAtMs:
      expiresAtText === undefined ? Number.NaN : Number(expiresAtText),
    ...(managed.has("OPENAI_CHATGPT_PLAN")
      ? { planType: managed.get("OPENAI_CHATGPT_PLAN") }
      : { planType: null }),
    refresh: managed.get("OPENAI_CHATGPT_REFRESH_TOKEN"),
  });
  if (!parsed.success) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The isolated OpenWiki credential file has invalid managed fields.",
    );
  }
  return parsed.data;
}

function parseCredentialFile(bytes: Buffer): ChatGptCredential {
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The managed ChatGPT credential store is invalid.",
    );
  }
  if (typeof value !== "object" || value === null) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The managed ChatGPT credential store is invalid.",
    );
  }
  const { schemaVersion, ...credential } = value as Record<string, unknown>;
  if (schemaVersion !== 1) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The managed ChatGPT credential store schema is unsupported.",
    );
  }
  const parsed = chatGptCredentialSchema.safeParse(credential);
  if (!parsed.success) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The managed ChatGPT credential store is invalid.",
    );
  }
  return parsed.data;
}

function renderManagedEnv(credential: ChatGptCredential): string {
  const values: Array<[string, string]> = [
    ["OPENAI_CHATGPT_ACCESS_TOKEN", credential.access],
    ["OPENAI_CHATGPT_REFRESH_TOKEN", credential.refresh],
    ["OPENAI_CHATGPT_EXPIRES_AT", String(credential.expiresAtMs)],
    ["OPENAI_CHATGPT_ACCOUNT_ID", credential.accountId],
  ];
  if (credential.email) values.push(["OPENAI_CHATGPT_EMAIL", credential.email]);
  if (credential.planType)
    values.push(["OPENAI_CHATGPT_PLAN", credential.planType]);
  return `${values.map(([key, value]) => `${key}=${JSON.stringify(value)}`).join("\n")}\n`;
}

function parseEnvValue(value: string): string {
  if (value.startsWith('"') && value.endsWith('"')) {
    try {
      const parsed = JSON.parse(value) as unknown;
      if (typeof parsed === "string") return parsed;
    } catch {
      // Rejected below.
    }
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The isolated OpenWiki credential file has invalid quoting.",
    );
  }
  if (/[\0\r\n]/u.test(value)) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The isolated OpenWiki credential file has an invalid value.",
    );
  }
  return value;
}

function credentialsEqual(
  left: ChatGptCredential,
  right: ChatGptCredential,
): boolean {
  return (
    left.access === right.access &&
    left.refresh === right.refresh &&
    left.expiresAtMs === right.expiresAtMs &&
    left.accountId === right.accountId &&
    (left.email ?? null) === (right.email ?? null) &&
    (left.planType ?? null) === (right.planType ?? null)
  );
}

function assertContained(root: string, candidate: string): void {
  assertAbsolute(candidate, "credential store");
  const relative = path.relative(root, candidate);
  if (
    relative === "" ||
    relative === ".." ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  ) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      "The credential store path is outside the runtime directory.",
    );
  }
}

function assertAbsolute(value: string, label: string): void {
  if (!path.isAbsolute(value)) {
    throw new C7CredentialStoreError(
      "invalid_credentials",
      `${label} path must be absolute.`,
    );
  }
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function hasErrorCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === code
  );
}
