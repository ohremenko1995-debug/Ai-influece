# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# InfluencerOS API image. Build context is the repository root.
#
# The same image serves the `api` and `worker` compose services; only the
# command differs (see worker.Dockerfile, which extends this stage).
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# libpq is not needed (asyncpg speaks the wire protocol directly), but curl is
# handy for debugging inside the container and gcc is needed by argon2-cffi
# wheels on architectures without a prebuilt wheel.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app/apps/api

# Dependency layer: copy only the manifests so edits to app code do not bust
# the dependency cache.
COPY apps/api/pyproject.toml apps/api/uv.lock* ./
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python -r pyproject.toml --extra dev

COPY apps/api ./

# Install the project itself (editable) so `app.*` and console scripts resolve.
RUN uv pip install --python /opt/venv/bin/python --no-deps -e .

RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /app /opt/venv
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
