import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const project = path.join(root, 'self-openwiki', 'win32-helper', 'SelfOpenWiki.Win32Helper.csproj');
const sourceManifestPath = path.join(root, 'self-openwiki', 'config', 'bootstrap-source-manifest.json');
const toolchainLockPath = path.join(root, 'self-openwiki', 'config', 'toolchain-runtime-lock.json');
const defaultBootstrap = path.join(root, 'self-openwiki', 'win32-helper', 'bootstrap', 'win-x64');
const protocolVersion = 1;

function sha256(bytes) { return createHash('sha256').update(bytes).digest('hex'); }
function bytesOf(file) { return readFileSync(file); }
function logical(rootPath, file) { return path.relative(rootPath, file).replaceAll(path.sep, '/'); }
function filesUnder(directory) {
  if (!existsSync(directory)) return [];
  const result = [];
  const visit = current => {
    for (const entry of readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const file = path.join(current, entry.name);
      if (entry.isDirectory()) visit(file);
      else if (entry.isFile()) result.push(file);
      else throw new Error(`unsupported toolchain entry: ${file}`);
    }
  };
  visit(directory);
  return result;
}
function writeCanonical(file, value) {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(value)}\n`, { encoding: 'utf8', flag: 'w' });
}
function fileRecord(file, relativeRoot, logicalPath = logical(relativeRoot, file)) {
  const bytes = bytesOf(file);
  return { path: logicalPath, bytes: bytes.byteLength, sha256: sha256(bytes) };
}
function run(command, args) {
  const env = { ...process.env, CI: 'true', DOTNET_CLI_TELEMETRY_OPTOUT: '1', DOTNET_NOLOGO: '1', NUGET_XMLDOC_MODE: 'skip' };
  delete env.PATH; delete env.COMSPEC; delete env.SystemRoot;
  return execFileSync(command, args, { cwd: root, env: { ...env, PATH: process.env.PATH }, stdio: 'inherit', windowsHide: true });
}

function createToolchainLock() {
  const dotnet = process.env.ProgramFiles ? path.join(process.env.ProgramFiles, 'dotnet') : 'C:\\Program Files\\dotnet';
  const sdk = '9.0.304';
  const runtime = '9.0.8';
  const roots = [
    ['dotnet.exe', path.join(dotnet, 'dotnet.exe')],
    [`sdk/${sdk}`, path.join(dotnet, 'sdk', sdk)],
    [`packs/Microsoft.NETCore.App.Ref/${runtime}`, path.join(dotnet, 'packs', 'Microsoft.NETCore.App.Ref', runtime)],
    [`packs/Microsoft.NETCore.App.Host.win-x64/${runtime}`, path.join(dotnet, 'packs', 'Microsoft.NETCore.App.Host.win-x64', runtime)],
    [`shared/Microsoft.NETCore.App/${runtime}`, path.join(dotnet, 'shared', 'Microsoft.NETCore.App', runtime)]
  ];
  const files = [];
  for (const [prefix, directory] of roots) {
    if (statSync(directory, { throwIfNoEntry: false })?.isFile()) files.push(fileRecord(directory, path.dirname(directory), prefix));
    else for (const file of filesUnder(directory)) files.push(fileRecord(file, directory, `${prefix}/${logical(directory, file)}`));
  }
  files.sort((a, b) => a.path.localeCompare(b.path));
  return { schemaVersion: 1, domain: 'selfopenwiki:toolchain-runtime-lock:v1', os: 'windows', architecture: 'x64', dotnet: { sdkVersion: sdk, runtimeVersion: runtime }, files };
}

function createSourceManifest() {
  const relativeFiles = [
    'global.json', 'package.json',
    'scripts/build-win32-helper.mjs', 'scripts/materialize-openwiki.mjs', 'scripts/update-upstream.mjs',
    'test/win32-helper-contract.test.mjs', 'test/win32-helper-protocol.test.mjs', 'test/materialize-openwiki.test.mjs', 'test/repository-contract.test.mjs', 'test/update-upstream.v2.test.mjs',
    'self-openwiki/win32-helper/SelfOpenWiki.Win32Helper.csproj', 'self-openwiki/win32-helper/Directory.Build.props', 'self-openwiki/win32-helper/Program.cs',
    'patches/openwiki/manifest.json', 'patches/openwiki/0001-selfopenwiki-runtime-hooks.patch',
    'self-openwiki/agent-skills/self-openwiki/SKILL.md',
    'self-openwiki/agent-skills/self-openwiki/references/mcp-contract.md',
    'self-openwiki/agent-skills/self-openwiki/references/migration-v2.md'
  ];
  const files = relativeFiles.map(relative => fileRecord(path.join(root, relative), root, relative));
  files.sort((a, b) => a.path.localeCompare(b.path));
  return { schemaVersion: 1, domain: 'selfopenwiki:bootstrap-source-root:v1', files };
}

function publish(destination) {
  if (!path.isAbsolute(destination)) throw new Error('--create-reviewed-candidate requires an absolute destination');
  mkdirSync(destination, { recursive: true });
  const publishDirectory = path.join(root, '.work', 'helper-build', 'publish');
  rmSync(publishDirectory, { recursive: true, force: true });
  run('dotnet', ['publish', project, '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-p:PublishSingleFile=true', '-p:IncludeNativeLibrariesForSelfExtract=true', '-p:DebugType=None', '-p:DebugSymbols=false', '--no-restore', '-o', publishDirectory]);
  const payload = filesUnder(publishDirectory).filter(file => path.extname(file).toLowerCase() === '.exe');
  if (payload.length !== 1) throw new Error('publish must contain exactly one executable');
  const forbidden = filesUnder(publishDirectory).filter(file => /\.(pdb|json|deps\.json|runtimeconfig\.json)$/i.test(file));
  if (forbidden.length) throw new Error(`publish contains non-bootstrap payload: ${forbidden.map(file => logical(publishDirectory, file)).join(',')}`);
  for (const entry of readdirSync(destination)) rmSync(path.join(destination, entry), { recursive: true, force: true });
  const executable = path.join(destination, 'SelfOpenWiki.Win32Helper.exe');
  writeFileSync(executable, bytesOf(payload[0]), { flag: 'wx' });
  const sourceManifest = createSourceManifest();
  const toolchainLock = createToolchainLock();
  writeCanonical(sourceManifestPath, sourceManifest);
  writeCanonical(toolchainLockPath, toolchainLock);
  const executableBytes = bytesOf(executable);
  writeCanonical(path.join(destination, 'bootstrap-manifest.json'), {
    schemaVersion: 1,
    domain: 'selfopenwiki:win32-helper-bootstrap:v1',
    protocolVersion,
    executable: { path: 'SelfOpenWiki.Win32Helper.exe', bytes: executableBytes.byteLength, sha256: sha256(executableBytes) },
    payloadFiles: [{ path: 'SelfOpenWiki.Win32Helper.exe', bytes: executableBytes.byteLength, sha256: sha256(executableBytes) }],
    sourceManifest: { path: 'self-openwiki/config/bootstrap-source-manifest.json', sha256: sha256(bytesOf(sourceManifestPath)) },
    toolchainLock: { path: 'self-openwiki/config/toolchain-runtime-lock.json', sha256: sha256(bytesOf(toolchainLockPath)) }
  });
}

function verifyReproducible(first, second) {
  const firstExe = path.join(first, 'SelfOpenWiki.Win32Helper.exe');
  const secondExe = path.join(second, 'SelfOpenWiki.Win32Helper.exe');
  if (!existsSync(firstExe) || !existsSync(secondExe)) throw new Error('candidate executable is missing');
  const a = bytesOf(firstExe), b = bytesOf(secondExe);
  if (a.length !== b.length || !a.equals(b)) throw new Error(`non-reproducible helper: ${sha256(a)} != ${sha256(b)}`);
  process.stdout.write(`${JSON.stringify({ status: 'verified', sha256: sha256(a), bytes: a.length })}\n`);
}

const args = process.argv.slice(2);
if (args[0] === '--create-reviewed-candidate') publish(args[1] ?? (() => { throw new Error('missing destination'); })());
else if (args[0] === '--verify-reproducible') verifyReproducible(args[1], args[2]);
else if (args.length === 0) publish(defaultBootstrap);
else throw new Error(`unknown build command: ${args.join(' ')}`);
