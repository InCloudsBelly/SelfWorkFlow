import assert from 'node:assert/strict';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import test from 'node:test';

const root = path.resolve(import.meta.dirname, '..');
const helper = path.join(root, 'self-openwiki', 'win32-helper', 'bootstrap', 'win-x64', 'SelfOpenWiki.Win32Helper.exe');

function frame(value) {
  const body = Buffer.from(JSON.stringify(value), 'utf8');
  const header = Buffer.alloc(4);
  header.writeInt32LE(body.length);
  return Buffer.concat([header, body]);
}

function start(rootPath) {
  const child = spawn(helper, ['--stdio', '--root', rootPath, '--attempt-id', 'io-boundary-test'], { stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true });
  let pending = Buffer.alloc(0);
  const waiters = [];
  child.stdout.on('data', chunk => {
    pending = Buffer.concat([pending, chunk]);
    while (pending.length >= 4) {
      const size = pending.readInt32LE(0);
      if (size <= 0 || pending.length < size + 4) return;
      const response = JSON.parse(pending.subarray(4, size + 4).toString('utf8'));
      pending = pending.subarray(size + 4);
      waiters.shift()?.(response);
    }
  });
  return {
    child,
    send(request) {
      const response = new Promise(resolve => waiters.push(resolve));
      child.stdin.write(frame(request));
      return response;
    },
    async stop() {
      if (child.exitCode !== null) return;
      const closed = once(child, 'close').catch(() => {});
      child.stdin.end();
      child.kill();
      await closed;
    }
  };
}

test('directory replacement cannot make list enumerate outside the bound root', { timeout: 120_000 }, async () => {
  const storage = mkdtempSync(path.join(tmpdir(), 'selfopenwiki-io-'));
  const outside = mkdtempSync(path.join(tmpdir(), 'selfopenwiki-io-outside-'));
  const docs = path.join(storage, 'docs');
  const parked = path.join(storage, 'docs-parked');
  mkdirSync(docs);
  writeFileSync(path.join(docs, 'inside.md'), 'inside\n');
  writeFileSync(path.join(outside, 'outside-secret.md'), 'must-not-be-enumerated\n');
  const session = start(storage);
  let active = true;
  let swaps = 0;
  const toggle = () => {
    if (!active) return;
    try {
      if (existsSync(docs) && !lstatSync(docs).isSymbolicLink()) renameSync(docs, parked);
      if (!existsSync(docs)) { symlinkSync(outside, docs, 'junction'); swaps++; }
    } catch {
      // The helper may hold a no-delete-share handle. Keep the attack schedule alive.
    }
    setImmediate(() => {
      try {
        if (existsSync(docs) && lstatSync(docs).isSymbolicLink()) unlinkSync(docs);
        if (!existsSync(docs) && existsSync(parked)) renameSync(parked, docs);
      } catch {
        // Retry on the next cycle.
      }
      if (active) setImmediate(toggle);
    });
  };
  try {
    const handshake = await session.send({ id: 'h', op: 'handshake', protocolVersion: 1, mountId: 'root' });
    assert.equal(handshake.status, 'ok');
    toggle();
    const outsideEntries = [];
    for (let i = 0; i < 200; i++) {
      const response = await session.send({ id: `l${i}`, op: 'list', mountId: 'root', path: 'docs' });
      if (response.status === 'ok') outsideEntries.push(...response.result.entries.filter(entry => entry.includes('outside')));
    }
    active = false;
    assert.ok(swaps > 0, 'attack schedule never established a junction');
    assert.deepEqual(outsideEntries, [], `list escaped the mount: ${JSON.stringify(outsideEntries)}`);
  } finally {
    active = false;
    await session.stop();
    if (existsSync(docs) && lstatSync(docs).isSymbolicLink()) unlinkSync(docs);
    if (!existsSync(docs) && existsSync(parked)) renameSync(parked, docs);
    rmSync(storage, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  }
});

