from __future__ import annotations

import os
from dataclasses import dataclass, field

# Pinned OmniParser V2 on Replicate (the bare slug 404s — a version is required).
DEFAULT_OMNIPARSER_REF = (
    "microsoft/omniparser-v2:"
    "49cf3d41b8d3aca1360514e83be4c97131ce8f0d99abfc365526d8384caa88df"
)

# Replicate-hosted vision-language model that drives the autonomous `test_app` loop
# (picks the next action from the Set-of-Mark screenshot + judges broken features).
# Pinned LLaVA-1.6; its inputs (image/prompt/max_tokens/temperature) match the driver.
# NOTE: open VLMs are weak at GUI action-selection — for high-quality autonomy use a
# stronger model (set INSPECTOR_DRIVER_REF) or drive via the host agent + run_test_session.
DEFAULT_DRIVER_REF = (
    "yorickvp/llava-v1.6-vicuna-13b:"
    "0603dec596080fa084e26f0ae6d605fc5788ed2b1a0358cd25010619487eae63"
)


def _load_dotenv() -> None:
    """Load a local .env into os.environ if python-dotenv is available.

    Searches the current working directory upward, so running the server or
    `python -m inspector.doctor` from the project root picks up `.env`.
    """
    try:
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True))
        # Also load the .env that sits next to the package, regardless of cwd — so
        # the MCP server finds the keys even when Claude Code launches it elsewhere.
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(pkg_root, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)
    except Exception:
        pass


def _env(*names: str, default: str | None = None) -> str | None:
    """First set environment variable among ``names``.

    INSPECTOR_* names are canonical; LOOPBACK_* are accepted as a legacy fallback
    (the product was renamed LoopBack -> Inspector). Pass the new name(s) first.
    """
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return default


@dataclass
class Config:
    """Runtime configuration, sourced from environment in `from_env`."""

    e2b_api_key: str | None = None
    replicate_api_token: str | None = None
    anthropic_api_key: str | None = None

    # Detector: "replicate" (hosted OmniParser) | "http" (self-hosted) | "local"
    detector_backend: str = "replicate"
    omniparser_endpoint: str | None = None
    omniparser_ref: str = DEFAULT_OMNIPARSER_REF

    # Driver: the brain for the one-call `test_app` autopilot. "replicate" only for now.
    driver_backend: str = "auto"  # auto → Claude when a key is present, else replicate
    driver_ref: str = DEFAULT_DRIVER_REF
    # Anthropic-brain model (when driver_backend="anthropic"). Cheaper than Opus by
    # default; override with INSPECTOR_DRIVER_MODEL (e.g. claude-haiku-4-5 = cheapest).
    driver_model: str = "claude-sonnet-4-6"

    # macOS/iOS plane (tart VM). If macos_host is set, connect to an already-running
    # Mac/guest over SSH and skip tart (dev: localhost). Else tart clones the golden image.
    macos_host: str | None = None
    macos_user: str = "admin"
    macos_ssh_key: str | None = None
    macos_base_image: str = "ghcr.io/cirruslabs/macos-sequoia-xcode:latest"
    macos_ios_udid: str | None = None
    # idb client binary. fb-idb breaks on Python 3.14 (asyncio.get_event_loop removed),
    # so point this at a py3.10-3.12 venv's idb: INSPECTOR_IDB_BIN=/path/idbvenv/bin/idb.
    ios_idb_bin: str = "idb"
    # Native macOS app to drive (name or bundle id) for Surface.MACOS — e.g. "Calculator".
    macos_app: str | None = None
    # flutter binary for Flutter iOS builds. The adapter runs build commands via a
    # login shell that may not have ~/flutter/bin on PATH — point this at it directly:
    # INSPECTOR_FLUTTER_BIN=/Users/you/flutter/bin/flutter.
    flutter_bin: str = "flutter"

    # Where mobile/desktop/native surfaces run: "local" = THIS host directly (no VM,
    # uses the local toolchains — simctl/idb, adb+emulator); "vm" = the tart/Redroid
    # planes. Local has no sandbox isolation (the app runs with your privileges) but
    # is far lighter. Web/Electron use the E2B Linux sandbox independently of this.
    execution: str = "local"

    # Android. Setting `android_package` switches the AndroidAdapter to ATTACH mode:
    # skip the source build and drive an already-installed app on a running emulator
    # (resolving its launch activity), instead of building+installing from repo_path.
    # `android_serial`/`android_avd` pick / boot the device; `android_runtime` =
    # "local" (AVD) or "redroid" (container plane).
    android_package: str | None = None
    android_activity: str | None = None   # optional; auto-resolved if omitted
    android_serial: str | None = None     # optional; else first running device, else boot AVD
    android_avd: str | None = None
    android_runtime: str = "local"

    # Sandbox
    sandbox_resolution: tuple[int, int] = (1280, 800)
    sandbox_timeout_s: int = 3600
    # Optional E2B template id/name. The stock desktop template ships Firefox, not
    # Chrome — point this at a custom template that pre-installs google-chrome to skip
    # the per-session install. None = stock template + runtime browser install.
    sandbox_template: str | None = None

    # Trace artifacts
    trace_root: str = field(
        default_factory=lambda: os.path.expanduser("~/.inspector/sessions")
    )

    # Loop guardrails
    max_iterations: int = 30
    max_wall_clock_s: int = 1800

    # Heartbeat capture: snapshot a frame every N seconds in the background so the
    # replay timeline stays dense even while the agent is idle/thinking. 0 disables.
    heartbeat_screenshot_s: float = 5.0

    # Session reaper: tear a session down after this many seconds with no tool
    # activity, or once it's older than sandbox_timeout_s (the sandbox dies anyway).
    # 0 disables the reaper. Guards against a host that crashes/forgets stop().
    session_idle_ttl_s: int = 600
    reaper_interval_s: int = 60

    # Host token cost: cap full SoM PNGs returned per session at the MCP boundary
    # (0 = unlimited). Past the cap, observe/act return the text element list only.
    max_images_per_session: int = 0

    # Local dashboard server: the port the MCP serves ~/.inspector/sessions on so a
    # finished test returns a clickable http://127.0.0.1:<port>/dashboard.html link.
    # Falls back to an ephemeral port if this one is taken.
    dashboard_port: int = 7321

    # Fire an OS desktop notification (with the dashboard link) when an autonomous
    # run finishes — nobody's watching the chat. Best-effort; set 0 to disable.
    notify: bool = True

    # Devin AI auto-fix: the "Fix with Devin" button on the Bug Ledger hands a finding
    # to Devin's API, which opens a PR. Needs a key (DEVIN_API_KEY, apk_*). max_acu and
    # the 10-minute poll cap bound cost/time per fix.
    devin_api_key: str | None = None
    devin_base_url: str = "https://api.devin.ai"
    devin_max_acu: int | None = None
    devin_poll_timeout_s: int = 600  # cap waiting on Devin at 10 minutes
    # Pin the GitHub repo Devin clones/opens PRs against ('owner/name'). Without this,
    # the target is auto-derived from the app-under-test's git remote, which can point
    # at an upstream/fork. Force every Devin push to our own repo instead.
    devin_repo: str | None = "wlu03/LoopBack"

    # MCP transport. "stdio" (default, for Claude Code/Cursor) or "http"/"sse" so a
    # REMOTE client (e.g. Devin, via its MCP marketplace) can reach Inspector over the
    # network. HTTP binds host:port/path; expose it with a tunnel for cloud clients.
    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    http_path: str = "/mcp"

    @classmethod
    def from_env(cls) -> "Config":
        _load_dotenv()
        return cls(
            e2b_api_key=os.getenv("E2B_API_KEY"),
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            detector_backend=_env("INSPECTOR_DETECTOR", "LOOPBACK_DETECTOR", default="replicate") or "replicate",
            omniparser_endpoint=_env("INSPECTOR_OMNIPARSER_URL", "LOOPBACK_OMNIPARSER_URL"),
            omniparser_ref=_env("INSPECTOR_OMNIPARSER_REF", "LOOPBACK_OMNIPARSER_REF", default=DEFAULT_OMNIPARSER_REF) or DEFAULT_OMNIPARSER_REF,
            driver_backend=_env("INSPECTOR_DRIVER", "LOOPBACK_DRIVER", default="auto") or "auto",
            driver_model=_env("INSPECTOR_DRIVER_MODEL", "LOOPBACK_DRIVER_MODEL",
                              default="claude-sonnet-4-6") or "claude-sonnet-4-6",
            macos_host=_env("INSPECTOR_MACOS_HOST", "LOOPBACK_MACOS_HOST"),
            macos_user=_env("INSPECTOR_MACOS_USER", "LOOPBACK_MACOS_USER", default="admin") or "admin",
            macos_ssh_key=_env("INSPECTOR_MACOS_SSH_KEY", "LOOPBACK_MACOS_SSH_KEY"),
            macos_base_image=_env("INSPECTOR_MACOS_IMAGE", "LOOPBACK_MACOS_IMAGE",
                                  default="ghcr.io/cirruslabs/macos-sequoia-xcode:latest")
            or "ghcr.io/cirruslabs/macos-sequoia-xcode:latest",
            macos_ios_udid=_env("INSPECTOR_IOS_UDID", "LOOPBACK_IOS_UDID"),
            ios_idb_bin=_env("INSPECTOR_IDB_BIN", "LOOPBACK_IDB_BIN", default="idb") or "idb",
            macos_app=_env("INSPECTOR_MACOS_APP", "LOOPBACK_MACOS_APP"),
            flutter_bin=_env("INSPECTOR_FLUTTER_BIN", "LOOPBACK_FLUTTER_BIN", default="flutter") or "flutter",
            execution=_env("INSPECTOR_EXECUTION", "LOOPBACK_EXECUTION", default="local") or "local",
            android_package=_env("INSPECTOR_ANDROID_PACKAGE"),
            android_activity=_env("INSPECTOR_ANDROID_ACTIVITY"),
            android_serial=_env("INSPECTOR_ANDROID_SERIAL"),
            android_avd=_env("INSPECTOR_ANDROID_AVD"),
            android_runtime=_env("INSPECTOR_ANDROID_RUNTIME", default="local") or "local",
            driver_ref=_env("INSPECTOR_DRIVER_REF", "LOOPBACK_DRIVER_REF", default=DEFAULT_DRIVER_REF) or DEFAULT_DRIVER_REF,
            sandbox_template=_env("INSPECTOR_E2B_TEMPLATE", "E2B_TEMPLATE"),
            session_idle_ttl_s=int(_env("INSPECTOR_SESSION_IDLE_TTL", "LOOPBACK_SESSION_IDLE_TTL", default="600") or "600"),
            reaper_interval_s=int(_env("INSPECTOR_REAPER_INTERVAL", "LOOPBACK_REAPER_INTERVAL", default="60") or "60"),
            max_images_per_session=int(_env("INSPECTOR_MAX_IMAGES", "LOOPBACK_MAX_IMAGES", default="0") or "0"),
            dashboard_port=int(_env("INSPECTOR_DASHBOARD_PORT", "LOOPBACK_DASHBOARD_PORT", default="7321") or "7321"),
            heartbeat_screenshot_s=float(_env("INSPECTOR_HEARTBEAT_S", "LOOPBACK_HEARTBEAT_S", default="5") or "5"),
            notify=(_env("INSPECTOR_NOTIFY", "LOOPBACK_NOTIFY", default="1") or "1") not in ("0", "false", "no", ""),
            devin_api_key=os.getenv("DEVIN_API_KEY"),
            devin_base_url=_env("INSPECTOR_DEVIN_URL", default="https://api.devin.ai") or "https://api.devin.ai",
            devin_max_acu=int(_env("INSPECTOR_DEVIN_MAX_ACU") or "0") or None,
            devin_poll_timeout_s=int(_env("INSPECTOR_DEVIN_TIMEOUT", default="600") or "600"),
            devin_repo=_env("INSPECTOR_DEVIN_REPO", "LOOPBACK_DEVIN_REPO", default="wlu03/LoopBack") or "wlu03/LoopBack",
            transport=_env("INSPECTOR_TRANSPORT", default="stdio") or "stdio",
            http_host=_env("INSPECTOR_HTTP_HOST", default="127.0.0.1") or "127.0.0.1",
            http_port=int(_env("INSPECTOR_HTTP_PORT", default="8765") or "8765"),
            http_path=_env("INSPECTOR_HTTP_PATH", default="/mcp") or "/mcp",
        )
