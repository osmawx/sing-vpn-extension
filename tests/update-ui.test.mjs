import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/extension/popup.js', import.meta.url), 'utf8');
const start = source.indexOf('async function updateExtension()');
const end = source.indexOf("elements['update-extension'].addEventListener", start);

test('update failures always restore the button and show the error', async () => {
  for (const throws of [false, true]) {
    const elements = { 'update-extension': {}, 'update-message': {}, 'update-target': { value: '' } };
    const context = vm.createContext({ elements, send: async () => {}, requestExtensionUpdate: async () => {
      if (throws) { throw new Error('fake updater error'); }
      return { ok: false, error: 'fake timeout' };
    } });
    vm.runInContext(source.slice(start, end), context);
    await context.updateExtension();
    assert.equal(elements['update-extension'].disabled, false);
    assert.equal(elements['update-message'].className, 'error');
    assert.match(elements['update-message'].textContent, /fake/);
  }
});
