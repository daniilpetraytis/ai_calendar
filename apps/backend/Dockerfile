FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv: fast Python package manager
COPY --from=ghcr.io/astral-sh/uv:0.5.8 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

COPY . .

RUN uv sync --frozen 2>/dev/null || uv sync

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
