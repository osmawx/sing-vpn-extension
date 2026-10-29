import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createConfiguration, parseConfiguration } from '../src/extension/configuration.js';

const browser = {
  servers: [{ name: 'Example', scheme: 'https', host: 'proxy.example.com', port: 443, username: 'test', password: 'fake' }],
  subscriptionUrl: 'https://example.com/subscription', exceptions: ['example.org'], bypassRu: true,
};
const sing = { subscriptionUrl: '', customLinks: [], exceptions: { domains: [], bypassRu: false } };

test('configuration round trip preserves credentials and excludes runtime state', () => {
  const exported = createConfiguration({ ...browser, connectedId: 'active', singServers: ['cache'] }, sing, '1.2.0');
  const restored = parseConfiguration(JSON.stringify(exported));
  assert.equal(restored.browser.servers[0].password, 'fake');
  assert.equal(restored.browser.servers[0].host, 'proxy.example.com');
  assert.equal(restored.browser.connectedId, undefined);
  assert.equal(restored.browser.singServers, undefined);
  assert.deepEqual(restored.sing, sing);
});

test('configuration rejects unknown format and invalid proxy before import', () => {
  assert.throws(() => parseConfiguration('{"format":"other"}'));
  const exported = createConfiguration(browser, sing, '1.2.0');
  exported.browser.servers[0].scheme = 'file';
  assert.throws(() => parseConfiguration(JSON.stringify(exported)), /proxy/);
});
