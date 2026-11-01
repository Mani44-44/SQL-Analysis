"""Checkpointing and resume for long benchmark runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.eval.checkpoint import Checkpoint, CheckpointMismatchError, checkpoint_path
from app.eval.metrics import CaseOutcome

META = {"dataset": "d", "model": "qwen3.5:9b", "config": "+samples", "git": "abc"}


def _outcome(case_id: str, error: str | None = None) -> CaseOutcome:
    return CaseOutcome(
        case_id=case_id,
        repeat=0,
        expected_kind="sql",
        difficulty="easy",
        tags=["t"],
        predicted_kind="sql",
        predicted_sql="SELECT 1",
        exec_match=error is None,
        error_type=error,
    )


def test_records_reload_and_skip_retryable(tmp_path: Path) -> None:
    path = checkpoint_path(tmp_path, META)
    assert ":" not in path.name and path.name.endswith("+samples.jsonl")
    cp = Checkpoint.open(path, META)
    cp.record(_outcome("a"))
    cp.record(_outcome("b", error="wrong_join"))
    cp.record(_outcome("c", error="llm_unavailable"))  # retried on resume, never stored
    with path.open("a", encoding="utf-8") as f:
        f.write('{"outcome": {"case_id": "tor')  # crash mid-write

    again = Checkpoint.open(path, META)
    assert set(again.outcomes) == {("a", 0), ("b", 0)}
    assert again.outcomes[("b", 0)].error_type == "wrong_join"
    assert not again.done
    again.mark_done()
    assert Checkpoint.open(path, META).done


def test_refuses_to_mix_runs_unless_fresh(tmp_path: Path) -> None:
    path = checkpoint_path(tmp_path, META)
    Checkpoint.open(path, META).record(_outcome("a"))
    other = {**META, "git": "def"}
    with pytest.raises(CheckpointMismatchError):
        Checkpoint.open(path, other)
    assert Checkpoint.open(path, other, fresh=True).outcomes == {}


def test_cli_resumes_interrupted_config_and_skips_finished(
    db: Session,
    demo_ws: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import app.eval.run as run_mod

    monkeypatch.setattr(run_mod, "_setup_workspace", lambda reseed: (db, demo_ws))
    out = tmp_path / "out"
    argv = ["--smoke", "--provider", "oracle", "--no-db", "--out", str(out), "--resume"]

    assert run_mod.main(argv) == 0
    reports = sorted(out.glob("*_full.json"))
    first = json.loads(reports[0].read_text(encoding="utf-8"))
    (cp_file,) = (out / "checkpoints").glob("*.jsonl")
    lines = cp_file.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1]) == {"done": True}
    n = len(first["outcomes"])
    assert len(lines) == n + 2  # header + one line per case + done

    # Rerunning the finished config does no work and writes no new report.
    capsys.readouterr()
    assert run_mod.main(argv) == 0
    assert "already finished" in capsys.readouterr().err
    assert sorted(out.glob("*_full.json")) == reports

    # Simulate a crash after 10 cases (plus a torn line), then resume.
    cp_file.write_text("\n".join(lines[:11]) + '\n{"outcome": {"ca', encoding="utf-8")
    for r in reports:
        r.unlink()
    capsys.readouterr()
    assert run_mod.main(argv) == 0
    err = capsys.readouterr().err
    assert "10 case(s) already done" in err
    assert err.count(f"/{n} ") == n - 10  # only the remaining cases ran
    resumed = json.loads(next(out.glob("*_full.json")).read_text(encoding="utf-8"))

    def scores(summary: dict) -> dict:  # timings legitimately differ between runs
        return {k: v for k, v in summary.items() if not k.startswith("latency")}

    assert scores(resumed["summary"]) == scores(first["summary"])
    assert [o["case_id"] for o in resumed["outcomes"]] == [o["case_id"] for o in first["outcomes"]]
