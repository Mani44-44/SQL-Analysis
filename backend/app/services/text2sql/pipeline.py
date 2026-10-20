"""Text-to-SQL orchestrator: link -> generate -> validate -> execute -> self-correct.

Every stage is timed and costed into `PipelineResult.trace`; every attempt's SQL and error is
kept in `PipelineResult.attempts` (the eval needs attempt 1 for first-attempt accuracy).
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

from app.core.config import Settings, get_settings
from app.services.charts.picker import chart_dict
from app.services.execution.executor import ExecutionError
from app.services.execution.service import run_query
from app.services.llm import LLMError, LLMProvider, LLMRefusalError, Tier
from app.services.schema.cards import WorkspaceSchema
from app.services.schema.linking import link_schema
from app.services.sqlguard import SqlGuardError
from app.services.text2sql.cache import AnswerCache
from app.services.text2sql.explain import explain
from app.services.text2sql.models import (
    Attempt,
    GenerationOutput,
    HistoryTurn,
    PipelineConfig,
    PipelineResult,
    StageTrace,
)
from app.services.text2sql.prompting import build_system_prompt, build_user_message

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], None]

EMPTY_RESULT_NOTE = (
    "The previous SQL ran but returned no rows (or only NULLs). If the filters, casing of text "
    "values or date logic are wrong, fix them. If an empty result is genuinely correct, return "
    "the same SQL unchanged."
)


def _suspicious(columns: list[str], rows: list[list[Any]]) -> bool:
    if not rows:
        return True
    return len(rows) == 1 and all(v is None for v in rows[0])


class Text2SQLPipeline:
    def __init__(
        self,
        provider: LLMProvider,
        settings: Settings | None = None,
        cache: AnswerCache | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or get_settings()
        self.cache = cache

    # ------------------------------------------------------------------ helpers

    def _generate(
        self,
        result: PipelineResult,
        *,
        task: str,
        system: str,
        user: str,
    ) -> GenerationOutput:
        start = time.perf_counter()
        llm = self.provider.complete_json(
            task=task,
            output_model=GenerationOutput,
            system=system,
            messages=[{"role": "user", "content": user}],
            tier=Tier.STRONG,
        )
        u = llm.usage
        result.tokens_in += u.tokens_in + u.cache_read_tokens + u.cache_write_tokens
        result.tokens_out += u.tokens_out
        result.cost_usd += u.cost_usd
        result.model = u.model
        result.trace.append(
            StageTrace(
                task,
                int((time.perf_counter() - start) * 1000),
                u.tokens_in,
                u.tokens_out,
                u.cost_usd,
                {"cache_read": u.cache_read_tokens} if u.cache_read_tokens else {},
            )
        )
        out = llm.output
        out.confidence = min(1.0, max(0.0, float(out.confidence or 0.0)))
        return out

    @staticmethod
    def _cache_key(
        workspace_id: str,
        schema: WorkspaceSchema,
        question: str,
        history: list[HistoryTurn],
        config: PipelineConfig,
        prompt_tag: str,
    ) -> str:
        h = hashlib.sha256()
        for part in (
            workspace_id,
            schema.fingerprint(),
            " ".join(question.lower().split()),
            config.key(),
            prompt_tag,
            *(f"{t.question}|{t.sql}" for t in history),
        ):
            h.update(part.encode())
            h.update(b"\x1f")
        return h.hexdigest()

    # ------------------------------------------------------------------ main

    def run(
        self,
        *,
        workspace_id: str,
        question: str,
        schema: WorkspaceSchema,
        history: list[HistoryTurn] | None = None,
        config: PipelineConfig | None = None,
        on_event: EventCallback | None = None,
    ) -> PipelineResult:
        config = config or PipelineConfig()
        history = (history or [])[-self.settings.followup_history_turns :]
        emit = on_event or (lambda _e, _p: None)
        started = time.perf_counter()
        result = PipelineResult(question=question, status="ok", resolved_question=question)

        if not schema.tables:
            result.status, result.kind = "unanswerable", "unanswerable"
            result.missing_data = "This workspace has no tables yet. Upload a CSV or Excel file."
            return self._finish(result, started, emit)

        # 1. schema linking ------------------------------------------------
        t0 = time.perf_counter()
        link = link_schema(
            question,
            schema,
            threshold_columns=self.settings.schema_link_threshold,
            force=config.force_linking and config.use_linking,
        )
        tables = link.tables if config.use_linking else [t.name for t in schema.tables]
        # Small glossaries go in whole (term matching misses inflections like spend/spent).
        if not config.use_glossary:
            glossary = []
        elif len(schema.glossary) <= 20:
            glossary = schema.glossary
        else:
            glossary = link.glossary
        result.trace.append(
            StageTrace(
                "link",
                int((time.perf_counter() - t0) * 1000),
                detail={
                    "tables": tables,
                    "skipped": link.skipped,
                    "glossary": [g.term for g in glossary],
                },
            )
        )
        system, prompt_tag = build_system_prompt(
            schema,
            tables=tables if config.use_linking and not link.skipped else None,
            glossary=glossary,
            include_samples=config.use_samples,
            examples=config.few_shot,
        )
        result.prompt_version = prompt_tag

        cache_key = self._cache_key(workspace_id, schema, question, history, config, prompt_tag)
        if self.cache is not None and (hit := self.cache.get(cache_key)) is not None:
            hit.cached = True
            emit("status", {"stage": "cached"})
            return self._finish(hit, started, emit, from_cache=True)

        # 2. generate + validate + execute + correct ----------------------------
        emit("status", {"stage": "generating"})
        user = build_user_message(question, history)
        try:
            gen = self._generate(result, task="generate_sql", system=system, user=user)
        except LLMRefusalError:
            return self._fail(
                result, started, emit, "refusal", "The model declined to answer this question."
            )
        except LLMError as e:
            return self._fail(
                result,
                started,
                emit,
                "llm_unavailable",
                f"The language model is unavailable ({e}). You can still write SQL by hand.",
            )

        max_attempts = 1 + (config.max_corrections if config.self_correction else 0)
        empty_retry_used = False
        while True:
            self._apply_generation(result, gen)
            if gen.kind != "sql":
                result.status = "clarify" if gen.kind == "clarify" else "unanswerable"
                break

            attempt = Attempt(number=len(result.attempts) + 1, sql=gen.sql.strip())
            result.attempts.append(attempt)
            emit("sql", {"sql": attempt.sql, "attempt": attempt.number})
            t1 = time.perf_counter()
            try:
                exec_result = run_query(
                    workspace_id, attempt.sql, schema.allowed(), row_cap=config.row_cap
                )
            except (SqlGuardError, ExecutionError) as e:
                attempt.error, attempt.error_code = e.message, e.code
                result.trace.append(
                    StageTrace(
                        "execute",
                        int((time.perf_counter() - t1) * 1000),
                        detail={"attempt": attempt.number, "error_code": e.code},
                    )
                )
                retryable = e.code not in {"timeout", "memory", "no_data", "connect_error"}
                if retryable and len(result.attempts) < max_attempts:
                    emit("status", {"stage": "correcting", "attempt": attempt.number + 1})
                    try:
                        gen = self._generate(
                            result,
                            task="correct_sql",
                            system=system,
                            user=build_user_message(question, history, attempt),
                        )
                    except LLMError as le:
                        return self._fail(result, started, emit, "llm_unavailable", str(le))
                    continue
                result.status = "error"
                result.error, result.error_code = e.message, e.code
                break

            attempt.row_count = exec_result.row_count
            result.trace.append(
                StageTrace(
                    "execute",
                    int((time.perf_counter() - t1) * 1000),
                    detail={"attempt": attempt.number, "rows": exec_result.row_count},
                )
            )
            result.sql = exec_result.sql
            result.columns = exec_result.columns
            result.column_types = exec_result.column_types
            result.rows = exec_result.rows
            result.truncated = exec_result.truncated

            if (
                config.self_correction
                and not empty_retry_used
                and _suspicious(exec_result.columns, exec_result.rows)
                and len(result.attempts) < max_attempts
            ):
                empty_retry_used = True
                attempt.error, attempt.error_code = "empty result", "empty_result"
                emit("status", {"stage": "checking_empty_result"})
                try:
                    retry = self._generate(
                        result,
                        task="correct_sql",
                        system=system,
                        user=build_user_message(question, history, attempt, note=EMPTY_RESULT_NOTE),
                    )
                except LLMError:
                    break  # keep the (empty) result we already have
                if retry.kind == "sql" and " ".join(retry.sql.split()) != " ".join(
                    attempt.sql.split()
                ):
                    gen = retry
                    continue
                attempt.error = attempt.error_code = None
            break

        emit(
            "rows",
            {
                "columns": result.columns,
                "row_count": result.row_count,
                "truncated": result.truncated,
            },
        )
        self._post_process(result, config, emit)
        if self.cache is not None and result.status in ("ok", "clarify", "unanswerable"):
            self.cache.set(cache_key, result)
        return self._finish(result, started, emit)

    # ------------------------------------------------------------------ steps

    @staticmethod
    def _apply_generation(result: PipelineResult, gen: GenerationOutput) -> None:
        result.kind = gen.kind
        result.resolved_question = gen.standalone_question.strip() or result.question
        result.reasoning = gen.reasoning
        result.assumptions = [a for a in gen.assumptions if a.strip()][:8]
        result.confidence = gen.confidence
        result.tables_used = gen.tables_used
        result.clarifying_question = gen.clarifying_question.strip() or None
        result.missing_data = gen.missing_data.strip() or None
        if gen.kind == "clarify" and not result.clarifying_question:
            result.clarifying_question = "Could you clarify what you mean?"

    def _post_process(
        self, result: PipelineResult, config: PipelineConfig, emit: EventCallback
    ) -> None:
        """Warnings, chart selection and the plain-language explanation."""
        if result.status != "ok":
            return
        try:
            result.chart = chart_dict(
                result.columns, result.column_types, result.rows, result.resolved_question
            )
        except ValueError:
            logger.warning("chart_spec_invalid")
            result.chart = {"type": "table", "x": None, "y": [], "series": None, "title": ""}
        emit("chart", {"chart": result.chart})
        if config.explain:
            t0 = time.perf_counter()
            text, usage = explain(self.provider, result)
            result.explanation = text
            stage = StageTrace("explain", int((time.perf_counter() - t0) * 1000))
            if usage is not None:
                stage.tokens_in, stage.tokens_out, stage.cost_usd = (
                    usage.tokens_in,
                    usage.tokens_out,
                    usage.cost_usd,
                )
                result.tokens_in += usage.tokens_in
                result.tokens_out += usage.tokens_out
                result.cost_usd += usage.cost_usd
            result.trace.append(stage)
            emit("explanation", {"text": text})
        if result.truncated:
            result.warnings.append(
                f"Showing the first {result.row_count:,} rows; the full result is larger."
            )
        if not result.rows:
            result.warnings.append("The query returned no rows.")
        if len(result.attempts) > 1:
            result.warnings.append(
                "The SQL was corrected automatically after "
                f"{len(result.attempts) - 1} failed attempt(s)."
            )
        if result.confidence is not None and result.confidence < 0.5:
            result.warnings.append("Low confidence: check the assumptions and SQL.")

    def _fail(
        self, result: PipelineResult, started: float, emit: EventCallback, code: str, message: str
    ) -> PipelineResult:
        result.status = "error"
        result.error_code, result.error = code, message
        return self._finish(result, started, emit)

    @staticmethod
    def _finish(
        result: PipelineResult, started: float, emit: EventCallback, *, from_cache: bool = False
    ) -> PipelineResult:
        if not from_cache:
            result.duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "pipeline_done",
            extra={
                "status": result.status,
                "kind": result.kind,
                "attempts": len(result.attempts),
                "duration_ms": result.duration_ms,
                "cost_usd": round(result.cost_usd, 6),
                "cached": from_cache,
            },
        )
        emit("done", {"status": result.status})
        return result
