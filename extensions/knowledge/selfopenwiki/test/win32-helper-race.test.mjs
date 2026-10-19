import assert from 'node:assert/strict';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import test from 'node:test';

const root = path.resolve(import.meta.dirname, '..');
const helper = path.join(root, 'self-openwiki', 'win32-helper', 'bootstrap', 'win-x64', 'SelfOpenWiki.Win32Helper.exe');

function encode(value) {
  const body = Buffer.from(JSON.stringify(value));
  const header = Buffer.alloc(4);
  header.writeInt32LE(body.length);
  return Buffer.concat([header, body]);
}

function start(rootPath) {
  const child = spawn(helper, ['--stdio', '--root', rootPath, '--attempt-id', 'race-test'], { stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true });
  let pending = Buffer.alloc(0);
  const waiters = [];
  child.stdout.on('data', chunk => {
    pending = Buffer.concat([pending, chunk]);
    while (pending.length >= 4) {
      const length = pending.readInt32LE(0);
      if (pending.length < length + 4) return;
      const response = JSON.parse(pending.subarray(4, length + 4).toString());
      pending = pending.subarray(length + 4);
      waiters.shift()?.(response);
    }
  });
  return {
    child,
    send(request) {
      const response = new Promise(resolve => waiters.push(resolve));
      child.stdin.write(encode(request));
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

test('ancestor junction replacement never writes outside the held storage root', { timeout: 120_000 }, async t => {
  const storage = mkdtempSync(path.join(tmpdir(), 'selfopenwiki-race-'));
  const outside = mkdtempSync(path.join(tmpdir(), 'selfopenwiki-outside-'));
  const docs = path.join(storage, 'docs');
  const parked = path.join(storage, 'docs-parked');
  mkdirSync(docs);
  writeFileSync(path.join(outside, 'sentinel.txt'), 'UNCHANGED\n');
  const session = start(storage);
  let active = true;
  let swaps = 0;
  const toggle = () => {
    if (!active) return;
    try {
      if (existsSync(docs) && !lstatSync(docs).isSymbolicLink()) renameSync(docs, parked);
      if (!existsSync(docs)) { symlinkSync(outside, docs, 'junction'); swaps++; }
    } catch {
      // The helper may hold a no-delete-share handle; retrying is the attack schedule.
      if (active) return setImmediate(toggle);
    }
    setTimeout(() => {
      try {
        if (existsSync(docs) && lstatSync(docs).isSymbolicLink()) unlinkSync(docs);
        if (!existsSync(docs) && existsSync(parked)) renameSync(parked, docs);
      } catch {
        // Retry the restore on the next attack cycle.
      }
      if (active) setImmediate(toggle);
    }, 20);
  };
  try {
    const handshake = await session.send({ id: 'h', op: 'handshake', protocolVersion: 1, mountId: 'root' });
    assert.equal(handshake.status, 'ok');
    const payload = Buffer.alloc(10 * 1024 * 1024, 0x5a);
    active = true;
    toggle();
    const result = await session.send({ id: 'w', op: 'write', mountId: 'root', path: 'docs/race.bin', dataBase64: payload.toString('base64') });
    active = false;
    assert.ok(result.status === 'ok' || result.status === 'error', JSON.stringify(result));
    assert.equal(readFileSync(path.join(outside, 'sentinel.txt'), 'utf8'), 'UNCHANGED\n');
    assert.equal(existsSync(path.join(outside, 'race.bin')), false, 'ancestor replacement escaped the mount');
    assert.ok(swaps > 0, 'attack schedule never established a junction');
  } finally {
    active = false;
    await session.stop();
    if (existsSync(docs) && lstatSync(docs).isSymbolicLink()) unlinkSync(docs);
    if (!existsSync(docs) && existsSync(parked)) renameSync(parked, docs);
    rmSync(storage, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  }
});
