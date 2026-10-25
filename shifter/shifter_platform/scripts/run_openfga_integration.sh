#!/usr/bin/env bash
set -euo pipefail

OPENFGA_IMAGE="openfga/openfga@sha256:d53ce5c48413d01e75ecf375f3f74eb35c50f155fc028c41d03dbc7c9838fb38"
OPENFGA_CLI_IMAGE="openfga/cli@sha256:26acde96d90420e53fe361a740dcceba4b67f1c49e4f35117cd0c19c83ac5068"
POSTGRES_IMAGE="postgres@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685"
RUN_ID="openfga-integration-$$"
NETWORK_NAME="${RUN_ID}-network"
POSTGRES_NAME="${RUN_ID}-postgres"
SERVER_NAME="${RUN_ID}-server"
RUNTIME_SERVER_NAME="${RUN_ID}-runtime"
FIXTURE_DIR="$(mktemp -d)"
TOKEN="integration-only-preshared-key-0001"
ADMIN_TOKEN="integration-only-admin-key-0002"
DB_PASSWORD="integration-only-postgres-password"

cleanup() {
  docker rm -f "${RUNTIME_SERVER_NAME}" "${SERVER_NAME}" "${POSTGRES_NAME}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK_NAME}" >/dev/null 2>&1 || true
  rm -rf "${FIXTURE_DIR}"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout "${FIXTURE_DIR}/tls.key" \
  -out "${FIXTURE_DIR}/tls.crt" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
chmod 0755 "${FIXTURE_DIR}"
chmod 0644 "${FIXTURE_DIR}/tls.crt" "${FIXTURE_DIR}/tls.key"

docker network create "${NETWORK_NAME}" >/dev/null
docker run -d --name "${POSTGRES_NAME}" --network "${NETWORK_NAME}" \
  -p 127.0.0.1::5432 \
  -e POSTGRES_USER=openfga \
  -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
  -e POSTGRES_DB=openfga \
  "${POSTGRES_IMAGE}" >/dev/null

# The image's initialization server accepts Unix sockets only and then stops.
# Wait for TCP so that readiness cannot race that temporary server's shutdown.
for _ in $(seq 1 60); do
  if docker exec "${POSTGRES_NAME}" pg_isready -h 127.0.0.1 -U openfga -d openfga >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${POSTGRES_NAME}" pg_isready -h 127.0.0.1 -U openfga -d openfga >/dev/null
docker exec "${POSTGRES_NAME}" createdb -h 127.0.0.1 -U openfga shifter_integration

DATASTORE_URI="postgres://openfga:${DB_PASSWORD}@${POSTGRES_NAME}:5432/openfga?sslmode=disable"
docker run --rm --network "${NETWORK_NAME}" \
  -e OPENFGA_DATASTORE_ENGINE=postgres \
  -e OPENFGA_DATASTORE_URI="${DATASTORE_URI}" \
  "${OPENFGA_IMAGE}" migrate

# API administration and runtime get separate non-owner database duties.
docker exec -i "${POSTGRES_NAME}" psql -h 127.0.0.1 -U openfga -d openfga -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE integration_runtime LOGIN PASSWORD 'integration-only-runtime-password';
CREATE ROLE integration_admin LOGIN PASSWORD 'integration-only-admin-password';
SQL
docker exec -i "${POSTGRES_NAME}" psql -h 127.0.0.1 -U openfga -d openfga \
  -v runtime_login=integration_runtime -v admin_login=integration_admin \
  < ../../platform/charts/shifter/files/openfga-duties.sql
ADMIN_DATASTORE_URI="postgres://integration_admin:integration-only-admin-password@${POSTGRES_NAME}:5432/openfga?sslmode=disable"
docker run -d --name "${SERVER_NAME}" --network "${NETWORK_NAME}" \
  -p 127.0.0.1::8080 \
  -v "${FIXTURE_DIR}:/integration-tls:ro" \
  -e OPENFGA_DATASTORE_ENGINE=postgres \
  -e OPENFGA_DATASTORE_URI="${ADMIN_DATASTORE_URI}" \
  -e OPENFGA_AUTHN_METHOD=preshared \
  -e OPENFGA_AUTHN_PRESHARED_KEYS="${ADMIN_TOKEN}" \
  -e OPENFGA_HTTP_TLS_ENABLED=true \
  -e OPENFGA_HTTP_TLS_CERT=/integration-tls/tls.crt \
  -e OPENFGA_HTTP_TLS_KEY=/integration-tls/tls.key \
  -e OPENFGA_GRPC_ADDR=127.0.0.1:8081 \
  -e OPENFGA_PLAYGROUND_ENABLED=false \
  -e OPENFGA_PROFILER_ENABLED=false \
  "${OPENFGA_IMAGE}" run >/dev/null

SERVER_PORT="$(docker port "${SERVER_NAME}" 8080/tcp | sed -n 's/.*://p')"
POSTGRES_PORT="$(docker port "${POSTGRES_NAME}" 5432/tcp | sed -n 's/.*://p')"
API_URL="https://localhost:${SERVER_PORT}"
ADMIN_API_URL="${API_URL}"
for _ in $(seq 1 60); do
  if curl --silent --fail --cacert "${FIXTURE_DIR}/tls.crt" "${API_URL}/healthz" >/dev/null; then
    break
  fi
  sleep 1
done

STORE_RESPONSE="$(curl --silent --fail --cacert "${FIXTURE_DIR}/tls.crt" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name":"shifter-integration"}' \
  "${API_URL}/stores")"
STORE_ID="$(printf '%s' "${STORE_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
# CI prepares the frozen environment before this harness. Execution must not
# resolve dependencies or build source distributions as a side effect.
MODEL_DSL="$(TESTING=1 ENVIRONMENT=test uv run --no-build --no-sync python manage.py render_openfga_model)"
MODEL_RESPONSE="$(docker run --rm "${OPENFGA_CLI_IMAGE}" model transform "${MODEL_DSL}" \
  --input-format fga --output-format json | curl --silent --fail --cacert "${FIXTURE_DIR}/tls.crt" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary @- \
  "${API_URL}/stores/${STORE_ID}/authorization-models")"
MODEL_ID="$(printf '%s' "${MODEL_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["authorization_model_id"])')"

# The real PostgreSQL permissions, not the application SDK, deny administration.
RUNTIME_DATASTORE_URI="postgres://integration_runtime:integration-only-runtime-password@${POSTGRES_NAME}:5432/openfga?sslmode=disable"
docker run -d --name "${RUNTIME_SERVER_NAME}" --network "${NETWORK_NAME}" \
  -p 127.0.0.1::8080 \
  -v "${FIXTURE_DIR}:/integration-tls:ro" \
  -e OPENFGA_DATASTORE_ENGINE=postgres \
  -e OPENFGA_DATASTORE_URI="${RUNTIME_DATASTORE_URI}" \
  -e OPENFGA_AUTHN_METHOD=preshared \
  -e OPENFGA_AUTHN_PRESHARED_KEYS="${TOKEN}" \
  -e OPENFGA_HTTP_TLS_ENABLED=true \
  -e OPENFGA_HTTP_TLS_CERT=/integration-tls/tls.crt \
  -e OPENFGA_HTTP_TLS_KEY=/integration-tls/tls.key \
  -e OPENFGA_GRPC_ADDR=127.0.0.1:8081 \
  -e OPENFGA_PLAYGROUND_ENABLED=false \
  -e OPENFGA_PROFILER_ENABLED=false \
  "${OPENFGA_IMAGE}" run >/dev/null
RUNTIME_SERVER_PORT="$(docker port "${RUNTIME_SERVER_NAME}" 8080/tcp | sed -n 's/.*://p')"
API_URL="https://localhost:${RUNTIME_SERVER_PORT}"
for _ in $(seq 1 60); do
  if curl --silent --fail --cacert "${FIXTURE_DIR}/tls.crt" "${API_URL}/healthz" >/dev/null; then
    break
  fi
  sleep 1
done
curl --silent --fail --cacert "${FIXTURE_DIR}/tls.crt" "${API_URL}/healthz" >/dev/null

TESTING=1 \
ENVIRONMENT=test \
TEST_DB_BACKEND=postgres \
DB_NAME=shifter_integration \
DB_USER=openfga \
DB_PASSWORD="${DB_PASSWORD}" \
DB_HOST=127.0.0.1 \
DB_PORT="${POSTGRES_PORT}" \
OPENFGA_INTEGRATION_URL="${API_URL}" \
OPENFGA_INTEGRATION_ADMIN_URL="${ADMIN_API_URL}" \
OPENFGA_INTEGRATION_ADMIN_TOKEN="${ADMIN_TOKEN}" \
OPENFGA_INTEGRATION_POSTGRES_CONTAINER="${POSTGRES_NAME}" \
OPENFGA_INTEGRATION_STORE_ID="${STORE_ID}" \
OPENFGA_INTEGRATION_MODEL_ID="${MODEL_ID}" \
OPENFGA_INTEGRATION_TOKEN="${TOKEN}" \
OPENFGA_INTEGRATION_CA_CERT="${FIXTURE_DIR}/tls.crt" \
OPENFGA_INTEGRATION_REQUIRED=1 \
uv run --no-build --no-sync pytest -n0 -q \
  tests/integration/authorization/test_openfga_released_server.py \
  tests/integration/authorization/test_gcp_native_database_duties.py "$@"
