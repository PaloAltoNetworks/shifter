#!/usr/bin/env bash
#
# Count lines of code in the Shifter repository
# Excludes vendor code, build artifacts, and auto-generated files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cloc "${REPO_ROOT}" \
  --exclude-dir=.venv,node_modules,__pycache__,.pytest_cache,.ruff_cache,.git,.terraform,_deprecated,.mypy_cache,htmlcov,.coverage,staticfiles,migrations \
  --exclude-ext=lock
