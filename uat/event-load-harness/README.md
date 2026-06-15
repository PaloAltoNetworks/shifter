# Event Load Harness (#926)

A scripted, repeatable load harness that drives a **deployed** Shifter portal
over its real HTTP and websocket contracts, measures client-side latency, error,
and websocket close-code evidence, and renders a sanitized concurrency-envelope
report.

It exists to replace the *analytical* capacity envelope in
`docs/architecture/terminal-websocket-capacity-847.md` with *measured* numbers,
and to produce the evidence #846 needs to establish the event baseline and #910
needs to size the portal. Design constraints are recorded in
`docs/architecture/event-load-harness-preflight-926.md`.

A sample of the output is committed at
[`sample-envelope-report.md`](sample-envelope-report.md) (illustrative
placeholder numbers, not a real run).

## Design

The load-generation core is platform-agnostic: it targets the application's
HTTP/websocket endpoints, which are identical whether the portal runs on AWS
EC2, OpenShift, or GKE. Provider-metrics collection is an optional, swappable
adapter behind `event_load_harness.metrics.base.MetricsAdapter`, so a platform
change replaces one adapter rather than the harness.

```
cli.py        one-command entrypoint: orchestrates load -> metrics -> report
config.py     validated run config (https-only, prod refusal, bounds)
profiles.py   named traffic mixes + the route catalog (active vs deferred)
auth.py       actor sources: 0600 manifest, dev-login generator, ctfd-csv (deferred)
auth_http.py  live authenticator (replays the real session flow)
routes.py     route->endpoint contract + the live executor
runner.py     async virtual-user orchestration (ramp, concurrency, duration)
stats.py      per-route p50/p95/p99, error and websocket close-code distributions
report.py     sanitized envelope renderer + heuristic conclusion
metrics/      client-only (default) and aws (thin plug) adapters
```

It does **not** import the Shifter Django application. It runs as an external
client, so it stays runnable without the app installed.

## Install

```sh
cd uat/event-load-harness
uv sync                # core (httpx, websockets)
uv sync --extra aws    # add boto3 for the AWS metrics adapter
```

## Run

One command produces the report. Provide config via flags or a TOML file (flags
override the file):

```sh
uv run event-load-harness \
  --target-url https://<deployed-dev-host> \
  --confirm-host <deployed-dev-host> \
  --environment dev \
  --profile portal-core \
  --concurrency 150 --ramp-seconds 60 --duration-seconds 600 \
  --actor-source manifest --actor-manifest ./actors.toml \
  --metric-source client-only \
  --report-path out/envelope.md
```

`--confirm-host` must match the target URL host. It is a deliberate per-run
acknowledgment of exactly which host you are about to load, so an unintended
target (a mislabeled production host, a copy-pasted URL) is refused rather than
hit by accident. Use `--allow-production` instead for an intended production
target, or `--allow-insecure-localhost` for an `http://localhost` tunnel.

Equivalent `run.toml`:

```toml
target_url = "https://<deployed-dev-host>"
environment = "dev"
profile = "portal-core"
concurrency = 150
ramp_seconds = 60
duration_seconds = 600
actor_source = "manifest"
actor_manifest_path = "actors.toml"
metric_source = "client-only"
report_path = "out/envelope.md"
confirm_host = "<deployed-dev-host>"
```

```sh
uv run event-load-harness --config run.toml
uv run event-load-harness --list-profiles    # list traffic profiles
```

## Profiles and routes

`portal-core` exercises the path that failed in the May event: authenticated
page traffic, range-status polling and websocket, browser terminal websockets,
and Guacamole RDP bootstrap.

The route catalog (`profiles.ROUTE_CATALOG`) also lists **deferred** route
classes (`ctfd:*`, `ctf:*`) that document the seam for follow-up work. The
native-CTF submission/scoreboard profile that feeds #850 is a future
profile-plus-executor addition, not a rewrite. A profile cannot select a
deferred route until its executor lands.

## Actors (identities)

Load must run as many distinct authenticated users, never one shared admin
session. Three sources:

- `manifest`: a **0600** TOML file of participant credentials or sessions. The
  loader refuses any group- or world-readable file.

  ```toml
  [[actor]]
  email = "participant1@example.com"
  password = "..."
  user_type = "ctf_participant"

  [[actor]]
  email = "participant2@example.com"
  session_cookie = "sessionid=...; csrftoken=..."
  ```

- `dev-login`: generates actors that drive the documented `/dev-login/`
  endpoint. Valid only where dev-login is enabled (deployed dev). Use
  `--actor-count` to set how many. The harness never broadens
  `DEV_LOGIN_ALLOWED_*` or makes this work against production.

- `ctfd-csv`: deferred with the CTFd surface.

## Safety

- **Target**: must be an explicit `https://` URL. Every non-localhost target
  must be positively acknowledged: pass `--confirm-host` matching the target
  host, or `--allow-production` for an intended production target. An
  unacknowledged or mislabeled host is refused rather than hit by accident.
  `http://` is allowed only for `localhost` with `--allow-insecure-localhost`
  (tunnel profile). The harness does not relax `ALLOWED_HOSTS`, WAF, TLS, or
  origin policy.
- **Secrets**: credentials come from the 0600 manifest, never from argv. The
  report renderer runs a sanitization scan and refuses to write output that
  matches a secret pattern. Do not commit `out/`, `run*.toml`, or `actors*.toml`
  (all gitignored).
- **Load on shared infrastructure**: running against shared dev puts real load
  on shared infra. Treat the live run as an operator-gated action.

## Metrics adapters

- `client-only` (default): no provider credentials. The report lists the
  provider signals it did not collect as explicit gaps.
- `aws`: thin CloudWatch plug. Pass the resource identifiers you want collected;
  anything omitted, or any failed query, becomes a named gap rather than a
  guessed number. Reads telemetry only; issues no mutating calls.

  ```sh
  uv run event-load-harness ... \
    --metric-source aws --region us-east-2 \
    --aws-alb app/<portal-alb>/<id> --aws-asg <portal-asg> \
    --aws-rds <portal-db> --aws-redis <portal-redis>
  ```

A GCP / Prometheus / OpenShift adapter is the next implementation of the same
`MetricsAdapter` protocol.

## Output

The envelope report covers the preflight Evidence Bar: target environment and
run parameters, deployment shape, per-route request/error counts and p50/p95/p99
latency, websocket open/drop/close-code counts and reconnects, same-window
provider metrics (or named gaps), first-mover attribution, and a
supported-concurrency conclusion with limiting factor and a #910 sizing
implication. Unknown fields render as `unknown` rather than a guess.

The conclusion is a heuristic first pass from a single run. Bounding the true
ceiling and margin needs a stepped-concurrency sweep; re-run at increasing
`--concurrency` and compare reports.

## Tests

```sh
uv run pytest
```

Tests cover the harness's own deterministic logic: config validation, percentile
and aggregation math, report rendering and sanitization, close-code mirror
fidelity, profile and route-catalog integrity, manifest permission handling, and
the runner's ramp/concurrency/aggregation via an injected fake executor. The
live HTTP/websocket driving is validated by operator runs against a deployed
environment, not in CI, because the harness must drive the real path rather than
a mock.
