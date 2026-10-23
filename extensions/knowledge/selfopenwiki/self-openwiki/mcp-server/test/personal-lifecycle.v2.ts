import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { describe, expect, test, vi } from "vitest";
import { TOOL_NAMES } from "../src/contracts.js";
import {
  canonicalPersonalJson,
  personalHash,
  PersonalWikiLifecycle,
  recoverPersonalClaimsFinalization,
} from "../src/personal-wiki-lifecycle.js";
import { PersonalSkillAdapter } from "../src/personal-skill-adapter.js";
import {
  createPersonalClaimsPayload,
  FilePersonalClaimsResolver,
  hashPersonalClaimsBytes,
} from "../src/personal-claims.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";
import { snapshotPersonalWiki } from "../src/personal-wiki-snapshot.js";
import {
  FilePersonalRunStore,
  PersonalRunStoreRouter,
} from "../src/personal-run-store.js";

describe("SelfOpenWiki adapted personal lifecycle", () => {
  test("hashes nested personal payloads with sorted canonical object keys", () => {
    expect(personalHash({ b: 2, a: { d: 4, c: 3 } })).toBe(
      personalHash({ a: { c: 3, d: 4 }, b: 2 }),
    );
  });

  test("discovers the adapted six tools before the legacy nine tools", () => {
    expect(TOOL_NAMES).toEqual([
      "openwiki_status",
      "openwiki_read",
      "openwiki_begin",
      "openwiki_submit_plan",
      "openwiki_next_page",
      "openwiki_inspect_page_claims",
      "openwiki_submit_page",
      "openwiki_finish",
      "openwiki_setup",
      "openwiki_prepare_sources",
      "openwiki_list_skills",
      "openwiki_query",
      "openwiki_update",
      "openwiki_begin_external_update",
      "openwiki_finalize_external_update",
      "openwiki_set_default_model",
    ]);
  });

  test("begin binds the explicit external Wiki root and adapted Skill snapshot", async () => {
    const wikiRoot = path.resolve("personal-wiki");
    const wikiRevision = hash("a");
    const markdownWikiRevision = hash("markdown-a");
    const skillAggregateHash = hash("b");
    const rootResolver = {
      resolve: vi.fn(async () => ({
        runtimeRoot: `${wikiRoot}.selfopenwiki`,
        markdownWikiRevision,
        wikiRevision,
        wikiRoot,
      })),
    };
    const skillAdapter = {
      resolve: vi.fn(async () => ({
        skillAggregateHash,
        skillIds: ["personal-wiki"],
      })),
    };
    const runStore = {
      begin: vi.fn(async () => ({
        runId: "11111111-1111-4111-8111-111111111111",
        status: "planning" as const,
      })),
    };
    const lifecycle = new PersonalWikiLifecycle({
      rootResolver,
      runStore,
      skillAdapter,
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    await expect(
      lifecycle.begin({
        mode: "update",
        wikiRoot,
        skills: ["personal-wiki"],
      }),
    ).resolves.toEqual({
      ok: true,
      protocol: "selfopenwiki:personal-openwiki-v1",
      recovery: { action: "none" },
      runId: "11111111-1111-4111-8111-111111111111",
      runtimeRoot: `${wikiRoot}.selfopenwiki`,
      binding: {
        markdownWikiRevision,
        runtimeRoot: `${wikiRoot}.selfopenwiki`,
        skillAggregateHash,
        upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
        wikiRevision,
        wikiRoot,
      },
      skillAggregateHash,
      status: "planning",
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
      wikiRevision,
      wikiRoot,
    });
    expect(rootResolver.resolve).toHaveBeenCalledWith(wikiRoot);
    expect(skillAdapter.resolve).toHaveBeenCalledWith(["personal-wiki"]);
    expect(runStore.begin).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "update",
        markdownWikiRevision,
        runtimeRoot: `${wikiRoot}.selfopenwiki`,
        skillAggregateHash,
        wikiRevision,
      }),
    );
    const beginInput = (
      runStore.begin.mock.calls as unknown as Array<[Record<string, unknown>]>
    )[0]?.[0];
    expect(beginInput).not.toHaveProperty("compatibilityManifestHash");
    expect(beginInput).not.toHaveProperty("force");
    expect(beginInput).not.toHaveProperty("language");
    expect(beginInput).not.toHaveProperty("sourceConfirmation");
    expect(beginInput).not.toHaveProperty("sourceManifestId");
  });

  test("personal Skill adaptation always binds the checked-in Skill and upstream revision", async () => {
    const skillPath = path.resolve(
      import.meta.dirname,
      "..",
      "..",
      "agent-skills",
      "self-openwiki",
      "SKILL.md",
    );
    const adapter = new PersonalSkillAdapter({
      skillPath,
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    await expect(adapter.resolve([])).resolves.toEqual({
      skillAggregateHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
      skillIds: ["kg-c7-project-wiki", "self-openwiki"],
    });
    await expect(adapter.resolve(["invalid skill"])).rejects.toMatchObject({
      code: "skill_untrusted",
    });
  });

  test("submit_plan starts one C7 candidate transaction and returns the bound queue", async () => {
    const wikiRoot = path.resolve("personal-wiki");
    const runId = "33333333-3333-4333-8333-333333333333";
    const planHash = hash("c");
    const queueHash = hash("d");
    const state = {
      runId,
      mode: "update" as const,
      wikiRoot,
      runtimeRoot: `${wikiRoot}.selfopenwiki`,
      wikiRevision: hash("a"),
      skillAggregateHash: hash("b"),
    };
    const runStore = {
      begin: vi.fn(async () => ({ runId, status: "planning" as const })),
      read: vi.fn(async () => state),
      submitPlan: vi.fn(async () => ({
        pageCount: 1,
        planHash,
        queueHash,
      })),
      attachCandidate: vi.fn(async () => undefined),
    };
    const candidate = {
      candidateBindingHash: hash("e"),
      candidateRoot: path.join(
        state.runtimeRoot,
        "transactions",
        "tx",
        "candidate",
      ),
      candidateRootHash: state.wikiRevision,
      generation: 1 as const,
      transactionId: "external-12345678",
      wikiRevision: state.wikiRevision,
    };
    const c7 = { start: vi.fn(async () => candidate) };
    const lifecycle = new PersonalWikiLifecycle({
      c7,
      rootResolver: {
        resolve: vi.fn(async () => ({
          runtimeRoot: state.runtimeRoot,
          wikiRevision: state.wikiRevision,
          wikiRoot,
        })),
      },
      runStore,
      skillAdapter: {
        resolve: vi.fn(async () => ({
          skillAggregateHash: state.skillAggregateHash,
          skillIds: ["self-openwiki"],
        })),
      },
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    await expect(
      lifecycle.submitPlan({
        confirmedByUser: true,
        pages: [{ path: "index.md", purpose: "Index.", title: "Index" }],
        runId,
      }),
    ).resolves.toEqual({
      binding: {
        candidateBindingHash: candidate.candidateBindingHash,
        candidateRootHash: candidate.candidateRootHash,
        generation: 1,
        planHash,
        queueHash,
        runId,
        transactionId: candidate.transactionId,
        wikiRevision: state.wikiRevision,
      },
      ok: true,
      pageCount: 1,
      planHash,
      protocol: "selfopenwiki:personal-openwiki-v1",
      recovery: { action: "none" },
      runId,
      queueHash,
      status: "plan_accepted",
    });
    expect(c7.start).toHaveBeenCalledWith(
      expect.objectContaining({
        runId,
        wikiRoot,
        wikiRevision: state.wikiRevision,
      }),
    );
    expect(runStore.attachCandidate).toHaveBeenCalledWith(runId, candidate);
  });

  test("next_page returns only the assigned page and its isolated candidate write package", async () => {
    const wikiRoot = path.resolve("personal-wiki");
    const runId = "44444444-4444-4444-8444-444444444444";
    const candidate = {
      candidateBindingHash: hash("e"),
      candidateRoot: path.join(
        `${wikiRoot}.selfopenwiki`,
        "transactions",
        "tx",
        "candidate",
      ),
      candidateRootHash: hash("a"),
      generation: 1 as const,
      transactionId: "external-12345678",
      wikiRevision: hash("a"),
    };
    const job = {
      issueClaims: [] as const,
      jobId: "55555555-5555-4555-8555-555555555555",
      path: "index.md",
      purpose: "Index.",
      status: "assigned" as const,
      title: "Index",
    };
    const state = {
      candidate,
      planHash: hash("c"),
      queueHash: hash("d"),
      runId,
      runtimeRoot: `${wikiRoot}.selfopenwiki`,
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot,
    };
    const runStore = {
      begin: vi.fn(),
      nextPage: vi.fn(async () => job),
      read: vi.fn(async () => state),
    };
    const lifecycle = new PersonalWikiLifecycle({
      rootResolver: {} as never,
      runStore,
      skillAdapter: {} as never,
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    await expect(lifecycle.nextPage({ runId })).resolves.toEqual({
      binding: {
        candidateBindingHash: candidate.candidateBindingHash,
        candidateRootHash: candidate.candidateRootHash,
        generation: 1,
        planHash: state.planHash,
        queueHash: state.queueHash,
        runId,
        transactionId: candidate.transactionId,
        wikiRevision: candidate.wikiRevision,
      },
      candidate: {
        pagePath: "index.md",
        permissions: ["read", "list", "write"],
        rootPath: candidate.candidateRoot,
      },
      issueClaims: [],
      jobId: job.jobId,
      ok: true,
      path: job.path,
      protocol: "selfopenwiki:personal-openwiki-v1",
      purpose: job.purpose,
      recovery: { action: "none" },
      relatedPages: [],
      runId,
      seedPaths: [],
      status: "page_pending",
      title: job.title,
    });
  });

  test("inspect_page_claims returns the complete current Claim set without changing the run", async () => {
    const wikiRoot = path.resolve("personal-wiki");
    const runId = "66666666-6666-4666-8666-666666666666";
    const jobId = "77777777-7777-4777-8777-777777777777";
    const state = {
      candidate: {
        candidateBindingHash: hash("e"),
        candidateRoot: path.join(`${wikiRoot}.selfopenwiki`, "candidate"),
        candidateRootHash: hash("a"),
        generation: 1 as const,
        transactionId: "external-12345678",
        wikiRevision: hash("a"),
      },
      planHash: hash("c"),
      queueHash: hash("d"),
      runId,
      runtimeRoot: `${wikiRoot}.selfopenwiki`,
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot,
    };
    const claims = [
      {
        evidence: [{ resource: "wiki://source.md" }],
        id: "claim-12345678",
        statement: "The guide exists.",
      },
    ];
    const runStore = {
      begin: vi.fn(),
      inspectClaims: vi.fn(async () => ({ claims, jobId })),
      read: vi.fn(async () => state),
    };
    const lifecycle = new PersonalWikiLifecycle({
      rootResolver: {} as never,
      runStore,
      skillAdapter: {} as never,
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    const result = await lifecycle.inspectPageClaims({ runId, jobId });
    expect(result).toMatchObject({
      binding: expect.objectContaining({ runId }),
      claims,
      claimsHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
      jobId,
      ok: true,
      protocol: "selfopenwiki:personal-openwiki-v1",
      recovery: { action: "none" },
      status: "claims_inspected",
    });
    expect(runStore.inspectClaims).toHaveBeenCalledWith(runId, jobId);
  });

  test.each([
    { status: undefined, accepted: true },
    { status: "draft", accepted: true },
    { status: "stable", accepted: true },
    { status: "deprecated", accepted: true },
    { status: "provisional", accepted: true },
    { status: "not-a-status", accepted: false },
    { status: "PROVISIONAL", accepted: false },
  ])("submit_page validates $status", async ({ status, accepted }) => {
    const wikiRoot = path.resolve("personal-wiki");
    const runId = "88888888-8888-4888-8888-888888888888";
    const jobId = "99999999-9999-4999-8999-999999999999";
    const candidateRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-page-"),
    );
    const runtimeRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-page-runtime-"),
    );
    try {
      await writeFile(
        path.join(candidateRoot, "index.md"),
        `---\ntype: concept\ntitle: Index\ndescription: Index page.\ntags: [index]\n${status === undefined ? "" : `status: ${status}\n`}---\n\n# Index\n`,
        "utf8",
      );
      const candidate = {
        candidateBindingHash: hash("e"),
        candidateRoot,
        candidateRootHash: hash("a"),
        generation: 1 as const,
        transactionId: "external-12345678",
        wikiRevision: hash("a"),
      };
      const state = {
        candidate,
        planHash: hash("c"),
        queueHash: hash("d"),
        runId,
        runtimeRoot,
        skillAggregateHash: hash("b"),
        wikiRevision: hash("a"),
        wikiRoot,
      };
      const runStore = {
        acceptPage: vi.fn(async () => ({ remainingPages: 0 })),
        begin: vi.fn(),
        readJob: vi.fn(async () => ({
          issueClaims: [
            {
              evidence: [{ resource: "wiki://source.md" }],
              id: "claim-12345678",
              statement: "The guide exists.",
            },
          ],
          jobId,
          path: "index.md",
          purpose: "Index.",
          status: "assigned" as const,
          title: "Index",
        })),
        read: vi.fn(async () => state),
      };
      const lifecycle = new PersonalWikiLifecycle({
        rootResolver: {} as never,
        runStore,
        skillAdapter: {} as never,
        upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
      });

      const submitted = lifecycle.submitPage({
        confirmedClaimIds: ["claim-12345678"],
        jobId,
        runId,
      });
      if (!accepted) {
        await expect(submitted).rejects.toMatchObject({
          code: "validation_failed",
        });
        expect(runStore.acceptPage).not.toHaveBeenCalled();
        return;
      }
      const result = await submitted;
      expect(result).toMatchObject({
        binding: expect.objectContaining({ runId }),
        candidateBindingHash: candidate.candidateBindingHash,
        claimDecisionHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
        jobId,
        ok: true,
        pageContentHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
        protocol: "selfopenwiki:personal-openwiki-v1",
        recovery: { action: "none" },
        remainingPages: 0,
        runId,
        status: "page_accepted",
      });
      expect(runStore.acceptPage).toHaveBeenCalledWith(
        expect.objectContaining({
          jobId,
          pageContentHash: expect.any(String),
          runId,
        }),
      );
      const marker = JSON.parse(
        await readFile(
          path.join(runtimeRoot, "page-markers", runId, `${jobId}.json`),
          "utf8",
        ),
      ) as Record<string, unknown>;
      expect(marker).toMatchObject({
        candidateBindingHash: candidate.candidateBindingHash,
        candidateRootHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
        claimDecisionHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
        pageContentHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
        pagePath: "index.md",
        pagePathHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
        state: "accepted",
      });
      await expect(snapshotMarkdownTree(candidateRoot)).resolves.toMatchObject({
        files: expect.any(Array),
        rootHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
      });
    } finally {
      await rm(candidateRoot, { force: true, recursive: true });
      await rm(runtimeRoot, { force: true, recursive: true });
    }
  });

  test("finish returns review_required until all accepted pages receive a C7 candidate receipt", async () => {
    const wikiRoot = path.resolve("personal-wiki");
    const runId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const candidate = {
      candidateBindingHash: hash("e"),
      candidateRoot: path.join(`${wikiRoot}.selfopenwiki`, "candidate"),
      candidateRootHash: hash("a"),
      generation: 1 as const,
      transactionId: "external-12345678",
      wikiRevision: hash("a"),
    };
    const state = {
      candidate,
      jobs: [
        {
          issueClaims: [],
          jobId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          path: "index.md",
          purpose: "Index.",
          status: "accepted" as const,
          title: "Index",
        },
      ],
      planHash: hash("c"),
      queueHash: hash("d"),
      runId,
      runtimeRoot: `${wikiRoot}.selfopenwiki`,
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot,
    };
    const runStore = {
      begin: vi.fn(),
      read: vi.fn(async () => state),
    };
    const c7 = {
      prepareReview: vi.fn(),
      start: vi.fn(),
      submitReview: vi.fn(),
    };
    const lifecycle = new PersonalWikiLifecycle({
      c7,
      rootResolver: {} as never,
      runStore,
      skillAdapter: {} as never,
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    await expect(lifecycle.finish({ runId })).resolves.toEqual({
      binding: expect.objectContaining({ runId }),
      nextAction: "submit_candidate_receipt",
      ok: true,
      protocol: "selfopenwiki:personal-openwiki-v1",
      recovery: { action: "none" },
      generation: 1,
      runId,
      status: "review_required",
      transactionId: candidate.transactionId,
    });
    expect(c7.prepareReview).not.toHaveBeenCalled();
    expect(c7.submitReview).not.toHaveBeenCalled();
  });

  test("finish maps the C7 review package to a resumable review_required state", async () => {
    const wikiRoot = path.resolve("personal-wiki");
    const runId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    const candidate = {
      candidateBindingHash: hash("e"),
      candidateRoot: path.join(`${wikiRoot}.selfopenwiki`, "candidate"),
      candidateRootHash: hash("a"),
      generation: 1 as const,
      transactionId: "external-12345678",
      wikiRevision: hash("a"),
    };
    const state = {
      candidate,
      jobs: [
        {
          issueClaims: [],
          jobId: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
          path: "index.md",
          purpose: "Index.",
          status: "accepted" as const,
          title: "Index",
        },
      ],
      planHash: hash("c"),
      queueHash: hash("d"),
      runId,
      runtimeRoot: `${wikiRoot}.selfopenwiki`,
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot,
    };
    const candidateReceipt = {
      bindingHash: candidate.candidateBindingHash,
      classification: "minor" as const,
      generation: 1 as const,
      issues: [],
      questions: [],
      summary: "Candidate complete.",
      transactionId: candidate.transactionId,
      type: "external_candidate_receipt" as const,
      version: 1 as const,
      writerExecutionId: "writer-12345678",
    };
    const reviewPackageHash = hash("f");
    const runStore = {
      begin: vi.fn(),
      read: vi.fn(async () => state),
    };
    const c7 = {
      prepareReview: vi.fn(async () => ({
        candidateReceiptHash: hash("g"),
        candidateRootHash: hash("h"),
        kind: "review_ready" as const,
        reviewPackage: { transactionId: candidate.transactionId },
        reviewPackageHash,
      })),
      start: vi.fn(),
      submitReview: vi.fn(),
    };
    const lifecycle = new PersonalWikiLifecycle({
      c7,
      rootResolver: {} as never,
      runStore,
      skillAdapter: {} as never,
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    await expect(
      lifecycle.finish({ candidateReceipt, runId }),
    ).resolves.toEqual({
      binding: expect.objectContaining({ runId }),
      nextAction: "submit_review_receipt",
      ok: true,
      protocol: "selfopenwiki:personal-openwiki-v1",
      recovery: { action: "none" },
      generation: 1,
      candidateReceiptHash: hash("g"),
      candidateRootHash: hash("h"),
      reviewPackage: { transactionId: candidate.transactionId },
      reviewPackageHash,
      runId,
      status: "review_required",
      transactionId: candidate.transactionId,
    });
    expect(c7.prepareReview).toHaveBeenCalledWith({
      runId,
      candidateReceipt,
      runtimeRoot: state.runtimeRoot,
      wikiRoot: state.wikiRoot,
    });
  });

  test("finish exposes complete only after C7 reports a published CAS result", async () => {
    const wikiRoot = path.resolve("personal-wiki");
    const runId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    const candidate = {
      candidateBindingHash: hash("e"),
      candidateRoot: path.join(`${wikiRoot}.selfopenwiki`, "candidate"),
      candidateRootHash: hash("a"),
      generation: 1 as const,
      transactionId: "external-12345678",
      wikiRevision: hash("a"),
    };
    const state = {
      candidate,
      jobs: [
        {
          issueClaims: [],
          jobId: "ffffffff-ffff-4fff-8fff-ffffffffffff",
          path: "index.md",
          purpose: "Index.",
          status: "accepted" as const,
          title: "Index",
        },
      ],
      planHash: hash("c"),
      queueHash: hash("d"),
      runId,
      runtimeRoot: `${wikiRoot}.selfopenwiki`,
      skillAggregateHash: hash("b"),
      wikiRevision: hash("a"),
      wikiRoot,
    };
    const reviewReceipt = {
      bindingHash: candidate.candidateBindingHash,
      candidateReceiptHash: hash("a"),
      candidateRootHash: candidate.candidateRootHash,
      generation: 1 as const,
      issues: [],
      reviewPackageHash: hash("f"),
      reviewerExecutionId: "reviewer-12345678",
      transactionId: candidate.transactionId,
      type: "external_review_receipt" as const,
      verdict: "pass" as const,
      version: 1 as const,
    };
    const runStore = {
      begin: vi.fn(),
      read: vi.fn(async () => state),
    };
    const c7 = {
      prepareReview: vi.fn(),
      start: vi.fn(),
      submitReview: vi.fn(async () => ({
        afterWikiHash: hash("h"),
        beforeWikiHash: state.wikiRevision,
        followUp: [
          {
            code: "follow_up",
            message: "Refresh this page in the next pass.",
            severity: "provisional" as const,
          },
        ],
        kind: "complete" as const,
        reviewReceiptHash: hash("i"),
        runReceiptHash: hash("j"),
        wikiRevision: hash("h"),
      })),
    };
    const lifecycle = new PersonalWikiLifecycle({
      c7,
      rootResolver: {} as never,
      runStore,
      skillAdapter: {} as never,
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    await expect(lifecycle.finish({ reviewReceipt, runId })).resolves.toEqual(
      expect.objectContaining({
        afterWikiHash: hash("h"),
        beforeWikiHash: state.wikiRevision,
        published: true,
        reviewReceiptHash: hash("i"),
        runReceiptHash: hash("j"),
        status: "complete",
        followUp: [
          {
            code: "follow_up",
            message: "Refresh this page in the next pass.",
            severity: "provisional",
          },
        ],
        wikiRevision: hash("h"),
      }),
    );
    expect(c7.submitReview).toHaveBeenCalledWith({
      beforeWikiHash: state.wikiRevision,
      reviewReceipt,
      runId,
      runtimeRoot: state.runtimeRoot,
      wikiRoot: state.wikiRoot,
    });
  });

  test("finish persists accepted sparse Claims into the formal Wiki sidecar", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-finish-claims-"),
    );
    const runtimeRoot = `${wikiRoot}.selfopenwiki`;
    const runId = "abababab-abab-4aba-8aba-abababababab";
    const jobId = "cdcdcdcd-cdcd-4cdc-8cdc-cdcdcdcdcdcd";
    const newJobId = "dededede-dede-4ded-8ded-dededededede";
    await writeFile(path.join(wikiRoot, "guide.md"), "# Guide\n", "utf8");
    await mkdir(runtimeRoot, { recursive: true });
    const markdownWikiRevision = (await snapshotMarkdownTree(wikiRoot))
      .rootHash;
    const personalWikiRevision = (await snapshotPersonalWiki(wikiRoot))
      .rootHash;
    const candidate = {
      candidateBindingHash: hash("e"),
      candidateRoot: path.join(runtimeRoot, "candidate"),
      candidateRootHash: hash("candidate-initial"),
      generation: 1 as const,
      transactionId: "external-12345678",
      wikiRevision: hash("a"),
    };
    const candidatePage = "# Guide v2\n";
    const newCandidatePage = "# New page\n";
    await mkdir(candidate.candidateRoot, { recursive: true });
    await writeFile(
      path.join(candidate.candidateRoot, "guide.md"),
      candidatePage,
      "utf8",
    );
    await writeFile(
      path.join(candidate.candidateRoot, "new.md"),
      newCandidatePage,
      "utf8",
    );
    const candidateRootRevision = (
      await snapshotMarkdownTree(candidate.candidateRoot)
    ).rootHash;
    const state = {
      candidate,
      deletePages: [],
      jobs: [
        {
          claimDecisions: [
            {
              evidence: [{ resource: "repo://src/guide.ts" }],
              statement: "The guide exists.",
            },
          ],
          issueClaims: [],
          jobId,
          path: "guide.md",
          purpose: "Guide.",
          status: "accepted" as const,
          title: "Guide",
        },
        {
          issueClaims: [],
          jobId: newJobId,
          path: "new.md",
          purpose: "Add a new page.",
          status: "accepted" as const,
          title: "New page",
        },
      ],
      planHash: hash("c"),
      queueHash: hash("d"),
      runId,
      runtimeRoot,
      skillAggregateHash: hash("b"),
      markdownWikiRevision,
      wikiRevision: personalWikiRevision,
      wikiRoot,
    };
    const runStore = {
      begin: vi.fn(),
      read: vi.fn(async () => state),
      setPhase: vi.fn(),
      setWikiRevision: vi.fn(),
    };
    const c7 = {
      start: vi.fn(),
      submitReview: vi.fn(async () => {
        const journal = JSON.parse(
          await readFile(
            path.join(runtimeRoot, "personal-claims-finalization.json"),
            "utf8",
          ),
        );
        const marker = JSON.parse(
          await readFile(
            path.join(runtimeRoot, "personal-finalization.json"),
            "utf8",
          ),
        );
        expect(journal.status).toBe("prepared");
        expect(marker.status).toBe("prepared");
        await writeFile(path.join(wikiRoot, "guide.md"), candidatePage, "utf8");
        await writeFile(
          path.join(wikiRoot, "new.md"),
          newCandidatePage,
          "utf8",
        );
        const published = await snapshotMarkdownTree(wikiRoot);
        expect(published.rootHash).toBe(candidateRootRevision);
        return {
          afterWikiHash: published.rootHash,
          beforeWikiHash: markdownWikiRevision,
          kind: "complete" as const,
          reviewReceiptHash: hash("i"),
          runReceiptHash: hash("j"),
          wikiRevision: markdownWikiRevision,
        };
      }),
    };
    try {
      const result = await new PersonalWikiLifecycle({
        c7,
        claimsResolver: new FilePersonalClaimsResolver(),
        rootResolver: {} as never,
        runStore,
        skillAdapter: {} as never,
        upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
      }).finish({
        reviewReceipt: {
          bindingHash: candidate.candidateBindingHash,
          candidateReceiptHash: hash("a"),
          candidateRootHash: candidateRootRevision,
          generation: 1,
          issues: [],
          reviewPackageHash: hash("f"),
          reviewerExecutionId: "reviewer-12345678",
          transactionId: candidate.transactionId,
          type: "external_review_receipt",
          verdict: "pass",
          version: 1,
        },
        runId,
      });
      expect(result).toMatchObject({ status: "complete", published: true });
      const sidecar = JSON.parse(
        await readFile(path.join(wikiRoot, ".claims", "guide.json"), "utf8"),
      );
      expect(sidecar.claims).toHaveLength(1);
      expect(sidecar.pageVersion).toMatch(/^sha256:[a-f0-9]{64}$/u);
      const newSidecar = JSON.parse(
        await readFile(path.join(wikiRoot, ".claims", "new.json"), "utf8"),
      );
      expect(newSidecar.claims).toEqual([]);
      expect(newSidecar.pageVersion).toMatch(/^sha256:[a-f0-9]{64}$/u);
      expect(runStore.setWikiRevision).toHaveBeenCalledWith(
        runId,
        expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
      );
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
      await rm(runtimeRoot, { force: true, recursive: true });
    }
  });

  test("recovers an idempotent partial Claims finalization journal", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-recovery-"),
    );
    const runtimeRoot = `${wikiRoot}.selfopenwiki`;
    const runId = "abababab-abab-4aba-8aba-abababababab";
    const transactionId = "external-12345678";
    const bindingHash = hash("b");
    const reviewReceiptInputHash = hash("c");
    const claim = (statement: string) => [
      {
        evidence: [{ resource: "repo://src/guide.ts" }],
        id: `claim-${statement.toLowerCase()}`,
        statement,
      },
    ];
    try {
      await mkdir(runtimeRoot, { recursive: true });
      await writeFile(path.join(wikiRoot, "a.md"), "# A\n", "utf8");
      await writeFile(path.join(wikiRoot, "b.md"), "# B\n", "utf8");
      const aBytes = await readFile(path.join(wikiRoot, "a.md"));
      const bBytes = await readFile(path.join(wikiRoot, "b.md"));
      const aPayload = createPersonalClaimsPayload(claim("A"), aBytes);
      const bPayload = createPersonalClaimsPayload(claim("B"), bBytes);
      await mkdir(path.join(wikiRoot, ".claims"), { recursive: true });
      await writeFile(path.join(wikiRoot, ".claims", "a.json"), aPayload.bytes);
      const markdown = await snapshotMarkdownTree(wikiRoot);
      const expectedClaims = [
        {
          hash: aPayload.hash,
          relativePath: ".claims/a.json",
          size: aPayload.bytes.byteLength,
        },
        {
          hash: bPayload.hash,
          relativePath: ".claims/b.json",
          size: bPayload.bytes.byteLength,
        },
      ];
      const currentClaimsHash = personalHash([]);
      await writeFile(
        path.join(runtimeRoot, "personal-claims-finalization.json"),
        `${canonicalPersonalJson({
          afterWikiHash: markdown.rootHash,
          baselineClaimsHash: personalHash([]),
          bindingHash,
          applyingOperation: 0,
          completedOperations: [],
          currentClaimsHash,
          expectedFinalClaimsHash: personalHash(expectedClaims),
          generation: 1,
          operations: [
            {
              action: "write",
              afterClaimsHash: personalHash([expectedClaims[0]]),
              claims: claim("A"),
              desiredSidecarHash: aPayload.hash,
              desiredSidecarSize: aPayload.bytes.byteLength,
              expectedSidecarHash: null,
              pageHash: hashPersonalClaimsBytes(aBytes),
              pagePath: "a.md",
            },
            {
              action: "write",
              afterClaimsHash: personalHash(expectedClaims),
              claims: claim("B"),
              desiredSidecarHash: bPayload.hash,
              desiredSidecarSize: bPayload.bytes.byteLength,
              expectedSidecarHash: null,
              pageHash: hashPersonalClaimsBytes(bBytes),
              pagePath: "b.md",
            },
          ],
          reviewReceiptInputHash,
          runId,
          runtimeRoot,
          status: "applying",
          transactionId,
          type: "selfopenwiki:personal-claims-finalization-v1",
          version: 1,
        })}\n`,
        "utf8",
      );
      await writeFile(
        path.join(runtimeRoot, "personal-finalization.json"),
        `${canonicalPersonalJson({
          afterWikiHash: markdown.rootHash,
          bindingHash,
          generation: 1,
          reviewReceiptHash: hash("d"),
          reviewReceiptInputHash,
          runId,
          status: "published",
          transactionId,
          type: "selfopenwiki:personal-finalization-v1",
          version: 1,
        })}\n`,
        "utf8",
      );

      const recovered = await recoverPersonalClaimsFinalization(
        runtimeRoot,
        wikiRoot,
      );
      expect(recovered?.snapshot.claims).toHaveLength(2);
      expect(
        JSON.parse(
          await readFile(path.join(wikiRoot, ".claims", "b.json"), "utf8"),
        ).claims,
      ).toEqual(
        claim("B").map((item) => ({
          ...item,
          evidence: [
            {
              resource: "repo://src/guide.ts",
              version: expect.stringMatching(/^personal-resource-v1:/u),
            },
          ],
        })),
      );
      expect(recovered?.journal.completedOperations).toEqual([0, 1]);
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
      await rm(runtimeRoot, { force: true, recursive: true });
    }
  });

  test("recovers when C7 published before the finalization marker advanced", async () => {
    const wikiRoot = await mkdtemp(
      path.join(os.tmpdir(), "personal-claims-published-window-"),
    );
    const runtimeRoot = `${wikiRoot}.selfopenwiki`;
    const runId = "abababab-abab-4aba-8aba-abababababab";
    const transactionId = "external-12345678";
    const bindingHash = hash("b");
    const reviewReceiptInputHash = hash("c");
    const claims = [
      {
        evidence: [{ resource: "repo://src/guide.ts" }],
        id: "claim-guide",
        statement: "The guide exists.",
      },
    ];
    try {
      await mkdir(runtimeRoot, { recursive: true });
      const pageBytes = Buffer.from("# Guide v2\n", "utf8");
      await writeFile(path.join(wikiRoot, "guide.md"), pageBytes);
      const payload = createPersonalClaimsPayload(claims, pageBytes);
      const markdown = await snapshotMarkdownTree(wikiRoot);
      const expectedClaims = [
        {
          hash: payload.hash,
          relativePath: ".claims/guide.json",
          size: payload.bytes.byteLength,
        },
      ];
      await writeFile(
        path.join(runtimeRoot, "personal-claims-finalization.json"),
        `${canonicalPersonalJson({
          afterWikiHash: markdown.rootHash,
          baselineClaimsHash: personalHash([]),
          bindingHash,
          completedOperations: [],
          currentClaimsHash: personalHash([]),
          expectedFinalClaimsHash: personalHash(expectedClaims),
          generation: 1,
          operations: [
            {
              action: "write",
              afterClaimsHash: personalHash(expectedClaims),
              claims,
              desiredSidecarHash: payload.hash,
              desiredSidecarSize: payload.bytes.byteLength,
              expectedSidecarHash: null,
              pageHash: hashPersonalClaimsBytes(pageBytes),
              pagePath: "guide.md",
            },
          ],
          reviewReceiptInputHash,
          runId,
          runtimeRoot,
          status: "prepared",
          transactionId,
          type: "selfopenwiki:personal-claims-finalization-v1",
          version: 1,
        })}\n`,
        "utf8",
      );
      await writeFile(
        path.join(runtimeRoot, "personal-finalization.json"),
        `${canonicalPersonalJson({
          bindingHash,
          generation: 1,
          reviewReceiptInputHash,
          runId,
          status: "prepared",
          transactionId,
          type: "selfopenwiki:personal-finalization-v1",
          version: 1,
        })}\n`,
        "utf8",
      );

      const rootResolver = {
        resolve: vi.fn(async () => ({
          markdownWikiRevision: markdown.rootHash,
          runtimeRoot,
          wikiRevision: hash("d"),
          wikiRoot,
        })),
      };
      const skillAdapter = {
        resolve: vi.fn(async () => ({
          skillAggregateHash: hash("e"),
          skillIds: ["personal-wiki"],
        })),
      };
      const state = {
        candidate: {
          candidateBindingHash: bindingHash,
          candidateRoot: path.join(runtimeRoot, "candidate"),
          candidateRootHash: hash("f"),
          generation: 1 as const,
          transactionId,
          wikiRevision: markdown.rootHash,
        },
        runId,
        runtimeRoot,
        skillAggregateHash: hash("e"),
        wikiRevision: hash("d"),
        wikiRoot,
      };
      const persistedStore = new FilePersonalRunStore({
        runtimeRoot,
        createRunId: () => runId,
      });
      await persistedStore.begin({
        mode: "update",
        requestedSkills: ["personal-wiki"],
        skillIds: ["personal-wiki"],
        skillAggregateHash: state.skillAggregateHash,
        wikiRevision: state.wikiRevision,
        wikiRoot,
        runtimeRoot,
      });
      await persistedStore.attachCandidate(runId, state.candidate);
      await persistedStore.setPhase(runId, "review");
      expect((await persistedStore.read(runId)).phase).toBe("review");
      const runStore = new PersonalRunStoreRouter();
      const result = await new PersonalWikiLifecycle({
        claimsResolver: {} as never,
        rootResolver,
        runStore,
        skillAdapter,
        upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
      }).begin({
        mode: "update",
        skills: ["personal-wiki"],
        wikiRoot,
      });
      const finalSnapshot = await snapshotPersonalWiki(wikiRoot);

      expect(finalSnapshot.claims).toEqual([
        {
          hash: payload.hash,
          relativePath: ".claims/guide.json",
          size: payload.bytes.byteLength,
        },
      ]);
      expect(await runStore.read(runId)).toMatchObject({
        phase: "complete",
        markdownWikiRevision: markdown.rootHash,
        wikiRevision: finalSnapshot.rootHash,
      });
      expect(result).toMatchObject({
        status: "noop",
        wikiRevision: finalSnapshot.rootHash,
      });
      await expect(
        readFile(path.join(runtimeRoot, "personal-finalization.json"), "utf8"),
      ).rejects.toMatchObject({ code: "ENOENT" });
      await expect(
        readFile(
          path.join(runtimeRoot, "personal-claims-finalization.json"),
          "utf8",
        ),
      ).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(wikiRoot, { force: true, recursive: true });
      await rm(runtimeRoot, { force: true, recursive: true });
    }
  });

  test("creates a new personal page-job generation for a C7 repair", async () => {
    const wikiRoot = path.resolve("personal-wiki");
    const runId = "12121212-1212-4121-8121-121212121212";
    const oldCandidate = {
      candidateBindingHash: hash("a"),
      candidateRoot: path.join(`${wikiRoot}.selfopenwiki`, "generation-1"),
      candidateRootHash: hash("b"),
      generation: 1 as const,
      transactionId: "external-12345678",
      wikiRevision: hash("c"),
    };
    const nextCandidate = {
      ...oldCandidate,
      candidateBindingHash: hash("d"),
      candidateRoot: path.join(`${wikiRoot}.selfopenwiki`, "generation-2"),
      candidateRootHash: hash("e"),
      generation: 2 as const,
    };
    const state = {
      candidate: oldCandidate,
      jobs: [
        {
          issueClaims: [],
          jobId: "13131313-1313-4131-8131-131313131313",
          path: "index.md",
          purpose: "Index.",
          status: "accepted" as const,
          title: "Index",
        },
      ],
      planHash: hash("f"),
      queueHash: hash("g"),
      runId,
      runtimeRoot: `${wikiRoot}.selfopenwiki`,
      skillAggregateHash: hash("h"),
      wikiRevision: hash("c"),
      wikiRoot,
    };
    const reviewReceipt = {
      bindingHash: oldCandidate.candidateBindingHash,
      candidateReceiptHash: hash("a"),
      candidateRootHash: oldCandidate.candidateRootHash,
      generation: 1 as const,
      issues: [
        {
          code: "clarify",
          message: "Clarify the page.",
          severity: "minor" as const,
        },
      ],
      reviewPackageHash: hash("b"),
      reviewerExecutionId: "reviewer-12345678",
      transactionId: oldCandidate.transactionId,
      type: "external_review_receipt" as const,
      verdict: "changes_requested" as const,
      version: 1 as const,
    };
    const runStore = {
      begin: vi.fn(),
      beginSuccessor: vi.fn(async () => ({ queueHash: hash("k") })),
      read: vi.fn(async () => state),
    };
    const c7 = {
      resumeRepair: vi.fn(async () => nextCandidate),
      start: vi.fn(),
      submitReview: vi.fn(async () => ({
        issues: [
          {
            code: "clarify",
            message: "Clarify the page.",
            severity: "minor" as const,
          },
        ],
        kind: "repair_ready" as const,
      })),
    };
    const lifecycle = new PersonalWikiLifecycle({
      c7,
      rootResolver: {} as never,
      runStore,
      skillAdapter: {} as never,
      upstreamCommit: "d1c7fc75a6a906da258cd94dbcb1602f98516480",
    });

    await expect(lifecycle.finish({ reviewReceipt, runId })).resolves.toEqual(
      expect.objectContaining({
        binding: expect.objectContaining({
          candidateBindingHash: nextCandidate.candidateBindingHash,
          generation: 2,
          queueHash: hash("k"),
        }),
        generation: 2,
        nextAction: "resume",
        status: "repair_ready",
      }),
    );
    expect(c7.resumeRepair).toHaveBeenCalledWith({
      bindingHash: oldCandidate.candidateBindingHash,
      runId,
      runtimeRoot: state.runtimeRoot,
      transactionId: oldCandidate.transactionId,
      wikiRoot,
    });
    expect(runStore.beginSuccessor).toHaveBeenCalledWith(runId, nextCandidate);
  });
});

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}
