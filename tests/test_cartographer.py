from inspector.cartographer.lenses import LogicArithmeticLens, PersistenceLens, StateSyncLens
from inspector.cartographer.mapper import segment
from inspector.cartographer.models import Region
from inspector.models import ActionType, Element


def E(i, label, x, y, w=0.1, h=0.05, interactive=False, role="text"):
    return Element(id=i, label=label, role=role, bbox=[x, y, x + w, y + h],
                   interactivity=interactive, source="dom")


# ---------- mapper ----------

def test_segment_clusters_by_proximity():
    els = [
        E(0, "0", 0.40, 0.10),                                  # number
        E(1, "+", 0.45, 0.18, interactive=True, role="button"),  # adjacent to the number
        E(2, "Subscribe", 0.40, 0.70, interactive=True, role="button"),  # far below
    ]
    regions = segment(els)
    assert len(regions) == 2
    counter = next(r for r in regions if 0 in r.member_ids)
    assert set(counter.member_ids) == {0, 1}


def test_region_id_is_stable_across_observations():
    a = Region.make("Counter", [0.1, 0.1, 0.5, 0.4], [0, 1], "panel", ["0", "+"])
    b = Region.make("Counter", [0.11, 0.1, 0.51, 0.41], [3, 9], "panel", ["+", "0"])  # diff ids/bbox, same labels
    assert a.region_id == b.region_id


# ---------- lens harness ----------

class _Adapter:
    def __init__(self, states): self.states = states
    def control_state(self, i): return self.states.get(i, {})


class _Session:
    def __init__(self, elements, adapter, on_act):
        self.last_elements = elements
        self.adapter = adapter
        self._on_act = on_act

    def act(self, atype, target_id, text, key):
        self._on_act(self, target_id)
        return (b"", True, [])


_PLUS = E(1, "+", 0.45, 0.18, interactive=True, role="button")
_REGION = Region.make("counter", [0.3, 0.05, 0.6, 0.25], [0, 1], "panel", ["0", "+"])


def test_logic_lens_catches_plus_two():
    def on_act(sess, tid):
        if tid == 1:  # BUG: increments by 2
            sess.last_elements = [E(0, "2", 0.40, 0.10), _PLUS]
    sess = _Session([E(0, "0", 0.40, 0.10), _PLUS], _Adapter({}), on_act)
    lens = LogicArithmeticLens()
    hyps = lens.detect(sess, _REGION, sess.last_elements)
    assert hyps and hyps[0].meta["kind"] == "increment"
    cand = lens.investigate(sess, _REGION, hyps[0])
    assert cand is not None and "by 2 instead of 1" in cand.issue and cand.severity == "high"


def test_logic_lens_silent_on_correct_increment():
    def on_act(sess, tid):
        if tid == 1:
            sess.last_elements = [E(0, "1", 0.40, 0.10), _PLUS]  # correct +1
    sess = _Session([E(0, "0", 0.40, 0.10), _PLUS], _Adapter({}), on_act)
    lens = LogicArithmeticLens()
    hyps = lens.detect(sess, _REGION, sess.last_elements)
    assert lens.investigate(sess, _REGION, hyps[0]) is None  # no false positive on correct behavior


def test_state_sync_catches_label_state_desync():
    tog = E(0, "Off", 0.40, 0.10, interactive=True, role="button")
    region = Region.make("prefs", [0.3, 0.05, 0.6, 0.2], [0], "panel", ["Off"])
    states = {0: {"pressed": "false", "role": "button"}}  # aria-pressed never moves

    def on_act(sess, tid):  # BUG: label flips Off->On but the backing state doesn't
        sess.last_elements = [E(0, "On", 0.40, 0.10, interactive=True, role="button")]

    sess = _Session([tog], _Adapter(states), on_act)
    lens = StateSyncLens()
    hyps = lens.detect(sess, region, sess.last_elements)
    assert hyps  # recognized as a toggle (carries aria-pressed)
    cand = lens.investigate(sess, region, hyps[0])
    assert cand is not None and "disagree" in cand.issue


def test_log_tier_fires_when_oracle_silent_but_handler_errors():
    # toggle flips label AND state correctly (a11y oracle silent), but logs an error
    # on click (the bug is an invisible internal-state desync) -> LOG_SIGNAL fires.
    tog = E(0, "Off", 0.40, 0.10, interactive=True, role="button")
    region = Region.make("prefs", [0.3, 0.05, 0.6, 0.2], [0], "panel", ["Off"])
    flips = {"n": 0}

    class A:
        def control_state(self, i):
            return {"pressed": "true" if flips["n"] else "false"}

    class S:
        def __init__(self):
            self.last_elements = [tog]
            self.adapter = A()

        def act(self, atype, target_id, text, key):
            flips["n"] = 1
            self.last_elements = [E(0, "On", 0.40, 0.10, interactive=True, role="button")]
            return (b"", True, ["[console.error] toggle state desync"])

    sess = S()
    lens = StateSyncLens()
    cand = lens.investigate(sess, region, lens.detect(sess, region, sess.last_elements)[0])
    assert cand is not None and cand.evidence.get("oracle") == "LOG_SIGNAL"


def _persistence_session(clears: bool):
    field = E(0, "", 0.4, 0.10, interactive=True, role="textfield")
    save = E(1, "Save", 0.4, 0.20, interactive=True, role="button")

    class S:
        def __init__(self):
            self.last_elements = [field, save]
            self.adapter = _Adapter({})

        def act(self, atype, target_id, text, key):
            if atype == ActionType.TYPE and target_id == 0:
                self.last_elements = [E(0, text, 0.4, 0.10, interactive=True, role="textfield"), save]
            elif atype == ActionType.CLICK and target_id == 1 and clears:
                self.last_elements = [E(0, "", 0.4, 0.10, interactive=True, role="textfield"), save]  # BUG: Save clears
            return (b"", True, [])

    return S(), Region.make("form", [0.3, 0.05, 0.6, 0.3], [0, 1], "form", ["Save"])


def test_persistence_lens_catches_lost_value():
    sess, region = _persistence_session(clears=True)
    lens = PersistenceLens()
    hyps = lens.detect(sess, region, sess.last_elements)
    assert hyps
    cand = lens.investigate(sess, region, hyps[0])
    assert cand is not None and "lost" in cand.issue and cand.severity == "high"


def test_persistence_lens_silent_when_value_persists():
    sess, region = _persistence_session(clears=False)
    lens = PersistenceLens()
    assert lens.investigate(sess, region, lens.detect(sess, region, sess.last_elements)[0]) is None


def test_toggle_state_reads_native_value():
    from inspector.cartographer.lenses import _toggle_state
    assert _toggle_state({"value": "0", "role": "CheckBox"}) == ("0",)   # iOS/macOS a11y
    assert _toggle_state({"value": "1", "role": "AXSwitch"}) == ("1",)
    assert _toggle_state({"value": "x", "role": "Button"}) is None        # non-toggle role
    assert _toggle_state({"pressed": "false"}) == ("false",)              # web aria still works


def test_state_sync_catches_inert_toggle():
    # a checkbox whose value never moves on tap (the Flutter inert-switch class).
    tog = E(0, "Not subscribed", 0.40, 0.10, interactive=True, role="checkbox")
    region = Region.make("prefs", [0.3, 0.05, 0.6, 0.2], [0], "panel", ["Not subscribed"])

    class A:
        def control_state(self, i):
            return {"value": "0", "role": "CheckBox", "label": "Not subscribed"}

    sess = _Session([tog], A(), lambda s, tid: None)  # tap does nothing → inert
    lens = StateSyncLens()
    hyps = lens.detect(sess, region, sess.last_elements)
    assert hyps  # recognized as a toggle via native value+role
    cand = lens.investigate(sess, region, hyps[0])
    assert cand is not None and "inert" in cand.issue


def test_state_sync_silent_when_label_and_state_move_together():
    tog = E(0, "Off", 0.40, 0.10, interactive=True, role="button")
    region = Region.make("prefs", [0.3, 0.05, 0.6, 0.2], [0], "panel", ["Off"])
    flips = {"n": 0}

    class A:
        def control_state(self, i):
            return {"pressed": "true" if flips["n"] else "false"}

    def on_act(sess, tid):
        flips["n"] = 1  # state moves
        sess.last_elements = [E(0, "On", 0.40, 0.10, interactive=True, role="button")]  # label moves too

    sess = _Session([tog], A(), on_act)
    lens = StateSyncLens()
    hyps = lens.detect(sess, region, sess.last_elements)
    assert lens.investigate(sess, region, hyps[0]) is None  # correct toggle -> no bug
