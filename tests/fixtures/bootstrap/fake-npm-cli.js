"use strict";

const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
const command = args[0];
const controlPath = path.join(__dirname, "fake-npm-control.json");
const control = fs.existsSync(controlPath)
  ? JSON.parse(fs.readFileSync(controlPath, "utf8"))
  : {};

function option(name) {
  const index = args.indexOf(name);
  return index >= 0 && index + 1 < args.length ? args[index + 1] : null;
}

function packageVersion(specification) {
  const separator = specification.lastIndexOf("@");
  return separator > 0 ? specification.slice(separator + 1) : "1.2.3";
}

function invocation() {
  return {
    command,
    pid: process.pid,
    stage: command === "view" ? "metadata" : command,
    args,
    cwd: process.cwd(),
    environment: Object.fromEntries(
      Object.entries(process.env).sort(([left], [right]) =>
        left.localeCompare(right),
      ),
    ),
  };
}

function mutateNodeOrExit() {
  try {
    fs.appendFileSync(process.execPath, "node identity drift", "utf8");
    process.exit(75);
  } catch {
    process.exit(76);
  }
}

function waitAtBarrier(barrier, release, stage) {
  if (!barrier || !release) {
    return;
  }
  fs.writeFileSync(barrier, JSON.stringify({ pid: process.pid, stage }), "utf8");
  const waitState = new Int32Array(new SharedArrayBuffer(4));
  while (!fs.existsSync(release)) {
    Atomics.wait(waitState, 0, 0, 10);
  }
}

function recordInvocation(cacheRoot) {
  if (!cacheRoot || cacheRoot.toUpperCase() === "NUL") {
    return;
  }
  fs.mkdirSync(cacheRoot, { recursive: true });
  fs.appendFileSync(
    path.join(cacheRoot, "fake-npm-invocations.jsonl"),
    JSON.stringify(invocation()) + "\n",
    "utf8",
  );
}

if (command === "view") {
  if (control.metadataMarker) {
    fs.writeFileSync(control.metadataMarker, "metadata", "utf8");
  }
  waitAtBarrier(control.metadataBarrier, control.metadataRelease, "metadata");
  if (control.metadataLog) {
    fs.writeFileSync(control.metadataLog, JSON.stringify(invocation()), "utf8");
  }
  if (control.mutateNodeOnMetadata) {
    mutateNodeOrExit();
  }
  if (control.metadataExitCode) {
    if (control.stderr) {
      process.stderr.write(String(control.stderr));
    }
    process.exit(Number(control.metadataExitCode));
  }
  if (Object.prototype.hasOwnProperty.call(control, "metadataRaw")) {
    process.stdout.write(String(control.metadataRaw));
    process.exit(0);
  }
  const specification = args[1];
  const requested = packageVersion(specification);
  if (requested === "mutate-entry") {
    try {
      fs.appendFileSync(__filename, "\n// entry identity drift\n", "utf8");
    } catch {
      process.exit(76);
    }
  }
  const version = control.metadataVersion ||
    (requested === "latest" || requested === "mutate-entry" ? "1.2.3" : requested);
  process.stdout.write(
    JSON.stringify({
      version,
      "dist.integrity": control.metadataIntegrity ||
        "sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ==",
    }) + "\n",
  );
  process.exit(0);
}

if (command === "install") {
  const prefix = option("--prefix");
  const cacheRoot = option("--cache") || process.env.NPM_CONFIG_CACHE;
  const specification = args[args.length - 1];
  const version = packageVersion(specification);
  if (control.installMarker) {
    fs.writeFileSync(control.installMarker, "install", "utf8");
  }
  waitAtBarrier(control.installBarrier, control.installRelease, "install");
  if (control.mutateNodeOnInstall) {
    mutateNodeOrExit();
  }
  recordInvocation(cacheRoot);
  if (control.mutateEntryOnInstall) {
    try {
      fs.appendFileSync(__filename, "\n// install entry drift\n", "utf8");
    } catch {
      process.exit(76);
    }
  }
  if (control.installExitCode) {
    if (control.stderr) {
      process.stderr.write(String(control.stderr));
    }
    process.exit(Number(control.installExitCode));
  }
  if (!prefix) {
    process.exit(65);
  }

  const packageRoot = path.join(prefix, "node_modules", "@openai", "codex");
  fs.mkdirSync(path.join(packageRoot, "bin"), { recursive: true });
  const packageMetadata = { name: "@openai/codex", version };
  if (!control.omitPackageJson) {
    fs.writeFileSync(
      path.join(packageRoot, "package.json"),
      control.packageJsonRaw === undefined
        ? JSON.stringify(packageMetadata)
        : String(control.packageJsonRaw),
      "utf8",
    );
  }
  fs.writeFileSync(
    path.join(packageRoot, "bin", "codex.js"),
    "require('fs').writeFileSync(__filename + '.executed', 'executed');\n",
    "utf8",
  );
  if (control.createPackageReparse) {
    const escapeTarget = path.join(prefix, "tree-escape-target");
    fs.mkdirSync(escapeTarget, { recursive: true });
    fs.symlinkSync(escapeTarget, path.join(packageRoot, "escape"), "junction");
  }
  if (control.createTreeDriftFixture) {
    const large = fs.openSync(path.join(packageRoot, "aaa-large.bin"), "w");
    fs.ftruncateSync(large, 256 * 1024 * 1024);
    fs.closeSync(large);
  }
  if (control.createTreeDriftFixture || control.createTreeWindowFixture) {
    fs.writeFileSync(path.join(packageRoot, "zzz-drift.bin"), "before", "utf8");
  }
  const packageLockMetadata = {
    lockfileVersion: 3,
    packages: {
      "node_modules/@openai/codex": {
        name: "@openai/codex",
        version,
        integrity: "sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ==",
      },
    },
  };
  if (control.packageLockPaddingBytes) {
    packageLockMetadata.padding = "x".repeat(Number(control.packageLockPaddingBytes));
  }
  if (!control.omitPackageLock) {
    fs.writeFileSync(
      path.join(prefix, "package-lock.json"),
      control.packageLockRaw === undefined
        ? JSON.stringify(packageLockMetadata)
        : String(control.packageLockRaw),
      "utf8",
    );
  }
  waitAtBarrier(
    control.installCompleteBarrier,
    control.installCompleteRelease,
    "install-complete",
  );
  process.exit(0);
}

process.stderr.write("fake npm: unsupported command\n");
process.exit(64);
