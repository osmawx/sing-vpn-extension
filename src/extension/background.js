// Service worker: хранит серверы, включает/выключает прокси браузера, отдаёт логин/пароль прокси.
import { buildProxyConfig, normalizeDomain, parseProxyList } from './proxy-links.js';

const HOST_NAME = 'com.singvpn.host';
// Локальный sing-box (команда `sing`) слушает mixed-инбаунд на 127.0.0.1:1080
const SING_PROXY = { scheme: 'socks5', host: '127.0.0.1', port: 1080 };

const BADGE_COLOR = '#2ea043';
const SUBSCRIPTION_TIMEOUT_MS = 15000;
const SUBSCRIPTION_MAX_CHARS = 2_000_000;
const OWN_CONTROL = 'controlled_by_this_extension';
// Запросы, на которые уже отдали логин/пароль: повторный 407 значит «пароль неверный»
const authAttemptedRequestIds = new Set();

/** Читает состояние из chrome.storage.local с значениями по умолчанию. */
async function readState() {
  const stored = await chrome.storage.local.get({
    servers: [], singServers: [], latencies: {}, exceptions: [], bypassRu: false, subscriptionUrl: '', connectedId: null, lastUsedId: null,
  });
  return stored;
}

/** Показывает на иконке «ON», пока VPN подключён. */
async function updateBadge(isConnected) {
  await chrome.action.setBadgeText({ text: isConnected ? 'ON' : '' });
  await chrome.action.setBadgeBackgroundColor({ color: BADGE_COLOR });
}

/**
 * Включает или снимает защиту от утечки реального IP через WebRTC (UDP мимо прокси).
 * Сбой не должен ломать подключение: политику может держать другое расширение.
 * @param {boolean} isProtected - true при подключении, false при отключении.
 */
async function setWebRtcProtection(isProtected) {
  try {
    if (isProtected) {
      await chrome.privacy.network.webRTCIPHandlingPolicy.set({ value: 'disable_non_proxied_udp' });
    } else {
      await chrome.privacy.network.webRTCIPHandlingPolicy.clear({});
    }
  } catch (error) {
    console.warn('WebRTC policy not changed:', error.message);
  }
}

/**
 * Подключается к серверу из списка.
 * @param {string} serverId - id сервера.
 * @returns {Promise<object>} {ok, connectedId} либо {ok: false, error}.
 */
async function connect(serverId) {
  const { servers, singServers, exceptions, bypassRu } = await readState();
  const server = [...singServers, ...servers].find((item) => item.id === serverId);
  if (!server) {
    return { ok: false, error: 'server not found' };
  }
  if (server.singName) {
    // Сервер локального sing: sing переключает сервер и поднимает sing-box
    const hostResult = await callHost({ action: 'connect', name: server.singName });
    if (!hostResult.ok) {
      return hostResult;
    }
  }
  await chrome.proxy.settings.set({ scope: 'regular', value: buildProxyConfig(server, exceptions, bypassRu) });
  // Другое расширение или политика может перехватить управление прокси
  const { levelOfControl } = await chrome.proxy.settings.get({});
  if (levelOfControl !== OWN_CONTROL) {
    return { ok: false, error: 'Proxy is controlled by another extension or policy' };
  }
  await chrome.storage.local.set({ connectedId: server.id, lastUsedId: server.id });
  await setWebRtcProtection(true);
  await updateBadge(true);
  return { ok: true, connectedId: server.id };
}

/**
 * Отправляет одно сообщение native host.
 * @param {object} payload - тело сообщения с полем action.
 * @returns {Promise<object>} ответ host либо {ok: false, error, hostMissing}.
 */
function callHost(payload) {
  return new Promise((resolve) => {
    chrome.runtime.sendNativeMessage(HOST_NAME, payload, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, hostMissing: true, error: chrome.runtime.lastError.message });
        return;
      }
      if (response?.singMissing) {
        // host есть, а sing не установлен: для расширения это тот же режим «только браузер»
        resolve({ ...response, hostMissing: true });
        return;
      }
      resolve(response ?? { ok: false, error: 'empty response from host' });
    });
  });
}

/**
 * Превращает локацию из `sing select` в запись сервера, ведущего на локальный sing.
 * @param {object} location - элемент списка от host.
 */
function singLocationToServer(location, subscriptionLabel) {
  return {
    id: `sing:${location.name}`,
    name: location.name,
    flag: location.flag,
    city: location.city,
    country: location.country,
    section: location.group === 'custom'
      ? 'My proxies (sing)'
      : `Subscription · ${subscriptionLabel || 'sing'}`,
    singName: location.name,
    username: '',
    password: '',
    ...SING_PROXY,
  };
}

/** Отключает недоступный sing, сохраняя кеш локаций до восстановления host. */
async function disconnectFromMissingSingHost() {
  const { connectedId = null } = await chrome.storage.local.get(['connectedId']);
  if (String(connectedId).startsWith('sing:')) {
    await disconnect();
  }
}

/** Загружает список серверов локального sing и кеширует его. */
async function refreshSing() {
  const result = await callHost({ action: 'list' });
  if (!result.ok) {
    if (result.hostMissing) {
      await disconnectFromMissingSingHost();
    }
    return result;
  }
  const singServers = result.locations.map((location) => singLocationToServer(location, result.subscriptionLabel));
  await chrome.storage.local.set({ singServers });
  return { ok: true, count: singServers.length, current: result.current, warning: result.warning ?? '' };
}

/** Возвращает прямое соединение. */
async function disconnect() {
  await chrome.proxy.settings.clear({ scope: 'regular' });
  await chrome.storage.local.set({ connectedId: null });
  await setWebRtcProtection(false);
  await updateBadge(false);
  return { ok: true, connectedId: null };
}

/**
 * Скачивает подписку и возвращает подходящие серверы.
 * @param {string} subscriptionUrl - https-адрес подписки.
 */
async function fetchSubscription(subscriptionUrl) {
  const response = await fetch(subscriptionUrl, {
    cache: 'no-store', signal: AbortSignal.timeout(SUBSCRIPTION_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`subscription HTTP ${response.status}`);
  }
  const text = await response.text();
  if (text.length > SUBSCRIPTION_MAX_CHARS) {
    throw new Error('subscription is too large');
  }
  return parseProxyList(text);
}

/**
 * Добавляет серверы из вставленного текста и/или подписки.
 * Ошибка подписки не отменяет сохранение вставленных ссылок.
 * @param {{text: string, subscriptionUrl: string}} input - ввод из popup.
 * @returns {Promise<object>} {ok, added, skipped, warning?}.
 */
async function importServers({ text, subscriptionUrl }) {
  const incoming = [{ ...parseProxyList(text || ''), section: 'Added in browser' }];
  let warning = '';
  if (subscriptionUrl) {
    if (!/^https:\/\//i.test(subscriptionUrl)) {
      return { ok: false, error: 'subscription URL must start with https://' };
    }
    try {
      const subscription = await fetchSubscription(subscriptionUrl);
      incoming.push({ ...subscription, section: `Subscription · ${new URL(subscriptionUrl).hostname.split('.').slice(-2).join('.')}` });
    } catch (error) {
      warning = `Subscription failed: ${error.message}`;
    }
  }
  // Состояние читаем после сетевого ожидания, чтобы не затереть параллельное удаление
  const state = await readState();
  const merged = new Map(state.servers.map((server) => [server.id, server]));
  const skipped = [];
  let added = 0;
  for (const source of incoming) {
    for (const server of source.servers) {
      if (!merged.has(server.id)) {
        added += 1;
      }
      merged.set(server.id, { ...server, section: source.section });
    }
    skipped.push(...source.skipped);
  }
  await chrome.storage.local.set({ servers: [...merged.values()], subscriptionUrl: subscriptionUrl || '' });
  return { ok: true, added, skipped, warning };
}

/** Отключается и удаляет все серверы. */
async function forgetAll() {
  await disconnect();
  await chrome.storage.local.set({ servers: [], lastUsedId: null });
  return { ok: true };
}

/** Переприменяет правила прокси к подключённому серверу (sing не трогаем). */
async function reapplyProxy() {
  const { connectedId, servers, singServers, exceptions, bypassRu } = await readState();
  const connectedServer = [...singServers, ...servers].find((item) => item.id === connectedId);
  if (connectedServer) {
    await chrome.proxy.settings.set({
      scope: 'regular', value: buildProxyConfig(connectedServer, exceptions, bypassRu),
    });
  }
}

/**
 * Сохраняет исключения локально, отправляет их в sing и применяет к прокси браузера.
 * Если host не установлен, исключения работают только в браузере.
 * @param {{exceptions: string[], bypassRu: boolean}} next - новое состояние.
 */
async function saveExceptions({ exceptions, bypassRu }) {
  await chrome.storage.local.set({ exceptions, bypassRu });
  await reapplyProxy();
  const hostResult = await callHost({ action: 'exceptions_set', domains: exceptions, bypassRu });
  if (!hostResult.ok && !hostResult.hostMissing) {
    return { ok: true, exceptions, bypassRu, warning: `sing: ${hostResult.error}` };
  }
  return { ok: true, exceptions, bypassRu, synced: hostResult.ok };
}

/**
 * Подтягивает исключения из sing (источник истины), если host доступен.
 * @returns {Promise<object>} {ok, synced}.
 */
async function syncExceptions() {
  const hostResult = await callHost({ action: 'exceptions_get' });
  if (hostResult.ok) {
    await chrome.storage.local.set({ exceptions: hostResult.domains, bypassRu: hostResult.bypassRu });
    await reapplyProxy();
    return { ok: true, synced: true };
  }
  return { ok: true, synced: false };
}

/**
 * Добавляет домен в исключения (сайт будет открываться без VPN).
 * @param {string} input - домен или URL.
 */
async function addException(input) {
  const domain = normalizeDomain(input);
  if (!domain) {
    return { ok: false, error: 'Enter a domain like example.com' };
  }
  const { exceptions, bypassRu } = await readState();
  return exceptions.includes(domain)
    ? { ok: true, exceptions, bypassRu }
    : saveExceptions({ exceptions: [...exceptions, domain], bypassRu });
}

/** Убирает домен из исключений. */
async function removeException(domain) {
  const { exceptions, bypassRu } = await readState();
  return saveExceptions({ exceptions: exceptions.filter((item) => item !== domain), bypassRu });
}

/** Включает/выключает «все сайты .ru, .su и .рф без VPN». */
async function setBypassRu(enabled) {
  const { exceptions } = await readState();
  return saveExceptions({ exceptions, bypassRu: Boolean(enabled) });
}

/** Удаляет сервер; если он подключён — сначала отключается. */
async function removeServer(serverId) {
  const state = await readState();
  if (state.connectedId === serverId) {
    await disconnect();
  }
  await chrome.storage.local.set({ servers: state.servers.filter((item) => item.id !== serverId) });
  return { ok: true };
}

/** Приводит значок и прокси в порядок после старта браузера. */
async function syncBadge() {
  const { connectedId } = await readState();
  const { levelOfControl } = await chrome.proxy.settings.get({});
  // Прокси могли снять или перехватить: тогда «Connected» было бы ложью
  if (connectedId && levelOfControl !== OWN_CONTROL) {
    await chrome.storage.local.set({ connectedId: null });
    await updateBadge(false);
    return;
  }
  await updateBadge(Boolean(connectedId));
}

const MESSAGE_HANDLERS = {
  connect: (message) => connect(message.serverId),
  disconnect: () => disconnect(),
  import: (message) => importServers(message),
  remove: (message) => removeServer(message.serverId),
  forgetAll: () => forgetAll(),
  refreshSing: () => refreshSing(),
  updateExtension: () => callHost({ action: 'update' }),
  addException: (message) => addException(message.domain),
  removeException: (message) => removeException(message.domain),
  setBypassRu: (message) => setBypassRu(message.enabled),
  syncExceptions: () => syncExceptions(),
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Принимаем сообщения только от собственных страниц расширения
  if (sender.id !== chrome.runtime.id) {
    return false;
  }
  const handler = MESSAGE_HANDLERS[message?.type];
  if (!handler) {
    sendResponse({ ok: false, error: 'unknown message type' });
    return false;
  }
  handler(message).then(sendResponse, (error) => sendResponse({ ok: false, error: error.message }));
  return true; // ответ асинхронный
});

// Логин/пароль для HTTP(S)-прокси: отвечаем только на запросы самого прокси
// и только пока он управляется этим расширением.
chrome.webRequest.onAuthRequired.addListener(
  (details, respond) => {
    // Повторный 407 на тот же запрос = неверный пароль: не зацикливаемся
    if (!details.isProxy || authAttemptedRequestIds.has(details.requestId)) {
      respond({});
      return;
    }
    readState().then(({ servers, connectedId }) => {
      const server = servers.find((item) => item.id === connectedId);
      // Пароль отдаём только самому прокси: совпадают и хост, и порт
      const matchesChallenger = server && details.challenger?.host === server.host
        && Number(details.challenger?.port) === Number(server.port);
      if (!matchesChallenger || !server.username) {
        respond({});
        return;
      }
      authAttemptedRequestIds.add(details.requestId);
      respond({ authCredentials: { username: server.username, password: server.password } });
    }).catch(() => respond({}));
  },
  { urls: ['<all_urls>'] },
  ['asyncBlocking'],
);

const forgetRequest = (details) => authAttemptedRequestIds.delete(details.requestId);
chrome.webRequest.onCompleted.addListener(forgetRequest, { urls: ['<all_urls>'] });
chrome.webRequest.onErrorOccurred.addListener(forgetRequest, { urls: ['<all_urls>'] });

chrome.runtime.onStartup.addListener(syncBadge);
chrome.runtime.onInstalled.addListener(syncBadge);
