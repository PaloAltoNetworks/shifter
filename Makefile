# Shifter developer entrypoint (#1529 / REV1 Q7; promotion target #1868).
#
# Nearly every target here is a clean-checkout test lane. One contract, two
# callers: those targets are what a contributor runs from a fresh clone, and
# they establish the SAME dependency sync + environment posture that CI
# (`.github/workflows/_quality.yml`) uses. All test *policy* -- markers,
# warning classification, coverage source, and coverage floors -- lives in each
# package's own `pyproject.toml` / `package.json`; the test targets only select
# a package and a service posture and never restate that policy.
#
# `devmain` is the exception, and the only target with an effect outside the
# working tree: it opens the `dev` to `main` promotion pull request on GitHub.
# It is deliberately not a prerequisite of `test`, `policy`, or any other
# verification target -- running a check must never create a pull request.
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

# Canonical repository for the `dev` -> `main` promotion PR. This checkout is a
# fork of PaloAltoNetworks/shifter and carries a second `panw` remote, so an
# unpinned `gh pr create` resolves its base repository to the fork parent and
# would open the promotion PR against the upstream OSS repo. `.gc/plan-rules.md`
# makes this value canonical regardless of remote configuration; `scripts/ami.sh`
# pins the same way. Overridable only to target a different fork -- base, head,
# title, and body are fixed because fixing them is the point of the target.
DEVMAIN_REPO ?= Brad-Edwards/shifter
DEVMAIN_TITLE := chore(main): promote dev
DEVMAIN_BODY := Promotes dev to main. Merge this PR with a merge commit. Do not squash it: squashing collapses the Conventional Commit subjects release-please reads on main, so the release PR loses this release's version bump and CHANGELOG section. See docs/DEVELOPMENT_WORKFLOW.md.

.DEFAULT_GOAL := help
.PHONY: help test test-platform test-platform-postgres test-platform-redis \
        test-provisioner test-packer test-installation test-bootstrap \
        test-check-layer-imports test-js test-platform-e2e test-platform-a11y test-adr-guard policy devmain

help: ## Show this help
	@echo "Shifter developer entrypoint. Test targets reproduce CI from a clean"
	@echo "checkout; devmain opens a pull request on GitHub. Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

test: test-platform test-provisioner test-packer test-installation test-bootstrap test-check-layer-imports test-charts test-js test-adr-guard ## Run every no-service (SQLite/pure-Python/JS) lane

test-platform: ## Platform fast lane (SQLite; sole coverage publisher)
	cd shifter/shifter_platform && uv sync --group dev && \
	  $(PLATFORM_ENV) uv run python manage.py collectstatic --noinput && \
	  $(PLATFORM_ENV) uv run pytest tests/ -m "not redis and not postgres" --cov

test-platform-postgres: ## Platform PostgreSQL semantics lane (needs a Postgres service on :5432)
	cd shifter/shifter_platform && uv sync --group dev && \
	  TESTING=1 DJANGO_DEBUG=true TEST_DB_BACKEND=postgres DJANGO_SECRET_KEY=$(TEST_DJANGO_SECRET_KEY) \
	  DB_HOST=localhost DB_PORT=5432 DB_NAME=shifter DB_USER=test DB_PASSWORD=test \
	  uv run pytest tests/ -m "not redis"

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

# Mirrors the `chart-tests` CI job. No --cov: the suite validates rendered Helm
# YAML (schema, ALB edge, GCP byte contract), not owned production Python, so a
# coverage number would only measure the tests covering themselves (cf. the
# packer lane). Requires helm on PATH (as the helm-lint pre-commit hook does).
test-charts: ## Helm chart contract suite (renders every backend profile)
	uv run --python 3.12 --with pyyaml --with pytest python -m pytest platform/charts/shifter/tests/ -q

test-js: ## Platform JavaScript (Jest) suite with coverage
	cd shifter/shifter_platform && npm ci && npm run test:coverage

# Authenticated SPA E2E (#1526). Builds the real Django-hosted SPA, migrates and
# seeds a hermetic SQLite stack, and drives Playwright journeys through normal
# session/CSRF. Mirrors the `shifter-platform-e2e` CI job (which uses PostgreSQL).
# LOCAL_PROVISIONER/ENGINE_TASK_* stay unset, so range launch enqueues nothing
# and no cloud is contacted. Requires a Chromium build (installed below).
test-platform-e2e: ## Authenticated SPA E2E (Playwright) against the hermetic Django-hosted SPA
	cd shifter/shifter_platform && uv sync --group dev && \
	  (cd frontend && npm ci && npm run build) && \
	  rm -f db.sqlite3 && \
	  $(PLATFORM_ENV) uv run python manage.py collectstatic --noinput && \
	  $(PLATFORM_ENV) uv run python manage.py migrate --noinput && \
	  $(PLATFORM_ENV) uv run python manage.py seed_e2e && \
	  cd frontend && npx playwright install chromium && \
	  ( $(PLATFORM_ENV) npm run test:e2e; status=$$?; rm -f ../db.sqlite3; exit $$status )

# Browser accessibility scans (#1526, ADR-055). Same hermetic stack as the E2E
# target; runs the @axe-core/playwright surface matrix. Mirrors the deploy.yml
# `Accessibility` PR Gate job (which uses PostgreSQL).
test-platform-a11y: ## Browser accessibility (Playwright + axe) against the hermetic Django-hosted SPA
	cd shifter/shifter_platform && uv sync --group dev && \
	  (cd frontend && npm ci && npm run build) && \
	  rm -f db.sqlite3 && \
	  $(PLATFORM_ENV) uv run python manage.py collectstatic --noinput && \
	  $(PLATFORM_ENV) uv run python manage.py migrate --noinput && \
	  $(PLATFORM_ENV) uv run python manage.py seed_e2e && \
	  cd frontend && npx playwright install chromium && \
	  ( $(PLATFORM_ENV) npm run test:e2e:a11y; status=$$?; rm -f ../db.sqlite3; exit $$status )

# Mirrors the `adr-guard-tests` CI job, including its pinned interpreter and
# pyyaml, so the guard suite runs from a clean checkout the same way. CI selects
# that job from the `adr_guard` quality unit, whose paths exclude the Makefile,
# so this lane is the only route a Makefile-only change has to it.
test-adr-guard: ## Repository-guard suite (adr_guard checks, quality ownership, workflow gating, make targets)
	uv run --python 3.11 --with 'pyyaml==6.0.2' --with coverage \
	  coverage run --source=scripts/adr_guard --omit='scripts/adr_guard/tests/*' \
	    -m unittest discover -s scripts/adr_guard/tests -p 'test_*.py'
	uv run --python 3.11 --with coverage coverage xml -o scripts/adr_guard/coverage.xml

policy: ## Run repository architecture, import, diff, and changed-doc policy
	python3 scripts/adr_guard/adr_guard.py --all --level ci
	cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
	git diff --check
	@if ! command -v vale >/dev/null 2>&1 && [ ! -x .tools/vale/current/vale ]; then \
	  bash tools/install-vale.sh; \
	fi
	@vale_bin="$$(command -v vale 2>/dev/null || true)"; \
	if [ -z "$$vale_bin" ]; then vale_bin=".tools/vale/current/vale"; fi; \
	git diff --name-only --diff-filter=d -z origin/dev...HEAD -- '*.md' | \
	  xargs -0 -r "$$vale_bin"

# Not silenced with `@`: this is the one target that mutates the remote, so the
# operator sees the exact command before it runs. `gh` owns authentication,
# branch validation, and duplicate-PR rejection; its nonzero exit and stderr
# propagate unchanged.
devmain: ## Open the dev -> main promotion PR on GitHub (merge it, never squash)
	gh pr create --repo "$(DEVMAIN_REPO)" --base main --head dev \
	  --title "$(DEVMAIN_TITLE)" \
	  --body "$(DEVMAIN_BODY)"
