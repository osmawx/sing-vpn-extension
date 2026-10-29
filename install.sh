#!/usr/bin/env bash
# Регистрирует native messaging host для расширения Sing VPN (Chrome/Chromium/Brave, macOS).
# Использование: ./install.sh [uninstall]
set -euo pipefail

HOST_NAME="com.singvpn.host"
EXTENSION_ID="plaaamdfdpajlgakeipabpddfkcaihpn"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPPORT_DIR="$HOME/.local/share/sing-vpn"
WRAPPER="$SUPPORT_DIR/host.sh"
SING_BIN="$HOME/.local/bin/sing"
SING_SELECT_SCRIPT="$HOME/.local/share/sing/select.py"
SING_PROXYCHAINS_CONFIG="$HOME/.proxychains/sing.conf"
SING_SOURCE_DIR="$SUPPORT_DIR/sing-source"
# Совпадает с CHILD_PATH в sing_host.py: Chrome запускает host без пользовательского PATH.
HOST_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
BROWSER_DIRS=(
  "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
  "$HOME/Library/Application Support/Chromium/NativeMessagingHosts"
  "$HOME/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts"
)

if [[ "${1:-}" == "uninstall" ]]; then
  for directory in "${BROWSER_DIRS[@]}"; do
    rm -f "${directory:?}/${HOST_NAME:?}.json"
  done
  rm -f "${WRAPPER:?}"
  echo "sing-vpn: host удалён"
  exit 0
fi

# Находит установленный Homebrew или ставит его официальным скриптом.
ensure_homebrew() {
  local brew_path
  if command -v brew >/dev/null 2>&1; then
    BREW_BIN="$(command -v brew)"
    return
  fi
  for brew_path in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [[ -x "$brew_path" ]]; then
      BREW_BIN="$brew_path"
      return
    fi
  done
  command -v curl >/dev/null 2>&1 || { echo "sing-vpn: нужен curl для установки Homebrew" >&2; return 1; }
  local installer_path
  installer_path="$(mktemp)"
  if ! curl -fsSL --output "$installer_path" https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh; then
    rm -f "$installer_path"
    echo "sing-vpn: не удалось скачать Homebrew" >&2
    return 1
  fi
  if ! /bin/bash "$installer_path"; then
    rm -f "$installer_path"
    echo "sing-vpn: не удалось установить Homebrew" >&2
    return 1
  fi
  rm -f "$installer_path"
  if command -v brew >/dev/null 2>&1; then
    BREW_BIN="$(command -v brew)"
    return
  fi
  for brew_path in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [[ -x "$brew_path" ]]; then
      BREW_BIN="$brew_path"
      return
    fi
  done
  echo "sing-vpn: Homebrew не найден после установки" >&2
  return 1
}

# Проверяет команду в том PATH, который native host передаёт дочернему sing.
host_command_exists() {
  PATH="$HOST_PATH" command -v "$1" >/dev/null 2>&1
}

# Ставит Node.js с npm, если их нет или версия Node.js не поддерживает сборку.
ensure_node() {
  local node_version=""
  if command -v node >/dev/null 2>&1; then
    node_version="$(node --version 2>/dev/null || true)"
  fi
  if [[ "$node_version" =~ ^v?([0-9]+) ]] && (( BASH_REMATCH[1] >= 18 )) && command -v npm >/dev/null 2>&1; then
    return
  fi
  ensure_homebrew
  "$BREW_BIN" install node
  PATH="$(dirname "$BREW_BIN"):$PATH"
  export PATH
  node_version="$(node --version 2>/dev/null || true)"
  if [[ ! "$node_version" =~ ^v?([0-9]+) ]] || (( BASH_REMATCH[1] < 18 )) || ! command -v npm >/dev/null 2>&1; then
    echo "sing-vpn: после установки не найдены Node.js >= 18 и npm" >&2
    return 1
  fi
}

# Собирает расширение перед регистрацией native host.
ensure_build() {
  ensure_node
  (cd "$REPO_DIR" && npm ci --no-audit --no-fund && npm run build)
  local filename
  for filename in manifest.json background.js popup.js proxy-links.js popup.html popup.css; do
    [[ -f "$REPO_DIR/build/$filename" ]] || {
      echo "sing-vpn: после сборки не найден build/$filename" >&2
      return 1
    }
  done
}

# Устанавливает только отсутствующие команды для native host и локального sing.
ensure_dependencies() {
  local missing_formulas=()
  host_command_exists python3 || missing_formulas+=(python)
  host_command_exists sing-box || missing_formulas+=(sing-box)
  host_command_exists proxychains4 || missing_formulas+=(proxychains-ng)
  host_command_exists nc || missing_formulas+=(netcat)
  if ((${#missing_formulas[@]})); then
    ensure_homebrew
    "$BREW_BIN" install "${missing_formulas[@]}"
    PATH="$(dirname "$BREW_BIN"):$PATH"
    export PATH
  fi
  local command_name
  for command_name in python3 sing-box proxychains4 nc; do
    host_command_exists "$command_name" || {
      echo "sing-vpn: после установки не найден $command_name" >&2
      return 1
    }
  done
}

# Ставит sing из соседнего checkout либо из отдельного checkout в каталоге приложения.
ensure_sing() {
  if [[ -x "$SING_BIN" && -f "$SING_SELECT_SCRIPT" && -f "$SING_PROXYCHAINS_CONFIG" ]]; then
    return
  fi
  local source_dir="$REPO_DIR/../sing"
  if [[ ! -f "$source_dir/install.sh" ]]; then
    source_dir="$SING_SOURCE_DIR"
    if [[ ! -e "$source_dir" ]]; then
      mkdir -p "$SUPPORT_DIR"
      if ! command -v git >/dev/null 2>&1; then
        ensure_homebrew
        "$BREW_BIN" install git
        PATH="$(dirname "$BREW_BIN"):$PATH"
        export PATH
      fi
      command -v git >/dev/null 2>&1 || { echo "sing-vpn: после установки не найден git" >&2; return 1; }
      git clone --depth 1 https://github.com/osmawx/sing.git "$source_dir"
    fi
  fi
  [[ -f "$source_dir/install.sh" ]] || { echo "sing-vpn: не найден install.sh в $source_dir" >&2; return 1; }
  local target_path source_path
  for target_path in "$SING_BIN" "$SING_SELECT_SCRIPT" "$SING_PROXYCHAINS_CONFIG"; do
    case "$target_path" in
      "$SING_BIN") source_path="$source_dir/bin/sing" ;;
      "$SING_SELECT_SCRIPT") source_path="$source_dir/share/select.py" ;;
      *) source_path="$source_dir/proxychains/sing.conf" ;;
    esac
    if [[ -d "$target_path" ]] || { [[ -L "$target_path" ]] && [[ ! "$target_path" -ef "$source_path" ]]; }; then
      echo "sing-vpn: существующий файл нельзя заменить: $target_path" >&2
      return 1
    fi
    if [[ -e "$target_path" && ! -L "$target_path" && ( -e "$target_path.bak" || -L "$target_path.bak" ) ]]; then
      echo "sing-vpn: backup уже существует: $target_path.bak" >&2
      return 1
    fi
  done
  bash "$source_dir/install.sh"
  [[ -x "$SING_BIN" && -f "$SING_SELECT_SCRIPT" && -f "$SING_PROXYCHAINS_CONFIG" ]] || {
    echo "sing-vpn: sing установлен не полностью" >&2
    return 1
  }
}

# Сохраняет прежний файл в уникальном backup и атомарно ставит новый.
install_generated_file() {
  local source_path="$1" target_path="$2" file_mode="$3"
  if [[ -e "$target_path" || -L "$target_path" ]]; then
    if [[ -f "$target_path" && ! -L "$target_path" ]] && cmp -s "$source_path" "$target_path"; then
      rm -f "$source_path"
      chmod "$file_mode" "$target_path"
      return
    fi
    [[ ! -d "$target_path" ]] || { echo "sing-vpn: каталог нельзя заменить: $target_path" >&2; return 1; }
    local backup_path
    backup_path="$(mktemp "$target_path.bak.XXXXXX")"
    mv "$target_path" "$backup_path"
    echo "sing-vpn: backup $backup_path"
  fi
  mv "$source_path" "$target_path"
  chmod "$file_mode" "$target_path"
}

PATH="$HOST_PATH:$PATH"
export PATH
ensure_build
ensure_dependencies
ensure_sing
PYTHON_BIN="$(PATH="$HOST_PATH" command -v python3)"

# Chrome запускает host с пустым окружением, поэтому фиксируем абсолютный python
mkdir -p "$SUPPORT_DIR"
wrapper_temp="$(mktemp "$WRAPPER.XXXXXX")"
printf '#!/bin/bash\nexec %q -I %q\n' "$PYTHON_BIN" "$REPO_DIR/src/host/sing_host.py" >"$wrapper_temp"
install_generated_file "$wrapper_temp" "$WRAPPER" 755

for directory in "${BROWSER_DIRS[@]}"; do
  # Только для установленных браузеров
  [[ -d "$(dirname "$directory")" ]] || continue
  mkdir -p "$directory"
  manifest_temp="$(mktemp "$directory/$HOST_NAME.json.XXXXXX")"
  "$PYTHON_BIN" -I - "$HOST_NAME" "$WRAPPER" "$EXTENSION_ID" >"$manifest_temp" <<'PYTHON'
import json
import sys

manifest = {
    "name": sys.argv[1],
    "description": "Sing VPN native host",
    "path": sys.argv[2],
    "type": "stdio",
    "allowed_origins": [f"chrome-extension://{sys.argv[3]}/"],
}
json.dump(manifest, sys.stdout, indent=2)
sys.stdout.write("\n")
PYTHON
  install_generated_file "$manifest_temp" "$directory/$HOST_NAME.json" 600
  echo "sing-vpn: host зарегистрирован в $directory"
done
