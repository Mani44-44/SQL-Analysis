# Project Spec: Natural-Language SQL & Data-Analysis Assistant ("AskData")

> Revision 2 (2026-10-20). Changes from revision 1 are summarized in the [changelog](#18-changelog-from-revision-1) at the end, and each non-obvious change is justified in `docs/decisions.md`. The phase-by-phase build order is in `docs/PLAN.md`.

---

## 0. Working rules

- Build incrementally, in the phases in `docs/PLAN.md`. A phase is finished only when its code, tests and docs are done and `ruff`, `mypy`, `pytest` (and `npm run build` once the frontend exists) are green. A phase that is red is not committed.
- Don't pause for approval on design choices. Make the call, and record any choice that is non-obvious or departs from this spec in `docs/decisions.md` (context, decision, trade-off).
- Prefer simple, readable, well-tested code over clever code.
- Every module gets unit tests. Anything that touches SQL execution also gets security tests.
- Never hard-code secrets. Read them from environment variables and keep `.env.example` current.
- **Every test, and CI, must pass with no LLM API key.** The mock LLM provider is the default. Real model calls happen only when a key is configured.
- Use conventional commit messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`). Commit at least once per phase and tag each phase (`phase-N`).

---

## 1. Product summary

AskData is a web app. A user uploads CSV/XLSX files (or, later, connects a read-only Postgres database), asks questions in plain English, and gets back:

- the generated SQL, which is shown and can be edited,
- the result table,
- a chart chosen automatically,
- a short plain-language explanation that states its assumptions.

Every query is validated for safety before it runs. Failed queries are retried with the error fed back. The system measures its own accuracy against a benchmark that lives in the repository.

**Project goal:** a deployed, measurable, production-style flagship project for an AI/ML + software-engineering portfolio.

**Differentiators** (each must be visible in the README):
1. A published, reproducible execution-accuracy benchmark, with an ablation table.
2. Safe-by-design execution: allowlist validation, a read-only sandbox, resource limits, and a 100%-pass safety suite.
3. A polished demo workspace in one narrow niche: personal finance (Section 2).

---

## 2. Niche: personal finance, UPI and bank statements (decided)

**Decision:** the demo workspace analyses personal-finance data. That means bank-account statements and UPI transactions in an Indian context: INR, UPI handles, merchants, categories and monthly budgets.

**Why this niche:** the data is relatable and naturally messy, and it exercises every interesting SQL pattern: date logic, aggregation, joins and ranking. See `docs/decisions.md` (D-002).

**Binding constraint:** the benchmark has to run offline and reproducibly in CI, and it has to be license-clean. Real personal statements are private, and public ones don't exist. The demo data is therefore **synthetic, produced by a seeded deterministic generator** (`scripts/generate_demo_data.py`). The generator deliberately injects real-world mess:
- mixed date formats (`2025-03-04`, `04/03/2025`, `4-Mar-25`),
- amounts written as `₹1,234.50`, `Rs. 1234.5`, or with a trailing `Dr`/`Cr`,
- inconsistent merchant spellings (`SWIGGY`, `Swiggy Ltd`, `swiggy*order`),
- blank rows, a repeated header row, trailing whitespace and mixed-case headers.

**Demo tables** (after ingestion and cleaning): `accounts`, `transactions`, `merchants`, `categories`, `budgets`.

The app itself stays general-purpose and accepts any CSV, XLSX or SQLite file.

---

## 3. Target users and core user stories

- As a visitor, I open the demo workspace with one click, no signup, and ask questions straight away.
- As a user, I sign up or log in and create a workspace.
- As a user, I upload CSV/XLSX files, or a SQLite file, into a workspace.
- As a user, I see a schema summary generated for me: tables, columns, types, null %, sample values and row counts.
- As a user, I ask a question in natural language and get back SQL, results, a chart and an explanation with its assumptions.
- As a user, I edit the generated SQL and re-run it. The edited SQL goes through the same validation.
- As a user, I ask follow-up questions that rely on conversation context ("now break that down by month").
- As a user, I get a clarifying question when my question is ambiguous, and a clear "can't answer, this data is missing" when it can't be answered.
- As a user, I see my question history, save useful queries, and export results as CSV and charts as PNG.
- As a user, I give an answer thumbs up or down and can attach a corrected SQL query.
- As a developer, I see accuracy, cost, latency and failure categories on a metrics page, and I can compare two benchmark runs.

---

## 4. Functional requirements

### 4.1 Data ingestion
- Accept CSV, XLSX and SQLite uploads. The size limit is configurable (default 50 MB), and so is the row limit (default 1,000,000).
- Clean the data robustly:
  - normalise headers to snake_case, de-duplicated and SQL-safe,
  - drop blank and repeated-header rows,
  - strip whitespace,
  - parse currency (₹, Rs., commas, Dr/Cr sign suffixes),
  - parse percentages and booleans,
  - parse dates and datetimes in multiple formats; a column is inferred as a date only when at least 95% of its non-null values parse.
- Type inference with a manual override: the user can PATCH a column type, which re-loads that table.
- Storage: **one DuckDB file per workspace** (`data/workspaces/<id>.duckdb`). This is the isolation boundary.
- Profile every table on ingest:
  - row count, plus per column: type, null %, distinct count, min/max,
  - top-5 values (low-cardinality columns only),
  - 3 sample values.
- Ingestion runs as a background task. The source moves through `pending → processing → ready | failed`, and on failure an error message is stored.
- Stretch: an external read-only Postgres connection, with credentials encrypted at rest using Fernet (key from env).

### 4.2 Schema understanding
- Build a **schema card** for every table and column: name, type, profile stats, sample values, and a description that the LLM drafts and the user can edit.
- **Schema linking:** when the schema is large (more than `SCHEMA_LINK_THRESHOLD` columns, default 40), send the model only the relevant tables and columns. Relevance is scored with BM25 over table/column names, descriptions and sample values, plus a glossary-term boost. Embeddings are an optional later upgrade behind the same interface.
- **Business glossary** per workspace (e.g. "spend = SUM(amount) WHERE direction='debit'"). Glossary terms that match the question are injected into the prompt.
- Join hints come from columns whose names match across tables and whose values overlap (inferred foreign keys).

### 4.3 Text-to-SQL pipeline
Each stage is a function with typed inputs and outputs and is traced (Section 4.8).

1. **Context resolution:** fold the recent conversation turns (last N=4) into a self-contained question when the new question refers back ("that", "same period").
2. **Schema linking:** pick the relevant schema subset with sample values, plus matching glossary terms.
3. **Generation** with structured output: `{kind: sql|clarify|unanswerable, sql, reasoning, assumptions[], tables_used[], confidence (0–1), clarifying_question, missing_data}`.
   - The model classifies the question (aggregation, filter, join, trend, comparison) inside the same call instead of in a separate call, which saves a round trip.
4. **Validation** with `sqlguard` (Section 4.4).
5. **Execution** in the sandbox, with a timeout and a row cap.
6. **Self-correction:** on a validation error, an execution error, or a suspicious result (empty, or all-NULL aggregates), retry with the error and the previous SQL fed back. At most `MAX_CORRECTION_ATTEMPTS` retries (default 2). Every attempt is recorded.
7. **Explanation and chart:** a rule-based chart picker runs first. A short LLM explanation (cheap model) summarises the result, using only aggregated or truncated rows.
8. **Response:** everything goes back to the UI with warnings and assumptions. It is streamed over SSE as stage events (`sql` → `rows` → `chart` → `explanation` → `done`).

- **Ambiguity:** return `kind=clarify` with one specific question. Don't guess.
- **Unanswerable:** return `kind=unanswerable` and say which data is missing.
- **Model routing:** generation uses the strong model (`LLM_MODEL_STRONG`, default `claude-opus-5-5`). Explanations and column descriptions use the fast model (`LLM_MODEL_FAST`, default `claude-haiku-5-5`). Both are configurable.

### 4.4 SQL safety and validation (critical, highest-priority code)
Execution runs on **DuckDB**, so the threat model is DuckDB-specific. The rules are **allowlist-based**: anything not explicitly allowed is rejected.

**Static validation** (`sqlglot`, `dialect="duckdb"`):
- The SQL must parse into **exactly one** statement, and its root must be `SELECT`, a `UNION`/`INTERSECT`/`EXCEPT` of selects, or a `WITH … SELECT`. Anything else is rejected: DML, DDL, `ATTACH`, `DETACH`, `INSTALL`, `LOAD`, `COPY`, `EXPORT`, `IMPORT`, `PRAGMA`, `SET`, `RESET`, `CALL`, `USE`, `CHECKPOINT`, `VACUUM`, transactions, and multiple statements.
- **Table allowlist:** every table reference must be a workspace table or a CTE defined in the same query. Anything else is rejected: schema-qualified references to other catalogs, `information_schema.*`, `pg_catalog.*`, `duckdb_*()`, `sqlite_master`, and **table functions** (`read_csv*`, `read_parquet`, `read_json*`, `read_text`, `read_blob`, `glob`, `range`, `generate_series` used as a table, `query`, `query_table`, and others).
- **Function allowlist:** only approved scalar, aggregate and window functions are allowed: math, string, date/time, conditional, cast, and statistical aggregates. Unknown or anonymous functions are rejected, as are `getenv`, `current_setting` and anything file- or system-related.
- **Column check:** column references are resolved against the workspace schema where possible. Unknown columns produce a friendly validation error, which the self-correction loop can use.
- **Cost guards:** reject a `CROSS JOIN` (or a comma-join without a join predicate) between tables whose estimated product exceeds `MAX_CROSS_PRODUCT_ROWS`. Reject recursive CTEs.
- **Row cap:** wrap the query as `SELECT * FROM (<query>) LIMIT <row_cap + 1>` so truncation can be detected without changing the query's meaning.

**Runtime sandbox:**
- The connection opens the workspace DuckDB file with `read_only=True` and these settings:
  - `enable_external_access=false`,
  - `autoload_known_extensions=false`, `autoinstall_known_extensions=false`,
  - `memory_limit` (default 512MB), `threads` (default 2),
  - and last, `lock_configuration=true` so the query can't undo any of them.
- Timeout: DuckDB has no statement timeout, so a watchdog timer calls `connection.interrupt()` after `QUERY_TIMEOUT_S` (default 10 s).
- Workspace isolation: a connection can only ever open its own workspace's file, and paths are derived from server-side IDs, never from user input.

**Prompt-injection hygiene:**
- Cell values and column names are untrusted. They go into prompts only inside clearly delimited data blocks, with an instruction that data is never instructions.
- The LLM's SQL is always validated, whatever the model says about its own safety.

**Audit:** every executed query is logged with user, workspace, SQL hash, duration, rows returned and status.

### 4.5 Visualization
- **Rule-based chart picker** works from the result's shape and types:
  - 1 row × 1 numeric → KPI card,
  - temporal x + numeric → line,
  - categorical (≤ 20 distinct) + numeric → bar; a pie only when there are ≤ 6 categories and the values are non-negative parts of a whole,
  - two numerics → scatter,
  - anything else → table only.
- The chart spec is JSON (`{type, x, y[], series?, title}`) and is validated with Pydantic before it reaches the frontend. Columns referenced in the spec must exist in the result.
- The frontend renders it with Recharts. Charts export as PNG.

### 4.6 Explanation and trust features
- A plain-language answer that cites concrete numbers from the result.
- "Show your work": the SQL, its assumptions, the tables used, and the number of attempts.
- Confidence badge plus warnings: empty result, truncated at N rows, self-corrected after K attempts, low confidence.
- Feedback: 👍/👎, optionally with corrected SQL and a comment. Corrected SQL is validated before it is stored. Feedback is stored as a candidate source of few-shot examples, but never from the benchmark (Section 16).

### 4.7 Auth, tenancy and limits
- Email/password auth (argon2 hashes) with a JWT in an httpOnly cookie. OAuth is a stretch goal.
- Workspaces with members; roles are `owner` and `member`.
- A public **demo workspace** that is read-only and needs no login. It is rate-limited per IP.
- Per-user rate limit (default 30 asks/min) and a daily LLM cost cap (default $1/user/day), both enforced in process. Redis is an optional backend behind the same interface.

### 4.8 Observability
- Structured JSON logs that carry a request ID (`X-Request-ID`) on every line.
- Per-stage tracing (context, linking, generation, validation, execution, correction, explanation), with latency, tokens and cost, stored on `query_runs.trace` as JSON. An OpenTelemetry exporter is optional.
- `/api/v1/metrics`: queries per day, success rate, p50/p95 latency, cost per query, correction-loop rate, thumbs-down rate, and the failure-category breakdown.
- Error monitoring: Sentry, enabled only when `SENTRY_DSN` is set.

---

## 5. Non-functional requirements

- **Correctness:** execution accuracy measured on the benchmark (Section 9).
- **Security:** Section 4.4, plus dependency audit (`pip-audit`, `npm audit`) and secret scanning (gitleaks) in CI. No secrets in the repo or its history.
- **Performance:** typical questions on the demo data should come back in under ~5 s end to end at p50 and under ~12 s at p95. Schema cards and identical (workspace, question, schema-hash) answers are cached.
- **Cost:** tracked per query. Routing between the strong and fast models (Section 4.3). Prompt caching on the static system prompt and schema block.
- **Reliability:** LLM calls retry with exponential backoff (the SDK's built-in retries plus one pipeline-level retry). When the LLM is unavailable, the user gets a clear message and can still run SQL by hand.
- **Privacy:** users can delete uploaded data, and deleting the workspace deletes its DuckDB file. The retention policy is stated in the README.
- **Accessibility:** keyboard-navigable, labelled controls, colour-blind-safe chart palette, responsive down to 375 px.

---

## 6. Architecture

```
[Next.js (App Router, TS) UI]
        |  REST + SSE (/api/v1)
[FastAPI backend]
   ├─ auth & workspaces
   ├─ ingestion (parse → clean → profile → load DuckDB)   ← BackgroundTasks
   ├─ schema (cards, glossary, linking)
   ├─ text2sql pipeline ──► llm (provider interface: anthropic | mock)
   │        └─► sqlguard ──► executor (sandboxed DuckDB, read-only)
   ├─ charts / explanations
   ├─ eval (benchmark runner, metrics, compare)
   └─ observability (logging, tracing, metrics, rate/cost limits)
        |
[App DB: SQLite (local) / Postgres (deploy) via SQLAlchemy + Alembic]
[Per-workspace data: DuckDB files]      [Uploads: local disk / object storage]
```

**Design notes**
- LLM access goes through a `LLMProvider` protocol, with `AnthropicProvider` and a deterministic `MockProvider`. The mock answers known benchmark-style questions from a fixture map, so pipeline tests are meaningful without a key.
- Prompts live in `backend/app/prompts/*.md` with a version header. `prompt_version` is stored on every run and every eval run.
- The app DB is kept dialect-agnostic: no SQLite-only or Postgres-only types, and JSON columns use SQLAlchemy `JSON`.
- No Redis in the default setup. Rate limiting, caching and jobs run in process, behind interfaces that allow Redis/RQ later (D-004).

---

## 7. Tech stack

- **Frontend:** Next.js 15 (App Router, TypeScript), Tailwind CSS, Recharts, CodeMirror 6 (SQL editor), TanStack Table.
- **Backend:** Python 3.11, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2, Alembic, uv for dependency management.
- **Data engine:** DuckDB (per workspace), pandas and openpyxl (ingestion parsing).
- **SQL parsing:** `sqlglot`.
- **LLM:** official `anthropic` Python SDK behind the provider interface, with structured JSON outputs. Default models are `claude-opus-5-5` (strong) and `claude-haiku-5-5` (fast).
- **Testing:**
  - pytest and hypothesis (validator fuzzing),
  - httpx TestClient for API tests,
  - a few Playwright end-to-end tests (stretch).
- **Tooling:** ruff (lint and format), mypy (strict on `sqlguard` and `executor`), pre-commit.
- **DevOps:** Dockerfiles, docker-compose, GitHub Actions.
- **Deployment:** backend on Fly.io, Render or Railway with a persistent volume for DuckDB files; frontend on Vercel; managed Postgres for the app DB.

---

## 8. Data model (app DB)

- `users` (id, email, password_hash, created_at)
- `workspaces` (id, owner_id, name, is_demo, created_at)
- `workspace_members` (workspace_id, user_id, role)
- `data_sources` (id, workspace_id, type [csv|xlsx|sqlite|postgres], filename, status, error, encrypted_credentials, created_at)
- `tables_meta` (id, source_id, workspace_id, name, row_count, description)
- `columns_meta` (id, table_id, name, type, null_pct, distinct_count, min_value, max_value, top_values JSON, sample_values JSON, description)
- `glossary_terms` (id, workspace_id, term, definition)
- `conversations` (id, workspace_id, user_id, title, created_at)
- `messages` (id, conversation_id, role, content, query_run_id, created_at)
- `query_runs`:
  - identity and content: id, workspace_id, conversation_id, question, resolved_question, kind,
  - SQL: generated_sql, final_sql,
  - outcome: status, error, error_category, attempts, rows_returned, truncated,
  - cost and timing: duration_ms, tokens_in, tokens_out, cost_usd,
  - provenance: model, prompt_version,
  - output and trace: chart_spec JSON, explanation, assumptions JSON, confidence, trace JSON, created_at
- `feedback` (id, query_run_id, user_id, rating, corrected_sql, comment, created_at)
- `saved_queries` (id, workspace_id, title, sql, created_by, created_at)
- `eval_runs` (id, dataset, git_sha, model, prompt_version, config JSON, started_at, finished_at, summary JSON)
- `eval_results` (id, run_id, case_id, predicted_sql, exec_match, kind_match, error_type, attempts, latency_ms, cost_usd)

Eval datasets and cases live as versioned files in `eval_data/` rather than in DB tables, so they are reviewed in git (D-006).

---

## 9. Evaluation and benchmark (the main differentiator)

### 9.1 Benchmark sets
- **Custom set** (`eval_data/finance_v1.jsonl`): 80 or more question/gold-SQL pairs on the seeded demo data. Each case is tagged with a difficulty (`easy`, `medium`, `hard`) and categories (`single_table`, `join`, `aggregation`, `date_logic`, `subquery`, `window`, `ambiguous`, `unanswerable`).
  - Ambiguous and unanswerable cases carry an expected `kind`, not SQL.
  - Every gold query runs in CI against the generated data, so a broken gold query fails the build.
  - The README reports a hand-verification log, including an error-rate estimate for the gold set.
- **Smoke subset:** cases flagged `smoke: true` (~25), stratified across categories.
- **Public set (stretch):** a pluggable loader for a Spider/BIRD dev subset. It is downloaded by a script, never committed, and its license is noted.

### 9.2 Metrics (precise definitions)
- **Execution match:** the predicted and gold result sets are equal under these rules:
  - Columns are compared as an unordered multiset of column vectors, so column order and aliases are ignored.
  - Rows are compared as a multiset unless the gold SQL has a top-level `ORDER BY`, in which case order matters.
  - Floats match within a relative tolerance of 1e-4 and an absolute tolerance of 1e-6.
  - `NULL` equals `NULL`.
  - Dates and timestamps are compared as ISO strings.
  - Extra predicted columns are allowed only when the gold columns are a subset and the row count matches ("superset-column match", reported separately from strict match).
- **Kind accuracy:** for ambiguous and unanswerable cases, the predicted `kind` equals the expected `kind`.
- **Valid-SQL rate** (passes `sqlguard`) and **execution-error rate**.
- **Self-correction recovery rate:** cases that were wrong on attempt 1 and correct on the final attempt, divided by cases wrong on attempt 1.
- **Safety suite pass rate** (Section 9.4).
- Latency p50/p95 and cost per case.
- Breakdowns by difficulty, category and **error category**. Error categories are assigned by heuristic diffs between predicted and gold SQL: wrong table, wrong join, wrong aggregation, wrong filter, date handling, hallucinated column, execution error, and other.
- Confidence intervals: run N repeats (default 3) and report the mean ± 95% CI (bootstrap).

### 9.3 Ablations (results go in the README)
- Pipeline configs are switched by flags:
  - `schema_only`,
  - `+samples`,
  - `+linking`,
  - `+glossary`,
  - `+self_correction`,
  - `+few_shot` (few-shot examples come only from a separate `eval_data/fewshot_pool.jsonl` that has no overlap with the benchmark).
- Models: strong only, fast only, and routed. The result is an accuracy-vs-cost table.

### 9.4 Safety test suite
- `backend/tests/security/` covers each attack category with explicit cases:
  - destructive statements, multi-statement injection, comment and obfuscation tricks,
  - file and table functions, extension loading, settings changes,
  - system catalog access, cross-workspace access,
  - expensive cross joins, timeouts and memory blowups,
  - prompt injection through cell values and column names.
- Hypothesis fuzzing: generated statements must never pass validation unless they are a single allowlisted SELECT.
- **Target: 100% blocked.** The suite runs on every commit.

### 9.5 CI integration
- Every push runs:
  - lint and types,
  - unit and security tests,
  - a gold-SQL validity check,
  - the **mock-provider pipeline benchmark**, which checks wiring and metrics code deterministically.
- The real-model smoke benchmark runs on PRs only when the `ANTHROPIC_API_KEY` secret is present, and otherwise skips with a clear message.
  - It posts a before/after table as a PR comment.
  - The check fails if smoke accuracy drops more than `EVAL_REGRESSION_THRESHOLD` (default 5 points) below the baseline file `eval_data/baseline.json`.
- The full benchmark runs nightly (cron) and on manual dispatch, with the same key condition.

---

## 10. API surface (REST, under `/api/v1`)

- **Auth:** `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- **Workspaces:** `GET/POST /workspaces`, `GET/DELETE /workspaces/{id}`, `GET /workspaces/demo`
- **Sources:**
  - `POST /workspaces/{id}/sources/upload` (multipart)
  - `GET /workspaces/{id}/sources`
  - `GET /sources/{id}`
  - `DELETE /sources/{id}`
- **Schema:**
  - `GET /workspaces/{id}/schema`
  - `PATCH /columns/{id}` (description or type override)
  - `PATCH /tables/{id}`
  - `GET/POST /workspaces/{id}/glossary`
  - `DELETE /glossary/{id}`
- **Query:**
  - `POST /workspaces/{id}/ask` (JSON response, or SSE stream with `Accept: text/event-stream`)
  - `POST /workspaces/{id}/sql/run` (edited SQL, same validation)
- **History:**
  - `GET /workspaces/{id}/conversations`
  - `GET /conversations/{id}`
  - `GET/POST /workspaces/{id}/saved-queries`
  - `DELETE /saved-queries/{id}`
- **Feedback:** `POST /query-runs/{id}/feedback`
- **Export:** `GET /query-runs/{id}/export?format=csv`
- **Eval (admin):** `GET /eval/runs`, `GET /eval/runs/{id}`, `GET /eval/compare?a=&b=`. Runs are started from the CLI (`python -m app.eval.run`) because they are long-running.
- **Metrics:** `GET /metrics`
- **Health:** `GET /health` (liveness), `GET /health/ready` (DB reachable)

---

## 11. Frontend pages and components

- **Landing page** (`/`): pitch, the benchmark headline number, and a **Try the demo** button that needs no signup.
- **Auth pages** (`/login`, `/register`) and a workspace switcher.
- **Data page** (`/w/[id]/data`): upload with ingestion status polling, a schema explorer with editable descriptions and type overrides, and a glossary editor.
- **Ask page** (`/w/[id]/ask`):
  - question box with suggested questions,
  - streamed response stages,
  - SQL panel (CodeMirror, editable, **Run**),
  - results table (sortable, paginated),
  - chart and explanation,
  - assumptions and warnings,
  - feedback, and follow-up input.
- **History page** (`/w/[id]/history`): conversations and saved queries.
- **Metrics page** (`/metrics`): accuracy by run, failure categories, cost and latency, and a two-run comparison.
- Every view has empty, loading and error states.

---

## 12. Repository structure

```
/
  backend/
    app/
      api/            # routers (v1)
      core/           # config, logging, security, request-id, limits
      db/             # SQLAlchemy models, session, alembic/
      services/
        ingestion/    # parse, clean, infer types, profile, load
        schema/       # schema cards, linking, glossary
        sqlguard/     # parser-based validator (allowlist)
        execution/    # sandboxed DuckDB executor
        text2sql/     # pipeline stages + orchestrator
        charts/       # chart picker + spec model
        llm/          # provider protocol, anthropic, mock
      eval/           # runner, matching, metrics, compare, CLI
      prompts/        # versioned prompt files
    tests/            # unit/, security/, api/, eval/
    pyproject.toml
  frontend/           # Next.js app
  eval_data/          # finance_v1.jsonl, fewshot_pool.jsonl, baseline.json
  scripts/            # generate_demo_data.py, seed_demo.py
  docs/               # SPEC.md, PLAN.md, decisions.md, evaluation.md, architecture.md
  docker-compose.yml
  .github/workflows/  # ci.yml, eval.yml
  .env.example
  README.md
  LICENSE
```

---

## 13. DevOps and quality

- Local development works without Docker: `uv run` for the backend and `npm run dev` for the frontend, with SQLite as the app DB.
- Docker Compose (backend, frontend, Postgres) is provided for parity with deployment.
- GitHub Actions:
  - `ci.yml`: ruff, mypy, pytest (unit, security, api, eval wiring), gold-SQL check, frontend lint/typecheck/build, pip-audit, gitleaks.
  - `eval.yml`: the keyed smoke benchmark on PRs, plus nightly and manual full runs.
- Pre-commit hooks: ruff and the basic file checks.
- `scripts/seed_demo.py` generates the demo data, ingests it into the demo workspace, and loads the glossary.
- Deployment: health checks, Sentry (optional), and a persistent volume for DuckDB.

---

## 14. Milestones

`docs/PLAN.md` holds the detailed, phase-by-phase version. Summary:

| Phase | Scope |
|---|---|
| P0 | Spec revision, plan, repo bootstrap |
| P1 | Backend foundation: config, logging, app DB + migrations, LLM interface + mock + Anthropic, health, CI |
| P2 | Demo-data generator, ingestion (clean/infer/profile/load), schema cards, source and schema APIs |
| P3 | `sqlguard` + sandboxed executor + safety suite + fuzzing |
| P4 | Text-to-SQL pipeline: linking, generation, self-correction, clarify/unanswerable, follow-ups, glossary; ask/run APIs, SSE |
| P5 | Charts, explanations, export, history, saved queries, feedback |
| P6 | Evaluation: benchmark set, matcher, runner, metrics, ablations, compare, CI workflows |
| P7 | Frontend: landing/demo, data, ask, history, metrics |
| P8 | Auth, workspaces/membership, rate and cost limits, metrics endpoint, Sentry |
| P9 | Deploy readiness: Dockerfiles, compose, README with results, architecture and evaluation docs |
| P10 | Stretch: Postgres connections, few-shot from feedback, embeddings linking, OAuth, Playwright E2E |

---

## 15. Definition of done

**Agent-completable:**
- The CI workflows are green: lint, types, tests, safety suite, gold-SQL check and frontend build.
- The safety suite covers every attack category in Section 9.4 and passes 100%.
- The README has: a one-line pitch, an architecture diagram, a Docker and a non-Docker quickstart, a results table (filled in from a keyed run, or clearly marked as pending a keyed run), design decisions and trade-offs, limitations, security notes and the license.
- `docs/` contains the evaluation methodology, the decision log and the architecture doc.
- No secrets in the repo or its history.

**User-owned** (these need accounts, money or people):
- A public URL, with a demo workspace that answers questions without signup.
- Benchmark numbers produced with a real API key and committed to `eval_data/baseline.json` and the README.
- A regression gate demonstrated on a real GitHub PR.
- A demo GIF.
- At least 20 real users, with their feedback captured and a short note on what changed because of it.

---

## 16. Risks and mitigations

- **Scope creep:** P10 doesn't start until P9 is done.
- **LLM cost:** daily caps, response caching, prompt caching, and routing between the strong and fast models.
- **Flaky accuracy numbers:** a fixed dataset seed, N repeated runs, and reported confidence intervals. The regression threshold sits above the noise floor.
- **Messy real-world data:** invest early in ingestion and profiling. They drive accuracy more than prompt tweaks do.
- **Security gaps:** an allowlist validator plus a runtime sandbox, layered so each catches what the other misses. Fuzzing, and the safety suite in every CI run.
- **Benchmark leakage:** benchmark questions never appear in prompts or few-shot pools, and a test asserts there is no overlap.
- **Synthetic-data bias:** the demo data is synthetic, so accuracy on it may overstate accuracy on real data. The README says so, and the public-benchmark subset gives an external reference point.
- **DuckDB file concurrency:** the executor opens files read-only, so readers don't block each other. Ingestion writes through a separate connection under a per-workspace lock.

---

## 17. Changelog from revision 1

1. Section 0: replaced "ask before deviating / wait for confirmation" with "decide and log in `decisions.md`". Added the no-API-key-needed rule and phase tags.
2. Section 2: chose the niche (personal finance/UPI) and made demo data a **seeded synthetic generator** with deliberate mess, so the benchmark is reproducible and license-clean.
3. Section 4.4: rewrote safety for the real execution engine (DuckDB) as an **allowlist**. Added DuckDB runtime hardening and a watchdog timeout, and dropped the Postgres-only items (`pg_sleep`), which didn't apply.
4. Section 4.3: merged the separate classification call into structured generation, added explicit `kind` outputs, set the retry limits, and defined model routing.
5. Section 6/7: no Redis or pgvector in the default stack. SQLite (local) or Postgres (deploy) for the app DB, BM25 schema linking, and in-process limits behind swappable interfaces. This means it runs on a laptop with no Docker.
6. Section 8: eval datasets are versioned files rather than DB rows. Added trace, error_category and truncation fields to `query_runs`.
7. Section 9: precise **execution-match** definition, superset-column match, kind accuracy, bootstrap CIs, a leakage guard, and a mock-provider benchmark in every CI run, with the keyed benchmark gated on a secret.
8. Section 10: eval runs start from the CLI rather than over HTTP. Added readiness, metrics and demo endpoints.
9. Section 15: split the Definition of Done into agent-completable and user-owned items.
10. Section 16: added risks for synthetic-data bias and DuckDB concurrency.
