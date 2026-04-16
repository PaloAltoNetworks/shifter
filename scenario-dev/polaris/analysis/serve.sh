#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/website"
PORT="${PORT:-8090}"
# serve the website, with ../data/ also accessible so the page can GET data/analysis.json
cd ..
cat <<BANNER
POLARIS event analysis — serving on http://127.0.0.1:${PORT}/website/
  - website:       http://127.0.0.1:${PORT}/website/
  - raw JSON:      http://127.0.0.1:${PORT}/data/analysis.json
  - cleaned CSVs:  http://127.0.0.1:${PORT}/data/cleaned/

press Ctrl-C to stop
BANNER
# simple static server
exec python3 -m http.server "${PORT}" --bind 127.0.0.1
