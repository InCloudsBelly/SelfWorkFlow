import {
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import {
  assertMarkdownTreeVersion,
  copyMarkdownTree,
  snapshotMarkdownTree,
} from "../src/snapshot.js";

const tempDirs: string[] = [];
const snapshotFsHook = vi.hoisted(
  (): {
    afterLstat?: (target: string) => Promise<void>;
    beforeOpen?: (target: string) => Promise<void>;
  } => ({}),
);

vi.mock("node:fs/promises", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:fs/promises")>();
  return {
    ...original,
    lstat: async (target: string) => {
      const stat = await original.lstat(target);
      await snapshotFsHook.afterLstat?.(path.resolve(target));
      return stat;
    },
    open: async (
      target: string,
      flags: Parameters<typeof original.open>[1],
      mode?: Parameters<typeof original.open>[2],
    ) => {
      await snapshotFsHook.beforeOpen?.(path.resolve(target));
      return original.open(target, flags, mode);
    },
  };
});

afterEach(async () => {
  snapshotFsHook.afterLstat = undefined;
  snapshotFsHook.beforeOpen = undefined;
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("deterministic Wiki snapshots", () => {
  test("sorts Markdown paths and binds exact bytes into a root hash", async () => {
    const root = await fixtureRoot();
    await mkdir(path.join(root, "nested"));
    await writeFile(path.join(root, "z.md"), "z\n", "utf8");
    await writeFile(path.join(root, "nested", "a.md"), "a\r\n", "utf8");

    const snapshot = await snapshotMarkdownTree(root);

    expect(snapshot.files.map((file) => file.relativePath)).toEqual([
      "nested/a.md",
      "z.md",
    ]);
    expect(
      snapshot.files.every((file) => /^sha256:[a-f0-9]{64}$/u.test(file.hash)),
    ).toBe(true);
    expect(snapshot.rootHash).toMatch(/^sha256:[a-f0-9]{64}$/u);
  });

  test("excludes the Wiki root Git metadata from the Markdown snapshot", async () => {
    const root = await fixtureRoot();
    await mkdir(path.join(root, ".git"));
    await writeFile(
      path.join(root, ".git", "HEAD"),
      "ref: refs/heads/main\n",
      "utf8",
    );
    await writeFile(path.join(root, "index.md"), "# Home\n", "utf8");

    const snapshot = await snapshotMarkdownTree(root);

    expect(snapshot.files.map((file) => file.relativePath)).toEqual([
      "index.md",
    ]);
  });

  test("rejects a reserved personal runtime directory inside the Wiki root", async () => {
    const root = await fixtureRoot();
    await mkdir(path.join(root, ".selfopenwiki"));
    await expect(snapshotMarkdownTree(root)).rejects.toEqual(
      expect.objectContaining({ code: "wiki_invalid" }),
    );
  });

  test("accepts only regular root Git policy files outside the content snapshot", async () => {
    const root = await fixtureRoot();
    await writeFile(path.join(root, "index.md"), "# Home\n");
    const before = await snapshotMarkdownTree(root);
    await writeFile(path.join(root, ".gitignore"), "*.tmp\n");
    await writeFile(path.join(root, ".gitattributes"), "*.md -text\n");
    await expect(snapshotMarkdownTree(root)).resolves.toEqual(before);
    await rm(path.join(root, ".gitattributes"));
    await mkdir(path.join(root, ".gitattributes"));
    await expect(snapshotMarkdownTree(root)).rejects.toMatchObject({ code: "wiki_invalid" });
  });

  test("copies exactly the captured Wiki and verifies the after tree", async () => {
    const source = await fixtureRoot();
    const destination = await fixtureRoot();
    await mkdir(path.join(source, "nested"));
    await writeFile(path.join(source, "index.md"), "# Home\n", "utf8");
    await writeFile(path.join(source, "nested", "page.md"), "body\n", "utf8");
    const before = await snapshotMarkdownTree(source);

    const copied = await copyMarkdownTree(source, destination, before);

    expect(copied).toEqual(before);
    await expect(
      assertMarkdownTreeVersion(destination, before),
    ).resolves.toBeUndefined();
  });

  test("rejects non-Markdown files and drift from a captured version", async () => {
    const root = await fixtureRoot();
    await writeFile(path.join(root, "index.md"), "before\n", "utf8");
    const before = await snapshotMarkdownTree(root);
    await writeFile(path.join(root, "index.md"), "after\n", "utf8");

    await expect(assertMarkdownTreeVersion(root, before)).rejects.toEqual(
      expect.objectContaining({ code: "wiki_changed" }),
    );
    await writeFile(path.join(root, "state.json"), "{}\n", "utf8");
    await expect(snapshotMarkdownTree(root)).rejects.toEqual(
      expect.objectContaining({ code: "wiki_invalid" }),
    );
  });

  test.runIf(process.platform === "win32")(
    "rejects a Markdown file replaced by an external symlink after inspection",
    async () => {
      const root = await fixtureRoot();
      const outside = await fixtureRoot();
      const sourcePath = path.join(root, "index.md");
      const displacedPath = path.join(root, "index.displaced");
      const outsidePath = path.join(outside, "outside.md");
      await writeFile(sourcePath, "inside\n", "utf8");
      await writeFile(outsidePath, "outside\n", "utf8");
      const inspectedSourcePath = path.join(await realpath(root), "index.md");
      let swapped = false;
      let openedAfterSwap = false;
      const inspected: string[] = [];
      snapshotFsHook.afterLstat = async (target) => {
        inspected.push(target);
        if (!sameTestPath(target, inspectedSourcePath) || swapped) return;
        swapped = true;
        await rename(sourcePath, displacedPath);
        await symlink(outsidePath, sourcePath, "file");
      };
      snapshotFsHook.beforeOpen = async (target) => {
        if (sameTestPath(target, inspectedSourcePath) && swapped)
          openedAfterSwap = true;
      };

      const error = await snapshotMarkdownTree(root).then(
        () => undefined,
        (caught: unknown) => caught,
      );
      expect(inspected, inspected.join("|")).toContain(inspectedSourcePath);
      expect(error).toEqual(expect.objectContaining({ code: "wiki_invalid" }));
      expect(swapped).toBe(true);
      expect(openedAfterSwap).toBe(true);
      await expect(readFile(outsidePath, "utf8")).resolves.toBe("outside\n");
    },
  );

  test.runIf(process.platform === "win32")(
    "rejects an inspected ancestor replaced by an external junction",
    async () => {
      const root = await fixtureRoot();
      const outside = await fixtureRoot();
      const nested = path.join(root, "nested");
      const displaced = path.join(root, "nested.displaced");
      await mkdir(nested);
      await writeFile(path.join(nested, "page.md"), "inside\n", "utf8");
      await writeFile(path.join(outside, "page.md"), "outside\n", "utf8");
      const inspectedNested = path.join(await realpath(root), "nested");
      let swapped = false;
      snapshotFsHook.afterLstat = async (target) => {
        if (!sameTestPath(target, inspectedNested) || swapped) return;
        swapped = true;
        await rename(nested, displaced);
        await symlink(outside, nested, "junction");
      };

      await expect(snapshotMarkdownTree(root)).rejects.toEqual(
        expect.objectContaining({ code: "wiki_invalid" }),
      );
      expect(swapped).toBe(true);
      await expect(
        readFile(path.join(outside, "page.md"), "utf8"),
      ).resolves.toBe("outside\n");
    },
  );

  test.runIf(process.platform === "win32")(
    "does not copy a source replaced while preflight inspects it",
    async () => {
      const source = await fixtureRoot();
      const destination = await fixtureRoot();
      const outside = await fixtureRoot();
      const sourcePath = path.join(source, "a.md");
      const displacedPath = path.join(source, "a.displaced");
      const outsidePath = path.join(outside, "outside.md");
      await writeFile(sourcePath, "bound bytes\n", "utf8");
      await writeFile(path.join(source, "z.md"), "last\n", "utf8");
      await writeFile(outsidePath, "bound bytes\n", "utf8");
      const expected = await snapshotMarkdownTree(source);
      const inspectedSourcePath = path.join(await realpath(source), "a.md");
      let swapped = false;
      snapshotFsHook.afterLstat = async (target) => {
        if (!sameTestPath(target, inspectedSourcePath) || swapped) return;
        swapped = true;
        await rename(sourcePath, displacedPath);
        await symlink(outsidePath, sourcePath, "file");
      };

      await expect(
        copyMarkdownTree(source, destination, expected),
      ).rejects.toEqual(expect.objectContaining({ code: "wiki_changed" }));
      expect(swapped).toBe(true);
      await expect(snapshotMarkdownTree(destination)).resolves.toEqual(
        expect.objectContaining({ files: [] }),
      );
    },
  );
});

async function fixtureRoot(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-wiki-snapshot-"));
  tempDirs.push(root);
  return root;
}

function sameTestPath(left: string, right: string): boolean {
  const normalize = (value: string): string =>
    process.platform === "win32"
      ? path.normalize(value).toLowerCase()
      : path.normalize(value);
  return normalize(left) === normalize(right);
}
