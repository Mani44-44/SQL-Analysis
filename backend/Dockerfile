# Build from the repository root:  docker build -f backend/Dockerfile -t askdata-api .
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/backend/.venv

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv

WORKDIR /srv/backend
# Dependencies first so code edits don't invalidate this layer.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
# The benchmark and few-shot pool are read at runtime by the eval endpoints and CLI.
COPY eval_data/ /srv/eval_data/

RUN groupadd --system --gid 10001 askdata \
    && useradd --system --uid 10001 --gid 10001 --home /srv askdata \
    && mkdir -p /data && chown askdata:askdata /data \
    && chmod +x /srv/backend/docker-entrypoint.sh
# No USER line: the entrypoint starts as root only to fix volume ownership, then drops to 10001.

ENV PATH="/srv/backend/.venv/bin:$PATH" \
    ENVIRONMENT=prod \
    DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/app.sqlite \
    LOG_JSON=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=4)"

# One worker on purpose: workspace locks, the rate limiter and the cost tracker are in-process
# (docs/decisions.md D-020). Scale by running a bigger machine, not more workers.
# The entrypoint seeds first: migrations run, and the demo workspace is created only if missing.
ENTRYPOINT ["/srv/backend/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
