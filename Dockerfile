# syntax=docker/dockerfile:1.7
# Deno backend image: API (default CMD), worker and scheduler (compose overrides the command).
# Python 3.12 in containers (ADR-014); the local 3.14 venv is dev only.

FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependencies first (cached layer), then the workspace sources.
COPY pyproject.toml uv.lock ./
COPY packages/gates/pyproject.toml packages/gates/pyproject.toml
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/sources/pyproject.toml packages/sources/pyproject.toml
COPY packages/llm/pyproject.toml packages/llm/pyproject.toml
COPY packages/rag/pyproject.toml packages/rag/pyproject.toml
COPY packages/graphs/pyproject.toml packages/graphs/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --no-install-workspace
COPY packages packages
COPY apps apps
COPY migrations migrations
COPY alembic.ini alembic.ini
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --no-editable

FROM python:3.14-slim AS runtime
RUN groupadd --system --gid 10001 deno && useradd --system --uid 10001 --gid deno --no-create-home deno
COPY --from=build --chown=deno:deno /app/.venv /app/.venv
COPY --from=build --chown=deno:deno /src/migrations /app/migrations
COPY --from=build --chown=deno:deno /src/alembic.ini /app/alembic.ini
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 ENVIRONMENT=production
WORKDIR /app
USER deno
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "deno_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
