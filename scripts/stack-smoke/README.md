# Built-image stack smoke (#922)

`stack_smoke.sh` boots the **production portal image** under its **real
`entrypoint.sh`** against local Postgres / Redis / ElasticMQ doubles and asserts
the runtime contracts the source-tree pytest estate cannot see. It is the same
class of regression the June-7 hotfix wave shipped live (portal home-directory,
worker container healthchecks): failures that only appear in the built artifact
under its real entrypoint, never in `pytest` against the source tree with test
settings.

It runs identically locally and on a hosted CI runner, with **no cloud
credentials** — the only AWS surface is a local ElasticMQ SQS double reached via
`AWS_ENDPOINT_URL` with dummy creds.

## What it asserts

1. **Image build** — the production `Dockerfile` (context `./shifter`) installs
   deps and runs `compilemessages` / `collectstatic` as the non-root `appuser`.
2. **Boot** — `entrypoint.sh` waits for the DB, runs migrations exactly once
   (a dedicated one-shot; every long-running container boots with
   `SKIP_MIGRATIONS=1`, mirroring `scripts/portal-deploy/deploy_portal.sh`), and
   execs the production Gunicorn/Uvicorn ASGI command as `appuser`.
3. **Readiness** — `/health/` returns 200 from the real dependency-aware
   `django-health-check` registry (DB + cache + storage + Redis channel layer).
4. **Websocket** — an authenticated handshake completes through
   `AllowedHostsOriginValidator` → `AuthMiddlewareStack` → a routed consumer
   (`ws/notifications/`), using a throwaway session in the smoke database.
5. **Workers** — the SQS worker and CTF scheduler boot from the same image and
   produce their `/tmp/<name>-heartbeat` files.

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
| `SMOKE_BOOT_TIMEOUT` | `180` | Seconds to wait for readiness |
| `SMOKE_HEARTBEAT_TIMEOUT` | `120` | Seconds to wait for each heartbeat |
| `SMOKE_WORKER_SPECS` | cms worker + ctf-scheduler | `name\|heartbeat_file\|command` per line |
| `SMOKE_PG_IMAGE` / `SMOKE_REDIS_IMAGE` / `SMOKE_ELASTICMQ_IMAGE` | pinned | Dependency double images |

## CI

`.github/workflows/_quality.yml` runs this as the `stack-smoke` job, gated on the
`run_stack_smoke` input that `.github/workflows/deploy.yml` drives from the
existing `portal_image` / `shifter_platform` path filters — so engine-only or
docs-only changes never pay the image build.
