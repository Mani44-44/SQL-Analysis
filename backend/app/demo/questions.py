"""Suggested questions for the demo workspace, with reference SQL.

Used by the UI (suggestion chips) and by the mock LLM so the app is usable end-to-end without an
API key. These are NOT benchmark cases (see eval_data/ and the leakage test).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DemoQuestion:
    question: str
    sql: str
    assumptions: tuple[str, ...] = field(default_factory=tuple)


SPEND_FILTER = (
    "t.type = 'Debit' AND t.status = 'Success' "
    "AND coalesce(c.category_group, '') NOT IN ('Transfers', 'Savings')"
)
SPEND_JOINS = (
    "FROM transactions t LEFT JOIN merchants m ON t.merchant_id = m.merchant_id "
    "LEFT JOIN categories c ON m.category_id = c.category_id"
)

DEMO_QUESTIONS: list[DemoQuestion] = [
    DemoQuestion(
        "How much did I spend each month?",
        f"SELECT date_trunc('month', t.txn_date) AS month, round(sum(t.amount), 2) AS spend "
        f"{SPEND_JOINS} WHERE {SPEND_FILTER} GROUP BY 1 ORDER BY 1",
        ("Spend = successful debits, excluding transfers and investments.",),
    ),
    DemoQuestion(
        "What are my top 5 merchants by spend?",
        f"SELECT m.merchant_name, round(sum(t.amount), 2) AS spend {SPEND_JOINS} "
        f"WHERE {SPEND_FILTER} AND m.merchant_name IS NOT NULL "
        f"GROUP BY 1 ORDER BY spend DESC LIMIT 5",
        ("Spend = successful debits, excluding transfers and investments.",),
    ),
    DemoQuestion(
        "How is my spending split across categories?",
        f"SELECT coalesce(c.category_name, 'Cash / Uncategorised') AS category, "
        f"round(sum(t.amount), 2) AS spend {SPEND_JOINS} WHERE {SPEND_FILTER} "
        f"GROUP BY 1 ORDER BY spend DESC",
        ("ATM withdrawals have no merchant and are shown as 'Cash / Uncategorised'.",),
    ),
    DemoQuestion(
        "Which categories went over budget in May 2026?",
        "WITH spend AS (SELECT m.category_id, sum(t.amount) AS spent FROM transactions t "
        "JOIN merchants m ON t.merchant_id = m.merchant_id WHERE t.type = 'Debit' "
        "AND t.status = 'Success' AND date_trunc('month', t.txn_date) = DATE '2026-05-01' "
        "GROUP BY 1) SELECT c.category_name, b.budget, round(s.spent, 2) AS spent, "
        "round(s.spent - b.budget, 2) AS over_by FROM budgets b "
        "JOIN categories c ON b.category_id = c.category_id "
        "JOIN spend s ON s.category_id = b.category_id WHERE b.month = DATE '2026-05-01' "
        "AND s.spent > b.budget ORDER BY over_by DESC",
    ),
    DemoQuestion(
        "How many transactions failed, by payment mode?",
        "SELECT payment_mode, count(*) AS failed_transactions FROM transactions "
        "WHERE status = 'Failed' GROUP BY 1 ORDER BY 2 DESC",
    ),
    DemoQuestion(
        "What was my monthly income vs spend in 2025?",
        "SELECT date_trunc('month', t.txn_date) AS month, "
        "round(sum(t.amount) FILTER (WHERE t.type = 'Credit' AND c.category_name = 'Salary'), 2) AS income, "
        f"round(sum(t.amount) FILTER (WHERE {SPEND_FILTER}), 2) AS spend "
        f"{SPEND_JOINS} WHERE t.status = 'Success' AND year(t.txn_date) = 2025 GROUP BY 1 ORDER BY 1",
        ("Income = successful salary credits.",),
    ),
]


def normalise(question: str) -> str:
    return " ".join("".join(ch for ch in question.lower() if ch.isalnum() or ch == " ").split())
