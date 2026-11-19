#!/bin/bash
# Keep cached browser downloads out of Terminal's Homebrew installation path.
set -euo pipefail

# Preserve only the exact, checksum-verified portable Ruby archive if it has quarantine metadata.
prepare_homebrew_cache() {
  local brew_prefix vendor_directory ruby_version architecture metadata ruby_tag expected_checksum
  local cache_directory archive actual_checksum backup brew_executable link_target link_count
  brew_prefix="$(dirname "$(dirname "$1")")"
  brew_executable="$1"
  # Intel Homebrew normally links /usr/local/bin/brew into /usr/local/Homebrew/bin.
  for ((link_count = 0; link_count < 32; link_count++)); do
    [[ -L "$brew_executable" ]] || break
    link_target="$(readlink "$brew_executable")"
    if [[ "$link_target" == /* ]]; then
      brew_executable="$link_target"
    else
      brew_executable="$(dirname "$brew_executable")/$link_target"
    fi
  done
  [[ ! -L "$brew_executable" ]] || { echo 'sing-vpn: Homebrew symlink loop' >&2; return 1; }
  vendor_directory="$(cd "$(dirname "$brew_executable")/.." && pwd -P)/Library/Homebrew/vendor"
  [[ -f "$vendor_directory/portable-ruby-version" ]] || return 0
  IFS= read -r ruby_version < "$vendor_directory/portable-ruby-version"
  [[ "$ruby_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(_[0-9]+)?$ ]] || {
    echo 'sing-vpn: invalid Homebrew Ruby version metadata' >&2; return 1;
  }
  architecture="$(uname -m)"
  # Intel Homebrew on an Apple Silicon Mac still downloads the Intel bottle.
  [[ "$brew_prefix" != /usr/local ]] || architecture=x86_64
  [[ "$architecture" == arm64 || "$architecture" == x86_64 ]] || return 0
  metadata="$vendor_directory/portable-ruby-$architecture-darwin"
  [[ -f "$metadata" ]] || return 0
  # Parse data only; never source or evaluate Homebrew metadata as shell code.
  ruby_tag="$(sed -nE 's/^ruby_TAG=([a-zA-Z0-9_]+)$/\1/p' "$metadata")"
  expected_checksum="$(sed -nE 's/^ruby_SHA=([0-9a-f]{64})$/\1/p' "$metadata")"
  [[ "$ruby_tag" =~ ^[a-zA-Z0-9_]+$ && "$expected_checksum" =~ ^[0-9a-f]{64}$ ]] || {
    echo 'sing-vpn: invalid Homebrew Ruby checksum metadata' >&2; return 1;
  }
  cache_directory="${HOMEBREW_CACHE:-$HOME/Library/Caches/Homebrew}"
  archive="$cache_directory/portable-ruby-$ruby_version.$ruby_tag.bottle.tar.gz"
  [[ ! -L "$archive" ]] || { echo 'sing-vpn: refusing a symlinked Ruby cache archive' >&2; return 1; }
  [[ -f "$archive" ]] || return 0
  command -v xattr >/dev/null 2>&1 || return 0
  xattr -p com.apple.quarantine "$archive" >/dev/null 2>&1 || return 0
  actual_checksum="$(shasum -a 256 "$archive")"
  [[ "${actual_checksum%% *}" == "$expected_checksum" ]] || {
    echo 'sing-vpn: cached Ruby checksum mismatch; repair the Homebrew cache before retrying' >&2; return 1;
  }
  backup="$(mktemp "$archive.backup-XXXXXXXX")"
  if ! mv -f -- "$archive" "$backup"; then
    rm -f -- "$backup"
    return 1
  fi
  # Homebrew downloads and verifies a new copy in Terminal; quarantine remains on the backup.
  echo 'sing-vpn: preserved a quarantined Ruby cache archive; Homebrew will download a fresh copy.'
}

if [[ $# -lt 2 ]]; then
  echo 'sing-vpn: missing Homebrew command' >&2
  exit 1
fi
prepare_homebrew_cache "$1"
exec "$@"
