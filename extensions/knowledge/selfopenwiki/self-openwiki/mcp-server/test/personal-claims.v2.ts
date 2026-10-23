import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, test, vi } from "vitest";
import {
  FilePersonalClaimsResolver,
  personalClaimsSidecarPath,
  writePersonalClaims,
} from "../src/personal-claims.js";
import { PersonalWikiLifecycle } from "../src/personal-wiki-lifecycle.js";
import { snapshotPersonalWiki } from "../src/personal-wiki-snapshot.js";

describe("personal Wiki authoritative Claims", () => {
  test("reads a new namespace without creating it and rejects orphan Claims", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-new-"),
    );
    try {
      const resolver = new FilePersonalClaimsResolver();
      await expect(resolver.load(wikiRoot, "new/topic.md")).resolves.toEqual({
        claims: [],
        source: "none",
      });
      expect(await readdir(wikiRoot)).toEqual([]);
      await mkdir(path.join(wikiRoot, ".claims", "new"), { recursive: true });
      await writeFile(
        path.join(wikiRoot, ".claims", "new", "topic.json"),
        JSON.stringify({
          claims: [],
          pageVersion: hash("a"),
          schemaVersion: 1,
        }),
      );
      await expect(
        resolver.load(wikiRoot, "new/topic.md"),
      ).rejects.toMatchObject({
        code: "validation_failed",
        message:
          "A personal Wiki Claim sidecar must have a current Markdown page.",
      });
      expect(await readdir(wikiRoot)).toEqual([".claims"]);
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
    }
  });

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

  test("reads an empty stale sidecar without rewriting its binding", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-empty-"),
    );
    try {
      const content = "# Current guide\n";
      const sidecar = JSON.stringify({
        claims: [],
        pageVersion: hash("a"),
        schemaVersion: 1,
      });
      await writeFile(path.join(wikiRoot, "guide.md"), content, "utf8");
      await mkdir(path.join(wikiRoot, ".claims"));
      await writeFile(
        path.join(wikiRoot, ".claims/guide.json"),
        sidecar,
        "utf8",
      );
      await expect(
        new FilePersonalClaimsResolver().load(wikiRoot, "guide.md"),
      ).resolves.toEqual({ claims: [], source: "authoritative" });
      expect(
        await readFile(path.join(wikiRoot, ".claims/guide.json"), "utf8"),
      ).toBe(sidecar);
      expect(await readFile(path.join(wikiRoot, "guide.md"), "utf8")).toBe(
        content,
      );
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
    }
  });

  test("rejects publication if Claims are added after an empty-sidecar snapshot", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-concurrent-"),
    );
    const runtimeRoot = `${wikiRoot}.selfopenwiki`;
    try {
      await mkdir(runtimeRoot);
      await mkdir(path.join(wikiRoot, ".claims"));
      await writeFile(path.join(wikiRoot, "guide.md"), "# Guide\n");
      const sidecarPath = path.join(wikiRoot, ".claims/guide.json");
      await writeFile(
        sidecarPath,
        JSON.stringify({
          claims: [],
          pageVersion: hash("a"),
          schemaVersion: 1,
        }),
      );
      await expect(
        new FilePersonalClaimsResolver().load(wikiRoot, "guide.md"),
      ).resolves.toEqual({ claims: [], source: "authoritative" });
      const before = await snapshotPersonalWiki(wikiRoot);
      const concurrent = JSON.stringify({
        claims: [
          {
            id: "claim-12345678",
            statement: "A concurrent fact.",
            evidence: [{ resource: "wiki://guide.md", version: "v1" }],
          },
        ],
        pageVersion: hashBytes(Buffer.from("# Guide\n")),
        schemaVersion: 1,
      });
      await writeFile(sidecarPath, concurrent);
      const runId = "abababab-abab-4aba-8aba-abababababab";
      const candidate = {
        transactionId: "external-12345678",
        generation: 1 as const,
        candidateBindingHash: hash("b"),
        candidateRoot: path.join(runtimeRoot, "candidate"),
        candidateRootHash: hash("c"),
        wikiRevision: before.markdownRootHash,
      };
      const submitReview = vi.fn();
      const lifecycle = new PersonalWikiLifecycle({
        rootResolver: {} as never,
        skillAdapter: {} as never,
        claimsResolver: new FilePersonalClaimsResolver(),
        upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
        c7: { start: vi.fn(), submitReview },
        runStore: {
          begin: vi.fn(),
          read: async () => ({
            runId,
            wikiRoot,
            runtimeRoot,
            candidate,
            wikiRevision: before.rootHash,
            markdownWikiRevision: before.markdownRootHash,
            skillAggregateHash: hash("d"),
            planHash: hash("e"),
            queueHash: hash("f"),
            jobs: [
              {
                jobId: "cdcdcdcd-cdcd-4cdc-8cdc-cdcdcdcdcdcd",
                path: "guide.md",
                title: "Guide",
                purpose: "Guide.",
                status: "accepted" as const,
                issueClaims: [],
              },
            ],
          }),
        },
      });
      await expect(
        lifecycle.finish({
          runId,
          reviewReceipt: {
            type: "external_review_receipt",
            version: 1,
            transactionId: candidate.transactionId,
            generation: 1,
            bindingHash: candidate.candidateBindingHash,
            reviewPackageHash: hash("a"),
            candidateRootHash: hash("b"),
            candidateReceiptHash: hash("c"),
            reviewerExecutionId: "reviewer-12345678",
            verdict: "pass",
            issues: [],
          },
        }),
      ).rejects.toMatchObject({ code: "wiki_conflict" });
      expect(submitReview).not.toHaveBeenCalled();
      expect(await readFile(sidecarPath, "utf8")).toBe(concurrent);
      expect(await readFile(path.join(wikiRoot, "guide.md"), "utf8")).toBe(
        "# Guide\n",
      );
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
      await rm(runtimeRoot, { force: true, recursive: true });
    }
  });

  test("rejects nonempty Claims whose page version is stale", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-stale-"),
    );
    try {
      await writeFile(path.join(wikiRoot, "guide.md"), "# Guide\n", "utf8");
      await mkdir(path.join(wikiRoot, ".claims"), { recursive: true });
      await writeFile(
        path.join(wikiRoot, ".claims", "guide.json"),
        JSON.stringify({
          claims: [
            {
              id: "claim-12345678",
              statement: "The old guide contains a fact.",
              evidence: [{ resource: "wiki://guide.md", version: "v1" }],
            },
          ],
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
