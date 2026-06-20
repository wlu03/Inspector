import json

from inspector.launch.detect import detect_package_manager, detect_project
from inspector.models import Surface


def _write_pkg(tmp_path, pkg: dict):
    (tmp_path / "package.json").write_text(json.dumps(pkg))


def test_detect_vite(tmp_path):
    _write_pkg(tmp_path, {"devDependencies": {"vite": "^5"}, "scripts": {"dev": "vite"}})
    (tmp_path / "package-lock.json").write_text("{}")
    info = detect_project(str(tmp_path))
    assert info.framework == "vite"
    assert info.surface == Surface.WEB
    assert info.dev_command == "npm run dev"
    assert info.default_port == 5173


def test_detect_next_wins_over_vite(tmp_path):
    _write_pkg(
        tmp_path,
        {"dependencies": {"next": "14"}, "devDependencies": {"vite": "^5"}, "scripts": {"dev": "next dev"}},
    )
    info = detect_project(str(tmp_path))
    assert info.framework == "next"
    assert info.default_port == 3000


def test_detect_electron(tmp_path):
    _write_pkg(tmp_path, {"devDependencies": {"electron": "^30"}, "scripts": {"dev": "electron ."}})
    info = detect_project(str(tmp_path))
    assert info.framework == "electron"
    assert info.surface == Surface.ELECTRON


def test_package_manager_from_lockfile(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("")
    pm, runner = detect_package_manager(str(tmp_path))
    assert pm == "pnpm"
    assert runner == "pnpm run"
