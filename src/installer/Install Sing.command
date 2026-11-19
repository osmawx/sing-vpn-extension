#!/bin/bash
# Download a verified, prebuilt release; no Git checkout or npm is required.
set -euo pipefail
umask 077

# Keep Terminal open so the user can read installation results.
pause_before_exit() {
  read -r -p "Press Return to close this window… " || true
}

trap 'echo "Installation failed. Check the error above and try again."; pause_before_exit' ERR
download_directory="$(mktemp -d)"
# Remove only the private temporary download directory owned by this invocation.
trap 'rm -rf -- "$download_directory"' EXIT
asset_name="sing-vpn-macos.tar.gz"
release_url="https://github.com/osmawx/sing-vpn-extension/releases/latest/download"
printf '%s\n' 'Downloading the latest Sing VPN release. No Git or Node.js is required.'
curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL "$release_url/$asset_name" -o "$download_directory/$asset_name"
curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL "$release_url/$asset_name.sha256" -o "$download_directory/checksum"
read -r expected_checksum _filename < "$download_directory/checksum"
[[ "$expected_checksum" =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid release checksum.' >&2; exit 1; }
actual_checksum="$(shasum -a 256 "$download_directory/$asset_name")"
[[ "${actual_checksum%% *}" == "$expected_checksum" ]] || { echo 'Release checksum mismatch.' >&2; exit 1; }
mkdir "$download_directory/package"
tar -xzf "$download_directory/$asset_name" -C "$download_directory/package"
bash "$download_directory/package/install.sh" --prebuilt
printf '\n%s\n%s\n' 'Local sing installed. Load this folder through your browser extensions page:' \
  "$HOME/.local/share/sing-vpn/runtime/build"
printf '%s\n' 'Use Load unpacked once. Future updates use ready-built releases.'
pause_before_exit
