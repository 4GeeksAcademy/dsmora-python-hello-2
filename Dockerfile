# syntax=docker/dockerfile:1
# Agentic RFP Workflow — teaching example image, built with `uv`.
#
# Runtime is pure Python standard library, so the image is tiny and dependency
# resolution is handled entirely by uv (highly reproducible via uv.lock).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1. Resolve + lock FIRST (cache layer: lockfile changes rarely)
COPY pyproject.toml uv.lock README.md ./
# Zero runtime deps -> sync brings just the project itself (editable install).
RUN uv sync --frozen --no-install-project --no-dev

# 2. Copy the source and install the project (entry points: rfp-e2e, observability-server)
COPY agentic_workflow_example ./agentic_workflow_example
COPY run_rfp_e2e.py ./run_rfp_e2e.py
COPY services ./services
COPY src ./src
RUN uv sync --frozen --no-dev

# Store tickets/raw/docs inside the container (optionally bind-mounted by compose)
RUN mkdir -p /app/data/raw /app/data/state /app/data/documents /app/data/pipelines

# 3. Runtime
EXPOSE 8000
CMD ["uv", "run", "observability-server"]