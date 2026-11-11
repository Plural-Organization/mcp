FROM ghcr.io/astral-sh/uv:0.10.11 AS uv

FROM python:3.12.12-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.12-slim-bookworm

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

RUN groupadd --system --gid 10001 plural-mcp \
    && useradd --system --uid 10001 --gid plural-mcp --home-dir /nonexistent plural-mcp

WORKDIR /app
COPY --from=builder /app/.venv .venv

USER plural-mcp
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).read()"]

CMD ["plural-mcp"]
