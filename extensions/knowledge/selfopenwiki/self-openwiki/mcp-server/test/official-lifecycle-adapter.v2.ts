import { mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, test, vi } from "vitest";
import {
  C7PersonalGateway,
  OFFICIAL_PERSONAL_LIFECYCLE_TOOLS,
  OfficialLifecycleAdapter,
} from "../src/official-lifecycle-adapter.js";

describe("official OpenWiki lifecycle adapter", () => {
  test("keeps the official six-stage names while routing through the personal owner", async () => {
    const owner = {
      begin: vi.fn(async (input: unknown) => ({ stage: "begin", input })),
      finish: vi.fn(async (input: unknown) => ({ stage: "finish", input })),
      inspectPageClaims: vi.fn(async (input: unknown) => ({
        stage: "inspect",
        input,
      })),
      nextPage: vi.fn(async (input: unknown) => ({ stage: "next", input })),
      submitPage: vi.fn(async (input: unknown) => ({ stage: "submit", input })),
      submitPlan: vi.fn(async (input: unknown) => ({ stage: "plan", input })),
    };
    const adapter = new OfficialLifecycleAdapter(owner);

    expect(OFFICIAL_PERSONAL_LIFECYCLE_TOOLS).toEqual([
      "openwiki_begin",
      "openwiki_submit_plan",
      "openwiki_next_page",
      "openwiki_inspect_page_claims",
      "openwiki_submit_page",
      "openwiki_finish",
    ]);
    await expect(adapter.begin({ value: 1 })).resolves.toEqual({
      input: { value: 1 },
      stage: "begin",
    });
    await expect(adapter.submitPlan({ value: 2 })).resolves.toEqual({
      input: { value: 2 },
      stage: "plan",
    });
    await expect(adapter.nextPage({ value: 3 })).resolves.toEqual({
      input: { value: 3 },
      stage: "next",
    });
    await expect(adapter.inspectPageClaims({ value: 4 })).resolves.toEqual({
      input: { value: 4 },
      stage: "inspect",
    });
    await expect(adapter.submitPage({ value: 5 })).resolves.toEqual({
      input: { value: 5 },
      stage: "submit",
    });
    await expect(adapter.finish({ value: 6 })).resolves.toEqual({
      input: { value: 6 },
      stage: "finish",
    });
  });

  test("maps the existing C7 external transaction into the adapted candidate binding", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-gateway-wiki-"),
    );
    const runtimeRoot = `${wikiRoot}.selfopenwiki`;
    await mkdir(runtimeRoot, { recursive: true });
    const candidateRoot = await mkdtemp(path.join(runtimeRoot, "candidate-"));
    const canonicalCandidateRoot = await realpath(candidateRoot);
    await writeFile(
      path.join(candidateRoot, "index.md"),
      "# Candidate\n",
      "utf8",
    );
    const externalBegin = vi.fn(async () => ({
      authRequired: false,
      executionMode: "external_agent",
      ok: true,
      recovery: { action: "none" },
      status: "external_update_ready",
      workPackage: {
        beforeWikiRevision: hash("a"),
        bindingHash: hash("b"),
        candidate: {
          allowedChangedPaths: ["index.md"],
          permissions: ["read", "list", "write"],
          rootPath: candidateRoot,
          workspaceId: "workspace-12345678",
        },
        confirmedWikiPaths: ["index.md"],
        generation: 1,
        requestPackage: { packageHash: hash("c"), path: "C:\\request.json" },
        rules: {
          candidateResultContract: {
            path: "C:\\result.json",
            schemaHash: hash("d"),
          },
          hardRulePackage: { packageHash: hash("e"), path: "C:\\rules.md" },
          skills: [],
        },
        skillAggregateHash: hash("f"),
        sourceManifestHash: null,
        sourceTreeHash: null,
        sources: null,
        transactionId: "external-12345678",
        version: 1,
      },
    }));
    const gateway = new C7PersonalGateway({
      externalUpdate: { begin: externalBegin } as never,
    });

    try {
      await expect(
        gateway.start({
          confirmedByUser: true,
          pages: [{ path: "index.md", purpose: "Index.", title: "Index" }],
          runId: "11111111-1111-4111-8111-111111111111",
          skillAggregateHash: hash("f"),
          markdownWikiRevision: hash("m"),
          wikiRevision: hash("a"),
          wikiRoot,
        }),
      ).resolves.toEqual({
        candidateBindingHash: hash("b"),
        candidateRoot: canonicalCandidateRoot,
        candidateRootHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
        generation: 1,
        transactionId: "external-12345678",
        wikiRevision: hash("a"),
      });
      expect(externalBegin).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "start",
          confirmedWikiPaths: ["index.md"],
          expectedWikiRevision: hash("m"),
          requestId: "11111111-1111-4111-8111-111111111111",
          materials: [
            expect.objectContaining({
              id: "selfopenwiki-personal-adapter-binding",
              source: "self-openwiki",
            }),
          ],
        }),
      );
      const startInput = (
        externalBegin.mock.calls as unknown as Array<
          [{ materials: [{ content: string }]; skills?: unknown }]
        >
      )[0]?.[0];
      if (startInput === undefined) throw new Error("missing start input");
      expect(startInput.skills).toBeUndefined();
      expect(JSON.parse(startInput.materials[0].content)).toEqual(
        expect.objectContaining({
          protocol: "selfopenwiki:personal-c7-binding-v1",
          skillAggregateHash: hash("f"),
        }),
      );
    } finally {
      await rm(candidateRoot, { force: true, recursive: true });
      await rm(runtimeRoot, { force: true, recursive: true });
      await rm(wikiRoot, { force: true, recursive: true });
    }
  });

  test("rejects a C7 candidate outside the personal runtime root", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-gateway-wiki-"),
    );
    const externalRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-gateway-external-"),
    );
    await writeFile(
      path.join(externalRoot, "index.md"),
      "# External\n",
      "utf8",
    );
    const externalBegin = vi.fn(async () => ({
      ok: true,
      status: "external_update_ready",
      workPackage: {
        beforeWikiRevision: hash("a"),
        bindingHash: hash("b"),
        candidate: {
          allowedChangedPaths: ["index.md"],
          permissions: ["read", "list", "write"],
          rootPath: externalRoot,
          workspaceId: "workspace-12345678",
        },
        confirmedWikiPaths: ["index.md"],
        generation: 1,
        transactionId: "external-12345678",
      },
    }));
    const gateway = new C7PersonalGateway({
      externalUpdate: { begin: externalBegin } as never,
    });
    try {
      await expect(
        gateway.start({
          confirmedByUser: true,
          pages: [{ path: "index.md", purpose: "Index.", title: "Index" }],
          runId: "11111111-1111-4111-8111-111111111111",
          skillAggregateHash: hash("f"),
          wikiRevision: hash("a"),
          wikiRoot,
        }),
      ).rejects.toMatchObject({ code: "upstream_incompatible" });
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
      await rm(externalRoot, { force: true, recursive: true });
    }
  });
});

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}
