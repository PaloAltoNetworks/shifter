# Shifter clean-checkout test entrypoint (#1529 / REV1 Q7).
#
# One contract, two callers: these targets are what a contributor runs from a
# fresh clone, and they establish the SAME dependency sync + environment posture
# that CI (`.github/workflows/_quality.yml`) uses. All test *policy* -- markers,
# warning classification, coverage source, and coverage floors -- lives in each
# package's own `pyproject.toml` / `package.json`; these targets only select a
# package and a service posture and never restate that policy.
#
# Prerequisites (installed once, not by these targets):
#   - uv     https://docs.astral.sh/uv/   (Python dependency manager)
#   - Node   20.19+ with npm              (JavaScript tests)
# The PostgreSQL and Redis postures additionally need a local service on the
# standard port; see the per-target notes below.

# Synthetic, non-secret key for the Django test posture. Never a real secret;
# override on the command line if a specific value is needed.
TEST_DJANGO_SECRET_KEY ?= shifter-local-make-test-key

# Posture the platform's clean-checkout fast lane runs under. Mirrors the
# shifter-platform-tests CI job. `manage.py collectstatic` is not a test (it does
# not import the test conftest), so it needs the posture on its environment;
# pytest itself also picks these up from conftest, but setting them here keeps
# collectstatic and pytest identical and self-contained.
PLATFORM_ENV := TESTING=1 DJANGO_DEBUG=true TEST_DB_BACKEND=sqlite DJANGO_SECRET_KEY=$(TEST_DJANGO_SECRET_KEY)

.DEFAULT_GOAL := help
.PHONY: help test test-platform test-platform-postgres test-platform-redis \
        test-provisioner test-packer test-installation test-bootstrap \
        test-check-layer-imports test-js

help: ## Show this help
	@echo "Shifter test entrypoint (clean-checkout; matches CI). Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

test: test-platform test-provisioner test-packer test-installation test-bootstrap test-check-layer-imports test-js ## Run every no-service (SQLite/pure-Python/JS) lane

test-platform: ## Platform fast lane (SQLite; sole coverage publisher)
	cd shifter/shifter_platform && uv sync --group dev && \
	  $(PLATFORM_ENV) uv run python manage.py collectstatic --noinput && \
	  $(PLATFORM_ENV) uv run pytest tests/ --ignore=tests/documentation -m "not redis and not postgres" --cov

test-platform-postgres: ## Platform PostgreSQL semantics lane (needs a Postgres service on :5432)
	cd shifter/shifter_platform && uv sync --group dev && \
	  TESTING=1 DJANGO_DEBUG=true TEST_DB_BACKEND=postgres DJANGO_SECRET_KEY=$(TEST_DJANGO_SECRET_KEY) \
	  DB_HOST=localhost DB_PORT=5432 DB_NAME=shifter DB_USER=test DB_PASSWORD=test \
	  uv run pytest tests/ --ignore=tests/documentation -m "not redis"

test-platform-redis: ## Platform Redis channel-layer integration lane (needs a Redis service on :6379)
	cd shifter/shifter_platform && uv sync --group dev && \
	  TESTING=1 DJANGO_DEBUG=true TEST_DB_BACKEND=sqlite DJANGO_SECRET_KEY=$(TEST_DJANGO_SECRET_KEY) \
	  CHANNEL_LAYER_BACKEND=redis REDIS_HOST=localhost REDIS_PORT=6379 \
	  uv run pytest tests/integration/asgi -m redis -n0 -p no:cacheprovider

test-provisioner: ## Engine provisioner suite
	cd shifter/engine/provisioner && uv sync --group dev && TESTING=1 uv run pytest tests/ --cov

test-packer: ## Packer helper suite (no coverage: Packer HCL, not owned production Python)
	cd shifter/packer && uv sync --group dev && uv run pytest tests/

test-installation: ## Installation CLI suite
	cd shifter/installation && uv sync --group dev && uv run pytest tests/ --cov

test-bootstrap: ## Bootstrap deployment-scripts suite
	cd scripts/bootstrap && uv sync --group dev && uv run pytest tests/ --cov

test-check-layer-imports: ## Layer-import checker suite
	cd scripts/check_layer_imports && uv sync --group dev && uv run pytest tests/ --cov

test-js: ## Platform JavaScript (Jest) suite with coverage
	cd shifter/shifter_platform && npm ci && npm run test:coverage
