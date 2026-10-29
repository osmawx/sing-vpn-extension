# Privacy

Configuration export creates a local, unencrypted JSON file containing browser proxy credentials, subscription URLs, exceptions and local sing custom links. Export requires an explicit button click. Import replaces settings only after confirmation and keeps private backups of previous local sing files. These files are not uploaded by the extension; protect exported files and backups as secrets.

Sing VPN has no servers, accounts, analytics or telemetry. Everything stays on your machine.

## Stored locally

`chrome.storage.local` (unencrypted, this browser profile only): your servers and their credentials, subscription URL, site exceptions, latency numbers. "Remove all servers" in Account wipes the server data.

## Network requests the extension makes

| Request | When | Who sees it |
|---|---|---|
| Subscription URL you entered | on Add / refresh | your subscription provider |
| `https://ipwho.is/` | Home / Account, to show your external IP and country | ipwho.is sees the exit IP (your VPN IP while connected) |
| `https://cp.cloudflare.com/generate_204` | once a second while the popup is open, to show ping | Cloudflare sees the exit IP |
| Your proxy server | all browsing while connected | the proxy operator sees your traffic metadata, and unencrypted traffic |

No browsing history, page content or credentials are sent anywhere other than the proxy you chose.

## Leak protection

While connected, WebRTC is restricted to proxied traffic (`disable_non_proxied_udp`) so your real IP is not exposed over UDP. It is restored on disconnect. Calls that rely on direct UDP may not work while connected. Sites in your exceptions list, and `.ru/.su/.рф` when that switch is on, bypass the proxy by design.

## Native host (optional)

Only with local sing: the host runs `sing` on your computer, never sends data over the network except to fetch your subscription and to measure latency through temporary local sing-box instances. It accepts messages only from this extension's ID. The subscription server-name cache is `~/.cache/sing-vpn/subscription.json` (mode 0600).

## Permissions

`proxy`, `webRequest`, `webRequestAuthProvider` (proxy login), `privacy` (WebRTC), `storage`, `nativeMessaging` (optional host), `activeTab` ("Add current site"), `<all_urls>` (required to answer proxy authentication on any site).
