# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed
- Un-vendored the ~51 MB `demo-apps/super-productivity` app (3,909 files); it is now
  fetched on demand via `benchmarks/manifests/` (`fetch-demo-app.sh`, pinned to a
  version). Tracked-file count dropped from 4,256 to ~344.
- Deleted a stray committed session transcript that contained third-party PII.
- Dropped the legacy `LOOPBACK_*` environment-variable fallbacks — use `INSPECTOR_*`.
- Moved internal planning docs (`BUILD_PLAN.md`, `DELIVERABLES.md`) out of the tree.

### Changed
- `devin_repo` no longer defaults to a hardcoded personal repository; the Devin PR
  target is derived from the app-under-test's git remote unless `INSPECTOR_DEVIN_REPO`
  is set.
- Refuse HTTP binds on non-loopback hosts until authentication is added.
- README: removed the stale "final branch" notice and fixed dead doc links.
- **Packaging:** renamed the distribution to `inspector-mcp` (the `inspector` PyPI
  name is taken); version `0.1.0a1`. The import package stays `inspector`.
- Pinned `fastmcp==3.4.4` + committed `uv.lock`; split dev tools out of runtime
  extras (`all` no longer pulls pytest/ruff); made **E2B a fully optional extra**.
- Moved `replicate` + `websocket-client` into base deps so the default detector +
  CDP capture work out of the box; `.env` is no longer loaded from `site-packages`.

### Added
- Governance docs: `CONTRIBUTING.md`, `SECURITY.md`, this changelog, and GitHub
  issue/PR templates.
- `inspector-mcp` CLI (`serve` + `doctor`); import-safe `mcp_server.py` (so
  `fastmcp inspect` works); MCP Registry `server.json`.
- pyproject metadata: authors, urls, keywords, classifiers; `INSPECTOR_ENV_FILE`.
- GitHub Actions CI: lint + tests + build + fresh-install + `fastmcp inspect` + `uv.lock` sync check.

### Security
- Validate `session_id` before joining it to the trace root (read + write paths),
  closing a traversal in the run/finding tools and the dashboard action handler.
- Canonicalize `repo_path`; optional `INSPECTOR_WORKSPACE_ROOTS` allowlist.
- Refuse host/local execution over the HTTP transport unless
  `INSPECTOR_ALLOW_UNSAFE_LOCAL=1` (was remote host code execution).
- Release the billed sandbox on client cancellation (previously leaked to the reaper).
- CSRF / DNS-rebinding guard on the dashboard `POST /api/*` endpoints.
