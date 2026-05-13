FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.8 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

COPY . .

RUN uv sync --frozen 2>/dev/null || uv sync

EXPOSE 8001

CMD ["uv", "run", "python", "-m", "app.main"]
