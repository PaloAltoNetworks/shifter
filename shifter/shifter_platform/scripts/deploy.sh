#!/usr/bin/env bash
# =============================================================================
# Shifter Production Deploy
# =============================================================================
# Quick-start script for deploying Shifter in production mode.
# Usage: ./scripts/deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.deploy.yml"

# ---------- .env check --------------------------------------------------------
if [[ ! -f .env ]]; then
    echo "No .env file found. Copying from .env.deploy.example..."
    cp .env.deploy.example .env
    echo "Edit .env with your production values, then re-run this script."
    exit 1
fi

# ---------- Required variable validation --------------------------------------
REQUIRED_VARS=(
    DOMAIN_NAME
    DJANGO_SECRET_KEY
    DB_PASSWORD
    FIELD_ENCRYPTION_KEY
    GUACAMOLE_JSON_AUTH_SECRET
    GUACAMOLE_DB_PASSWORD
)

MISSING=()
for var in "${REQUIRED_VARS[@]}"; do
    val=$(grep -E "^${var}=" .env | head -1 | cut -d= -f2-)
    if [[ -z "$val" || "$val" == "CHANGEME" ]]; then
        MISSING+=("$var")
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo "ERROR: The following required variables are missing or unchanged in .env:"
    for var in "${MISSING[@]}"; do
        echo "  - $var"
    done
    exit 1
fi

# ---------- TLS certificate ---------------------------------------------------
TLS_DIR=$(grep -E "^TLS_CERT_DIR=" .env | head -1 | cut -d= -f2- || echo "./nginx/ssl")
TLS_DIR="${TLS_DIR:-./nginx/ssl}"

if [[ ! -f "$TLS_DIR/cert.pem" || ! -f "$TLS_DIR/key.pem" ]]; then
    echo "No TLS certificate found in $TLS_DIR. Generating self-signed cert..."
    mkdir -p "$TLS_DIR"
    DOMAIN=$(grep -E "^DOMAIN_NAME=" .env | head -1 | cut -d= -f2-)
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$TLS_DIR/key.pem" \
        -out "$TLS_DIR/cert.pem" \
        -subj "/CN=${DOMAIN:-localhost}" \
        2>/dev/null
    echo "Self-signed certificate created."
fi

# ---------- Deploy ------------------------------------------------------------
echo "Building and starting Shifter in production mode..."
$COMPOSE_CMD up -d --build

# ---------- Health check ------------------------------------------------------
echo "Waiting for health check..."
RETRIES=30
for i in $(seq 1 $RETRIES); do
    if curl -sfk https://localhost/health > /dev/null 2>&1; then
        echo ""
        DOMAIN=$(grep -E "^DOMAIN_NAME=" .env | head -1 | cut -d= -f2-)
        echo "Shifter is running at https://${DOMAIN:-localhost}"
        echo ""
        echo "Verify with:"
        echo "  $COMPOSE_CMD ps"
        echo "  curl -k https://localhost/health"
        exit 0
    fi
    printf "."
    sleep 2
done

echo ""
echo "WARNING: Health check did not pass within 60s."
echo "Check logs with: $COMPOSE_CMD logs web"
exit 1
