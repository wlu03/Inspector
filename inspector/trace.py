from __future__ import annotations

import json
import os

from .models import Action, Finding, Run, SessionRecord


class TraceRecorder:
    """Writes the on-disk trace (dashboard-ready schema from docs/06).

    ~/.inspector/sessions/<session_id>/
        session.json
        run.json
        actions.jsonl      # one Action per line — the replay timeline + re-run script
        logs.jsonl
        frames/frame_NNNN.png
        findings/<id>.json
    """

    def __init__(self, trace_root: str, session_id: str):
        self.dir = os.path.join(trace_root, session_id)
        self.frames_dir = os.path.join(self.dir, "frames")
        self.findings_dir = os.path.join(self.dir, "findings")
        os.makedirs(self.frames_dir, exist_ok=True)
        os.makedirs(self.findings_dir, exist_ok=True)
        self.actions_path = os.path.join(self.dir, "actions.jsonl")
        self.logs_path = os.path.join(self.dir, "logs.jsonl")
        self._frame_n = 0

    def save_frame(self, png: bytes) -> str:
        name = f"frame_{self._frame_n:04d}.png"
        with open(os.path.join(self.frames_dir, name), "wb") as f:
            f.write(png)
        self._frame_n += 1
        return name

    def record_action(self, action: Action) -> None:
        with open(self.actions_path, "a") as f:
            f.write(action.model_dump_json() + "\n")

    def record_logs(self, lines: list[str]) -> None:
        if not lines:
            return
        with open(self.logs_path, "a") as f:
            for line in lines:
                f.write(json.dumps({"line": line}) + "\n")

    def save_finding(self, finding: Finding) -> None:
        path = os.path.join(self.findings_dir, f"{finding.id}.json")
        with open(path, "w") as f:
            f.write(finding.model_dump_json(indent=2))

    def save_session(self, record: SessionRecord) -> None:
        with open(os.path.join(self.dir, "session.json"), "w") as f:
            f.write(record.model_dump_json(indent=2))

    def save_run(self, run: Run) -> None:
        with open(os.path.join(self.dir, "run.json"), "w") as f:
            f.write(run.model_dump_json(indent=2))

    def save_plan(self, plan) -> None:
        with open(os.path.join(self.dir, "plan.json"), "w") as f:
            f.write(plan.model_dump_json(indent=2))
