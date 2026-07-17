# Contributing to Inspector

Thanks for helping improve Inspector — an MCP server that lets a coding agent see,
operate, and test the app it just built, across web, Electron, Android, and iOS.

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"        # runtime + pytest + ruff
cp .env.example .env           # add keys only if you run cloud surfaces
pytest -q                      # pure unit tests (no cloud SDKs needed)
ruff check inspector tests
```

Heavy SDKs (fastmcp / e2b / replicate / anthropic) are lazy-imported, so the package
and the pure tests run with only `pydantic` + `pillow`.

## Workflow

- Branch off `main` (`fix/…`, `feat/…`, `chore/…`).
- Keep changes focused; add or update tests for behavior you change.
- Run `pytest -q` and `ruff check inspector tests` before opening a PR.
- Describe **what** changed, **why**, and **how you verified it** in the PR.

## Conventions

- Python ≥ 3.12, fully typed. Ruff is the linter/formatter of record.
- Match the surrounding code's naming and comment density.
- Never commit secrets, personal paths, or large third-party apps. Demo apps are
  fetched on demand — see `benchmarks/manifests/`.

## Reporting

- Functional bugs → open a GitHub issue (bug template).
- Security vulnerabilities → **do not** open a public issue; see [SECURITY.md](SECURITY.md).
