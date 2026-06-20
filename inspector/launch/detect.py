from __future__ import annotations

import json
import os
from dataclasses import dataclass

from ..models import Surface


@dataclass
class ProjectInfo:
    surface: Surface
    framework: str
    package_manager: str
    dev_command: str
    default_port: int | None


# (lockfile, package manager, script runner) — first match wins
_LOCKFILES = [
    ("bun.lockb", "bun", "bun run"),
    ("bun.lock", "bun", "bun run"),
    ("pnpm-lock.yaml", "pnpm", "pnpm run"),
    ("yarn.lock", "yarn", "yarn"),
    ("package-lock.json", "npm", "npm run"),
]

# (dep key, framework, surface, preferred dev script, default port) — ordered,
# most specific first because frameworks share deps (SvelteKit/Astro both use vite).
_FRAMEWORKS = [
    ("expo", "expo", Surface.ANDROID, "start", 8081),
    ("next", "next", Surface.WEB, "dev", 3000),
    ("@sveltejs/kit", "sveltekit", Surface.WEB, "dev", 5173),
    ("astro", "astro", Surface.WEB, "dev", 4321),
    ("vite", "vite", Surface.WEB, "dev", 5173),
    ("react-scripts", "cra", Surface.WEB, "start", 3000),
    ("electron", "electron", Surface.ELECTRON, "dev", None),
]


def detect_package_manager(repo_path: str) -> tuple[str, str]:
    for lockfile, pm, runner in _LOCKFILES:
        if os.path.exists(os.path.join(repo_path, lockfile)):
            return pm, runner
    return "npm", "npm run"


def detect_project(repo_path: str, surface_hint: Surface | None = None) -> ProjectInfo:
    pkg_path = os.path.join(repo_path, "package.json")
    if not os.path.exists(pkg_path):
        raise FileNotFoundError(f"no package.json in {repo_path}")
    with open(pkg_path) as f:
        pkg = json.load(f)

    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    scripts = pkg.get("scripts", {})
    pm, runner = detect_package_manager(repo_path)

    for dep_key, framework, surface, dev_script, port in _FRAMEWORKS:
        if dep_key in deps:
            script = _pick_script(scripts, [dev_script, "dev", "start"])
            cmd = f"{runner} {script}" if script else f"{runner} {dev_script}"
            return ProjectInfo(
                surface=surface_hint or surface,
                framework=framework,
                package_manager=pm,
                dev_command=cmd,
                default_port=port,
            )

    # generic fallback
    script = _pick_script(scripts, ["dev", "start"]) or "dev"
    return ProjectInfo(surface_hint or Surface.WEB, "unknown", pm, f"{runner} {script}", None)


def _pick_script(scripts: dict, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in scripts:
            return c
    return None
