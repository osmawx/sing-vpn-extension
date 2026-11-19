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
- the update action downloading code outside the fixed official GitHub Release assets, accepting invalid checksums or unsafe archive entries, overwriting modified managed code, or executing shell input;
- `install.sh` overwriting or deleting user files.

Out of scope:

- vulnerabilities in Chrome, sing-box or the proxy protocols themselves (report them upstream);
- a malicious proxy server the user added on purpose.

Release downloads use HTTPS and SHA-256 checksums from the official release. Checksums detect corrupted downloads; they do not replace trust in the repository maintainers and GitHub account. Runtime updates keep a previous-package backup and never contain subscription URLs, generated proxy configurations or credentials.

The installer is delivered as a user-copied Terminal command, not a Finder-opened executable. Homebrew cache repair is limited to its exact current portable Ruby archive, requires matching vendor SHA-256 metadata, rejects archive symlinks and preserves the old archive as a unique backup before Homebrew downloads again. It never recursively removes quarantine or changes Gatekeeper settings.
