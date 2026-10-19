import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import {
  access,
  link,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeAll, describe, expect, test, vi } from "vitest";
import {
  SourceManifestStore,
  type StableSourceCopier,
} from "../src/sources.js";
import { TrustedWin32SourceHelper } from "../src/win32-helper.js";

const tempDirs: string[] = [];
const packageRoot = path.resolve(import.meta.dirname, "../..");
const policyPath = path.join(packageRoot, "config", "sensitive-files.json");
const helperPath = path.join(
  packageRoot,
  "win32-helper",
  "dist",
  "SelfOpenWiki.Win32Helper.exe",
);
let helperHash: string;

beforeAll(async () => {
  helperHash = `sha256:${createHash("sha256")
    .update(await readFile(helperPath))
    .digest("hex")}`;
});

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe.runIf(process.platform === "win32")(
  "local source manifest preparation",
  () => {
    test("prepares exact supported files, honors .gitignore, and binds confirmation", async () => {
      const fixture = await createFixture();
      await writeFile(
        path.join(fixture.sourceDir, ".gitignore"),
        "ignored.cpp\n",
      );
      await writeFile(
        path.join(fixture.sourceDir, "main.cpp"),
        "int Main();\n",
      );
      await writeFile(path.join(fixture.sourceDir, "README.md"), "# Project\n");
      await writeFile(path.join(fixture.sourceDir, "ignored.cpp"), "ignored\n");
      await writeFile(
        path.join(fixture.sourceDir, "image.png"),
        Buffer.from([0, 1, 2]),
      );

      const prepared = await fixture.store.prepare([fixture.sourceDir]);

      expect(prepared.sourceManifestId).toBe(
        "source-11111111-1111-4111-8111-111111111111",
      );
      expect(prepared.confirmation).toBe(
        `confirm-source:${prepared.sourceManifestId}:${prepared.manifestHash}`,
      );
      expect(
        prepared.files.map((file) => path.basename(file.requestedPath)),
      ).toEqual([".gitignore", "main.cpp", "README.md"]);
      expect(
        prepared.files.every((file) => file.hash.startsWith("sha256:")),
      ).toBe(true);

      const snapshot = await fixture.store.verify({
        confirmation: prepared.confirmation,
        sourceManifestId: prepared.sourceManifestId,
      });
      expect(snapshot.manifestHash).toBe(prepared.manifestHash);
      await snapshot.cleanup();
    }, 15_000);

    test("ignores files added outside the confirmed set but invalidates changed files", async () => {
      const fixture = await createFixture();
      const sourcePath = path.join(fixture.sourceDir, "module.cpp");
      await writeFile(sourcePath, "int Value = 1;\n");
      const prepared = await fixture.store.prepare([sourcePath]);

      await writeFile(
        path.join(fixture.sourceDir, "new.cpp"),
        "int New = 1;\n",
      );
      const unchanged = await fixture.store.verify({
        confirmation: prepared.confirmation,
        sourceManifestId: prepared.sourceManifestId,
      });
      await unchanged.cleanup();

      await writeFile(sourcePath, "int Value = 2;\n");
      await expect(
        fixture.store.verify({
          confirmation: prepared.confirmation,
          sourceManifestId: prepared.sourceManifestId,
        }),
      ).rejects.toEqual(expect.objectContaining({ code: "source_changed" }));
    }, 15_000);

    test("hard-rejects sensitive paths before copy and removes sensitive quarantine", async () => {
      const fixture = await createFixture();
      const sensitivePath = path.join(fixture.sourceDir, ".env");
      await writeFile(sensitivePath, "TOKEN=secret\n");
      const copier = {
        inspectAndCopy: vi.fn(),
        inspectPath: vi.fn(),
        securePrivatePath: vi.fn().mockResolvedValue(undefined),
      };
      const pathStore = fixture.createStore(copier);

      await expect(pathStore.prepare([sensitivePath])).rejects.toEqual(
        expect.objectContaining({ code: "source_rejected" }),
      );
      expect(copier.inspectAndCopy).not.toHaveBeenCalled();

      const canary = `sk-${"A".repeat(32)}`;
      const contentPath = path.join(fixture.sourceDir, "notes.md");
      await writeFile(contentPath, `credential=${canary}\n`);
      let caught: unknown;
      try {
        await fixture.store.prepare([contentPath]);
      } catch (error) {
        caught = error;
      }
      expect(caught).toEqual(
        expect.objectContaining({ code: "source_rejected" }),
      );
      expect(JSON.stringify(caught)).not.toContain(canary);
      expect(await readAllText(fixture.runtimeDir)).not.toContain(canary);
    });

    test.each([
      ['{"refresh_token":"refresh-secret-value-123456"}', "refresh token JSON"],
      ['{"client_secret": "client-secret-value-123456"}', "client secret JSON"],
      ["aws_secret_access_key=aws-secret-value-123456", "AWS env assignment"],
      [`Authorization: Bearer ${"B".repeat(32)}`, "Authorization bearer token"],
      [
        `aws_access_key_id=ASIA${"A".repeat(16)}\naws_session_token=${"S".repeat(32)}`,
        "AWS temporary credentials",
      ],
    ])("hard-rejects %s credential content", async (content) => {
      const fixture = await createFixture();
      const sourcePath = path.join(fixture.sourceDir, "config.json");
      await writeFile(sourcePath, content, "utf8");

      await expect(fixture.store.prepare([sourcePath])).rejects.toEqual(
        expect.objectContaining({ code: "source_rejected" }),
      );
      expect(await readAllText(fixture.runtimeDir)).not.toContain(content);
    });

    test("requires trusted helper preflight before filesystem enumeration", async () => {
      const fixture = await createFixture();
      await writeFile(
        path.join(fixture.sourceDir, "main.cpp"),
        "int Main();\n",
      );
      const inspectPath = vi.fn().mockRejectedValue(
        Object.assign(new Error("unsupported"), {
          code: "platform_unsupported",
        }),
      );
      const copier: StableSourceCopier = {
        inspectAndCopy: vi.fn(),
        inspectPath,
        securePrivatePath: vi.fn().mockResolvedValue(undefined),
      };

      await expect(
        fixture.createStore(copier).prepare([fixture.sourceDir]),
      ).rejects.toEqual(
        expect.objectContaining({ code: "platform_unsupported" }),
      );
      expect(inspectPath).toHaveBeenCalledWith({
        sourcePath: fixture.sourceDir,
      });
      expect(copier.inspectAndCopy).not.toHaveBeenCalled();
    });

    test("rejects duplicate inputs and hard-link aliases by file identity", async () => {
      const fixture = await createFixture();
      const firstPath = path.join(fixture.sourceDir, "first.cpp");
      const aliasPath = path.join(fixture.sourceDir, "alias.cpp");
      await writeFile(firstPath, "int Value;\n", "utf8");

      await expect(
        fixture.store.prepare([firstPath, firstPath]),
      ).rejects.toEqual(expect.objectContaining({ code: "source_rejected" }));
      await link(firstPath, aliasPath);
      await expect(
        fixture.store.prepare([firstPath, aliasPath]),
      ).rejects.toEqual(expect.objectContaining({ code: "source_rejected" }));
    });

    test("rejects NUL text and enforces actual copied total bytes", async () => {
      const fixture = await createFixture({ maxTotalBytes: 8 });
      const nulPath = path.join(fixture.sourceDir, "nul.txt");
      await writeFile(nulPath, Buffer.from([0x61, 0x00, 0x62]));
      await expect(fixture.store.prepare([nulPath])).rejects.toEqual(
        expect.objectContaining({ code: "source_rejected" }),
      );
      const controlPath = path.join(fixture.sourceDir, "controls.txt");
      await writeFile(controlPath, Buffer.from([0x01, 0x02, 0x03, 0x0a]));
      await expect(fixture.store.prepare([controlPath])).rejects.toEqual(
        expect.objectContaining({ code: "source_rejected" }),
      );

      const firstPath = path.join(fixture.sourceDir, "a.txt");
      const secondPath = path.join(fixture.sourceDir, "b.txt");
      await writeFile(firstPath, "a", "utf8");
      await writeFile(secondPath, "b", "utf8");
      const copier: StableSourceCopier = {
        inspectPath: vi.fn(async ({ sourcePath }) => ({
          canonicalPath: sourcePath,
          directory: sourcePath === fixture.sourceDir,
          fileIndex: sourcePath.endsWith("a.txt")
            ? "0000000000000001"
            : sourcePath.endsWith("b.txt")
              ? "0000000000000002"
              : "0000000000000009",
          lastWriteFileTime: "1",
          ok: true as const,
          reparseTagChecked: true as const,
          size: 1,
          version: 1 as const,
          volumeSerial: 1,
        })),
        inspectAndCopy: vi.fn(async ({ destinationPath, sourcePath }) => {
          const bytes = Buffer.from("123456", "utf8");
          await writeFile(destinationPath, bytes);
          return {
            canonicalPath: sourcePath,
            fileIndex: sourcePath.endsWith("a.txt")
              ? "0000000000000001"
              : "0000000000000002",
            hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
            lastWriteFileTime: "1",
            ok: true as const,
            reparseTagChecked: true as const,
            size: bytes.length,
            version: 1 as const,
            volumeSerial: 1,
          };
        }),
        securePrivatePath: vi.fn().mockResolvedValue(undefined),
      };
      await expect(
        fixture.createStore(copier).prepare([firstPath, secondPath]),
      ).rejects.toEqual(expect.objectContaining({ code: "source_too_large" }));
    });

    test("marks explicitly selected ignored files and retries snapshot cleanup", async () => {
      const fixture = await createFixture();
      const sourcePath = path.join(fixture.sourceDir, "ignored.cpp");
      await writeFile(
        path.join(fixture.sourceDir, ".gitignore"),
        "ignored.cpp\n",
      );
      await writeFile(sourcePath, "int Ignored;\n");
      const prepared = await fixture.store.prepare([sourcePath]);
      expect(prepared.files[0]?.risks).toContain("explicitly_ignored");

      const snapshot = await fixture.store.verify({
        confirmation: prepared.confirmation,
        sourceManifestId: prepared.sourceManifestId,
      });
      expect(snapshot).toEqual(
        expect.objectContaining({
          snapshotTreeHash: expect.stringMatching(/^sha256:[a-f0-9]{64}$/u),
        }),
      );
      const child = spawn(
        process.execPath,
        [
          "-e",
          "process.stdout.write('ready'); setTimeout(() => process.exit(0), 200)",
        ],
        {
          cwd: snapshot.snapshotPath,
          stdio: ["ignore", "pipe", "ignore"],
          windowsHide: true,
        },
      );
      await new Promise<void>((resolve, reject) => {
        child.once("error", reject);
        child.stdout.once("data", () => resolve());
      });
      await expect(snapshot.cleanup()).resolves.toBeUndefined();
      await expect(access(snapshot.snapshotPath)).rejects.toBeDefined();
    });

    test("marks a file ignored by an ancestor repository .gitignore", async () => {
      const fixture = await createFixture();
      const nested = path.join(fixture.sourceDir, "sub");
      const sourcePath = path.join(nested, "sample.txt");
      await mkdir(nested);
      await writeFile(
        path.join(fixture.sourceDir, ".gitignore"),
        "sub/sample.txt\n",
      );
      await writeFile(sourcePath, "safe text\n", "utf8");

      const prepared = await fixture.store.prepare([sourcePath]);

      expect(prepared.files[0]?.risks).toContain("explicitly_ignored");
    });

    test("clearly rejects unsupported binary files and selection limits", async () => {
      const fixture = await createFixture({ maxFileBytes: 4 });
      const pdfPath = path.join(fixture.sourceDir, "manual.pdf");
      await writeFile(pdfPath, "%PDF-1.7");
      await expect(fixture.store.prepare([pdfPath])).rejects.toEqual(
        expect.objectContaining({ code: "source_rejected" }),
      );

      const textPath = path.join(fixture.sourceDir, "large.md");
      await writeFile(textPath, "12345");
      await expect(fixture.store.prepare([textPath])).rejects.toEqual(
        expect.objectContaining({ code: "source_too_large" }),
      );
    });

    test("rejects a wrong confirmation before recopying content", async () => {
      const fixture = await createFixture();
      const sourcePath = path.join(fixture.sourceDir, "main.cpp");
      await writeFile(sourcePath, "int Main();\n");
      const prepared = await fixture.store.prepare([sourcePath]);
      const copier = {
        inspectAndCopy: vi.fn(),
        inspectPath: vi.fn(),
        securePrivatePath: vi.fn().mockResolvedValue(undefined),
      };
      const verifier = fixture.createStore(copier);

      await expect(
        verifier.verify({
          confirmation: "confirm-source:wrong",
          sourceManifestId: prepared.sourceManifestId,
        }),
      ).rejects.toEqual(
        expect.objectContaining({ code: "source_manifest_invalid" }),
      );
      expect(copier.inspectAndCopy).not.toHaveBeenCalled();
    });

    test("never overwrites an existing manifest id", async () => {
      const fixture = await createFixture();
      const sourcePath = path.join(fixture.sourceDir, "main.cpp");
      await writeFile(sourcePath, "int Main();\n");
      const first = await fixture.store.prepare([sourcePath]);

      await expect(fixture.store.prepare([sourcePath])).rejects.toEqual(
        expect.objectContaining({ code: "internal_error" }),
      );
      const snapshot = await fixture.store.verify({
        confirmation: first.confirmation,
        sourceManifestId: first.sourceManifestId,
      });
      await snapshot.cleanup();
    }, 15_000);
  },
);

async function createFixture(
  limits: { maxFileBytes?: number; maxTotalBytes?: number } = {},
) {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-sources-"));
  tempDirs.push(root);
  const runtimeDir = path.join(root, "runtime");
  const sourceDir = path.join(root, "project");
  await Promise.all([
    mkdir(runtimeDir, { recursive: true }),
    mkdir(sourceDir, { recursive: true }),
  ]);
  await mkdir(path.join(sourceDir, ".git"));
  const defaultCopier = new TrustedWin32SourceHelper({
    executablePath: helperPath,
    expectedHash: helperHash,
  });
  const createStore = (copier: StableSourceCopier = defaultCopier) =>
    new SourceManifestStore({
      copier,
      createId: () => "source-11111111-1111-4111-8111-111111111111",
      limits,
      policyPath,
      runtimeDir,
    });
  return {
    createStore,
    runtimeDir,
    sourceDir,
    store: createStore(),
  };
}

async function readAllText(directory: string): Promise<string> {
  let result = "";
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) result += await readAllText(entryPath);
    else if (entry.isFile()) result += await readFile(entryPath, "utf8");
  }
  return result;
}
