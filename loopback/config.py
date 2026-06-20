from __future__ import annotations

import os
from dataclasses import dataclass, field

# Pinned OmniParser V2 on Replicate (the bare slug 404s — a version is required).
DEFAULT_OMNIPARSER_REF = (
    "microsoft/omniparser-v2:"
    "49cf3d41b8d3aca1360514e83be4c97131ce8f0d99abfc365526d8384caa88df"
)


def _load_dotenv() -> None:
    """Load a local .env into os.environ if python-dotenv is available.

    Searches the current working directory upward, so running the server or
    `python -m loopback.doctor` from the project root picks up `.env`.
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

    # Sandbox
    sandbox_resolution: tuple[int, int] = (1280, 800)
    sandbox_timeout_s: int = 3600

    # Trace artifacts
    trace_root: str = field(
        default_factory=lambda: os.path.expanduser("~/.loopback/sessions")
    )

    # Loop guardrails
    max_iterations: int = 30
    max_wall_clock_s: int = 1800

    @classmethod
    def from_env(cls) -> "Config":
        _load_dotenv()
        return cls(
            e2b_api_key=os.getenv("E2B_API_KEY"),
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            detector_backend=os.getenv("LOOPBACK_DETECTOR", "replicate"),
            omniparser_endpoint=os.getenv("LOOPBACK_OMNIPARSER_URL"),
            omniparser_ref=os.getenv("LOOPBACK_OMNIPARSER_REF", DEFAULT_OMNIPARSER_REF),
        )
