#!/usr/bin/env bash
# Generate a self-signed TLS certificate for local/dev Docker deployments.
# Idempotent — skips if certs already exist.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSL_DIR="${SCRIPT_DIR}/ssl"
CERT="${SSL_DIR}/cert.pem"
KEY="${SSL_DIR}/key.pem"
DOMAIN="${DOMAIN_NAME:-localhost}"

if [[ -f "$CERT" && -f "$KEY" ]]; then
    echo "Certs already exist at ${SSL_DIR}, skipping generation."
    exit 0
fi

mkdir -p "$SSL_DIR"

openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" \
    -out "$CERT" \
    -days 365 \
    -subj "/CN=${DOMAIN}" \
    -addext "subjectAltName=DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1"

echo "Self-signed cert generated:"
echo "  Certificate: ${CERT}"
echo "  Key:         ${KEY}"
