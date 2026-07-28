from inspector.models import Action, ActionType, Element, ReproStep, SessionRecord, Surface


def test_center_px():
    el = Element(id=0, bbox=[0.0, 0.0, 0.5, 0.5])
    assert el.center_px(1000, 1000) == (250, 250)


def test_center_px_tolerates_short_bbox():
    el = Element(id=0, bbox=[0.2, 0.4])  # padded to [0.2, 0.4, 0, 0]
    assert el.center_px(1000, 1000) == (100, 200)


def test_ids_unique_and_prefixed():
    a = SessionRecord(repo_path=".", surface=Surface.WEB)
    b = SessionRecord(repo_path=".", surface=Surface.WEB)
    assert a.id != b.id
    assert a.id.startswith("ses_")
    assert a.trace_id.startswith("trc_")


def test_surface_enum_roundtrip():
    assert Surface("electron") is Surface.ELECTRON


def test_action_records_where_a_drag_went_and_how_a_scroll_was_aimed():
    # the trace is the re-run script: a drag with no destination replays as a click,
    # and a scroll with no direction replays as the default downward one
    a = Action(seq=0, type=ActionType.DRAG, coords=[10, 20], to_coords=[300, 400])
    back = Action.model_validate_json(a.model_dump_json())
    assert back.to_coords == [300, 400]
    s = Action(seq=1, type=ActionType.SCROLL, direction="up", amount=9)
    assert Action.model_validate_json(s.model_dump_json()).direction == "up"


def test_repro_step_carries_a_drag_destination():
    step = ReproStep(action="drag", locator="Card A", to_locator="Done column")
    assert ReproStep.model_validate_json(step.model_dump_json()).to_locator == "Done column"
