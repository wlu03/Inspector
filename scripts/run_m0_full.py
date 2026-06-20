"""Full live M0 loop through the Session (records a replay):
launch -> observe -> click Save -> verify-after-act -> re-observe -> report finding.
Writes the trace + an HTML replay under ./replays/<session_id>/.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from loopback.config import Config  # noqa: E402
from loopback.findings import build_finding  # noqa: E402
from loopback.models import ActionType, Confidence, Severity, Surface  # noqa: E402
from loopback.replay import write_replay_html, write_replay_video  # noqa: E402
from loopback.session import Session  # noqa: E402

REPO = os.path.abspath("examples/sample-buggy-app")


def find_save(elements):
    for e in elements:
        if "save" in (e.label or "").lower():
            return e
    return None


def main() -> None:
    cfg = Config.from_env()
    cfg.trace_root = os.path.abspath("replays")  # keep replays inside the project
    s = Session(REPO, Surface.WEB, cfg, goal="verify the settings save flow")
    try:
        print("launching ...", flush=True)
        if not s.launch():
            print("app never became ready"); return

        print("observing ...", flush=True)
        som, elements, logs = s.observe()
        print(f"detected {len(elements)} elements:")
        for e in elements:
            bb = [round(b, 3) for b in e.bbox]
            print(f"  #{e.id} [{e.role}] {e.label!r:28.28} bbox={bb} click={e.interactivity}")

        save = find_save(elements)
        if not save:
            print("\n!! could not find a 'Save' element by label — inspect the list above")
        else:
            print(f"\nclicking Save -> element #{save.id} ({save.label!r})", flush=True)
            _som2, changed, logs2 = s.act(ActionType.CLICK, target_id=save.id)
            print(f"verify-after-act: changed={changed}")

            print("re-observing to check for the expected 'Saved' confirmation ...", flush=True)
            _som3, elements3, _logs3 = s.observe()
            saved = any("saved" in (e.label or "").lower() for e in elements3)
            print(f"'Saved' confirmation present after click: {saved}")

            if not saved:
                f = build_finding(
                    session_id=s.record.id,
                    trace_id=s.record.trace_id,
                    summary="Save button shows no confirmation",
                    expected="clicking Save shows a 'Saved' confirmation",
                    actual="after clicking Save, no 'Saved' confirmation appeared (UI unchanged)",
                    repro=["open the app", f"click the Save button (element #{save.id})", "observe: no confirmation"],
                    suspected_area="examples/sample-buggy-app/main.js — Save click handler",
                    severity=Severity.MEDIUM,
                    confidence=Confidence.HIGH,
                )
                s.trace.save_finding(f)
                s.record.findings.append(f.id)
                print(f"\nFINDING: {f.summary} — {f.actual}")

        s.trace.save_session(s.record)
        captions = [
            "1. observe — initial state",
            "2. before click: Save",
            "3. after click: Save",
            "4. re-observe — no 'Saved' confirmation (BUG)",
        ]
        video = write_replay_video(s.trace.dir, captions=captions)
        replay = write_replay_html(s.trace.dir)
        print(f"\ntrace dir : {s.trace.dir}")
        print(f"video     : {video}")
        print(f"replay    : {replay}")
        print(f"open it   : open {replay}")
    finally:
        s.teardown()
        print("done.", flush=True)


if __name__ == "__main__":
    main()
