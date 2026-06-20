# 11 — Implementation Steps (build-ready)

Every part broken into ordered, concrete steps with the exact APIs/commands to call. This is the granular companion to [08 — Build Plan](08-roadmap.md) (the inventory) and [02 — Architecture](02-architecture.md) (the shape). Items to confirm against pinned versions are marked **[VERIFY]**. A concrete API cheat-sheet is in the [Appendix](#appendix--concrete-api-cheat-sheet).

Pinned baselines used below: FastMCP 2.x · `e2b-desktop` Python v2.x · MCP spec 2025-11-25 · OmniParser V2 (microsoft/OmniParser master).

---

## Part A — Project scaffold & data models

1. `pyproject.toml` with deps: `fastmcp`, `e2b-desktop`, `pydantic`, `httpx`, `pillow`, `websocket-client` (CDP), `replicate` *or* local OmniParser (`torch`, `ultralytics`, `transformers`). Pin exact versions.
2. `loopback/models.py` — pydantic models from [06 — Data Schema](06-data-schema.md): `Session`, `Element`, `Action`, `Finding`, `Run`. Add ID factories (`ses_`, `run_`, `fnd_`, `trc_`).
3. `loopback/config.py` — env (`E2B_API_KEY`, OmniParser endpoint), surface registry, caps.
4. Stub `~/.loopback/sessions/<id>/` writer (trace dirs) — wire in Part F.

## Part B — Shared core: MCP server skeleton

1. `loopback/server.py`: `mcp = FastMCP("LoopBack")`. Keep `stateless_http=False`.
2. **State**: hold the live sandbox/session in a `lifespan` async context manager (one shared sandbox) **or** a module-global dict keyed by `session_id` (for multiple). Stdio = one long-lived process, so globals persist.
   ```python
   @asynccontextmanager
   async def lifespan(server):
       sessions = {}
       try: yield {"sessions": sessions}
       finally:
           for s in sessions.values(): s.sandbox.kill()
   ```
3. Register tools with `@mcp.tool`; access state via `ctx.lifespan_context["sessions"]` (declare `ctx: Context`).
4. **Image returns**: `from fastmcp.utilities.types import Image` → return `Image(data=bytes(png), format="png")`. Mix with text by returning a `list`. Structured data → return a `dict`/model (auto `structuredContent`) or `ToolResult(content=[...], structured_content={...})`.
5. `mcp.run()` (stdio default). **Log to stderr only** — any stdout `print()` corrupts JSON-RPC.
6. Register in clients:
   - Claude Code: `claude mcp add --transport stdio --scope project loopback --env E2B_API_KEY=xxx -- python /abs/loopback/server.py` (note the `--` separator).
   - `.mcp.json` / Cursor `~/.cursor/mcp.json`: `{"mcpServers":{"loopback":{"command":"python","args":["server.py"],"env":{"E2B_API_KEY":"${E2B_API_KEY}"},"timeout":600000}}}`. Set a **high `timeout`** (ms) — loops are slow.

## Part C — Shared core: sandbox + computer-use tools

1. `loopback/sandbox.py` wraps `e2b_desktop.Sandbox`:
   - Create: `Sandbox.create(resolution=(1280,800), timeout=3600)` (timeout in **seconds**).
   - Start stream (for the dashboard/VNC): `desktop.stream.start()`; `desktop.stream.get_url()`.
   - **Keep-alive**: call `desktop.set_timeout(600)` periodically during long runs or the sandbox dies mid-task.
   - Teardown: `desktop.kill()` (also in lifespan `finally:`).
2. Computer-use wrappers (exact E2B method names — note `move_mouse`, not `mouse_move`):
   `desktop.screenshot()` → `bytearray`; `left_click/double_click/right_click(x,y)`; `move_mouse(x,y)`; `drag((x1,y1),(x2,y2))`; `scroll(direction,amount)` **[VERIFY sign/sig]**; `write(text)`; `press(key|list)`; `get_screen_size()`.
3. Run a background process (the dev server) + stream logs:
   ```python
   handle = desktop.commands.run("npm run dev", background=True, cwd="/home/user/app",
                                 envs={"PORT":"5173"}, on_stdout=cb, on_stderr=cb)
   # handle.pid, handle.kill();  do NOT call handle.wait() on the main thread (blocks)
   ```
4. Upload the repo: `desktop.files.write(path, str|bytes)` per file, or `commands.run` a `tar` extract for a dir. **[VERIFY]** batch `files.write_files`.

## Part D — Shared core: perception (OmniParser → Set-of-Mark)

1. `loopback/perception/detector.py`. Choose run mode:
   - **Self-host** (recommended for loop latency): run OmniParser's FastAPI server (`omnitool/omniparserserver`) on a GPU box; POST screenshots. ~0.6–0.8 s/frame on A100/4090.
   - **Replicate** (no infra): `replicate.run("microsoft/omniparser-v2", input={"image":..., "imgsz":640, "box_threshold":0.05, "iou_threshold":0.1, "use_paddleocr":True})`. ~$0.0064/run, ~29 s incl. cold start. **[VERIFY]** output key names.
2. Local API path (if self-hosting): `get_yolo_model`, `get_caption_model_processor`, `check_ocr_box`, then `get_som_labeled_img(..., BOX_TRESHOLD=0.05, output_coord_in_ratio=True, ...)` — note `BOX_TRESHOLD` is **literally misspelled**.
3. Output = 3-tuple: `(som_image_b64, label_coordinates, parsed_content_list)`. Each element dict: `{type:"text"|"icon", bbox:[x1,y1,x2,y2] (ratio 0–1), interactivity:bool, content:str, source:str}`. **SoM index = list index `i`** (the number drawn).
4. `perception/som.py` — render numbered boxes with PIL from the element list (already returned as `som_image_b64`; reimplement only to restyle). Rescale ratios → pixels with `get_screen_size()`.
5. **Click target** = bbox center in pixels: `cx=int((x1+x2)/2*W)`, `cy=int((y1+y2)/2*H)` → `desktop.left_click(cx,cy)`. **Re-parse after every action** — coords are ratios of the *current* screen.

## Part E — Shared core: the loop tools

1. `observe(session_id)` → screenshot bytes → detector → return `Image(som_png)` + `structuredContent={elements, logs_since_last, state}`.
2. `act(session_id, {type,target_id?,text?,coords?})` → map `target_id`→bbox center→E2B input; **screenshot again**; diff before/after to set `changed`; return post-action `Image` + logs + `changed`. This **verify-after-act** is the core reliability mechanism (no DOM).
3. `verify(session_id, expectation)` → `observe` + fold in deterministic log-error check; host judges; return `{passed, evidence, confidence}`.
4. `launch_app(repo_path, dev_command?)` → Part G/H adapter (detect → boot → readiness) → returns `session_id` + status. Long-running → use Tasks (Part I).
5. `get_findings`, `stop` (teardown + flush trace).

## Part F — Shared core: detection, findings, trace, guardrails

1. `detection.py` — **deterministic first**: parse the log tap (stdout/stderr/logcat/idevicesyslog) for crash/exception/error markers; classify. (Web/Electron: also CDP console/network — Part G2.) Add axe-core (Part G3), pixel-diff + layout geometry later.
2. `findings.py` — synthesize constrained-JSON `Finding` (see [05](05-detection-and-feedback.md)) with `confidence` (deterministic=high, visual=lower).
3. `trace.py` — write `~/.loopback/sessions/<id>/`: `actions.jsonl` (append-only), `frames/frame_NNNN.png`, `logs.jsonl`, `findings/*.json`, `session.json`, `run.json`. **The action log is also the deterministic re-run script** for fix verification.
4. `loop.py` guardrails: iteration/cost/wall-clock caps; **no-progress detection** = hash `(action, post-screenshot, logs)`, repeated identical → escalate; **confidence gate** = K-sample the host judgment for visual findings; terminal = **open PR/draft, never auto-merge**.

## Part G — Web adapter

1. **Detect** (`launch/detect.py`): package manager from lockfile (`bun.lockb→bun`, `pnpm-lock.yaml→pnpm`, `yarn.lock→yarn`, `package-lock.json→npm`; honor `packageManager` field). Framework via ordered matcher (Expo→Next→SvelteKit→Astro→Vite→CRA): strongest dep signal + config file. **Prefer `scripts.dev`/`scripts.start`** over inferring the binary; framework table is the fallback + the port hint.
2. **Readiness** (`launch/readiness.py`): `detect-port` → pick free port → launch with `--port realPort --host 0.0.0.0`. Then race (a) `wait-on` `http-get://127.0.0.1:PORT/` (use **http-get**, accept 3xx via `validateStatus`, 60–90s timeout) and (b) log-pattern (`ready in \d+ ms`, `➜ Local: (https?://\S+)`) — capture the URL from the match; abort early on `EADDRINUSE`/`Error:`/process exit. Ready = HTTP probe passes.
3. **Browser launch**: `google-chrome --app=URL --window-position=0,0 --window-size=1280,800 --no-first-run --disable-session-crashed-bubble --remote-debugging-port=9222 --user-data-dir=/tmp/loopback-profile` (background). Prefer **`--app`** over `--kiosk` (kiosk overrides window-size). Fallback geometry: `wmctrl -r :ACTIVE: -e 0,0,0,1280,800`.
4. **Console/network capture (no Playwright)**: CDP over raw WebSocket — GET `http://localhost:9222/json` for `webSocketDebuggerUrl`; send `Runtime.enable` (→ `consoleAPICalled`/`exceptionThrown`), `Log.enable`, `Network.enable` (→ `loadingFailed`); read events on a thread. Fallback: inject `console`/`onerror` overrides via `Runtime.evaluate`.
5. **(optional)** axe-core: inject CDN bundle via `Page.addScriptToEvaluateOnNewDocument`, `axe.run(document).then(r=>r.violations)`. rrweb: inject recorder, drain `window.__rrwebEvents`.

## Part H — Electron adapter

1. **Display**: E2B XFCE already has `$DISPLAY`. If headless: `Xvfb :99 -screen 0 1280x800x24 &` / `xvfb-run -a electron .`.
2. **Detect**: `electron` devDep + `main` field / `electron-builder.yml` / `forge.config.js`. Dev command from `scripts`.
3. **Launch**: `ELECTRON_DISABLE_SECURITY_WARNINGS=1 electron . --no-sandbox --disable-gpu --disable-dev-shm-usage --remote-debugging-port=9223`. **`--no-sandbox` is mandatory** in containers; `--disable-gpu` avoids "GPU process isn't usable. Goodbye."
4. **Window ready/geometry**: `until xdotool search --name "AppName"; do sleep 0.5; done` → `xdotool windowactivate/windowmove/windowsize` (or `wmctrl`). Match `--name` and/or `--class` **[VERIFY WM_CLASS per app]**. Gate on mapped/visible before screenshot.
5. **Logs**: main process = the `electron .` process stdout/stderr (capture via background `commands.run`). Renderer console = `--remote-debugging-port=9223` + same CDP pipeline as Part G4 (for apps you can't modify) — or in-app `webContents.on('console-message', …)` if you control source.

## Part I — Long-running ops (MCP Tasks)

1. Declare server capability `tasks` + per-tool `execution.taskSupport="optional"` (never `"required"` unless you own the client — few clients implement Tasks yet).
2. `launch_app`/agent-loop return `CreateTaskResult` (`{task:{taskId,status:"working",pollInterval,ttl,...}}`) immediately; keep a durable task store.
3. Implement `tasks/get` (status), `tasks/result` (blocks until terminal, attach `_meta["io.modelcontextprotocol/related-task"]`), `tasks/list`, `tasks/cancel`. Statuses: `working→(input_required)→completed|failed|cancelled`.
4. **Fallback**: also support synchronous calls + `await ctx.report_progress(progress,total)` — this is what works in clients without Tasks today. **[VERIFY]** whether FastMCP `@mcp.tool(task=True)` wires to protocol `tasks/*` or only worker offload.

## Part J — Android adapter (Redroid plane)

1. **Host prep (most fragile)**: `apt install linux-modules-extra-$(uname -r)`; `modprobe binder_linux devices="binder,hwbinder,vndbinder"`; `modprobe ashmem_linux` (newer kernels use memfd). Persist via `/etc/modules-load.d/`. **Cannot run on stock macOS Docker / WSL2 / most managed k8s** — needs a Linux host/VM whose kernel has binder.
2. **Run container**: `docker run -itd --privileged -v ~/redroid-data:/data -p 5555:5555 redroid/redroid:12.0.0_64only-latest [androidboot.redroid_width=1080 ... gpu_mode=host]`. Distinct host ports per instance for parallelism. Prefer an **ARM64 host** to avoid ARM-on-x86 translation (`libndk_translation`, the most fragile x86 part).
3. **Connect/install/launch**: `adb connect localhost:5555`; `adb install -r -t app.apk` (AAB→use `install-multiple`/bundletool); `adb shell am start -n pkg/.MainActivity` (resolve via `cmd package resolve-activity --brief`).
4. **Screenshot**: `adb exec-out screencap -p > screen.png` (use `exec-out`, not `shell`).
5. **Input**: `adb shell input tap x y` / `input swipe x1 y1 x2 y2 dur` / `input text "a%sb"` (`%s`=space) / `input keyevent 66`.
6. **Logs/crash**: `adb logcat -c` before; `adb logcat -b crash -d` after; `--pid=$(adb shell pidof -s pkg)` (empty pid = crashed).
7. **Build APK** (separate Linux build sandbox, JDK 17 + Android SDK): RN/Expo `npx expo prebuild -p android && ./gradlew assembleDebug`; native `./gradlew assembleDebug`; EAS `eas build -p android --profile preview --local` (force APK not AAB). Pre-warm Gradle cache.

## Part K — iOS adapter (macOS plane) ⚠️

1. **Host (hard macOS requirement)**: Xcode + `xcode-select --install`; `xcodebuild -runFirstLaunch`. simctl/idb/xcodebuild are Xcode-only — never Linux.
2. **Boot sim**: `xcrun simctl list devices --json`; `simctl create`/`simctl boot <UDID>`; `simctl bootstatus <UDID> -b` (block).
3. **Install/launch**: `simctl install booted MyApp.app`; `simctl launch --console-pty booted com.example.MyApp` (captures stdout).
4. **Screenshot/video**: `simctl io booted screenshot screen.png`; `recordVideo`.
5. **Input via idb** (simctl can't tap): `brew install idb-companion`, `pip install fb-idb`; `idb_companion --udid <UDID>` on the Mac; then `idb ui tap x y` / `ui swipe` / `ui text` / `ui key 40` / `ui button HOME`. **`idb ui describe-all`** returns the a11y tree (labels+frames in points) → resolve targets by label instead of pixel-guessing. Sim only; flaky on real devices.
6. **Logs/crash**: `simctl spawn booted log stream --predicate 'subsystem=="com.example.MyApp"'`; crash `.ips` files land on the **host** at `~/Library/Logs/DiagnosticReports/` — poll after action sequences.
7. **Build for simulator** (host): RN/Expo `npx expo run:ios`; native `xcodebuild -scheme MyApp -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build` → `.app` under `Debug-iphonesimulator/`. EAS sim profile yields a `.tar.gz` `.app`.
8. **Hosting**: local Mac mini (dev) → cloud Mac (MacStadium/AWS `mac`, 24h min billing, $100s/mo) → Corellium (real-iOS ARM, highest fidelity/cost). Default = **Simulator + idb**; reserve Corellium for device-level fidelity.

## Part L — Planes & lifecycle

1. **Linux plane** (`planes/linux.py`): E2B Desktop provisioning/pooling/teardown for web/Electron; Redroid container manager for Android (ports, modules check).
2. **macOS plane** (`planes/macos.py`): cloud-Mac/Corellium pool behind the same `SurfaceAdapter` interface.
3. **Lifecycle**: one sandbox per session; warm pool + recycle; `set_timeout` keep-alive; always teardown.

## Part M — Detection depth & dashboard (later)

1. Visual: pixel-diff (`pixelmatch`) → host-VLM judgment, confidence-gated.
2. Layout anomalies: element-bbox geometry (overlap/off-screen/truncation) from the detector output.
3. Exploratory: crash/invariant-oracle crawling only (research-hard — [05](05-detection-and-feedback.md)).
4. Dashboard: pure frontend over the trace format ([07](07-dashboard.md)) — replay = scrub `actions.jsonl` + swap `frames/` + sync `logs.jsonl`.

---

## M0 acceptance test (proves the core)

From Claude Code on a sample web app with a silently-failing Save button: `launch_app` → `observe` (numbered screenshot) → `act` click #N → `changed:false` + log error → reproducible `Finding` → host fixes → re-verify `changed:true` → trace written → ends in a PR. One unattended pass = thesis holds.

---

## Appendix — concrete API cheat-sheet

**FastMCP**: `@mcp.tool`; `Image(data=bytes,format="png")` from `fastmcp.utilities.types`; `ToolResult(content=[...],structured_content={...})`; `await ctx.report_progress(progress,total)`; `lifespan` + `ctx.lifespan_context`; `mcp.run()`; stdout = JSON-RPC only.

**E2B Desktop**: `Sandbox.create(resolution=,timeout=secs)`; `.screenshot()→bytearray`; `.left_click/double_click/right_click(x,y)`; `.move_mouse(x,y)`; `.drag((x1,y1),(x2,y2))`; `.scroll(direction,amount)`; `.write(text)`; `.press(key)`; `.get_screen_size()`; `.commands.run(cmd,background=True,cwd=,envs=,on_stdout=)→CommandHandle(.pid,.kill())`; `.files.write(path,data)`; `.stream.start()/.get_url()`; `.set_timeout(secs)`; `.kill()`.

**OmniParser**: `get_som_labeled_img(...,BOX_TRESHOLD=0.05,output_coord_in_ratio=True)` → `(som_img_b64, label_coords, parsed_content_list)`; element `{type,bbox(ratio),interactivity,content,source}`; SoM idx = list index.

**Android/adb**: `adb connect host:5555`; `adb install -r -t a.apk`; `adb shell am start -n pkg/.Act`; `adb exec-out screencap -p`; `adb shell input tap|swipe|text|keyevent`; `adb logcat -b crash -d`.

**iOS/simctl+idb**: `simctl boot|install|launch --console-pty|io booted screenshot|spawn booted log stream`; `idb ui tap|swipe|text|key|button|describe-all`; crashes at `~/Library/Logs/DiagnosticReports/`.

## [VERIFY] before relying on
- FastMCP `report_progress(message=)` arg; `@mcp.tool(task=True)` → protocol vs worker offload.
- E2B `scroll` sign/signature; `files.write_files` batch; `Sandbox.connect`.
- Replicate OmniParser output JSON keys + defaults.
- Next.js/Expo exact "ready" banner strings (match `https?://\S+` loosely).
- Electron per-app WM_CLASS and GPU flags; `detect-port` `waitPort` signature.
- AGPL licensing on OmniParser YOLOv8 weights for a hosted product.

## Sources
Consolidated in [10 — Research Notes](10-research-notes.md); primary references: [FastMCP docs](https://gofastmcp.com/servers/tools), [MCP Tasks spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks), [E2B Desktop](https://github.com/e2b-dev/desktop), [OmniParser](https://github.com/microsoft/OmniParser), [Redroid docs](https://github.com/remote-android/redroid-doc), [idb](https://fbidb.io/docs/commands/), [Claude Code MCP](https://code.claude.com/docs/en/mcp).
