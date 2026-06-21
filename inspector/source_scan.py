from __future__ import annotations

import json
import os
import re

from .expectations import ExpectedElement
from .models import Surface

_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", ".venv", "venv",
    "coverage", ".pytest_cache", "__pycache__", ".turbo", ".cache", "Pods",
}
_MAX_FILE_BYTES = 512 * 1024
_MAX_FILES = 600

_EXTS = {
    Surface.WEB: (".jsx", ".tsx", ".js", ".ts", ".html", ".htm", ".vue", ".svelte"),
    Surface.ELECTRON: (".jsx", ".tsx", ".js", ".ts", ".html", ".htm", ".vue", ".svelte"),
    Surface.ANDROID: (".xml", ".kt", ".java"),
    Surface.IOS: (".swift", ".m", ".storyboard", ".xib"),
}


def extract_expected(repo_path: str, surface: Surface) -> list[ExpectedElement]:
    """Scan the repo's source for interactive elements the code declares.

    Routing is FRAMEWORK-first, then surface: React Native and Flutter are
    cross-platform (their source is JS/Dart, not native), so a repo targeting the
    Android or iOS surface may actually be RN/Flutter — detect that and use the
    right extractor. Falls back to the native per-surface extractor otherwise.
    The diff + brain-judgment that consume these are surface-agnostic.
    """
    framework = detect_framework(repo_path)
    if framework == "flutter":
        extractor, exts = _extract_flutter, (".dart",)
    elif framework == "react-native":
        extractor, exts = _extract_rn, (".js", ".jsx", ".ts", ".tsx")
    else:
        extractor = {
            Surface.WEB: _extract_web,
            Surface.ELECTRON: _extract_web,   # Electron renderer is web — same extractor
            Surface.ANDROID: _extract_android,
            Surface.IOS: _extract_ios,
        }.get(surface)
        if extractor is None:
            return []
        exts = _EXTS[surface]

    out: list[ExpectedElement] = []
    seen: set[tuple[str, str]] = set()
    for path in _walk(repo_path, exts):
        rel = os.path.relpath(path, repo_path)
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read(_MAX_FILE_BYTES)
        except OSError:
            continue
        for label, kind, line in extractor(text):
            label = _clean(label)
            if not label or len(label) > 60:
                continue
            key = (kind, label.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(ExpectedElement(label=label, kind=kind, source_ref=f"{rel}:{line}"))
    return out


# --- framework detection (RN/Flutter override the native surface extractor) ---

def detect_framework(repo_path: str) -> str | None:
    """'flutter' | 'react-native' | None, from the repo's manifest. Cheap, no walk."""
    pubspec = os.path.join(repo_path, "pubspec.yaml")
    if os.path.isfile(pubspec):
        try:
            with open(pubspec, encoding="utf-8", errors="ignore") as f:
                if "flutter" in f.read():
                    return "flutter"
        except OSError:
            pass
    pkg = os.path.join(repo_path, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if any(k in deps for k in ("react-native", "expo", "react-native-web")):
                return "react-native"
        except Exception:
            pass
    return None


# --- helpers ---

def _walk(repo_path: str, exts: tuple[str, ...]):
    n = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith(exts):
                yield os.path.join(root, name)
                n += 1
                if n >= _MAX_FILES:
                    return


def _clean(s: str) -> str:
    s = re.sub(r"\{[^{}]*\}", "", s)   # JSX / Compose interpolations
    s = re.sub(r"<[^>]+>", "", s)      # nested tags
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip("\"'")


def _lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _finditer(pattern, text, kind, group=1, flags=re.IGNORECASE | re.DOTALL):
    for m in re.finditer(pattern, text, flags):
        yield m.group(group), kind, _lineno(text, m.start())


# --- web / electron (JSX, HTML, Vue, Svelte) ---

def _extract_web(text: str):
    yield from _finditer(r"<(?:button|Button)\b[^>]*>(.*?)</(?:button|Button)>", text, "button")
    yield from _finditer(r"<(?:a|Link|NavLink)\b[^>]*>(.*?)</(?:a|Link|NavLink)>", text, "link")
    yield from _finditer(r"<input\b[^>]*\bplaceholder=[\"']([^\"']+)[\"']", text, "input")
    # explicit aria-labels, but ONLY on interactive tags — a decorative <div aria-label>
    # or landmark shouldn't become an expected affordance the oracle hunts for.
    yield from _finditer(
        r"<(?:button|a|Button|Link|NavLink|input|select|textarea)\b[^>]*"
        r"\baria-label=[\"']([^\"']+)[\"']", text, "element")
    yield from _finditer(
        r"role=[\"']button[\"'][^>]*\baria-label=[\"']([^\"']+)[\"']", text, "element")
    # role="button" with adjacent text content
    yield from _finditer(r"role=[\"']button[\"'][^>]*>(.*?)<", text, "button")


# --- android (XML layouts + Jetpack Compose) ---

def _extract_android(text: str):
    # XML widgets: android:text / android:contentDescription (strip @string/ ref prefix)
    for raw, kind, line in _finditer(
        r"<(?:Button|ImageButton|TextView)\b[^>]*android:text=[\"']([^\"']+)[\"']", text, "button"
    ):
        yield _android_label(raw), kind, line
    # contentDescription ONLY on interactive widgets — a decorative <ImageView
    # contentDescription> shouldn't become an expected affordance the oracle hunts for.
    for raw, kind, line in _finditer(
        r"<(?:Button|ImageButton)\b[^>]*android:contentDescription=[\"']([^\"']+)[\"']", text, "element"
    ):
        yield _android_label(raw), kind, line
    # Compose: Button/IconButton/TextButton { ... Text("Label") ... } via a small window
    yield from _compose_buttons(text)


def _android_label(raw: str) -> str:
    raw = re.sub(r"^@(?:string|id)/", "", raw)   # @string/save_btn -> save_btn
    return raw.replace("_", " ")


def _compose_buttons(text: str):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"\b(?:Button|TextButton|IconButton|OutlinedButton)\s*\(", line):
            window = " ".join(lines[i : i + 4])
            m = re.search(r"Text\s*\(\s*[\"']([^\"']+)[\"']", window)
            if m:
                yield m.group(1), "button", i + 1


# --- ios (SwiftUI + UIKit) ---

def _extract_ios(text: str):
    # SwiftUI Button("Label") and NavigationLink("Label")
    yield from _finditer(r"Button\s*\(\s*[\"']([^\"']+)[\"']", text, "button")
    yield from _finditer(r"NavigationLink\s*\(\s*[\"']([^\"']+)[\"']", text, "link")
    yield from _finditer(r"\.accessibilityIdentifier\(\s*[\"']([^\"']+)[\"']", text, "element")
    # UIKit: button.setTitle("Label", for:)
    yield from _finditer(r"setTitle\(\s*[\"']([^\"']+)[\"']", text, "button")
    # SwiftUI Button(action:) { Text("Label") } via a small window
    yield from _swift_action_buttons(text)


def _swift_action_buttons(text: str):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"Button\s*\(\s*action\s*:", line):
            window = " ".join(lines[i : i + 4])
            m = re.search(r"Text\s*\(\s*[\"']([^\"']+)[\"']", window)
            if m:
                yield m.group(1), "button", i + 1


# --- react native (JS/TS components; source is shared across android + ios) ---

_RN_TOUCHABLES = ("TouchableOpacity", "TouchableHighlight", "TouchableWithoutFeedback", "Pressable")


def _extract_rn(text: str):
    # <Button title="Save" /> — RN's Button uses the `title` prop, not children
    yield from _finditer(r"<Button\b[^>]*\btitle=[\"']([^\"']+)[\"']", text, "button")
    yield from _finditer(r"<TextInput\b[^>]*\bplaceholder=[\"']([^\"']+)[\"']", text, "input")
    yield from _finditer(r"accessibilityLabel=[\"']([^\"']+)[\"']", text, "element")
    # touchables wrap a <Text> child — grab the first Text label in a small window
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if any(f"<{t}" in line for t in _RN_TOUCHABLES):
            window = " ".join(lines[i : i + 5])
            m = re.search(r"<Text\b[^>]*>([^<]+)</Text>", window)
            if m:
                yield m.group(1), "button", i + 1


# --- flutter (Dart widgets; source is shared across android + ios) ---

_FLUTTER_BUTTONS = (
    "ElevatedButton", "TextButton", "OutlinedButton", "FilledButton",
    "IconButton", "FloatingActionButton", "CupertinoButton",
)


def _extract_flutter(text: str):
    # TextField hint/label, Tooltip message, Semantics label → declared affordances
    yield from _finditer(r"(?:hintText|labelText)\s*:\s*[\"']([^\"']+)[\"']", text, "input")
    yield from _finditer(r"Tooltip\s*\(\s*message\s*:\s*[\"']([^\"']+)[\"']", text, "element")
    yield from _finditer(r"Semantics\s*\([^)]*?label\s*:\s*[\"']([^\"']+)[\"']", text, "element")
    # button widgets: child:/label: Text('Label') in a small window after the widget
    lines = text.splitlines()
    button_re = re.compile(r"\b(?:" + "|".join(_FLUTTER_BUTTONS) + r")\b")
    for i, line in enumerate(lines):
        if button_re.search(line):
            window = " ".join(lines[i : i + 5])
            m = re.search(r"Text\s*\(\s*[\"']([^\"']+)[\"']", window)
            if m:
                yield m.group(1), "button", i + 1
