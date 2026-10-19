import { constants } from "node:fs";
import {
  lstat as nodeLstat,
  open as nodeOpen,
  type FileHandle,
} from "node:fs/promises";
import path from "node:path";

type StatLike = {
  dev: bigint | number;
  ino: bigint | number;
  isDirectory(): boolean;
  isFile(): boolean;
  isSymbolicLink(): boolean;
  mode: number;
  uid: number;
};

type PosixHandle = {
  chmod(mode: number): Promise<void>;
  close(): Promise<void>;
  stat(): Promise<StatLike>;
};

type PosixOperations = {
  getuid(): number;
  lstat(targetPath: string): Promise<StatLike>;
  open(targetPath: string, flags: number): Promise<PosixHandle>;
};

type Win32PrivatePathHelper = {
  securePrivatePath(input: {
    directory: boolean;
    targetPath: string;
  }): Promise<unknown>;
};

export class PrivatePathPermissionError extends Error {
  constructor(
    readonly code: "permission_failed" | "platform_unsupported",
    message: string,
  ) {
    super(message);
    this.name = "PrivatePathPermissionError";
  }
}

export class VerifiedPrivatePathSecurity {
  private readonly platform: string;
  private readonly posix: PosixOperations | undefined;
  private readonly win32Helper: Win32PrivatePathHelper | undefined;

  constructor(options: {
    platform?: string;
    posix?: PosixOperations;
    win32Helper?: Win32PrivatePathHelper;
  }) {
    this.platform = options.platform ?? process.platform;
    this.posix =
      options.posix ??
      (this.platform === "linux" || this.platform === "darwin"
        ? createNodePosixOperations()
        : undefined);
    this.win32Helper = options.win32Helper;
  }

  async securePrivatePath(input: {
    directory: boolean;
    targetPath: string;
  }): Promise<void> {
    if (!path.isAbsolute(input.targetPath)) {
      throw permissionFailure();
    }
    if (this.platform === "win32") {
      if (this.win32Helper === undefined) throw unsupportedPlatform();
      try {
        const result = await this.win32Helper.securePrivatePath(input);
        if (!isVerifiedWin32Result(result)) throw permissionFailure();
        return;
      } catch (error) {
        if (error instanceof PrivatePathPermissionError) throw error;
        throw permissionFailure();
      }
    }
    if (this.platform !== "linux" && this.platform !== "darwin") {
      throw unsupportedPlatform();
    }
    if (this.posix === undefined) throw unsupportedPlatform();
    await securePosixPath(input, this.posix);
  }
}

async function securePosixPath(
  input: { directory: boolean; targetPath: string },
  operations: PosixOperations,
): Promise<void> {
  const expectedMode = input.directory ? 0o700 : 0o600;
  const expectedUid = operations.getuid();
  let handle: PosixHandle | undefined;
  try {
    const before = await operations.lstat(input.targetPath);
    assertExpectedObject(before, input.directory, expectedUid);
    const flags =
      constants.O_RDONLY |
      constants.O_NOFOLLOW |
      (input.directory ? constants.O_DIRECTORY : 0);
    handle = await operations.open(input.targetPath, flags);
    const opened = await handle.stat();
    assertExpectedObject(opened, input.directory, expectedUid);
    assertSameIdentity(before, opened);
    await handle.chmod(expectedMode);
    const secured = await handle.stat();
    assertExpectedObject(secured, input.directory, expectedUid);
    assertSameIdentity(opened, secured);
    if ((secured.mode & 0o777) !== expectedMode) throw permissionFailure();
    const finalPath = await operations.lstat(input.targetPath);
    assertExpectedObject(finalPath, input.directory, expectedUid);
    assertSameIdentity(secured, finalPath);
    if ((finalPath.mode & 0o777) !== expectedMode) throw permissionFailure();
  } catch (error) {
    if (error instanceof PrivatePathPermissionError) throw error;
    throw permissionFailure();
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

function assertExpectedObject(
  stat: StatLike,
  directory: boolean,
  expectedUid: number,
): void {
  if (
    stat.isSymbolicLink() ||
    stat.uid !== expectedUid ||
    (directory ? !stat.isDirectory() : !stat.isFile())
  ) {
    throw permissionFailure();
  }
}

function assertSameIdentity(left: StatLike, right: StatLike): void {
  if (
    String(left.dev) !== String(right.dev) ||
    String(left.ino) !== String(right.ino)
  ) {
    throw permissionFailure();
  }
}

function isVerifiedWin32Result(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  const result = value as Record<string, unknown>;
  if (
    result.ok !== true ||
    result.version !== 1 ||
    result.daclProtected !== true ||
    typeof result.ownerSid !== "string" ||
    !/^S-1-/u.test(result.ownerSid) ||
    !Array.isArray(result.explicitFullControlSids) ||
    result.explicitFullControlSids.length !== 2 ||
    !result.explicitFullControlSids.includes(result.ownerSid) ||
    !result.explicitFullControlSids.includes("S-1-5-18")
  ) {
    return false;
  }
  return true;
}

function createNodePosixOperations(): PosixOperations {
  if (process.getuid === undefined) throw unsupportedPlatform();
  return {
    getuid: () => process.getuid!(),
    lstat: (targetPath) => nodeLstat(targetPath),
    open: async (targetPath, flags) =>
      (await nodeOpen(targetPath, flags)) as FileHandle & PosixHandle,
  };
}

function permissionFailure(): PrivatePathPermissionError {
  return new PrivatePathPermissionError(
    "permission_failed",
    "The private runtime path permissions could not be applied and verified.",
  );
}

function unsupportedPlatform(): PrivatePathPermissionError {
  return new PrivatePathPermissionError(
    "platform_unsupported",
    "Private runtime path verification is unavailable on this platform.",
  );
}
