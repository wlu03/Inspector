"""Tests for the planner (app → parts) + planned_verify wiring."""
from __future__ import annotations

import inspector.parallel as P
from inspector.config import Config
from inspector.driver import HeuristicDriver, build_plan_prompt, parse_plan
from inspector.models import Element


def _el(label, role="button"):
    return Element(id=0, label=label, role=role, bbox=[0, 0, 0.1, 0.1], interactivity=True)


# --- plan prompt + parser (pure) ---

def test_plan_prompt_mentions_elements():
    p = build_plan_prompt([_el("Settings", "tab"), _el("Profile", "tab")], "find bugs")
    assert "Settings" in p and "parts" in p and "JSON" in p


def test_parse_plan():
    parts = parse_plan('{"parts":[{"name":"Settings","goal":"test settings"},'
                       '{"name":"settings","goal":"dup"},{"name":"Profile"}]}')
    assert [p["name"] for p in parts] == ["Settings", "Profile"]   # dedup by name
    assert parts[1]["goal"] == "Profile"                            # goal falls back to name


def test_parse_plan_garbage_is_empty():
    assert parse_plan("not json") == []


# --- heuristic planner: nav elements → parts, else whole app ---

def test_heuristic_plan_from_nav():
    parts = HeuristicDriver().plan(b"", [_el("Settings", "tab"), _el("Profile", "link"),
                                         _el("Save", "button")], "find bugs")
    assert {p["name"] for p in parts} == {"Settings", "Profile"}   # the button is not a part


def test_heuristic_plan_falls_back_to_whole_app():
    parts = HeuristicDriver().plan(b"", [_el("Save", "button")], "find bugs")
    assert parts == [{"name": "app", "goal": "find bugs"}]


# --- planned_verify: plan then dispatch (mocked) ---

def test_planned_verify_plans_then_dispatches(monkeypatch):
    monkeypatch.setattr(P, "plan_parts",
                        lambda cfg, repo, surface, goal: [{"name": "a", "goal": "g"},
                                                          {"name": "b", "goal": "g"}])
    monkeypatch.setattr(P, "parallel_verify",
                        lambda cfg, repo, parts, surface, steps, max_workers: {
                            "parts": [{"part": p["name"]} for p in parts],
                            "agents": len(parts), "merged_findings": [], "total_unique_findings": 0})
    res = P.planned_verify(Config(), "/repo", max_agents=4)
    assert res["agents"] == 2
    assert [p["name"] for p in res["plan"]] == ["a", "b"]
