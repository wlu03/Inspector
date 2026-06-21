# iOS + macOS-native Adapter — Build Plan

> Two adapters on **one** tart macOS VM. `Surface.IOS` (the milestone) is a single kit-parameterized adapter over the iOS Simulator. `Surface.MACOS` is a follow-up native-AppKit/SwiftUI adapter reusing the same VM. Grounding is **hybrid** (native accessibility tree primary, OmniParser SoM fallback) wired through **one** new optional hook so the loop/driver/SoM/MCP never branch on surface — clicks always go through pixels, preserving pure-computer-use.

## Decisive answers (the crux)

| Question | Decision |
|---|---|
| How many adapters? | **Two.** `IOSAdapter` (kit-parameterized: SwiftUI/UIKit/Catalyst/RN/Flutter/Unity all share simctl+idb; only the **build command** + a11y richness vary). `MacOSAdapter` (distinct: AXUIElement + CGEvent + screencapture) — Phase 4. |
| Grounding on native UI? | **Hybrid: a11y-primary, OmniParser-fallback.** a11y gives exact tap-ready frames/labels/roles where OmniParser is weakest (tab bars, icon-only controls); vision fills webview/canvas/Flutter holes where a11y is blind. |
| How does it fit the existing model? | **One ~6-line core change:** add `detect_elements(screenshot) -> list[Element] | None` (default `None`) to `SurfaceAdapter`; in `observe()/act()`, use it when non-None else fall back to `OmniParserDetector`. Web/Electron/Android keep the default and are untouched. The a11y tree just emits the **same `Element[]`** (stamp `Element.source = 'a11y'`). |
| Clicks via a11y or pixels? | **Always pixels** (`Element.center_px`). a11y is an additive grounding source, never the action path — the pure-computer-use thesis holds, and it makes `rendered_elements()`/the missing-element oracle first-class on native UI. |
| Plane wiring? | **Adapter-owns-transport** (Option A): `IOSAdapter` constructs `self.plane = MacOSPlane(...)` internally, exactly like `DesktopAdapter.sandbox = E2BSandbox`. **No `session.py` plane refactor** (that's dead code today; bigger/riskier). |
| Input/a11y backend? | **idb** (companion built from `main`, not the stale v1.1.8 pip release) for both `idb ui tap`/`text`/`swipe` and `idb ui describe-all` (a11y). Appium XCUITest only if from-source idb proves too flaky — and never for clicks. |

## Grounding strategy (detail)

`Element{id,label,role,bbox(0..1 ratios),interactivity,source}` and `perception/som.py` key entirely off **bbox ratios + id**. A native a11y tree is just a *second element source* emitting the same list — nothing downstream changes.

- **iOS** `detect_elements`: parse `idb ui describe-all` JSON → `Element` per node (bbox normalized by **point** dims). If the tree is thin/opaque (one WKWebView node, or < N interactive) → also run OmniParser, append non-IoU-overlapping vision elements, re-number ids, stamp `source`.
- **macOS** `detect_elements`: same shape via a code-signed `axctl` helper dumping `AXUIElement`.
- If idb/AX absent or errors → return `None` → Inspector runs today's pure-vision path (a half-provisioned host still works).

## Plane design (`MacOSPlane`, tart)

Mirror `E2BSandbox`'s method surface so `IOSAdapter` reads like `DesktopAdapter`:
- `start()` — if `config.macos_host` set → no-op connect (dev against localhost/an already-booted Mac); else `tart clone <golden>` + `tart run --no-graphics &` + `tart ip --wait` + `caffeinate -dimsu` (keeps the auto-login Aqua session alive so simctl-over-SSH isn't blank).
- `run_sync` / `run_bg` — `ssh user@ip '<cmd>'` (stdout/exit_code, `None` on error); backgrounded ssh for `log stream` + `idb_companion`.
- `upload` — `scp -r` with the same `.env`/`node_modules` skip filtering.
- `screenshot()` — `xcrun simctl io booted screenshot --type png -`, **base64'd over SSH** (raw PNG through an ssh pipe corrupts), decoded in Python.
- `stop()` — `tart stop` (+ optional `tart delete`).
- **Concurrency:** Apple SLA caps **2 macOS VMs/host** → a small warm lease pool, not elastic per-session. Keep one warm VM to hide the 30–60s clone+boot.

**Golden image (build once, snapshot):** clone `ghcr.io/cirruslabs/macos-sequoia-xcode:<PINNED-TAG>`, then bake: (1) `xcodebuild -downloadPlatform iOS` (~7GB runtime — host has none); (2) `idb_companion` from `main`; (3) SSH pubkey + disable password auth; (4) for Phase 4, code-signed `axctl` + TCC grants (Accessibility + Screen Recording) baked into `TCC.db` (SIP-off).

## Phases (dependency order)

- **P0 — Host + golden-image provisioning** *(unblocks everything; nothing runs on the host today — tart/idb/iOS-runtime all absent).* Install tart, clone+pin the xcode image, bake the iOS runtime + idb-from-main + SSH key, snapshot. Add `doctor.py` checks (tart / iOS runtime / idb) that fail loudly. **Deliverable:** a pinned golden VM that clones in ~30–60s.
- **P1 — `MacOSPlane` transport.** Fill the scaffold (`run_sync`/`run_bg`/`upload`/`start`/`screenshot`/`stop`); add `macos_*` config via the existing `_env()` `INSPECTOR_*`/`LOOPBACK_*` fallback. Smoke-test with `macos_host=localhost` to iterate without paying tart boot. **Deliverable:** working clone/boot/ip + ssh/scp + base64 screenshot.
- **P2 — Thinnest end-to-end slice** *(the milestone gate).* `examples/sample-buggy-ios/` SwiftUI project → boot → **one clean screenshot into SoM** → **one idb tap that lands** → **one captured log**. Implement in testable order: `screenshot` (no crop — simctl returns only the framebuffer) → **`screen_size` returns device POINTS (e.g. 393×852), NOT PNG pixels** → `input` (idb tap, focus-before-type) → `is_ready` (`simctl bootstatus`) → `logs` (`simctl spawn log stream --predicate`) → `launch`. **Deliverable:** green vertical slice with the point-vs-pixel contract verified.
- **P3 — Hybrid grounding + `rendered_elements` oracle.** Add the `detect_elements` hook (core 6 lines) + iOS a11y parser + OmniParser fallback-merge + per-kit builder registry (extend `detect.py`, which currently `FileNotFoundError`s on non-JS projects). **Deliverable:** iOS reaches the missing-element-oracle parity web/Electron have; SwiftUI/UIKit/RN/Flutter all boot.
- **P4 — Native `Surface.MACOS`** *(follow-up, same VM).* `axctl` Swift helper (dump/shot/click/type via AXUIElement + CGEvent + `screencapture -l`), TCC grants baked in, `adapters/macos.py`. Live-test the open question: does `screencapture -l` return real pixels in a `--no-graphics` guest (else VNC-framebuffer fallback)?

## Top risks

1. **Point-vs-pixel click bug (highest)** — simctl screenshot is PIXELS (1179×2556 @3x); idb taps are POINTS (393×852). `screen_size()` MUST return points or every click lands ~3× off-screen. Verify in P2 against a known button.
2. **idb supply chain** — the only pip/brew idb is the stale Aug-2022 v1.1.8 that breaks on modern Xcode (the host's companion already throws class-duplication warnings). Build from `main`, bake into the golden image, gate behind a doctor check.
3. **Headless blank frames** — simctl over bare SSH is blank without an auto-login Aqua session (keep auto-login + `caffeinate`); macOS `screencapture` in `--no-graphics` *may* be black (P4 live-test, VNC fallback).
4. **2-VM/host cap** — iOS concurrency hard-capped at 2/host; scale = more Macs / cloud Apple-silicon. Warm pool + accept for M3.
5. **RN/Flutter a11y blind spots** — keep OmniParser as the action source of truth; `rendered_elements()` self-disables on a degenerate tree.
6. **Binary PNG over SSH** — base64 it. **7GB runtime per session** — bake once. **TCC/SIP schema drift** (P4) — dump the real schema in the image.

## Files touched
`inspector/adapters/ios.py`, `adapters/base.py`, `adapters/desktop.py` (pattern), `planes/macos.py`, `planes/base.py`, `models.py` (Surface, later `Surface.MACOS`), `config.py` (`macos_*`), `adapters/__init__.py` (registry), `launch/detect.py` (native arm), `infra/macos-tart/`, `examples/sample-buggy-ios/`.
