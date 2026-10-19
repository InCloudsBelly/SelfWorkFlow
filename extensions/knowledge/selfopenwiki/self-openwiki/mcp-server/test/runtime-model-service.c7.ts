import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { EphemeralCredentialVault } from "../src/auth.js";
import {
  readCredentialStore,
  writeCredentialStoreAtomic,
} from "../src/credential-store.js";
import { readRuntimeConfigState } from "../src/config.js";
import {
  ModelVerificationError,
  type ModelVerificationEvidence,
} from "../src/model-verification.js";
import {
  createRuntimeSetupManager,
  RuntimeModelService,
} from "../src/runtime-model-service.js";
import { createModelConfirmation } from "../src/setup-attempt.js";

const tempDirs: string[] = [];
const firstSelection = {
  model: "gpt-5.6-sol",
  reasoningEffort: "xhigh" as const,
};
const secondSelection = {
  model: "gpt-5.6-sol",
  reasoningEffort: "max" as const,
};
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

describe("runtime model setup persistence", () => {
  test("wires setup through operation, credential, and config persistence", async () => {
    const fixture = await createFixture();
    const verifier = {
      verify: vi.fn().mockResolvedValue(modelEvidence(firstSelection)),
    };
    const manager = createRuntimeSetupManager({
      createId: () => "attempt-12345678",
      oauth: {
        start: vi.fn().mockResolvedValue({
          authorizationUrl:
            "https://auth.openai.com/oauth/authorize?state=bound-state",
          authorize: vi.fn().mockImplementation(async () => ({
            credentialReference: fixture.vault.stage(credential),
          })),
          cancel: vi.fn().mockResolvedValue(undefined),
        }),
      },
      service: fixture.service,
      verifier,
    });

    await manager.start({
      confirmation: createModelConfirmation(firstSelection),
      selection: firstSelection,
    });
    await expect(manager.complete("attempt-12345678")).resolves.toEqual(
      expect.objectContaining({ status: "setup_completed" }),
    );
    expect((await readRuntimeConfigState(fixture.configPath)).config).toEqual(
      expect.objectContaining({
        defaultModel: firstSelection,
        initialized: true,
      }),
    );
  });

  test("persists OAuth first but initializes config only after exact evidence", async () => {
    const fixture = await createFixture();
    const context = await fixture.service.captureSetupState();
    const reference = fixture.vault.stage(credential);

    await fixture.service.persistAuthorizedCredential(reference, context);
    expect(
      (await readRuntimeConfigState(fixture.configPath)).config,
    ).toBeUndefined();
    expect(
      (await readCredentialStore(fixture.credentialPath)).credential,
    ).toEqual(credential);

    const evidence = modelEvidence(firstSelection);
    await fixture.service.completeSetup({
      credentialReference: reference,
      evidence,
      persistenceContext: context,
      selection: firstSelection,
    });
    expect((await readRuntimeConfigState(fixture.configPath)).config).toEqual(
      expect.objectContaining({
        defaultModel: firstSelection,
        generation: 1,
        initialized: true,
      }),
    );
  });

  test("fails stale credential CAS without consuming the staged retry", async () => {
    const fixture = await createFixture();
    const context = await fixture.service.captureSetupState();
    const reference = fixture.vault.stage(credential);
    await writeCredentialStoreAtomic(
      fixture.runtimeDir,
      fixture.credentialPath,
      credential,
      "missing",
    );

    await expect(
      fixture.service.persistAuthorizedCredential(reference, context),
    ).rejects.toEqual(expect.objectContaining({ code: "stale_version" }));
    expect(fixture.vault.has(reference)).toBe(true);
  });

  test("set-default runs smoke first and preserves the old config on failure", async () => {
    const fixture = await initializedFixture();
    const before = await readFile(fixture.configPath);
    const verifier = {
      verify: vi
        .fn()
        .mockRejectedValue(
          new ModelVerificationError("model_rejected", false, "rejected"),
        ),
    };

    await expect(
      fixture.service.verifyAndSetDefault(
        {
          confirmation: createModelConfirmation(secondSelection),
          selection: secondSelection,
        },
        verifier,
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "model_rejected" }));
    expect(await readFile(fixture.configPath)).toEqual(before);
  });

  test("set-default CAS commits only the exact verified model and effort", async () => {
    const fixture = await initializedFixture();
    const evidence = modelEvidence(secondSelection);
    const verifier = { verify: vi.fn().mockResolvedValue(evidence) };

    const result = await fixture.service.verifyAndSetDefault(
      {
        confirmation: createModelConfirmation(secondSelection),
        selection: secondSelection,
      },
      verifier,
    );

    expect(verifier.verify).toHaveBeenCalledWith(
      secondSelection,
      "runtime-credential",
    );
    expect(result).toEqual(
      expect.objectContaining({
        config: expect.objectContaining({
          config: expect.objectContaining({
            defaultModel: secondSelection,
            generation: 2,
          }),
        }),
        model: evidence,
      }),
    );
  });

  test("accepts the verifier's own whitelist-CAS token refresh during set-default", async () => {
    const fixture = await initializedFixture();
    const evidence = modelEvidence(secondSelection);
    const verifier = {
      verify: vi.fn().mockImplementation(async () => {
        const lease =
          await fixture.service.resolveOpenWikiHome("runtime-credential");
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
        await lease.finalize?.();
        await lease.cleanup();
        return evidence;
      }),
    };

    await expect(
      fixture.service.verifyAndSetDefault(
        {
          confirmation: createModelConfirmation(secondSelection),
          selection: secondSelection,
        },
        verifier,
      ),
    ).resolves.toEqual(
      expect.objectContaining({
        config: expect.objectContaining({
          config: expect.objectContaining({ defaultModel: secondSelection }),
        }),
      }),
    );
    expect(
      (await readCredentialStore(fixture.credentialPath)).credential,
    ).toEqual(
      expect.objectContaining({
        access: "rotated-access",
        refresh: "rotated-refresh",
      }),
    );
  });
});

async function initializedFixture() {
  const fixture = await createFixture();
  const context = await fixture.service.captureSetupState();
  const reference = fixture.vault.stage(credential);
  await fixture.service.persistAuthorizedCredential(reference, context);
  await fixture.service.completeSetup({
    credentialReference: reference,
    evidence: modelEvidence(firstSelection),
    persistenceContext: context,
    selection: firstSelection,
  });
  return fixture;
}

async function createFixture() {
  const runtimeDir = await mkdtemp(path.join(os.tmpdir(), "c7-model-runtime-"));
  tempDirs.push(runtimeDir);
  const configPath = path.join(runtimeDir, "config.json");
  const credentialPath = path.join(runtimeDir, "credentials", "chatgpt.json");
  const vault = new EphemeralCredentialVault(
    () => "credential-reference-12345678",
  );
  const service = new RuntimeModelService({
    configPath,
    credentialPath,
    now: () => Date.parse("2026-08-07T00:00:00.000Z"),
    privatePathSecurity: {
      securePrivatePath: vi.fn().mockResolvedValue(undefined),
    },
    runtimeDir,
    vault,
  });
  return { configPath, credentialPath, runtimeDir, service, vault };
}

function modelEvidence(
  selection: typeof firstSelection | typeof secondSelection,
): ModelVerificationEvidence {
  return {
    providerAccepted: true,
    requested: selection,
    sent: selection,
  };
}
