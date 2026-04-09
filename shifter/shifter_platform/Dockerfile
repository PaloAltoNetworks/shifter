# syntax=docker/dockerfile:1

# Build stage - use uv's official image for faster builds
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder

WORKDIR /app

# Copy cyberscript library first (better layer caching)
COPY cyberscript /cyberscript

# Copy dependency files
COPY shifter_platform/pyproject.toml shifter_platform/uv.lock shifter_platform/requirements-gcp.txt ./

# Export requirements and install dependencies into system Python
# Install cyberscript as a local package
RUN uv export --no-hashes --no-emit-project --frozen > requirements.txt && \
    uv pip install --system --no-cache -r requirements.txt && \
    uv pip install --system --no-cache -r requirements-gcp.txt && \
    uv pip install --system --no-cache /cyberscript

# Production stage
FROM python:3.12-slim-trixie AS production

WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash appuser

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/gunicorn /usr/local/bin/daphne /usr/local/bin/django-admin /usr/local/bin/

# Copy application code (context is now shifter/, so path is shifter_platform)
COPY --chown=appuser:appgroup shifter_platform .

# Create staticfiles directory for collectstatic
RUN mkdir -p /app/staticfiles && chown appuser:appgroup /app/staticfiles

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Switch to non-root user
USER appuser

# Health check using Python (curl not available in slim image)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')" || exit 1

# Expose port
EXPOSE 8000

# Entrypoint
ENTRYPOINT ["./entrypoint.sh"]
