#!/usr/bin/env bash
set -euo pipefail
exec "$(dirname "$0")/smoke-test.sh" --variant windows "$@"
