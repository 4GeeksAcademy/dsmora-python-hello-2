FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src ./src
COPY app ./app

RUN uv pip install --system --no-cache .

EXPOSE 8000 5555
