# Contributing

## Setup

```bash
git clone https://github.com/osmawx/sing-vpn-extension.git
cd sing-vpn-extension
```

Load `extension/` unpacked in `chrome://extensions` (Developer mode). The optional local-sing mode also needs [sing](https://github.com/osmawx/sing) and `./host/install.sh`.

## Checks

```bash
node --test tests/proxy-links.test.mjs
python3 -m unittest discover -s tests -p "test_sing_host.py"
shellcheck host/install.sh
```

## Rules

- No build step and no runtime dependencies: plain ES modules in the extension, Python standard library only in `host/`.
- Parsing and validation changes need tests with fake hosts and credentials only.
- Every function gets a comment; keep names descriptive.
- One change per pull request. Never commit `extension-key.pem`, subscription URLs, proxy links or real credentials.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`).
