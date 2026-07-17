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

### Added
- Governance docs: `CONTRIBUTING.md`, `SECURITY.md`, this changelog, and GitHub
  issue/PR templates.
