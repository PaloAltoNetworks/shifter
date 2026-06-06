# syntax=docker/dockerfile:1

# Build stage - use uv's official image for faster builds. Tracked by the
# `docker` dependabot ecosystem; the floating minor tag receives upstream
# security rebuilds (SonarCloud docker:S8431 forbids tag + digest together).
FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS builder

WORKDIR /app

# Copy dependency files. requirements-gcp.lock is the pinned + hashed compile of
# requirements-gcp.txt; regenerate it with:
#   uv export --no-emit-project --frozen --no-hashes > /tmp/constraint.txt
#   uv pip compile requirements-gcp.txt --constraint /tmp/constraint.txt \
#     --python-version 3.12 --generate-hashes -o requirements-gcp.lock
COPY shifter_platform/pyproject.toml shifter_platform/uv.lock shifter_platform/requirements-gcp.lock ./

# Export the platform's frozen lock to a hashed requirements.txt and install every
# third-party dependency with hashes enforced and wheels only — no source builds, so no
# setup scripts execute at install time (docker:S8541) and every version is locked and
# integrity-checked (docker:S8544). requirements-gcp.lock is installed the same way and
# is constrained to the frozen lock, so shared transitive deps stay at the locked
# versions rather than an unpinned rebuild-time resolution.
# --no-config: requirements.txt / requirements-gcp.lock are already fully resolved
# against the frozen lock (which incorporated [tool.uv].constraint-dependencies), so the
# install must NOT re-read pyproject's unpinned [tool.uv] constraints — under
# --require-hashes those `>=` entries would be rejected as not `==`-pinned.
# py-ubjson (a vestigial autobahn->daphne transitive) ships sdist-only with no wheel on
# any platform, so it is the single --no-binary source exception; it is version-pinned
# and hash-verified, with a pure-Python fallback so it needs no compiler.
# The first-party packages (cyberscript, installation) are NOT installed here: they are
# first-party source with no external resolution to lock or hash, so they ride on
# PYTHONPATH in the production stage instead of through a pip install.
RUN uv export --no-emit-project --frozen > requirements.txt && \
    uv pip install --system --no-cache --no-config \
        --require-hashes --only-binary :all: --no-binary py-ubjson \
        -r requirements.txt && \
    uv pip install --system --no-cache --no-config \
        --require-hashes --only-binary :all: \
        -r requirements-gcp.lock

# Production stage. Tracked by the `docker` dependabot ecosystem; the floating
# minor tag receives upstream security rebuilds (docker:S8431 forbids tag +
# digest together).
FROM python:3.12-slim-trixie AS production

# Image metadata. `maintainer` is the label SonarCloud docker:S7028 requires;
# the org.opencontainers.image.* labels are the modern OCI equivalents.
LABEL maintainer="Shifter maintainers" \
      org.opencontainers.image.title="shifter-portal" \
      org.opencontainers.image.description="Shifter platform portal (Django: Mission Control, CMS, CTF, Management)" \
      org.opencontainers.image.source="https://github.com/Brad-Edwards/shifter" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Shifter maintainers"

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

# First-party shared packages on PYTHONPATH (cyberscript = data contracts, installation =
# root installation config). They are first-party source with no external dependency to
# lock/hash, so they ride on PYTHONPATH rather than a pip install, which Sonar flags as an
# unlocked/unhashed resolution (docker:S8544). Flat-layout packages: the directory IS the
# importable package.
COPY cyberscript /opt/shifter-libs/cyberscript
COPY installation /opt/shifter-libs/installation

# Copy application code (context is now shifter/, so path is shifter_platform)
COPY --chown=appuser:appgroup shifter_platform .

# Create staticfiles directory for collectstatic
RUN mkdir -p /app/staticfiles && chown appuser:appgroup /app/staticfiles

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/shifter-libs

# Switch to non-root user
USER appuser

# Health check using Python (curl not available in slim image)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')" || exit 1

# Expose port
EXPOSE 8000

# Entrypoint
ENTRYPOINT ["./entrypoint.sh"]
