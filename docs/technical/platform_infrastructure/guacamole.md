# Guacamole Remote-Desktop Integration

Apache Guacamole provides browser-based RDP and SSH access to range instances and
to NGFW management terminals. The Portal mints short-lived, signed Guacamole
sessions on demand using the Guacamole JSON-auth extension, so no connection is
ever pre-provisioned in the Guacamole database.

This document is the canonical reference for the subsystem. The point-in-time
design notes under `docs/architecture/guacamole-*-preflight-*.md` record the
decisions that produced the current behaviour:

- `docs/architecture/guacamole-first-click-rdp-preflight-395.md` (token-readiness retry)
- `docs/architecture/guacamole-token-affinity-preflight-928.md` (single client replica)
- `docs/architecture/guacamole-token-lifecycle-preflight-939.md` (at-rest token lifecycle)

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Platform Network                                 │
│  ┌───────────┐    ┌────────────────┐    ┌─────────────────────────────────┐  │
│  │           │    │                │    │      Guacamole Services         │  │
│  │   Load    │───▶│    Portal      │    │  ┌───────────────────────────┐  │  │
│  │  Balancer │    │    Django      │───▶│  │  guacamole-client (8080)  │  │  │
│  │           │    │  (+ bootstrap  │    │  │  - JSON Auth Extension    │  │  │
│  │ /guacamole│───▶│    workers)    │    │  └───────────┬───────────────┘  │  │
│  │    path   │    │                │    │              │ port 4822        │  │
│  └───────────┘    └───────┬────────┘    │  ┌───────────▼───────────────┐  │  │
│                           │             │  │     guacd (4822)          │  │  │
│       ┌─────────────────┐ │             │  │  - Protocol translation   │  │  │
│       │  Secret Store   │ │             │  │  - RDP/SSH/VNC client     │  │  │
│       │ - JSON_SECRET   │◀┘             │  └───────────┬───────────────┘  │  │
│       │ - DB_CREDS      │               └──────────────┼──────────────────┘  │
│       └─────────────────┘                              │                     │
│       ┌─────────────────┐    ┌─────────────────┐       │                     │
│       │  Portal/App DB  │    │  Guacamole DB   │◀──────┘                     │
│       │ (bootstrap rows)│    │ (session state) │                            │
│       └─────────────────┘    └─────────────────┘                            │
└───────────────────────────────────────────────────────────┼──────────────────┘
                                                             │ Network peering
┌────────────────────────────────────────────────────────────┼──────────────────┐
│                           Range Network                     ▼                  │
│        ┌──────────────────────────────────────────────────────┐               │
│        │  Range instances: RDP 3389 / SSH 22 (Kali, Windows,   │               │
│        │  Ubuntu, victim hosts) reached by guacd on private IP │               │
│        └──────────────────────────────────────────────────────┘               │
└────────────────────────────────────────────────────────────────────────────────┘
```

On AWS, `guacd` and `guacamole-client` run as ECS Fargate services with an RDS
PostgreSQL backend; the Portal and the bootstrap prune worker run on EC2. On GCP,
all of them run as Kubernetes Deployments with Cloud SQL. The Django integration
and JSON-auth flow are identical on both clouds.

## Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **guacamole-client** | ECS service (AWS) / K8s Deployment (GCP) | HTML5 web app; hosts the JSON-auth extension and serves `/guacamole`. |
| **guacd** | ECS service (AWS) / K8s Deployment (GCP) | Protocol proxy; translates the Guacamole protocol to RDP/SSH/VNC and dials the range host. |
| **Guacamole PostgreSQL** | RDS (AWS) / Cloud SQL (GCP) | Guacamole session and connection state. |
| **Token broker** | Portal Django, `mission_control/guacamole.py` | Signs the JSON-auth payload, exchanges it at `/api/tokens`, builds the client URL. |
| **Bootstrap runner** | Portal Django, `mission_control/guacamole_bootstrap.py` | Bounded worker pool that runs the blocking token exchange off the request thread and persists a pollable result. |
| **Bootstrap prune worker** | `manage.py run_guacamole_bootstrap_prune` | Dedicated service that deletes expired bootstrap rows on a schedule. |
| **`GuacamoleBootstrapRequest`** | Portal/App DB, `mission_control/models.py` | Pollable per-request state; holds the token-bearing URL only between mint and first delivery. |

## Request flow

The Portal never returns the token URL directly from the launch request. Building
a Guacamole session requires a blocking server-to-server call to
`guacamole-client` `/api/tokens`, so that work runs asynchronously in a bounded
worker pool and the browser polls for the result.

```
Browser                         Portal Django                     guacamole-client
   │                                  │                                  │
   │ 1. POST /api/guacamole/rdp-url/  │                                  │
   │    {instance_uuid}  + CSRF       │                                  │
   │─────────────────────────────────▶│                                  │
   │                                  │ 2. authn, resolve range via      │
   │                                  │    engine.services, enqueue a    │
   │                                  │    GuacamoleBootstrapRequest      │
   │ 3. 202 {request_id, status,      │                                  │
   │    status_url, url}              │                                  │
   │◀─────────────────────────────────│                                  │
   │                                  │ 4. worker builds the signed      │
   │                                  │    payload, POSTs /api/tokens ───▶│
   │                                  │    receives authToken, stores    │
   │                                  │    result_url on the row         │
   │ 5. GET status_url (poll, 1s)     │                                  │
   │─────────────────────────────────▶│                                  │
   │ 6. 200 {url: ".../#/client/...?token=..."}  (once)                   │
   │◀─────────────────────────────────│  result_url cleared on delivery  │
   │                                  │                                  │
   │ 7. open url ─────────────────────────────────────────────────────▶ guacamole-client
   │    WebSocket tunnel ───▶ guacd ───▶ range host (RDP 3389 / SSH 22)   │
```

Key points:

- **Launch request body is `{instance_uuid}`** for RDP and range SSH; the NGFW
  SSH route takes the application id in the path. There is no `instance_type`
  field.
- **The launch response is `202 Accepted`** with `{request_id, status,
  status_url, url}`, a `Location` header set to `status_url`, and `Retry-After:
  1`. The `url` field is a compatibility opener page (see Frontend), not the
  token URL.
- **The token URL is delivered by the status endpoint, exactly once** (see Token
  lifecycle). The final URL has the form
  `{GUACAMOLE_BASE_URL}/#/client/{connection_id}?token={authToken}`, where
  `connection_id` is `base64(connection_name + "\0c\0json")` with padding
  stripped.
- **Capacity is bounded.** If every worker slot is busy the launch returns `503`
  with `Retry-After: 1`.

## Token broker (`mission_control/guacamole.py`)

The broker implements the Guacamole JSON-auth extension protocol.

1. **Build the payload.** `create_guacamole_auth_payload(username, connections,
   expires_minutes=5)` returns `{"username", "expires", "connections"}`, where
   `expires` is a millisecond Unix timestamp `expires_minutes` in the future. The
   default token validity is 5 minutes.
2. **Sign and encrypt.** `sign_and_encrypt_payload(payload, secret_key)`:
   - reads `secret_key` as hex; the key must be 16, 24, or 32 bytes (32, 48, or
     64 hex characters), selecting AES-128/192/256. A 64-hex (256-bit) key is the
     configured preference.
   - `signature = HMAC-SHA256(key, json_bytes)`,
   - `signed = signature || json_bytes`, PKCS7-padded to the AES block size,
   - `AES-CBC(key, IV = 0x00 * 16, signed)`, then Base64.

   The signature is prepended to the plaintext and the whole thing is encrypted;
   the guacamole-client JSON-auth extension reverses this with the shared key.
3. **Exchange for a token.** `get_guacamole_auth_token(api_base_url,
   encrypted_data)` POSTs `data=<encrypted>` (form-encoded) to
   `{api_base_url}/api/tokens` and returns `authToken` from the JSON response.
   This call uses the **internal** API URL. It retries on transient failures
   (HTTP 408/429/502/503/504 and connection errors) with exponential backoff
   governed by `GUACAMOLE_TOKEN_RETRY_ATTEMPTS` and
   `GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS`; malformed responses are fatal. The
   retry exists for first-click reliability (issue #395).
4. **Build the client URL.** `create_guacamole_rdp_url` and
   `create_guacamole_ssh_url` assemble the connection map, sign/encrypt, exchange
   for `authToken`, and return
   `{public_base_url}/#/client/{connection_id}?token={authToken}` using the
   **public** base URL for the browser.

The public/internal split matters: `GUACAMOLE_API_BASE_URL` is the
server-to-server address used to mint the token, while `GUACAMOLE_BASE_URL` is the
browser-facing path baked into the returned URL.

## Async bootstrap (`mission_control/guacamole_bootstrap.py`)

The token exchange is blocking, so it runs off the request thread:

- **Worker pool.** A process-local `ThreadPoolExecutor` plus a `BoundedSemaphore`
  cap concurrent exchanges at `GUACAMOLE_BOOTSTRAP_WORKERS` (default 4). A launch
  that cannot acquire a slot raises `BootstrapQueueFull`, surfaced as `503`.
- **Enqueue.** `enqueue_guacamole_bootstrap` creates a `PENDING`
  `GuacamoleBootstrapRequest` with `expires_at = now + GUACAMOLE_BOOTSTRAP_TTL_SECONDS`
  (default 300, floor 30) and submits `_run_bootstrap`.
- **Inline mode.** With `GUACAMOLE_BOOTSTRAP_INLINE` true the exchange runs
  synchronously in-request. This is used by tests and single-threaded contexts.
- **Worker.** `_run_bootstrap` marks the row `RUNNING`, calls the per-protocol
  `build_url` callable, and on success stores `result_url` and `SUCCEEDED`. A
  build that raises records a `FAILED` row with a sanitised error and HTTP-ish
  status. A build that finishes after `expires_at` records expiry and **does not
  persist a token URL** (see Token lifecycle).

The polling endpoints live in `mission_control/views/_guacamole_bootstrap.py`:

- `GET api/guacamole/bootstrap/<request_id>/` returns the current state, owner-scoped
  by `request_id + user_id`. `PENDING`/`RUNNING` return `Retry-After: 1`;
  `FAILED` returns the recorded status and message; `SUCCEEDED` delivers the URL
  once (then `410` on any later poll); an expired row returns `410`.
- `GET api/guacamole/bootstrap/<request_id>/open/` serves a small HTML opener page
  that polls the status endpoint and redirects when the URL is ready, for clients
  that consume the opener `url` directly.

## Token lifecycle and at-rest security (issue #939)

`result_url` carries the Guacamole `authToken`, so a database row is a live
credential for the token's remaining validity. The subsystem holds that material
at rest for the minimum possible window:

1. **Single-use delivery.** `consume_ready_url` runs inside a `select_for_update`
   transaction: the first owner-scoped status poll that finds a ready URL returns
   it, sets `delivered_at`, and clears `result_url` in the same transaction. A
   second poll (a second tab, the opener plus the JS client, a retry) gets a
   `410` and never the token again. `succeeded` keeps meaning "ready to deliver";
   the separate `delivered_at` marker records that delivery happened, so lifecycle
   state is never inferred from a blanked secret column.
2. **No persist after expiry.** If a slow build finishes after `expires_at`, the
   worker records the expiry and never writes `result_url`. The expired-poll path
   also clears any URL still parked on a `succeeded` row.
3. **Scheduled pruning.** `run_guacamole_bootstrap_prune` deletes rows with
   `expires_at <= now` in bounded, oldest-first batches. This is the backstop for
   `succeeded`-but-abandoned rows (built, never polled) and bounds table growth.
   Pruning is the eventual cleanup; clearing on delivery is the immediate control.

Encryption at rest was considered and deliberately not added: clearing on
delivery plus no-persist-after-expiry plus pruning shrink the at-rest window to,
at most, the sub-TTL gap between a successful mint and the first poll. An
encrypted-but-undeleted row would still be a durable credential escrow.

## Persistence model (`GuacamoleBootstrapRequest`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `user_id` | big int, indexed | Owner; every read is scoped by it. |
| `protocol` | choice | `rdp`, `range_ssh`, `ngfw_ssh`. |
| `target_id` | char(200) | Instance UUID or NGFW app id. |
| `status` | choice, indexed | `pending`, `running`, `succeeded`, `failed`. |
| `result_url` | text | Token-bearing URL; secret; cleared on delivery. |
| `error_message` / `error_status_code` | char / small int | Sanitised failure detail. |
| `duration_ms` | int, nullable | Build duration. |
| `created_at` / `updated_at` | datetime | Auto. |
| `expires_at` | datetime, indexed | `created_at + TTL`; drives the prune. |
| `delivered_at` | datetime, nullable | Set once on single-use delivery. |

Indexes: `(user_id, created_at)` for owner polling and `(status, expires_at)` for
the prune query. The `is_expired` property is `expires_at <= now`.

## Frontend

`static/js/terminal-guacamole.js` drives the terminal page. It reads
`{rdpUrl, sshUrl, csrfToken}` from a `json_script` block, POSTs `{instance_uuid}`
with the CSRF token to the launch endpoint, then polls `status_url` once per
second (up to 60 attempts) until it sees `data.url`, and opens the result in a new
tab (with a same-tab fallback when the popup is blocked). It stops polling on the
first delivered URL, so single-use delivery is transparent to the happy path.

The CTF participant page (`templates/ctf/participant/range.html`) uses an older
inline launcher that consumes the `url` field from the launch response directly
(the opener page) rather than running the status-polling loop. Both paths funnel
through the same status endpoint as the delivery boundary.

## Settings

Guacamole settings live in `config/_guacamole_settings.py` (re-exported by
`config/settings.py` to keep that module under the 500-line cap); the two retry
knobs live in `config/settings.py`.

| Setting | Default | Controls |
|---------|---------|----------|
| `GUACAMOLE_JSON_AUTH_SECRET` | `""` | Hex HMAC/AES key; must equal guacamole-client `JSON_SECRET_KEY`. Empty means the feature returns `503`. |
| `GUACAMOLE_BASE_URL` | `/guacamole` | Public browser base for the `#/client/...` URL. |
| `GUACAMOLE_API_BASE_URL` | falls back to `GUACAMOLE_BASE_URL` | Internal `/api/tokens` address. |
| `GUACAMOLE_BOOTSTRAP_WORKERS` | `4` | Per-process bounded worker/semaphore count. |
| `GUACAMOLE_BOOTSTRAP_TTL_SECONDS` | `300` | Bootstrap row lifetime (floor 30). |
| `GUACAMOLE_BOOTSTRAP_INLINE` | `False` | Run the exchange synchronously in-request. |
| `GUACAMOLE_BOOTSTRAP_PRUNE_INTERVAL_SECONDS` | `60` | Prune cadence. |
| `GUACAMOLE_BOOTSTRAP_PRUNE_BATCH_SIZE` | `500` | Bounded prune batch size. |
| `GUACAMOLE_TOKEN_RETRY_ATTEMPTS` | `3` | `/api/tokens` retry attempts. |
| `GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS` | `200` | `/api/tokens` backoff base. |

## Deployment topology

`guacd` and `guacamole-client` are pinned to a single `guacamole-client` replica
so the in-memory token minted by `/api/tokens` is consumed by the same instance
that issued it (issue #928); `guacd` scales independently. This is enforced by
`tests/platform/test_guacamole_topology.py`.

### AWS

- `guacd` and `guacamole-client` run on ECS Fargate (`platform/terraform/modules/guacamole/`).
  The client task's `desired_count` is hard-pinned to 1 with a validation block;
  client autoscaling is removed; only `guacd` autoscales.
- The ALB path-routes `/guacamole` to guacamole-client (8080) and everything else
  to the Portal.
- `JSON_SECRET_KEY` is injected from Secrets Manager into the client task; the
  Portal reads the same value via `GUACAMOLE_JSON_AUTH_SECRET`.
- The Portal and the `guacamole-bootstrap-prune` container run on EC2; the prune
  container is launched from `platform/terraform/modules/portal/ec2/user_data.sh`
  (and the SSM redeploy path `scripts/portal-deploy/deploy_portal.sh`) and is
  supervised by the worker-health agent.

### GCP

- `guacd`, `guacamole-client`, and `guacamole-bootstrap-prune` are Kubernetes
  Deployments (Helm chart `platform/charts/shifter/templates/` and the kustomize
  base `platform/k8s/gcp/base/`). `guacamoleClient.replicas` is 1.
- `JSON_SECRET_KEY` and DB credentials reach the client via the
  `guacamole-runtime` Kubernetes Secret. That Secret is created **out of band**
  by the deploy bootstrap (`kubectl apply` from GCP Secret Manager, before the
  Helm release). The Helm chart never carries the secret values; it references
  the Secret by name only (`envFrom.secretRef`), so credentials never enter
  chart values or Helm release history. `scripts/gcp/render_runtime_env.py` sets
  `GUACAMOLE_SECRET_ID`, `GUACAMOLE_BASE_URL`, and the in-cluster
  `GUACAMOLE_API_BASE_URL`.
- NetworkPolicies restrict `guacamole-client` to `guacd` on TCP 4822 and admit
  GCLB ingress to the portal and guacamole-client backends on 8000/8080.

### Local

`docker-compose.yml` runs the `guacamole-bootstrap-prune` worker (the Django
broker logic is identical across clouds); `guacd` and `guacamole-client` are
exercised through the AWS or GCP stacks.

### Secret injection

The Portal entrypoint (`entrypoint.sh`) resolves `GUACAMOLE_SECRET_ID` /
`GUACAMOLE_SECRET_ARN` and exports `GUACAMOLE_JSON_AUTH_SECRET` from the secret
store, failing closed if the fetch fails. The guacamole-client container receives
the same key as `JSON_SECRET_KEY`. The two values must match, or every signature
fails validation.

## Configuration reference

### guacamole-client container

| Variable | Source | Notes |
|----------|--------|-------|
| `GUACD_HOSTNAME` / `GUACD_PORT` | deployment | `guacd` service / `4822`. |
| `POSTGRESQL_HOSTNAME` / `PORT` / `DATABASE` | runtime config | Guacamole DB. |
| `POSTGRESQL_USER` / `PASSWORD` | secret store | Guacamole DB creds. |
| `POSTGRESQL_AUTO_CREATE_ACCOUNTS` | deployment | `true`. |
| `JSON_ENABLED` / `OPENID_ENABLED` | deployment | `true` / `false`. |
| `JSON_SECRET_KEY` | secret store | Must equal `GUACAMOLE_JSON_AUTH_SECRET`. |

### Secrets

| Secret name pattern | Purpose |
|---------------------|---------|
| `shifter-{env}-guacamole-db` | Guacamole PostgreSQL credentials. |
| `shifter-{env}-guacamole-json-auth` | JSON-auth signing key. |

## Code references

| Area | Path |
|------|------|
| Token broker (crypto, `/api/tokens`, URL) | `shifter/shifter_platform/mission_control/guacamole.py` |
| Launch endpoints (RDP / range SSH / NGFW SSH) | `shifter/shifter_platform/mission_control/views/_guacamole.py`, `views/_guacamole_builders.py` |
| Async bootstrap + token lifecycle | `shifter/shifter_platform/mission_control/guacamole_bootstrap.py` |
| Polling endpoints | `shifter/shifter_platform/mission_control/views/_guacamole_bootstrap.py` |
| Persistence model | `shifter/shifter_platform/mission_control/models.py` |
| Prune service | `shifter/shifter_platform/mission_control/management/commands/run_guacamole_bootstrap_prune.py` |
| URL routes | `shifter/shifter_platform/mission_control/urls.py` |
| Settings | `shifter/shifter_platform/config/_guacamole_settings.py` |
| Frontend | `shifter/shifter_platform/static/js/terminal-guacamole.js` |
| AWS infra | `platform/terraform/modules/guacamole/` |
| GCP infra | `platform/charts/shifter/templates/guac*`, `platform/k8s/gcp/base/guac*` |
| Topology invariant test | `shifter/shifter_platform/tests/platform/test_guacamole_topology.py` |

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---------|--------------|------------|
| Launch returns `503` | All bootstrap worker slots busy, or `GUACAMOLE_JSON_AUTH_SECRET` unset | Retry after the `Retry-After` interval; verify the Portal secret. |
| Status poll returns `410` "no longer available" | The URL was already delivered (single-use) | Launch again; the first reader consumes the token. |
| Status poll returns `410` "expired" | Polled after the bootstrap TTL | Launch again. |
| "Invalid signature" in guacamole-client logs | Key mismatch | Ensure `JSON_SECRET_KEY` equals `GUACAMOLE_JSON_AUTH_SECRET`. |
| Connection timeout after the client opens | guacd cannot reach the range host | Verify peering and the range RDP/SSH ingress rules. |
| No RDP button | Instance has no GUI (`os_type == "ubuntu"`) | Expected; use SSH. |
</content>
