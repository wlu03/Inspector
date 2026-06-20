from inspector.plan import ScenarioStatus, build_plan


def test_build_plan():
    plan = build_plan(
        "ses_x",
        "test the save flow",
        [{"title": "Save flow", "rationale": "core", "steps": ["click save"], "expected": "toast"}],
    )
    assert plan.goal == "test the save flow"
    assert len(plan.scenarios) == 1
    s = plan.scenarios[0]
    assert s.title == "Save flow"
    assert s.steps == ["click save"]
    assert s.status == ScenarioStatus.PENDING
    assert plan.get(s.id) is s
    assert plan.pending() == [s]


def test_build_plan_empty():
    plan = build_plan("ses_y", "nothing", [])
    assert plan.scenarios == []
    assert plan.pending() == []
