import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  rename,
  realpath,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeAll, describe, expect, test } from "vitest";
import { TrustedWin32SourceHelper } from "../src/win32-helper.js";

const tempDirs: string[] = [];
const helperPath = path.resolve(
  import.meta.dirname,
  "../../win32-helper/dist/SelfOpenWiki.Win32Helper.exe",
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
  "trusted Win32 stable copy",
  () => {
    test("copies exact bytes and returns handle identity evidence", async () => {
      const root = await createTempDir();
      const sourcePath = path.join(root, "source.cpp");
      const destinationPath = path.join(root, "copy.cpp");
      const bytes = Buffer.from("int main() { return 0; }\r\n", "utf8");
      await writeFile(sourcePath, bytes);

      const result = await helper().inspectAndCopy({
        destinationPath,
        maxBytes: 1024,
        sourcePath,
      });

      expect(await readFile(destinationPath)).toEqual(bytes);
      expect(result).toEqual(
        expect.objectContaining({
          canonicalPath: await realpath(sourcePath),
          fileIndex: expect.stringMatching(/^[a-f0-9]{16}$/u),
          hash: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
          reparseTagChecked: true,
          size: bytes.byteLength,
          volumeSerial: expect.any(Number),
        }),
      );
    });

    test("preflights files and directories with handle-bound reparse evidence", async () => {
      const root = await createTempDir();
      const sourcePath = path.join(root, "source.cpp");
      await writeFile(sourcePath, "int Value;\n", "utf8");

      const directory = await helper().inspectPath({ sourcePath: root });
      const file = await helper().inspectPath({ sourcePath });

      expect(directory).toEqual(
        expect.objectContaining({
          directory: true,
          reparseTagChecked: true,
        }),
      );
      expect(file).toEqual(
        expect.objectContaining({
          directory: false,
          reparseTagChecked: true,
        }),
      );

      const rootRelative = sourcePath.slice(2);
      expect(rootRelative.startsWith("\\")).toBe(true);
      await expect(
        helper().inspectPath({ sourcePath: rootRelative }),
      ).rejects.toEqual(expect.objectContaining({ code: "source_rejected" }));
    });

    test("rejects byte limits, untrusted helper hashes, and reparse ancestors", async () => {
      const root = await createTempDir();
      const outside = await createTempDir();
      const sourcePath = path.join(outside, "source.md");
      await writeFile(sourcePath, "source bytes\n", "utf8");
      const linked = path.join(root, "linked");
      await symlink(outside, linked, "junction");

      await expect(
        helper().inspectAndCopy({
          destinationPath: path.join(root, "too-large.md"),
          maxBytes: 1,
          sourcePath,
        }),
      ).rejects.toEqual(expect.objectContaining({ code: "source_too_large" }));
      await expect(
        helper().inspectAndCopy({
          destinationPath: path.join(root, "linked-copy.md"),
          maxBytes: 1024,
          sourcePath: path.join(linked, "source.md"),
        }),
      ).rejects.toEqual(expect.objectContaining({ code: "source_rejected" }));
      await expect(
        new TrustedWin32SourceHelper({
          executablePath: helperPath,
          expectedHash: `sha256:${"0".repeat(64)}`,
        }).inspectAndCopy({
          destinationPath: path.join(root, "untrusted.md"),
          maxBytes: 1024,
          sourcePath,
        }),
      ).rejects.toEqual(expect.objectContaining({ code: "helper_untrusted" }));
    });

    test.each(["opened", "copying"])(
      "detects path replacement at the %s stable-handle barrier",
      async (stage) => {
        const root = await createTempDir();
        const sourcePath = path.join(root, "source.cpp");
        const oldPath = path.join(root, "old.cpp");
        const destinationPath = path.join(root, "copy.cpp");
        await writeFile(sourcePath, Buffer.alloc(256 * 1024, 0x41));
        const child = spawn(helperPath, [], {
          env: {
            SystemRoot: process.env.SystemRoot,
            WINDIR: process.env.WINDIR,
            KG_C7_TEST_BARRIER_DIR: root,
            KG_C7_TEST_BARRIER_STAGE: stage,
          },
          stdio: ["pipe", "pipe", "pipe"],
          windowsHide: true,
        });
        let stdout = "";
        let stderr = "";
        child.stdout
          .setEncoding("utf8")
          .on("data", (chunk) => (stdout += chunk));
        child.stderr
          .setEncoding("utf8")
          .on("data", (chunk) => (stderr += chunk));
        child.stdin.end(
          JSON.stringify({
            destinationPath,
            maxBytes: 1024 * 1024,
            operation: "inspect-copy",
            sourcePath,
            version: 1,
          }),
        );

        await waitForPath(path.join(root, `${stage}.ready`));
        await rename(sourcePath, oldPath);
        await writeFile(sourcePath, "replacement\n", "utf8");
        await writeFile(path.join(root, `${stage}.continue`), "continue\n");
        const exitCode = await new Promise<number | null>((resolve, reject) => {
          child.once("error", reject);
          child.once("exit", resolve);
        });

        expect(exitCode).toBe(3);
        expect(stderr).toBe("");
        expect(JSON.parse(stdout)).toEqual({
          code: "source_changed",
          ok: false,
          version: 1,
        });
        await expect(access(destinationPath)).rejects.toBeDefined();
      },
    );

    test("sets and verifies protected current-user plus SYSTEM ACLs", async () => {
      const root = await createTempDir();
      const privateDirectory = path.join(root, "private");
      await mkdir(privateDirectory);
      const privateFile = path.join(privateDirectory, "state.json");
      await writeFile(privateFile, "{}\n", "utf8");

      const directoryResult = await helper().securePrivatePath({
        directory: true,
        targetPath: privateDirectory,
      });
      const fileResult = await helper().securePrivatePath({
        directory: false,
        targetPath: privateFile,
      });

      for (const result of [directoryResult, fileResult]) {
        expect(result.daclProtected).toBe(true);
        expect(result.ownerSid).toMatch(/^S-1-/u);
        expect(result.explicitFullControlSids).toEqual(
          expect.arrayContaining([result.ownerSid, "S-1-5-18"]),
        );
      }
    });
  },
);

function helper(): TrustedWin32SourceHelper {
  return new TrustedWin32SourceHelper({
    executablePath: helperPath,
    expectedHash: helperHash,
  });
}

async function createTempDir(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "c7-win32-helper-"));
  tempDirs.push(root);
  await mkdir(root, { recursive: true });
  return root;
}

async function waitForPath(filePath: string): Promise<void> {
  const deadline = Date.now() + 5_000;
  for (;;) {
    try {
      await access(filePath);
      return;
    } catch {
      if (Date.now() >= deadline) throw new Error("barrier timed out");
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }
}
