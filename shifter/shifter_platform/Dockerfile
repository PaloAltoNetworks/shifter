# syntax=docker/dockerfile:1

# Build stage - use uv's official image for faster builds
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder

WORKDIR /app

# Copy the Django-free shared packages first (better layer caching)
COPY cyberscript /cyberscript
COPY installation /installation

# Copy dependency files. requirements-gcp.lock is the pinned + hashed compile of
# requirements-gcp.txt; regenerate it with:
#   uv export --no-emit-project --frozen --no-hashes > /tmp/constraint.txt
#   uv pip compile requirements-gcp.txt --constraint /tmp/constraint.txt \
#     --python-version 3.12 --generate-hashes -o requirements-gcp.lock
COPY shifter_platform/pyproject.toml shifter_platform/uv.lock shifter_platform/requirements-gcp.lock ./

# Export the platform's frozen lock to a hashed requirements.txt and install everything
# from it with hashes enforced and wheels only — no source builds, so no third-party
# setup scripts execute at install time (docker:S8541) and every version is locked and
# integrity-checked (docker:S8544). requirements-gcp.lock is installed the same way and
# is constrained to the frozen lock, so shared transitive deps stay at the locked
# versions rather than an unpinned rebuild-time resolution. The local shared packages —
# cyberscript (data contracts) and installation (root installation config;
# Django/workers/provisioner derive runtime config from it) — are first-party source, so
# they are built to wheels and installed --no-deps / wheel-only.
# --no-config: requirements.txt / requirements-gcp.lock are already fully resolved
# against the frozen lock (which incorporated [tool.uv].constraint-dependencies), so the
# install must NOT re-read pyproject's unpinned [tool.uv] constraints — under
# --require-hashes those `>=` entries would be rejected as not `==`-pinned.
# py-ubjson (a vestigial autobahn->daphne transitive) ships sdist-only with no wheel on
# any platform, so it is the single --no-binary source exception; everything else is
# wheel-only. It is version-pinned and hash-verified, and has a pure-Python fallback so
# it needs no compiler.
RUN uv export --no-emit-project --frozen > requirements.txt && \
    uv pip install --system --no-cache --no-config --require-hashes --only-binary :all: --no-binary py-ubjson -r requirements.txt && \
    uv pip install --system --no-cache --no-config --require-hashes --only-binary :all: -r requirements-gcp.lock && \
    uv build --wheel /cyberscript --out-dir /wheels && \
    uv build --wheel /installation --out-dir /wheels && \
    uv pip install --system --no-cache --no-config --no-deps --only-binary :all: /wheels/*.whl

# Production stage
FROM python:3.12-slim-trixie AS production

WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash appuser

# Install runtime dependencies
# gettext provides msgfmt, required by `manage.py compilemessages` in
# entrypoint.sh (added in #1260, Django i18n adoption).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gettext \
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
