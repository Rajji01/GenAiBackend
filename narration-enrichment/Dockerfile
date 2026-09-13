# uv's own static binary — no separate pip install step needed to get uv itself.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Dependencies first, copied and installed before the app source, so
# editing application code doesn't invalidate the (slow) dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY README.md ./
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "narration_enrichment.main:app", "--host", "0.0.0.0", "--port", "8000"]
