# Security policy

## Supported versions

Only the latest commit on `main` is supported. There are no release branches.

## Reporting a vulnerability

Do not open a public issue for security problems.

Report privately through GitHub: **Security → Report a vulnerability** on this repository
([direct link](https://github.com/osmawx/sing-vpn-extension/security/advisories/new)).

Include:

- what is affected (`src/extension/`, `src/host/sing_host.py`, `build/`, `install.sh`);
- steps to reproduce, with **fake** links and credentials only;
- the impact you expect (traffic leak outside the proxy, credential exposure, code execution, and so on).

You will get a reply within 7 days. Fixes land on `main`, and the advisory is published after the fix.

## Never paste real secrets

Subscription URLs, proxy links and credentials are stored in `chrome.storage.local` and must be redacted in issues, pull requests and logs. If you leaked one, rotate it with your provider.

## Scope

In scope:

- browser traffic leaving outside the chosen proxy while the extension shows it as connected;
- credentials or subscription URLs sent anywhere except the proxy or subscription host the user chose;
- the native messaging host executing anything other than the documented `sing` actions, or accepting messages from other extensions;
- the update action pulling from a remote other than `origin/main`, overwriting local changes, or executing shell input;
- `install.sh` overwriting or deleting user files.

Out of scope:

- vulnerabilities in Chrome, sing-box or the proxy protocols themselves (report them upstream);
- a malicious proxy server the user added on purpose.
