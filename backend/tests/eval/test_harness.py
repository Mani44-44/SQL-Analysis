"""End-to-end harness tests with the deterministic oracle: the expected metrics are known exactly."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import REPO_DIR
from app.eval.dataset import EVAL_DATA_DIR, load_dataset, load_fewshot_pool
from app.eval.error_category import categorize
from app.eval.metrics import CaseOutcome, bootstrap_ci, summarise
from app.eval.mock_oracle import build_oracle, plan
from app.eval.runner import make_config, run_benchmark
from app.services.schema.cards import load_workspace_schema


def test_dataset_loads_and_is_in_sync_with_builder() -> None:
    cases = load_dataset("finance_v1")
    assert len(cases) >= 80
    kinds = {c.expected_kind for c in cases}
    assert kinds == {"sql", "clarify", "unanswerable"}
    smoke = load_dataset("finance_v1", smoke=True)
    assert 20 <= len(smoke) <= 35
    assert {c.expected_kind for c in smoke} == kinds  # stratified
    builder = REPO_DIR / "eval_data" / "build_finance_v1.py"
    ns: dict[str, object] = {"__name__": "finance_v1_builder"}
    exec(compile(builder.read_text(encoding="utf-8"), str(builder), "exec"), ns)
    render = ns["render"]
    assert callable(render)
    assert render() == (EVAL_DATA_DIR / "finance_v1.jsonl").read_text(encoding="utf-8")


def _norm(q: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", q.lower()))


def test_no_benchmark_leakage() -> None:
    """Benchmark questions must not appear in few-shot pools, demo suggestions or prompts."""
    from app.demo.questions import DEMO_QUESTIONS
    from app.prompts import PROMPTS_DIR

    bench = [_norm(c.question) for c in load_dataset("finance_v1")]
    others = [q for q, _ in load_fewshot_pool()] + [d.question for d in DEMO_QUESTIONS]
    for other in others:
        o = _norm(other)
        for b in bench:
            jaccard = len(o & b) / len(o | b)
            assert jaccard < 0.8, f"near-duplicate of a benchmark question: {other!r}"
    prompt_text = " ".join(p.read_text(encoding="utf-8") for p in PROMPTS_DIR.glob("*.md")).lower()
    for c in load_dataset("finance_v1"):
        assert c.question.lower() not in prompt_text


def test_gold_sql_valid_and_roundtrip_stable(db: Session, demo_ws: str) -> None:
    from app.eval.run import check_gold

    assert check_gold("finance_v1", demo_ws, db) == []


def test_oracle_benchmark_exact_metrics(db: Session, demo_ws: str) -> None:
    cases = load_dataset("finance_v1")
    schema = load_workspace_schema(db, demo_ws)
    report = run_benchmark(
        cases=cases,
        provider=build_oracle(cases),
        workspace_id=demo_ws,
        schema=schema,
        dataset="finance_v1",
        concurrency=4,
        db=db,
    )
    p = plan(cases)
    n_sql = sum(1 for c in cases if c.expected_kind == "sql")
    n_other = len(cases) - n_sql
    wrong = sum(1 for v in p.values() if v == "wrong")
    correctable = sum(1 for v in p.values() if v == "correctable")
    wrong_kind = sum(1 for v in p.values() if v == "wrong_kind")
    s = report.summary
    assert s["execution_accuracy"] == pytest.approx((n_sql - wrong) / n_sql, abs=1e-4)
    assert s["kind_accuracy"] == pytest.approx((n_other - wrong_kind) / n_other, abs=1e-4)
    assert s["first_attempt_accuracy"] == pytest.approx(
        (n_sql - wrong - correctable) / n_sql, abs=1e-4
    )
    assert s["self_correction_recovery_rate"] == pytest.approx(
        correctable / (wrong + correctable), abs=1e-4
    )
    assert s["accuracy"] == pytest.approx(
        (n_sql - wrong + n_other - wrong_kind) / len(cases), abs=1e-4
    )
    assert s["valid_sql_rate"] == 1.0
    assert sum(s["error_categories"].values()) == wrong + wrong_kind
    assert s["error_categories"]["kind_mismatch"] == wrong_kind
    lo, hi = s["accuracy_ci95"]
    assert lo <= s["accuracy"] <= hi
    assert report.run_id


def test_eval_api(client: TestClient, db: Session, demo_ws: str) -> None:
    cases = load_dataset("finance_v1", smoke=True)
    schema = load_workspace_schema(db, demo_ws)
    a = run_benchmark(cases=cases, provider=build_oracle(cases), workspace_id=demo_ws, schema=schema,
                      dataset="finance_v1", db=db)  # fmt: skip
    b = run_benchmark(cases=cases, provider=build_oracle(cases), workspace_id=demo_ws, schema=schema,
                      dataset="finance_v1", db=db, config_name="schema_only")  # fmt: skip
    runs = client.get("/api/v1/eval/runs").json()
    assert {r["id"] for r in runs} >= {a.run_id, b.run_id}
    detail = client.get(f"/api/v1/eval/runs/{a.run_id}").json()
    assert len(detail["results"]) == len(cases)
    cmp = client.get(f"/api/v1/eval/compare?a={a.run_id}&b={b.run_id}").json()
    assert "accuracy" in cmp["metrics"]
    assert client.get("/api/v1/eval/runs/" + "0" * 32).status_code == 404


def test_metrics_endpoint(client: TestClient, demo_ws: str) -> None:
    from app.demo.questions import DEMO_QUESTIONS

    run = client.post(
        f"/api/v1/workspaces/{demo_ws}/ask", json={"question": DEMO_QUESTIONS[0].question}
    ).json()
    client.post(f"/api/v1/workspaces/{demo_ws}/ask", json={"question": "unknown thing"})
    client.post(f"/api/v1/query-runs/{run['query_run_id']}/feedback", json={"rating": -1})
    m = client.get("/api/v1/metrics").json()
    assert m["total_queries"] == 2
    assert m["success_rate"] == 0.5
    assert m["thumbs_down_rate"] == 1.0
    assert sum(m["queries_per_day"].values()) == 2


def test_ablation_configs() -> None:
    assert make_config("schema_only").use_samples is False
    assert make_config("+few_shot").few_shot
    assert make_config("+linking").force_linking is True
    with pytest.raises(ValueError):
        make_config("nope")


def test_bootstrap_ci_bounds() -> None:
    lo, hi = bootstrap_ci([1.0] * 50 + [0.0] * 50)
    assert 0.35 < lo < 0.5 < hi < 0.65
    assert bootstrap_ci([]) == (0.0, 0.0)


def test_summarise_repeats() -> None:
    outs = [
        CaseOutcome("c1", r, "sql", "easy", ["x"], "sql", "s", exec_match=(r == 0))
        for r in range(2)
    ] + [
        CaseOutcome("c2", r, "clarify", "hard", ["y"], "clarify", None, kind_match=True)
        for r in range(2)
    ]
    s = summarise(outs)
    assert s["repeats"] == 2 and s["n_cases"] == 2
    assert s["accuracy"] == 0.75
    assert s["accuracy_per_repeat"] == [1.0, 0.5]


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        (dict(expected_kind="sql", predicted_kind="clarify"), "kind_mismatch"),
        (dict(error_code="unknown_column"), "hallucinated_column"),
        (dict(error_code="table_function"), "validation_error"),
        (dict(error_code="timeout"), "execution_error"),
        (dict(gold_sql="SELECT a FROM t", predicted_sql="SELECT a FROM u"), "wrong_table"),
        (
            dict(gold_sql="SELECT sum(a) FROM t", predicted_sql="SELECT avg(a) FROM t"),
            "wrong_aggregation",
        ),
        (
            dict(
                gold_sql="SELECT a FROM t JOIN u ON t.k = u.k", predicted_sql="SELECT a FROM t, u"
            ),
            "wrong_join",
        ),
        (
            dict(gold_sql="SELECT year(d) FROM t", predicted_sql="SELECT month(d) FROM t"),
            "date_handling",
        ),
        (
            dict(
                gold_sql="SELECT a FROM t WHERE s = 'Success'",
                predicted_sql="SELECT a FROM t WHERE s = 'success'",
            ),
            "wrong_filter",
        ),
    ],
)
def test_error_categories(kw: dict[str, str], expected: str) -> None:
    args = dict(
        expected_kind="sql",
        predicted_kind="sql",
        gold_sql=None,
        predicted_sql=None,
        error_code=None,
    )
    args.update(kw)
    assert categorize(**args) == expected  # type: ignore[arg-type]


def test_cli_compare(tmp_path: Path) -> None:
    from app.eval.run import main

    a = {
        "summary": {"accuracy": 0.5},
        "outcomes": [
            {
                "case_id": "x",
                "repeat": 0,
                "expected_kind": "sql",
                "exec_match": False,
                "kind_match": True,
            }
        ],
    }
    b = {
        "summary": {"accuracy": 0.6},
        "outcomes": [
            {
                "case_id": "x",
                "repeat": 0,
                "expected_kind": "sql",
                "exec_match": True,
                "kind_match": True,
            }
        ],
    }
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(a))
    pb.write_text(json.dumps(b))
    assert main(["--compare", str(pa), str(pb)]) == 0


def test_regression_gate(tmp_path: Path) -> None:
    from app.eval.run import _gate

    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({"status": "pending"}))
    assert _gate({"accuracy": 0.1}, base, "smoke", 5) == 0
    base.write_text(json.dumps({"status": "set", "smoke": {"accuracy": 0.80}}))
    assert _gate({"accuracy": 0.78}, base, "smoke", 5) == 0
    assert _gate({"accuracy": 0.70}, base, "smoke", 5) == 2


def test_cli_refuses_run_where_model_is_unreachable(
    db: Session, demo_ws: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.eval.run as run_mod
    from app.services.llm.base import LLMUnavailableError

    class Unreachable:
        name = "anthropic"

        def model_for(self, tier: object) -> str:
            return "claude-opus-5-5"

        def complete_json(self, *a: object, **kw: object) -> object:
            raise LLMUnavailableError("credit balance too low")

    monkeypatch.setattr(run_mod, "_provider", lambda name, cases: Unreachable())
    monkeypatch.setattr(run_mod, "_setup_workspace", lambda reseed: (db, demo_ws))
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"status": "pending"}')
    code = run_mod.main(
        [
            "--smoke",
            "--no-db",
            "--out",
            str(tmp_path / "out"),
            "--baseline",
            str(baseline),
            "--update-baseline",
        ]
    )
    assert code == 3
    assert json.loads(baseline.read_text())["status"] == "pending"
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())
