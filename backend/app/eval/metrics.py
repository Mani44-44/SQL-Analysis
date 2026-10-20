"""Benchmark metrics with bootstrap confidence intervals."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import Any


@dataclass
class CaseOutcome:
    case_id: str
    repeat: int
    expected_kind: str
    difficulty: str
    tags: list[str]
    predicted_kind: str | None
    predicted_sql: str | None
    exec_match: bool = False
    superset_match: bool = False
    kind_match: bool = False
    first_attempt_match: bool = False
    valid_sql: bool = False
    execution_error: bool = False
    error_type: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def correct(self) -> bool:
        """Overall correctness: execution match for SQL cases, kind match otherwise."""
        if self.expected_kind == "sql":
            return self.exec_match
        return self.kind_match


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def bootstrap_ci(
    per_case: list[float], *, iterations: int = 1000, seed: int = 7, alpha: float = 0.05
) -> tuple[float, float]:
    """Percentile bootstrap CI over cases (cases are the resampling unit)."""
    if not per_case:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(per_case)
    stats = sorted(mean(rng.choices(per_case, k=n)) for _ in range(iterations))
    return (stats[int(alpha / 2 * iterations)], stats[int((1 - alpha / 2) * iterations) - 1])


def _rate(outcomes: list[CaseOutcome], attr: str) -> float:
    return (
        round(sum(1 for o in outcomes if getattr(o, attr)) / len(outcomes), 4) if outcomes else 0.0
    )


def summarise(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    if not outcomes:
        return {"n_cases": 0}
    sql_cases = [o for o in outcomes if o.expected_kind == "sql"]
    kind_cases = [o for o in outcomes if o.expected_kind != "sql"]
    repeats = sorted({o.repeat for o in outcomes})

    # Per-case accuracy averaged over repeats -> bootstrap unit.
    by_case: dict[str, list[CaseOutcome]] = defaultdict(list)
    for o in outcomes:
        by_case[o.case_id].append(o)
    per_case_acc = [mean(1.0 if x.correct else 0.0 for x in xs) for xs in by_case.values()]
    per_repeat = [
        mean(1.0 if o.correct else 0.0 for o in outcomes if o.repeat == r) for r in repeats
    ]
    ci_lo, ci_hi = bootstrap_ci(per_case_acc)

    first_wrong = [o for o in sql_cases if not o.first_attempt_match]
    recovered = [o for o in first_wrong if o.exec_match]

    def breakdown(key: str) -> dict[str, dict[str, float]]:
        groups: dict[str, list[CaseOutcome]] = defaultdict(list)
        for o in outcomes:
            values = o.tags if key == "tags" else [getattr(o, key)]
            for v in values:
                groups[v].append(o)
        return {
            k: {
                "n": len(v) / len(repeats),
                "accuracy": round(mean(1.0 if o.correct else 0.0 for o in v), 4),
            }
            for k, v in sorted(groups.items())
        }

    latencies = [float(o.latency_ms) for o in outcomes]
    errors = Counter(o.error_type for o in outcomes if not o.correct and o.error_type)
    return {
        "n_cases": len(by_case),
        "repeats": len(repeats),
        "accuracy": round(mean(per_case_acc), 4),
        "accuracy_ci95": [round(ci_lo, 4), round(ci_hi, 4)],
        "accuracy_per_repeat": [round(a, 4) for a in per_repeat],
        "execution_accuracy": _rate(sql_cases, "exec_match"),
        "superset_accuracy": _rate(sql_cases, "superset_match"),
        "first_attempt_accuracy": _rate(sql_cases, "first_attempt_match"),
        "kind_accuracy": _rate(kind_cases, "kind_match"),
        "valid_sql_rate": _rate([o for o in sql_cases if o.predicted_kind == "sql"], "valid_sql"),
        "execution_error_rate": _rate(sql_cases, "execution_error"),
        "self_correction_recovery_rate": round(len(recovered) / len(first_wrong), 4)
        if first_wrong
        else 0.0,
        "mean_attempts": round(mean(o.attempts for o in sql_cases), 3) if sql_cases else 0.0,
        "latency_ms_p50": round(percentile(latencies, 0.5)),
        "latency_ms_p95": round(percentile(latencies, 0.95)),
        "cost_usd_total": round(sum(o.cost_usd for o in outcomes), 4),
        "cost_usd_per_case": round(mean(o.cost_usd for o in outcomes), 6),
        "tokens_in_total": sum(o.tokens_in for o in outcomes),
        "tokens_out_total": sum(o.tokens_out for o in outcomes),
        "by_difficulty": breakdown("difficulty"),
        "by_tag": breakdown("tags"),
        "error_categories": dict(errors.most_common()),
    }
