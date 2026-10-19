import { constants } from "node:fs";
import { describe, expect, test, vi } from "vitest";
import { VerifiedPrivatePathSecurity } from "../src/permissions.js";

describe("verified private runtime path permissions", () => {
  test("delegates Windows ACL application and verification to the trusted helper", async () => {
    const securePrivatePath = vi.fn().mockResolvedValue({
      daclProtected: true,
      explicitFullControlSids: ["S-1-5-21-1", "S-1-5-18"],
      ok: true,
      ownerSid: "S-1-5-21-1",
      version: 1,
    });
    const security = new VerifiedPrivatePathSecurity({
      platform: "win32",
      win32Helper: { securePrivatePath },
    });

    await security.securePrivatePath({
      directory: true,
      targetPath: "D:\\runtime\\private",
    });

    expect(securePrivatePath).toHaveBeenCalledWith({
      directory: true,
      targetPath: "D:\\runtime\\private",
    });
  });

  test.each([
    [true, 0o700, constants.O_DIRECTORY],
    [false, 0o600, 0],
  ] as const)(
    "uses a no-follow handle and verifies POSIX identity, owner, and mode for directory=%s",
    async (directory, expectedMode, typeFlag) => {
      const before = posixStat({ directory, mode: directory ? 0o755 : 0o644 });
      const secured = posixStat({ directory, mode: expectedMode });
      const chmod = vi.fn().mockResolvedValue(undefined);
      const close = vi.fn().mockResolvedValue(undefined);
      const stat = vi
        .fn()
        .mockResolvedValueOnce(before)
        .mockResolvedValueOnce(secured);
      const lstat = vi
        .fn()
        .mockResolvedValueOnce(before)
        .mockResolvedValueOnce(secured);
      const open = vi.fn().mockResolvedValue({ chmod, close, stat });
      const security = new VerifiedPrivatePathSecurity({
        platform: "linux",
        posix: { getuid: () => 1000, lstat, open },
      });

      await security.securePrivatePath({
        directory,
        targetPath: "/runtime/private",
      });

      expect(open).toHaveBeenCalledWith(
        "/runtime/private",
        constants.O_RDONLY | constants.O_NOFOLLOW | typeFlag,
      );
      expect(chmod).toHaveBeenCalledWith(expectedMode);
      expect(close).toHaveBeenCalledTimes(1);
    },
  );

  test("fails closed when the path identity changes after securing", async () => {
    const before = posixStat({ directory: false, ino: 41, mode: 0o644 });
    const secured = posixStat({ directory: false, ino: 41, mode: 0o600 });
    const replaced = posixStat({ directory: false, ino: 42, mode: 0o600 });
    const security = new VerifiedPrivatePathSecurity({
      platform: "linux",
      posix: {
        getuid: () => 1000,
        lstat: vi
          .fn()
          .mockResolvedValueOnce(before)
          .mockResolvedValueOnce(replaced),
        open: vi.fn().mockResolvedValue({
          chmod: vi.fn().mockResolvedValue(undefined),
          close: vi.fn().mockResolvedValue(undefined),
          stat: vi
            .fn()
            .mockResolvedValueOnce(before)
            .mockResolvedValueOnce(secured),
        }),
      },
    });

    await expect(
      security.securePrivatePath({
        directory: false,
        targetPath: "/runtime/private",
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "permission_failed" }));
  });

  test("rejects unsupported platforms instead of claiming private-path verification", async () => {
    const security = new VerifiedPrivatePathSecurity({
      platform: "aix",
    });

    await expect(
      security.securePrivatePath({
        directory: true,
        targetPath: "/runtime/private",
      }),
    ).rejects.toEqual(
      expect.objectContaining({ code: "platform_unsupported" }),
    );
  });
});

function posixStat(options: {
  directory: boolean;
  ino?: number;
  mode: number;
}) {
  return {
    dev: 7,
    ino: options.ino ?? 41,
    isDirectory: () => options.directory,
    isFile: () => !options.directory,
    isSymbolicLink: () => false,
    mode: options.mode,
    uid: 1000,
  };
}
