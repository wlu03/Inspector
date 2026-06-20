# 12 — Accounts & Services

Every external platform Inspector needs, grouped by phase. Most are gated behind a surface or the productization phase — **v0 needs only two new signups.**

> **Current scope (decided):** build all four surfaces (Web, Electron, Android, iOS) as a personal/dev tool. **Not** productionizing yet — no hosting, no payments, no hosted dashboard. So the [Productization (v2)](#productization-v2--hosted-dashboard-paid-tier) section is **deferred**; everything above it is in scope.
>
> **Required signups for the full multimodal (pre-production) build:** E2B · Replicate · Docker Hub · a Linux VM you control (AWS Graviton / Hetzner, for Android) · a Mac (own or cloud, for iOS) · free Apple ID. You already have Claude Code/Cursor + GitHub.
>
> **Real footprint:** cloud E2B+Replicate, a Linux box for Android (not your Mac — Redroid can't run on macOS Docker), and a Mac for iOS. Web/Electron need no local machine.

## v0 — to prove the core loop (web/Electron)

| Platform | Required? | Credential | Why | Cost |
|---|---|---|---|---|
| **E2B** (e2b.dev) | ✅ Required | `E2B_API_KEY` | Linux desktop sandbox (boot app + screenshot + input) | Free tier + usage-based |
| **Replicate** (replicate.com) | ✅ Required* | `REPLICATE_API_TOKEN` | Hosted OmniParser V2 (screenshot → elements) | ~$0.0064/run, pay-as-you-go |
| Claude Code / Cursor | ✅ (have it) | — | The host coding agent Inspector plugs into | existing |
| GitHub | ✅ (have it) | `gh` auth / token | The "open a PR, never auto-merge" guardrail | free |
| **Anthropic API** (console.anthropic.com) | ⬜ Optional | `ANTHROPIC_API_KEY` | Only if Inspector makes its *own* LLM calls (visual-diff judgment, K-sample confidence). The core design delegates grounding/judgment to the host agent, so **not needed for v0**. | usage-based |

\* Replicate is required *only if you don't self-host OmniParser* (next section). For v0, Replicate is the cheaper/faster path — skip running your own GPU.

## If you self-host OmniParser instead of Replicate

Pick **one** GPU host (avoids per-run fees, lowers loop latency, but you operate infra). Needed once latency/volume matters.

| Platform | Credential | Notes |
|---|---|---|
| **Modal** (modal.com) | API token | Serverless GPU, scale-to-zero — best fit for an on-demand detector |
| **RunPod** / **Lambda** / **Fal** | API key | Cheaper sustained GPU; more ops |

> ⚠️ License flag: OmniParser's YOLOv8 detection weights are **AGPL**. Fine for internal/dev use; review before shipping Inspector as a hosted commercial product.

## Android surface (Milestone M2 — Redroid)

| Platform | Required? | Why | Cost |
|---|---|---|---|
| **Docker Hub** (hub.docker.com) | ✅ | Pull the `redroid/redroid` image (avoids anon rate limits) | free |
| **A Linux VM with kernel control** | ✅ | Redroid needs `binder`/`ashmem` kernel modules + `--privileged` — **managed container services / macOS Docker / WSL2 won't work** | VM cost |
| → **AWS EC2** (Graviton ARM64) | option | ARM64 avoids ARM-on-x86 translation; needs module support | hourly |
| → **Hetzner / bare-metal VPS** | option | Cheaper sustained; full kernel control | monthly |

## iOS surface (Milestone M3 — the cost cliff ⚠️)

| Platform | Required? | Why | Cost |
|---|---|---|---|
| **A macOS host** | ✅ (one of) | simctl/idb/Xcode are macOS-only — cannot run on Linux | varies |
| → Own Mac / Mac mini | option | Cheapest if owned | one-time |
| → **AWS EC2 Mac** | option | Cloud macOS | **24-hr minimum billing**, pricey |
| → **MacStadium** / **Scaleway Mac** / **MacinCloud** | option | Hosted Mac subscription | $100s/mo |
| → **Corellium** (corellium.com) | option | Virtualized *real* iOS (not simulator) — highest fidelity | enterprise $$$ |
| **Apple ID** (free) | ✅ | Download Xcode; simulator builds need no signing (`CODE_SIGNING_ALLOWED=NO`) | free |
| **Apple Developer Program** | ⬜ Optional | Only for **real devices** / TestFlight — *not* needed for simulator | $99/yr |
| **Expo / EAS** (expo.dev) | ⬜ Optional | Only if you use EAS *cloud* builds instead of local Gradle/xcodebuild | free tier + paid |

Default iOS path = **Simulator + idb on a Mac you control**; reserve cloud Mac / Corellium for scale or device fidelity.

## Productization (v2 — hosted dashboard, paid tier)

| Platform | Purpose | Example |
|---|---|---|
| **PyPI** (pypi.org) | Publish the `inspector` package | free |
| **Object storage** | Store trace artifacts (frames/logs) in hosted mode | Cloudflare R2 / AWS S3 |
| **App hosting + DB** | Run the control-plane service + dashboard | Fly.io / Render / Railway + Neon / Supabase |
| **Auth** | Multi-user dashboard | Clerk / Supabase Auth |
| **Stripe** | Payments / the paid tier | stripe.com |
| **Cloudflare** | (optional) tunnel so cloud agents reach a local dev server (Swarm-style) | free tier |

---

## TL;DR by phase

- **Start today (v0):** sign up for **E2B** + **Replicate**. That's it. (You already have Claude Code/Cursor + GitHub.)
- **Self-host the detector later:** add **Modal** (or RunPod/Lambda).
- **Android:** add **Docker Hub** + an **AWS/Hetzner Linux VM** with kernel control.
- **iOS:** add a **Mac** (owned, or AWS Mac / MacStadium / Corellium) + a free **Apple ID**.
- **Ship a product:** add **PyPI, R2/S3, Fly/Render + Neon, Clerk, Stripe**.
