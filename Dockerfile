FROM ghcr.io/astral-sh/uv:0.12.9 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --uid 10001 --create-home app \
    && mkdir /data && chown app:app /data
COPY main.py ./
COPY scripts ./scripts
USER app
CMD ["uvicorn", "dsmora_python_hello_2.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
