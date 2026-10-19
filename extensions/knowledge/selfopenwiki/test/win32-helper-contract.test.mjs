import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';

const root = path.resolve(import.meta.dirname, '..');
const helperRoot = path.join(root, 'self-openwiki', 'win32-helper');
const project = path.join(helperRoot, 'SelfOpenWiki.Win32Helper.csproj');
const bootstrapRoot = path.join(helperRoot, 'bootstrap', 'win-x64');
const bootstrapExe = path.join(bootstrapRoot, 'SelfOpenWiki.Win32Helper.exe');
const bootstrapManifest = path.join(bootstrapRoot, 'bootstrap-manifest.json');
const sourceManifest = path.join(root, 'self-openwiki', 'config', 'bootstrap-source-manifest.json');
const toolchainLock = path.join(root, 'self-openwiki', 'config', 'toolchain-runtime-lock.json');
const buildScript = path.join(root, 'scripts', 'build-win32-helper.mjs');

test('Batch 1A publishes the reviewed helper project and closed bootstrap roots', () => {
  assert.equal(existsSync(project), true, 'helper project is missing');
  assert.equal(existsSync(bootstrapExe), true, 'tracked bootstrap executable is missing');
  assert.equal(existsSync(bootstrapManifest), true, 'bootstrap manifest is missing');
  assert.equal(existsSync(sourceManifest), true, 'bootstrap source manifest is missing');
  assert.equal(existsSync(toolchainLock), true, 'toolchain runtime lock is missing');

  const entries = readdirSync(bootstrapRoot).sort();
  assert.deepEqual(entries, ['SelfOpenWiki.Win32Helper.exe', 'bootstrap-manifest.json']);
  assert.equal(statSync(bootstrapExe).isFile(), true);
  assert.equal(statSync(bootstrapManifest).isFile(), true);
});

test('bootstrap manifests use the frozen domain-separated v1 contracts', () => {
  const bootstrap = JSON.parse(readFileSync(bootstrapManifest, 'utf8'));
  const source = JSON.parse(readFileSync(sourceManifest, 'utf8'));
  const toolchain = JSON.parse(readFileSync(toolchainLock, 'utf8'));
  assert.equal(bootstrap.schemaVersion, 1);
  assert.equal(bootstrap.domain, 'selfopenwiki:win32-helper-bootstrap:v1');
  assert.equal(source.schemaVersion, 1);
  assert.equal(source.domain, 'selfopenwiki:bootstrap-source-root:v1');
  assert.equal(toolchain.schemaVersion, 1);
  assert.equal(toolchain.domain, 'selfopenwiki:toolchain-runtime-lock:v1');
});

test('network-free helper rebuilds are byte-identical and payload roots stay closed', { timeout: 120_000 }, () => {
  const parent = mkdtempSync(path.join(tmpdir(), 'selfopenwiki-helper-candidates-'));
  const first = path.join(parent, 'candidate-a');
  const second = path.join(parent, 'candidate-b');
  try {
    const env = { ...process.env, CI: 'true', COREPACK_ENABLE_DOWNLOAD_PROMPT: '0' };
    execFileSync(process.execPath, [buildScript, '--create-reviewed-candidate', first, '--no-restore'], { cwd: root, env, stdio: 'pipe', windowsHide: true });
    execFileSync(process.execPath, [buildScript, '--create-reviewed-candidate', second, '--no-restore'], { cwd: root, env, stdio: 'pipe', windowsHide: true });
    const verification = JSON.parse(execFileSync(process.execPath, [buildScript, '--verify-reproducible', first, second, '--no-restore'], { cwd: root, env, encoding: 'utf8', windowsHide: true }).trim());
    assert.equal(verification.status, 'verified');
    assert.equal(readdirSync(first).sort().join(','), 'SelfOpenWiki.Win32Helper.exe,bootstrap-manifest.json');
    assert.equal(JSON.parse(readFileSync(path.join(first, 'bootstrap-manifest.json'), 'utf8')).executable.path, 'SelfOpenWiki.Win32Helper.exe');
  } finally {
    rmSync(parent, { recursive: true, force: true });
  }
});
