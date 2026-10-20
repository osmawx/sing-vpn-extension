#!/usr/bin/env bash
# Регистрирует native messaging host для расширения Sing VPN (Chrome/Chromium/Brave, macOS).
# Использование: ./host/install.sh [uninstall]
set -euo pipefail

HOST_NAME="com.singvpn.host"
EXTENSION_ID="plaaamdfdpajlgakeipabpddfkcaihpn"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT_DIR="$HOME/.local/share/sing-vpn"
WRAPPER="$SUPPORT_DIR/host.sh"
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

PYTHON_BIN="$(command -v python3)"
[[ -x "$PYTHON_BIN" ]] || { echo "sing-vpn: нужен python3" >&2; exit 1; }
# sing необязателен: без него расширение работает в режиме «только браузер» (http/https/socks5)
[[ -x "$HOME/.local/bin/sing" ]] || echo "sing-vpn: sing не найден — режим «только браузер»; установите sing позже, host подхватит его сам" >&2

# Chrome запускает host с пустым окружением, поэтому фиксируем абсолютный python
mkdir -p "$SUPPORT_DIR"
printf '#!/bin/sh\nexec "%s" -I "%s/host/sing_host.py"\n' "$PYTHON_BIN" "$REPO_DIR" >"$WRAPPER"
chmod 755 "$WRAPPER"

for directory in "${BROWSER_DIRS[@]}"; do
  # Только для установленных браузеров
  [[ -d "$(dirname "$directory")" ]] || continue
  mkdir -p "$directory"
  cat >"$directory/$HOST_NAME.json" <<JSON
{
  "name": "$HOST_NAME",
  "description": "Sing VPN native host",
  "path": "$WRAPPER",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXTENSION_ID/"]
}
JSON
  echo "sing-vpn: host зарегистрирован в $directory"
done
