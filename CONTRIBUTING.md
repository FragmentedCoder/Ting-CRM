# Contributing to Þing

Þing is in early development, and ideas, questions and bug reports are welcome. Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## Issues

- Use the issue templates: [report a bug](https://github.com/FragmentedCoder/Ting-CRM/issues/new?template=bug_report.yml) or [suggest a feature](https://github.com/FragmentedCoder/Ting-CRM/issues/new?template=feature_request.yml). They're also what **New issue** offers on the Issues tab; blank issues are switched off. The templates live in [.github/ISSUE_TEMPLATE](.github/ISSUE_TEMPLATE).
- Search existing issues first; add to one rather than opening a duplicate.
- Report security problems privately as described in [SECURITY.md](SECURITY.md).

## Pull requests

- For anything bigger than a small fix, open an issue first so the approach is agreed before you build it.
- Keep each pull request focused on one change, and describe what it does and how you tested it.
- Add or update tests and documentation along with the code.
- Commit messages: a short subject in the imperative mood ("Add CVSS lookup table"), with detail in the body if needed.

## Running Þing and its tests

The design is in [docs/architecture.md](docs/architecture.md); read it before changing how something works, and keep it current. You need Docker, Python 3.13 and Node 22.17 or later.

- **Backend** (`backend/`): `pip install -e ".[dev]"`, then `ruff check .`, `mypy app` and `pytest`. The backup tests run restic itself and need restic 0.18 or later on the PATH; without it they're skipped.
- **Frontend** (`frontend/`): `npm ci`, then `npm run lint`, `npm run check`, `npm run test` and `npm run build`.
- **Browser tests** against the whole stack behind Caddy: `frontend/e2e/run.sh` from the repository root. It starts its own stack (project `ting-e2e`, port 8443) and removes it with its data afterwards, so it runs beside a test install. It keeps its keys apart from any install's, in `/etc/ting-e2e`: run as root (`sudo frontend/e2e/run.sh`) it makes a throwaway master key there; otherwise put one there first, as the CI workflow does.
- **Installer and scripts**: `deploy/install.test.sh`, `deploy/ting.test.sh`, `python3 deploy/release-compose.test.py`, `shellcheck -x install.sh deploy/*.sh deploy/ting frontend/e2e/run.sh`, and actionlint on the workflows.

CI runs all of these on every pull request, and the browser tests keep their screenshots as an artifact.

## Never commit

- Real customer data, in fixtures, examples, screenshots or import samples. Use the fictional demo company.
- Passwords, API keys, tokens, private keys or certificates.

## Licence

By contributing, you agree that your contribution is licensed under the [GNU AGPL v3.0](LICENSE), the same licence as the rest of Þing.
