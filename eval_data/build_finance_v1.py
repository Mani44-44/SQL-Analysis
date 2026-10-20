"""Source of truth for the finance_v1 benchmark; writes finance_v1.jsonl next to this file.

Conventions
- Questions are phrased so a careful analyst using the workspace glossary has one reading,
  except the cases tagged `ambiguous` (expected kind "clarify") and `unanswerable`.
- Gold SQL is minimal: it returns only the columns the question asks for, so a prediction with
  extra columns can still earn a superset match.
- "Spend" follows the glossary: successful debits, excluding Transfers/Savings category groups,
  with merchant-less ATM withdrawals included.
- No question here may appear in prompts, few-shot pools or demo suggestions (leakage test).

Run:  python eval_data/build_finance_v1.py
"""

from __future__ import annotations

import json
from pathlib import Path

J = (
    "FROM transactions t LEFT JOIN merchants m ON t.merchant_id = m.merchant_id "
    "LEFT JOIN categories c ON m.category_id = c.category_id"
)
JI = (
    "FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
    "JOIN categories c ON m.category_id = c.category_id"
)
S = (
    "t.type = 'Debit' AND t.status = 'Success' "
    "AND coalesce(c.category_group, '') NOT IN ('Transfers', 'Savings')"
)
OK_DEBIT = "t.type = 'Debit' AND t.status = 'Success'"

# (id, question, gold_sql | None, expected_kind, difficulty, tags, smoke)
CASES: list[tuple[str, str, str | None, str, str, list[str], bool]] = [
    # ------------------------------------------------------------------ single table, easy
    ("fin-001", "How many transactions are there in total?",
     "SELECT count(*) FROM transactions", "sql", "easy", ["single_table", "aggregation"], True),
    ("fin-002", "How many accounts do I have?",
     "SELECT count(*) FROM accounts", "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-003", "How many of my accounts are currently active?",
     "SELECT count(*) FROM accounts WHERE active", "sql", "easy", ["single_table", "filter"], True),
    ("fin-004", "List the names of all my accounts together with their bank.",
     "SELECT account_name, bank FROM accounts", "sql", "easy", ["single_table"], False),
    ("fin-005", "Which merchants are based in Bengaluru?",
     "SELECT merchant_name FROM merchants WHERE city = 'Bengaluru'", "sql", "easy", ["single_table", "filter"], True),
    ("fin-006", "How many transactions failed?",
     "SELECT count(*) FROM transactions WHERE status = 'Failed'", "sql", "easy", ["single_table", "filter"], True),
    ("fin-007", "What is the largest single successful debit amount?",
     "SELECT max(amount) FROM transactions WHERE type = 'Debit' AND status = 'Success'", "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-008", "How many transactions were made via UPI, regardless of status?",
     "SELECT count(*) FROM transactions WHERE payment_mode = 'UPI'", "sql", "easy", ["single_table", "filter"], False),
    ("fin-009", "What is the total amount of all successful credit transactions?",
     "SELECT sum(amount) FROM transactions WHERE type = 'Credit' AND status = 'Success'", "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-010", "How many distinct merchants appear in my transactions?",
     "SELECT count(DISTINCT merchant_id) FROM transactions", "sql", "easy", ["single_table", "aggregation"], True),
    ("fin-011", "Which spending categories are marked as essential?",
     "SELECT category_name FROM categories WHERE is_essential", "sql", "easy", ["single_table", "filter"], False),
    ("fin-012", "What are the earliest and the latest transaction dates?",
     "SELECT min(txn_date), max(txn_date) FROM transactions", "sql", "easy", ["single_table", "date_logic"], True),
    ("fin-013", "How many transactions have a note attached?",
     "SELECT count(*) FROM transactions WHERE notes IS NOT NULL", "sql", "easy", ["single_table", "filter"], False),
    ("fin-014", "What is the credit limit on my credit card account?",
     "SELECT credit_limit FROM accounts WHERE account_type = 'Credit Card'", "sql", "easy", ["single_table", "filter"], False),
    ("fin-015", "What is the total opening balance across all my accounts?",
     "SELECT sum(opening_balance) FROM accounts", "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-016", "How many transactions are still pending?",
     "SELECT count(*) FROM transactions WHERE status = 'Pending'", "sql", "easy", ["single_table", "filter"], False),
    ("fin-017", "How many transactions mention swiggy (in any letter case) in their description?",
     "SELECT count(*) FROM transactions WHERE lower(description) LIKE '%swiggy%'", "sql", "easy", ["single_table", "filter"], True),
    ("fin-018", "Which account was opened first? Give its name.",
     "SELECT account_name FROM accounts ORDER BY opened_on LIMIT 1", "sql", "easy", ["single_table", "date_logic"], False),
    # ------------------------------------------------------------------ aggregation
    ("fin-020", "What is the total amount of failed transactions for each payment mode?",
     "SELECT payment_mode, sum(amount) FROM transactions WHERE status = 'Failed' GROUP BY payment_mode",
     "sql", "medium", ["single_table", "aggregation"], False),
    ("fin-021", "How many transactions does each account_id have?",
     "SELECT account_id, count(*) FROM transactions GROUP BY account_id", "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-022", "What is the average successful debit amount for each payment mode?",
     "SELECT payment_mode, avg(amount) FROM transactions WHERE type = 'Debit' AND status = 'Success' GROUP BY payment_mode",
     "sql", "medium", ["single_table", "aggregation"], True),
    ("fin-023", "How many successful debits and how many successful credits are there?",
     "SELECT type, count(*) FROM transactions WHERE status = 'Success' GROUP BY type",
     "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-024", "What is my total spend across all time?",
     f"SELECT sum(t.amount) {J} WHERE {S}", "sql", "medium", ["join", "aggregation", "glossary"], True),
    ("fin-025", "What is my total spend for each account_id?",
     f"SELECT t.account_id, sum(t.amount) {J} WHERE {S} GROUP BY t.account_id",
     "sql", "medium", ["join", "aggregation", "glossary"], False),
    ("fin-026", "How many transactions were made with each payment mode?",
     "SELECT payment_mode, count(*) FROM transactions GROUP BY payment_mode", "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-027", "What is the median amount of a successful debit?",
     "SELECT median(amount) FROM transactions WHERE type = 'Debit' AND status = 'Success'",
     "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-028", "Which payment mode has the most failed transactions?",
     "SELECT payment_mode FROM transactions WHERE status = 'Failed' GROUP BY payment_mode ORDER BY count(*) DESC LIMIT 1",
     "sql", "medium", ["single_table", "aggregation"], True),
    ("fin-029", "How many budget rows exist for each category_id?",
     "SELECT category_id, count(*) FROM budgets GROUP BY category_id", "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-030", "What is the sum of all budgets across every category and month?",
     "SELECT sum(budget) FROM budgets", "sql", "easy", ["single_table", "aggregation"], False),
    ("fin-031", "What is the average amount I paid per ride on Uber or Ola (successful rides only)?",
     "SELECT avg(t.amount) FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
     "WHERE m.merchant_name IN ('Uber', 'Ola') AND t.type = 'Debit' AND t.status = 'Success'",
     "sql", "medium", ["join", "aggregation"], False),
    # ------------------------------------------------------------------ date logic
    ("fin-040", "What was my total spend in 2025?",
     f"SELECT sum(t.amount) {J} WHERE {S} AND year(t.txn_date) = 2025",
     "sql", "medium", ["join", "date_logic", "glossary"], True),
    ("fin-041", "What was my total spend in January 2026?",
     f"SELECT sum(t.amount) {J} WHERE {S} AND t.txn_date BETWEEN DATE '2026-01-01' AND DATE '2026-01-31'",
     "sql", "medium", ["join", "date_logic", "glossary"], False),
    ("fin-042", "Give me my spend for every calendar month in the data, in date order.",
     f"SELECT date_trunc('month', t.txn_date) AS month, sum(t.amount) {J} WHERE {S} GROUP BY 1 ORDER BY 1",
     "sql", "medium", ["join", "date_logic", "glossary"], True),
    ("fin-043", "How much did I spend in each quarter of 2025? Label quarters by number 1 to 4.",
     f"SELECT quarter(t.txn_date) AS q, sum(t.amount) {J} WHERE {S} AND year(t.txn_date) = 2025 GROUP BY 1",
     "sql", "medium", ["join", "date_logic", "glossary"], False),
    ("fin-044", "Which calendar month had my highest spend?",
     f"SELECT date_trunc('month', t.txn_date) AS month {J} WHERE {S} GROUP BY 1 ORDER BY sum(t.amount) DESC LIMIT 1",
     "sql", "medium", ["join", "date_logic", "glossary"], False),
    ("fin-045", "How many transactions happened on a Saturday or Sunday?",
     "SELECT count(*) FROM transactions WHERE dayofweek(txn_date) IN (0, 6)",
     "sql", "medium", ["single_table", "date_logic"], True),
    ("fin-046", "What was my total spend for each day of the week, labelled by day name (Monday, Tuesday, ...)?",
     f"SELECT dayname(t.txn_date) AS day_name, sum(t.amount) {J} WHERE {S} GROUP BY 1",
     "sql", "medium", ["join", "date_logic", "glossary"], False),
    ("fin-047", "How much did I spend in the first half of 2026 (January to June)?",
     f"SELECT sum(t.amount) {J} WHERE {S} AND t.txn_date >= DATE '2026-01-01' AND t.txn_date < DATE '2026-07-01'",
     "sql", "medium", ["join", "date_logic", "glossary"], False),
    ("fin-048", "What was my total salary income in 2025?",
     f"SELECT sum(t.amount) {JI} WHERE c.category_name = 'Salary' AND t.type = 'Credit' AND t.status = 'Success' AND year(t.txn_date) = 2025",
     "sql", "medium", ["join", "date_logic"], True),
    ("fin-049", "Show each month's spend and the difference from the previous month's spend, in date order.",
     f"WITH ms AS (SELECT date_trunc('month', t.txn_date) AS month, sum(t.amount) AS spend {J} WHERE {S} GROUP BY 1) "
     "SELECT month, spend, spend - lag(spend) OVER (ORDER BY month) AS diff FROM ms ORDER BY month",
     "sql", "hard", ["join", "date_logic", "window", "glossary"], False),
    ("fin-050", "In which month of 2025 did I spend the most on Food & Dining?",
     f"SELECT date_trunc('month', t.txn_date) AS month {JI} WHERE {OK_DEBIT} AND c.category_name = 'Food & Dining' "
     "AND year(t.txn_date) = 2025 GROUP BY 1 ORDER BY sum(t.amount) DESC LIMIT 1",
     "sql", "medium", ["join", "date_logic"], False),
    ("fin-051", "How many transactions (of any status) did I make in December 2025?",
     "SELECT count(*) FROM transactions WHERE txn_date >= DATE '2025-12-01' AND txn_date < DATE '2026-01-01'",
     "sql", "easy", ["single_table", "date_logic"], False),
    ("fin-052", "What was my average monthly spend in 2025?",
     f"SELECT avg(s) FROM (SELECT date_trunc('month', t.txn_date) AS m, sum(t.amount) AS s {J} WHERE {S} "
     "AND year(t.txn_date) = 2025 GROUP BY 1)",
     "sql", "hard", ["join", "date_logic", "subquery", "glossary"], True),
    ("fin-053", "How much did I spend on Travel in May 2025 and in May 2026? Give one row per year.",
     f"SELECT year(t.txn_date) AS yr, sum(t.amount) {JI} WHERE {OK_DEBIT} AND c.category_name = 'Travel' "
     "AND month(t.txn_date) = 5 GROUP BY 1",
     "sql", "medium", ["join", "date_logic"], False),
    ("fin-054", "On how many different days did at least one transaction fail?",
     "SELECT count(DISTINCT txn_date) FROM transactions WHERE status = 'Failed'",
     "sql", "easy", ["single_table", "date_logic"], False),
    ("fin-055", "What is the average number of transactions per calendar month (counting every status)?",
     "SELECT avg(n) FROM (SELECT date_trunc('month', txn_date) AS m, count(*) AS n FROM transactions GROUP BY 1)",
     "sql", "medium", ["single_table", "date_logic", "subquery"], False),
    ("fin-056", "How did my salary change over time? List each distinct monthly salary amount and the first month it was paid.",
     f"SELECT t.amount, min(date_trunc('month', t.txn_date)) {JI} WHERE c.category_name = 'Salary' AND t.status = 'Success' GROUP BY t.amount",
     "sql", "hard", ["join", "date_logic"], False),
    # ------------------------------------------------------------------ joins
    ("fin-060", "Which 5 merchants did I spend the most money at, from highest to lowest?",
     f"SELECT m.merchant_name, sum(t.amount) AS spend {J} WHERE {S} AND m.merchant_name IS NOT NULL "
     "GROUP BY 1 ORDER BY spend DESC LIMIT 5",
     "sql", "medium", ["join", "aggregation", "glossary"], True),
    ("fin-061", "What is my total spend per category, ignoring transactions that have no merchant?",
     f"SELECT c.category_name, sum(t.amount) {JI} WHERE {S} GROUP BY 1",
     "sql", "medium", ["join", "aggregation", "glossary"], True),
    ("fin-062", "How much did I spend on food delivery from Swiggy and Zomato combined?",
     f"SELECT sum(t.amount) {J} WHERE {S} AND m.merchant_name IN ('Swiggy', 'Zomato')",
     "sql", "medium", ["join", "filter"], False),
    ("fin-063", "Into which account is my salary credited? Give the account name.",
     "SELECT DISTINCT a.account_name FROM transactions t JOIN accounts a ON t.account_id = a.account_id "
     "JOIN merchants m ON t.merchant_id = m.merchant_id JOIN categories c ON m.category_id = c.category_id "
     "WHERE c.category_name = 'Salary' AND t.type = 'Credit'",
     "sql", "medium", ["join"], True),
    ("fin-064", "How much have I spent using my credit card account?",
     f"SELECT sum(t.amount) {J} JOIN accounts a ON t.account_id = a.account_id WHERE {S} AND a.account_type = 'Credit Card'",
     "sql", "medium", ["join", "glossary"], False),
    ("fin-065", "What is my total spend in each category group, counting only transactions that have a merchant?",
     f"SELECT c.category_group, sum(t.amount) {JI} WHERE {S} GROUP BY 1",
     "sql", "medium", ["join", "aggregation", "glossary"], False),
    ("fin-066", "How many transactions were recorded for each bank?",
     "SELECT a.bank, count(*) FROM transactions t JOIN accounts a ON t.account_id = a.account_id GROUP BY a.bank",
     "sql", "easy", ["join", "aggregation"], False),
    ("fin-067", "In which merchant city did I spend the most money?",
     f"SELECT m.city {JI} WHERE {S} GROUP BY m.city ORDER BY sum(t.amount) DESC LIMIT 1",
     "sql", "medium", ["join", "aggregation", "glossary"], False),
    ("fin-068", "For accounts that have at least one failed transaction, how many failed transactions does each have? Use account names.",
     "SELECT a.account_name, count(*) FROM transactions t JOIN accounts a ON t.account_id = a.account_id "
     "WHERE t.status = 'Failed' GROUP BY a.account_name",
     "sql", "medium", ["join", "aggregation"], False),
    ("fin-069", "How much did I spend on essential categories in 2025?",
     f"SELECT sum(t.amount) {JI} WHERE {S} AND c.is_essential AND year(t.txn_date) = 2025",
     "sql", "medium", ["join", "date_logic", "glossary"], False),
    ("fin-070", "How much have I invested in total (successful payments in the Investments category)?",
     f"SELECT sum(t.amount) {JI} WHERE {OK_DEBIT} AND c.category_name = 'Investments'",
     "sql", "medium", ["join", "aggregation"], True),
    ("fin-071", "How much cash have I withdrawn from ATMs in total (successful withdrawals only)?",
     "SELECT sum(amount) FROM transactions WHERE payment_mode = 'ATM' AND type = 'Debit' AND status = 'Success'",
     "sql", "easy", ["single_table", "filter"], False),
    ("fin-072", "What is the total amount I paid towards my credit card bill from my bank accounts?",
     "SELECT sum(t.amount) FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
     "WHERE m.merchant_name = 'ICICI Credit Card Bill' AND t.type = 'Debit' AND t.status = 'Success'",
     "sql", "medium", ["join", "filter"], False),
    ("fin-073", "Which categories had a budget above 10,000 for January 2026?",
     "SELECT c.category_name FROM budgets b JOIN categories c ON b.category_id = c.category_id "
     "WHERE b.month = DATE '2026-01-01' AND b.budget > 10000",
     "sql", "medium", ["join", "date_logic", "filter"], True),
    ("fin-074", "Which categories went over their budget in March 2026, and by how much?",
     "WITH s AS (SELECT m.category_id, sum(t.amount) AS spent FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
     "WHERE t.type = 'Debit' AND t.status = 'Success' AND t.txn_date >= DATE '2026-03-01' AND t.txn_date < DATE '2026-04-01' GROUP BY 1) "
     "SELECT c.category_name, s.spent - b.budget AS over_by FROM budgets b JOIN s ON s.category_id = b.category_id "
     "JOIN categories c ON c.category_id = b.category_id WHERE b.month = DATE '2026-03-01' AND s.spent > b.budget",
     "sql", "hard", ["join", "date_logic", "subquery"], True),
    ("fin-075", "For June 2026, what was the ratio of spend to budget for each budgeted category that had any spend? Give the ratio as a fraction, not a percentage.",
     "WITH s AS (SELECT m.category_id, sum(t.amount) AS spent FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
     "WHERE t.type = 'Debit' AND t.status = 'Success' AND t.txn_date >= DATE '2026-06-01' AND t.txn_date < DATE '2026-07-01' GROUP BY 1) "
     "SELECT c.category_name, s.spent / b.budget FROM budgets b JOIN s ON s.category_id = b.category_id "
     "JOIN categories c ON c.category_id = b.category_id WHERE b.month = DATE '2026-06-01'",
     "sql", "hard", ["join", "date_logic", "subquery", "glossary"], False),
    ("fin-076", "How much did I get back as refunds (successful credits) from Amazon?",
     "SELECT sum(t.amount) FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
     "WHERE m.merchant_name = 'Amazon' AND t.type = 'Credit' AND t.status = 'Success'",
     "sql", "medium", ["join", "filter"], False),
    ("fin-077", "Show the distinct amounts I have paid as rent.",
     "SELECT DISTINCT t.amount FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
     "JOIN categories c ON m.category_id = c.category_id WHERE c.category_name = 'Rent' AND t.type = 'Debit'",
     "sql", "easy", ["join", "filter"], False),
    ("fin-078", "What was the net flow (successful credits minus successful debits) for each account in 2025? Use account names.",
     "SELECT a.account_name, sum(CASE WHEN t.type = 'Credit' THEN t.amount ELSE -t.amount END) "
     "FROM transactions t JOIN accounts a ON t.account_id = a.account_id "
     "WHERE t.status = 'Success' AND year(t.txn_date) = 2025 GROUP BY a.account_name",
     "sql", "hard", ["join", "aggregation", "date_logic"], False),
    ("fin-079", "Which merchants had no successful transaction with me at all during 2026?",
     "SELECT merchant_name FROM merchants WHERE merchant_id NOT IN "
     "(SELECT merchant_id FROM transactions WHERE status = 'Success' AND merchant_id IS NOT NULL "
     "AND year(txn_date) = 2026)",
     "sql", "medium", ["subquery", "date_logic"], False),
    # ------------------------------------------------------------------ subqueries / windows (hard)
    ("fin-090", "For each category, which merchant received the most spend? Only consider transactions with a merchant.",
     f"SELECT category_name, merchant_name FROM (SELECT c.category_name, m.merchant_name, "
     f"row_number() OVER (PARTITION BY c.category_name ORDER BY sum(t.amount) DESC) AS rn {JI} WHERE {S} "
     "GROUP BY 1, 2) WHERE rn = 1",
     "sql", "hard", ["join", "window", "subquery", "glossary"], True),
    ("fin-091", "What is the running total of my spend by month during 2025, in date order?",
     f"WITH ms AS (SELECT date_trunc('month', t.txn_date) AS month, sum(t.amount) AS spend {J} WHERE {S} "
     "AND year(t.txn_date) = 2025 GROUP BY 1) SELECT month, sum(spend) OVER (ORDER BY month) AS running_total FROM ms ORDER BY month",
     "sql", "hard", ["join", "window", "date_logic", "glossary"], False),
    ("fin-092", "List the IDs of successful debit transactions that were more than 5 times the average successful debit amount.",
     "SELECT txn_id FROM transactions WHERE type = 'Debit' AND status = 'Success' AND amount > 5 * "
     "(SELECT avg(amount) FROM transactions WHERE type = 'Debit' AND status = 'Success')",
     "sql", "hard", ["single_table", "subquery"], False),
    ("fin-093", "Rank the payment modes by their total successful debit amount, highest first.",
     "SELECT payment_mode, sum(amount) AS total FROM transactions WHERE type = 'Debit' AND status = 'Success' "
     "GROUP BY 1 ORDER BY total DESC",
     "sql", "medium", ["single_table", "aggregation"], False),
    ("fin-094", "What percentage (0 to 100) of my total spend went to rent?",
     f"SELECT 100.0 * sum(t.amount) FILTER (WHERE c.category_name = 'Rent') / sum(t.amount) {J} WHERE {S}",
     "sql", "hard", ["join", "aggregation", "glossary"], True),
    ("fin-095", "What was my savings rate for 2025, as a fraction between 0 and 1?",
     f"WITH x AS (SELECT sum(t.amount) FILTER (WHERE t.type = 'Credit' AND t.status = 'Success' "
     f"AND (c.category_name = 'Salary' OR t.payment_mode = 'Interest')) AS income, "
     f"sum(t.amount) FILTER (WHERE {S}) AS spend {J} WHERE year(t.txn_date) = 2025) "
     "SELECT (income - spend) / income FROM x",
     "sql", "hard", ["join", "aggregation", "glossary"], True),
    ("fin-096", "Which month of 2025 had the largest increase in spend compared with the month before it?",
     f"WITH ms AS (SELECT date_trunc('month', t.txn_date) AS month, sum(t.amount) AS spend {J} WHERE {S} GROUP BY 1), "
     "d AS (SELECT month, spend - lag(spend) OVER (ORDER BY month) AS inc FROM ms) "
     "SELECT month FROM d WHERE year(month) = 2025 ORDER BY inc DESC NULLS LAST LIMIT 1",
     "sql", "hard", ["join", "window", "date_logic", "glossary"], False),
    ("fin-097", "How many merchants individually account for more than 10% of my total spend?",
     f"WITH ms AS (SELECT m.merchant_name, sum(t.amount) AS s {J} WHERE {S} GROUP BY 1) "
     "SELECT count(*) FROM ms WHERE merchant_name IS NOT NULL AND s > 0.1 * (SELECT sum(s) FROM ms)",
     "sql", "hard", ["join", "subquery", "glossary"], False),
    ("fin-098", "Which account had the highest total of successful debits in 2026? Give the account name.",
     "SELECT a.account_name FROM transactions t JOIN accounts a ON t.account_id = a.account_id "
     "WHERE t.type = 'Debit' AND t.status = 'Success' AND year(t.txn_date) = 2026 "
     "GROUP BY a.account_name ORDER BY sum(t.amount) DESC LIMIT 1",
     "sql", "medium", ["join", "aggregation", "date_logic"], False),
    ("fin-099", "What was the second-highest successful purchase (debit) amount at Amazon?",
     "SELECT t.amount FROM transactions t JOIN merchants m ON t.merchant_id = m.merchant_id "
     "WHERE m.merchant_name = 'Amazon' AND t.type = 'Debit' AND t.status = 'Success' "
     "ORDER BY t.amount DESC LIMIT 1 OFFSET 1",
     "sql", "medium", ["join", "subquery"], False),
    ("fin-100", "For each month of 2026, what fraction of my spend went to Food & Dining? Order by month.",
     f"SELECT date_trunc('month', t.txn_date) AS month, "
     f"sum(t.amount) FILTER (WHERE c.category_name = 'Food & Dining') / sum(t.amount) AS share {J} "
     f"WHERE {S} AND year(t.txn_date) = 2026 GROUP BY 1 ORDER BY 1",
     "sql", "hard", ["join", "date_logic", "aggregation", "glossary"], False),
    ("fin-101", "List the months in which my spend exceeded 90,000.",
     f"SELECT date_trunc('month', t.txn_date) AS month {J} WHERE {S} GROUP BY 1 HAVING sum(t.amount) > 90000",
     "sql", "medium", ["join", "date_logic", "glossary"], False),
    # ------------------------------------------------------------------ ambiguous -> clarify
    ("fin-200", "How much did I spend in March?", None, "clarify", "medium", ["ambiguous"], True),
    ("fin-201", "Compare my spending.", None, "clarify", "medium", ["ambiguous"], True),
    ("fin-202", "How much did I spend at the store?", None, "clarify", "medium", ["ambiguous"], False),
    ("fin-203", "Was it more than last time?", None, "clarify", "medium", ["ambiguous"], False),
    ("fin-204", "Show me the big ones.", None, "clarify", "medium", ["ambiguous"], False),
    ("fin-205", "What's my balance in the account?", None, "clarify", "medium", ["ambiguous"], False),
    # ------------------------------------------------------------------ unanswerable
    ("fin-300", "What is my credit score?", None, "unanswerable", "medium", ["unanswerable"], True),
    ("fin-301", "How much income tax was deducted from my salary in 2025?", None, "unanswerable", "medium", ["unanswerable"], True),
    ("fin-302", "What was Zomato's share price on the days I ordered from them?", None, "unanswerable", "medium", ["unanswerable"], False),
    ("fin-303", "Which friends did I split bills with?", None, "unanswerable", "medium", ["unanswerable"], False),
    ("fin-304", "What is the monthly EMI on my home loan?", None, "unanswerable", "medium", ["unanswerable"], False),
    ("fin-305", "Where exactly did my Uber rides start and end?", None, "unanswerable", "medium", ["unanswerable"], False),
]  # fmt: skip


def build() -> list[dict[str, object]]:
    seen: set[str] = set()
    out: list[dict[str, object]] = []
    for cid, question, sql, kind, difficulty, tags, smoke in CASES:
        assert cid not in seen, cid
        seen.add(cid)
        assert (sql is None) == (kind != "sql"), cid
        out.append(
            {
                "id": cid,
                "question": question,
                "gold_sql": sql,
                "expected_kind": kind,
                "difficulty": difficulty,
                "tags": tags,
                "smoke": smoke,
            }
        )
    return out


def render() -> str:
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in build())


if __name__ == "__main__":
    path = Path(__file__).with_name("finance_v1.jsonl")
    path.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {len(CASES)} cases to {path}")
