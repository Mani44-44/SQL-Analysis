# AskData: execution plan

This plan breaks the spec (`docs/SPEC.md`) into phases. Each phase ends with:

1. a green gate: `ruff check`, `ruff format --check`, `mypy`, `pytest`, and from P7 on `npm run lint && npm run build`,
2. docs updated (`decisions.md`, plus README sections where relevant),
3. a commit, or a few commits, with conventional messages, a `phase-N` tag, and a push when a remote exists.

The status column is updated as phases land.

| Phase | Name | Status |
|---|---|---|
| P0 | Spec revision, plan, repo bootstrap | done |
| P1 | Backend foundation | done |
| P2 | Demo data and ingestion | done |
| P3 | SQL guard and sandboxed executor | done |
| P4 | Text-to-SQL pipeline and query API | done |
| P5 | Charts, explanations, history, feedback, export | done |
| P6 | Evaluation harness and CI eval | done |
| P7 | Frontend | done |
| P8 | Auth, limits, observability | done |
| P9 | Deploy readiness and docs | pending |
| P10 | Stretch | backlog |

---

## P0: Spec revision, plan, repo bootstrap
- `git init`, `.gitignore`, `.gitattributes`.
- Commit the original spec, then the revised `docs/SPEC.md` on top, so the diff shows what changed.
- `docs/PLAN.md` (this file) and `docs/decisions.md`, with the initial decisions D-001…D-008.
- A placeholder README and an MIT LICENSE.

**Exit:** the documents are committed and tagged `phase-0`.

## P1: Backend foundation
- `backend/pyproject.toml` (uv): fastapi, uvicorn, pydantic-settings, sqlalchemy, alembic, duckdb, sqlglot, pandas, openpyxl, anthropic, structlog-free stdlib JSON logging. Dev dependencies: pytest, hypothesis, httpx, ruff, mypy.
- `core/config.py`: a typed `Settings` with all limits from the spec, with defaults.
- `core/logging.py`: JSON log formatter, plus request-ID middleware that sets a contextvar and adds a response header.
- `db/`: SQLAlchemy 2 models for every table in spec §8, a session factory, and Alembic with an initial migration, kept dialect-agnostic.
- `services/llm/`:
  - the `LLMProvider` protocol (`complete_json(schema_model, system, messages, tier) -> LLMResult[T]`),
  - `MockProvider`, which is deterministic and driven by fixtures,
  - `AnthropicProvider`, which uses structured outputs and the typed error chain, and records usage and cost,
  - a `get_provider()` factory: the mock when no key is set, or when `LLM_PROVIDER=mock`.
- `api/health.py`: `/health`, `/health/ready`.
- `.env.example`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` (backend job).
- Tests: config, logging and request IDs, the health endpoints, the mock provider, and Anthropic response parsing with a fake client.

**Exit:** the gate is green and the commit is tagged `phase-1`.

## P2: Demo data and ingestion
- `scripts/generate_demo_data.py`: a seeded generator that writes messy CSVs (accounts, transactions ~5k rows, merchants, categories, budgets) plus one XLSX variant.
- `services/ingestion/`:
  - `readers.py`: CSV with delimiter and encoding sniffing, XLSX, and SQLite import,
  - `clean.py`: headers, blank and repeated-header rows, whitespace,
  - `infer.py`: types (int, float, currency, percent, bool, date, timestamp, text) with a 95% threshold,
  - `profile.py`,
  - `loader.py`: writes DuckDB tables under a per-workspace lock,
  - `service.py`: orchestration and status transitions.
- `services/schema/cards.py`: builds schema cards from the profile and inferred FK hints.
- API: upload (multipart, size-checked), list and get sources, delete a source, get the schema, PATCH a column (description or type override, which reloads), PATCH a table, and glossary CRUD.
- `scripts/seed_demo.py`: creates the demo workspace and ingests the generated data and the glossary.
- Tests:
  - every cleaning rule, with parametrised messy inputs,
  - type inference edge cases,
  - profile stats,
  - an end-to-end ingestion of the generated data into DuckDB,
  - the API upload flow.

**Exit:** the gate is green and the commit is tagged `phase-2`.

## P3: SQL guard and sandboxed executor
- `services/sqlguard/`:
  - `validator.py`: parse with sqlglot (duckdb), single statement, root-type allowlist, table allowlist including CTE scoping, a table-function ban, a function allowlist, column resolution, a recursive-CTE ban, and a cross-join guard,
  - `functions.py`: the allowlist,
  - `errors.py`: typed violations with user-friendly messages,
  - `rewrite.py`: row-cap wrapping.
- `services/execution/executor.py`: a read-only DuckDB connection, hardening settings followed by `lock_configuration`, a watchdog `interrupt()` timeout, row cap and truncation flag, an audit log line, and an `ExecutionResult` holding columns, types, rows, truncated and duration.
- `tests/security/`: a table-driven case for every attack category in spec §9.4, plus hypothesis fuzzing (random statements and mutations of valid queries), plus runtime tests proving the sandbox blocks file access even if validation were bypassed (defence in depth).
- mypy strict on these two packages.

**Exit:** the safety suite passes 100%, the gate is green, and the commit is tagged `phase-3`.

## P4: Text-to-SQL pipeline and query API
- `prompts/generate_sql.v1.md`, `prompts/correct_sql.v1.md`, `prompts/resolve_followup.v1.md`, and a loader that parses the version header.
- `services/schema/linking.py`: BM25 (implemented in house, small) plus a glossary boost, and a threshold to skip linking on small schemas.
- `services/text2sql/`:
  - `models.py`: `GenerationOutput`, `PipelineResult` and `StageTrace`,
  - `context.py`: follow-up resolution, which only calls the LLM when the question has referential cues and there is prior history,
  - `generate.py`: prompt assembly with delimited data blocks,
  - `pipeline.py`: the orchestrator, with the correction loop, suspicious-result checks, tracing and cost accumulation,
  - `cache.py`: a TTL/LRU keyed on (workspace, schema_hash, resolved_question).
- Mock fixtures for the demo-question set, so pipeline tests exercise the success, correction, clarify and unanswerable paths.
- API: `POST /ask` (JSON and SSE), `POST /sql/run`, and persistence to `conversations`, `messages` and `query_runs`.
- Tests: the pipeline paths, the correction loop recovering from an injected bad SQL, follow-up resolution, linking ranking, SSE event order, and the API.

**Exit:** the gate is green and the commit is tagged `phase-4`.

## P5: Charts, explanations, history, feedback, export
- `services/charts/picker.py` and `spec.py`: the rule-based picker and the validated spec model.
- `prompts/explain.v1.md`: the explanation uses the fast tier, and only receives summarised rows.
- API: conversations list and get, saved-queries CRUD, feedback (validates corrected SQL), and CSV export (re-executes `final_sql` with the export row cap).
- Tests: the picker over a matrix of result shapes, spec validation, explanation input truncation, feedback validation, and export.

**Exit:** the gate is green and the commit is tagged `phase-5`.

## P6: Evaluation harness and CI eval
- `eval_data/finance_v1.jsonl`: 80 or more cases with tags, smoke flags, gold SQL, and expected kind.
- `eval_data/fewshot_pool.jsonl`, plus a leakage test asserting no overlap with the benchmark (normalised question similarity).
- `app/eval/`:
  - `matching.py`: the execution-match semantics from spec §9.2,
  - `error_category.py`,
  - `runner.py`: concurrency, repeats, and ablation flags,
  - `metrics.py`: accuracy, kind accuracy, recovery rate, latency, cost, bootstrap CI and breakdowns,
  - `compare.py`,
  - `report.py`: markdown tables,
  - `__main__` CLI: `python -m app.eval.run --dataset finance_v1 --smoke --config full --repeats 3`.
- Persist to `eval_runs` and `eval_results`, and write a JSON and markdown report.
- API: eval runs list and get, compare, and `/metrics`.
- CI:
  - `ci.yml` adds the gold-SQL validity check and a mock-provider benchmark run,
  - `eval.yml` runs the keyed smoke benchmark on PRs (skips without the secret), posts a PR comment, applies the regression gate against `baseline.json`, and runs nightly.
- Tests: matching semantics (ordering, floats, NULLs, superset columns), metrics, the bootstrap CI, the runner using the mock, and compare.

**Exit:** the gate is green and the commit is tagged `phase-6`.

## P7: Frontend
- Next.js 15 + TypeScript + Tailwind. An API client with typed responses, and an SSE reader.
- Pages: landing (with the demo CTA), data (upload, schema explorer, glossary), ask (chat, CodeMirror SQL panel, results table, Recharts chart, explanation, warnings, feedback, PNG/CSV export), history, and metrics.
- Accessible components, a colour-blind-safe palette, responsive layouts, and empty, loading and error states.
- CI frontend job: lint, typecheck, build.

**Exit:** `npm run build` is green, the backend gate is green, and the commit is tagged `phase-7`.

## P8: Auth, limits, observability
- argon2 password hashing, JWT in an httpOnly cookie, register/login/logout/me.
- `current_user` and `workspace_access(role)` dependencies applied to every workspace route. The demo workspace is public and read-only.
- An in-process sliding-window rate limiter (per user, or per IP for demo users) and a daily cost cap, both behind an interface.
- `/metrics` aggregates from `query_runs`. Sentry is initialised when `SENTRY_DSN` is set.
- Frontend: login and register pages, the workspace switcher, and auth-aware fetch.
- Tests: auth flows, cross-workspace access denied (security), rate limit, cost cap, and the demo being read-only.

**Exit:** the gate is green and the commit is tagged `phase-8`.

## P9: Deploy readiness and docs
- `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` (backend, frontend, postgres) and `fly.toml` / `render.yaml` examples.
- README: the pitch, architecture diagram (mermaid), quickstarts, results table (from the mock wiring run and marked "pending a keyed run" until the user runs it), security model, limitations, and retention policy.
- `docs/architecture.md` and `docs/evaluation.md`.
- A final pass over everything: the security review checklist and a dependency audit.

**Exit:** everything is green and the commit is tagged `phase-9`.

## P10: Stretch (backlog)
- External Postgres connections with Fernet-encrypted credentials.
- Few-shot examples taken from thumbs-up corrections.
- Embedding-based schema linking.
- OAuth.
- Playwright E2E.
- Query-cost estimation.
- Scheduled reports.

---

## Environment constraints at build time
- No Docker, Postgres or Redis on the build machine. Local development uses SQLite and DuckDB, and the Docker artifacts are written but **not executed** here.
- No `ANTHROPIC_API_KEY`, so all tests use the mock provider and real benchmark numbers are a user-owned step.
- No GitHub remote and no `gh` CLI, so each phase is committed and tagged locally. To publish: `git remote add origin <url> && git push -u origin main --tags`.
