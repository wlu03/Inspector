# 03 — MCP Contract

## SDK & transport

- **SDK:** FastMCP (Python) or the official TS SDK. Pick by where the element-detector and sandbox SDKs are easiest (E2B has both Python and JS SDKs).
- **Transport:** stdio for local/IDE use; streamable HTTP for hosted/cloud-agent use.
- **Long-running ops:** use the MCP **Tasks** primitive (2025-11-25 spec) — "call-now, fetch-later." A tool that can't return immediately returns a `taskId`; the client polls `tasks/get` until a terminal state (`working → completed | failed | input_required | cancelled`). The same `progressToken` drives progress bars. **Build a polling fallback** — client support for Tasks still varies.

## Tool surface

Keep tools dumb and composable — the host agent supplies all reasoning.

```
launch_app(repo_path, surface?, dev_command?) -> { session_id, status, task_id }
   # detect framework + dev command, boot sandbox, run app, wait for ready
   # long-running → returns task_id; poll until status = READY

observe(session_id) -> {
     screenshot_som,            # base64 PNG with numbered element boxes
     elements: [{ id, label, role, bbox }],   # from the detector
     logs_since_last: [ ... ],  # stdout/stderr/console/logcat tail
     state                      # current route / window title / activity
   }

act(session_id, action) -> { ok, screenshot_som_after, logs, changed }
   # action = { type, target_id?, text?, coords? }
   # type ∈ click | double_click | type | scroll | drag | key | wait
   # ALWAYS returns the post-action SoM screenshot + whether the screen changed
   #   → this is verify-after-act; lets the host self-correct without a DOM

verify(session_id, expectation) -> { passed, evidence, confidence }
   # expectation in natural language, e.g. "a toast 'Saved' appears"

report_issue(session_id, finding) -> { finding_id, trace_id }
get_findings(session_id) -> [ Finding ]
list_sessions() -> [ Session ]
stop(session_id) -> { ok }
```

### Why `act` returns the screenshot

With no DOM to assert against, reliability is bought back through **verify-after-act**: every action returns the consequence (new SoM screenshot + `changed` flag + fresh logs). The host sees what happened and re-grounds/retries if the screen didn't change as expected. This is the single most important reliability mechanism in the loop.

## Session lifecycle (state machine)

```
CREATED
  → PROVISIONING (sandbox)
  → INSTALLING (deps)
  → LAUNCHING (dev command)
  → WAITING_READY
  → READY  ⇄  INTERACTING  →  (DETECTING)  →  REPORTING
  → IDLE
  → TORN_DOWN
            ↘ ERROR (from any state) → REPORTING
```

The **Session** is the long-lived object. It owns: the sandbox handle, the running app PID, the log stream, the findings list, and the replay-trace recorder. Each session maps to a Task; `launch_app` returns immediately with `task_id`; the host polls until `READY`.

## Permissions & safety

- LoopBack runs untrusted user code (the dev build) — always inside the sandbox, never on the host.
- The host agent's edits happen in its own workspace; LoopBack only *observes and operates* the running app.
- Terminal output of an autonomous run is a **findings report + PR/draft — never an auto-merge** (see [05](05-detection-and-feedback.md)).
