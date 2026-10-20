"""Schema linking: pick the tables relevant to a question when the schema is large.

Each table is a BM25 "document" built from its name, description, column names, column
descriptions and low-cardinality values. Glossary terms that appear in the question add their
definitions to the query, so "spend" pulls in the tables its definition mentions. Tables joined
to a selected table through a join key are added so the generated SQL can join.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.services.schema.cards import GlossaryCard, TableCard, WorkspaceSchema

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "of", "in", "on", "for", "to", "by", "and", "or", "is", "are", "was",
    "what", "which", "how", "many", "much", "me", "my", "i", "show", "list", "give", "per",
    "with", "from", "each", "all", "did", "do", "does", "that", "this", "it", "at", "as",
}  # fmt: skip


def tokenize(text: str) -> list[str]:
    tokens = []
    for t in _TOKEN.findall(text.lower()):
        if t in _STOP:
            continue
        tokens.append(t)
        if len(t) > 3 and t.endswith("s"):
            tokens.append(t[:-1])  # naive singular
    return tokens


def _table_doc(t: TableCard) -> list[str]:
    parts = [t.name, t.name.replace("_", " "), t.description or ""]
    for c in t.columns:
        parts += [c.name.replace("_", " "), c.description or "", c.original_name or ""]
        parts += [str(v["value"]) for v in c.top_values]
    return tokenize(" ".join(parts))


@dataclass
class LinkResult:
    tables: list[str]
    scores: dict[str, float]
    glossary: list[GlossaryCard]
    skipped: bool = False


def matching_glossary(question: str, glossary: list[GlossaryCard]) -> list[GlossaryCard]:
    q = set(tokenize(question))
    out = []
    for g in glossary:
        term_tokens = set(tokenize(g.term))
        if term_tokens and term_tokens <= q:
            out.append(g)
    return out


def bm25_scores(
    query: list[str], docs: dict[str, list[str]], k1: float = 1.5, b: float = 0.75
) -> dict[str, float]:
    n = len(docs)
    if n == 0:
        return {}
    avgdl = sum(len(d) for d in docs.values()) / n or 1.0
    df: Counter[str] = Counter()
    for d in docs.values():
        df.update(set(d))
    scores: dict[str, float] = {}
    for name, d in docs.items():
        tf = Counter(d)
        s = 0.0
        for term in set(query):
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            s += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * len(d) / avgdl))
        scores[name] = s
    return scores


def link_schema(
    question: str,
    schema: WorkspaceSchema,
    *,
    threshold_columns: int = 40,
    max_tables: int = 6,
    force: bool = False,
) -> LinkResult:
    glossary = matching_glossary(question, schema.glossary)
    all_tables = [t.name for t in schema.tables]
    if not force and schema.column_count <= threshold_columns:
        return LinkResult(all_tables, {}, glossary, skipped=True)

    query = tokenize(question)
    for g in glossary:
        query += tokenize(g.definition)
    docs = {t.name: _table_doc(t) for t in schema.tables}
    scores = bm25_scores(query, docs)
    ranked = [name for name, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s > 0]
    selected = ranked[:max_tables] or all_tables[:max_tables]

    # Add direct join neighbours so the generator can join selected tables to their dimensions.
    for h in schema.join_hints:
        if len(selected) >= max_tables + 2:
            break
        if h.left_table in selected and h.right_table not in selected:
            selected.append(h.right_table)
    return LinkResult(selected, scores, glossary)
