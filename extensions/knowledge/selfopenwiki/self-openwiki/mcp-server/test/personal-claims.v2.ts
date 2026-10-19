import { createHash } from "node:crypto";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, test } from "vitest";
import {
  FilePersonalClaimsResolver,
  personalClaimsSidecarPath,
  writePersonalClaims,
} from "../src/personal-claims.js";

describe("personal Wiki authoritative Claims", () => {
  test("loads current Claims only when the sidecar is bound to current page bytes", async () => {
    const wikiRoot = await mkdtemp(path.join(os.tmpdir(), "personal-claims-"));
    try {
      const page = "guide.md";
      const content = "# Guide\n";
      await writeFile(path.join(wikiRoot, page), content, "utf8");
      await mkdir(path.join(wikiRoot, ".claims"), { recursive: true });
      await writeFile(
        path.join(wikiRoot, ".claims", "guide.json"),
        JSON.stringify({
          claims: [
            {
              evidence: [{ resource: "wiki://guide.md", version: "v1" }],
              id: "claim-12345678",
              statement: "The guide exists.",
            },
          ],
          pageVersion: hashBytes(Buffer.from(content, "utf8")),
          schemaVersion: 1,
        }),
        "utf8",
      );
      await expect(
        new FilePersonalClaimsResolver().load(wikiRoot, page),
      ).resolves.toEqual({
        claims: [
          {
            evidence: [{ resource: "wiki://guide.md" }],
            id: "claim-12345678",
            statement: "The guide exists.",
          },
        ],
        source: "authoritative",
      });
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
    }
  });

  test("rejects a sidecar whose page version is stale", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-stale-"),
    );
    try {
      await writeFile(path.join(wikiRoot, "guide.md"), "# Guide\n", "utf8");
      await mkdir(path.join(wikiRoot, ".claims"), { recursive: true });
      await writeFile(
        path.join(wikiRoot, ".claims", "guide.json"),
        JSON.stringify({
          claims: [],
          pageVersion: hash("a"),
          schemaVersion: 1,
        }),
        "utf8",
      );
      await expect(
        new FilePersonalClaimsResolver().load(wikiRoot, "guide.md"),
      ).rejects.toMatchObject({ code: "validation_failed" });
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
    }
  });

  test("rejects sidecar evidence outside the repo/wiki resource grammar", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-invalid-resource-"),
    );
    try {
      const content = "# Guide\n";
      await writeFile(path.join(wikiRoot, "guide.md"), content, "utf8");
      await mkdir(path.join(wikiRoot, ".claims"), { recursive: true });
      await writeFile(
        path.join(wikiRoot, ".claims", "guide.json"),
        JSON.stringify({
          claims: [
            {
              evidence: [
                { resource: "https://example.invalid/source", version: "v1" },
              ],
              id: "claim-12345678",
              statement: "The guide exists.",
            },
          ],
          pageVersion: hashBytes(Buffer.from(content, "utf8")),
          schemaVersion: 1,
        }),
        "utf8",
      );
      await expect(
        new FilePersonalClaimsResolver().load(wikiRoot, "guide.md"),
      ).rejects.toMatchObject({ code: "validation_failed" });
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
    }
  });

  test("writes a complete sidecar atomically for a reconciled page", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-write-"),
    );
    try {
      const content = Buffer.from("# Guide\n", "utf8");
      await writeFile(path.join(wikiRoot, "guide.md"), content);
      await writePersonalClaims(
        wikiRoot,
        "guide.md",
        [
          {
            evidence: [{ resource: "repo://src/guide.ts" }],
            statement: "The guide exists.",
          },
        ],
        content,
      );
      await expect(
        new FilePersonalClaimsResolver().load(wikiRoot, "guide.md"),
      ).resolves.toMatchObject({
        source: "authoritative",
        claims: [
          {
            statement: "The guide exists.",
            id: expect.stringMatching(/^personal-claim-/u),
          },
        ],
      });
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
    }
  });

  test("normalizes uppercase Markdown extensions to JSON sidecars", () => {
    expect(personalClaimsSidecarPath("nested/Page.MD")).toBe(
      ".claims/nested/Page.json",
    );
  });
});

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}

function hashBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
