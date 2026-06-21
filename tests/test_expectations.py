"""Pure tests for the code-aware missing-element oracle — no sandbox, no model."""
from __future__ import annotations

from inspector.driver import build_missing_judge_prompt, parse_verdict
from inspector.expectations import (
    ExpectedElement,
    check_expectations,
    diff_expected_vs_actual,
)
from inspector.models import Surface
from inspector.source_scan import extract_expected


def _exp(label, kind="button"):
    return ExpectedElement(label=label, kind=kind, source_ref="src.jsx:1")


# --- the diff (pure) ---

def test_diff_flags_only_absent_elements():
    expected = [_exp("Save"), _exp("Profile", "link"), _exp("Checkout")]
    actual = ["Save settings", "Profile"]  # Save via containment, Profile exact
    missing = diff_expected_vs_actual(expected, actual)
    assert [m.label for m in missing] == ["Checkout"]


def test_diff_empty_when_all_present():
    assert diff_expected_vs_actual([_exp("OK")], ["ok"]) == []


def test_diff_dedupes_by_normalized_label():
    missing = diff_expected_vs_actual([_exp("Sign Up"), _exp("sign  up")], [])
    assert len(missing) == 1


# --- source scanners (per surface) ---

def _labels(tmp_path, name, content, surface):
    (tmp_path / name).write_text(content)
    return {e.label.lower() for e in extract_expected(str(tmp_path), surface)}


def test_web_extractor(tmp_path):
    src = (
        '<button>Save</button>\n'
        '<a href="/p">Profile</a>\n'
        '<input placeholder="Your name" />\n'
        '<button aria-label="Close menu"></button>\n'
    )
    labels = _labels(tmp_path, "App.jsx", src, Surface.WEB)
    assert {"save", "profile", "your name", "close menu"} <= labels


def test_web_extractor_records_source_ref(tmp_path):
    (tmp_path / "App.jsx").write_text("\n\n<button>Delete</button>")
    [el] = [e for e in extract_expected(str(tmp_path), Surface.WEB) if e.label == "Delete"]
    assert el.source_ref == "App.jsx:3" and el.kind == "button"


def test_android_extractor(tmp_path):
    src = (
        '<Button android:text="Save" />\n'
        '<Button android:text="@string/submit_form" />\n'
        '<TextView android:contentDescription="Profile picture" />\n'
    )
    labels = _labels(tmp_path, "main.xml", src, Surface.ANDROID)
    assert "save" in labels
    assert "submit form" in labels        # @string/submit_form -> "submit form"
    assert "profile picture" in labels


def test_android_compose_extractor(tmp_path):
    src = 'Button(onClick = { save() }) {\n    Text("Checkout")\n}\n'
    labels = _labels(tmp_path, "Screen.kt", src, Surface.ANDROID)
    assert "checkout" in labels


def test_ios_extractor(tmp_path):
    src = (
        'Button("Save") { save() }\n'
        'Button(action: doIt) {\n    Text("Submit")\n}\n'
        'NavigationLink("Settings") { SettingsView() }\n'
        '.accessibilityIdentifier("profileButton")\n'
    )
    labels = _labels(tmp_path, "View.swift", src, Surface.IOS)
    assert {"save", "submit", "settings", "profilebutton"} <= labels


def test_electron_uses_web_extractor(tmp_path):
    labels = _labels(tmp_path, "renderer.jsx", "<button>Quit</button>", Surface.ELECTRON)
    assert "quit" in labels


def test_react_native_extractor(tmp_path):
    # RN is detected from package.json and overrides the native ANDROID extractor.
    (tmp_path / "package.json").write_text('{"dependencies": {"react-native": "0.74"}}')
    src = (
        '<Button title="Save" onPress={save} />\n'
        '<TextInput placeholder="Your name" />\n'
        '<TouchableOpacity onPress={go}>\n'
        '  <Text>Checkout</Text>\n'
        '</TouchableOpacity>\n'
        '<Pressable accessibilityLabel="Close menu" />\n'
    )
    labels = _labels(tmp_path, "App.js", src, Surface.ANDROID)
    assert {"save", "your name", "checkout", "close menu"} <= labels


def test_react_native_works_on_ios_surface_too(tmp_path):
    # same RN source, iOS target — framework routing is surface-independent
    (tmp_path / "package.json").write_text('{"dependencies": {"expo": "51"}}')
    labels = _labels(tmp_path, "App.tsx", '<Button title="Login" />', Surface.IOS)
    assert "login" in labels


def test_flutter_extractor(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: app\ndependencies:\n  flutter:\n    sdk: flutter\n")
    src = (
        "ElevatedButton(\n  onPressed: save,\n  child: Text('Save'),\n)\n"
        "TextField(decoration: InputDecoration(hintText: 'Your name'))\n"
        "TextButton(onPressed: go, child: Text('Checkout'))\n"
        "Tooltip(message: 'Close menu', child: Icon(Icons.close))\n"
    )
    labels = _labels(tmp_path, "main.dart", src, Surface.IOS)
    assert {"save", "your name", "checkout", "close menu"} <= labels


# --- verdict prompt + parser (driver, pure) ---

def test_missing_judge_prompt_mentions_candidate_and_rendered():
    p = build_missing_judge_prompt(_exp("Checkout"), ["Save", "Cancel"])
    assert "Checkout" in p and "Save, Cancel" in p and "is_bug" in p


def test_parse_verdict_true_and_false():
    assert parse_verdict('{"is_bug": true, "severity": "high", "reason": "gone"}') == {
        "is_bug": True, "severity": "high", "reason": "gone",
    }
    v = parse_verdict("garbage")
    assert v["is_bug"] is False


# --- end-to-end check_expectations with fakes ---

class _Trace:
    def __init__(self):
        self.findings_dir = "/nonexistent"
        self.saved = []

    def save_finding(self, f):
        self.saved.append(f)


class _Rec:
    id = "ses_x"
    trace_id = "trc_x"

    def __init__(self):
        self.findings = []


class _Adapter:
    def __init__(self, rendered):
        self._rendered = rendered

    def rendered_elements(self):
        if self._rendered is NotImplemented:
            raise NotImplementedError
        return self._rendered

    def screenshot(self):
        return b"png"


class _Session:
    def __init__(self, rendered):
        self.adapter = _Adapter(rendered)
        self.trace = _Trace()
        self.record = _Rec()


def test_check_records_finding_when_brain_confirms():
    session = _Session(rendered=["Cancel"])  # "Save" is missing
    def judge(candidate, rendered, screenshot):
        return {"is_bug": True, "severity": "high", "reason": "should be on the form"}
    found = check_expectations(session, [_exp("Save")], judge)
    assert len(found) == 1
    assert session.record.findings == [found[0].id]
    assert "Save" in found[0].summary and found[0].suspected_area == "src.jsx:1"


def test_check_skips_when_brain_says_offscreen():
    session = _Session(rendered=["Cancel"])
    judge = lambda c, r, s: {"is_bug": False, "reason": "behind a route"}  # noqa: E731
    assert check_expectations(session, [_exp("Save")], judge) == []
    assert session.trace.saved == []


def test_check_noops_when_surface_cannot_enumerate():
    session = _Session(rendered=NotImplemented)  # adapter raises NotImplementedError
    called = []
    check_expectations(session, [_exp("Save")], lambda *a: called.append(1) or {"is_bug": True})
    assert called == []  # judge never invoked → true no-op on unsupported surfaces
