import { normalizeDomain, parseProxyLink } from './proxy-links.js';

export const MAX_CONFIGURATION_BYTES = 768 * 1024;

/** Проверяет строку, не включая её содержимое в сообщение ошибки. */
function checkedString(value, maximum = 10000) {
  if (typeof value !== 'string' || value.length > maximum || /[\r\n\0]/.test(value)) {
    throw new Error('Invalid configuration string.');
  }
  return value;
}

/** Восстанавливает сервер через общий парсер, исключая произвольные поля. */
function normalizeServer(value) {
  if (!value || !['http', 'https', 'socks5'].includes(value.scheme)
      || !Number.isInteger(value.port) || value.port < 1 || value.port > 65535) {
    throw new Error('Invalid proxy in configuration.');
  }
  const host = checkedString(value.host, 255);
  if (!host || /[\s/@?#\\]/.test(host)) {
    throw new Error('Invalid proxy host.');
  }
  const authority = host.includes(':') ? `[${host.replace(/^\[|\]$/g, '')}]` : host;
  const username = encodeURIComponent(checkedString(value.username ?? ''));
  const password = encodeURIComponent(checkedString(value.password ?? ''));
  const name = checkedString(value.name, 500);
  const { server } = parseProxyLink(`${value.scheme}://${username}:${password}@${authority}:${value.port}#${encodeURIComponent(name)}`);
  if (!server) {
    throw new Error('Invalid proxy in configuration.');
  }
  return { ...server, section: checkedString(value.section ?? 'Imported', 500) };
}

/** Проверяет переносимые настройки расширения без кеша и состояния подключения. */
function normalizeBrowser(value) {
  if (!value || !Array.isArray(value.servers) || value.servers.length > 1000
      || !Array.isArray(value.exceptions) || value.exceptions.length > 1000 || typeof value.bypassRu !== 'boolean') {
    throw new Error('Invalid browser configuration.');
  }
  const subscriptionUrl = checkedString(value.subscriptionUrl);
  if (subscriptionUrl && !/^https:\/\//i.test(subscriptionUrl)) {
    throw new Error('Subscription must use HTTPS.');
  }
  if (subscriptionUrl) {
    try { new URL(subscriptionUrl); } catch { throw new Error('Invalid subscription URL.'); }
  }
  const exceptions = value.exceptions.map((domain) => {
    const normalized = normalizeDomain(checkedString(domain, 255));
    if (!normalized) { throw new Error('Invalid exception domain.'); }
    return normalized;
  });
  return {
    servers: [...new Map(value.servers.map(normalizeServer).map((server) => [server.id, server])).values()],
    subscriptionUrl, exceptions: [...new Set(exceptions)], bypassRu: value.bypassRu,
  };
}

/** Читает и проверяет файл до любых изменений настроек. */
export function parseConfiguration(text) {
  if (typeof text !== 'string' || new TextEncoder().encode(text).length > MAX_CONFIGURATION_BYTES) {
    throw new Error('Configuration file is too large.');
  }
  let data;
  try { data = JSON.parse(text); } catch { throw new Error('Invalid configuration JSON.'); }
  if (!data || data.format !== 'sing-vpn' || data.schemaVersion !== 1 || !data.sing || typeof data.sing !== 'object') {
    throw new Error('Unsupported configuration format.');
  }
  return { format: 'sing-vpn', schemaVersion: 1, browser: normalizeBrowser(data.browser), sing: data.sing };
}

/** Собирает переносимый файл, явно исключая активное соединение и кеш. */
export function createConfiguration(browser, sing, appVersion) {
  const data = { format: 'sing-vpn', schemaVersion: 1, appVersion, browser: normalizeBrowser(browser), sing };
  parseConfiguration(JSON.stringify(data));
  return data;
}
