# 04 — Core Loop

## The loop

```
launch → observe → [host decides] → act → verify-after-act → detect → report → (host fixes) → re-verify
```

1. **launch** — boot the app in the sandbox, wait until genuinely interactive.
2. **observe** — screenshot → element detector → Set-of-Mark; return annotated image + element list + recent logs.
3. **host decides** — the host coding agent (frontier VLM) picks the next action, referencing element IDs.
4. **act** — map ID → bbox center → input event (per surface). Return the post-action screenshot + `changed`.
5. **verify-after-act** — host confirms the screen changed as expected; re-ground/retry if not.
6. **detect** — run detection channels (logs + visual). Emit candidate findings.
7. **report** — structured finding + replay trace handed back to the host.
8. **host fixes & re-verifies** — host edits code, calls the loop again until green.

## Grounding: Set-of-Mark, not raw coordinates

- **Detector:** OmniParser V2 — YOLOv8 detects interactive elements, Florence-2 captions them. Cheap (CPU / small GPU), not a frontier LLM.
- **Set-of-Mark (SoM):** overlay numbered bounding boxes on the screenshot. The host model selects a **number**, which maps to a ground-truth bbox — far more reliable than predicting an `(x, y)`.
- **Alternative / upgrade path:** UI-TARS (end-to-end GUI grounding model) if SoM selection proves insufficient on a surface.
- **Fallback:** raw `coords` only when the detector misses an element (custom canvas/WebGL). Expect this to be the weak spot.

## Action space (8 primitives)

Standard computer-use action set, dispatched to the right backend per surface:

`click · double_click · type · scroll · drag · key · move · wait`

| Surface | Backend (input) | Backend (capture) | Log tap |
|---|---|---|---|
| Web | xdotool (browser) | scrot | dev-server stdout/stderr + (optional) browser console |
| Electron | xdotool | scrot | main/renderer stdout/stderr |
| Android | adb / UiAutomator | adb screencap | logcat |
| iOS | simctl / idb | simctl io screenshot | idevicesyslog |

E2B Desktop's SDK already exposes `screenshot()`, `left_click/double_click/right_click`, `move_mouse(x,y)`, `drag`, `scroll`, `write(text)`, `press(key)` — so the Linux input/capture layer is orchestration, not new code.

## Surface adapters (the core IP)

Each surface — **web, Electron, Android, iOS** — is a `SurfaceAdapter` implementing one interface (`launch · is_ready · screenshot · input · logs · teardown`), so the core loop is identical across all four. Adapters detect the project, boot it in the right runtime, confirm readiness, then expose capture/input/logs. The per-surface backends are tabulated above (under Action space); the detection + readiness specifics follow.

### Framework / command detection
- Parse `package.json` scripts, lockfiles, config files (`vite.config`, `next.config`, Expo `app.json`, `electron` in deps).
- Explicit `dev_command` override always wins.
- Prior art to lean on: `npm-dev-mcp` auto-discovers package.json + dev scripts and tracks ports via `lsof`/`netstat`.

### Readiness detection (genuinely hard — many edge cases)
Compose multiple signals; only emit `READY` when the app is truly interactive:
- **web:** `wait-on` for HTTP 2xx on the dev port + `detect-port`.
- **Electron:** window mapped on the X display (`xdotool search --name`).
- **Android:** `adb wait-for-device` + focused activity.
- **all:** log-pattern matcher ("Local: http://…", "compiled successfully", "Metro waiting on…").

## Reliability strategy (no DOM, pure computer-use)

1. **Grounding-by-ID** (SoM) over coordinate-guessing.
2. **Verify-after-act** on every action (the screen-changed check).
3. **Coarse, observable actions** — one at a time, observe between each.
4. **Log tap for the invisible** — silent errors the pixels can't show (see [05](05-detection-and-feedback.md)).
5. **No-progress detection** in the loop controller to stop thrashing.
