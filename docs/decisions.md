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
