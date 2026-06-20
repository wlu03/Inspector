import json

from loopback.adapters.electron import ElectronAdapter


def test_name_hints_from_package(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {"name": "myapp", "productName": "My App", "build": {"productName": "My Cool App"}}
        )
    )
    hints = ElectronAdapter._read_name_hints(str(tmp_path))
    assert "My App" in hints
    assert "myapp" in hints
    assert "My Cool App" in hints
    assert "electron" in hints and "Electron" in hints


def test_name_hints_fallback_when_no_package(tmp_path):
    assert ElectronAdapter._read_name_hints(str(tmp_path)) == ["electron", "Electron"]


def test_name_hints_dedupes(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "electron"}))
    hints = ElectronAdapter._read_name_hints(str(tmp_path))
    assert hints.count("electron") == 1
