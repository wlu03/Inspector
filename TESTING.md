# Testing LoopBack with a real agent

How to do tasks **#6** (validate the real agent loop in Claude Code) and **#7**
(run on real-world web apps).

## Prereqs (once)

```bash
cd /Users/wesleylu/Projects/Research/LoopBack
python -m venv .venv && . .venv/bin/activate
pip install -e ".[all]"
cp .env.example .env            # add E2B_API_KEY + REPLICATE_API_TOKEN
python -m loopback.doctor       # confirm both keys + SDKs OK
```

The MCP server loads `.env` from next to the package, so it works no matter
which directory Claude Code launches it from.

---

## #6 — Validate the real agent loop in Claude Code

The point: let an **actual Claude model** read the Set-of-Mark screenshot, pick
the element, drive the loop, and fix the code — instead of our script that
already knows the answer.

### 1. Register LoopBack as an MCP server

```bash
claude mcp add --transport stdio --scope user loopback \
  -- /Users/wesleylu/Projects/Research/LoopBack/.venv/bin/loopback
```

(Or, if you open Claude Code with this folder as the project root, the included
`.mcp.json` is picked up automatically.) Restart Claude Code so it connects, then
confirm with `/mcp` — you should see `loopback` with tools
`launch_app, observe, act, verify, get_findings, stop`.

### 2. Prompt the agent to drive the loop

In a Claude Code session, paste:

> Use the **loopback** MCP tools to test the app at
> `/Users/wesleylu/Projects/Research/LoopBack/examples/sample-buggy-app`.
> Steps: call `launch_app` on it; call `observe` and look at the numbered
> screenshot; identify and `act`-click the **Save** button; then `observe`/`verify`
> to check whether a "Saved" confirmation appears. If it doesn't, read the app
> source, find the bug, fix it, then **stop, re-launch, and re-verify** that Save
> now works. Report what you found and fixed.

### 3. What you're actually validating (watch for these)

- Does the model **pick the right element** (#N = Save) from the screenshot/element list?
- Does it **drive the multi-step loop** (observe → act → verify) without hand-holding?
- Does it **locate and fix** the bug in `examples/sample-buggy-app/main.js`?
- Does it **re-verify** correctly after the fix?

> **Note on the fix loop:** the app is uploaded into the sandbox at `launch_app`,
> so editing the local file does not change the *running* sandbox app. To confirm
> a fix, the agent must **stop and `launch_app` again** (re-upload). A future
> enhancement is hot-syncing the changed file; for now, re-launch.

If the agent does all of the above unattended, the core product is validated.
If it stumbles, note exactly where (element-picking vs. planning vs. fix-verify) —
that tells you what to harden next.

---

## #7 — Run on real-world web apps

Goal: prove launch/readiness/detection survive real apps (auth, routing, dense UIs).

### Quick smoke test (launch + detection only)

```bash
. .venv/bin/activate
python scripts/run_app.py /path/to/a/real/nextjs-app
python scripts/run_app.py /path/to/a/real/dashboard
```

This prints the detected elements and writes a replay (`replays/<id>/index.html`)
so you can eyeball detection quality on a real UI. Good starter apps: a fresh
`npx create-next-app`, an open-source admin dashboard, a Vite + React app.

### Full agentic test

Point the **#6** Claude Code prompt at the real app's path instead of the sample,
and give it a concrete goal ("verify the login flow", "add an item to the cart").

### What tends to break first (fix these as they show up)

- **Readiness**: a framework whose ready signal / port differs (see
  `loopback/launch/detect.py` `_FRAMEWORKS` and `web.py` `_host_port_args`).
- **Auth walls**: a login page blocks everything — the agent must log in first
  (computer-use can type credentials), or seed a session.
- **Dense detection**: many elements → noisier Set-of-Mark; see task #15.
- **Multi-page nav**: state across routes; the loop must re-observe after navigation.
