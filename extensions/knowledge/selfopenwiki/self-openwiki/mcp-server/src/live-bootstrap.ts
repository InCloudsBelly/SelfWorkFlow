import { readFile } from "node:fs/promises";
import path from "node:path";
import { bootstrapC7Runtime } from "./bootstrap.js";
import {
  computeCapabilityFingerprint,
  loadRuntimeCapabilityGate,
} from "./capabilities.js";
import { TOOL_NAMES } from "./contracts.js";
import type { C7CapabilityGate, C7ToolRuntime } from "./server.js";

type BootstrapRuntime = {
  capabilityGate: C7CapabilityGate;
  runtime: C7ToolRuntime;
};

const RECONNECT_MESSAGE =
  "SelfOpenWiki executable or runtime configuration changed or could not be bound at startup. Reconnect this MCP server to load the verified build.";
const UNVERIFIED_MESSAGE =
  "SelfOpenWiki capability verification is missing, stale, or incomplete. Complete module verification and retry on this connection.";

export async function bootstrapLiveC7Runtime(
  options: NonNullable<Parameters<typeof bootstrapC7Runtime>[0]> = {},
): Promise<LiveC7Bootstrap> {
  const repositoryRoot = path.resolve(
    options.repositoryRoot ?? path.resolve(import.meta.dirname, "../.."),
  );
  const openWikiRoot = path.resolve(
    options.openWikiRoot ??
      path.resolve(repositoryRoot, "..", ".work", "openwiki"),
  );
  const boundOptions = { ...options, repositoryRoot, openWikiRoot };
  const evidencePath = path.resolve(
    options.evidencePath ??
      path.join(repositoryRoot, "runtime", "verified-capabilities.json"),
  );
  // Evidence can be absent at startup. Bind the executable inputs themselves,
  // rather than accepting the first subsequently verified build as our identity.
  const readBinding = async () => {
    const [fingerprint, config] = await Promise.all([
      computeCapabilityFingerprint({ repositoryRoot, openWikiRoot }),
      Promise.all(
        ["defaults.json", "sensitive-files.json"].map((name) =>
          readFile(path.join(repositoryRoot, "config", name), "utf8"),
        ),
      ),
    ]);
    return JSON.stringify([
      fingerprint.buildHash,
      fingerprint.contractsHash,
      fingerprint.dependencyHash,
      fingerprint.matrixHash,
      fingerprint.moduleHasherHash,
      ...config,
    ]);
  };
  let startupBinding = await readBinding().catch(() => null);
  const initial = await bootstrapC7Runtime(boundOptions);
  if ((await readBinding().catch(() => null)) !== startupBinding)
    startupBinding = null;
  return new LiveC7Bootstrap({
    initial,
    startupBinding,
    readBinding,
    loadGate: () =>
      loadRuntimeCapabilityGate({ repositoryRoot, openWikiRoot, evidencePath }),
    bootstrap: () => bootstrapC7Runtime(boundOptions),
  });
}

export class LiveC7Bootstrap {
  // The MCP server gate is synchronous. Admit calls only to this asynchronous
  // guard; it must never expose the minimal or replacement runtime directly.
  readonly capabilityGate: C7CapabilityGate = { isToolVerified: () => true };
  private current: BootstrapRuntime;
  private ready: boolean;
  private reconnectRequired: boolean;
  private promotion: Promise<void> | undefined;

  constructor(
    private readonly options: {
      initial: BootstrapRuntime;
      startupBinding: string | null;
      readBinding(): Promise<string>;
      loadGate(): Promise<C7CapabilityGate>;
      bootstrap(): Promise<BootstrapRuntime>;
    },
  ) {
    this.current = options.initial;
    this.reconnectRequired = options.startupBinding === null;
    this.ready =
      !this.reconnectRequired && fullyVerified(options.initial.capabilityGate);
  }

  readonly runtime: C7ToolRuntime = {
    invoke: async (name, input, signal) => {
      await this.ensureReady();
      const message = this.reconnectRequired
        ? RECONNECT_MESSAGE
        : UNVERIFIED_MESSAGE;
      if (
        name !== "openwiki_status" &&
        (!this.ready || !this.current.capabilityGate.isToolVerified(name))
      ) {
        return {
          ok: false,
          error: { code: "capability_unverified", message, retryable: false },
          recovery: { action: "retry", message },
        };
      }
      const output = await this.current.runtime.invoke(name, input, signal);
      if (
        name !== "openwiki_status" ||
        this.ready ||
        typeof output !== "object" ||
        output === null ||
        !("ok" in output) ||
        output.ok !== true ||
        !("recovery" in output) ||
        typeof output.recovery !== "object" ||
        output.recovery === null ||
        !("action" in output.recovery)
      )
        return output;
      const recovery = output.recovery as { action: string; message?: string };
      return {
        ...output,
        recovery: {
          ...recovery,
          action: recovery.action === "none" ? "retry" : recovery.action,
          message: [recovery.message, message].filter(Boolean).join(" "),
        },
      };
    },
  };

  private async ensureReady(): Promise<void> {
    if (this.ready || this.reconnectRequired) return;
    if (!this.promotion) {
      this.promotion = this.tryPromote().finally(() => {
        this.promotion = undefined;
      });
    }
    await this.promotion;
  }

  private async tryPromote(): Promise<void> {
    try {
      if (!fullyVerified(await this.options.loadGate())) return;
      if ((await this.options.readBinding()) !== this.options.startupBinding) {
        this.reconnectRequired = true;
        return;
      }
      const next = await this.options.bootstrap();
      if ((await this.options.readBinding()) !== this.options.startupBinding) {
        this.reconnectRequired = true;
        return;
      }
      if (
        !fullyVerified(next.capabilityGate) ||
        !fullyVerified(await this.options.loadGate())
      )
        return;
      this.current = next;
      this.ready = true;
    } catch {
      // Keep the original diagnostic runtime and retry transient verification or
      // bootstrap failures on the next call without requiring another marker.
    }
  }
}

function fullyVerified(gate: C7CapabilityGate): boolean {
  return TOOL_NAMES.every((name) => gate.isToolVerified(name));
}
