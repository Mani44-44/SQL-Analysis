"""Benchmark CLI.

Examples:
    python -m app.eval.run --check-gold
    python -m app.eval.run --provider oracle                 # harness wiring check, no key
    python -m app.eval.run --smoke --baseline ../eval_data/baseline.json
    python -m app.eval.run --configs schema_only,+samples,+linking,+glossary,+self_correction,+few_shot
    python -m app.eval.run --compare runA.json runB.json

Exit codes: 0 ok, 1 harness/gold failure, 2 regression against the baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import REPO_DIR, get_settings
from app.core.logging import configure_logging
from app.eval.dataset import load_dataset
from app.eval.matching import gold_is_ordered, match_results
from app.eval.report import (
    ablation_markdown,
    compare_markdown,
    compare_outcomes,
    outcomes_payload,
    summary_markdown,
    write_report,
)
from app.eval.runner import ABLATIONS, run_benchmark

DEFAULT_OUT = REPO_DIR / "eval_runs"


def _setup_workspace(reseed: bool) -> tuple[Any, str]:
    from app.db.migrate import upgrade_to_head
    from app.db.session import get_sessionmaker
    from app.demo.seed import seed_demo

    settings = get_settings()
    settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
    upgrade_to_head()
    db = get_sessionmaker()()
    ws = seed_demo(db, force=reseed)
    return db, ws.id


def check_gold(dataset: str, workspace_id: str, db: Any) -> list[str]:
    """Every gold query must run, return rows, and give identical results raw vs regenerated."""
    from app.services.execution.executor import execute_sql
    from app.services.execution.service import run_query
    from app.services.schema.cards import load_workspace_schema

    allowed = load_workspace_schema(db, workspace_id).allowed()
    problems: list[str] = []
    for case in load_dataset(dataset):
        if not case.gold_sql:
            continue
        try:
            via = run_query(workspace_id, case.gold_sql, allowed, row_cap=10_000)
            raw = execute_sql(workspace_id, case.gold_sql, row_cap=10_000, timeout_s=30)
        except Exception as e:
            problems.append(f"{case.id}: gold SQL failed: {e}")
            continue
        if not via.rows:
            problems.append(f"{case.id}: gold SQL returns no rows (weak case)")
        m = match_results(
            raw.columns, raw.rows, via.columns, via.rows, ordered=gold_is_ordered(case.gold_sql)
        )
        if not m.strict or raw.column_types != via.column_types:
            problems.append(f"{case.id}: result differs after sqlglot round trip")
    return problems


def _provider(name: str, cases: list[Any]) -> Any:
    from app.services.llm import build_provider

    if name == "oracle":
        from app.eval.mock_oracle import build_oracle

        return build_oracle(cases)
    settings = get_settings()
    if name == "anthropic":
        if settings.anthropic_api_key is None:
            raise SystemExit(
                "ANTHROPIC_API_KEY is not set; use --provider oracle for a wiring check"
            )
        settings = settings.model_copy(update={"llm_provider": "anthropic"})
    elif name == "mock":
        settings = settings.model_copy(update={"llm_provider": "mock"})
    return build_provider(settings)


def _gate(summary: dict[str, Any], baseline_path: Path, key: str, threshold: float) -> int:
    if not baseline_path.exists():
        print(f"[gate] no baseline at {baseline_path}; skipping")
        return 0
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    ref = baseline.get(key)
    if baseline.get("status") != "set" or not ref:
        print(f"[gate] baseline status is {baseline.get('status')!r}; skipping regression gate")
        return 0
    base_acc, new_acc = float(ref["accuracy"]), float(summary["accuracy"])
    drop = 100 * (base_acc - new_acc)
    print(
        f"[gate] {key}: baseline {100 * base_acc:.1f}% -> {100 * new_acc:.1f}% (drop {drop:+.1f} pts, threshold {threshold})"
    )
    return 2 if drop > threshold else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--dataset", default="finance_v1")
    p.add_argument("--smoke", action="store_true", help="only cases flagged smoke")
    p.add_argument("--configs", default="full", help=f"comma list from {sorted(ABLATIONS)}")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--provider", choices=["auto", "anthropic", "mock", "oracle"], default="auto")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--baseline", type=Path, default=None)
    p.add_argument(
        "--threshold", type=float, default=5.0, help="max allowed accuracy drop (points)"
    )
    p.add_argument("--update-baseline", action="store_true")
    p.add_argument("--reseed", action="store_true", help="recreate the demo workspace first")
    p.add_argument("--check-gold", action="store_true")
    p.add_argument("--no-db", action="store_true", help="do not persist the run to the app DB")
    p.add_argument("--compare", nargs=2, type=Path, metavar=("A_JSON", "B_JSON"))
    args = p.parse_args(argv)
    configure_logging("WARNING", json_logs=False)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.compare:
        a, b = (json.loads(x.read_text(encoding="utf-8")) for x in args.compare)
        print(
            compare_markdown(args.compare[0].stem, a["summary"], args.compare[1].stem, b["summary"])
        )
        flips = compare_outcomes(a.get("outcomes", []), b.get("outcomes", []))
        print(f"fixed: {flips['fixed']}\nbroken: {flips['broken']}")
        return 0

    db, workspace_id = _setup_workspace(args.reseed)
    try:
        if args.check_gold:
            problems = check_gold(args.dataset, workspace_id, db)
            for line in problems:
                print(f"[gold] {line}")
            print(f"[gold] {len(problems)} problem(s)")
            return 1 if problems else 0

        cases = load_dataset(args.dataset, smoke=args.smoke)
        provider = _provider(args.provider, cases)
        from app.services.schema.cards import load_workspace_schema

        schema = load_workspace_schema(db, workspace_id)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        rows: list[tuple[str, dict[str, Any]]] = []
        exit_code = 0
        for config_name in [c.strip() for c in args.configs.split(",") if c.strip()]:
            report = run_benchmark(
                cases=cases,
                provider=provider,
                workspace_id=workspace_id,
                schema=schema,
                dataset=args.dataset,
                config_name=config_name,
                repeats=args.repeats,
                concurrency=args.concurrency,
                db=None if args.no_db else db,
            )
            meta = {
                "dataset": args.dataset + (" (smoke)" if args.smoke else ""),
                "config": config_name,
                "provider": provider.name,
                "model": report.model,
                "prompt": report.prompt_version,
                "git": report.git_sha,
                "run_id": report.run_id,
            }
            md = summary_markdown(
                report.summary, title=f"AskData benchmark — {config_name}", meta=meta
            )
            if provider.name in ("mock",) or args.provider == "oracle":
                md = (
                    "> ⚠️ Mock/oracle provider: these numbers check the harness, not a model.\n\n"
                    + md
                )
            payload = {
                "meta": meta,
                "summary": report.summary,
                "outcomes": outcomes_payload(report.outcomes),
            }
            safe = config_name.replace("+", "plus_")
            jp, mp = write_report(args.out, f"{stamp}_{args.dataset}_{safe}", payload, md)
            print(md)
            print(f"[report] {jp}\n[report] {mp}")
            rows.append((config_name, report.summary))

            key = "smoke" if args.smoke else "full"
            if args.baseline:
                exit_code = max(
                    exit_code, _gate(report.summary, args.baseline, key, args.threshold)
                )
                if args.update_baseline and args.provider != "oracle":
                    base = (
                        json.loads(args.baseline.read_text(encoding="utf-8"))
                        if args.baseline.exists()
                        else {}
                    )
                    base.update(
                        {
                            "status": "set",
                            "dataset": args.dataset,
                            "model": report.model,
                            "prompt": report.prompt_version,
                        }
                    )
                    base[key] = {
                        "accuracy": report.summary["accuracy"],
                        "git": report.git_sha,
                        "date": stamp,
                    }
                    args.baseline.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
                    print(f"[gate] baseline updated: {args.baseline}")
        if len(rows) > 1:
            table = ablation_markdown(rows)
            (args.out / f"{stamp}_{args.dataset}_ablation.md").write_text(table, encoding="utf-8")
            print(table)
        return exit_code
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
