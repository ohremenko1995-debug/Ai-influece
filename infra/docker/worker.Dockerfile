# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# InfluencerOS worker image. Build context is the repository root.
#
# Shares the API's dependency set and domain code — the worker is a second
# process type over the same modular monolith, not a separate service with its
# own model layer (docs/adr/0001-modular-monolith.md).
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/apps/worker"

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app/apps/api

COPY apps/api/pyproject.toml apps/api/uv.lock* ./
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python -r pyproject.toml --extra dev

COPY apps/api ./
RUN uv pip install --python /opt/venv/bin/python --no-deps -e .

COPY apps/worker /app/apps/worker

WORKDIR /app/apps/worker

RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /app /opt/venv
USER appuser

CMD ["arq", "worker.main.WorkerSettings"]
