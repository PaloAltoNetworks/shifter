#!/bin/bash
# Executed from the approved verifier context, never from the candidate disk.
set -euo pipefail
context="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -I "${context}/verify.py" "${1:?read-only candidate root is required}"
