from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass

from .config import Config
from .models import ActionType, Element

# Actions the driver may emit. "done" is a sentinel (not an ActionType) that ends
# the run; everything else maps 1:1 onto ActionType for `session.act`.
DONE = "done"
_VALID_ACTIONS = {a.value for a in ActionType} | {DONE}


@dataclass
class Decision:
    """One step the driver chose: the next action plus optional bug judgment."""

    action: str = "wait"
    target_id: int | None = None
    text: str | None = None
    key: str | None = None
    expectation: str = ""   # what the action is supposed to achieve
    reason: str = ""        # why the driver picked it (for the trace/history)
    bug: dict | None = None  # {summary, severity, expected, actual} when judged broken

    @property
    def is_done(self) -> bool:
        return self.action == DONE

    def action_type(self) -> ActionType:
        return ActionType(self.action)


_SYSTEM = (
    "You are the brain of an autonomous UI tester. Your job is to TRY TO BREAK the app, "
    "not to confirm it works. You are given a screenshot of a running app with NUMBERED "
    "boxes over the interactive elements, the element list, the goal, the actions taken "
    "so far, and the most recent logs. Decide the SINGLE next action that best STRESSES "
    "the app toward the goal and surfaces bugs — prefer adversarial moves (empty/invalid/"
    "overflow/injection input, rapid re-clicks, Escape and keyboard nav, empty states, "
    "bogus routes) over happy-path clicks. When you see something broken (a crash, an "
    "error toast or console error, an action that did nothing when it should have, a "
    "wrong screen, a missing element, layout overflow), report it in `bug`. When the app "
    "has been adversarially exercised enough to judge it, choose action \"done\".\n"
    "EXPLORE FOR BREADTH: never repeat an action that already returned changed=false in "
    "ACTIONS SO FAR — it will not work the second time. When an action does nothing, MOVE "
    "ON to a different element or screen. Cover every screen (navigate via the tab/nav "
    "elements) and try each control once before going deep on any one."
)

_PROTOCOL = (
    'Reply with ONLY a JSON object (no prose, no code fence):\n'
    '{"action": "click|double_click|type|scroll|key|wait|done", '
    '"target_id": <int id from the list, or null>, '
    '"text": <string for type, else null>, '
    '"key": <key name for key action, else null>, '
    '"expectation": "<what should happen after this action>", '
    '"reason": "<one short sentence>", '
    '"bug": {"summary": "...", "severity": "low|medium|high|critical", '
    '"expected": "...", "actual": "..."} or null}'
)


def _format_elements(elements: list[Element], limit: int = 40) -> str:
    rows = []
    for el in elements[:limit]:
        label = (el.label or "").strip().replace("\n", " ")[:60]
        rows.append(f"  [{el.id}] {el.role or '?'}: {label!r} (interactive={el.interactivity})")
    if len(elements) > limit:
        rows.append(f"  … {len(elements) - limit} more")
    return "\n".join(rows) or "  (none detected)"


def _format_history(history: list[dict], limit: int = 8) -> str:
    if not history:
        return "  (nothing yet)"
    rows = []
    for h in history[-limit:]:
        rows.append(
            f"  #{h.get('step')}: {h.get('action')} target={h.get('target_id')} "
            f"({h.get('target_label', '')[:30]}) -> changed={h.get('changed')}"
        )
    return "\n".join(rows)


def build_decision_prompt(
    goal: str, elements: list[Element], history: list[dict], logs: list[str]
) -> str:
    """Assemble the text prompt sent alongside the Set-of-Mark screenshot. Pure."""
    from .adversarial import catalog_text

    recent_logs = "\n".join(f"  {ln}" for ln in (logs or [])[-12:]) or "  (none)"
    return (
        f"{_SYSTEM}\n\n"
        f"GOAL: {goal}\n\n"
        f"ELEMENTS (id → role: label):\n{_format_elements(elements)}\n\n"
        f"ACTIONS SO FAR:\n{_format_history(history)}\n\n"
        f"RECENT LOGS:\n{recent_logs}\n\n"
        f"ADVERSARIAL MOVES TO TRY (pick the one that fits what's on screen):\n"
        f"{catalog_text()}\n\n"
        f"{_PROTOCOL}"
    )


def parse_decision(text: str, elements: list[Element] | None = None) -> Decision:
    """Extract a Decision from the model's raw text, defensively. Pure.

    Tolerates code fences and surrounding prose by grabbing the outermost JSON
    object. Unknown/empty actions fall back to a no-op `wait` so the loop never
    crashes on a malformed reply.
    """
    obj = _extract_json_object(text)
    if obj is None:
        return Decision(action="wait", reason="unparseable driver reply")

    action = str(obj.get("action", "wait")).strip().lower()
    if action not in _VALID_ACTIONS:
        action = "wait"

    target_id = _coerce_int(obj.get("target_id"))
    if target_id is not None and elements is not None:
        valid_ids = {e.id for e in elements}
        if target_id not in valid_ids:
            target_id = None  # hallucinated id → drop it rather than misclick

    bug = obj.get("bug")
    if not isinstance(bug, dict) or not str(bug.get("summary", "")).strip():
        bug = None

    return Decision(
        action=action,
        target_id=target_id,
        text=_coerce_str(obj.get("text")),
        key=_coerce_str(obj.get("key")),
        expectation=_coerce_str(obj.get("expectation")) or "",
        reason=_coerce_str(obj.get("reason")) or "",
        bug=bug,
    )


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    # direct parse first; then the outermost {...} span as a fallback.
    for candidate in (text, _outermost_braces(text)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def _outermost_braces(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _coerce_int(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.search(r"-?\d+", v)
        if m:
            return int(m.group())
    return None


def _coerce_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# --- code-aware "missing element" judgment (brain decides real-bug vs off-screen) ---

_MISSING_JUDGE = (
    "You are auditing a running UI against its source code. The source declares an "
    "interactive {kind} labeled {label!r} (at {source_ref}), but it is NOT among the "
    "elements currently rendered.\n\nCurrently rendered interactive elements:\n  {rendered}\n\n"
    "Look at the screenshot. Decide: is this element MISSING when it SHOULD be visible in "
    "the current state (a real bug), or is it legitimately not on this screen right now "
    "(behind a route/tab/modal, or a condition like an empty cart)?\n"
    'Reply with ONLY JSON: {{"is_bug": true|false, "severity": "low|medium|high", '
    '"reason": "<one short sentence>"}}'
)


def build_missing_judge_prompt(candidate, rendered: list[str]) -> str:
    """Prompt asking the brain whether a code-declared-but-absent element is a real
    bug or just off-screen (the conditional-rendering guard). Pure."""
    shown = ", ".join(rendered[:40]) or "(none)"
    return _MISSING_JUDGE.format(
        kind=candidate.kind, label=candidate.label,
        source_ref=candidate.source_ref, rendered=shown,
    )


def parse_verdict(text: str) -> dict:
    """Parse the brain's missing-element verdict, defensively. Pure."""
    obj = _extract_json_object(text) or {}
    return {
        "is_bug": bool(obj.get("is_bug", False)),
        "severity": (_coerce_str(obj.get("severity")) or "medium").lower(),
        "reason": _coerce_str(obj.get("reason")) or "",
    }


# --- the live Replicate-backed driver ---

class ReplicateDriver:
    """Calls a Replicate-hosted vision-language model to choose each next action.

    The frontier "brain" lives here (not in the host agent) so `test_app` is a
    single self-contained call. Replicate is lazy-imported so the package + pure
    tests still run without the cloud SDK.
    """

    def __init__(self, config: Config):
        self.config = config

    def decide(
        self,
        som: bytes,
        elements: list[Element],
        goal: str,
        history: list[dict],
        logs: list[str],
    ) -> Decision:
        prompt = build_decision_prompt(goal, elements, history, logs)
        text = self._run_model(som, prompt)
        return parse_decision(text, elements)

    def judge_missing_element(self, candidate, rendered: list[str], screenshot: bytes) -> dict:
        return parse_verdict(self._run_model(screenshot, build_missing_judge_prompt(candidate, rendered)))

    def _run_model(self, image_bytes: bytes, prompt: str) -> str:
        import replicate  # lazy

        out = replicate.run(
            self.config.driver_ref,
            input={
                "image": io.BytesIO(image_bytes),
                "prompt": prompt,
                "max_tokens": 400,
                "temperature": 0.2,
            },
            use_file_output=False,
        )
        # Replicate VLMs stream either a string or a list of token strings.
        if isinstance(out, (list, tuple)):
            return "".join(str(x) for x in out)
        return str(out)


_FIELD_HINTS = ("name", "email", "search", "input", "your ", "text", "message", "address")


class HeuristicDriver:
    """No-LLM explorer: visit each interactive element once (type into fields,
    click everything else), then `done`. Satisfies the same `decide` interface, so
    it doubles as a fallback when the VLM stalls — guaranteeing the loop makes
    real progress instead of spinning on unparseable replies.
    """

    def __init__(self):
        self._visited: set[tuple] = set()
        self._field_n = 0  # which adversarial payload to push into the next field

    def decide(self, som, elements, goal, history, logs) -> Decision:
        from .adversarial import adversarial_value

        for el in elements:
            if not getattr(el, "interactivity", False):
                continue
            # de-dup by on-screen position (stable), not label — a text field's label
            # changes as it fills in, which otherwise makes us re-click it forever
            # instead of advancing to the next control (e.g. the Save button).
            sig = (round((el.bbox[0] + el.bbox[2]) / 2, 2), round((el.bbox[1] + el.bbox[3]) / 2, 2))
            if sig in self._visited:
                continue
            self._visited.add(sig)
            label = (el.label or "").strip().lower()
            if any(w in label for w in _FIELD_HINTS):
                # push a DIFFERENT breaking value into each field (empty, injection,
                # overflow, unicode, …) instead of one benign string everywhere.
                name, payload = adversarial_value(self._field_n)
                self._field_n += 1
                return Decision(
                    action="type", target_id=el.id, text=payload,
                    expectation="the field validates/escapes the input without crashing",
                    reason=f"adversarial input ({name}) into field {label!r}",
                )
            return Decision(
                action="click", target_id=el.id,
                expectation="the click does something visible",
                reason=f"click {label!r}" if label else "click element",
            )
        return Decision(action=DONE, reason="explored all interactive elements")

    def judge_missing_element(self, candidate, rendered: list[str], screenshot: bytes) -> dict:
        # no model to reason about conditional rendering → don't surface (avoid noise).
        return {"is_bug": False, "severity": "low", "reason": "heuristic mode — no brain to judge"}


def _is_degenerate(d: Decision) -> bool:
    """A primary decision that can't actually do anything → fall back to heuristic.

    Catches the dominant weak-VLM failures beyond a literal `wait`: a `type` with no
    text, a click/double-click with no target (a hallucinated id is dropped to None by
    `parse_decision`), or a `key` with no key. These otherwise pass straight through as
    no-ops and waste a step (the empty-type LLaVA emitted on the Electron run)."""
    if d.is_done:
        return False
    if d.action == "wait":
        return True
    if d.action == "type" and not (d.text or "").strip():
        return True
    if d.action in ("click", "double_click") and d.target_id is None:
        return True
    if d.action == "key" and not (d.key or "").strip():
        return True
    return False


class FallbackDriver:
    """Try the primary (VLM) driver; if it returns a no-op `wait` or a degenerate
    action (empty type, targetless click), fall back to deterministic heuristic
    exploration so the loop keeps making real progress."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    def decide(self, som, elements, goal, history, logs) -> Decision:
        try:
            decision = self.primary.decide(som, elements, goal, history, logs)
        except Exception:
            # a raised error (rate-limit, token-limit, API failure) must ALSO fall back
            # to deterministic exploration — otherwise every erroring step is a wasted
            # no-op and the run does zero work.
            return self.fallback.decide(som, elements, goal, history, logs)
        if _is_degenerate(decision):
            return self.fallback.decide(som, elements, goal, history, logs)
        return decision

    def judge_missing_element(self, candidate, rendered: list[str], screenshot: bytes) -> dict:
        # judgment needs the brain — delegate to the primary (VLM/Claude) driver.
        return self.primary.judge_missing_element(candidate, rendered, screenshot)


class AnthropicDriver:
    """SoM-grounded Claude driver — the high-quality brain.

    Reuses the exact same prompt (`build_decision_prompt`) and parser
    (`parse_decision`) as the Replicate driver, swapping the backend to the
    Anthropic Messages API (Set-of-Mark image + text → JSON action). Needs
    ANTHROPIC_API_KEY; `anthropic` is lazy-imported so the package + pure tests
    run without the SDK.
    """

    def __init__(self, config: Config, model: str | None = None):
        self.config = config
        # cheaper-by-default, configurable via INSPECTOR_DRIVER_MODEL (see Config)
        self.model = model or config.driver_model

    def decide(
        self, som: bytes, elements: list[Element], goal: str,
        history: list[dict], logs: list[str],
    ) -> Decision:
        prompt = build_decision_prompt(goal, elements, history, logs)
        text = self._run_model(som, prompt)
        return parse_decision(text, elements)

    def judge_missing_element(self, candidate, rendered: list[str], screenshot: bytes) -> dict:
        return parse_verdict(self._run_model(screenshot, build_missing_judge_prompt(candidate, rendered)))

    def _run_model(self, image_bytes: bytes, prompt: str) -> str:
        import base64

        import anthropic  # lazy

        client = anthropic.Anthropic(api_key=self.config.anthropic_api_key)
        b64 = base64.standard_b64encode(image_bytes).decode()
        resp = client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt + "\n\nReply with ONLY the JSON object."},
                ],
            }],
        )
        return next((b.text for b in resp.content if b.type == "text"), "{}")


def get_driver(config: Config):
    backend = config.driver_backend
    if backend == "auto":  # prefer the Claude brain when a key is present
        backend = "anthropic" if config.anthropic_api_key else "replicate"
    if backend == "anthropic":
        # Claude brain when it decides; heuristic exploration when it stalls.
        return FallbackDriver(AnthropicDriver(config), HeuristicDriver())
    if backend == "replicate":
        # VLM-guided when the model decides; heuristic exploration when it stalls.
        return FallbackDriver(ReplicateDriver(config), HeuristicDriver())
    if backend == "heuristic":
        return HeuristicDriver()
    raise NotImplementedError(f"driver backend {backend!r} not implemented")
