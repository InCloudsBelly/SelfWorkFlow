import {
  access,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test } from "vitest";
import {
  normalizeWikiCandidate,
  stripOpenWikiRuntimeMetadata,
  validateWikiCandidate,
} from "../src/validation.js";
import { snapshotMarkdownTree } from "../src/snapshot.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("deterministic Wiki candidate validation", () => {
  test("accepts bounded OKF Markdown with valid internal links and Mermaid", async () => {
    const root = await createWiki();
    await writePage(
      root,
      "quickstart.md",
      page("Guide", "# Quickstart\n\nSee [rendering](./rendering.md).\n"),
    );
    await writePage(
      root,
      "rendering.md",
      page(
        "Architecture",
        "# Rendering\n\n```mermaid\nflowchart LR\n  A --> B\n```\n",
      ),
    );

    const result = await validateWikiCandidate({ candidateRoot: root });

    expect(result.passed).toBe(true);
    expect(result.checks.every((check) => check.status === "passed")).toBe(
      true,
    );
    expect(result.snapshot?.files).toHaveLength(2);
  });

  test.each([
    ["missing quickstart", { omitQuickstart: true }],
    ["missing OKF type", { content: "---\ntitle: No type\n---\n\n# Bad\n" }],
    ["invalid YAML front matter", { content: "---\ntype: [\n---\n\n# Bad\n" }],
    [
      "broken internal link",
      { content: page("Guide", "# Q\n\n[missing](./missing.md)\n") },
    ],
    [
      "invalid Mermaid fence",
      { content: page("Guide", "# Q\n\n```mermaid\nnot-a-diagram\n```\n") },
    ],
    [
      "unbalanced Mermaid structure",
      {
        content: page(
          "Guide",
          "# Q\n\n```mermaid\nflowchart LR\n  A[bad --> B\n```\n",
        ),
      },
    ],
  ])("rejects %s", async (_label, options) => {
    const root = await createWiki();
    if (!("omitQuickstart" in options && options.omitQuickstart)) {
      await writePage(
        root,
        "quickstart.md",
        ("content" in options ? options.content : undefined) ??
          page("Guide", "# Quickstart\n"),
      );
    }

    const result = await validateWikiCandidate({ candidateRoot: root });

    expect(result.passed).toBe(false);
    expect(result.checks.some((check) => check.status === "failed")).toBe(true);
  });

  test("rejects source copying even when wrapped and excessive page expansion", async () => {
    const beforeRoot = await createWiki();
    await writePage(beforeRoot, "quickstart.md", page("Guide", "# Before\n"));
    await writePage(beforeRoot, "removed.md", page("Guide", "# Removed\n"));
    const beforeSnapshot = await snapshotMarkdownTree(beforeRoot);
    const root = await createWiki();
    const sourceRoot = await createWiki();
    const copiedSource = "class FExactSource {\npublic:\n  void Run();\n};\n";
    await writePage(
      root,
      "quickstart.md",
      page(
        "Guide",
        `# Wrapped\n\nBefore.\n\n\`\`\`cpp\n${copiedSource}\`\`\`\n`,
      ),
    );
    await writeFile(path.join(sourceRoot, "source.cpp"), copiedSource, "utf8");
    await writePage(root, "added.md", page("Guide", "# Added\n"));
    const result = await validateWikiCandidate({
      beforeSnapshot,
      candidateRoot: root,
      forbiddenSourceRoot: sourceRoot,
      maxAddedPages: 0,
    });

    expect(result.passed).toBe(false);
    expect(result.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "source_copy", status: "failed" }),
        expect.objectContaining({ id: "page_expansion", status: "failed" }),
      ]),
    );
  });

  test("validates anchors and constrains autonomous repair paths", async () => {
    const beforeRoot = await createWiki();
    await writePage(
      beforeRoot,
      "quickstart.md",
      page(
        "Guide",
        "# Quickstart\n\nSee [details](./details.md#known-heading).\n",
      ),
    );
    await writePage(
      beforeRoot,
      "details.md",
      page("Guide", "# Known heading\n\nBefore.\n"),
    );
    const beforeSnapshot = await snapshotMarkdownTree(beforeRoot);

    const root = await createWiki();
    await writePage(
      root,
      "quickstart.md",
      page(
        "Guide",
        "# Quickstart\n\nSee [details](./details.md#missing-heading).\n",
      ),
    );
    await writePage(
      root,
      "details.md",
      page("Guide", "# Known heading\n\nAfter.\n"),
    );

    const result = await validateWikiCandidate({
      allowedChangedPaths: ["details.md"],
      beforeSnapshot,
      candidateRoot: root,
    });

    expect(result.passed).toBe(false);
    expect(result.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "internal_links", status: "failed" }),
        expect.objectContaining({ id: "change_scope", status: "failed" }),
      ]),
    );
  });

  test("requires every Wiki page to be reachable from quickstart navigation", async () => {
    const root = await createWiki();
    await writePage(root, "quickstart.md", page("Guide", "# Quickstart\n"));
    await writePage(root, "orphan.md", page("Guide", "# Orphan\n"));

    const result = await validateWikiCandidate({ candidateRoot: root });

    expect(result.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "navigation_index",
          status: "failed",
        }),
      ]),
    );
  });

  test("requires an explicit provisional front-matter marker on a changed page", async () => {
    const beforeRoot = await createWiki();
    await writePage(beforeRoot, "quickstart.md", page("Guide", "# Before\n"));
    const beforeSnapshot = await snapshotMarkdownTree(beforeRoot);
    const root = await createWiki();
    await writePage(root, "quickstart.md", page("Guide", "# Tentative\n"));

    const missing = await validateWikiCandidate({
      beforeSnapshot,
      candidateRoot: root,
      requireProvisionalMarker: true,
    });
    expect(missing.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "provisional_marker",
          status: "failed",
        }),
      ]),
    );

    await writePage(
      root,
      "quickstart.md",
      "---\ntype: Guide\nstatus: provisional\n---\n\n# Tentative\n",
    );
    const marked = await validateWikiCandidate({
      beforeSnapshot,
      candidateRoot: root,
      requireProvisionalMarker: true,
    });
    expect(marked.passed).toBe(true);
  });

  test("removes only the known OpenWiki run metadata before validation", async () => {
    const root = await createWiki();
    await writePage(root, "quickstart.md", page("Guide", "# Quickstart\n"));
    const metadataPath = path.join(root, ".last-update.json");
    await writeFile(metadataPath, '{"gitHead":"abc"}\n', "utf8");

    await stripOpenWikiRuntimeMetadata(root);
    const result = await validateWikiCandidate({ candidateRoot: root });

    expect(result.passed).toBe(true);
    await expect(access(metadataPath)).rejects.toBeDefined();
  });

  test("normalizes only root runtime metadata and preserves every Markdown byte", async () => {
    const root = await createWiki();
    const outside = await createWiki();
    const metadataPath = path.join(root, ".last-update.json");
    const preservedFiles = new Map([
      [path.join(root, "sources", ".last-update.json"), "nested metadata\n"],
      [path.join(root, "index.md"), "root index\n"],
      [path.join(root, "sources", "index.md"), "nested index\n"],
      [path.join(root, "case", "Index.md"), "case-sensitive page\n"],
      [path.join(root, "index.markdown"), "different extension\n"],
      [path.join(root, "log.md"), "log page\n"],
      [path.join(root, "INSTRUCTIONS.md"), "instructions page\n"],
      [path.join(root, "ordinary.md"), page("Guide", "# Ordinary\n")],
    ]);
    await writeFile(metadataPath, '{"gitHead":"abc"}\n', "utf8");
    for (const [target, content] of preservedFiles) {
      await mkdir(path.dirname(target), { recursive: true });
      await writeFile(target, content, "utf8");
    }
    const outsideIndex = path.join(outside, "index.md");
    const outsideSentinel = path.join(outside, "sentinel.txt");
    await writeFile(outsideIndex, "outside index\n", "utf8");
    await writeFile(outsideSentinel, "outside sentinel\n", "utf8");
    await symlink(outside, path.join(root, "linked-outside"), "junction");

    await normalizeWikiCandidate(root);

    await expect(access(metadataPath)).rejects.toBeDefined();
    for (const [target, content] of preservedFiles) {
      await expect(readFile(target, "utf8")).resolves.toBe(content);
    }
    await expect(readFile(outsideIndex, "utf8")).resolves.toBe(
      "outside index\n",
    );
    await expect(readFile(outsideSentinel, "utf8")).resolves.toBe(
      "outside sentinel\n",
    );
  });

  test("keeps extra Markdown visible to strict validation instead of silently deleting it", async () => {
    const root = await createWiki();
    await writePage(
      root,
      "quickstart.md",
      page(
        "Guide",
        "# Quickstart\n\nSee [index](./index.md), [case](./case/Index.md), [log](./log.md), and [instructions](./INSTRUCTIONS.md).\n",
      ),
    );
    const extras = new Map([
      ["index.md", "# Generated index without OKF front matter\n"],
      ["sources/index.md", "# Nested generated index without OKF\n"],
      ["case/Index.md", page("Guide", "# Case-sensitive page\n")],
      ["index.markdown", "different extension\n"],
      ["log.md", page("Guide", "# Log\n")],
      ["INSTRUCTIONS.md", page("Guide", "# Instructions\n")],
    ]);
    for (const [relativePath, content] of extras) {
      await writePage(root, relativePath, content);
    }

    await normalizeWikiCandidate(root);
    const result = await validateWikiCandidate({ candidateRoot: root });

    for (const [relativePath, content] of extras) {
      await expect(
        readFile(path.join(root, relativePath), "utf8"),
      ).resolves.toBe(content);
    }
    expect(result.passed).toBe(false);
    expect(result.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "markdown_tree", status: "failed" }),
      ]),
    );
  });

  test("preserves external bytes after a candidate directory is replaced by a Windows junction", async () => {
    const root = await createWiki();
    const outside = await createWiki();
    const replaceable = path.join(root, "replaceable");
    const parked = path.join(outside, "parked-candidate-directory");
    await mkdir(replaceable, { recursive: true });
    await writeFile(path.join(replaceable, "local.md"), "local\n", "utf8");
    await rename(replaceable, parked);
    const outsideIndex = path.join(outside, "index.md");
    const outsideSentinel = path.join(outside, "sentinel.txt");
    await writeFile(outsideIndex, "outside index\n", "utf8");
    await writeFile(outsideSentinel, "outside sentinel\n", "utf8");
    await symlink(outside, replaceable, "junction");

    await normalizeWikiCandidate(root);

    expect((await lstat(replaceable)).isSymbolicLink()).toBe(true);
    await expect(readFile(outsideIndex, "utf8")).resolves.toBe(
      "outside index\n",
    );
    await expect(readFile(outsideSentinel, "utf8")).resolves.toBe(
      "outside sentinel\n",
    );
  });

  test("fails closed when root metadata is not a regular non-link file", async () => {
    const root = await createWiki();
    const metadataPath = path.join(root, ".last-update.json");
    await mkdir(metadataPath);

    await expect(normalizeWikiCandidate(root)).rejects.toThrow(
      "OpenWiki run metadata is not a bounded regular file",
    );

    expect((await lstat(metadataPath)).isDirectory()).toBe(true);
  });

  test("fails closed when the candidate root is missing", async () => {
    const missingRoot = path.join(await createWiki(), "missing");
    await expect(normalizeWikiCandidate(missingRoot)).rejects.toBeDefined();
  });
});

async function createWiki(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-validation-"));
  tempDirs.push(root);
  return root;
}

async function writePage(
  root: string,
  relativePath: string,
  content: string,
): Promise<void> {
  const target = path.join(root, relativePath);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, content, "utf8");
}

function page(type: string, body: string): string {
  return `---\ntype: ${type}\n---\n\n${body}`;
}
