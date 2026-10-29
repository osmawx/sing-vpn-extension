// Разбор ссылок на прокси и подписок. Чистые функции без обращения к chrome.*.

/** Схемы, которые браузер умеет использовать как прокси. */
export const SUPPORTED_SCHEMES = ['http', 'https', 'socks5', 'socks'];
const FLAG_PATTERN = /^([\u{1F1E6}-\u{1F1FF}]{2})\s*(.*)$/u;
const DEFAULT_PORTS = { http: 80, https: 443, socks5: 1080, socks: 1080 };

/**
 * Разбирает «🇱🇹 Вильнюс, Литва, Extra» на флаг, город и страну.
 * @param {string} name - отображаемое имя сервера.
 * @returns {{flag: string, city: string, country: string}}
 */
export function splitLocationName(name) {
  let rest = name.trim();
  let flag = '';
  const flagMatch = FLAG_PATTERN.exec(rest);
  if (flagMatch) {
    [, flag, rest] = flagMatch;
  }
  const parts = rest.split(',').map((part) => part.trim());
  return { flag, city: parts[0] || rest, country: parts[1] || '' };
}

/**
 * Превращает «socks5://host:port:login:password» (формат sing) в обычный URL.
 * @param {string} link - исходная ссылка.
 * @returns {string} ссылка в виде scheme://login:password@host:port.
 */
function normalizeColonLink(link) {
  const hashIndex = link.indexOf('#');
  const mainPart = hashIndex === -1 ? link : link.slice(0, hashIndex);
  const fragment = hashIndex === -1 ? undefined : link.slice(hashIndex + 1);
  const match = /^([a-z0-9]+):\/\/([^/@:]+):(\d+):([^:]+):(.+)$/i.exec(mainPart);
  if (!match) {
    return link;
  }
  const [, scheme, host, port, username, password] = match;
  const encodedAuth = `${encodeURIComponent(username)}:${encodeURIComponent(password)}`;
  const rebuilt = `${scheme}://${encodedAuth}@${host}:${port}`;
  return fragment === undefined ? rebuilt : `${rebuilt}#${fragment}`;
}

/**
 * Разбирает одну ссылку на прокси.
 * @param {string} rawLink - например socks5://user:pass@1.2.3.4:1080#Имя.
 * @returns {{server?: object, error?: string}} сервер либо причина отказа.
 */
export function parseProxyLink(rawLink) {
  const link = normalizeColonLink(rawLink.trim());
  let url;
  try {
    url = new URL(link);
  } catch {
    return { error: 'invalid link' };
  }
  const scheme = url.protocol.replace(':', '').toLowerCase();
  if (!SUPPORTED_SCHEMES.includes(scheme)) {
    return { error: `${scheme} is not supported in a browser` };
  }
  let username;
  let password;
  let name;
  try {
    username = decodeURIComponent(url.username);
    password = decodeURIComponent(url.password);
    name = decodeURIComponent(url.hash.replace(/^#/, ''));
  } catch {
    return { error: 'invalid link' };
  }
  // URL.hostname оставляет скобки у IPv6, а chrome.proxy и challenger.host их не используют
  const hostname = url.hostname.replace(/^\[|\]$/g, '');
  // Chrome не умеет логин/пароль для SOCKS: запрос аутентификации не доходит до расширения
  if (scheme.startsWith('socks') && (username || password)) {
    return { error: 'Chrome cannot authenticate SOCKS proxies (use http/https)' };
  }
  if (!hostname) {
    return { error: 'host is missing' };
  }
  name = name || hostname;
  const normalizedScheme = scheme === 'socks' ? 'socks5' : scheme;
  return {
    server: {
      id: `${normalizedScheme}://${username}@${hostname}:${url.port || DEFAULT_PORTS[scheme]}`,
      name,
      ...splitLocationName(name),
      scheme: normalizedScheme,
      host: hostname,
      port: Number(url.port) || DEFAULT_PORTS[scheme],
      username,
      password,
    },
  };
}

/**
 * Достаёт ссылки из текста: обычный список или base64 (формат подписки).
 * @param {string} text - содержимое подписки или вставленный пользователем текст.
 * @returns {string[]} непустые строки.
 */
export function extractLinks(text) {
  let content = text.trim();
  if (content && !content.includes('://')) {
    try {
      const binary = atob(content.replace(/-/g, '+').replace(/_/g, '/'));
      // atob даёт Latin-1; имена с кириллицей и флагами нужно декодировать как UTF-8
      content = new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)));
    } catch {
      // не base64 — оставляем как есть
    }
  }
  return content.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

/**
 * Разбирает текст со ссылками на список серверов; дубликаты по id убираются.
 * @param {string} text - ссылки по одной в строке или base64.
 * @returns {{servers: object[], skipped: {link: string, reason: string}[]}}
 */
export function parseProxyList(text) {
  const servers = new Map();
  const skipped = [];
  for (const link of extractLinks(text)) {
    const { server, error } = parseProxyLink(link);
    if (server) {
      servers.set(server.id, server);
    } else {
      // Секреты в отчёт не попадают: оставляем только схему и причину
      skipped.push({ link: `${link.split('://')[0]}://…`, reason: error });
    }
  }
  return { servers: [...servers.values()], skipped };
}

const DOMAIN_PATTERN = /^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+(xn--[a-z0-9-]{2,59}|[a-z]{2,63})$/;
const BASE_BYPASS_LIST = ['localhost', '127.0.0.1', '[::1]', '<local>'];
// Российские зоны; .рф в punycode, потому что Chrome сопоставляет ASCII-имя хоста
const RU_BYPASS_RULES = ['*.ru', '*.su', '*.xn--p1ai'];

/**
 * Приводит ввод (домен или URL) к чистому домену для списка исключений.
 * @param {string} input - например «https://www.Example.com/path», «*.example.com».
 * @returns {string|null} домен в нижнем регистре или null, если ввод не похож на домен.
 */
export function normalizeDomain(input) {
  let candidate = String(input ?? '').trim().toLowerCase();
  if (!candidate) {
    return null;
  }
  if (candidate.includes('://')) {
    try {
      candidate = new URL(candidate).hostname;
    } catch {
      return null;
    }
  }
  candidate = candidate.replace(/^\*?\./, '').split(/[/?#:]/)[0].replace(/\.$/, '');
  return DOMAIN_PATTERN.test(candidate) ? candidate : null;
}

/**
 * Строит значение настройки chrome.proxy для сервера.
 * Сайты из исключений идут напрямую: домен и все его поддомены.
 * @param {{scheme: string, host: string, port: number}} server - выбранный прокси.
 * @param {string[]} [exceptions] - домены, которые нужно открывать мимо VPN.
 * @param {boolean} [bypassRu] - открывать мимо VPN все сайты .ru, .su и .рф.
 * @returns {object} значение для chrome.proxy.settings.set.
 */
export function buildProxyConfig(server, exceptions = [], bypassRu = false) {
  const exceptionRules = exceptions.flatMap((domain) => [domain, `*.${domain}`]);
  return {
    mode: 'fixed_servers',
    rules: {
      singleProxy: { scheme: server.scheme, host: server.host, port: server.port },
      bypassList: [...BASE_BYPASS_LIST, ...(bypassRu ? RU_BYPASS_RULES : []), ...exceptionRules],
    },
  };
}
