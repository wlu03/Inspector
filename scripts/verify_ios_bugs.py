"""a11y-state oracle verifier for sample-buggy-ios.

Drives each planted bug's exact trigger sequence on a booted iOS Simulator via
idb, then reads `idb ui describe-all` and asserts the bug-PRESENT condition. This
proves the (log-free) bugs are real and observable purely from the a11y tree —
and that the fixture is rigorous. No app logs are consulted.

Env: INSPECTOR_IDB_BIN (py3.10-3.12 idb), INSPECTOR_IOS_UDID (else first booted).
Assumes SampleBuggyApp.app is already built + installed.
"""

import json
import os
import shlex
import subprocess
import time

IDB = os.environ.get("INSPECTOR_IDB_BIN", "idb")
BUND = "com.inspector.SampleBuggyApp"


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def _udid() -> str:
    u = os.environ.get("INSPECTOR_IOS_UDID")
    if u:
        return u
    out = sh("xcrun simctl list devices booted -j")
    try:
        for devs in json.loads(out).get("devices", {}).values():
            for d in devs:
                if d.get("state") == "Booted":
                    return d["udid"]
    except Exception:
        pass
    raise SystemExit("no booted simulator (set INSPECTOR_IOS_UDID)")


UD = _udid()


def describe() -> list[dict]:
    try:
        return [n for n in json.loads(sh(f"{IDB} ui describe-all --udid {UD}")) if isinstance(n, dict)]
    except Exception:
        return []


def center(n: dict) -> tuple[float, float]:
    f = n.get("frame", {})
    return f.get("x", 0) + f.get("width", 0) / 2, f.get("y", 0) + f.get("height", 0) / 2


def find(pred) -> dict | None:
    return next((n for n in describe() if pred(n)), None)


def tap(x: float, y: float) -> None:
    sh(f"{IDB} ui tap --udid {UD} {int(x)} {int(y)}")
    time.sleep(0.5)


def _scroll_down() -> None:
    # swipe finger up → content scrolls up, revealing lower rows (the taller Wishlist
    # home pushes the nav links below the fold; a11y only describes visible nodes).
    sh(f"{IDB} ui swipe --udid {UD} 200 600 200 250")
    time.sleep(0.5)


def tap_label(label: str) -> bool:
    for _ in range(4):
        n = find(lambda n: n.get("AXLabel") == label and n.get("type") == "Button")
        if n:
            tap(*center(n))
            return True
        _scroll_down()
    return False


def tap_field(placeholder: str) -> bool:
    # an empty SwiftUI TextField carries its placeholder in AXValue
    for _ in range(4):
        n = find(lambda n: n.get("type") == "TextField" and n.get("AXValue") == placeholder)
        if n:
            tap(*center(n))
            return True
        _scroll_down()
    return False


def typ(text: str) -> None:
    sh(f"{IDB} ui text --udid {UD} {shlex.quote(text)}")
    time.sleep(0.6)


def back() -> None:
    n = find(lambda n: n.get("type") == "Button"
             and n.get("frame", {}).get("y", 999) < 105
             and n.get("frame", {}).get("x", 999) < 90)
    if n:
        tap(*center(n))
    else:
        tap(24, 67)  # back-chevron fallback
    time.sleep(0.8)


def nav_title() -> str | None:
    n = find(lambda n: n.get("type") == "Heading"
             and n.get("AXLabel") in ("My Wishlist", "Wish Details", "About"))
    return n.get("AXLabel") if n else None


def reset() -> None:
    sh(f"xcrun simctl terminate {UD} {BUND}")
    time.sleep(0.4)
    sh(f"xcrun simctl launch {UD} {BUND}")
    time.sleep(2.0)


def bug02_int_normalize():
    reset()
    tap_field("Item name"); typ("007")
    tap_label("Add"); time.sleep(0.6)
    fld = find(lambda n: n.get("type") == "TextField")
    saved = find(lambda n: n.get("AXLabel") == "Added")
    val = fld.get("AXValue") if fld else None
    return ("BUG-02", val == "7" and bool(saved), f"field={val!r}, added={bool(saved)} (PRESENT: '7' + Added)")


def bug03_counter():
    reset()
    tap_field("Item name"); typ("Alice")
    cnt = find(lambda n: (n.get("AXLabel") or "").endswith("/30"))
    lbl = cnt.get("AXLabel") if cnt else None
    return ("BUG-03", lbl == "4/30", f"counter={lbl!r} for 5 chars (PRESENT: '4/30')")


def bug06_theme():
    reset()
    tg = find(lambda n: n.get("type") == "TabGroup")
    if not tg:
        return ("BUG-06", False, "no TabGroup found")
    f = tg["frame"]; y = f["y"] + f["height"] / 2; x0 = f["x"]; w = f["width"]
    tap(x0 + w * 1 / 6, y)   # Light
    tap(x0 + w * 3 / 6, y)   # Dark
    cur = find(lambda n: (n.get("AXLabel") or "").startswith("Current theme"))
    lbl = cur.get("AXLabel") if cur else None
    return ("BUG-06", lbl == "Current theme: Light", f"{lbl!r} while Dark highlighted (PRESENT: 'Light')")


def bug04_completeness():
    reset()
    tap_label("Wish Details"); time.sleep(1.0)
    tap_field("Item name"); typ("Bob")
    tap_field("Price"); typ("$50")
    comp = find(lambda n: (n.get("AXLabel") or "").startswith("Wishlist"))
    lbl = comp.get("AXLabel") if comp else None
    return ("BUG-04", "66%" in (lbl or ""), f"{lbl!r} for 2 of 3 (PRESENT: 66%)")


def bug01_05_nav():
    reset()
    tap_label("Wish Details"); time.sleep(1.0)
    tap_field("Item name"); typ("Wesley")
    tap_field("Price"); typ("$10")
    tap_label("Continue"); time.sleep(1.0)      # navigates to About via buggy 3-deep stack
    back()                                       # -> duplicate Wish Details
    saved = find(lambda n: n.get("AXLabel") == "Wesley")
    dn = find(lambda n: n.get("type") == "TextField")  # first field = Item name
    dn_val = dn.get("AXValue") if dn else None
    bug01 = bool(saved) and dn_val in ("Item name", "", None)
    back()                                       # -> still Wish Details (one too deep)
    title = nav_title()
    bug05 = title == "Wish Details"
    return [
        ("BUG-01", bug01, f"savedName='Wesley':{bool(saved)}, field={dn_val!r} (PRESENT: saved set + field empty)"),
        ("BUG-05", bug05, f"title after 2 Backs={title!r} (PRESENT: still 'Wish Details')"),
    ]


def main():
    print(f"udid={UD} idb={IDB}\n")
    results = []
    for fn in (bug02_int_normalize, bug03_counter, bug06_theme, bug04_completeness):
        results.append(fn())
    results.extend(bug01_05_nav())
    results.sort(key=lambda r: r[0])
    npass = 0
    for bid, present, detail in results:
        mark = "PRESENT ✓" if present else "MISSING ✗"
        npass += int(present)
        print(f"  {bid}  {mark}  — {detail}")
    print(f"\n{npass}/{len(results)} planted bugs confirmed present via the a11y oracle")


if __name__ == "__main__":
    main()
