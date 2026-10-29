// UI popup: Home / Locations / Account. Вся логика подключения — в background.js.

import { normalizeDomain } from './proxy-links.js';

const FAST_SERVER_COUNT = 2;
const HOST_NAME = 'com.singvpn.host';
const LIVE_PING_INTERVAL_MS = 1000;
const LIVE_PING_TIMEOUT_MS = 3000;
const LIVE_PING_URL = 'https://cp.cloudflare.com/generate_204';
const LATENCY_HISTORY_SIZE = 3;
const GOOD_LATENCY_MS = 200;
const OK_LATENCY_MS = 400;
const IP_LOOKUP_URL = 'https://ipwho.is/';
const IP_LOOKUP_TIMEOUT_MS = 6000;
const IP_LOOKUP_ATTEMPTS = 3;
const IP_LOOKUP_RETRY_DELAY_MS = 1500;

const elements = Object.fromEntries(
  [...document.querySelectorAll('[id]')].map((node) => [node.id, node]),
);

let latencyHistory = {};
let liveLatency = null;
let state = { servers: [], singServers: [], latencies: {}, exceptions: [], bypassRu: false, connectedId: null, lastUsedId: null };

/**
 * Отправляет сообщение в background и возвращает ответ.
 * @param {object} message - сообщение с полем type.
 */
async function send(message) {
  try {
    return (await chrome.runtime.sendMessage(message)) ?? { ok: false, error: 'no response' };
  } catch (error) {
    return { ok: false, error: error.message };
  }
}

/** Перечитывает состояние из storage. */
async function loadState() {
  state = await chrome.storage.local.get({
    servers: [], singServers: [], latencies: {}, exceptions: [], bypassRu: false, connectedId: null, lastUsedId: null, subscriptionUrl: '',
  });
}

/**
 * Находит сервер по id.
 * @param {string|null} serverId - id сервера.
 */
function findServer(serverId) {
  return allServers().find((server) => server.id === serverId) ?? null;
}

/** Все серверы: сначала локального sing, затем добавленные вручную. */
function allServers() {
  return [...state.singServers, ...state.servers];
}

/**
 * Подпись сервера «Страна — Город» или имя, если страны нет.
 * @param {object} server - сервер из списка.
 */
function formatServerTitle(server) {
  return server.country ? `${server.country} — ${server.city}` : server.city;
}

/** Один запрос внешнего IP и страны; null при ошибке. */
async function lookupIpOnce() {
  const startedAt = performance.now();
  try {
    const response = await fetch(IP_LOOKUP_URL, {
      cache: 'no-store', signal: AbortSignal.timeout(IP_LOOKUP_TIMEOUT_MS),
    });
    const data = await response.json();
    return data.success
      ? { ip: data.ip, country: data.country, milliseconds: Math.round(performance.now() - startedAt) }
      : null;
  } catch {
    return null;
  }
}

/**
 * Определяет внешний IP с повторами: сразу после смены сервера туннель sing-box
 * ещё поднимается, и первые запросы могут не пройти.
 */
async function lookupIp() {
  for (let attempt = 0; attempt < IP_LOOKUP_ATTEMPTS; attempt += 1) {
    const info = await lookupIpOnce();
    if (info) {
      return info;
    }
    await new Promise((resolve) => setTimeout(resolve, IP_LOOKUP_RETRY_DELAY_MS));
  }
  return null;
}

/** Обновляет верхний баннер и вкладку Account по текущему внешнему IP. */
async function refreshIpInfo() {
  elements['ip-banner'].textContent = 'Checking IP…';
  const info = await lookupIp();
  const isConnected = Boolean(state.connectedId);
  elements['acc-ip'].textContent = info?.ip ?? '—';
  elements['acc-country'].textContent = info?.country ?? '—';
  elements['ip-banner'].classList.toggle('protected', isConnected && Boolean(info));
  if (!info) {
    elements['ip-banner'].textContent = isConnected
      ? 'Connected, but IP check failed' : 'IP check unavailable';
    return;
  }
  elements['ip-banner'].textContent = isConnected
    ? `Protected — ${info.ip} (${info.country})`
    : `Your IP is public — ${info.ip} (${info.country})`;
}

/**
 * Показывает на Home живую задержку текущего подключения.
 * @param {number|undefined} milliseconds - время ответа через прокси; undefined скрывает строку.
 */
function renderLiveLatency(milliseconds) {
  liveLatency = milliseconds ?? null;
  const info = describeLatency(milliseconds);
  elements['live-latency'].hidden = !info;
  elements['live-latency'].className = `live-latency ${info?.level ?? ''}`;
  elements['live-latency'].textContent = info ? `Latency ${info.text}` : '';
  updateConnectedRowLabel();
}

/** Синхронизирует подпись подключённого сервера в списке с живым значением. */
function updateConnectedRowLabel() {
  if (!state.connectedId) {
    return;
  }
  document.querySelectorAll('[data-latency-for]').forEach((label) => {
    if (label.dataset.latencyFor === state.connectedId) {
      const connectedInfo = describeLatency(displayLatency(state.connectedId));
      label.className = `ms ${connectedInfo?.level ?? ''}`;
      label.textContent = connectedInfo?.text ?? '';
    }
  });
}

/** Показывает ошибку на Home; пустая строка скрывает. */
function showError(text) {
  elements.error.hidden = !text;
  elements.error.textContent = text;
}

/** Перерисовывает Home и Account. */
function renderHome() {
  const isConnected = Boolean(state.connectedId);
  const shown = findServer(state.connectedId) ?? findServer(state.lastUsedId) ?? allServers()[0] ?? null;
  elements['home-flag'].textContent = shown?.flag ?? '';
  elements['home-location'].textContent = shown ? formatServerTitle(shown) : 'No servers — add in Locations';
  elements.power.classList.toggle('connected', isConnected);
  elements.status.textContent = isConnected ? 'Connected' : 'Not connected';
  elements['acc-count'].textContent = String(allServers().length);
  elements['acc-proxy'].textContent = findServer(state.connectedId)
    ? `${findServer(state.connectedId).scheme}://${findServer(state.connectedId).host}:${findServer(state.connectedId).port}`
    : '—';
}

/** Создаёт строку списка локаций. */
function buildLocationRow(server) {
  const row = document.createElement('li');
  row.className = server.id === state.connectedId ? 'current' : '';
  row.dataset.serverId = server.id;
  const flag = Object.assign(document.createElement('span'), { className: 'flag', textContent: server.flag });
  const label = document.createElement('span');
  label.className = 'label';
  label.textContent = formatServerTitle(server);
  const latencyInfo = describeLatency(displayLatency(server.id));
  const latencyLabel = Object.assign(document.createElement('span'), {
    className: `ms ${latencyInfo?.level ?? ''}`, textContent: latencyInfo?.text ?? '',
  });
  latencyLabel.dataset.latencyFor = server.id;
  const mark = Object.assign(document.createElement('span'), {
    className: 'check', textContent: server.id === state.connectedId ? '✓' : '',
  });
  const removeButton = Object.assign(document.createElement('button'), {
    className: 'remove', type: 'button', textContent: '✕', title: 'Remove',
  });
  removeButton.hidden = Boolean(server.singName);
  removeButton.addEventListener('click', async (event) => {
    event.stopPropagation();
    await send({ type: 'remove', serverId: server.id });
    await refreshAll();
  });
  row.addEventListener('click', () => connectTo(server.id));
  row.append(flag, label, latencyLabel, mark, removeButton);
  return row;
}

/**
 * Группирует серверы по разделам (мои / подписки) в порядке появления.
 * @param {object[]} servers - видимые серверы.
 * @returns {HTMLElement[]} заголовки разделов и строки серверов.
 */
function buildSectionedRows(servers) {
  const sections = new Map();
  for (const server of servers) {
    const title = server.section ?? 'My proxies';
    sections.set(title, [...(sections.get(title) ?? []), server]);
  }
  return [...sections].flatMap(([title, sectionServers]) => [
    Object.assign(document.createElement('li'), { className: 'section', textContent: title }),
    ...sectionServers.map(buildLocationRow),
  ]);
}

/** Перерисовывает список локаций с учётом поиска. */
function renderLocations() {
  const query = elements.search.value.trim().toLowerCase();
  const visible = allServers().filter((server) => server.name.toLowerCase().includes(query));
  elements['location-list'].replaceChildren(
    ...(visible.length
      ? buildSectionedRows(visible)
      : [Object.assign(document.createElement('li'), {
        className: 'empty', textContent: allServers().length ? 'Nothing found' : 'Press + to add servers',
      })]),
  );
}

/**
 * Подпись задержки и цветовой класс: быстрее 200 мс — зелёный, до 400 — жёлтый, дальше — красный.
 * @param {number|null|undefined} milliseconds - задержка; null, если сервер не ответил.
 * @returns {{text: string, level: string}|null} null, если замера ещё нет.
 */
function describeLatency(milliseconds) {
  if (milliseconds === undefined) {
    return null;
  }
  if (!Number.isFinite(milliseconds)) {
    return { text: '—', level: 'slow' };
  }
  const level = milliseconds < GOOD_LATENCY_MS ? 'good' : milliseconds < OK_LATENCY_MS ? 'ok' : 'slow';
  return { text: `${milliseconds} ms`, level };
}

/**
 * Задержка для показа: у подключённого сервера — живое значение (то же, что на главной),
 * у остальных — замер host.
 * @param {string} serverId - id сервера.
 */
function displayLatency(serverId) {
  if (serverId === state.connectedId && Number.isFinite(liveLatency)) {
    return liveLatency;
  }
  return state.latencies[serverId];
}

/**
 * Сглаживает замеры host: берёт минимум из последних раундов, чтобы разовая нагрузка
 * (параллельные пробы, холодное соединение) не раздувала число.
 * @param {Object<string, number|null>} latenciesById - свежий раунд замера.
 */
function mergeLatencyRound(latenciesById) {
  const merged = {};
  for (const [serverId, milliseconds] of Object.entries(latenciesById)) {
    const history = [...(latencyHistory[serverId] ?? []), milliseconds].slice(-LATENCY_HISTORY_SIZE);
    latencyHistory = { ...latencyHistory, [serverId]: history };
    const finiteValues = history.filter(Number.isFinite);
    merged[serverId] = finiteValues.length ? Math.min(...finiteValues) : null;
  }
  state.latencies = merged;
}

/** Создаёт карточку быстрого подключения: сервер и задержка. */
function buildFastCard(server) {
  const card = document.createElement('button');
  card.type = 'button';
  card.className = `card fast-card${server.id === state.connectedId ? ' current' : ''}`;
  const bolt = Object.assign(document.createElement('span'), { className: 'bolt', textContent: '⚡' });
  const name = Object.assign(document.createElement('span'), {
    className: 'fast-name', textContent: `${server.flag} ${formatServerTitle(server)}`.trim(),
  });
  const latency = Object.assign(document.createElement('span'), {
    className: 'muted', textContent: `${displayLatency(server.id)} ms`,
  });
  card.append(bolt, name, latency);
  card.addEventListener('click', () => connectTo(server.id));
  return card;
}

/** Показывает два самых быстрых сервера по замеру задержки. */
function renderFastList(isMeasuring = false) {
  const fastest = state.singServers
    .filter((server) => Number.isFinite(state.latencies[server.id]))
    .sort((first, second) => state.latencies[first.id] - state.latencies[second.id])
    .slice(0, FAST_SERVER_COUNT);
  if (fastest.length) {
    elements['fast-list'].replaceChildren(...fastest.map(buildFastCard));
    return;
  }
  const note = Object.assign(document.createElement('p'), {
    className: 'muted fast-note', textContent: isMeasuring ? 'Measuring speed…' : '',
  });
  elements['fast-list'].replaceChildren(note);
}

/** Обновляет подписи задержки в списке на месте, не пересобирая его (сохраняется прокрутка). */
function updateLatencyLabels() {
  document.querySelectorAll('[data-latency-for]').forEach((label) => {
    const info = describeLatency(displayLatency(label.dataset.latencyFor));
    label.className = `ms ${info?.level ?? ''}`;
    label.textContent = info?.text ?? '';
  });
  renderFastList();
}

/**
 * Запускает непрерывный замер серверов sing: host шлёт новый раунд каждые несколько секунд,
 * пока попап открыт. Закрытие попапа закрывает порт, и host гасит временный sing-box.
 */
function startLatencyStream() {
  renderFastList(true);
  const port = chrome.runtime.connectNative(HOST_NAME);
  port.onMessage.addListener((message) => {
    if (!message.ok) {
      return;
    }
    mergeLatencyRound(Object.fromEntries(
      Object.entries(message.latencies).map(([name, milliseconds]) => [`sing:${name}`, milliseconds]),
    ));
    updateLatencyLabels();
  });
  port.onDisconnect.addListener(() => void chrome.runtime.lastError);
  port.postMessage({ action: 'latency_stream' });
}

let livePingInFlight = false;

/** Раз в секунду мерит задержку текущего подключения (маленький запрос через прокси). */
async function pingConnection() {
  if (livePingInFlight) {
    return;
  }
  if (!state.connectedId) {
    renderLiveLatency(undefined);
    return;
  }
  livePingInFlight = true;
  const startedAt = performance.now();
  try {
    await fetch(LIVE_PING_URL, {
      mode: 'no-cors', cache: 'no-store', signal: AbortSignal.timeout(LIVE_PING_TIMEOUT_MS),
    });
    renderLiveLatency(Math.round(performance.now() - startedAt));
  } catch {
    renderLiveLatency(null);
  } finally {
    livePingInFlight = false;
  }
}

/** Перерисовывает список исключений. */
function renderExceptions() {
  elements['bypass-ru'].checked = state.bypassRu;
  elements['exception-list'].replaceChildren(...state.exceptions.map((domain) => {
    const row = document.createElement('li');
    const label = Object.assign(document.createElement('span'), { textContent: domain });
    const removeButton = Object.assign(document.createElement('button'), {
      type: 'button', textContent: '✕', title: 'Remove',
    });
    removeButton.addEventListener('click', async () => {
      await send({ type: 'removeException', domain });
      await refreshAll();
    });
    row.append(label, removeButton);
    return row;
  }));
}

/**
 * Добавляет домен в исключения и показывает ошибку, если ввод неверный.
 * @param {string} input - домен или URL.
 */
async function submitException(input) {
  const result = await send({ type: 'addException', domain: input });
  elements['exception-message'].hidden = result.ok;
  elements['exception-message'].textContent = result.ok ? '' : result.error;
  if (result.ok) {
    elements['exception-input'].value = '';
    await refreshAll();
  }
}

/** Добавляет в исключения сайт активной вкладки. */
async function addCurrentSite() {
  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const domain = normalizeDomain(activeTab?.url ?? '');
  await submitException(domain ?? '');
}

/** Полная перерисовка. */
function renderAll() {
  renderHome();
  renderLocations();
  renderExceptions();
  renderFastList();
}

/** Перечитывает состояние и обновляет экран. */
async function refreshAll() {
  await loadState();
  renderAll();
}

/**
 * Подключается к серверу и обновляет экран.
 * @param {string} serverId - id сервера.
 */
async function connectTo(serverId) {
  showError('');
  elements.power.classList.add('busy');
  const result = await send({ type: 'connect', serverId });
  elements.power.classList.remove('busy');
  if (!result.ok) {
    showError(result.error);
  }
  switchView('home');
  await refreshAll();
  await refreshIpInfo();
}

/** Кнопка питания: отключить либо подключить последний/первый сервер. */
async function togglePower() {
  if (state.connectedId) {
    elements.power.classList.add('busy');
    await send({ type: 'disconnect' });
    elements.power.classList.remove('busy');
    await refreshAll();
    await refreshIpInfo();
    return;
  }
  const target = findServer(state.lastUsedId) ?? allServers()[0];
  if (!target) {
    showError('Add a server in Locations first');
    return;
  }
  await connectTo(target.id);
}

/**
 * Переключает вкладку.
 * @param {string} viewName - home | locations | account.
 */
function switchView(viewName) {
  document.querySelectorAll('.view').forEach((view) => {
    view.hidden = view.id !== `view-${viewName}`;
  });
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.view === viewName);
  });
}

/** Обработчик формы добавления серверов. */
async function handleAddSubmit(event) {
  event.preventDefault();
  const result = await send({
    type: 'import',
    text: elements['add-links'].value,
    subscriptionUrl: elements['add-subscription'].value.trim(),
  });
  elements['add-message'].hidden = false;
  if (!result.ok) {
    elements['add-message'].textContent = result.error;
    return;
  }
  const skippedNote = result.skipped.length
    ? ` Skipped ${result.skipped.length}: ${[...new Set(result.skipped.map((item) => item.reason))].join('; ')}.`
    : '';
  elements['add-message'].textContent = `Added ${result.added}.${skippedNote} ${result.warning}`.trim();
  elements['add-links'].value = '';
  await refreshAll();
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => switchView(tab.dataset.view));
});
elements.power.addEventListener('click', togglePower);
elements['location-card'].addEventListener('click', () => switchView('locations'));
elements.search.addEventListener('input', renderLocations);
elements['add-toggle'].addEventListener('click', () => {
  elements['add-panel'].hidden = !elements['add-panel'].hidden;
  elements['add-message'].hidden = true;
});
elements['add-panel'].addEventListener('submit', handleAddSubmit);
elements['exception-form'].addEventListener('submit', (event) => {
  event.preventDefault();
  submitException(elements['exception-input'].value);
});
elements['bypass-ru'].addEventListener('change', async () => {
  await send({ type: 'setBypassRu', enabled: elements['bypass-ru'].checked });
  await refreshAll();
});
elements['exception-current'].addEventListener('click', addCurrentSite);
elements['forget-all'].addEventListener('click', async () => {
  await send({ type: 'forgetAll' });
  await refreshAll();
  await refreshIpInfo();
});

/** Подтягивает список локального sing; без host показывает подсказку. */
async function refreshSingList() {
  const result = await send({ type: 'refreshSing' });
  if (result.ok) {
    elements['list-note'].hidden = !result.warning;
    elements['list-note'].textContent = result.warning ? `Subscription: ${result.warning}` : '';
    await refreshAll();
    startLatencyStream();
    return;
  }
  if (result.hostMissing) {
    // Режим без sing: это не ошибка, просто работают только http/https/socks5 без логина
    elements['list-note'].hidden = false;
    elements['list-note'].textContent = 'Browser-only mode. For VLESS/WireGuard and your sing servers, run ./install.sh and reload.';
    await refreshAll();
  }
}

(async () => {
  await loadState();
  elements['add-subscription'].value = state.subscriptionUrl ?? '';
  renderAll();
  refreshSingList();
  send({ type: 'syncExceptions' }).then(refreshAll);
  setInterval(pingConnection, LIVE_PING_INTERVAL_MS);
  await refreshIpInfo();
})();
