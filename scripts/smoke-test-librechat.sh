#!/usr/bin/env bash
#
# Smoke test for local LibreChat Docker Compose stack.
# Starts the stack, waits for health, then cleans up.
#
set -euo pipefail

cd "$(dirname "$0")/../librechat"

# Init if needed (creates .env and starts services)
make init

# Wait for health (max 90s)
echo "Waiting for LibreChat to be healthy..."
for i in {1..18}; do
  if curl -sf http://localhost:3080/api/health >/dev/null 2>&1; then
    echo "LibreChat is healthy"
    make down
    exit 0
  fi
  sleep 5
done

echo "Health check failed after 90s"
docker compose logs
make down
exit 1

