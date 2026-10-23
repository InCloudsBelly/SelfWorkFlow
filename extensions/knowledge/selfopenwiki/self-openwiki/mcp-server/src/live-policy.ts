import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  loadRuntimeCapabilityGate,
  type RuntimeCapabilityGate,
} from "./capabilities.js";
import { TOOL_NAMES } from "./contracts.js";
import {
  assertPersonalCompatibility,
  computeModuleSourceManifestHash,
  loadPersonalCompatibilityManifest,
  PersonalSkillAdapter as BoundPersonalSkillAdapter,
  PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT,
} from "./personal-skill-adapter.js";
import type { PersonalSkillAdapter } from "./personal-wiki-lifecycle.js";
import type { C7ToolRuntime } from "./server.js";
import { loadC7SkillRegistry, type C7SkillRegistry } from "./skills.js";

const STALE_MODULE_MESSAGE =
  "SelfOpenWiki module files no longer match their verified capability evidence. Verify this module before using Wiki tools.";
const VALIDATION_ERROR_MESSAGE =
  "SelfOpenWiki module validation could not complete. Check the module files and verification evidence, then retry.";
const POLICY_ERROR_MESSAGE =
  "SelfOpenWiki policy verification is missing, stale, or incomplete. Complete module verification; the next call will load its verified rules automatically.";
const RECONNECT_MESSAGE =
  "SelfOpenWiki executable or runtime configuration changed. Reconnect this MCP server to load the verified build.";

export async function createLiveWikiPolicy(options: {
  repositoryRoot: string;
  openWikiRoot: string;
  evidencePath: string;
  capabilityGate: RuntimeCapabilityGate;
}): Promise<LiveWikiPolicy> {
  const startupVerifiedTools = new Set(
    TOOL_NAMES.filter((name) => options.capabilityGate.isToolVerified(name)),
  );
  const matchesStartupTools = (gate: RuntimeCapabilityGate) =>
    startupVerifiedTools.size > 0 &&
    TOOL_NAMES.every(
      (name) => gate.isToolVerified(name) === startupVerifiedTools.has(name),
    );
  const readVersion = () =>
    readFile(options.evidencePath, "utf8").catch(() => null);
  const load = async (): Promise<WikiPolicySnapshot> => {
    const gate = await loadRuntimeCapabilityGate(options);
    if (!matchesStartupTools(gate) || !gate.fingerprint) {
      throw new Error("Policy capability evidence is unverified.");
    }
    const skills = await loadC7SkillRegistry(
      path.join(options.repositoryRoot, "config", "trusted-skills.json"),
      path.join(options.repositoryRoot, "openwiki-skills"),
    );
    const compatibility = await loadPersonalCompatibilityManifest(
      options.repositoryRoot,
    );
    await assertPersonalCompatibility(
      compatibility,
      PINNED_PERSONAL_OPENWIKI_UPSTREAM_COMMIT,
      TOOL_NAMES,
      {
        ...options,
        expectedModuleHasherHash: gate.fingerprint.moduleHasherHash,
      },
    );
    const manifestBytes = await readFile(
      path.join(
        options.repositoryRoot,
        "config",
        "personal-openwiki-compatibility.json",
      ),
    );
    const restartConfig = await Promise.all(
      ["defaults.json", "sensitive-files.json"].map((name) =>
        readFile(path.join(options.repositoryRoot, "config", name), "utf8"),
      ),
    );
    return {
      capabilities: gate,
      moduleSourceHash: compatibility.build.parentSourceManifestHash,
      skills,
      personalSkill: new BoundPersonalSkillAdapter({
        expectedCompatibilityManifestHash: `sha256:${createHash("sha256").update(manifestBytes).digest("hex")}`,
        expectedPackageHash: compatibility.skill.packageHash,
        expectedBasePackageHash: skills.list()[0].packageHash,
        skillPath: path.join(
          options.repositoryRoot,
          "agent-skills",
          "self-openwiki",
          "SKILL.md",
        ),
        upstreamCommit: compatibility.upstream.commit,
      }),
      restartBinding: JSON.stringify([
        gate.fingerprint.buildHash,
        gate.fingerprint.contractsHash,
        gate.fingerprint.dependencyHash,
        gate.fingerprint.matrixHash,
        gate.fingerprint.moduleHasherHash,
        ...restartConfig,
      ]),
    };
  };
  const version = await readVersion();
  const initial = await load();
  if (version === null || (await readVersion()) !== version)
    throw new Error("Policy verification changed during startup.");
  if (
    !options.capabilityGate.fingerprint ||
    initial.restartBinding !==
      (await startupRestartBinding(
        options.capabilityGate,
        options.repositoryRoot,
      ))
  ) {
    throw new Error(
      "SelfOpenWiki executable changed during startup. Reconnect the MCP server.",
    );
  }
  const validateCurrent = async (snapshot: WikiPolicySnapshot) => {
    const gate = await loadRuntimeCapabilityGate(options);
    if (!gate.fingerprint || !matchesStartupTools(gate)) return false;
    if (
      (await startupRestartBinding(gate, options.repositoryRoot)) !==
      initial.restartBinding
    ) {
      return "restart_required" as const;
    }
    const moduleSourceHash = await computeModuleSourceManifestHash(
      path.resolve(options.repositoryRoot, ".."),
      gate.fingerprint.moduleHasherHash,
    );
    return moduleSourceHash === snapshot.moduleSourceHash;
  };
  return new LiveWikiPolicy({
    initial,
    version,
    readVersion,
    load,
    validateCurrent,
  });
}

async function startupRestartBinding(
  gate: RuntimeCapabilityGate,
  root: string,
): Promise<string> {
  const config = await Promise.all(
    ["defaults.json", "sensitive-files.json"].map((name) =>
      readFile(path.join(root, "config", name), "utf8"),
    ),
  );
  const fingerprint = gate.fingerprint!;
  return JSON.stringify([
    fingerprint.buildHash,
    fingerprint.contractsHash,
    fingerprint.dependencyHash,
    fingerprint.matrixHash,
    fingerprint.moduleHasherHash,
    ...config,
  ]);
}

export type WikiPolicySnapshot = {
  capabilities: Pick<RuntimeCapabilityGate, "isToolVerified" | "records">;
  moduleSourceHash: string;
  skills: C7SkillRegistry;
  personalSkill: PersonalSkillAdapter;
  restartBinding: string;
};

export class LiveWikiPolicy {
  private current: WikiPolicySnapshot;
  private version: string | null;
  private active = 0;
  private admission: Promise<void> = Promise.resolve();
  private failure: string | undefined;

  constructor(
    private readonly options: {
      initial: WikiPolicySnapshot;
      version: string | null;
      readVersion(): Promise<string | null>;
      load(): Promise<WikiPolicySnapshot>;
      validateCurrent?(
        snapshot: WikiPolicySnapshot,
      ): Promise<boolean | "restart_required">;
    },
  ) {
    this.current = options.initial;
    this.version = options.version;
  }

  readonly skills: C7SkillRegistry = {
    list: () => this.current.skills.list(),
    select: (ids) => this.current.skills.select(ids),
  };

  readonly capabilities: WikiPolicySnapshot["capabilities"] = {
    isToolVerified: (name) =>
      !this.failure && this.current.capabilities.isToolVerified(name),
    records: () => (this.failure ? [] : this.current.capabilities.records()),
  };

  readonly personalSkill: PersonalSkillAdapter = {
    resolve: (ids) => this.current.personalSkill.resolve(ids),
  };

  wrap(runtime: C7ToolRuntime): C7ToolRuntime {
    return {
      invoke: async (name, input, signal) => {
        // A generation stays fixed for every in-flight call, including provider work.
        const entered = this.admission.then(async () => {
          if (this.active === 0) await this.refreshOnce();
          if (this.options.validateCurrent) {
            try {
              const validation = await this.options.validateCurrent(
                this.current,
              );
              if (validation === "restart_required") {
                this.failure = RECONNECT_MESSAGE;
              } else if (!validation) {
                if (!this.failure || this.isValidationFailure())
                  this.failure = STALE_MODULE_MESSAGE;
              } else if (
                this.isValidationFailure() ||
                this.failure === RECONNECT_MESSAGE
              ) {
                this.failure = undefined;
              }
            } catch {
              if (!this.failure || this.isValidationFailure())
                this.failure = VALIDATION_ERROR_MESSAGE;
            }
          }
          this.active++;
        });
        this.admission = entered.catch(() => undefined);
        await entered;
        try {
          if (
            name !== "openwiki_status" &&
            !this.capabilities.isToolVerified(name)
          ) {
            return {
              ok: false,
              error: {
                code: "capability_unverified",
                message: this.failure ?? "Wiki capability is unverified.",
                retryable: false,
              },
              recovery: { action: "retry", message: this.failure },
            };
          }
          const output = await runtime.invoke(name, input, signal);
          if (
            name === "openwiki_status" &&
            this.failure &&
            typeof output === "object" &&
            output !== null &&
            "ok" in output &&
            output.ok === true &&
            "recovery" in output &&
            typeof output.recovery === "object" &&
            output.recovery !== null &&
            "action" in output.recovery &&
            typeof output.recovery.action === "string"
          ) {
            const recovery = output.recovery as {
              action: string;
              message?: string;
            };
            return {
              ...output,
              recovery: {
                action: recovery.action === "none" ? "retry" : recovery.action,
                message: [recovery.message, this.failure]
                  .filter(Boolean)
                  .join(" "),
              },
            };
          }
          return output;
        } finally {
          this.active--;
        }
      },
    };
  }

  private isValidationFailure(): boolean {
    return (
      this.failure === STALE_MODULE_MESSAGE ||
      this.failure === VALIDATION_ERROR_MESSAGE
    );
  }

  private async refreshOnce(): Promise<void> {
    try {
      const version = await this.options.readVersion();
      if (version === this.version && this.failure !== POLICY_ERROR_MESSAGE)
        return;
      if (version === null) throw new Error("unverified");
      const next = await this.options.load();
      if (next.restartBinding !== this.options.initial.restartBinding) {
        this.version = version;
        this.failure = RECONNECT_MESSAGE;
        return;
      }
      if ((await this.options.readVersion()) !== version)
        throw new Error("changed");
      this.current = next;
      this.version = version;
      this.failure = undefined;
    } catch {
      this.failure = POLICY_ERROR_MESSAGE;
    }
  }
}
