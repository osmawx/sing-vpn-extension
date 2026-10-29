import assert from 'node:assert/strict';
import { test } from 'node:test';

test('temporary host failure keeps cached sing locations', async () => {
  const cachedLocation = { id: 'sing:Example', singName: 'Example', scheme: 'socks5', host: '127.0.0.1', port: 1080 };
  const storage = { servers: [], singServers: [cachedLocation], connectedId: cachedLocation.id };
  let messageListener;
  let proxyClears = 0;
  const startupListeners = [];
  const addListener = () => {};

  globalThis.chrome = {
    runtime: {
      id: 'test-extension',
      onMessage: { addListener: (listener) => { messageListener = listener; } },
      onStartup: { addListener: (listener) => startupListeners.push(listener) },
      onInstalled: { addListener },
      sendNativeMessage: (_name, _message, reply) => {
        if (_message.action === 'check_update') {
          reply({ ok: true, available: true });
          return;
        }
        chrome.runtime.lastError = { message: 'Native host not found' };
        reply(undefined);
        delete chrome.runtime.lastError;
      },
    },
    storage: { local: {
      get: async (keys) => Array.isArray(keys)
        ? Object.fromEntries(keys.map((key) => [key, storage[key]]))
        : { ...keys, ...storage },
      set: async (changes) => Object.assign(storage, changes),
    } },
    proxy: { settings: { clear: async () => { proxyClears += 1; } } },
    privacy: { network: { webRTCIPHandlingPolicy: { clear: async () => {} } } },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
    webRequest: {
      onAuthRequired: { addListener }, onCompleted: { addListener }, onErrorOccurred: { addListener },
    },
  };

  try {
    await import('../src/extension/background.js');
    const response = await new Promise((resolve) => {
      messageListener({ type: 'refreshSing' }, { id: chrome.runtime.id }, resolve);
    });

    assert.equal(response.hostMissing, true);
    assert.deepEqual(storage.singServers, [cachedLocation]);
    assert.equal(storage.connectedId, null);
    assert.equal(proxyClears, 1);
    await startupListeners[1]();
    assert.deepEqual(storage.extensionUpdate, { ok: true, available: true });
  } finally {
    delete globalThis.chrome;
  }
});
