import { spawn } from "node:child_process";
import { access, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test } from "vitest";
import {
  createCredentialStoreHomeLease,
  createTemporaryOpenWikiHome,
  readCredentialStore,
  writeCredentialStoreAtomic,
} from "../src/credential-store.js";

const tempDirs: string[] = [];
const credential = {
  access: "access-secret-canary",
  accountId: "account-private",
  email: null,
  expiresAtMs: 1_800_000_000_000,
  planType: null,
  refresh: "refresh-secret-canary",
};

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("managed ChatGPT credential store", () => {
  test("writes strict credentials atomically and rejects stale CAS", async () => {
    const runtimeDir = await createRuntimeDir();
    const credentialPath = path.join(runtimeDir, "credentials", "chatgpt.json");
    expect(await readCredentialStore(credentialPath)).toEqual({
      version: "missing",
    });

    const written = await writeCredentialStoreAtomic(
      runtimeDir,
      credentialPath,
      credential,
      "missing",
    );
    expect(written.version).toMatch(/^sha256:[a-f0-9]{64}$/u);
    expect(await readCredentialStore(credentialPath)).toEqual(written);
    await expect(
      writeCredentialStoreAtomic(
        runtimeDir,
        credentialPath,
        { ...credential, access: "new-secret" },
        "missing",
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "stale_version" }));
  });

  test("rejects extra fields and malformed persisted stores", async () => {
    const runtimeDir = await createRuntimeDir();
    const credentialPath = path.join(runtimeDir, "credentials.json");
    await expect(
      writeCredentialStoreAtomic(
        runtimeDir,
        credentialPath,
        { ...credential, untrusted: "value" },
        "missing",
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "invalid_credentials" }));

    await writeFile(credentialPath, '{"schemaVersion":1,"access":"x"}\n');
    await expect(readCredentialStore(credentialPath)).rejects.toEqual(
      expect.objectContaining({ code: "invalid_credentials" }),
    );
  });

  test("creates an exact managed .env and removes the temporary Home", async () => {
    const runtimeDir = await createRuntimeDir();
    const lease = await createTemporaryOpenWikiHome(runtimeDir, credential);
    const envPath = path.join(lease.path, ".env");
    const contents = await readFile(envPath, "utf8");

    expect(contents).toContain(
      'OPENAI_CHATGPT_ACCESS_TOKEN="access-secret-canary"',
    );
    expect(contents).not.toContain("undefined");
    expect(contents).not.toContain("OPENAI_CHATGPT_EMAIL");
    await lease.cleanup();
    await expect(access(lease.path)).rejects.toBeDefined();
    await expect(lease.cleanup()).resolves.toBeUndefined();
  });

  test("merges only refreshed ChatGPT fields with credential CAS", async () => {
    const runtimeDir = await createRuntimeDir();
    const credentialPath = path.join(runtimeDir, "credentials", "chatgpt.json");
    const first = await writeCredentialStoreAtomic(
      runtimeDir,
      credentialPath,
      credential,
      "missing",
    );
    const lease = await createCredentialStoreHomeLease(
      runtimeDir,
      credentialPath,
    );
    await writeFile(
      path.join(lease.path, ".env"),
      [
        "OPENAI_CHATGPT_ACCESS_TOKEN=rotated-access",
        "OPENAI_CHATGPT_REFRESH_TOKEN=rotated-refresh",
        "OPENAI_CHATGPT_EXPIRES_AT=1900000000000",
        "OPENAI_CHATGPT_ACCOUNT_ID=account-private",
        "AWS_SECRET_ACCESS_KEY=must-never-merge",
        "INVENTED_STATE=must-never-merge",
        "",
      ].join("\n"),
      "utf8",
    );

    const transition = await lease.finalize?.();
    await lease.cleanup();
    const persisted = await readCredentialStore(credentialPath);
    expect(transition).toEqual({
      fromVersion: first.version,
      toVersion: persisted.version,
    });
    expect(persisted.credential).toEqual({
      access: "rotated-access",
      accountId: "account-private",
      email: null,
      expiresAtMs: 1_900_000_000_000,
      planType: null,
      refresh: "rotated-refresh",
    });
    expect(JSON.stringify(persisted)).not.toContain("must-never-merge");
  });

  test("rejects refresh merge after concurrent credential replacement", async () => {
    const runtimeDir = await createRuntimeDir();
    const credentialPath = path.join(runtimeDir, "credentials", "chatgpt.json");
    const first = await writeCredentialStoreAtomic(
      runtimeDir,
      credentialPath,
      credential,
      "missing",
    );
    const lease = await createCredentialStoreHomeLease(
      runtimeDir,
      credentialPath,
    );
    await writeCredentialStoreAtomic(
      runtimeDir,
      credentialPath,
      { ...credential, access: "concurrent-access" },
      first.version,
    );
    await writeFile(
      path.join(lease.path, ".env"),
      [
        "OPENAI_CHATGPT_ACCESS_TOKEN=rotated-access",
        "OPENAI_CHATGPT_REFRESH_TOKEN=rotated-refresh",
        "OPENAI_CHATGPT_EXPIRES_AT=1900000000000",
        "OPENAI_CHATGPT_ACCOUNT_ID=account-private",
        "",
      ].join("\n"),
      "utf8",
    );

    await expect(lease.finalize?.()).rejects.toEqual(
      expect.objectContaining({ code: "stale_version" }),
    );
    await lease.cleanup();
    expect((await readCredentialStore(credentialPath)).credential?.access).toBe(
      "concurrent-access",
    );
  });

  test("retries cleanup internally after a transient Windows directory lock", async () => {
    const runtimeDir = await createRuntimeDir();
    const lease = await createTemporaryOpenWikiHome(runtimeDir, credential);
    const child = spawn(
      process.execPath,
      [
        "-e",
        "process.stdout.write('ready'); setTimeout(() => process.exit(0), 200)",
      ],
      {
        cwd: lease.path,
        stdio: ["ignore", "pipe", "ignore"],
        windowsHide: true,
      },
    );
    await new Promise<void>((resolve, reject) => {
      child.once("error", reject);
      child.stdout.once("data", () => resolve());
    });

    await expect(lease.cleanup()).resolves.toBeUndefined();
    await expect(access(lease.path)).rejects.toBeDefined();
    if (child.exitCode === null) {
      await new Promise<void>((resolve) => child.once("exit", () => resolve()));
    }
  });
});

async function createRuntimeDir(): Promise<string> {
  const runtimeDir = await mkdtemp(path.join(os.tmpdir(), "c7-runtime-"));
  tempDirs.push(runtimeDir);
  return runtimeDir;
}
