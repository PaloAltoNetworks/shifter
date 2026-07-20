# Built-image stack smoke (#922)

`stack_smoke.sh` boots the **production portal image** under its **real
`entrypoint.sh`** against local Postgres / Redis / ElasticMQ doubles and asserts
the runtime contracts the source-tree pytest estate cannot see. It is the same
class of regression the June-7 hotfix wave shipped live (portal home-directory,
worker container healthchecks): failures that only appear in the built artifact
under its real entrypoint, never in `pytest` against the source tree with test
settings.

It runs identically locally and on a hosted CI runner, with **no cloud
credentials**: the only AWS surface is a local ElasticMQ SQS double reached via
`AWS_ENDPOINT_URL` with dummy creds.

## What it asserts

1. **Image build**: the production `Dockerfile` (context `./shifter`) installs
   deps and runs `compilemessages` / `collectstatic` as the non-root `appuser`.
2. **Boot**: `entrypoint.sh` waits for the DB, runs migrations exactly once
   (a dedicated one-shot; every long-running container boots with
   `SKIP_MIGRATIONS=1`, mirroring `scripts/portal-deploy/deploy_portal.sh`), and
   execs the production Gunicorn/Uvicorn ASGI command as `appuser`.
3. **Readiness**: `/health/` returns 200 from the real dependency-aware
   `django-health-check` registry (DB + cache + storage + Redis channel layer).
4. **Real OIDC login** (`#988`): a real authorization-code flow against a local
   Cognito-shaped provider double drives `/login/` then `/oauth2/authorize` then
   `/oidc/callback/` through `mozilla_django_oidc` + `ShifterOIDCBackend`,
   provisions the first-login Django user + `UserProfile` (proved absent before
   the flow, then exactly one user + one profile bound to the verified
   `(issuer, subject)` after), and establishes the Django session reused by the
   checks below. A regression in OIDC config, the callback, first-login
   provisioning, or session establishment fails the smoke.
5. **Websocket**: an authenticated handshake completes through
   `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and a routed consumer
   (`ws/notifications/`), using the session established by the login flow above.
6. **Authenticated page renders**: the real dashboard / range / terminal /
   settings / help pages return 200 off the built image, and every local
   `/static/` asset they reference (plus any declared sourcemap) resolves,
   catching the missing-terminal-sourcemaps / static-asset regression class
   (`#923` TEST-3, range-independent subset). Range-dependent checks (live
   terminal data exchange, Guacamole) are out of scope.
7. **Workers**: the SQS worker and CTF scheduler boot from the same image and
   produce their `/tmp/<name>-heartbeat` files.

### Local OIDC provider double

Real login is exercised without any live identity provider (the blocking
Quality gate stays hosted and credential-free):

- `stub_idp.py`: a deterministic, fail-closed, Cognito-shaped OIDC provider
  double. It serves the exact endpoint shapes `config._oidc_settings` derives
  (`/oauth2/authorize`, `/oauth2/token`, `/oauth2/userInfo`,
  `/.well-known/jwks.json`), signs an RS256 ID token bound to the per-request
  `state`/`nonce`, and rejects the wrong client id/secret, a wrong/absent
  redirect URI, a reused code, or a missing bearer token. It runs under the
  built portal image's interpreter (reusing its in-image `PyJWT`/`cryptography`)
  and generates its keypair fresh at startup, with no committed private key.
- `oidc_login.py`: a browser-like login driver (cookie jar, manual redirect
  following) that walks `/login/`, authorize, and callback, then captures the
  callback-established session. It runs inside the smoke network so it reaches
  the portal and the IdP by name, and addresses the portal by its logical HTTPS
  origin (`Host` + `X-Forwarded-Proto: https`) over the private HTTP transport,
  so the secure-cookie / redirect-URI semantics stay real.

The captured session key is written to a mode-0600 file whose **path** (never
its value) is passed to `ws_handshake.py` / `page_smoke.py` via `--session-file`,
so no session/token material lands on any process's argv.

## Run it locally

```bash
# from the repo root; requires docker, uv, python3, curl
bash scripts/stack-smoke/stack_smoke.sh
```

The script creates a private docker network, tears everything down on exit
(including failures, after a bounded log tail), and exits non-zero on any failed
assertion.

## Parameters (extensibility seam)

All scalars are env-overridable; the worker/scheduler set is one list, so a new
variation is a parameter change rather than a copy of the workflow block.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SMOKE_IMAGE` | `shifter-portal:stack-smoke` | Image tag to build/run |
| `SMOKE_BUILD` | `1` | Build the image (`0` = reuse `SMOKE_IMAGE`) |
| `SMOKE_DOCKERFILE` | `shifter/shifter_platform/Dockerfile` | Dockerfile path |
| `SMOKE_CONTEXT` | `shifter` | Docker build context |
| `SMOKE_WEB_PORT` | `18000` | Host port mapped to the web container's 8000 |
| `SMOKE_HEALTH_PATH` | `/health/` | Readiness path to poll for 200 |
| `SMOKE_WS_PATH` | `ws/notifications/` | Routed websocket consumer path |
| `SMOKE_PAGES` | dashboard/range/terminal/settings/help | Space-separated authenticated page paths to render + asset-check |
| `SMOKE_BOOT_TIMEOUT` | `180` | Seconds to wait for readiness |
| `SMOKE_HEARTBEAT_TIMEOUT` | `120` | Seconds to wait for each heartbeat |
| `SMOKE_WORKER_SPECS` | cms worker + ctf-scheduler | `name\|heartbeat_file\|command` per line |
| `SMOKE_PG_IMAGE` / `SMOKE_REDIS_IMAGE` / `SMOKE_ELASTICMQ_IMAGE` | pinned | Dependency double images |
| `SMOKE_IDP_PORT` | `8080` | Port the local OIDC provider double listens on |

The OIDC login scenario is a single parameter set (client id/secret, issuer,
auth domain, callback, synthetic claims) on one provider double, so the next
variation (another fixture version or synthetic claim set) is a parameter
change rather than a second harness.

## CI

`.github/workflows/_quality.yml` runs this as the `stack-smoke` job, gated on the
`run_stack_smoke` input that `.github/workflows/deploy.yml` drives from the
existing `portal_image` / `shifter_platform` path filters, so engine-only or
docs-only changes never pay the image build.
