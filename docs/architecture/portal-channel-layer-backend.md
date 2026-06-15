# Portal Channel-Layer Backend Posture

Status: accepted (ADR-018)

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/849>

## Decision

The portal's Django Channels backend is selected by an **explicit, environment-owned
posture**, decoupled from the portal autoscaling topology.

- `enable_autoscaling` is **compute topology only** (single EC2 vs. Auto Scaling
  Group). It does not decide whether Django Channels uses Redis.
- A single Terraform knob, `enable_redis`, owns Redis wiring per environment. It is
  independent of `enable_autoscaling`: a single-instance dev portal may use Redis,
  and an environment may disable Redis to save cost without changing ASG posture.
- The Django runtime reads one contract, `CHANNEL_LAYER_BACKEND` ∈ {`in_memory`,
  `redis`}. A `redis` posture **requires** `REDIS_HOST` and **fails closed**
  (`ImproperlyConfigured`) when it is absent, instead of silently degrading to the
  in-memory layer.

The Redis ElastiCache resource is always provisioned by the portal Terraform; the
`enable_redis` knob governs whether it is *wired into the runtime*, not whether it
exists. A provisioned-but-unused Redis is a legitimate (cost) posture — but it must
not be silent.

## Why

Previously the Redis endpoint reached the portal only when `enable_autoscaling` was
true: the endpoint was written to SSM and injected as `REDIS_HOST` only in ASG mode,
and Django fell back to `InMemoryChannelLayer` whenever `REDIS_HOST` was absent. In
toned-down dev (`enable_autoscaling = false`) the portal therefore ran on the
in-memory channel layer even though Redis was provisioned, and the websocket fan-out
behavior was not representative of an event-shaped deployment. Toggling ASG silently
changed the channel-layer backend. See `aws-portal-redis-channel-layer-preflight-849.md`.

## Contract

| Layer | Knob | Values | Default (dev / prod) |
| --- | --- | --- | --- |
| Terraform (environment-owned) | `var.enable_redis` | `true` / `false` | `false` / `true` |
| SSM parameter | `<prefix>/channel-layer-backend` | `redis` / `in_memory` (always written) | derived from `enable_redis` |
| SSM parameter | `<prefix>/redis-endpoint` | endpoint (written only when `enable_redis`) | — |
| Container env | `CHANNEL_LAYER_BACKEND` | `redis` / `in_memory` | from SSM |
| Container env | `REDIS_HOST` | endpoint (set only when present) | from SSM |

Runtime resolution lives in `shifter/shifter_platform/config/_channels.py`
(`_resolve_backend`):

- `CHANNEL_LAYER_BACKEND=redis` → Redis layer; missing `REDIS_HOST` fails closed.
- `CHANNEL_LAYER_BACKEND=in_memory` → in-memory layer, even if a stray `REDIS_HOST`
  is present (the drift is reported by the startup posture log, not acted on).
- unset → legacy `REDIS_HOST`-presence heuristic, preserved for local dev / pytest.

The `channel-layer-backend` SSM parameter is written with a non-empty value
regardless of `enable_redis`, and independently of whether the `redis-endpoint`
write succeeded. That independence is what makes the fail-closed meaningful: a
`redis` posture whose endpoint never arrived stops the portal at startup rather
than letting it serve on a silent in-memory layer.

Defaults preserve current effective behavior — dev stays in-memory, prod stays on
Redis — but the choice is now explicit, observable, and decoupled from ASG.

## Observability

The portal logs its active channel-layer backend once per process at ASGI startup
(`config/asgi.py` → `log_channel_layer_posture`). The record is non-secret: it
carries `backend`, `explicit_backend`, `redis_host_present`, `redis_port`, and
`redis_tls`, but never the hostname, password, CA, or a connection URL.

```text
channel-layer posture: backend=redis explicit_backend=redis redis_host_present=True redis_port=6379 redis_tls=False
```

## Operating

- **Run dev on Redis** (event-representative websocket behavior): set
  `enable_redis = true` in `platform/terraform/environments/dev/portal/terraform.tfvars`
  and apply. No change to `enable_autoscaling` is needed.
- **Disable Redis in an environment** to save cost: set `enable_redis = false`. The
  portal runs `CHANNEL_LAYER_BACKEND=in_memory`; the ElastiCache resource remains
  provisioned (its lifecycle is separate) but is not wired into the runtime.
- **Confirm the running posture**: read the portal startup log (ECS JSON) for the
  `channel-layer posture` line.

## Out of scope

AWS ElastiCache AUTH/TLS hardening is not part of this contract. The TLS path
(`REDIS_TLS` / `REDIS_PASSWORD` / `REDIS_CA_PEM`, ADR-008-R6) is unchanged; if AWS
Redis later needs auth/TLS, follow the GCP Memorystore secret-hydration precedent in
`gcp-redis-auth-tls-preflight.md` rather than putting auth material in SSM, Docker
env literals, logs, or URLs.
