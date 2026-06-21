from inspector.config import Config
from inspector.driver import (
    AnthropicDriver,
    FallbackDriver,
    ReplicateDriver,
    get_driver,
)
from inspector.models import Element


def _els():
    return [Element(id=2, label="Save", role="icon", bbox=[0.1, 0.1, 0.2, 0.2], interactivity=True)]


def test_anthropic_driver_reuses_parser(monkeypatch):
    d = AnthropicDriver(Config(anthropic_api_key="sk-test"))
    monkeypatch.setattr(
        d, "_run_model",
        lambda som, prompt: '{"action":"click","target_id":2,"reason":"save"}',
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
