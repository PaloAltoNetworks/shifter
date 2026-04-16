#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8080}"
echo "JTF POLARIS briefing deck — serving on http://127.0.0.1:${PORT}"
echo "press Ctrl-C to stop"
exec python3 -m http.server "${PORT}" --bind 127.0.0.1
