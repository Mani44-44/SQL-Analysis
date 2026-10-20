"""Benchmark runner: executes cases through the real pipeline and scores them."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import REPO_DIR, get_settings
from app.db.models import EvalResult, EvalRun
from app.eval.dataset import EvalCase, load_fewshot_pool
from app.eval.error_category import categorize
from app.eval.matching import gold_is_ordered, match_results
from app.eval.metrics import CaseOutcome, summarise
from app.prompts import load_prompt
from app.services.execution.executor import ExecutionError, ExecutionResult
from app.services.execution.service import run_query
from app.services.llm import LLMProvider, Tier
from app.services.schema.cards import WorkspaceSchema
from app.services.sqlguard import SqlGuardError
from app.services.text2sql.models import PipelineConfig
from app.services.text2sql.pipeline import Text2SQLPipeline

logger = logging.getLogger(__name__)

EVAL_ROW_CAP = 10_000

# Ablation ladder (spec section 9.3). Each config adds one capability to the previous.
ABLATIONS: dict[str, dict[str, Any]] = {
    "schema_only": dict(use_samples=False, use_linking=False, use_glossary=False, self_correction=False),
    "+samples": dict(use_samples=True, use_linking=False, use_glossary=False, self_correction=False),
    "+linking": dict(use_samples=True, use_linking=True, force_linking=True, use_glossary=False, self_correction=False),
    "+glossary": dict(use_samples=True, use_linking=True, force_linking=True, use_glossary=True, self_correction=False),
    "+self_correction": dict(use_samples=True, use_linking=True, force_linking=True, use_glossary=True, self_correction=True),
    "full": dict(use_samples=True, use_linking=True, use_glossary=True, self_correction=True),
    "+few_shot": dict(use_samples=True, use_linking=True, use_glossary=True, self_correction=True, few_shot=True),
}  # fmt: skip


def make_config(name: str) -> PipelineConfig:
    if name not in ABLATIONS:
        raise ValueError(f"unknown config {name!r}; choose from {sorted(ABLATIONS)}")
    opts = dict(ABLATIONS[name])
    few = opts.pop("few_shot", False)
    cfg = PipelineConfig(explain=False, row_cap=EVAL_ROW_CAP, **opts)
    if few:
        cfg.few_shot = load_fewshot_pool()
    return cfg


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class RunReport:
    run_id: str | None
    dataset: str
    config_name: str
    model: str
    prompt_version: str
    summary: dict[str, Any]
    outcomes: list[CaseOutcome] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    git_sha: str | None = None


class GoldCache:
    def __init__(self, workspace_id: str, schema: WorkspaceSchema) -> None:
        self.workspace_id = workspace_id
        self.allowed = schema.allowed()
        self._cache: dict[str, ExecutionResult] = {}

    def get(self, case: EvalCase) -> ExecutionResult:
        assert case.gold_sql is not None
        if case.id not in self._cache:
            self._cache[case.id] = run_query(
                self.workspace_id, case.gold_sql, self.allowed, row_cap=EVAL_ROW_CAP
            )
        return self._cache[case.id]


def score_case(
    case: EvalCase,
    repeat: int,
    pipeline: Text2SQLPipeline,
    workspace_id: str,
    schema: WorkspaceSchema,
    config: PipelineConfig,
    gold: GoldCache,
) -> CaseOutcome:
    result = pipeline.run(
        workspace_id=workspace_id, question=case.question, schema=schema, config=config
    )
    last_error = next((a.error_code for a in reversed(result.attempts) if a.error_code), None)
    out = CaseOutcome(
        case_id=case.id,
        repeat=repeat,
        expected_kind=case.expected_kind,
        difficulty=case.difficulty,
        tags=case.tags,
        predicted_kind=result.kind if result.status != "error" or result.attempts else None,
        predicted_sql=result.sql or (result.attempts[-1].sql if result.attempts else None),
        attempts=len(result.attempts),
        latency_ms=result.duration_ms,
        cost_usd=result.cost_usd,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )
    if result.error_code == "llm_unavailable" or result.error_code == "refusal":
        out.predicted_kind = None
        out.error_type = result.error_code
        return out
    out.kind_match = out.predicted_kind == case.expected_kind

    if case.expected_kind == "sql" and out.kind_match:
        gold_res = gold.get(case)
        ordered = gold_is_ordered(case.gold_sql or "")
        out.valid_sql = result.status == "ok" or (
            result.error_code is not None and result.error_code not in _VALIDATION_FAILURES
        )
        out.execution_error = result.status == "error"
        if result.status == "ok":
            m = match_results(
                gold_res.columns, gold_res.rows, result.columns, result.rows, ordered=ordered
            )
            out.exec_match, out.superset_match = m.strict, m.superset
        out.first_attempt_match = _first_attempt_match(
            result, out.exec_match, workspace_id, gold, gold_res, ordered
        )

    if not out.correct:
        out.error_type = categorize(
            expected_kind=case.expected_kind,
            predicted_kind=out.predicted_kind,
            gold_sql=case.gold_sql,
            predicted_sql=out.predicted_sql,
            error_code=result.error_code if result.status == "error" else None,
        )
    elif case.expected_kind == "sql" and len(result.attempts) > 1 and last_error:
        out.notes["recovered_from"] = result.attempts[0].error_code
    return out


_VALIDATION_FAILURES = {
    "parse_error", "multiple_statements", "not_select", "forbidden_statement", "table_function",
    "system_table", "forbidden_function", "unknown_table", "unknown_column", "recursive_cte",
    "cross_join", "too_long", "too_complex", "empty", "parameter",
}  # fmt: skip


def _first_attempt_match(
    result: Any,
    final_match: bool,
    workspace_id: str,
    gold: GoldCache,
    gold_res: ExecutionResult,
    ordered: bool,
) -> bool:
    if not result.attempts:
        return False
    if len(result.attempts) == 1:
        return final_match
    first = result.attempts[0]
    if first.error_code and first.error_code != "empty_result":
        return False
    try:
        res = run_query(workspace_id, first.sql, gold.allowed, row_cap=EVAL_ROW_CAP)
    except (SqlGuardError, ExecutionError):
        return False
    return match_results(
        gold_res.columns, gold_res.rows, res.columns, res.rows, ordered=ordered
    ).strict


def run_benchmark(
    *,
    cases: list[EvalCase],
    provider: LLMProvider,
    workspace_id: str,
    schema: WorkspaceSchema,
    dataset: str,
    config_name: str = "full",
    repeats: int = 1,
    concurrency: int = 4,
    db: Session | None = None,
    progress: Callable[[CaseOutcome], None] | None = None,
) -> RunReport:
    config = make_config(config_name)
    pipeline = Text2SQLPipeline(provider, get_settings(), cache=None)
    gold = GoldCache(workspace_id, schema)
    for c in cases:  # fail fast on broken gold SQL before spending tokens
        if c.gold_sql:
            gold.get(c)

    jobs = [(c, r) for r in range(repeats) for c in cases]
    outcomes: list[CaseOutcome] = []

    def work(job: tuple[EvalCase, int]) -> CaseOutcome:
        case, rep = job
        try:
            return score_case(case, rep, pipeline, workspace_id, schema, config, gold)
        except Exception:
            logger.exception("eval_case_crashed", extra={"case": case.id})
            return CaseOutcome(
                case_id=case.id, repeat=rep, expected_kind=case.expected_kind,
                difficulty=case.difficulty, tags=case.tags, predicted_kind=None,
                predicted_sql=None, error_type="harness_error",
            )  # fmt: skip

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        for outcome in pool.map(work, jobs):
            outcomes.append(outcome)
            if progress:
                progress(outcome)

    report = RunReport(
        run_id=None,
        dataset=dataset,
        config_name=config_name,
        model=provider.model_for(Tier.STRONG),
        prompt_version=load_prompt("generate_sql").tag,
        summary=summarise(outcomes),
        outcomes=outcomes,
        git_sha=git_sha(),
    )
    if db is not None:
        report.run_id = persist(db, report, provider_name=provider.name, repeats=repeats)
    return report


def persist(db: Session, report: RunReport, *, provider_name: str, repeats: int) -> str:
    run = EvalRun(
        dataset=report.dataset,
        git_sha=report.git_sha,
        model=report.model,
        prompt_version=report.prompt_version,
        config={"config": report.config_name, "provider": provider_name, "repeats": repeats},
        started_at=report.started_at,
        finished_at=datetime.now(UTC),
        summary=report.summary,
    )
    for o in report.outcomes:
        run.results.append(
            EvalResult(
                case_id=o.case_id,
                repeat=o.repeat,
                predicted_kind=o.predicted_kind,
                predicted_sql=o.predicted_sql,
                exec_match=o.exec_match,
                superset_match=o.superset_match,
                kind_match=o.kind_match,
                first_attempt_match=o.first_attempt_match,
                error_type=o.error_type,
                attempts=o.attempts,
                latency_ms=o.latency_ms,
                cost_usd=o.cost_usd,
            )
        )
    db.add(run)
    db.commit()
    return run.id
