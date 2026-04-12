#!/bin/bash
# Quick flag submission to CTFd
# Usage: ./flag_submit.sh FLAG{hex_string}
#
# Requires CTFD_URL and CTFD_TOKEN environment variables

CTFD_URL="${CTFD_URL:-http://ctfd.northstorm.local}"
CTFD_TOKEN="${CTFD_TOKEN:-}"

if [ -z "$1" ]; then
    echo "Usage: $0 FLAG{...}"
    echo ""
    echo "Submit a flag to the CTFd scoreboard."
    echo "Set CTFD_URL and CTFD_TOKEN environment variables."
    exit 1
fi

FLAG="$1"

if [ -z "$CTFD_TOKEN" ]; then
    echo "Error: CTFD_TOKEN not set."
    echo "Set it with: export CTFD_TOKEN=your_token_here"
    exit 1
fi

echo "Submitting: $FLAG"
RESPONSE=$(curl -sf -X POST "${CTFD_URL}/api/v1/challenges/attempt" \
    -H "Authorization: Token ${CTFD_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"submission\": \"${FLAG}\"}" 2>&1)

if echo "$RESPONSE" | grep -q "correct"; then
    echo "CORRECT! Flag accepted."
elif echo "$RESPONSE" | grep -q "already_solved"; then
    echo "Already solved. Flag was previously submitted."
elif echo "$RESPONSE" | grep -q "incorrect"; then
    echo "INCORRECT. Flag not recognized."
else
    echo "Response: $RESPONSE"
fi
