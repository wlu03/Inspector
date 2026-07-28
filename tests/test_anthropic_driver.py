"""AnthropicDriver: request shape, structured outputs, and the cacheable prefix.

Every test here mocks the SDK by shadowing `anthropic` in sys.modules — the driver
lazy-imports it inside `_run_model`, so no network call is ever made.
"""
from __future__ import annotations

import sys
import types

from inspector.config import Config
from inspector.driver import (
    AnthropicDriver,
    FallbackDriver,
    ReplicateDriver,
    _is_cacheable,
    build_decision_prefix,
    get_driver,
)
from inspector.models import Element


def _els():
    return [Element(id=2, label="Save", role="icon", bbox=[0.1, 0.1, 0.2, 0.2], interactivity=True)]


class _Block:
    def __init__(self, type_: str, text: str = ""):
        self.type = type_
        self.text = text


def _fake_anthropic(monkeypatch, reply: str = "{}") -> list[dict]:
    """Shadow the `anthropic` SDK; return the list that collects create() kwargs.

    The stub leads the response with a thinking block so the tests also cover the
    "skip past thinking, take the first text block" extraction.
    """
    calls: list[dict] = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                content=[_Block("thinking"), _Block("text", reply)])

    class _Anthropic:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    module = types.ModuleType("anthropic")
    module.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return calls


def _blocks(call: dict) -> list[dict]:
    return call["messages"][0]["content"]


def test_anthropic_driver_reuses_parser(monkeypatch):
    d = AnthropicDriver(Config(anthropic_api_key="sk-test"))
    monkeypatch.setattr(
        d, "_run_model",
        lambda som, prompt, schema, prefix=None:
            '{"action":"click","target_id":2,"reason":"save"}',
    )
    dec = d.decide(b"png", _els(), "test save", [], [])
    assert dec.action == "click" and dec.target_id == 2


def test_auto_prefers_anthropic_with_key():
    drv = get_driver(Config(driver_backend="auto", anthropic_api_key="sk-test"))
    assert isinstance(drv, FallbackDriver) and isinstance(drv.primary, AnthropicDriver)


def test_auto_falls_back_to_replicate_without_key():
    drv = get_driver(Config(driver_backend="auto", anthropic_api_key=None))
    assert isinstance(drv, FallbackDriver) and isinstance(drv.primary, ReplicateDriver)


def test_explicit_anthropic_backend():
    drv = get_driver(Config(driver_backend="anthropic", anthropic_api_key="sk-test"))
    assert isinstance(drv.primary, AnthropicDriver)


def test_defaults_to_opus_5():
    assert AnthropicDriver(Config(anthropic_api_key="sk-test")).model == "claude-opus-5"


# --- request shape: the parameters this model generation accepts (and rejects) ---

def test_request_omits_rejected_sampling_and_thinking_params(monkeypatch):
    calls = _fake_anthropic(monkeypatch)
    AnthropicDriver(Config(anthropic_api_key="sk-test")).decide(b"png", _els(), "g", [], [])
    kwargs = calls[0]
    for rejected in ("temperature", "top_p", "top_k", "thinking", "output_format"):
        assert rejected not in kwargs


def test_max_tokens_leaves_room_for_a_plan(monkeypatch):
    calls = _fake_anthropic(monkeypatch, '{"parts": []}')
    AnthropicDriver(Config(anthropic_api_key="sk-test")).plan(b"png", _els(), "g")
    assert calls[0]["max_tokens"] >= 2048


def test_effort_travels_inside_output_config(monkeypatch):
    calls = _fake_anthropic(monkeypatch)
    AnthropicDriver(Config(anthropic_api_key="sk-test")).decide(b"png", _els(), "g", [], [])
    assert "effort" not in calls[0]
    assert calls[0]["output_config"]["effort"]


# --- structured outputs: one schema per call site, and it constrains the reply ---

def _schema(call: dict) -> dict:
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    return fmt["schema"]


def test_each_call_site_sends_its_own_schema(monkeypatch):
    calls = _fake_anthropic(monkeypatch, '{"parts": []}')
    d = AnthropicDriver(Config(anthropic_api_key="sk-test"))
    d.decide(b"png", _els(), "g", [], [])
    d.plan(b"png", _els(), "g")
    d.judge_missing_element(
        types.SimpleNamespace(kind="button", label="Save", source_ref="a.tsx:1"), [], b"png")
    d.verify_finding({"summary": "s", "severity": "high"}, b"png")

    keys = [sorted(_schema(c)["properties"]) for c in calls]
    assert keys[0] == ["action", "bug", "expectation", "key", "reason", "target_id", "text"]
    assert keys[1] == ["parts"]
    assert keys[2] == ["is_bug", "reason", "severity"]
    assert keys[3] == ["confirmed", "reason"]


def test_schemas_satisfy_structured_output_constraints(monkeypatch):
    calls = _fake_anthropic(monkeypatch, '{"parts": []}')
    d = AnthropicDriver(Config(anthropic_api_key="sk-test"))
    d.decide(b"png", _els(), "g", [], [])
    d.plan(b"png", _els(), "g")

    def _check(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
        # numeric/string bounds are not supported by structured outputs
        for unsupported in ("minimum", "maximum", "minLength", "maxLength", "minItems"):
            assert unsupported not in node
        for child in list(node.get("properties", {}).values()) + node.get("anyOf", []):
            _check(child)
        _check(node.get("items"))

    for call in calls:
        _check(_schema(call))


def test_decision_reply_is_parsed_not_scraped(monkeypatch):
    _fake_anthropic(
        monkeypatch,
        '{"action":"click","target_id":2,"text":null,"key":null,'
        '"expectation":"saves","reason":"save","bug":null}',
    )
    dec = AnthropicDriver(Config(anthropic_api_key="sk-test")).decide(
        b"png", _els(), "test save", [], [])
    assert dec.action == "click" and dec.target_id == 2 and dec.reason == "save"


# --- caching: a static prefix ahead of the per-turn image and state ---

def test_static_prefix_precedes_image_and_state(monkeypatch):
    calls = _fake_anthropic(monkeypatch)
    AnthropicDriver(Config(anthropic_api_key="sk-test")).decide(
        b"png", _els(), "test save", [], ["boom"])
    kinds = [b["type"] for b in _blocks(calls[0])]
    assert kinds == ["text", "image", "text"]

    prefix, _, state = _blocks(calls[0])
    assert prefix["text"] == build_decision_prefix()
    assert "test save" not in prefix["text"]  # nothing per-turn ahead of the breakpoint
    assert "boom" in state["text"] and "test save" in state["text"]


def test_cache_breakpoint_on_the_last_static_block(monkeypatch):
    calls = _fake_anthropic(monkeypatch)
    AnthropicDriver(Config(anthropic_api_key="sk-test")).decide(b"png", _els(), "g", [], [])
    prefix, image, state = _blocks(calls[0])
    assert prefix["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in image and "cache_control" not in state


def test_prefix_is_byte_identical_across_turns(monkeypatch):
    calls = _fake_anthropic(monkeypatch)
    d = AnthropicDriver(Config(anthropic_api_key="sk-test"))
    d.decide(b"png", _els(), "goal one", [], [])
    d.decide(b"other", _els(), "goal two", [{"step": 1, "action": "click"}], ["err"])
    assert _blocks(calls[0])[0]["text"] == _blocks(calls[1])[0]["text"]
    assert _blocks(calls[0])[2]["text"] != _blocks(calls[1])[2]["text"]


def test_no_breakpoint_when_prefix_is_below_the_model_minimum(monkeypatch):
    calls = _fake_anthropic(monkeypatch)
    # haiku's minimum cacheable prefix is far above our instruction text — a marker
    # there would never hit, so we must not send one.
    AnthropicDriver(Config(anthropic_api_key="sk-test"),
                    model="claude-haiku-4-5").decide(b"png", _els(), "g", [], [])
    assert "cache_control" not in _blocks(calls[0])[0]


def test_single_shot_calls_send_no_prefix(monkeypatch):
    calls = _fake_anthropic(monkeypatch, '{"confirmed": false, "reason": "benign"}')
    AnthropicDriver(Config(anthropic_api_key="sk-test")).verify_finding(
        {"summary": "s", "severity": "low"}, b"png")
    assert [b["type"] for b in _blocks(calls[0])] == ["image", "text"]


def test_is_cacheable_tracks_the_per_model_minimum():
    assert _is_cacheable("x" * 4096, "claude-opus-5")        # 1024 est. tokens > 512
    assert not _is_cacheable("x" * 1024, "claude-opus-5")    # 256 est. tokens < 512
    assert not _is_cacheable("x" * 4096, "claude-haiku-4-5")  # minimum is 4096 tokens
    assert not _is_cacheable("x" * 2048, "some-unknown-model")  # conservative default
