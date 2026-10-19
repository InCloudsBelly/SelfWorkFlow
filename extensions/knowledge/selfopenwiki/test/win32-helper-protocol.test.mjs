import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, linkSync, rmSync } from 'node:fs';
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
  const child = spawn(helper, ['--stdio', '--root', rootPath, '--attempt-id', 'test-attempt', '--manifest-sha256', 'test-manifest'], { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
  let closed = false;
  child.once('close', () => { closed = true; });
  let pending = Buffer.alloc(0);
  const responses = [];
  const waiters = [];
  child.stdout.on('data', chunk => {
    pending = Buffer.concat([pending, chunk]);
    while (pending.length >= 4) {
      const length = pending.readInt32LE(0);
      if (pending.length < 4 + length) break;
      const response = JSON.parse(pending.subarray(4, 4 + length).toString('utf8'));
      pending = pending.subarray(4 + length);
      const waiter = waiters.shift();
      if (waiter) waiter(response); else responses.push(response);
    }
  });
  const next = () => responses.shift() ?? new Promise(resolve => waiters.push(resolve));
  const send = request => { child.stdin.write(frame(request)); return next(); };
  const stop = async () => {
    if (closed) return;
    const wait = once(child, 'close').catch(() => {});
    if (!child.stdin.destroyed) child.stdin.end();
    if (!child.killed) child.kill();
    await wait;
  };
  return { child, send, stop };
}

test('real helper handshake and bounded filesystem operations use the v1 frame protocol', async t => {
  const storage = mkdtempSync(path.join(tmpdir(), 'selfopenwiki-helper-'));
  const session = start(storage);
  t.after(async () => { await session.stop(); rmSync(storage, { recursive: true, force: true }); });

  const handshake = await session.send({ id: 'h1', op: 'handshake', protocolVersion: 1, mountId: 'root' });
  assert.equal(handshake.status, 'ok');
  assert.equal(handshake.result.ready, true);
  assert.equal(handshake.result.protocolVersion, 1);
  assert.equal(handshake.result.attemptId, 'test-attempt');
  assert.match(handshake.result.image.sha256, /^[0-9a-f]{64}$/);
  assert.equal(typeof handshake.result.mount.volumeSerial, 'number');
  assert.equal(typeof handshake.result.mount.fileIndexHigh, 'number');
  assert.equal(typeof handshake.result.mount.fileIndexLow, 'number');

  const mkdir = await session.send({ id: 'm1', op: 'mkdir', mountId: 'root', path: 'docs' });
  assert.equal(mkdir.status, 'ok', JSON.stringify(mkdir));
  const content = Buffer.from('# stable\n', 'utf8');
  const written = await session.send({ id: 'w1', op: 'write', mountId: 'root', path: 'docs/page.md', dataBase64: content.toString('base64') });
  assert.equal(written.status, 'ok');
  assert.equal(written.result.writtenBytes, content.length);
  const read = await session.send({ id: 'r1', op: 'read', mountId: 'root', path: 'docs/page.md' });
  assert.equal(read.status, 'ok', JSON.stringify(read));
  assert.equal(Buffer.from(read.result.dataBase64, 'base64').toString(), content.toString());
  const listed = await session.send({ id: 'l1', op: 'list', mountId: 'root', path: 'docs' });
  assert.deepEqual(listed.result.entries, ['page.md']);

  const outside = await session.send({ id: 'p1', op: 'read', mountId: 'root', path: '../outside' });
  assert.equal(outside.status, 'error');
  assert.equal(outside.error.code, 'path-rejected');
  const ads = await session.send({ id: 'p2', op: 'read', mountId: 'root', path: 'docs/page.md:secret' });
  assert.equal(ads.status, 'error');
  assert.equal(ads.error.code, 'path-rejected');

  linkSync(path.join(storage, 'docs', 'page.md'), path.join(storage, 'docs', 'page-hardlink.md'));
  const hardlink = await session.send({ id: 'p3', op: 'read', mountId: 'root', path: 'docs/page-hardlink.md' });
  assert.equal(hardlink.status, 'error');
  assert.equal(hardlink.error.code, 'path-rejected');
});

test('unknown and duplicate protocol fields fail closed before any operation', async t => {
  const storage = mkdtempSync(path.join(tmpdir(), 'selfopenwiki-helper-protocol-'));
  t.after(() => rmSync(storage, { recursive: true, force: true }));
  for (const body of [
    Buffer.from('{"id":"x","op":"ping","extra":true}', 'utf8'),
    Buffer.from('{"id":"x","op":"ping","op":"ping"}', 'utf8')
  ]) {
    const child = spawn(helper, ['--stdio', '--root', storage], { stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true });
    child.stdin.write(Buffer.concat([Buffer.from([body.length, 0, 0, 0]), body]));
    child.stdin.end();
    const [code] = await once(child, 'close');
    assert.equal(code, 2);
  }
});
