# 06 — Data Schema

> **Design this now, build the viewer later.** In v0, write session artifacts to disk as structured JSON + a trace folder. It costs almost nothing and makes the dashboard ([07](07-dashboard.md)) pure frontend over an existing format — no retrofitting.

## Core entities

```jsonc
// A single verification session against one running app
Session {
  "id": "ses_...",
  "repo_path": "/path/to/project",
  "surface": "web | electron | android | ios",
  "dev_command": "npm run dev",
  "sandbox_handle": "e2b_...",
  "app_pid": 12345,
  "state": "READY | INTERACTING | DETECTING | REPORTING | IDLE | TORN_DOWN | ERROR",
  "task_id": "tsk_...",
  "goal": "verify the checkout flow",
  "findings": ["fnd_..."],
  "trace_id": "trc_...",
  "created_at": "2026-06-20T...",
  "ended_at": "2026-06-20T..."
}

// One detected/labeled element on a screen (from the detector → Set-of-Mark)
Element {
  "id": 7,                       // the SoM number the host selects
  "label": "Save",
  "role": "button",
  "bbox": [x, y, w, h]
}

// One action taken in the loop (the replay timeline is a list of these)
Action {
  "seq": 12,
  "type": "click | double_click | type | scroll | drag | key | wait",
  "target_id": 7,                // or null if coords-based
  "coords": null,
  "text": null,
  "ts": "2026-06-20T...",
  "result": "ok | no_change | error",
  "changed": true,
  "screenshot_before": "frame_0012.png",
  "screenshot_after": "frame_0013.png",
  "logs": ["..."]
}

// A detected issue (see 05 for the synthesis format)
Finding {
  "id": "fnd_...",
  "session_id": "ses_...",
  "summary": "...",
  "severity": "low | medium | high | critical",
  "confidence": "high | medium | low",
  "repro": ["..."],
  "expected": "...",
  "actual": "...",
  "logs": ["..."],
  "suspected_area": "...",
  "screenshot_refs": ["frame_0012.png", "frame_0013.png"],
  "trace_id": "trc_...",
  "status": "open | fixed | verified | dismissed",
  "pr_url": null
}

// A run = one autonomous loop invocation (may span multiple verify passes)
Run {
  "id": "run_...",
  "session_id": "ses_...",
  "trigger": "host_request | ci | scheduled",
  "passed": false,
  "findings": ["fnd_..."],
  "iterations": 6,
  "cost_tokens": 48000,
  "duration_ms": 92000,
  "pr_url": null,
  "created_at": "..."
}
```

## On-disk trace layout

```
~/.loopback/sessions/<session_id>/
  session.json            # the Session object
  run.json                # the Run summary
  findings/
    fnd_xxx.json
  trace/
    actions.jsonl         # one Action per line — the replay timeline
    frames/
      frame_0001.png      # SoM-annotated screenshots, per action
      ...
    logs.jsonl            # timestamped log lines (for timeline sync)
    network.har           # optional (web)
    session.rrweb.json    # optional (web visual replay)
```

## Why this shape

- **`actions.jsonl` + `frames/` + `logs.jsonl` = the replay.** The dashboard scrubs `actions.jsonl`, shows the matching frame, and syncs log lines by timestamp. No new capture needed.
- **`actions.jsonl` is also the deterministic re-run script** for fix verification ([05](05-detection-and-feedback.md)).
- **Append-only JSONL** for actions/logs keeps streaming cheap and crash-safe.
- **Stable IDs** (`ses_`, `run_`, `fnd_`, `trc_`) make everything linkable in the dashboard and in PR comments.
