# Instructions for AI agents

- Follow [CONTRIBUTING.md](CONTRIBUTING.md) for branches, commits, pull requests, checks, and code style.
- Read [README.md](README.md) before changing supported proxies, browser behavior, or local sing behavior.
- Read [SECURITY.md](SECURITY.md) before changing proxy routing, credentials, storage, native messaging, or installation.
- Never put real subscription URLs, proxy links, credentials, private keys, or `extension-key.pem` in code, tests, logs, issues, or pull requests.

## Work on a task

1. Inspect the relevant code and tests. Reuse existing parsing and validation helpers where possible.
2. For a complex change, write a short plan before editing.
3. Add a failing test for a bug or new proxy behavior. Implement the smallest fix, then refactor.
4. Review the diff for traffic leaks, secret exposure, command injection, and accidental changes to user files.
5. Run the checks in [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a pull request.

## Project constraints

- Keep extension runtime code as plain ES modules; build from src/extension into build with JavaScript-only minifiers.
- Keep `src/host/sing_host.py` compatible with the system `python3` and the standard library only.
- Use fake hosts, links, and credentials in tests. Add parser and validation cases to `tests/proxy-links.test.mjs`; add native host cases to `tests/test_*.py`.
- Keep `install.sh` safe for existing user files. Verify install and uninstall behavior when changing it.
- Do not bypass checks or commit with `--no-verify`.

## Git

- Check the current branch and worktree before editing. Keep unrelated changes intact.
- Use one task per branch, based on current `main`. Name branches `<type>/<kebab-case>`; use a type from [CONTRIBUTING.md](CONTRIBUTING.md#branches).
- Do not push, open a pull request, merge, delete a remote branch, or change repository settings without the owner's explicit instruction.
