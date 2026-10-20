# Sing VPN (browser extension)

Chrome MV3 extension with a Blanc-style popup (Home / Locations / Account). It connects **inside the browser** through your own proxies, with no helper app and no native host.

## Install

1. Open `chrome://extensions`, enable **Developer mode**.
2. **Load unpacked** and pick the `extension/` folder.
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
- **With sing** (optional): `./host/install.sh` plus `~/.local/bin/sing`. Adds VLESS/WireGuard and the rest of your `sing` servers. Without the host, or with the host but no `sing`, the popup stays in browser-only mode and hides sing sections; if you were connected through sing, it disconnects.

## Local sing (all servers from `sing select`)

The popup lists every server from your local `sing` (custom + subscription) and switches them: picking one runs `sing select <name>`, starts `sing-box` if needed and points the browser at `127.0.0.1:1080`. Browsers cannot run commands, so this needs a native messaging host:

```bash
./host/install.sh            # register for Chrome/Chromium/Brave
./host/install.sh uninstall
```

Then reload the extension. Requires `~/.local/bin/sing` and Python 3. VLESS/WireGuard servers work this way.

## Fastest locations

Home shows the two fastest servers of your local `sing`. The host starts a temporary `sing-box` (no listening ports) with every server and measures real delay to the internet through each one (about 10 s), so the numbers include the exit, not just the entry node. WireGuard servers are not measured.

## How it works

- `proxy-links.js`: parses links and base64/plain subscriptions.
- `background.js`: sets `chrome.proxy` (fixed_servers), answers proxy auth via `webRequest.onAuthRequired`, shows an `ON` badge.
- `popup.*`: UI; the external IP banner uses `https://ipwho.is/`.

Servers and credentials are stored in `chrome.storage.local` (unencrypted, on this machine only).

## Tests

```bash
node --test tests/proxy-links.test.mjs
python3 -m unittest discover -s tests -p "test_sing_host.py"
```
