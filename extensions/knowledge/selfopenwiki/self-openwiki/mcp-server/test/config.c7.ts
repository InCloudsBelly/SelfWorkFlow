import {
  mkdir,
  mkdtemp,
  lstat,
  readFile,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { afterEach, describe, expect, test } from "vitest";
import {
  C7ConfigError,
  C7_LOCK_ORDER,
  loadDefaults,
  readRuntimeConfig,
  recoverStaleC7Locks,
  resolveModelSelection,
  runtimeConfigSchema,
  withC7Locks,
  writeRuntimeConfigAtomic,
} from "../src/config.js";

const tempDirs: string[] = [];
const defaultModel = {
  model: "gpt-5.6-sol",
  reasoningEffort: "xhigh" as const,
};

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("versioned C7 configuration", () => {
  test("loads repository defaults as a recommendation, not initialization", async () => {
    const defaultsPath = path.resolve(
      import.meta.dirname,
      "../../config/defaults.json",
    );

    await expect(loadDefaults(defaultsPath)).resolves.toEqual({
      schemaVersion: 1,
      provider: "openai-chatgpt",
      recommendedModel: defaultModel,
    });
    const text = await readFile(defaultsPath, "utf8");
    expect(text).not.toContain('"initialized": true');
  });

  test("strictly parses initialized runtime config and rejects unknown fields", () => {
    const config = createRuntimeConfig();
    expect(runtimeConfigSchema.safeParse(config).success).toBe(true);
    expect(
      runtimeConfigSchema.safeParse({ ...config, invented: true }).success,
    ).toBe(false);
    expect(
      runtimeConfigSchema.safeParse({ ...config, schemaVersion: 2 }).success,
    ).toBe(false);
    expect(
      runtimeConfigSchema.safeParse({ ...config, initialized: false }).success,
    ).toBe(false);
    expect(
      runtimeConfigSchema.safeParse({
        ...config,
        defaultModel: {
          model: "gpt-5.6-terra",
          reasoningEffort: "high",
        },
      }).success,
    ).toBe(false);
    expect(
      runtimeConfigSchema.safeParse({
        ...config,
        verifiedModels: [
          ...(config.verifiedModels as unknown[]),
          ...(config.verifiedModels as unknown[]),
        ],
      }).success,
    ).toBe(false);
  });

  test("uses one-shot override before runtime default without writing config", async () => {
    const fixture = await createConfigFixture();
    const first = await writeRuntimeConfigAtomic(
      fixture.configPath,
      createRuntimeConfig(),
      "missing",
    );
    const override = { model: "gpt-5.6-terra", reasoningEffort: "high" };

    expect(resolveModelSelection(first.config, override)).toEqual({
      selection: override,
      source: "override",
    });
    expect(resolveModelSelection(first.config)).toEqual({
      selection: defaultModel,
      source: "runtime_default",
    });

    const after = await readRuntimeConfig(fixture.configPath);
    expect(after).toEqual(first);
  });

  test("requires setup when no verified runtime config exists", () => {
    expect(() => resolveModelSelection(undefined)).toThrowError(
      expect.objectContaining({ code: "setup_required" }),
    );
  });

  test("preserves the old default when an atomic write fails before commit", async () => {
    const fixture = await createConfigFixture();
    const first = await writeRuntimeConfigAtomic(
      fixture.configPath,
      createRuntimeConfig(),
      "missing",
    );
    const changed = createRuntimeConfig({
      defaultModel: { model: "gpt-5.6-terra", reasoningEffort: "max" },
      generation: 2,
      verifiedModels: [
        {
          model: "gpt-5.6-terra",
          reasoningEffort: "max",
          providerAccepted: true,
          verifiedAt: "2026-08-07T00:00:00.000Z",
        },
      ],
    });

    await expect(
      writeRuntimeConfigAtomic(fixture.configPath, changed, first.version, {
        beforeRename() {
          throw new Error("injected crash before rename");
        },
      }),
    ).rejects.toThrow(/injected crash/iu);

    await expect(readRuntimeConfig(fixture.configPath)).resolves.toEqual(first);
    const files = await import("node:fs/promises").then((fs) =>
      fs.readdir(fixture.runtimeDir),
    );
    expect(files).toEqual(["config.json", "locks"]);
  });

  test("rejects stale versions instead of overwriting a newer default", async () => {
    const fixture = await createConfigFixture();
    const first = await writeRuntimeConfigAtomic(
      fixture.configPath,
      createRuntimeConfig(),
      "missing",
    );
    const second = await writeRuntimeConfigAtomic(
      fixture.configPath,
      createRuntimeConfig({ generation: 2 }),
      first.version,
    );

    await expect(
      writeRuntimeConfigAtomic(
        fixture.configPath,
        createRuntimeConfig({ generation: 3 }),
        first.version,
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "stale_version" }));
    await expect(readRuntimeConfig(fixture.configPath)).resolves.toEqual(
      second,
    );
  });

  test("requires generation one initially and exactly one step per CAS write", async () => {
    const fixture = await createConfigFixture();
    await expect(
      writeRuntimeConfigAtomic(
        fixture.configPath,
        createRuntimeConfig({ generation: 2 }),
        "missing",
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "stale_version" }));

    const first = await writeRuntimeConfigAtomic(
      fixture.configPath,
      createRuntimeConfig(),
      "missing",
    );
    await expect(
      writeRuntimeConfigAtomic(
        fixture.configPath,
        createRuntimeConfig({ generation: 3 }),
        first.version,
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "stale_version" }));
  });
});

describe("observable cross-process lock contract", () => {
  test("distinguishes real roots that differ only by case under a case-sensitive Windows parent", async (context) => {
    if (process.platform !== "win32") context.skip();
    const parent = await mkdtemp(
      path.join(os.tmpdir(), "c7-config-case-sensitive-"),
    );
    tempDirs.push(parent);
    const capability = spawnSync(
      "fsutil.exe",
      ["file", "SetCaseSensitiveInfo", parent, "enable"],
      { encoding: "utf8", shell: false, windowsHide: true },
    );
    if (capability.status !== 0) {
      context.skip(
        `Windows per-directory case sensitivity is unavailable: ${capability.stderr.trim()}`,
      );
    }
    const runtimeA = path.join(parent, "Runtime");
    const runtimeB = path.join(parent, "runtime");
    await Promise.all([mkdir(runtimeA), mkdir(runtimeB)]);
    let callbackCount = 0;

    await expect(
      withC7Locks(runtimeA, ["operation"], () =>
        withC7Locks(runtimeB, ["operation"], async () => {
          callbackCount += 1;
        }),
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "invalid_config" }));
    expect(callbackCount).toBe(0);
    await expect(lstat(path.join(runtimeB, "locks"))).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  test("uses the acquired canonical root after a runtime junction is retargeted", async () => {
    const runtimeA = await createConfigFixture();
    const runtimeB = await createConfigFixture();
    const runtimeAlias = `${runtimeA.runtimeDir}-retarget`;
    const operationA = path.join(
      runtimeA.runtimeDir,
      "locks",
      "operation.lock",
    );
    const operationB = path.join(
      runtimeB.runtimeDir,
      "locks",
      "operation.lock",
    );
    await symlink(
      runtimeA.runtimeDir,
      runtimeAlias,
      process.platform === "win32" ? "junction" : "dir",
    );
    try {
      await withC7Locks(runtimeAlias, ["operation"], async () => {
        expect(await lstat(operationA)).toMatchObject({});
        await rm(runtimeAlias);
        await symlink(
          runtimeB.runtimeDir,
          runtimeAlias,
          process.platform === "win32" ? "junction" : "dir",
        );
        await mkdir(operationB, { recursive: true });
        await writeFile(path.join(operationB, "foreign.txt"), "foreign");
      });

      await expect(lstat(operationA)).rejects.toMatchObject({ code: "ENOENT" });
      await expect(
        readFile(path.join(operationB, "foreign.txt"), "utf8"),
      ).resolves.toBe("foreign");
    } finally {
      await rm(runtimeAlias, { force: true });
    }
  });

  test.each(["missing", "different"] as const)(
    "rejects nested %s runtime roots before creating lock storage",
    async (kind) => {
      const runtimeA = await createConfigFixture();
      const root = await mkdtemp(path.join(os.tmpdir(), "c7-config-nested-"));
      tempDirs.push(root);
      const runtimeB = path.join(root, "runtime-b");
      if (kind === "different") await mkdir(runtimeB);
      let callbackCount = 0;

      await expect(
        withC7Locks(runtimeA.runtimeDir, ["operation"], () =>
          withC7Locks(runtimeB, ["operation"], async () => {
            callbackCount += 1;
          }),
        ),
      ).rejects.toEqual(expect.objectContaining({ code: "invalid_config" }));
      expect(callbackCount).toBe(0);
      await expect(lstat(path.join(runtimeB, "locks"))).rejects.toMatchObject({
        code: "ENOENT",
      });
      if (kind === "missing") {
        await expect(lstat(runtimeB)).rejects.toMatchObject({ code: "ENOENT" });
      }
    },
  );

  test("does not let a detached async task inherit a released lock lease", async () => {
    const fixture = await createConfigFixture();
    let releaseDetached!: () => void;
    const detachedGate = new Promise<void>((resolve) => {
      releaseDetached = resolve;
    });
    let detachedCallbackCount = 0;
    let detached!: Promise<void>;
    await withC7Locks(fixture.runtimeDir, ["operation"], async () => {
      detached = (async () => {
        await detachedGate;
        await withC7Locks(fixture.runtimeDir, ["operation"], async () => {
          detachedCallbackCount += 1;
        });
      })();
    });
    let holderEntered!: () => void;
    const holderReady = new Promise<void>((resolve) => {
      holderEntered = resolve;
    });
    let releaseHolder!: () => void;
    const holderGate = new Promise<void>((resolve) => {
      releaseHolder = resolve;
    });
    const holder = withC7Locks(fixture.runtimeDir, ["operation"], async () => {
      holderEntered();
      await holderGate;
    });
    await holderReady;

    releaseDetached();
    await expect(detached).rejects.toEqual(
      expect.objectContaining({ code: "busy" }),
    );
    expect(detachedCallbackCount).toBe(0);
    releaseHolder();
    await holder;
  });

  test("a completed nested lease falls back to its still-active parent", async () => {
    const fixture = await createConfigFixture();
    let releaseNested!: () => void;
    const nestedGate = new Promise<void>((resolve) => {
      releaseNested = resolve;
    });
    let detached!: Promise<string>;

    await expect(
      withC7Locks(fixture.runtimeDir, ["operation"], async () => {
        await withC7Locks(fixture.runtimeDir, ["wiki"], async () => {
          detached = (async () => {
            await nestedGate;
            return withC7Locks(
              fixture.runtimeDir,
              ["operation"],
              async () => "parent-active",
            );
          })();
        });
        releaseNested();
        await expect(detached).resolves.toBe("parent-active");
      }),
    ).resolves.toBeUndefined();
  });

  test("binds nested re-entry to one canonical runtime root", async () => {
    const runtimeA = await createConfigFixture();
    const runtimeB = await createConfigFixture();
    let crossRootCallbackCount = 0;

    await expect(
      withC7Locks(runtimeA.runtimeDir, ["operation", "wiki"], () =>
        withC7Locks(runtimeB.runtimeDir, ["operation", "wiki"], async () => {
          crossRootCallbackCount += 1;
        }),
      ),
    ).rejects.toEqual(expect.objectContaining({ code: "invalid_config" }));
    expect(crossRootCallbackCount).toBe(0);

    let sameRootCallbackCount = 0;
    const runtimeAlias = `${runtimeA.runtimeDir}-alias`;
    tempDirs.push(runtimeAlias);
    await symlink(
      runtimeA.runtimeDir,
      runtimeAlias,
      process.platform === "win32" ? "junction" : "dir",
    );
    await expect(
      withC7Locks(runtimeA.runtimeDir, ["operation", "wiki"], () =>
        withC7Locks(runtimeAlias, ["operation", "wiki"], async () => {
          sameRootCallbackCount += 1;
          return "same-root";
        }),
      ),
    ).resolves.toBe("same-root");
    expect(sameRootCallbackCount).toBe(1);

    await expect(
      withC7Locks(runtimeB.runtimeDir, ["operation"], async () => "ordinary"),
    ).resolves.toBe("ordinary");
  });

  test("publishes and enforces the fixed lock order", async () => {
    expect(C7_LOCK_ORDER).toEqual([
      "operation",
      "credentials",
      "config",
      "wiki",
      "manifests",
    ]);
    const fixture = await createConfigFixture();

    await expect(
      withC7Locks(fixture.runtimeDir, ["wiki", "config"], async () => true),
    ).rejects.toThrow(/order/iu);
    await expect(
      withC7Locks(
        fixture.runtimeDir,
        ["operation", "config", "wiki"],
        async () => "locked",
      ),
    ).resolves.toBe("locked");

    await expect(
      withC7Locks(fixture.runtimeDir, ["wiki"], () =>
        withC7Locks(fixture.runtimeDir, ["config"], async () => true),
      ),
    ).rejects.toThrow(/order/iu);

    await expect(
      withC7Locks(
        fixture.runtimeDir,
        ["operation", "credentials", "wiki"],
        () =>
          withC7Locks(fixture.runtimeDir, ["credentials"], async () =>
            withC7Locks(fixture.runtimeDir, ["wiki"], async () => "reentrant"),
          ),
      ),
    ).resolves.toBe("reentrant");
  });

  test("fails busy when another process owns the filesystem lock", async () => {
    const fixture = await createConfigFixture();
    const lockDir = path.join(fixture.runtimeDir, "locks", "config.lock");
    const child = spawnSync(
      process.execPath,
      [
        "-e",
        'const fs=require("node:fs"); const p=require("node:path"); const d=process.argv[1]; fs.mkdirSync(d,{recursive:true}); fs.writeFileSync(p.join(d,"owner.json"),JSON.stringify({pid:process.pid}));',
        lockDir,
      ],
      { shell: false, windowsHide: true },
    );
    expect(child.status).toBe(0);

    await expect(
      withC7Locks(fixture.runtimeDir, ["config"], async () => true),
    ).rejects.toEqual(expect.objectContaining({ code: "busy" }));
  });

  test("startup recovery removes only a strictly identified dead-owner lock", async () => {
    const fixture = await createConfigFixture();
    const lockDir = path.join(fixture.runtimeDir, "locks", "wiki.lock");
    const child = spawnSync(
      process.execPath,
      [
        "-e",
        'const fs=require("node:fs"); const p=require("node:path"); const d=process.argv[1]; fs.mkdirSync(d,{recursive:true}); fs.writeFileSync(p.join(d,"owner.json"),JSON.stringify({createdAt:new Date().toISOString(),instanceId:"00000000-0000-4000-8000-000000000000",pid:process.pid,version:1}));',
        lockDir,
      ],
      { shell: false, windowsHide: true },
    );
    expect(child.status).toBe(0);

    await expect(recoverStaleC7Locks(fixture.runtimeDir)).resolves.toEqual([
      "wiki",
    ]);
    await expect(
      withC7Locks(fixture.runtimeDir, ["wiki"], async () => "recovered"),
    ).resolves.toBe("recovered");
  });

  test("startup recovery fails closed on malformed lock ownership", async () => {
    const fixture = await createConfigFixture();
    const lockDir = path.join(fixture.runtimeDir, "locks", "wiki.lock");
    await mkdir(lockDir, { recursive: true });
    await writeFile(path.join(lockDir, "owner.json"), '{"pid":999999}\n');

    await expect(recoverStaleC7Locks(fixture.runtimeDir)).rejects.toEqual(
      expect.objectContaining({ code: "invalid_config" }),
    );
  });

  test("startup recovery removes a dead pending acquisition with no owner file", async () => {
    const fixture = await createConfigFixture();
    const child = spawnSync(
      process.execPath,
      [
        "-e",
        'const fs=require("node:fs"); const p=require("node:path"); const root=process.argv[1]; fs.mkdirSync(p.join(root,`wiki.pending.${process.pid}.00000000-0000-4000-8000-000000000000`),{recursive:true});',
        path.join(fixture.runtimeDir, "locks"),
      ],
      { shell: false, windowsHide: true },
    );
    expect(child.status).toBe(0);

    await expect(recoverStaleC7Locks(fixture.runtimeDir)).resolves.toEqual([]);
    await expect(
      withC7Locks(fixture.runtimeDir, ["wiki"], async () => "available"),
    ).resolves.toBe("available");
  });
});

describe("Git boundary", () => {
  test("keeps generated and private runtime artifacts out of the source tree", () => {
    const repositoryRoot = path.resolve(import.meta.dirname, "../../..");

    expect(isIgnored(repositoryRoot, ".work/openwiki/dist/cli.js")).toBe(true);
    expect(
      isIgnored(repositoryRoot, "self-openwiki/mcp-server/dist/index.js"),
    ).toBe(true);
    expect(
      isIgnored(repositoryRoot, "self-openwiki/mcp-server/node_modules/x.js"),
    ).toBe(true);
    expect(isIgnored(repositoryRoot, "README.md")).toBe(false);
  });
});

function createRuntimeConfig(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    schemaVersion: 1,
    initialized: true,
    provider: "openai-chatgpt",
    defaultModel,
    generation: 1,
    verifiedModels: [
      {
        ...defaultModel,
        providerAccepted: true,
        verifiedAt: "2026-08-07T00:00:00.000Z",
      },
    ],
    ...overrides,
  };
}

async function createConfigFixture(): Promise<{
  configPath: string;
  runtimeDir: string;
}> {
  const runtimeDir = await mkdtemp(path.join(os.tmpdir(), "c7-config-"));
  tempDirs.push(runtimeDir);
  return { configPath: path.join(runtimeDir, "config.json"), runtimeDir };
}

function isIgnored(repositoryRoot: string, relativePath: string): boolean {
  const result = spawnSync(
    "git",
    ["check-ignore", "--quiet", "--no-index", relativePath],
    { cwd: repositoryRoot, shell: false, windowsHide: true },
  );
  if (result.status !== 0 && result.status !== 1) {
    throw new Error(`git check-ignore failed with status ${result.status}`);
  }
  return result.status === 0;
}
