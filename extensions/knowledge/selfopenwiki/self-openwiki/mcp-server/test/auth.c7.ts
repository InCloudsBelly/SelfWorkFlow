import { describe, expect, test, vi } from "vitest";
import { EphemeralCredentialVault } from "../src/auth.js";

const secretAccess = "access-secret-canary";
const secretRefresh = "refresh-secret-canary";
const credential = {
  access: secretAccess,
  refresh: secretRefresh,
  expiresAtMs: 1_800_000_000_000,
  accountId: "account-private",
  email: "private@example.test",
  planType: "plus",
};

describe("ephemeral private-IPC credential vault", () => {
  test("stages a strict credential behind an opaque one-time reference", () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-12345678",
    );

    const reference = vault.stage(credential);

    expect(reference).toBe("credential-reference-12345678");
    expect(reference).not.toContain(secretAccess);
    expect(reference).not.toContain(secretRefresh);
    expect(vault.has(reference)).toBe(true);
    expect(JSON.stringify(vault)).not.toContain(secretAccess);
    expect(JSON.stringify(vault)).not.toContain(secretRefresh);
  });

  test("rejects missing, unknown, and malformed credential fields", () => {
    const vault = new EphemeralCredentialVault();
    for (const invalid of [
      { ...credential, access: "" },
      { ...credential, expiresAtMs: Number.NaN },
      { ...credential, invented: secretAccess },
      { ...credential, refresh: undefined },
    ]) {
      expect(() => vault.stage(invalid)).toThrowError(
        expect.objectContaining({ code: "invalid_credential" }),
      );
    }
  });

  test("accepts nullable identity fields returned by upstream OAuth", () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-12345678",
    );

    expect(() =>
      vault.stage({ ...credential, email: null, planType: null }),
    ).not.toThrow();
  });

  test("persists once, deletes the reachable secret, and refuses reuse", async () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-12345678",
    );
    const reference = vault.stage(credential);
    const writer = vi.fn().mockResolvedValue(undefined);

    await expect(vault.persist(reference, writer)).resolves.toBeUndefined();
    expect(writer).toHaveBeenCalledWith(credential);
    expect(vault.has(reference)).toBe(false);
    await expect(vault.persist(reference, writer)).rejects.toEqual(
      expect.objectContaining({ code: "credential_not_found" }),
    );
  });

  test("keeps the staged credential available when persistence fails", async () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-12345678",
    );
    const reference = vault.stage(credential);
    const writer = vi.fn().mockRejectedValue(new Error("disk unavailable"));

    await expect(vault.persist(reference, writer)).rejects.toThrow(
      /disk unavailable/iu,
    );
    expect(vault.has(reference)).toBe(true);
  });

  test("discard makes cancellation terminal without exposing credential data", async () => {
    const vault = new EphemeralCredentialVault(
      () => "credential-reference-12345678",
    );
    const reference = vault.stage(credential);
    vault.discard(reference);

    await expect(
      vault.persist(reference, async () => undefined),
    ).rejects.toEqual(
      expect.objectContaining({
        code: "credential_not_found",
        message: expect.not.stringContaining(secretAccess),
      }),
    );
  });
});
