"""Markdown / JSON reports and run comparison."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.eval.metrics import CaseOutcome

HEADLINE = [
    ("accuracy", "Overall accuracy"),
    ("execution_accuracy", "Execution accuracy (SQL cases)"),
    ("superset_accuracy", "Superset-column accuracy"),
    ("first_attempt_accuracy", "First-attempt accuracy"),
    ("kind_accuracy", "Clarify / unanswerable accuracy"),
    ("valid_sql_rate", "Valid-SQL rate"),
    ("execution_error_rate", "Execution-error rate"),
    ("self_correction_recovery_rate", "Self-correction recovery rate"),
]


def pct(v: Any) -> str:
    return f"{100 * float(v):.1f}%" if isinstance(v, int | float) else str(v)


def summary_markdown(summary: dict[str, Any], *, title: str, meta: dict[str, Any]) -> str:
    lines = [f"## {title}", ""]
    lines += [f"- **{k}**: {v}" for k, v in meta.items() if v is not None]
    lo, hi = summary.get("accuracy_ci95", [0, 0])
    lines += ["", "| Metric | Value |", "|---|---|"]
    for key, label in HEADLINE:
        val = pct(summary.get(key, 0))
        if key == "accuracy":
            val += f" (95% CI {pct(lo)} – {pct(hi)})"
        lines.append(f"| {label} | {val} |")
    lines += [
        f"| Latency p50 / p95 | {summary.get('latency_ms_p50', 0)} ms / {summary.get('latency_ms_p95', 0)} ms |",
        f"| Cost per case | ${summary.get('cost_usd_per_case', 0):.4f} |",
        f"| Cases × repeats | {summary.get('n_cases', 0)} × {summary.get('repeats', 1)} |",
        "",
        "### By difficulty",
        "",
        "| Difficulty | Cases | Accuracy |",
        "|---|---|---|",
    ]
    for k, v in summary.get("by_difficulty", {}).items():
        lines.append(f"| {k} | {v['n']:g} | {pct(v['accuracy'])} |")
    lines += ["", "### By tag", "", "| Tag | Cases | Accuracy |", "|---|---|---|"]
    for k, v in summary.get("by_tag", {}).items():
        lines.append(f"| {k} | {v['n']:g} | {pct(v['accuracy'])} |")
    errors = summary.get("error_categories", {})
    if errors:
        lines += ["", "### Failure categories", "", "| Category | Count |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in errors.items()]
    return "\n".join(lines) + "\n"


def ablation_markdown(rows: list[tuple[str, dict[str, Any]]]) -> str:
    lines = [
        "| Config | Accuracy | Exec acc. | Kind acc. | First-attempt | Cost / case | p50 latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in rows:
        lines.append(
            f"| {name} | {pct(s['accuracy'])} | {pct(s['execution_accuracy'])} | "
            f"{pct(s['kind_accuracy'])} | {pct(s['first_attempt_accuracy'])} | "
            f"${s['cost_usd_per_case']:.4f} | {s['latency_ms_p50']} ms |"
        )
    return "\n".join(lines) + "\n"


def compare_summaries(a: dict[str, Any], b: dict[str, Any]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for key, _ in HEADLINE:
        if key in a and key in b:
            out[key] = {"a": a[key], "b": b[key], "delta": round(b[key] - a[key], 4)}
    return out


def compare_outcomes(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Cases that flipped between runs (first repeat only)."""

    def correct(o: dict[str, Any]) -> bool:
        return bool(o["exec_match"] if o["expected_kind"] == "sql" else o["kind_match"])

    amap = {o["case_id"]: correct(o) for o in a if o.get("repeat", 0) == 0}
    bmap = {o["case_id"]: correct(o) for o in b if o.get("repeat", 0) == 0}
    common = sorted(set(amap) & set(bmap))
    return {
        "fixed": [c for c in common if not amap[c] and bmap[c]],
        "broken": [c for c in common if amap[c] and not bmap[c]],
    }


def compare_markdown(a_name: str, a: dict[str, Any], b_name: str, b: dict[str, Any]) -> str:
    cmp = compare_summaries(a, b)
    lines = [f"| Metric | {a_name} | {b_name} | Δ |", "|---|---|---|---|"]
    for key, label in HEADLINE:
        if key in cmp:
            d = cmp[key]["delta"]
            arrow = "🔺" if d > 0 else ("🔻" if d < 0 else "")
            lines.append(
                f"| {label} | {pct(cmp[key]['a'])} | {pct(cmp[key]['b'])} | {arrow} {100 * d:+.1f} pts |"
            )
    return "\n".join(lines) + "\n"


def write_report(
    out_dir: Path, stem: str, payload: dict[str, Any], markdown: str
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    jp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    mp.write_text(markdown, encoding="utf-8")
    return jp, mp


def outcomes_payload(outcomes: list[CaseOutcome]) -> list[dict[str, Any]]:
    return [asdict(o) for o in outcomes]
