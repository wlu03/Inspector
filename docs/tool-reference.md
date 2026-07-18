# MCP tool reference

_Generated from the server by `scripts/gen_docs.py`. Do not edit by hand;
run `python scripts/gen_docs.py` to regenerate._

The default `core` profile exposes 10 tools; `INSPECTOR_PROFILE=full` exposes all 25.

## Core tools (default profile)

| Tool | Kind | Description |
|---|---|---|
| `act` | write | Perform one action and return the post-action Set-of-Mark image + `changed` + logs. |
| `audit_dom` | write | Run a DETERMINISTIC DOM audit (web/Electron) and file any issues as findings. |
| `check` | write | Check for NEW runtime errors and return a screenshot. Three-valued; never a false pass. |
| `get_findings` | read-only | Return the findings collected this session (from the deterministic log tap). |
| `launch_app` | destructive | Boot the app in a sandbox and (by default) wait until it's interactive. |
| `launch_status` | read-only | Poll a background launch (from `launch_app(wait=false)`). |
| `observe` | read-only | Screenshot the running app and return a Set-of-Mark image + element list + recent logs. |
| `report_issue` | write | File a finding the HOST agent judged from the screenshot (host-as-brain). |
| `stop` | destructive | Tear down the sandbox (released first), then write the replay (html + video). |
| `test_app` | destructive | ONE CALL: launch the app in a VM, autonomously explore it, and return the bugs found. |

## Advanced tools (`INSPECTOR_PROFILE=full`)

| Tool | Kind | Description |
|---|---|---|
| `bug_ledger` | read-only | Every unique issue across all runs with its CURRENT fix status — the fix loop, closed. |
| `build_dashboard` | write | Aggregate EVERY past session into one static, replayable dashboard + serve it. |
| `devin_status` | external | Poll a Devin fix session; if it opened a PR, record `pr_url` on the issue. |
| `fix_finding` | read-only | Get the actionable fix context for one finding — the live agent fix loop. |
| `fix_with_devin` | destructive | Hand any surfaced issue to Devin AI — it opens a PR with the fix. |
| `get_run` | read-only | Full detail for one past session: meta, plan, findings (with fix prompts), counts. |
| `list_runs` | read-only | List past Inspector sessions (newest first) with verdict + findings + replay path. |
| `open_dashboard` | write | Build + serve the dashboard on localhost and return a clickable link. |
| `set_plan` | write | Record the overall test plan: the scenarios (app parts/flows/edge cases) to cover. |
| `test_app_parallel` | destructive | PLAN → DISPATCH → MERGE: a planner maps the app into parts, then a headless agent |
| `test_feature` | destructive | Cartographer — region-decomposed DETERMINISTIC bug sweep: "I built X, hand me fixes". |
| `test_report` | write | Return the full test run: per-scenario status + notes + findings, plus totals. |
| `update_finding_status` | write | Record fix-loop progress on a finding: open | fixed | verified | dismissed. |
| `update_scenario` | write | Record a scenario's outcome once you've tested it. |
| `verify_fix` | destructive | Re-verify ONE finding is fixed by replaying its exact repro on the current build. |
