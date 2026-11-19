import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ensureCurrentBackground } from '../src/extension/runtime-version.js';

test('new popup reloads an old background before sending configuration requests', async () => {
  let reloads = 0;
  const runtime = { getManifest: () => ({ version: '1.2.1' }), reload: () => { reloads += 1; } };
  const ready = await ensureCurrentBackground(async () => ({ ok: false, error: 'unknown message type' }), runtime);
  assert.equal(ready, false);
  assert.equal(reloads, 1);
});

test('current background and transient messaging errors do not cause reload loops', async () => {
  const runtime = { getManifest: () => ({ version: '1.2.1' }), reload: () => assert.fail('unexpected reload') };
  assert.equal(await ensureCurrentBackground(async () => ({ ok: true, version: '1.2.1' }), runtime), true);
  assert.equal(await ensureCurrentBackground(async () => ({ ok: false, error: 'no response' }), runtime), true);
});

test('update request times out without waiting forever for native messaging', async () => {
  const { requestExtensionUpdate } = await import('../src/extension/runtime-version.js');
  const response = await requestExtensionUpdate(() => new Promise(() => {}), { type: 'updateExtension' }, 5);
  assert.equal(response.ok, false);
  assert.equal(response.timedOut, true);
});

test('update request returns native results and restores errors as responses', async () => {
  const { requestExtensionUpdate } = await import('../src/extension/runtime-version.js');
  assert.deepEqual(await requestExtensionUpdate(async () => ({ ok: true, updated: true }), {}),
    { ok: true, updated: true });
  const response = await requestExtensionUpdate(async () => { throw new Error('native unavailable'); }, {});
  assert.equal(response.ok, false);
  assert.match(response.error, /native unavailable/);
});
