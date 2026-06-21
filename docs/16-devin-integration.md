# 16 — Devin AI integration

Two directions, both built.

## A. Inspector → Devin ("Fix with Devin" button)

Hand a Bug Ledger issue to Devin; it opens a PR; re-run auto-verifies the fix.

1. **Get a Devin API key.** In Devin (https://app.devin.ai) → **Settings → API Keys**
   (you need an org admin / a service account). Create a key — it starts with `apk_`
   (personal `apk_user_*` or service `apk_*`). Devin's API is a **paid** feature (ACU-based);
   keys live under the org's API settings. Docs: https://docs.devin.ai/api-reference/authentication
2. **Set it:** `DEVIN_API_KEY=apk_...` in `.env` (optionally `INSPECTOR_DEVIN_MAX_ACU` to cap cost).
3. **Use it:** on the dashboard Bug Ledger tab, click **Fix with Devin** on any issue — or
   call the `fix_with_devin(signature)` MCP tool. It starts a Devin session
   (`POST /v1/sessions`), marks the issue `fixing`, and shows a **Devin working ↗** link.
   The dashboard polls `devin_status` (capped at 10 min) and shows **PR ↗** when ready.
4. **Close the loop:** after the PR merges, re-run `test_app` — the issue drops out of the
   latest run and the ledger flips it to **verified**.

## B. Devin → Inspector (Devin tests its own fix)

Devin is an MCP **client** — give it Inspector's tools so it can `test_app` / `get_findings`
after it fixes something.

1. **Run Inspector over HTTP** (it's stdio by default):
   `python -m inspector.server --http --host 0.0.0.0 --port 8765`
   (or `INSPECTOR_TRANSPORT=http`). Endpoint: `http://<host>:8765/mcp`.
2. **Expose it** (Devin is in the cloud, localhost isn't reachable): tunnel with
   `ngrok http 8765` or `cloudflared tunnel --url http://localhost:8765`.
3. **Register in Devin:** Settings → Connections → **MCP servers → Add a custom MCP** →
   transport **HTTP**, URL = the tunnel URL + `/mcp`, add an auth header if you put one in
   front. Click **Test listing tools** — Devin discovers `test_app`, `get_findings`,
   `bug_ledger`, etc. Docs: https://docs.devin.ai/work-with-devin/mcp

> Security: the HTTP server has no auth of its own — only expose it behind a tunnel with an
> access policy / auth header, never bind `0.0.0.0` on an untrusted network.
