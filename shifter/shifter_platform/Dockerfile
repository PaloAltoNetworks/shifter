# syntax=docker/dockerfile:1

# Build stage - use uv's official image for faster builds. Digest-pinned for
# build provenance (ADR-037-R2): the resolved input is an immutable @sha256,
# and the "# base image:" comment above the FROM records the human-readable
# tag. Digest-only (no tag) satisfies SonarCloud docker:S8431 ("specify tag OR
# digest, not both"). Refresh the digest via the reviewed process in
# docs/architecture/rev1-build-deployment-provenance.md.
# base image: python3.12-trixie-slim
FROM ghcr.io/astral-sh/uv@sha256:3137a0b606f65a74ee0245f43dae219b09e8af98fc37fef20841cbceef35a646 AS builder

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
# --no-dev excludes the [dependency-groups].dev group from the export: dev/test
# tooling (ruff, pytest, mypy, ...) has no place in the production image. Runtime
# deps live in [project].dependencies and are exported here. `aces-sdl` is a
# runtime dependency (issue #1262: shared.aces.runtime_target imports it) and is
# installed from its published PyPI wheel, so uv emits a hash for it and the
# --require-hashes install succeeds; it was previously a git source, which uv
# cannot hash, and that broke this build when it was promoted to runtime (#1445).
RUN uv export --no-emit-project --frozen --no-dev > requirements.txt && \
    uv pip install --system --no-cache --no-config \
        --require-hashes --only-binary :all: --no-binary py-ubjson \
        -r requirements.txt && \
    uv pip install --system --no-cache --no-config \
        --require-hashes --only-binary :all: \
        -r requirements-gcp.lock

# Frontend build stage (ADR-029 / #1302). Builds the SPA bundle into the static
# tree so collectstatic folds it into STATIC_ROOT. Node is a build-time-only
# dependency; the production image ships no Node runtime. Digest-pinned for
# build provenance (ADR-037-R2); digest-only satisfies docker:S8431. Refresh
# per docs/architecture/rev1-build-deployment-provenance.md.
# base image: node:20-slim
FROM node@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS frontend

WORKDIR /app/shifter_platform/frontend

# Install with the committed lockfile for a reproducible, offline-resolvable build.
# --ignore-scripts blocks package lifecycle scripts (docker:S6505); Vite's esbuild
# resolves its prebuilt platform binary from its optional dependency without a
# postinstall, so the build still works.
COPY shifter_platform/frontend/package.json shifter_platform/frontend/package-lock.json ./
RUN npm ci --ignore-scripts

# SPA sources. Vite emits the content-hashed bundle + manifest to
# /app/shifter_platform/static/spa (frontend/vite.config.ts); tsc typecheck runs
# first via `npm run build`.
COPY shifter_platform/frontend ./

RUN npm run build

# Production stage. Digest-pinned for build provenance (ADR-037-R2);
# digest-only satisfies docker:S8431. Refresh per
# docs/architecture/rev1-build-deployment-provenance.md.
# base image: python:3.12-slim-trixie
FROM python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS production

# Image metadata. `maintainer` is the label SonarCloud docker:S7028 requires;
# the org.opencontainers.image.* labels are the modern OCI equivalents.
LABEL maintainer="Shifter maintainers" \
      org.opencontainers.image.title="shifter-portal" \
      org.opencontainers.image.description="Shifter platform portal (Django: Mission Control, CMS, CTF, Management)" \
      org.opencontainers.image.source="https://github.com/Brad-Edwards/shifter" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Shifter maintainers"

WORKDIR /app

# Create non-root user and its writable home. Gunicorn and provisioner helpers
# resolve HOME to /home/appuser in production containers.
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --create-home --home-dir /home/appuser --shell /bin/bash appuser

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

# Bring in the built SPA bundle from the frontend stage. Kept out of the source
# COPY above because it is generated (gitignored / dockerignored); collectstatic
# below folds it into STATIC_ROOT and WhiteNoise fingerprints it (#1302).
COPY --from=frontend --chown=appuser:appgroup /app/shifter_platform/static/spa ./static/spa

# Create writable runtime directories for collectstatic, django-health-check's
# default-storage probe, and tools that use HOME. The application source tree
# stays immutable.
RUN mkdir -p /app/staticfiles /app/media /home/appuser/.terraform.d/plugin-cache /home/appuser/.pulumi && \
    chown -R appuser:appgroup /app/staticfiles /app/media /home/appuser

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/shifter-libs \
    HOME=/home/appuser

# Switch to non-root user
USER appuser

# Build immutable Django runtime artifacts once per image. These commands use
# build-only settings env; runtime secrets are still hydrated by
# entrypoint.sh when the container starts.
RUN BUILD_DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" && \
    BUILD_FIELD_ENCRYPTION_KEY="$( \
      python -c 'import cryptography.fernet as f; print(f.Fernet.generate_key().decode())' \
    )" && \
    DJANGO_SECRET_KEY="$BUILD_DJANGO_SECRET_KEY" \
    FIELD_ENCRYPTION_KEY="$BUILD_FIELD_ENCRYPTION_KEY" \
    ENVIRONMENT=build \
    OIDC_RP_CLIENT_ID=build-time-client \
    OIDC_AUTH_DOMAIN=https://auth.example.test \
    OIDC_ISSUER_URL=https://issuer.example.test \
    python manage.py compilemessages && \
    DJANGO_SECRET_KEY="$BUILD_DJANGO_SECRET_KEY" \
    FIELD_ENCRYPTION_KEY="$BUILD_FIELD_ENCRYPTION_KEY" \
    ENVIRONMENT=build \
    OIDC_RP_CLIENT_ID=build-time-client \
    OIDC_AUTH_DOMAIN=https://auth.example.test \
    OIDC_ISSUER_URL=https://issuer.example.test \
    python manage.py collectstatic --noinput

# Health check using Python (curl not available in slim image)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')" || exit 1

# Expose port
EXPOSE 8000

# Entrypoint
ENTRYPOINT ["./entrypoint.sh"]
