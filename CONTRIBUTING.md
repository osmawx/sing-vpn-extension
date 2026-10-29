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
python3 -m unittest discover -s tests -p "test_*.py"
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

## Style

- No extension runtime dependencies: build files from `src/extension/` into `build/`. Python uses the standard library only in `src/host/`.
- Comment every function.
- JavaScript: descriptive `camelCase` names, `PascalCase` components, `UPPER_SNAKE_CASE` constants, and JSDoc for public functions and utilities.
- Python: PEP 8 names and a docstring on every public function and class.
- Bash: `set -euo pipefail`, quote expansions, and comment every function.
- Explain non-obvious logic inside functions with inline comments.

Keep changes focused. Add tests for parsing, validation, failure paths, proxy routing, and credential handling. Use fake hosts, links, and credentials only.

## Branches

- Start each change from current `main` in a separate branch: `git fetch --prune` then `git switch -c fix/short-name origin/main`.
- Name branches `<type>/<kebab-case>`. Use `feat`, `fix`, `refactor`, `docs`, `test`, `ci`, or `chore` as the type.
- Keep one task per branch. If a change depends on an unmerged branch, base the new branch on it and merge in order.
- Do not push directly to `main`, rewrite another contributor's branch, or create merge commits in a pull request branch.

## Commits and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org): `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`, `chore:`. Add a scope when it helps, for example `fix(proxy): reject unsupported links`.
- Write an English imperative subject without a trailing period. Keep it at 50 characters or fewer; use the body to explain non-obvious reasons.
- Do not replace Git author or committer identity. Credit AI-assisted commits with the model name and no email address, for example `Co-Authored-By: GPT-6.1 Sol`.
- Keep one change per pull request. Never commit `extension-key.pem`, subscription URLs, proxy links, or real credentials.
- Explain why the change is needed in the pull request description. List key changes and any checks you could not run.
- Wait for CI checks and address review comments before merging. The maintainer decides when to merge.
