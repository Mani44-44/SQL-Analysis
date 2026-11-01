"""Per-case checkpoints so a long benchmark run can resume after a crash.

One JSONL file per (run identity, config). The first line is a header with the identity
(dataset, model, config, code and prompt version...). Every scored case is appended and fsynced
as soon as it finishes, and a final `{"done": ...}` line marks the config complete. Resuming
skips cases already recorded; a header mismatch refuses to mix results from different runs.

Cases that failed only because the model couldn't be reached are not recorded, so a resumed run
retries them instead of keeping a failure that says nothing about the model.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.eval.metrics import CaseOutcome

RETRYABLE = {"llm_unavailable", "harness_error"}


class CheckpointMismatchError(Exception):
    pass


def checkpoint_path(directory: Path, meta: dict[str, Any]) -> Path:
    raw = f"{meta['dataset']}_{meta['model']}_{meta['config']}"
    return directory / (re.sub(r"[^A-Za-z0-9._+-]+", "-", raw) + ".jsonl")


class Checkpoint:
    def __init__(self, path: Path, meta: dict[str, Any]) -> None:
        self.path = path
        self.meta = meta
        self.outcomes: dict[tuple[str, int], CaseOutcome] = {}
        self.done = False

    @classmethod
    def open(cls, path: Path, meta: dict[str, Any], *, fresh: bool = False) -> Checkpoint:
        cp = cls(path, meta)
        if fresh and path.exists():
            path.unlink()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            cp._append({"meta": meta})
            return cp
        raw = path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            # A crash mid-write left a partial last line: cut it off so the next append
            # starts on a fresh line instead of being glued onto it.
            raw = raw[: raw.rfind(b"\n") + 1]
            path.write_bytes(raw)
        lines = raw.decode("utf-8").splitlines()
        header = json.loads(lines[0]).get("meta") if lines else None
        if header != meta:
            raise CheckpointMismatchError(
                f"{path} belongs to a different run ({header}); "
                "pass --fresh to discard it or delete the file"
            )
        for line in lines[1:]:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:  # a torn final line from a crash mid-write
                continue
            if rec.get("done"):
                cp.done = True
            elif "outcome" in rec:
                o = CaseOutcome(**rec["outcome"])
                cp.outcomes[(o.case_id, o.repeat)] = o
        return cp

    def record(self, outcome: CaseOutcome) -> None:
        if outcome.error_type in RETRYABLE:
            return
        self.outcomes[(outcome.case_id, outcome.repeat)] = outcome
        self._append({"outcome": asdict(outcome)})

    def mark_done(self) -> None:
        self.done = True
        self._append({"done": True})

    def _append(self, rec: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
