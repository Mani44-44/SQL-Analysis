"""Data models for the text-to-SQL pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["sql", "clarify", "unanswerable"]


class GenerationOutput(BaseModel):
    """Structured output requested from the model. Kept flat (no unions / numeric bounds) so the
    JSON schema is accepted by structured outputs; confidence is clamped in code."""

    kind: Kind = Field(description="sql, clarify or unanswerable")
    standalone_question: str = Field(description="The question rewritten to stand alone")
    sql: str = Field(description="One DuckDB SELECT query when kind is sql, else empty")
    reasoning: str = Field(description="One or two sentences on how the query answers it")
    assumptions: list[str] = Field(description="Interpretations made; empty if none")
    tables_used: list[str] = Field(description="Tables the query reads")
    confidence: float = Field(description="0 to 1")
    clarifying_question: str = Field(description="One question when kind is clarify, else empty")
    missing_data: str = Field(description="What data is missing when kind is unanswerable")


class Explanation(BaseModel):
    answer: str = Field(description="Two to four plain-language sentences")


@dataclass
class HistoryTurn:
    question: str
    sql: str | None = None
    kind: str = "sql"


@dataclass
class PipelineConfig:
    """Feature flags; the eval runner toggles these for ablations."""

    use_samples: bool = True
    use_linking: bool = True
    use_glossary: bool = True
    self_correction: bool = True
    explain: bool = True
    max_corrections: int = 2
    row_cap: int | None = None
    force_linking: bool = False  # link even when the schema is under the size threshold
    few_shot: list[tuple[str, str]] = field(default_factory=list)  # (question, sql) examples

    def key(self) -> str:
        return (
            f"s{int(self.use_samples)}l{int(self.use_linking)}g{int(self.use_glossary)}"
            f"c{int(self.self_correction)}e{int(self.explain)}m{self.max_corrections}"
            f"f{int(self.force_linking)}x{len(self.few_shot)}"
        )


@dataclass
class Attempt:
    number: int
    sql: str
    error: str | None = None
    error_code: str | None = None
    row_count: int | None = None


@dataclass
class StageTrace:
    stage: str
    ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "ms": self.ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            **({"detail": self.detail} if self.detail else {}),
        }


@dataclass
class PipelineResult:
    question: str
    status: Literal["ok", "clarify", "unanswerable", "error"]
    kind: Kind = "sql"
    resolved_question: str = ""
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    column_types: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    assumptions: list[str] = field(default_factory=list)
    reasoning: str = ""
    confidence: float | None = None
    tables_used: list[str] = field(default_factory=list)
    clarifying_question: str | None = None
    missing_data: str | None = None
    explanation: str | None = None
    chart: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    trace: list[StageTrace] = field(default_factory=list)
    model: str | None = None
    prompt_version: str | None = None
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cached: bool = False

    @property
    def generated_sql(self) -> str | None:
        return self.attempts[0].sql if self.attempts else None

    @property
    def row_count(self) -> int:
        return len(self.rows)
