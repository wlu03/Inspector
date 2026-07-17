# Security Policy

Inspector drives real applications and can spawn sandboxes, read repository paths,
and (optionally) run dev commands, so we take security reports seriously.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Use GitHub's private vulnerability reporting on this repository
(**Security → Report a vulnerability**). Include a description, reproduction steps,
the affected version/commit, and the impact. We aim to acknowledge within a few days
and will keep you updated through the fix.

## Known hardening in progress

Inspector is pre-1.0 and actively being hardened. Current caveats:

- **HTTP transport has no authentication yet.** Non-loopback binds are refused; run
  on `127.0.0.1` and front it with an authenticated proxy/tunnel.
- **`execution=local` runs the app on the host** with no sandbox isolation. Prefer
  the sandboxed planes for untrusted apps.
- **`repo_path` and `dev_command` are powerful.** Only point Inspector at
  repositories and commands you trust.

The roadmap's security phase tracks the full plan (auth, path canonicalization,
command restriction, deterministic sandbox teardown).
