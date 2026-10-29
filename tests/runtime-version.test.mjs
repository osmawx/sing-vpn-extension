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
