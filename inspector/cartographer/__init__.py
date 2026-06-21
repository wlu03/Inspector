"""Cartographer — region-decomposed, hypothesis-driven bug finding (docs/15).

Phase 0: deterministic spine for web/electron — map the UI into regions, run the
LOGIC_ARITHMETIC + STATE_SYNC lens oracles per region (scripted protocol + an
assertion on the app's OWN state, never on injected input), and return a ranked
fix list. No LLM in the action choice and no payloads typed, so it structurally
cannot flag self-inflicted input.
"""

from .mapper import segment
from .models import Candidate, Hypothesis, Region
from .orchestrator import run_regions

__all__ = ["segment", "Region", "Hypothesis", "Candidate", "run_regions"]
