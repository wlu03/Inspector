# Linux plane — E2B Desktop

The Linux microVM that hosts **web, Electron, and Android (Redroid)**. This is the
plane that's already working for web (see `inspector/adapters/web.py`).

- **Provisioning:** managed by E2B — `e2b_desktop.Sandbox.create(...)` (no infra to run).
- **Code:** `inspector/planes/linux.py` (`LinuxPlane`, wraps `inspector/sandbox.py`).
- **Contents:** Ubuntu 22.04 + XFCE + VNC, `xdotool`, Node + the browser installed on demand.

> **Browser:** the **stock** E2B desktop template ships **Firefox**, which has no
> Chrome DevTools Protocol — and the console tap + headless control need CDP. So the
> web adapter resolves a Chromium-family binary at launch and **installs google-chrome**
> if none is present (~30-60s the first time per sandbox). To skip that per-session
> install, build a custom template with chrome baked in and set `E2B_TEMPLATE` in `.env`.

## Setup
1. `E2B_API_KEY` in `.env` (see project root `.env.example`).
2. That's it — sandboxes are created per session.
3. *(optional)* `E2B_TEMPLATE=<id>` for a custom template that pre-installs google-chrome.

## Self-hosted alternative (optional)
If you outgrow E2B, the same plane can run on **Firecracker / Cloud-Hypervisor**
microVMs you operate. `LinuxPlane` would swap its backend from `E2BSandbox` to an
SSH/agent transport into your own microVM. Not needed to start.

## Android note
Android (Redroid) runs **inside this plane's host**, but needs `binder`/`ashmem`
kernel modules — which E2B's managed sandbox may not expose. If so, Android needs
a Linux host you control (a small AWS Graviton / Hetzner box). See
[../android-redroid/](../android-redroid/).
