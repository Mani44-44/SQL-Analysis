"""Benchmark dataset loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.config import REPO_DIR

EVAL_DATA_DIR = REPO_DIR / "eval_data"


class EvalCase(BaseModel):
    id: str
    question: str
    gold_sql: str | None = None
    expected_kind: Literal["sql", "clarify", "unanswerable"] = "sql"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    tags: list[str] = Field(default_factory=list)
    smoke: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> EvalCase:
        if (self.gold_sql is None) != (self.expected_kind != "sql"):
            raise ValueError(f"{self.id}: gold_sql must be set iff expected_kind == 'sql'")
        return self


def dataset_path(name: str) -> Path:
    path = EVAL_DATA_DIR / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"unknown dataset {name!r} ({path})")
    return path


def load_dataset(name: str, *, smoke: bool = False) -> list[EvalCase]:
    cases = [
        EvalCase.model_validate(json.loads(line))
        for line in dataset_path(name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate case ids in {name}")
    return [c for c in cases if c.smoke] if smoke else cases


def load_fewshot_pool(name: str = "fewshot_pool") -> list[tuple[str, str]]:
    path = EVAL_DATA_DIR / f"{name}.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [(r["question"], r["sql"]) for r in rows]
