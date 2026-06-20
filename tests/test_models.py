from inspector.models import Element, SessionRecord, Surface


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
