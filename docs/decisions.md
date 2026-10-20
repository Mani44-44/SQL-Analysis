# Decision log

Each entry has three parts: context, decision, and trade-off. New entries go at the end.

## D-001: Autonomous build, with decisions logged instead of approved
- **Context:** Revision 1 of the spec said to "ask before deviating" and to "wait for confirmation" after each milestone. The project owner asked for an autonomous, phase-by-phase build.
- **Decision:** Make each design call when it comes up and record it here. Gate each phase on green checks, not on human approval.
- **Trade-off:** Some choices may need revisiting later. This log makes that cheap.

## D-002: Niche is personal finance, using synthetic UPI and bank-statement data
- **Context:** The benchmark must run offline in CI, be reproducible, and be license-clean. Real statements are private. Public datasets for other niches either need downloads or have unclear licenses.
- **Decision:** Use a seeded generator (`scripts/generate_demo_data.py`) that injects realistic mess: mixed date formats, ₹ and Rs. amounts with Dr/Cr suffixes, merchant aliases, blank and repeated-header rows. The gold SQL runs against the generated data, so it is validated in CI.
- **Trade-off:** Synthetic data may be easier than real data. The README states this, and a public-benchmark subset (stretch) gives an external reference.

## D-003: DuckDB for per-workspace data
- **Context:** Uploaded tables need fast analytics and strong per-workspace isolation.
- **Decision:** Each workspace gets one DuckDB file. Queries run on a read-only connection with external access disabled, extension autoload disabled, and memory and thread limits set, and then the configuration is locked.
- **Trade-off:** DuckDB has no statement timeout, so a watchdog thread calls `interrupt()`. The DuckDB SQL dialect also differs slightly from Postgres, and the prompts state the dialect explicitly.

## D-004: No Redis or pgvector in the default stack
- **Context:** The build machine has no Docker, Redis, or Postgres. A portfolio app should also be cheap to host.
- **Decision:** The app DB is SQLite locally and Postgres in deployment, through dialect-agnostic SQLAlchemy. Jobs run on FastAPI BackgroundTasks. Rate limits and the cache live in process, behind interfaces. Schema linking uses BM25.
- **Trade-off:** In-process limits don't coordinate across multiple instances. That's fine for a single deployed instance, and a Redis backend can be added behind the same interface.

## D-005: Allowlist-based SQL validation
- **Context:** Blocklists miss new functions, such as DuckDB's many `read_*` table functions, `glob`, and extensions.
- **Decision:** Use the sqlglot AST to allow exactly one SELECT, UNION, or WITH-SELECT; tables from the workspace or from CTEs; and functions from an explicit allowlist. Everything else is rejected. The runtime sandbox is a second, independent layer.
- **Trade-off:** Some legitimate functions get rejected until they're added to the allowlist. That's a safe failure mode, and the self-correction loop sees the error.

## D-006: Eval datasets live in versioned files, not DB tables
- **Context:** Gold SQL should be code-reviewed, diffable, and runnable in CI without a database.
- **Decision:** Store cases in `eval_data/*.jsonl`. Eval runs and results go into the DB and a JSON report.
- **Trade-off:** Cases can't be edited in the UI. That's acceptable for a benchmark.

## D-007: Mock LLM provider by default; Anthropic Claude for real runs
- **Context:** Tests and CI must work without an API key, and accuracy numbers must come from a real model.
- **Decision:** An `LLMProvider` protocol with a deterministic `MockProvider`, driven by fixtures, and an `AnthropicProvider` that uses the official SDK with structured JSON output. The strong tier is `claude-opus-5-5` and the fast tier is `claude-haiku-5-5`. Both can be changed in config.
- **Trade-off:** Mock-provider "accuracy" only checks the wiring. It is never reported as model accuracy.

## D-008: Classification folded into generation
- **Context:** Revision 1 had a separate "understand/classify" LLM call before generation.
- **Decision:** One structured generation call returns `kind` (sql, clarify, or unanswerable), the SQL, assumptions, and a confidence score.
- **Trade-off:** There's less modularity, but each question saves one round trip, roughly 30–40% of latency on simple questions.

## D-009: Demo dataset size (~1.1k transactions over 18 months)
- **Context:** Revision 2 of the plan estimated about 5k transactions. A realistic simulation of one person's finances, with salary, rent, around 60 discretionary transactions a month, refunds, and failed or pending payments, comes to roughly 1,100 rows over Jan 2025 to Jun 2026.
- **Decision:** Keep the realistic volume. Benchmark difficulty comes from date logic, joins, status filtering, and messy formats, not from the row count.
- **Trade-off:** This doesn't stress performance. The row-cap, timeout, and memory-limit paths are covered separately by safety tests that use synthetic large tables.

## D-010: Type inference rules
- **Context:** Messy uploads mix formats. Being wrong in either direction hurts: if amounts end up as text, aggregation breaks, and if IDs end up as numbers, leading zeros are lost.
- **Decision:** Numeric and boolean types require every non-null value to parse. Values with leading zeros stay text. Dates need at least 95% of values to parse, and the remainder becomes NULL and is counted. For slash dates, day-first is the default unless the column proves month-first (some second component is greater than 12 and no first component is). Currency is detected from ₹, Rs., INR, $, or a Dr/Cr suffix, and Dr makes the value negative. Percentages are stored as the number shown, so 12.5% is stored as 12.5.
- **Trade-off:** One stray value turns a numeric column into text. The user can override the type, which reloads the table with the unparseable values set to NULL.

## D-011: Per-workspace readers-writer lock around DuckDB files
- **Context:** DuckDB won't open the same file twice in one process with different configurations, and the read-only sandbox and the ingestion writer use different configurations.
- **Decision:** Each workspace gets an in-process, writer-preferring RW lock. Ingestion takes the write side and the executor takes the read side.
- **Trade-off:** This only works in a single process. Running multiple workers would need a file lock or a separate ingestion service. That's documented as a deployment constraint: one backend instance per volume.

## D-012: Execute the SQL regenerated from the validated AST
- **Context:** If the validator's parser (sqlglot) and DuckDB's parser disagree about a string, through comment nesting, quoting, or dialect quirks, an attacker could hide something that sqlglot reads as harmless and DuckDB reads as an attack.
- **Decision:** After validation, generate the SQL from the checked sqlglot AST with comments stripped, and execute that string. The original string never reaches DuckDB.
- **Trade-off:** sqlglot normalises some functions when it regenerates SQL. For example, `ifnull` becomes `COALESCE` and `range(3)` becomes `RANGE(0, 3)`. The benchmark's gold SQL runs through the same round trip, so any semantic drift shows up there.

## D-013: Order of the validation checks
- **Decision:** Checks run in this order: parse into a single statement, size limits, root type, forbidden nodes anywhere in the tree, tables (table functions, qualifiers, CTE scope, allowlist), functions, columns, cross joins. Checking tables before functions gives table functions such as `read_csv(...)` a clear `table_function` error. Column checks come late because they exist for the self-correction loop's error messages and are not a security boundary.
- **Runtime finding:** With `enable_external_access=false`, DuckDB still lets a connection read its own open database file by path. That exposes only the workspace's own data. Reading another workspace's file through `FROM 'path'`, `read_csv`, `read_text`, or `ATTACH` is blocked, and `tests/security/test_sandbox.py` asserts this.
- **Hardening after review:**
  - CTE resolution now follows SQL scoping. A CTE body can see only the CTEs defined *before* it, never itself or later siblings. Otherwise `WITH pg_tables AS (SELECT * FROM pg_tables) …` would resolve to the catalog view.
  - `tests/security/test_roundtrip.py` checks D-012 directly. About 160 allowlisted expressions are run both raw and regenerated, and their values and types must match.
  - `tests/unit/test_concurrency.py` interleaves sandboxed reads with re-ingestion on the same file.
  - `pytz` was added because fetching TIMESTAMPTZ values failed without it.

## D-014: Follow-up resolution folded into generation; calls are single-turn
- **Context:** Revision 2 had a separate context-resolution stage that rewrote follow-ups into standalone questions. That would cost an extra LLM call on every follow-up.
- **Decision:**
  - The last N turns go into a delimited `<history>` block in the user message, as question plus final SQL. The generation output includes `standalone_question`, which is stored as `resolved_question` and reused as history.
  - Each call is a single user turn. Earlier assistant turns are never replayed, so there are no thinking-block or history-editing constraints.
  - The system prompt holds the static instructions, the schema and the glossary, so it stays cacheable per workspace.
- **Trade-off:** The generation prompt does slightly more work. In return, each question costs one model call instead of two.

## D-015: Self-correction policy
- **Decision:**
  - Validation and execution errors are retried with the error fed back, up to `max_corrections` times (default 2).
  - Timeout, memory and no-data errors are not retried, because another attempt won't fix them.
  - An empty or all-NULL result gets one "check your filters" retry. If the model returns the same SQL, the empty result stands.
  - Every attempt's SQL and error is kept for evaluation, including first-attempt accuracy and recovery rate.
- **Trade-off:** In the worst case a question takes four model calls. Cost caps (P8) bound the spend.

## D-016: sqlglot models boolean operators as functions
- **Finding:** In sqlglot 30, `exp.And`, `exp.Or` and `exp.Xor` subclass `exp.Func`. The function allowlist was rejecting every query that used `AND`.
- **Decision:** Add the operator classes to the allowlist. Allowed-query tests now cover `AND`, `OR` and `NOT` in WHERE, FILTER, JOIN ON and CASE, plus every demo question.

## D-017: How the benchmark is scored
- **Decision:**
  - Execution match ignores column order and names, but the row-level pairing must still hold.
  - Rows are compared as a multiset unless the gold SQL has a top-level ORDER BY.
  - Numbers are rounded money-style. Temporal values are canonicalised, so a midnight timestamp matches its date and a `YYYY-MM` label matches the first of the month.
  - Strict and superset (extra predicted columns) matches are reported separately.
  - The headline accuracy counts SQL cases by strict execution match and clarify/unanswerable cases by kind match.
- **Trade-off:** Matching a `YYYY-MM` label to the first of the month accepts both `strftime` and `date_trunc` answers to "per month" questions. That is lenient but defensible. Rounding at two decimals could in theory hide a difference of less than one paisa.

## D-018: Eval uses the demo workspace; the oracle provider checks the harness
- **Decision:**
  - The runner seeds the demo workspace if it's missing (`--reseed` forces a rebuild), then persists `eval_runs` and `eval_results` to the app DB so the metrics page can show history.
  - A deterministic oracle provider fails on purpose in fixed patterns, so the expected metrics are exact and CI can check the whole harness without a key.
- **Trade-off:** Re-seeding resets the demo's conversation history. CI always starts from an empty DB.

## D-019: Frontend design direction
- **Context:** The demo niche is Indian personal finance. The UI should feel like it belongs to that subject rather than look like a generic analytics template.
- **Decision:**
  - **Look:** a passbook or ledger theme, with ledger-green "paper", navy "ink", ruled table rows as the only decorative device, a teal accent, and stamp red used only for errors. Dark mode inverts ink and paper.
  - **Type:** Bricolage Grotesque for display text and questions, Instrument Sans for the UI, and JetBrains Mono only for SQL.
  - **Formatting:** amounts use Indian digit grouping (₹5,04,000) and compact lakh ticks on chart axes.
  - **Accessibility:** a visible focus ring, reduced-motion support, `aria-sort` on sortable tables, and alt descriptions on charts.
- **Finding:** Tailwind v4's scanner skips paths containing `[`, which is how Next.js names dynamic routes. Page implementations therefore live in `src/views/`, and the bracketed route files only re-export them.
