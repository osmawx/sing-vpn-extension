# Contributing

## Setup

```bash
git clone https://github.com/osmawx/sing-vpn-extension.git
cd sing-vpn-extension
```

Run `npm ci && npm run build`, then load `build/` unpacked in `chrome://extensions` (Developer mode). Edit extension files in `src/extension/` and native host files in `src/host/`. Commit generated `build/` files with each extension change. For the optional local-sing mode, run `./install.sh`; it builds the extension, installs missing local requirements and registers the native host.

## Checks

```bash
npm ci
npm run build
npm test
python3 -m unittest discover -s tests -p "test_sing_host.py"
shellcheck install.sh
```

## Rules

- No extension runtime dependencies: `npm run build` minifies JavaScript, CSS and HTML from `src/extension/` into `build/`; Python uses the standard library only in `src/host/`.
- Parsing and validation changes need tests with fake hosts and credentials only.
- Every function gets a comment; keep names descriptive.
- One change per pull request. Never commit `extension-key.pem`, subscription URLs, proxy links or real credentials.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`).
- Credit AI-assisted commits with the exact model name and no email address, for example `Co-Authored-By: GPT-6.1 Sol`. Keep Git author and committer identities unchanged.
- Bump `package.json` and the matching lockfile version for releases. Keep `src/extension/manifest.json` in sync; the build uses the package version for the generated manifest.
