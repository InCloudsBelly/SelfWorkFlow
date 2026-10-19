import { spawn, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

const hashSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/u);
const helperSuccessSchema = z.strictObject({
  canonicalPath: z.string().min(3).max(32_768),
  fileIndex: z.string().regex(/^[a-f0-9]{16}$/u),
  hash: hashSchema,
  lastWriteFileTime: z.string().regex(/^\d+$/u),
  ok: z.literal(true),
  reparseTagChecked: z.literal(true),
  size: z.number().int().nonnegative(),
  version: z.literal(1),
  volumeSerial: z.number().int().nonnegative(),
});
const pathInspectionSuccessSchema = z.strictObject({
  canonicalPath: z.string().min(3).max(32_768),
  directory: z.boolean(),
  fileIndex: z.string().regex(/^[a-f0-9]{16}$/u),
  lastWriteFileTime: z.string().regex(/^\d+$/u),
  ok: z.literal(true),
  reparseTagChecked: z.literal(true),
  size: z.number().int().nonnegative(),
  version: z.literal(1),
  volumeSerial: z.number().int().nonnegative(),
});
const helperFailureSchema = z.strictObject({
  code: z.enum([
    "platform_unsupported",
    "invalid_request",
    "source_changed",
    "source_rejected",
    "source_too_large",
    "helper_failure",
  ]),
  ok: z.literal(false),
  version: z.literal(1),
});
const securePathSuccessSchema = z.strictObject({
  daclProtected: z.literal(true),
  explicitFullControlSids: z.array(z.string().regex(/^S-1-/u)).length(2),
  ok: z.literal(true),
  ownerSid: z.string().regex(/^S-1-/u),
  version: z.literal(1),
});
const helperResultSchema = z.union([
  helperSuccessSchema,
  pathInspectionSuccessSchema,
  securePathSuccessSchema,
  helperFailureSchema,
]);

export type StableCopyResult = z.infer<typeof helperSuccessSchema>;
export type StablePathInspection = z.infer<typeof pathInspectionSuccessSchema>;

export class Win32SourceHelperError extends Error {
  constructor(
    readonly code:
      | "platform_unsupported"
      | "helper_untrusted"
      | "source_changed"
      | "source_rejected"
      | "source_too_large"
      | "helper_failure",
    message: string,
  ) {
    super(message);
    this.name = "Win32SourceHelperError";
  }
}

export class TrustedWin32SourceHelper {
  private readonly executablePath: string;
  private readonly expectedHash: string;
  private readonly timeoutMs: number;

  constructor(options: {
    executablePath: string;
    expectedHash: string;
    timeoutMs?: number;
  }) {
    if (!path.isAbsolute(options.executablePath)) {
      throw new Win32SourceHelperError(
        "helper_untrusted",
        "The Win32 source helper path must be absolute.",
      );
    }
    if (!hashSchema.safeParse(options.expectedHash).success) {
      throw new Win32SourceHelperError(
        "helper_untrusted",
        "The Win32 source helper hash is invalid.",
      );
    }
    this.executablePath = options.executablePath;
    this.expectedHash = options.expectedHash;
    this.timeoutMs = options.timeoutMs ?? 30_000;
  }

  async inspectAndCopy(input: {
    destinationPath: string;
    maxBytes: number;
    sourcePath: string;
  }): Promise<StableCopyResult> {
    if (process.platform !== "win32") {
      throw new Win32SourceHelperError(
        "platform_unsupported",
        "Local source preparation is not verified on this platform.",
      );
    }
    await this.verifyExecutable();
    const request = `${JSON.stringify({
      destinationPath: input.destinationPath,
      maxBytes: input.maxBytes,
      operation: "inspect-copy",
      sourcePath: input.sourcePath,
      version: 1,
    })}\n`;
    const result = await runHelper(
      this.executablePath,
      request,
      this.timeoutMs,
    );
    if (!result.ok) {
      const code =
        result.code === "invalid_request" ? "helper_failure" : result.code;
      throw new Win32SourceHelperError(
        code,
        code === "source_too_large"
          ? "The source file exceeds the configured byte limit."
          : code === "source_changed"
            ? "The source changed while it was being copied."
            : code === "source_rejected"
              ? "The source path is not an allowed fixed local file."
              : "The trusted Win32 source helper failed.",
      );
    }
    if (!("hash" in result)) {
      throw new Win32SourceHelperError(
        "helper_failure",
        "The trusted Win32 source helper returned the wrong result type.",
      );
    }
    return result;
  }

  async inspectPath(input: {
    sourcePath: string;
  }): Promise<StablePathInspection> {
    if (process.platform !== "win32") {
      throw new Win32SourceHelperError(
        "platform_unsupported",
        "Local source preparation is not verified on this platform.",
      );
    }
    await this.verifyExecutable();
    const result = await runHelper(
      this.executablePath,
      `${JSON.stringify({
        operation: "inspect-path",
        sourcePath: input.sourcePath,
        version: 1,
      })}\n`,
      this.timeoutMs,
    );
    if (!result.ok) {
      const code =
        result.code === "platform_unsupported"
          ? "platform_unsupported"
          : result.code === "source_changed"
            ? "source_changed"
            : "source_rejected";
      throw new Win32SourceHelperError(
        code,
        code === "platform_unsupported"
          ? "Local source preparation is not verified on this platform."
          : code === "source_changed"
            ? "The source path changed during trusted preflight."
            : "The source path failed trusted fixed-drive preflight.",
      );
    }
    if (!("directory" in result)) {
      throw new Win32SourceHelperError(
        "helper_failure",
        "The trusted Win32 source helper returned the wrong result type.",
      );
    }
    return result;
  }

  async securePrivatePath(input: {
    directory: boolean;
    targetPath: string;
  }): Promise<z.infer<typeof securePathSuccessSchema>> {
    if (process.platform !== "win32") {
      throw new Win32SourceHelperError(
        "platform_unsupported",
        "Private runtime paths are not verified on this platform.",
      );
    }
    await this.verifyExecutable();
    const result = await runHelper(
      this.executablePath,
      `${JSON.stringify({
        directory: input.directory,
        operation: "secure-path",
        targetPath: input.targetPath,
        version: 1,
      })}\n`,
      this.timeoutMs,
    );
    if (!result.ok) {
      throw new Win32SourceHelperError(
        result.code === "platform_unsupported"
          ? "platform_unsupported"
          : "helper_failure",
        "The trusted Win32 helper could not secure a private runtime path.",
      );
    }
    if (!("ownerSid" in result)) {
      throw new Win32SourceHelperError(
        "helper_failure",
        "The trusted Win32 source helper returned the wrong result type.",
      );
    }
    return result;
  }

  private async verifyExecutable(): Promise<void> {
    let stat;
    let bytes: Buffer;
    try {
      stat = await lstat(this.executablePath);
      bytes = await readFile(this.executablePath);
    } catch {
      throw new Win32SourceHelperError(
        "helper_untrusted",
        "The trusted Win32 source helper is missing.",
      );
    }
    if (!stat.isFile() || stat.isSymbolicLink()) {
      throw new Win32SourceHelperError(
        "helper_untrusted",
        "The Win32 source helper must be a regular non-link file.",
      );
    }
    const actual = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
    if (actual !== this.expectedHash) {
      throw new Win32SourceHelperError(
        "helper_untrusted",
        "The Win32 source helper does not match verified capability evidence.",
      );
    }
  }
}

async function runHelper(
  executablePath: string,
  request: string,
  timeoutMs: number,
): Promise<z.infer<typeof helperResultSchema>> {
  const child = spawn(executablePath, [], {
    detached: false,
    env: createHelperEnvironment(),
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  const stdout: Buffer[] = [];
  let stdoutBytes = 0;
  let stderrBytes = 0;
  child.stdout.on("data", (chunk: Buffer) => {
    stdoutBytes += chunk.byteLength;
    if (stdoutBytes <= 64 * 1024) stdout.push(chunk);
  });
  child.stderr.on("data", (chunk: Buffer) => {
    stderrBytes += chunk.byteLength;
  });
  child.stdin.end(request, "utf8");

  const exitCode = await waitForHelper(child, timeoutMs);
  if (exitCode === null || stdoutBytes > 64 * 1024 || stderrBytes !== 0) {
    throw new Win32SourceHelperError(
      "helper_failure",
      "The trusted Win32 source helper process failed.",
    );
  }
  let value: unknown;
  try {
    value = JSON.parse(Buffer.concat(stdout).toString("utf8"));
  } catch {
    throw new Win32SourceHelperError(
      "helper_failure",
      "The trusted Win32 source helper returned invalid output.",
    );
  }
  const parsed = helperResultSchema.safeParse(value);
  if (!parsed.success) {
    throw new Win32SourceHelperError(
      "helper_failure",
      "The trusted Win32 source helper returned invalid output.",
    );
  }
  return parsed.data;
}

function waitForHelper(
  child: ChildProcess,
  timeoutMs: number,
): Promise<number | null> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      child.kill();
      resolve(null);
    }, timeoutMs);
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(
        new Win32SourceHelperError(
          "helper_failure",
          `The trusted Win32 source helper could not start: ${error.name}`,
        ),
      );
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      resolve(code);
    });
  });
}

function createHelperEnvironment(): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const key of ["SystemRoot", "WINDIR", "TEMP", "TMP"] as const) {
    const value = process.env[key];
    if (value !== undefined) environment[key] = value;
  }
  return environment;
}
