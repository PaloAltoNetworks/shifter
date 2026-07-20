# Portal DB Connection Churn Diagnostic (#853)

Status: diagnostic instrumentation implemented

Date: 2026-06-15

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/853>

## Decision

Keep the deployed Django database posture unchanged for this issue:
`CONN_MAX_AGE=0`. The change adds measurement to the event-load harness so a
live-environment run can decide whether database connection lifecycle is a
material contributor before any connection lifetime is changed.

## Recommended Posture

| Environment | Current recommendation |
| --- | --- |
| Development | Keep `CONN_MAX_AGE=0`. Local tests and SQLite development do not need persistent PostgreSQL connections; deployed development should use the harness as the measurement baseline before experimenting. |
| Event | Keep `CONN_MAX_AGE=0` unless a generated event-load envelope shows DB connection lifecycle moving with RDS pressure and portal p95/p99 latency. |
| Production | Keep `CONN_MAX_AGE=0` until prod-like evidence and max-connection capacity math justify a controlled connection-lifetime knob. Do not run event load against production without the harness production opt-in gate. |

## Measurement Method

Use `uat/event-load-harness` against a deployed target with the AWS metrics
adapter enabled:

```sh
uv run event-load-harness \
  --target-url https://<deployed-dev-host> \
  --confirm-host <deployed-dev-host> \
  --environment dev \
  --profile portal-core \
  --concurrency 150 --ramp-seconds 60 --duration-seconds 600 \
  --actor-source manifest --actor-manifest ./actors.toml \
  --metric-source aws --region us-east-2 \
  --aws-rds <portal-db-instance-id> \
  --report-path out/envelope.md
```

The report renders a `Database connection posture (#853)` section with:

- current Django posture: `CONN_MAX_AGE=0`;
- RDS `DatabaseConnections` average and peak for the same window;
- a lower-bound connection churn proxy from sample-to-sample absolute changes in
  `DatabaseConnections`;
- RDS CPU for the same window;
- portal max route p95/p99 from the client-measured run;
- a recommendation based on whether churn, RDS pressure, and user-visible
  latency move together.

CloudWatch `DatabaseConnections` is a sampled active-connection count, not an
exact open/close counter. Short-lived open/close cycles between samples are not
visible, so the churn value is explicitly labeled as a lower-bound proxy. If an
operator needs exact opens/closes per second, use an explicitly scoped
read-only database observation method for that run and keep DSNs, credentials,
hostnames, and query text out of reports and issue comments.

## Interpretation

The current posture is acceptable when stepped-concurrency runs show low churn,
low RDS CPU, stable RDS peak connections, and portal p95/p99 latency that does
not move with the database metrics.

Treat DB connection lifecycle as a material candidate only when the same window
shows all of these together:

- the RDS connection churn proxy rises with concurrency;
- RDS CPU or connection count moves in the same window;
- portal HTTP p95/p99 or server/service-unavailable errors move with those RDS
  signals.

Do not infer materiality from connection count alone. Persistent connections
can reduce churn while increasing the steady-state number of open database
connections.

## Capacity Check Before Any Posture Change

Before setting a non-zero connection lifetime, size the connection budget:

```text
portal replicas * worker/process count * Django connection contexts
```

That product must fit under the database max-connection limit with room for
background workers, migrations, administrative sessions, failover reconnects,
and Guacamole or adjacent service database users where applicable.

If evidence supports a knob, keep it in `config.settings` under
`DATABASES["default"]`, use the existing `_env_int` pattern, fail startup on
invalid values, and document dev/event/prod defaults. Do not add a new
connection manager, pooling abstraction, pgBouncer/RDS Proxy, or app-side
metrics schema as the first move.

## Follow-Up Rule

Implementation follow-ups are linked only when a generated envelope report
shows DB connection lifecycle moving with RDS pressure and portal tail latency.
Without that evidence, the recommendation is to keep `CONN_MAX_AGE=0` and keep
collecting the same-window event-load envelope.
