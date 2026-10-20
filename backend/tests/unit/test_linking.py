from __future__ import annotations

from anthropic.lib._parse._transform import transform_schema
from sqlalchemy.orm import Session

from app.services.schema.cards import load_workspace_schema
from app.services.schema.linking import bm25_scores, link_schema, matching_glossary, tokenize
from app.services.text2sql.models import Explanation, GenerationOutput


def test_tokenize() -> None:
    assert tokenize("How much did I spend on Swiggy orders?") == [
        "spend", "swiggy", "orders", "order",
    ]  # fmt: skip


def test_bm25_prefers_matching_doc() -> None:
    scores = bm25_scores(["budget"], {"a": ["budget", "month"], "b": ["merchant", "name"]})
    assert scores["a"] > scores["b"] == 0


def test_link_skipped_for_small_schema(db: Session, demo_ws: str) -> None:
    schema = load_workspace_schema(db, demo_ws)
    r = link_schema("budget for groceries", schema, threshold_columns=100)
    assert r.skipped and set(r.tables) == schema.table_names


def test_link_selects_relevant_tables(db: Session, demo_ws: str) -> None:
    schema = load_workspace_schema(db, demo_ws)
    r = link_schema("monthly budget per category", schema, force=True, max_tables=2)
    assert "budgets" in r.tables[:2]
    assert "categories" in r.tables  # join neighbour of budgets
    r2 = link_schema("which bank account was opened first", schema, force=True, max_tables=1)
    assert r2.tables[0] == "accounts"


def test_glossary_matching(db: Session, demo_ws: str) -> None:
    schema = load_workspace_schema(db, demo_ws)
    terms = {
        g.term for g in matching_glossary("what is my savings rate and UPI spend", schema.glossary)
    }
    assert {"savings rate", "UPI", "spend"} <= terms


def test_structured_output_schemas_are_accepted_offline() -> None:
    """The SDK's transform must accept our output models without needing an API key."""
    for model in (GenerationOutput, Explanation):
        schema = transform_schema(model.model_json_schema())
        assert schema["type"] == "object"
        assert schema.get("additionalProperties") is False
        assert set(schema["required"]) == set(schema["properties"])
        text = str(schema)
        for forbidden in ("minimum", "maximum", "pattern", "anyOf", "oneOf"):
            assert forbidden not in text, (model.__name__, forbidden)
