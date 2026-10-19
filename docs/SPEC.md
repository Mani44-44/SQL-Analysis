# Project Spec: Natural-Language SQL & Data-Analysis Assistant (working title: "AskData")

> How to use this file: paste it into your coding LLM as the project brief. Work milestone by milestone (Section 14). After each milestone, ask the LLM to review its own code against the "Definition of Done" (Section 15) before moving on.

---

## 0. Instructions for the coding LLM

- Build incrementally. Finish one milestone fully (code, tests, docs) before starting the next.
- Ask before making major architectural changes that deviate from this spec.
- Prefer simple, readable, well-tested code over clever code.
- Every module needs unit tests. Anything touching SQL execution needs security tests.
- Never hard-code secrets. Use environment variables and provide `.env.example`.
- Keep a `docs/decisions.md` file recording each non-obvious design decision and its trade-off.
- Commit in small steps with conventional commit messages (feat:, fix:, test:, docs:, chore:).

---

## 1. Product summary

A web app where a user connects a database or uploads CSV/Excel files, asks questions in plain English, and receives: the generated SQL (shown and editable), the result table, an automatically chosen chart, and a short plain-language explanation. The system validates every query for safety, retries on errors, and tracks its own accuracy against an evaluation benchmark.

**Primary goal of the project:** a deployed, measurable, production-style flagship project for an AI/ML + software engineering portfolio.

**Differentiators (must be visible in the README):**
1. A published accuracy benchmark with numbers (execution accuracy), reproducible in CI.
2. Safe-by-design execution (read-only, validated, sandboxed, limited).
3. A narrow, well-chosen niche demo dataset (see Section 2).

---

## 2. Niche decision (pick ONE before building)

Choose one demo domain with real, messy data. Recommended options:
- Personal finance / UPI & bank statement analysis (messy formats, very relatable)
- Campus or club data (events, budgets, attendance)
- Sports statistics (cricket, F1)
- Open government / public-health datasets

The app stays general-purpose (any CSV or DB), but ship one polished demo workspace in the chosen niche, with a custom question set for the benchmark.

---

## 3. Target users and core user stories

- As a user, I sign up/log in and create a workspace.
- As a user, I upload CSV/XLSX files or connect a read-only database (Postgres first; SQLite via upload).
- As a user, I see an auto-generated schema summary (tables, columns, types, sample values, row counts).
- As a user, I ask a question in natural language and get SQL + results + chart + explanation.
- As a user, I can edit the generated SQL and re-run it.
- As a user, I can ask follow-up questions that use conversation context ("now break that down by month").
- As a user, I can see a history of questions, save useful queries, and export results (CSV) and charts (PNG).
- As a user, I can give thumbs up/down and a correction on an answer.
- As an admin/developer, I can view accuracy metrics, cost, latency, and failure categories.

---

## 4. Functional requirements

### 4.1 Data ingestion
- CSV and XLSX upload (size limit, e.g. 50 MB; row limit configurable).
- Type inference with manual override; handle messy headers, mixed types, dates, currency symbols, empty rows.
- Store uploaded data as tables in an isolated per-workspace schema or per-workspace SQLite/DuckDB file.
- Optional: connect external Postgres with a read-only credential; credentials encrypted at rest.
- Data profiling on ingest: column types, null %, distinct counts, min/max, top values, sample rows.

### 4.2 Schema understanding
- Build a "schema card" per table/column: name, type, description (LLM-drafted, user-editable), sample values.
- Schema linking: when the schema is large, retrieve only relevant tables/columns for the question (embedding + keyword match).
- Store optional business glossary (e.g. "revenue = SUM(amount) where type='credit'") that is injected into prompts.

### 4.3 Text-to-SQL pipeline
1. Understand the question (classify: aggregation, filter, join, trend, comparison, unanswerable/ambiguous).
2. Schema linking (select relevant schema subset + sample values).
3. Generate SQL with a structured output (SQL + short reasoning + assumptions + confidence).
4. Validate SQL (see 4.4).
5. Execute in the sandbox with timeout and row limit.
6. On error or empty/suspicious result: self-correct loop (max 2-3 attempts) feeding the error back.
7. Generate explanation and pick a chart spec.
8. Return everything to the UI with the assumptions shown.
- Handle ambiguity: if the question is ambiguous, ask a clarifying question instead of guessing.
- Handle unanswerable questions: say so, and state which data is missing.
- Support follow-ups via conversation memory (resolve references like "that", "same period").

### 4.4 SQL safety and validation (critical)
- Parse SQL with a real parser (e.g. `sqlglot`) and allow only a single SELECT (and WITH/CTE) statement.
- Block: INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT, multiple statements, system tables, file functions, `COPY`, `pg_sleep`, etc.
- Allowlist tables/columns to the workspace schema only.
- Run with a read-only DB role; set statement timeout, row limit (auto-append LIMIT), and memory limits.
- Row-level or workspace isolation so users can never read other workspaces' data.
- Treat all user data and column values as untrusted (prompt-injection via cell contents): never let data text be interpreted as instructions.
- Log every executed query with user, workspace, duration, rows returned.

### 4.5 Visualization
- Rule-based + LLM-assisted chart selection (bar, line, pie, scatter, table-only) from result shape.
- Render in the frontend with a charting library (e.g. Recharts/Plotly/ECharts).
- Chart spec returned as JSON (type, x, y, series, title), validated before rendering.

### 4.6 Explanation and trust features
- Plain-language answer summarizing the result.
- "Show your work": SQL, assumptions, tables/columns used.
- Confidence indicator and warnings (e.g. "result is empty", "query returned truncated rows").
- Feedback: thumbs up/down + optional corrected SQL, stored for evaluation and few-shot improvement.

### 4.7 Auth, tenancy, and limits
- Email/password and/or OAuth (Google/GitHub); JWT or session cookies.
- Workspaces with isolation; per-user rate limits and daily LLM-cost caps.
- Basic roles: owner, member.

### 4.8 Observability
- Structured logging, request IDs.
- Tracing of each pipeline stage (schema linking, generation, validation, execution, correction) with latency and token cost (Langfuse or OpenTelemetry).
- Metrics dashboard: queries/day, success rate, average latency, cost per query, correction-loop rate, thumbs-down rate.

---

## 5. Non-functional requirements

- Correctness: measured execution accuracy on the benchmark; target numbers set in Section 9.
- Security: see 4.4; dependency scanning; secret scanning; no secrets in repo/history.
- Performance: p50 end-to-end under ~5 s, p95 under ~12 s for typical queries; cache schema cards and repeated queries.
- Cost: per-query cost tracked; cheaper model for simple steps, stronger model only when needed (routing).
- Reliability: retries with backoff on LLM calls; graceful degradation messages.
- Privacy: uploaded data deletable by the user; state retention policy in README.
- Accessibility and responsive UI.

---

## 6. Architecture

```
[Next.js/React UI]
       |
   HTTPS/REST (+ SSE for streaming)
       |
[FastAPI backend]
   |-- Auth & workspace service
   |-- Ingestion service (parse, profile, load)
   |-- Query service (the text-to-SQL pipeline)
   |-- Eval service (benchmark runner, metrics)
   |-- Worker queue (ingestion + long jobs)
       |
[Postgres (app data + pgvector)]   [Per-workspace data store: Postgres schemas or DuckDB/SQLite files]
[Redis (cache, rate limit, queue)]
[LLM provider(s)] [Object storage for uploads]
```

Design notes:
- LLM access behind a provider-agnostic interface so models can be swapped and mocked in tests.
- Prompts live in versioned files, not inline strings. Every prompt change is evaluated on the benchmark.
- Stream partial results (SQL first, then results, then explanation) to improve perceived speed.

---

## 7. Suggested tech stack

- Frontend: Next.js (TypeScript), Tailwind, a charting library, a SQL editor component (Monaco/CodeMirror).
- Backend: Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic migrations.
- Data/engine: Postgres + pgvector for app data; DuckDB or SQLite for per-workspace uploaded data (simplest isolation).
- SQL parsing: `sqlglot`.
- Queue/cache: Redis + RQ or Celery (or ARQ).
- LLM: provider-agnostic wrapper; structured outputs via JSON schema; tracing with Langfuse.
- Testing: pytest, pytest-asyncio, Playwright (a few end-to-end tests), hypothesis for SQL-validator fuzzing.
- Tooling: ruff, mypy, pre-commit.
- DevOps: Docker, docker-compose, GitHub Actions.
- Deployment: Fly.io / Render / Railway (backend), Vercel (frontend), managed Postgres.

---

## 8. Data model (core tables)

- `users` (id, email, password_hash/oauth_id, created_at)
- `workspaces` (id, owner_id, name, created_at)
- `workspace_members` (workspace_id, user_id, role)
- `data_sources` (id, workspace_id, type [upload|postgres], status, encrypted_credentials, created_at)
- `tables_meta` (id, source_id, name, row_count, description)
- `columns_meta` (id, table_id, name, type, null_pct, distinct_count, sample_values, description, embedding)
- `glossary_terms` (id, workspace_id, term, definition)
- `conversations` (id, workspace_id, user_id, created_at)
- `messages` (id, conversation_id, role, content, created_at)
- `query_runs` (id, message_id, generated_sql, final_sql, status, error, attempts, rows_returned, duration_ms, tokens_in, tokens_out, cost, model, prompt_version, chart_spec)
- `feedback` (id, query_run_id, rating, corrected_sql, comment)
- `saved_queries` (id, workspace_id, title, sql, created_by)
- `eval_datasets` (id, name, description), `eval_cases` (id, dataset_id, question, gold_sql, gold_result_hash, difficulty, tags)
- `eval_runs` (id, dataset_id, git_sha, model, prompt_version, started_at), `eval_results` (id, run_id, case_id, predicted_sql, exec_match, error_type, latency, cost)

---

## 9. Evaluation and benchmark (the main differentiator)

### 9.1 Benchmark sets
- Custom set: 80-150 question/SQL pairs on the niche dataset, with difficulty tags (easy single-table, joins, aggregations, date logic, subqueries, ambiguous, unanswerable).
- Public set: a subset (e.g. 100-200 cases) of a public text-to-SQL benchmark such as Spider or BIRD for an external reference number.
- Hand-verify gold SQL for the custom set; report the verified error rate of your own dataset.

### 9.2 Metrics
- Execution accuracy (result-set match, order-insensitive unless ORDER BY is required).
- Valid-SQL rate and execution-error rate.
- Self-correction recovery rate (how many initial failures get fixed by the retry loop).
- Ambiguity/unanswerable handling accuracy.
- Safety suite pass rate (see 9.4).
- Latency (p50/p95) and cost per query.
- Breakdown by difficulty tag and by error category (wrong table, wrong join, wrong aggregation, wrong filter, date handling, hallucinated column).

### 9.3 Ablations (include results in README)
- Baseline (schema only) vs. + sample values vs. + schema linking vs. + glossary vs. + self-correction vs. + few-shot examples from feedback.
- Cheap model vs. stronger model vs. routed combination: accuracy vs. cost curve.

### 9.4 Safety test suite
- Attempted destructive statements, multi-statement injection, system-table access, cross-workspace access, expensive cross joins, prompt injection through cell contents and column names. Target: 100% blocked, with tests for each.

### 9.5 CI integration
- A fast smoke benchmark (e.g. 20-30 cases) runs on every PR; the full benchmark runs nightly or on demand.
- PR comment with a before/after score table; the check fails if accuracy drops by more than a set threshold (use repeated runs or fixed seeds to handle noise).

---

## 10. API surface (REST, versioned under `/api/v1`)

- Auth: `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /me`
- Workspaces: `GET/POST /workspaces`, `GET/DELETE /workspaces/{id}`
- Data sources: `POST /workspaces/{id}/sources/upload`, `POST /workspaces/{id}/sources/connect`, `GET /workspaces/{id}/sources`, `DELETE /sources/{id}`
- Schema: `GET /sources/{id}/schema`, `PATCH /columns/{id}` (edit descriptions), `GET/POST /workspaces/{id}/glossary`
- Query: `POST /workspaces/{id}/ask` (question + conversation id; supports streaming), `POST /workspaces/{id}/sql/run` (edited SQL, same validation)
- History: `GET /workspaces/{id}/conversations`, `GET /conversations/{id}`, saved queries CRUD
- Feedback: `POST /query-runs/{id}/feedback`
- Export: `GET /query-runs/{id}/export?format=csv`
- Eval (admin): `POST /eval/runs`, `GET /eval/runs/{id}`, `GET /eval/compare?a=&b=`
- Health: `GET /health`

---

## 11. Frontend pages and components

- Landing page with a one-click demo workspace (no signup) using the niche dataset.
- Auth pages; workspace switcher.
- Data page: upload/connect, ingestion progress, schema explorer with editable descriptions.
- Chat/analysis page: question box with suggested questions, streamed response, SQL panel (editable, "Run again"), results table (sortable, paginated), chart, explanation, assumptions, feedback buttons, follow-up input.
- History and saved queries.
- Admin/metrics page: accuracy over time, failure categories, cost and latency charts, benchmark run comparison.
- Empty, loading, and error states for everything.

---

## 12. Repository structure

```
askdata/
  backend/
    app/
      api/            # routers
      core/           # config, security, logging
      db/             # models, migrations
      services/
        ingestion/
        schema/
        text2sql/     # pipeline stages
        sqlguard/     # parser + validation
        execution/
        charts/
        llm/          # provider-agnostic client
      eval/           # benchmark runner, metrics
      prompts/        # versioned prompt files
    tests/
  frontend/
  eval_data/          # benchmark datasets + gold SQL
  docs/               # architecture, decisions, evaluation methodology
  scripts/
  docker-compose.yml
  .github/workflows/  # ci.yml, eval.yml
  .env.example
  README.md
  LICENSE
```

---

## 13. DevOps and quality

- Docker Compose for local development (backend, frontend, Postgres, Redis).
- GitHub Actions: lint (ruff), type check (mypy), unit tests, safety tests, frontend build, smoke benchmark; nightly full benchmark; Docker image build.
- Pre-commit hooks; secret scanning and dependency audit enabled.
- Seed script to load the demo dataset and benchmark.
- Public deployment with a health check and error monitoring (e.g. Sentry).

---

## 14. Milestones

**M0 - Setup (2-3 days):** repo, Docker Compose, CI skeleton, config, logging, DB migrations, LLM client wrapper with a mock.
**M1 - Ingestion and schema (4-5 days):** CSV/XLSX upload, type inference, profiling, schema cards, schema explorer UI.
**M2 - Core text-to-SQL (5-6 days):** pipeline with structured outputs, SQL validator, sandboxed execution, results table, basic chat UI.
**M3 - Reliability (4-5 days):** self-correction loop, ambiguity and unanswerable handling, follow-up context, glossary, schema linking.
**M4 - Charts and explanations (3 days):** chart selection and rendering, explanation, export, history, saved queries.
**M5 - Evaluation (5-6 days):** benchmark datasets, runner, metrics, ablations, safety suite, CI integration, admin metrics page.
**M6 - Auth, limits, observability (3-4 days):** auth, workspaces, rate and cost limits, tracing, error monitoring.
**M7 - Deploy and polish (4-5 days):** public deployment, demo workspace, README with results, architecture diagram, demo GIF, short write-up.
**M8 - Stretch (optional):** external Postgres connections, glossary auto-suggestions, few-shot learning from thumbs-up corrections, query-cost estimation, scheduled reports, voice input.

---

## 15. Definition of done

- Public URL works; the demo workspace answers questions with no signup.
- Reported benchmark numbers in the README (custom + public subset), with ablation table and methodology.
- Safety suite passes with every attack category covered.
- CI is green: lint, types, tests, smoke benchmark; regression gate demonstrated on at least one PR.
- README includes: one-line pitch, demo GIF, architecture diagram, quickstart (Docker), results table, design decisions and trade-offs, limitations, security notes, license.
- `docs/` includes the evaluation methodology and decision log.
- At least 20 real users (friends, classmates) have tried it, with feedback captured and a short note on what changed because of it.
- No secrets in the repo or its history.

---

## 16. Risks and how to handle them

- Scope creep: do not start M8 before M7 is done.
- LLM cost: set caps, cache, route cheap vs. strong models.
- Flaky accuracy numbers: fix seeds/temperature, run repeated trials, report confidence intervals.
- Messy real-world data: invest early in the ingestion/profiling step; it drives accuracy more than prompt tweaks.
- Security gaps: treat the SQL validator and isolation as the highest-priority code; fuzz-test it.
- Benchmark leakage: never put benchmark questions in prompts or few-shot examples.

---

## 17. First prompt to give the coding LLM

"Read this spec fully. Start with Milestone M0. Propose the repo layout, the docker-compose file, the backend config and logging setup, the LLM client interface with a mock implementation, and a CI workflow. Explain any deviations from the spec before writing code. After finishing M0, summarize what was built, list tests added, and wait for my confirmation before starting M1."
