import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test } from "vitest";
import {
  readPersonalCandidateMarker,
  transitionPersonalCandidateMarker,
  writePersonalCandidateMarker,
} from "../src/personal-candidate-marker.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("personal candidate page marker", () => {
  test("writes a strict marker atomically and supports accepted transition", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "personal-marker-"));
    tempDirs.push(root);
    const markerPath = path.join(root, "markers", "job.json");
    const marker = {
      candidateBindingHash: hash("a"),
      candidateRoot: root,
      candidateRootHash: hash("b"),
      claimDecisionHash: hash("c"),
      createdAt: "2026-09-10T10:00:00.000Z",
      generation: 1,
      jobId: "11111111-1111-4111-8111-111111111111",
      pageContentHash: hash("d"),
      pagePath: "index.md",
      pagePathHash: hash("e"),
      runId: "22222222-2222-4222-8222-222222222222",
      state: "candidate_written" as const,
      transactionId: "external-12345678",
      type: "selfopenwiki:candidate-page-marker-v1" as const,
      updatedAt: "2026-09-10T10:00:00.000Z",
      version: 1 as const,
      writerExecutionId: "writer-12345678",
    };

    await writePersonalCandidateMarker(markerPath, marker);
    await expect(readPersonalCandidateMarker(markerPath)).resolves.toEqual(
      marker,
    );
    expect(await readFile(markerPath, "utf8")).toContain("candidate_written");

    await expect(
      transitionPersonalCandidateMarker(
        markerPath,
        "accepted",
        "2026-09-10T10:01:00.000Z",
      ),
    ).resolves.toMatchObject({
      state: "accepted",
      updatedAt: "2026-09-10T10:01:00.000Z",
    });
  });
});

function hash(character: string): string {
  return `sha256:${character.repeat(64)}`;
}
