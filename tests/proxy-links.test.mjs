// Запуск: node --test tests/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  buildProxyConfig, normalizeDomain, parseProxyLink, parseProxyList, splitLocationName,
} from '../extension/proxy-links.js';

test('splitLocationName extracts flag, city and country', () => {
  const parts = splitLocationName('🇱🇹 Вильнюс, Литва, Extra');

  assert.deepEqual(parts, { flag: '🇱🇹', city: 'Вильнюс', country: 'Литва' });
});

test('parseProxyLink parses https proxy with credentials and name', () => {
  const { server } = parseProxyLink('https://user:p%40ss@proxy.example.com:8443#🇩🇪 Берлин, Германия');

  assert.equal(server.scheme, 'https');
  assert.equal(server.host, 'proxy.example.com');
  assert.equal(server.port, 8443);
  assert.equal(server.password, 'p@ss');
  assert.equal(server.city, 'Берлин');
});

test('parseProxyLink accepts sing colon format for http', () => {
  const { server } = parseProxyLink('http://1.2.3.4:3128:login:secret#Home');

  assert.equal(server.host, '1.2.3.4');
  assert.equal(server.username, 'login');
  assert.equal(server.name, 'Home');
});

test('parseProxyLink accepts socks5 without credentials', () => {
  const { server } = parseProxyLink('socks5://1.2.3.4:1080');

  assert.equal(server.scheme, 'socks5');
  assert.equal(server.port, 1080);
});

test('parseProxyLink rejects socks5 with credentials', () => {
  const { error } = parseProxyLink('socks5://u:p@1.2.3.4:1080');

  assert.match(error, /SOCKS/);
});

test('parseProxyLink rejects vless and garbage', () => {
  assert.match(parseProxyLink('vless://abc@host:443').error, /not supported/);
  assert.equal(parseProxyLink('not a link').error, 'invalid link');
});

test('parseProxyList reads base64 subscriptions and hides secrets in skipped', () => {
  const plain = 'https://a:b@h1.example.com:443#One\nvless://secret@h2:443\nhttp://h3:80';
  const result = parseProxyList(Buffer.from(plain).toString('base64'));

  assert.equal(result.servers.length, 2);
  assert.deepEqual(result.skipped.map((item) => item.link), ['vless://…']);
});

test('parseProxyList keeps good links when one has a malformed escape', () => {
  const result = parseProxyList('http://u:p%zz@h:80\nhttp://good:80');

  assert.equal(result.servers.length, 1);
  assert.equal(result.skipped.length, 1);
});

test('parseProxyList decodes UTF-8 names in base64 subscriptions', () => {
  const plain = 'https://a:b@h1.example.com:443#🇱🇹 Вильнюс, Литва, Extra';
  const result = parseProxyList(Buffer.from(plain, 'utf8').toString('base64'));

  assert.equal(result.servers[0].city, 'Вильнюс');
  assert.equal(result.servers[0].flag, '🇱🇹');
});

test('parseProxyLink strips brackets from IPv6 hosts', () => {
  const { server } = parseProxyLink('http://[2001:db8::1]:3128');

  assert.equal(server.host, '2001:db8::1');
});

test('parseProxyList removes duplicates', () => {
  const result = parseProxyList('http://h:80\nhttp://h:80');

  assert.equal(result.servers.length, 1);
});

test('buildProxyConfig produces fixed_servers rules', () => {
  const config = buildProxyConfig({ scheme: 'https', host: 'h', port: 443 });

  assert.equal(config.mode, 'fixed_servers');
  assert.deepEqual(config.rules.singleProxy, { scheme: 'https', host: 'h', port: 443 });
});

test('normalizeDomain cleans URLs, wildcards and ports', () => {
  assert.equal(normalizeDomain('https://www.Example.com:8443/path?q=1'), 'www.example.com');
  assert.equal(normalizeDomain('*.example.com'), 'example.com');
  assert.equal(normalizeDomain(' example.co.uk. '), 'example.co.uk');
});

test('normalizeDomain rejects non-domains', () => {
  for (const bad of ['', 'localhost', 'not a domain', 'http://', '1.2.3.4', 'a_b.com', null]) {
    assert.equal(normalizeDomain(bad), null, String(bad));
  }
});

test('buildProxyConfig adds exceptions with subdomain wildcard', () => {
  const config = buildProxyConfig({ scheme: 'http', host: 'h', port: 1 }, ['example.com']);

  assert.ok(config.rules.bypassList.includes('example.com'));
  assert.ok(config.rules.bypassList.includes('*.example.com'));
  assert.ok(config.rules.bypassList.includes('localhost'));
});

test('buildProxyConfig adds RU zones when bypassRu is on', () => {
  const rules = buildProxyConfig({ scheme: 'http', host: 'h', port: 1 }, [], true).rules.bypassList;

  assert.ok(['*.ru', '*.su', '*.xn--p1ai'].every((rule) => rules.includes(rule)));
  assert.ok(!buildProxyConfig({ scheme: 'http', host: 'h', port: 1 }).rules.bypassList.includes('*.ru'));
});

test('normalizeDomain accepts punycode TLD', () => {
  assert.equal(normalizeDomain('xn--e1afmkfd.xn--p1ai'), 'xn--e1afmkfd.xn--p1ai');
});
