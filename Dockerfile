# ── Stage 1: Install dependencies ─────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy only dependency definition first (layer caching)
COPY pyproject.toml .
COPY src/aiwebnovel/__init__.py src/aiwebnovel/__init__.py

# Install runtime dependencies into /build/.venv
RUN python -m venv /build/.venv && \
    /build/.venv/bin/pip install --no-cache-dir --upgrade pip && \
    /build/.venv/bin/pip install --no-cache-dir . && \
    # Fix shebangs to use the runtime path (/app/.venv)
    find /build/.venv/bin -type f -exec \
        sed -i 's|#!/build/.venv/bin/python|#!/app/.venv/bin/python|g' {} + 2>/dev/null || true

# ── Stage 2: Runtime image ───────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

# Install runtime-only system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r aiwn && useradd -r -g aiwn -d /app -s /bin/bash aiwn

# Copy virtualenv from builder
COPY --from=builder /build/.venv /app/.venv

# Copy application code
COPY src/ /app/src/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Ensure the venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Create directories for assets and data
RUN mkdir -p /app/assets/images /app/vector_store /app/data && \
    chown -R aiwn:aiwn /app

USER aiwn

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=30s \
    CMD curl -f http://localhost:8003/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]

CMD ["gunicorn", "aiwebnovel.main:create_app()", \
     "--bind", "0.0.0.0:8003", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--timeout", "120"]
