import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/extension/popup.js', import.meta.url), 'utf8');

/** Runs the real installer click handler with isolated clipboard and extension assets. */
async function prepareInstaller(clipboardAvailable) {
  const elements = {
    'install-sing': { disabled: false }, 'install-sing-message': { textContent: '' },
    'install-command-panel': { hidden: true }, 'sing-install-command': { value: '' },
  };
  let copied;
  const context = vm.createContext({
    elements,
    chrome: { runtime: { getURL: (name) => `chrome-extension://fake/${name}` } },
    fetch: async (url) => {
      assert.equal(url, 'chrome-extension://fake/install-command.txt');
      return { ok: true, text: async () => '/bin/bash -c \'fake verified installer\'' };
    },
    navigator: { clipboard: { writeText: async (command) => {
      if (!clipboardAvailable) { throw new Error('Clipboard unavailable'); }
      copied = command;
    } } },
  });
  const start = source.indexOf('async function copySingInstallCommand()');
  assert.ok(start >= 0, 'Install local sing must use the Terminal command flow');
  const end = source.indexOf('/** Rechecks the native host', start);
  vm.runInContext(source.slice(start, end), context);
  await context.copySingInstallCommand();
  return { elements, copied };
}

test('installer copies a Terminal command instead of downloading an executable', async () => {
  const result = await prepareInstaller(true);
  assert.equal(result.copied, result.elements['sing-install-command'].value);
  assert.equal(result.elements['install-command-panel'].hidden, false);
  assert.match(result.elements['install-sing-message'].textContent, /Paste it in Terminal/);
  assert.equal(result.elements['install-sing'].disabled, false);
});

test('installer retains a visible command when clipboard access is denied', async () => {
  const result = await prepareInstaller(false);
  assert.equal(result.copied, undefined);
  assert.ok(result.elements['sing-install-command'].value);
  assert.match(result.elements['install-sing-message'].textContent, /Copy the command below/);
});
