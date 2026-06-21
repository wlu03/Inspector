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
    driver_backend: str = "replicate"
    driver_ref: str = DEFAULT_DRIVER_REF
    # Anthropic-brain model (when driver_backend="anthropic"). Cheaper than Opus by
    # default; override with INSPECTOR_DRIVER_MODEL (e.g. claude-haiku-4-5 = cheapest).
    driver_model: str = "claude-sonnet-4-6"

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

    # Session reaper: tear a session down after this many seconds with no tool
    # activity, or once it's older than sandbox_timeout_s (the sandbox dies anyway).
    # 0 disables the reaper. Guards against a host that crashes/forgets stop().
    session_idle_ttl_s: int = 600
    reaper_interval_s: int = 60

    # Host token cost: cap full SoM PNGs returned per session at the MCP boundary
    # (0 = unlimited). Past the cap, observe/act return the text element list only.
    max_images_per_session: int = 0

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
            driver_backend=_env("INSPECTOR_DRIVER", "LOOPBACK_DRIVER", default="replicate") or "replicate",
            driver_model=_env("INSPECTOR_DRIVER_MODEL", "LOOPBACK_DRIVER_MODEL",
                              default="claude-sonnet-4-6") or "claude-sonnet-4-6",
            driver_ref=_env("INSPECTOR_DRIVER_REF", "LOOPBACK_DRIVER_REF", default=DEFAULT_DRIVER_REF) or DEFAULT_DRIVER_REF,
            sandbox_template=os.getenv("E2B_TEMPLATE"),
            session_idle_ttl_s=int(_env("INSPECTOR_SESSION_IDLE_TTL", "LOOPBACK_SESSION_IDLE_TTL", default="600") or "600"),
            reaper_interval_s=int(_env("INSPECTOR_REAPER_INTERVAL", "LOOPBACK_REAPER_INTERVAL", default="60") or "60"),
            max_images_per_session=int(_env("INSPECTOR_MAX_IMAGES", "LOOPBACK_MAX_IMAGES", default="0") or "0"),
        )
