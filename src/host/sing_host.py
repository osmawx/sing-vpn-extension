#!/usr/bin/env python3
"""Native messaging host: мост между расширением Sing VPN и локальным CLI `sing`.

Chrome запускает скрипт на каждое сообщение: один JSON в stdin, один JSON в stdout.
Действия: ping, list, connect, status, latency, exceptions_get, exceptions_set, update.
Протокол: 4 байта длины (native byte order) + UTF-8 JSON.
"""

import contextlib
import importlib.util
import json
import os
import re
import secrets
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit

HOME = os.path.expanduser("~")
REPOSITORY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SING_BIN = os.path.join(HOME, ".local", "bin", "sing")
SING_BOX_BINARIES = ("/opt/homebrew/bin/sing-box", "/usr/local/bin/sing-box")
CONFIG_DIR = os.path.join(HOME, ".config", "sing-box")
CONFIG_FILE = os.path.join(CONFIG_DIR, "sing.json")
PID_FILE = os.path.join(CONFIG_DIR, "sing.pid")
CURRENT_FILE = os.path.join(CONFIG_DIR, "sing.current")
SUBSCRIPTION_FILE = os.path.join(CONFIG_DIR, "sing.sub")
SELECT_SCRIPT = os.path.join(HOME, ".local", "share", "sing", "select.py")
LATENCY_TEST_URL = "https://cp.cloudflare.com/generate_204"
LATENCY_TEST_TIMEOUT_MS = 4000
LATENCY_MAX_WORKERS = 16
STREAM_PAUSE_SECONDS = 1
LOG_FILE = os.path.join(HOME, "Library", "Logs", "sing.log")
CACHE_FILE = os.path.join(HOME, ".cache", "sing-vpn", "subscription.json")
LIST_RETRY_DELAY_SECONDS = 2
PROXY_VARIABLES = frozenset({"http_proxy", "https_proxy", "all_proxy", "no_proxy"})
SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 1080
# У Chrome почти пустой PATH: добавляем homebrew и ~/.local/bin, нужные скрипту sing
CHILD_PATH = ":".join(
    ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
     os.path.join(HOME, ".local", "bin")]
)
SELECT_TIMEOUT_SECONDS = 60
PORT_WAIT_ATTEMPTS = 50
PORT_WAIT_INTERVAL_SECONDS = 0.1
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_NAME_LENGTH = 200
UPDATE_REPOSITORY_URL = "https://github.com/osmawx/sing-vpn-extension.git"
UPDATE_GIT_TIMEOUT_SECONDS = 120
UPDATE_BUILD_TIMEOUT_SECONDS = 180
MAX_CONFIGURATION_BYTES = 512 * 1024
CONFIGURATION_FILES = ("sing.sub", "custom.txt", "exceptions.json", "sing.current", "sing.json")
# Имена, которые `sing select` воспринимает как подкоманды, а не как сервер
RESERVED_NAMES = frozenset({"add", "rm", "remove"})
GROUP_HEADERS = {"— свои:": "custom", "— подписка:": "subscription"}
FLAG_PATTERN = re.compile(r"^([\U0001F1E6-\U0001F1FF]{2})\s*(.*)$")


def child_environment():
    """Окружение для дочерних процессов.

    Прокси-переменные убираем: подписку нужно скачивать напрямую, а не через
    собственный sing-box (иначе при TLS-перехвате на выходе проверка сертификата падает).
    """
    environment = {
        name: value for name, value in os.environ.items() if name.lower() not in PROXY_VARIABLES
    }
    environment["PATH"] = CHILD_PATH
    environment["HOME"] = HOME
    return environment


def split_location_name(name):
    """Разбирает «🇱🇹 Вильнюс, Литва, Extra» на флаг, город и страну."""
    flag = ""
    rest = name.strip()
    flag_match = FLAG_PATTERN.match(rest)
    if flag_match:
        flag, rest = flag_match.group(1), flag_match.group(2)
    parts = [part.strip() for part in rest.split(",")]
    city = parts[0] if parts else rest
    country = parts[1] if len(parts) > 1 else ""
    return {"name": name, "flag": flag, "city": city, "country": country}


def parse_select_output(text):
    """Превращает вывод `sing select` в список локаций с группой и признаком текущей."""
    locations = []
    group = "subscription"
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped in GROUP_HEADERS:
            group = GROUP_HEADERS[stripped]
            continue
        # Строка сервера: " <маркер> <имя>", маркер «*» у текущего
        if len(raw_line) < 4 or not raw_line.startswith(" "):
            continue
        name = raw_line[3:].strip()
        if not name:
            continue
        location = split_location_name(name)
        location["group"] = group
        location["current"] = raw_line[1] == "*"
        locations.append(location)
    return locations


def validate_location_name(name):
    """Проверяет имя сервера из сообщения; бросает ValueError, если оно небезопасно."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError("name is too long")
    if name.startswith("-") or name.strip().lower() in RESERVED_NAMES:
        raise ValueError("name is reserved")
    return name.strip()


def run_sing(arguments, timeout_seconds, input_text=None):
    """Запускает `sing …` без shell (stdin — input_text или пусто); возвращает (код, stdout, stderr)."""
    completed = subprocess.run(
        [SING_BIN, *arguments], input=input_text,
        stdin=subprocess.DEVNULL if input_text is None else None,
        capture_output=True, text=True,
        timeout=timeout_seconds, env=child_environment(), check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def is_socks_listening():
    """Проверяет, слушает ли sing-box локальный порт."""
    try:
        with socket.create_connection((SOCKS_HOST, SOCKS_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def find_sing_box_binary():
    """Ищет бинарник sing-box среди типичных путей homebrew."""
    for candidate in SING_BOX_BINARIES:
        if os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError("sing-box not found (brew install sing-box)")


def read_current_name():
    """Читает имя выбранного сервера из файла состояния sing."""
    try:
        with open(CURRENT_FILE, encoding="utf-8") as current_file:
            return current_file.read().strip()
    except OSError:
        return ""


def ensure_sing_box_running():
    """Поднимает sing-box так же, как `sing`, если порт ещё не слушается."""
    if is_socks_listening():
        return
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError("sing config missing: run `sing select <server>` first")
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [find_sing_box_binary(), "run", "-c", CONFIG_FILE], stdin=subprocess.DEVNULL,
            stdout=log_file, stderr=log_file, start_new_session=True, env=child_environment(),
        )
    with open(PID_FILE, "w", encoding="utf-8") as pid_file:
        pid_file.write(str(process.pid))
    for _attempt in range(PORT_WAIT_ATTEMPTS):
        if is_socks_listening():
            return
        time.sleep(PORT_WAIT_INTERVAL_SECONDS)
    raise RuntimeError(f"sing-box did not start, see {LOG_FILE}")


def read_subscription_label():
    """Домен подписки для заголовка раздела (сам URL с токеном наружу не отдаём)."""
    try:
        with open(SUBSCRIPTION_FILE, encoding="utf-8") as subscription_file:
            hostname = urlsplit(subscription_file.read().strip()).hostname or ""
        # Только основной домен: поддомен у подписки бывает персональным идентификатором
        return ".".join(hostname.split(".")[-2:])
    except OSError:
        return ""


def load_cached_subscription():
    """Читает последний удачный список серверов подписки; пустой список, если кеша нет."""
    try:
        with open(CACHE_FILE, encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, ValueError):
        return []


def save_cached_subscription(locations):
    """Сохраняет список серверов подписки (без секретов: только имена)."""
    os.makedirs(os.path.dirname(CACHE_FILE), mode=0o700, exist_ok=True)
    # Файл только для владельца: даже имена серверов подписки не для чужих глаз
    file_descriptor = os.open(CACHE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as cache_file:
        json.dump(locations, cache_file, ensure_ascii=False)
    os.chmod(CACHE_FILE, 0o600)


def fetch_locations():
    """Вызывает `sing select`; возвращает (локации, текст stderr)."""
    code, output, error = run_sing(["select"], SELECT_TIMEOUT_SECONDS)
    if code != 0:
        raise RuntimeError(error.strip() or "sing select failed")
    return parse_select_output(output), error.strip()


def handle_list(_message):
    """Возвращает серверы подписки и свои прокси.

    `sing select` при сбое сети молча отдаёт только свои прокси, поэтому делаем
    один повтор, а затем подставляем кеш последнего удачного списка подписки.
    """
    locations, notice = fetch_locations()
    has_subscription = any(item["group"] == "subscription" for item in locations)
    if not has_subscription:
        time.sleep(LIST_RETRY_DELAY_SECONDS)
        locations, notice = fetch_locations()
        has_subscription = any(item["group"] == "subscription" for item in locations)
    warning = ""
    if has_subscription:
        save_cached_subscription([item for item in locations if item["group"] == "subscription"])
    else:
        cached = load_cached_subscription()
        locations = locations + [dict(item, current=False) for item in cached]
        warning = notice or "subscription unavailable"
        if cached:
            warning += " (showing cached list)"
    return {"locations": locations, "current": read_current_name(), "warning": warning,
            "subscriptionLabel": read_subscription_label()}


def handle_connect(message):
    """Выбирает сервер (sing перезапускает sing-box сам) и гарантирует, что порт слушается."""
    name = validate_location_name(message.get("name"))
    code, _output, error = run_sing(["select", name], SELECT_TIMEOUT_SECONDS)
    if code != 0:
        raise RuntimeError(error.strip() or "sing select failed")
    ensure_sing_box_running()
    return {"running": True, "current": read_current_name()}


def handle_exceptions_get(_message):
    """Возвращает исключения sing: домены и режим «все .ru/.su/.рф»."""
    code, output, error = run_sing(["exceptions", "get-json"], SELECT_TIMEOUT_SECONDS)
    if code != 0:
        raise RuntimeError(error.strip() or "sing exceptions failed")
    state = json.loads(output)
    return {"domains": state["domains"], "bypassRu": state["bypass_ru"]}


def handle_exceptions_set(message):
    """Записывает исключения в sing (он сам применит их и перезапустит sing-box)."""
    domains = message.get("domains")
    if not isinstance(domains, list) or not all(isinstance(item, str) for item in domains):
        raise ValueError("domains must be a list of strings")
    payload = json.dumps({"domains": domains, "bypass_ru": bool(message.get("bypassRu"))})
    code, output, error = run_sing(["exceptions", "set-json"], SELECT_TIMEOUT_SECONDS, payload)
    if code != 0:
        raise RuntimeError(error.strip() or "sing exceptions failed")
    state = json.loads(output)
    return {"domains": state["domains"], "bypassRu": state["bypass_ru"]}


def load_select_module():
    """Подгружает select.py из установки sing, чтобы переиспользовать разбор ссылок."""
    spec = importlib.util.spec_from_file_location("sing_select", SELECT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_probe_outbounds(select_module, links):
    """Собирает outbound-ы для проверки: {tag: имя сервера}, список конфигов.

    WireGuard пропускаем (в sing-box это endpoint, и пробу он не поддерживает).
    """
    outbounds, names = [], {}
    for link in links:
        try:
            outbound = select_module.build_outbound(link)
        except (ValueError, KeyError, IndexError):
            continue
        if outbound.get("type") == "wireguard":
            continue
        tag = f"probe-{len(outbounds)}"
        outbounds.append({**outbound, "tag": tag})
        names[tag] = select_module.link_name(link)
    return outbounds, names


def pick_free_port():
    """Свободный локальный порт для временного API sing-box."""
    with socket.socket() as probe_socket:
        probe_socket.bind((SOCKS_HOST, 0))
        return probe_socket.getsockname()[1]


def query_delay(api_port, secret, tag):
    """Спрашивает у sing-box задержку до интернета через outbound; None при ошибке."""
    query = urlencode({"url": LATENCY_TEST_URL, "timeout": LATENCY_TEST_TIMEOUT_MS})
    request = urllib.request.Request(
        f"http://{SOCKS_HOST}:{api_port}/proxies/{tag}/delay?{query}",
        headers={"Authorization": f"Bearer {secret}"},
    )
    direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with direct_opener.open(request, timeout=LATENCY_TEST_TIMEOUT_MS / 1000 + 2) as response:
            return int(json.load(response)["delay"])
    except (OSError, ValueError, KeyError):
        return None


def wait_for_api(api_port, process):
    """Ждёт, пока временный sing-box поднимет API; RuntimeError, если он завершился."""
    for _attempt in range(PORT_WAIT_ATTEMPTS * 2):
        if process.poll() is not None:
            raise RuntimeError("probe sing-box exited")
        try:
            with socket.create_connection((SOCKS_HOST, api_port), timeout=0.3):
                return
        except OSError:
            time.sleep(PORT_WAIT_INTERVAL_SECONDS)
    raise RuntimeError("probe sing-box did not start")


@contextlib.contextmanager
def probe_session(outbounds):
    """Поднимает временный sing-box со всеми серверами; отдаёт (порт API, секрет).

    В конфиге пароли серверов: каталог только для владельца, удаляется всегда;
    процесс гасится при выходе из контекста.
    """
    api_port, secret = pick_free_port(), secrets.token_hex(16)
    config = {
        "log": {"level": "error"},
        "outbounds": outbounds + [{"type": "direct", "tag": "direct"}],
        "route": {"final": "direct"},
        "experimental": {"clash_api": {
            "external_controller": f"{SOCKS_HOST}:{api_port}", "secret": secret,
        }},
    }
    with tempfile.TemporaryDirectory(prefix="sing-vpn-") as probe_dir:
        config_path = os.path.join(probe_dir, "probe.json")
        file_descriptor = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(file_descriptor, "w") as config_file:
            json.dump(config, config_file)
        process = subprocess.Popen(
            [find_sing_box_binary(), "run", "-c", config_path], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_environment(),
        )
        try:
            wait_for_api(api_port, process)
            yield api_port, secret
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def measure_round(api_port, secret, names):
    """Один раунд замера: {имя сервера: мс или None}."""
    with ThreadPoolExecutor(max_workers=LATENCY_MAX_WORKERS) as executor:
        delays = executor.map(lambda tag: query_delay(api_port, secret, tag), names)
        return dict(zip(names.values(), delays))


def collect_probe_targets():
    """Outbound-ы и имена всех серверов sing (свои и подписка) для замера."""
    select_module = load_select_module()
    links = select_module.read_custom_links() + select_module.fetch_subscription_links()
    return build_probe_outbounds(select_module, links)


def handle_latency(_message):
    """Один замер реальной задержки до интернета через каждый сервер sing.

    WireGuard не измеряется. Возвращает {имя: мс или None}.
    """
    outbounds, names = collect_probe_targets()
    if not outbounds:
        return {"latencies": {}}
    with probe_session(outbounds) as (api_port, secret):
        return {"latencies": measure_round(api_port, secret, names)}


def run_latency_stream(output_stream, input_stream):
    """Непрерывный замер: раунд за раундом шлёт {latencies}, пока расширение не закроет порт.

    Закрытие порта видно по EOF на stdin; тогда временный sing-box сразу гасится.
    """
    stop_requested = threading.Event()

    def watch_input():
        input_stream.read()  # блокируется до закрытия порта
        stop_requested.set()

    threading.Thread(target=watch_input, daemon=True).start()
    try:
        outbounds, names = collect_probe_targets()
        if not outbounds:
            write_message(output_stream, {"ok": True, "latencies": {}})
            return
        with probe_session(outbounds) as (api_port, secret):
            while not stop_requested.is_set():
                write_message(output_stream, {"ok": True, "latencies": measure_round(api_port, secret, names)})
                stop_requested.wait(STREAM_PAUSE_SECONDS)
    except (RuntimeError, OSError, ValueError) as error:
        try:
            write_message(output_stream, {"ok": False, "error": str(error)})
        except OSError:
            pass


def handle_status(_message):
    """Слушает ли sing-box порт и какой сервер выбран."""
    return {"running": is_socks_listening(), "current": read_current_name(), "port": SOCKS_PORT}


def handle_ping(_message):
    """Проверка связи: доступен ли CLI sing."""
    return {"singInstalled": os.access(SING_BIN, os.X_OK)}


def validate_sing_configuration(data):
    """Проверяет переносимые исходники sing через его парсер без запуска соединения."""
    if not isinstance(data, dict) or len(json.dumps(data).encode()) > MAX_CONFIGURATION_BYTES:
        raise ValueError("invalid or oversized sing configuration")
    subscription = data.get("subscriptionUrl")
    links = data.get("customLinks")
    exceptions = data.get("exceptions")
    if not isinstance(subscription, str) or any(character in subscription for character in "\r\n\0"):
        raise ValueError("invalid sing subscription")
    if subscription:
        try:
            parsed = urlsplit(subscription)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError()
        except ValueError:
            raise ValueError("invalid sing subscription") from None
    if not isinstance(links, list) or len(links) > 1000 or not all(
            isinstance(link, str) and len(link) <= 10000 and not any(char in link for char in "\r\n\0")
            for link in links):
        raise ValueError("invalid custom links")
    if not isinstance(exceptions, dict) or not isinstance(exceptions.get("domains"), list) or len(
            exceptions["domains"]) > 1000 or not isinstance(exceptions.get("bypassRu"), bool):
        raise ValueError("invalid sing exceptions")
    selector = load_select_module()
    try:
        for link in links:
            selector.build_outbound(link)
        domains = [selector.normalize_domain(domain) if isinstance(domain, str) else None
                   for domain in exceptions["domains"]]
        if not all(domains):
            raise ValueError()
    except Exception:
        # Парсер протокола может включать секретную ссылку в текст исключения.
        raise ValueError("invalid custom proxy or exception") from None
    return {"subscriptionUrl": subscription, "customLinks": links,
            "exceptions": {"domains": list(dict.fromkeys(domains)), "bypassRu": exceptions["bypassRu"]}}


def read_configuration_file(filename):
    """Читает только обычный файл фиксированного набора, не следуя symlink."""
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.lexists(path):
        return None
    if not stat.S_ISREG(os.lstat(path).st_mode):
        raise ValueError("configuration path must be a regular file")
    with open(path, encoding="utf-8") as source:
        contents = source.read(MAX_CONFIGURATION_BYTES + 1)
    if len(contents.encode()) > MAX_CONFIGURATION_BYTES:
        raise ValueError("sing configuration is too large")
    return contents


def write_private_file(path, contents):
    """Атомарно записывает файл с секретами и правами 0600."""
    descriptor, temporary_path = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(contents)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def handle_export_configuration(_message):
    """Экспортирует исходные настройки sing без готового sing.json и состояния процесса."""
    subscription = (read_configuration_file("sing.sub") or "").strip()
    custom = read_configuration_file("custom.txt") or ""
    exceptions = json.loads(read_configuration_file("exceptions.json") or '{}')
    data = {"subscriptionUrl": subscription,
            "customLinks": [line.strip() for line in custom.splitlines() if line.strip() and not line.lstrip().startswith("#")],
            "exceptions": {"domains": exceptions.get("domains", []), "bypassRu": exceptions.get("bypass_ru", False)}}
    return {"configuration": validate_sing_configuration(data)}


def handle_validate_configuration(message):
    """Проверяет конфигурацию до отключения активного соединения."""
    validate_sing_configuration(message.get("configuration"))
    return {}


def handle_import_configuration(message):
    """Сохраняет backup, останавливает sing и восстанавливает исходники без автоподключения."""
    data = validate_sing_configuration(message.get("configuration"))
    if os.path.islink(CONFIG_DIR):
        raise ValueError("configuration directory must not be a symlink")
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    previous = {name: read_configuration_file(name) for name in CONFIGURATION_FILES}
    backup = tempfile.mkdtemp(prefix="import-backup-", dir=CONFIG_DIR)
    for name, contents in previous.items():
        if contents is not None:
            write_private_file(os.path.join(backup, name), contents)
    code, _output, _error = run_sing(["stop"], SELECT_TIMEOUT_SECONDS)
    if code != 0:
        raise RuntimeError("cannot stop sing before import")
    contents = {
        "sing.sub": data["subscriptionUrl"] + "\n",
        "custom.txt": "\n".join(data["customLinks"]) + "\n",
        "exceptions.json": json.dumps({"domains": data["exceptions"]["domains"],
                                      "bypass_ru": data["exceptions"]["bypassRu"]}),
    }
    try:
        for name in CONFIGURATION_FILES:
            target = os.path.join(CONFIG_DIR, name)
            if name in contents:
                write_private_file(target, contents[name])
            elif os.path.lexists(target):
                os.unlink(target)
    except OSError:
        for name, original in previous.items():
            target = os.path.join(CONFIG_DIR, name)
            if original is not None:
                write_private_file(target, original)
            elif os.path.lexists(target):
                os.unlink(target)
        raise RuntimeError("sing import failed; previous files restored") from None
    if os.path.lexists(CACHE_FILE):
        os.unlink(CACHE_FILE)
    return {"backup": backup}


def run_update_command(arguments, timeout_seconds):
    """Запускает фиксированную команду обновления в checkout без shell и вывода секретов."""
    environment = child_environment()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            arguments, cwd=REPOSITORY_DIR, env=environment, shell=False,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("update timed out") from error


def handle_check_update(_message):
    """Сравнивает публичный main с checkout без скачивания и установки кода."""
    if not os.path.exists(os.path.join(REPOSITORY_DIR, ".git")):
        raise RuntimeError("update requires a Git checkout")
    remote = run_update_command(
        ["git", "ls-remote", UPDATE_REPOSITORY_URL, "refs/heads/main"], 20,
    )
    if remote.returncode != 0:
        raise RuntimeError("update check failed; check GitHub access")
    revision = remote.stdout.split()[0] if remote.stdout.strip() else ""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("cannot read latest revision")
    # Не предлагаем обновление, если локальная ветка уже содержит публичный main.
    ancestor = run_update_command(
        ["git", "merge-base", "--is-ancestor", revision, "HEAD"], 10,
    )
    return {"available": ancestor.returncode != 0}


def handle_update(_message):
    """Получает fast-forward из публичного main по HTTPS и пересобирает расширение."""
    if not os.path.exists(os.path.join(REPOSITORY_DIR, ".git")):
        raise RuntimeError("update requires a Git checkout")

    status = run_update_command(["git", "status", "--porcelain"], UPDATE_GIT_TIMEOUT_SECONDS)
    if status.returncode != 0:
        raise RuntimeError("cannot inspect Git checkout")
    if status.stdout.strip():
        raise RuntimeError("local changes prevent update")

    current_revision = run_update_command(["git", "rev-parse", "HEAD"], UPDATE_GIT_TIMEOUT_SECONDS)
    if current_revision.returncode != 0:
        raise RuntimeError("cannot read current revision")

    pulled = run_update_command(["git", "pull", "--ff-only", UPDATE_REPOSITORY_URL, "main"], UPDATE_GIT_TIMEOUT_SECONDS)
    if pulled.returncode != 0:
        raise RuntimeError("git pull failed; check GitHub access and local history")

    installed = run_update_command(["npm", "ci", "--no-audit", "--no-fund"], UPDATE_BUILD_TIMEOUT_SECONDS)
    if installed.returncode != 0:
        raise RuntimeError("npm ci failed; run ./install.sh")
    built = run_update_command(["npm", "run", "build"], UPDATE_BUILD_TIMEOUT_SECONDS)
    if built.returncode != 0:
        raise RuntimeError("build failed; run ./install.sh")

    new_revision = run_update_command(["git", "rev-parse", "HEAD"], UPDATE_GIT_TIMEOUT_SECONDS)
    if new_revision.returncode != 0:
        raise RuntimeError("cannot read updated revision")
    return {"updated": current_revision.stdout.strip() != new_revision.stdout.strip()}


# Действия, которым нужен установленный `sing`; без него расширение работает в режиме «только браузер»
ACTIONS_NEEDING_SING = {"list", "connect", "latency", "exceptions_get", "exceptions_set",
                        "export_configuration", "validate_configuration", "import_configuration"}

ACTION_HANDLERS = {
    "list": handle_list,
    "connect": handle_connect,
    "status": handle_status,
    "latency": handle_latency,
    "exceptions_get": handle_exceptions_get,
    "exceptions_set": handle_exceptions_set,
    "ping": handle_ping,
    "update": handle_update,
    "check_update": handle_check_update,
    "export_configuration": handle_export_configuration,
    "validate_configuration": handle_validate_configuration,
    "import_configuration": handle_import_configuration,
}


def read_message(stream):
    """Читает одно сообщение native messaging; None, если поток закрыт."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = struct.unpack("=I", header)
    if length > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    return json.loads(stream.read(length).decode("utf-8"))


def write_message(stream, payload):
    """Пишет ответ в формате native messaging."""
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("=I", len(encoded)))
    stream.write(encoded)
    stream.flush()


def dispatch(message):
    """Выполняет действие и всегда возвращает словарь с ключом ok."""
    action = message.get("action") if isinstance(message, dict) else None
    handler = ACTION_HANDLERS.get(action)
    if handler is None:
        return {"ok": False, "error": f"unknown action: {action}"}
    if action in ACTIONS_NEEDING_SING and not os.access(SING_BIN, os.X_OK):
        return {"ok": False, "singMissing": True, "error": "sing is not installed"}
    try:
        return {"ok": True, **handler(message)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "sing timed out"}
    except (ValueError, RuntimeError, OSError) as error:
        return {"ok": False, "error": str(error)}


def main():
    """Точка входа: одно сообщение → один ответ."""
    try:
        message = read_message(sys.stdin.buffer)
    except (ValueError, json.JSONDecodeError) as error:
        write_message(sys.stdout.buffer, {"ok": False, "error": str(error)})
        return
    if message is None:
        return
    if isinstance(message, dict) and message.get("action") == "latency_stream":
        run_latency_stream(sys.stdout.buffer, sys.stdin.buffer)
        return
    write_message(sys.stdout.buffer, dispatch(message))


if __name__ == "__main__":
    main()
