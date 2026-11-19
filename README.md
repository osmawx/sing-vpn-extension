# Sing VPN (browser extension)

Chrome MV3 extension with a Blanc-style popup (Home / Locations / Account). It connects **inside the browser** through your own proxies. Local sing integration uses an optional native host.

## Install

1. Open `chrome://extensions`, enable **Developer mode**.
2. **Load unpacked** and pick the `build/` folder.
3. Open the popup, go to **Locations**, press **+**, paste proxy links and/or a subscription URL, press **Add**.
4. Pick a location, or press the power button to connect to the last used one.

## Supported servers

| Link | Notes |
|---|---|
| `https://user:pass@host:443#Name` | login/password supported |
| `http://user:pass@host:3128#Name` | login/password supported |
| `socks5://host:1080#Name` | only without login/password |
| `socks5://host:1080:login:password` | sing colon format is accepted, but Chrome cannot authenticate SOCKS, so it is rejected |

Name format `🇱🇹 Vilnius, Lithuania, Extra` gives the flag, city and country in the list.

**Not possible in a browser extension:** VLESS, VMess, Trojan, Shadowsocks, Hysteria2, WireGuard. They need a local client such as sing-box, and an extension cannot open sockets or listen on a port. Such links in a subscription are skipped and reported. To use them, run `sing` (sing-box on `127.0.0.1:1080`): the extension adds **Local sing** (`socks5://127.0.0.1:1080`) on first install, pick it in Locations. Choose the server with `sing select <name>` and start it with `sing status`/`sing <cmd>`; the extension only points the browser at that port. If sing-box is not running, connecting breaks browsing: press the power button again to disconnect.

## Two modes

- **Browser-only** (default, nothing to install): http/https/socks5 servers, site exceptions, `.ru` bypass. Nothing outside the browser is touched.
- **With sing** (optional): run `./install.sh` once. It installs the local requirements and adds VLESS/WireGuard and the rest of your `sing` servers. Without the host, the popup stays in browser-only mode and hides sing sections; if you were connected through sing, it disconnects.

## Local sing (all servers from `sing select`)

The popup lists every server from your local `sing` (custom + subscription) and switches them: picking one runs `sing select <name>`, starts `sing-box` if needed and points the browser at `127.0.0.1:1080`. Browsers cannot run commands, so this needs a native messaging host:

**Account → Settings → Install local sing** downloads `sing-installer.tar.gz`. Open the archive and double-click **Install Sing.command**. The launcher downloads a ready-built GitHub Release, verifies its SHA-256 checksum, and installs the native host and CLI without a local Git checkout or Node.js. Homebrew supplies missing Python, sing-box and proxychains dependencies and may ask for your macOS password.

Load `~/.local/share/sing-vpn/runtime/build` once through the browser's **Load unpacked** button. Future updates replace that managed runtime, so the loaded extension and native host use the same installation. Existing development checkouts and proxy configuration remain intact. **Check installation** refreshes local locations after setup. Source developers can still use the command below; this developer path builds with npm.

```bash
./install.sh            # install requirements and register for Chrome/Chromium/Brave/Aside
./install.sh uninstall
```

The install command checks Node.js 18+, npm, Python 3, `sing-box`, `proxychains4`, and `nc`. It installs missing packages with Homebrew, installing Homebrew first if needed. It runs `npm ci` and builds the extension from `src/extension/` before registering the native host. It uses a neighboring `sing` checkout when available; otherwise it clones `sing` into `~/.local/share/sing-vpn/sing-source` and runs its installer. Existing `sing` files are checked before replacement. Then reload the extension. Loading `build/` unpacked in Chrome is still a browser step.

## Build from source

Extension source files live in `src/extension/`. The native host lives in `src/host/`. The checked-in `build/` directory contains the extension to load in Chrome. `./install.sh` regenerates it. To build only the extension after changes:

```bash
npm ci
npm run build
```

The build minifies JavaScript, CSS and HTML, removes comments, and copies icons. It uses JavaScript minifiers without native executables and does not include source maps.

## Update from the extension

Account shows the installed extension version. The extension compares it with the latest stable GitHub Release at browser startup and when the popup opens. Checks do not install anything.

In **Account → Settings**, **Update extension** downloads the prebuilt release and checksum, validates archive paths and file hashes, preserves the previous runtime as a unique backup, and activates the new runtime. Git and npm are not required. Modified managed code blocks an update rather than overwriting local edits. Proxy credentials and configuration are outside the runtime and are not replaced.

When migrating from a source checkout, the extension shows the managed `build` path to load once. It continues showing this instruction until the browser loads the managed package. Subsequent successful updates reload the extension automatically.

**Local versions** shows installed and available versions of the `sing` CLI and `sing-box` engine. Legacy CLI installations without version metadata show an unknown version. **Update sing** installs the standalone CLI release and preserves user settings and existing files as backups. **Update sing-box** uses Homebrew. An active engine keeps running during its update; reconnect local sing afterward to use the new binary. Installation of updates requires an explicit button click.

## Automatic releases

After all CI jobs pass for a push to `main`, CI builds and publishes a complete release with SHA-256 checksums. Extension versions use `1.3.<CI run number>` and CLI versions use `1.0.<CI run number>`. PR runs do not publish releases. Release assets are uploaded to a draft before it becomes the latest stable release.

For the first rollout, merge the standalone `sing` release workflow and wait for its release before merging this extension's release workflow: first-time installation downloads both packages.

## Diagnostic logs

In **Account → Settings → Diagnostics**, **Export logs** downloads a JSON report with browser connection status and the latest 128 KiB of the local `sing.log`. Known credentials, proxy/subscription URLs and common key formats are redacted. Review the file before sharing: site addresses and other diagnostic details may remain. Without the native host, the download still includes browser diagnostics. Export does not change the connection or settings.

Account also has an **Exceptions** button for managing sites that open without VPN.

## Configuration backup

In **Account → Settings**, use **Export configuration** to download a JSON backup of browser proxies, credentials, subscription URL and exceptions, together with local sing custom links, subscription URL and exceptions. The native host is required. The file is not encrypted and contains secrets; keep it private.

**Import configuration** validates the file and asks for confirmation before replacing settings. It disconnects the browser, stops local sing and backs up existing sing files in a private `~/.config/sing-box/import-backup-*` directory. Imported files have permissions `0600`. A failed file write restores previous sing files. Cached locations and generated sing-box configuration are rebuilt when you select a server; active connections and the previous selection are not restored automatically. Subscription servers are fetched from the saved URL, so restoring those locations requires access to the subscription provider.


## Fastest locations

Home shows the two fastest servers of your local `sing`. The host starts a temporary `sing-box` (no listening ports) with every server and measures real delay to the internet through each one (about 10 s), so the numbers include the exit, not just the entry node. WireGuard servers are not measured.

## How it works

- `proxy-links.js`: parses links and base64/plain subscriptions.
- `background.js`: sets `chrome.proxy` (fixed_servers), answers proxy auth via `webRequest.onAuthRequired`, shows an `ON` badge.
- `popup.*`: UI; the external IP banner uses `https://ipwho.is/`.

Servers and credentials are stored in `chrome.storage.local` (unencrypted, on this machine only).

## Security and privacy

See [SECURITY.md](SECURITY.md) and [PRIVACY.md](PRIVACY.md). Licensed under [MIT](LICENSE); contributions: [CONTRIBUTING.md](CONTRIBUTING.md).

## Tests

```bash
npm ci
npm run build
npm test
python3 -m unittest discover -s tests -p "test_*.py"
```
