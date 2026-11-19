import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/extension/popup.js', import.meta.url), 'utf8');
const start = source.indexOf('async function checkSingInstallation()');
const end = source.indexOf("\nelements['install-sing'].addEventListener", start);

/** Runs the actual click handler with isolated status elements and host responses. */
async function checkInstallation(response) {
  const elements = { 'check-sing-installation': { disabled: false }, 'install-sing-message': { textContent: '' } };
  const context = vm.createContext({ elements, refreshSingList: async () => response });
  vm.runInContext(source.slice(start, end), context);
  const checking = context.checkSingInstallation();
  assert.equal(elements['check-sing-installation'].disabled, true);
  assert.equal(elements['install-sing-message'].textContent, 'Checking installation…');
  await checking;
  assert.equal(elements['check-sing-installation'].disabled, false);
  return elements['install-sing-message'].textContent;
}

test('installation check reports success in Settings even with zero locations', async () => {
  assert.equal(await checkInstallation({ ok: true, count: 0 }), 'Local sing is available. Locations: 0.');
});

test('installation check reports missing host and other failures in Settings', async () => {
  assert.match(await checkInstallation({ ok: false, hostMissing: true }), /unavailable in this browser/);
  assert.match(await checkInstallation({ ok: false }), /Export logs/);
});
