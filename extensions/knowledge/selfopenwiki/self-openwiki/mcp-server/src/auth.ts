import { randomUUID } from "node:crypto";
import { z } from "zod";

export type ChatGptCredential = {
  access: string;
  accountId: string;
  email?: string | null;
  expiresAtMs: number;
  planType?: string | null;
  refresh: string;
};

export const chatGptCredentialSchema = z.strictObject({
  access: z.string().min(1).max(1_000_000),
  accountId: z.string().min(1).max(4_096),
  email: z.string().min(1).max(4_096).nullable().optional(),
  expiresAtMs: z.number().int().positive().finite(),
  planType: z.string().min(1).max(256).nullable().optional(),
  refresh: z.string().min(1).max(1_000_000),
});

type VaultEntry = {
  credential: ChatGptCredential;
  persisting: boolean;
};

export class CredentialVaultError extends Error {
  constructor(
    readonly code: "invalid_credential" | "credential_not_found",
    message: string,
  ) {
    super(message);
    this.name = "CredentialVaultError";
  }
}

/**
 * Keeps credentials received over private child-process IPC behind opaque,
 * one-time references until the credentials writer commits them. JavaScript
 * cannot promise physical memory erasure; deletion here only removes reachable
 * references from this vault.
 */
export class EphemeralCredentialVault {
  readonly #createReference: () => string;
  readonly #entries = new Map<string, VaultEntry>();

  constructor(
    createReference: () => string = () => `credential-${randomUUID()}`,
  ) {
    this.#createReference = createReference;
  }

  stage(credential: unknown): string {
    const parsed = chatGptCredentialSchema.safeParse(credential);
    if (!parsed.success) {
      throw new CredentialVaultError(
        "invalid_credential",
        "ChatGPT credential received over private IPC is invalid.",
      );
    }
    const reference = this.#createReference();
    if (
      !/^[A-Za-z0-9][A-Za-z0-9._:-]{7,255}$/u.test(reference) ||
      this.#entries.has(reference)
    ) {
      throw new CredentialVaultError(
        "invalid_credential",
        "Could not create a unique credential reference.",
      );
    }
    this.#entries.set(reference, {
      credential: { ...parsed.data },
      persisting: false,
    });
    return reference;
  }

  async persist(
    reference: string,
    writer: (credential: ChatGptCredential) => Promise<void>,
  ): Promise<void> {
    const entry = this.#entries.get(reference);
    if (!entry || entry.persisting) {
      throw new CredentialVaultError(
        "credential_not_found",
        "Credential reference is unavailable or already consumed.",
      );
    }

    entry.persisting = true;
    try {
      await writer({ ...entry.credential });
      this.#entries.delete(reference);
    } catch (error) {
      entry.persisting = false;
      throw error;
    }
  }

  discard(reference: string): void {
    this.#entries.delete(reference);
  }

  has(reference: string): boolean {
    return this.#entries.has(reference);
  }
}
