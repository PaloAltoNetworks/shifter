# GCP Shared-Service Event Capacity Preflight (#1816)

Status: pre-implementation guidance

Date: 2026-09-17

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1816>

Issue #1816 is requirement-free. The GitHub issue is the shipping contract.
This note fixes the repository-wide boundaries before implementation; it does
not implement a capacity profile, deployment change, load gate, or runbook.

## Decision Boundary

This issue authors the capacity contract for the GCP **shared participant
path**: portal, Guacamole client, guacd, Cloud SQL, Memorystore, GKE access
capacity, and the public load balancer. It does not own the range-plane quota,
placement, or reservation contract covered by #1346 and ADR-047.

Keep four existing meanings separate:

1. `deployment.profile` (`dev` or `prod`) selects a backend deployment tier.
2. A shared-service capacity profile selects an immutable, versioned event
   envelope such as 10, 30, 50, or 100 concurrent participants.
3. `event_load_harness.profiles.Profile` selects a traffic mix.
4. A gate budget decides whether one run passes.

Do not reuse the bare word `profile` across these boundaries in code, generated
artifacts, labels, or reports. A capacity identity should carry both revision
and participant count (for example, an identifier shaped like
`gcp-shared-v1-p30`); materially changing its settings or budget creates a new
revision instead of silently redefining old evidence.

No new ADR is needed. ADR-006/007/008 already own GKE packaging, restricted
workloads, bootstrap, and GCP secret posture; ADR-011 owns the validated root
configuration and backend bundle; ADR-018 owns Redis channel-layer selection;
ADR-019 owns live-boundary evidence; ADR-039 owns participant access and range
containment; and ADR-047 owns range-plane capacity. Update an ADR only if the
implementation changes one of those durable decisions.

## Architecture Decisions And Guardrails

### One selected contract, multiple projections

`shifter/installation/settings_gcp.py` is the canonical operator-intent
validator. Add one GCP-specific `shared_service_capacity_profile` selector
there; do not overload `deployment.profile`, infer a size from an environment
name, or add an independent workflow, Terraform, Helm, and harness selector.
The normal `installation.loader.load_root_config` path must validate it before
any cloud mutation. Do not copy the current `_read_deployment_profile` YAML
shortcut for this new setting.

The committed capacity catalog must have one typed, closed validator and one
resolver owned beside the GCP backend installation contract. That resolver
projects the same selected entry into:

- generated, non-secret Terraform inputs for Cloud SQL, Redis, GKE node-pool
  capacity/autoscaling, and the selected profile identity;
- Helm values for replicas, resources, HPA/drain posture, BackendConfig
  timeouts, and non-secret runtime settings;
- the strict load-gate budget and run shape; and
- a sanitized desired-state document used by drift inspection.

The catalog must contain at least versioned 10-, 30-, 50-, and 100-participant
entries. It is policy, not an arbitrary extension map: unknown keys, unknown
profile ids, missing projections, non-positive quantities, invalid Kubernetes
resources, inconsistent timeout orderings, and unsafe connection budgets fail
before Terraform or Helm runs. Terraform tfvars, `values-gcp-*.yaml`, harness
TOML, workflow variables, and runbooks must not carry hand-copied second
definitions of the same profile.

`scripts/bootstrap/gcp_control_plane.py` remains the deployment compositor. It
must resolve the selected entry once, write the generated Terraform projection
before `apply_gcp_control_plane_terraform`, and pass the same resolved object to
`render_gcp_helm_values`. Checked-in `terraform.tfvars` and
`values-gcp-{dev,prod}.yaml` remain safe baselines, not event overrides.

### Capacity fields and invariants

Each catalog entry must make these deployment-owned settings explicit:

- portal minimum/desired replicas, CPU/memory requests and limits, web worker
  count, bootstrap-worker count, pod HPA bounds/thresholds, and access-node
  capacity;
- `guacd` replicas/resources/HPA posture and `guacamole-client` resources;
- Cloud SQL tier/availability/storage posture and the per-consumer SQL
  connection budget;
- Memorystore tier/capacity and Redis connection/utilization budget;
- public portal and Guacamole backend request/idle/drain timeouts, portal
  WebSocket ping interval/timeout, process graceful timeout, pod termination
  grace, and connection draining; and
- gate concurrency, ramp, bootstrap deadlines, sustained-hold duration,
  latency/error budgets, required telemetry, and saturation thresholds.

The selected 30-participant entry must reproduce the qualified live shape from
the issue without an operator editing Kubernetes, Cloud SQL, Memorystore, or
load-balancer resources after deployment. Its minimum ready capacity, rather
than hoped-for scale-out during the run, must carry the 30-participant gate.
Autoscaling is recovery/headroom and future-growth posture; it is not proof of
pre-event readiness.

Preserve the #928 token-affinity invariant: `guacamoleClient.replicas` remains
exactly one until a separately accepted shared-token/affine-mint design exists.
Scale `guacd`, not the token-serving client. Portal and `guacd` retain the
exclusive access-pool placement from #1711; do not schedule
`guacamole-client` or unrelated workers there.

Validate coupled limits rather than accepting individually valid numbers:

- WebSocket ping cadence stays safely below the public backend idle timeout.
- Connection drain and termination grace cover the authored in-flight drain
  window; HPA scale-down must not reap active event tunnels.
- Effective portal bootstrap concurrency accounts for replicas * web workers *
  the process-local `GUACAMOLE_BOOTSTRAP_WORKERS` pool.
- SQL capacity accounts for portal worker/process contexts, all background
  worker replicas, migrations/operator reserve, and the Guacamole JDBC pool.
  `CONN_MAX_AGE=0` remains the incumbent unless event evidence justifies the
  existing `_env_int`-style setting seam; do not introduce pgBouncer, a new
  ORM pool, or a connection-manager abstraction here.
- Redis capacity accounts for all Channels processes and reconnect headroom.
  Redis is not a terminal/Guacamole byte-stream transport.
- HPA maxima cannot exceed node-pool/IP/resource capacity, and node-pool
  autoscaling minima must be sufficient to schedule the profile's minimum
  portal and guacd replicas with anti-affinity.

### A strict public-path gate, built from the existing UAT seams

Extend `uat/event-load-harness`; do not create another load harness. Reuse the
real front-door and tunnel implementation already present in
`uat/range-functional-smoke`:

- `session.Credential`, `identity_platform_id_token`, and
  `exchange_id_token_for_session` for password + TOTP + product session
  creation;
- `targets.select_target` for owner-scoped, logical target selection;
- `guacamole.bootstrap_path`, polling classification, one-time URL parsing,
  tunnel parameters, and secure URL rules; and
- the bounded, authored result/error and redaction conventions.

Factor only the reusable Guacamole session primitive inside that existing UAT
package if necessary so both runners call one implementation. Do not duplicate
Identity Platform, CSRF, target-discovery, Guacamole token, or protocol parsing
logic in the event harness.

The event-load harness's present `guacamole:bootstrap` route is insufficient:
it calls a legacy endpoint, records only HTTP latency, and never consumes the
one-time URL or opens the public Guacamole tunnel. A gate actor must perform a
real login, submit the versioned bootstrap request, poll to one-time delivery,
open the public Guacamole WebSocket, wait for guacd readiness **and display
synchronization**, then keep reading and acknowledging the protocol for the
entire hold. A WebSocket upgrade, HTTP 202, minted URL, or `ready` instruction
alone is not a connected-display claim. Protocol handling must parse bounded
Guacamole instructions and acknowledge synchronization as the browser does;
substring matching and sleeping on an unread socket are not sufficient.

The strict gate is separate from the harness's current heuristic
`derive_conclusion`. It fails closed when a required check or metric is missing,
stale, or unparseable. The authored budget must cover at least:

- login/bootstrap success and p50/p95/p99 bootstrap latency;
- established/display-synchronized tunnel count;
- zero unexpected tunnel drops during the full hold;
- zero pod-restart delta for portal, guacamole-client, and guacd;
- Redis connection/utilization plus zero eviction and rejected-connection
  deltas;
- Cloud SQL connection utilization, connection errors, CPU, and remaining
  connection headroom;
- guacd ready replicas, active tunnels, CPU/memory, and an explicit saturation
  ceiling; and
- load-balancer backend latency, 5xx/timeouts, backend health, and dropped or
  rejected connections.

Threshold values are catalog data fixed before a run, not values learned from
the run being judged. Missing provider telemetry is a named gap for an
exploratory envelope, but a failing prerequisite for the acceptance gate. Keep
the current `MetricsAdapter` / `MetricsResult` / `MetricValue` normalization and
add a GCP Cloud Monitoring/Kubernetes read-only adapter; do not create a second
report schema or a public application diagnostics endpoint.

Use distinct participant identities and already-provisioned, authorized ranges.
Credential values stay in a `0600` manifest, environment, or Secret Manager and
in memory; never place passwords, TOTP seeds, ID/session/CSRF tokens, Guacamole
URLs, tunnel query strings, or private target addresses in argv, workflow
outputs, logs, reports, screenshots, or committed artifacts. The public web API
key is configuration, not authentication authority, but it still should not be
dumped with the actor record. Identity Platform throttling is a measured edge
failure, not permission to substitute `/dev-login/` for the acceptance gate.

### Drift and operations

The profile identity and catalog revision must be visible as non-secret
Terraform output/resource label and Kubernetes release/workload annotation,
but labels are provenance, not drift proof. A read-only drift command must
compare an allowlisted, normalized desired projection with effective live
state:

- a refresh-enabled Terraform plan or provider readback for Cloud SQL, Redis,
  and GKE node-pool settings;
- actual Deployment/HPA/BackendConfig/ConfigMap specs from the Kubernetes API,
  not only `helm get values`; and
- the expected profile identity/revision on both projections.

The drift report names resource, field, desired value, and observed value while
excluding Terraform outputs/state, Kubernetes Secrets, environment dumps,
Guacamole data, private addresses, and provider response bodies. Do not copy the
repository's `-refresh=false` IAM plan pattern for live-capacity drift: that
mode cannot prove remote state matches configuration. A report-only check must
not silently reconcile drift.

The operator runbook must keep scale-up and scale-down asymmetric. Scale-up uses
the normal `deploy.yml` / `_gcp-dev.yml` path, waits for Terraform convergence,
Helm rollouts, all ready replicas/HPA minima, dependency health, and zero drift,
then runs the strict gate before event admission. Scale-down is never an HPA or
manual emergency action during active tunnels: wait for the event and sessions
to end, record final health, select the lower authored profile, preview provider
changes, deploy through the same path, then re-run drift/readiness checks.
Database/cache resizing or topology changes that can restart/fail over a
service require an explicit maintenance window and rollback target. `kubectl
scale`, console edits, direct `gcloud sql/redis` updates, and ad hoc Helm
`--set` values are break-glass actions that deliberately produce drift and
must be followed by reconciliation through authored source.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1816 |
| --- | --- | --- |
| Public operator intent | `shifter/installation/schema.py`, `settings_gcp.py`, `loader.py`, `bundle_gcp.py`, published backend contract | Add one validated capacity selector to the GCP settings model. Do not add a workflow-only or Terraform-only selector. |
| GCP composition | `scripts/bootstrap/gcp_control_plane.py`, `scripts/gcp/render_runtime_env.py`, `runtime_inventory_gcp.py` | Resolve once and project to Terraform, Helm, runtime env, gate, and drift. New runtime keys need inventory and `config/env-manifest.json` ownership. |
| Infrastructure | `platform/terraform/gcp/environments/{gcp-dev,nazgul}`, `modules/platform-core`, `modules/portal/{cloud-sql,redis,gke}` | Extend existing variables/modules and outputs; no event-only Terraform root or console-owned setting. |
| Kubernetes packaging | `platform/charts/shifter/{values.yaml,values.schema.json,values-gcp-*.yaml,templates/**}`, chart contract tests | Helm remains authoritative. Validate values, retain restricted PSS/NetworkPolicy/Workload Identity, and keep Kustomize parity where the supporting manifests remain. |
| Portal runtime | `entrypoint.sh`, `config/asgi_worker.py`, `_database_settings.py`, `_guacamole_settings.py`, `_terminal_settings.py`, `_channels.py` | Reuse env-owned workers/timeouts, database settings, bounded bootstrap workers, terminal limits, and Redis fail-closed posture. Parse each knob once. |
| Guacamole topology | `mission_control.guacamole*`, `GuacamoleBootstrapRequest`, #928 topology tests, chart Guacamole templates | Preserve JSON-auth, one-time delivery, single guacamole-client, guacd scaling, and sanitized bootstrap failures. |
| Load generation | `uat/event-load-harness` config/profile/runner/stats/report and metrics adapter contract | Add a strict Guacamole hold scenario and gate verdict without replacing traffic profiles, aggregate schema, or report sanitizer. |
| Real participant flow | `uat/range-functional-smoke` session/targets/guacamole/runner/results/report | Reuse Identity Platform + MFA, CSRF/session exchange, logical target resolution, secure URL enforcement, tunnel protocol handling, and bounded evidence. |
| Health/observability | `/health`, GKE readiness/liveness probes, Cloud Monitoring, Kubernetes status/events, existing startup posture logs | Health, saturation, and gate verdict stay distinct. Use provider/platform telemetry; do not expose verbose public diagnostics. |
| Errors/logging | Harness `ConfigError`/`AuthError`/`ReportError`, smoke `ProfileError`/`SessionError`/check codes, app `shared.errors`, `shared.log_sanitize`, `ECSFormatter` | Extend the local incumbent hierarchy; use authored low-cardinality reasons and sanitized identifiers, never raw SDK/API/Guacamole errors. |
| Deployment workflow | `deploy.yml`, `_gcp-dev.yml`, digest verification and rollout waits | Capacity changes use the real serialized deploy path and existing WIF/Environment trust; no parallel deploy workflow or long-lived service-account key. |
| Range-plane boundary | ADR-047 capacity catalog and #1346 range quota/placement work | Treat sufficient ready ranges as a gate precondition. Do not reserve, create, or re-size range-plane capacity in this shared-service profile. |

## Cross-Cutting Layers The Intended Design Must Pass

- **Authentication and authorization:** Identity Platform password/TOTP and
  `/auth/identity/session/` establish each real Django session; existing
  email-verification, MFA, allowlist, CSRF, owner/event/range READY, instance
  membership, logical participant-access channel, and one-time bootstrap
  ownership checks remain active. The harness receives no admin bypass and
  performs no direct model/service calls.
- **Secret handling:** actor secrets use the existing off-argv credential/file
  posture; app, DB, Redis, and Guacamole values remain in Secret Manager or
  Kubernetes Secrets and are hydrated by `entrypoint.sh` / existing secret
  sync. The catalog, tfvars projection, Helm values, ConfigMap, labels, reports,
  and drift output contain non-secret settings or secret references only.
- **Configuration shapes:** root config passes the closed GCP settings model;
  catalog resolution is closed and cross-field validated; Terraform variables,
  Helm `values.schema.json`, runtime-env inventory/manifest, Django parsers, and
  harness `RunConfig` each validate their owned projection. No layer reparses
  the whole catalog or silently defaults an unknown field.
- **Network/Kubernetes admission:** public traffic retains managed TLS, Cloud
  Armor, GCE Ingress/BackendConfig, default-deny NetworkPolicy, and the #1711
  access-pool source boundary. Pods retain restricted PSS, non-root users,
  dropped capabilities, read-only roots, bounded writable volumes, explicit
  resources, and no unnecessary service-account token.
- **OS/process exposure:** all subprocesses use fixed argv arrays. Credentials,
  token URLs, generated secret bundles, Terraform state, kubeconfigs, and full
  process environments stay out of argv and logs. Non-secret profile ids,
  resource quantities, and timeout values may ride generated tfvars/ConfigMaps.
- **Error envelopes and logging:** application failures keep existing
  `classify_user_message` / `safe_user_message` behavior. Harness failures use
  authored check codes/categories and aggregate counts. Raw response bodies,
  provider exceptions, terminal/display data, tokens, emails, and private
  topology do not enter evidence. Provider gaps and stale data fail the strict
  gate without leaking the underlying response.
- **Persistence:** PostgreSQL remains authoritative application state and
  `GuacamoleBootstrapRequest` remains the bounded one-time token lifecycle.
  Capacity selection is deployment config, not a Django model. Gate samples
  and reports are ephemeral/sanitized evidence; no telemetry database,
  participant-session store, or durable Guacamole connection table is added.
- **Workflow trust:** GitHub OIDC/WIF, Environment scoping, pinned actions,
  digest verification, Terraform state locking, and serialized environment
  deploys remain intact. The load identity and provider read-only telemetry
  identity are separate authorities; neither receives deploy mutation rights
  merely to run the gate.

## Whole-Repository Surfaces In Scope

- Installation contract and publication: `shifter/installation/**` and the GCP
  example/schema compatibility tests.
- Deployment composition and workflow: `scripts/bootstrap/**`, `scripts/gcp/**`,
  `.github/workflows/{deploy,_gcp-dev}.yml`, and deploy-secret documentation.
- Infrastructure: GCP environment roots, `platform-core`, Cloud SQL, Redis, GKE,
  outputs, and their Terraform tests/linters.
- Workloads: `platform/charts/shifter/**`, `platform/k8s/gcp/**`, BackendConfig,
  Deployments/HPAs/PDBs, runtime ConfigMap, chart schema/tests, and render checks.
- Runtime configuration only where the selected profile owns an existing
  process/pool/timeout knob: `entrypoint.sh`, `config/_*.py`, runtime inventory,
  env manifest, and focused settings tests.
- Verification: `uat/event-load-harness/**`,
  `uat/range-functional-smoke/**`, their package tests/docs, and an operations
  runbook for selection, gate, drift, scale-up, rollback, and scale-down.

## Gotchas And Anti-Patterns

- Do not call the range count, deployment tier, traffic mix, HPA target, or gate
  budget the shared-service capacity profile. They are related inputs/outputs,
  not synonyms.
- Do not hard-code four copies of the profile in Terraform tfvars, Helm values,
  workflow choices, and harness configs. A drift test between duplicates is not
  as strong as one resolver projecting one contract.
- Do not let a workflow input override a different profile selected by
  `shifter.yaml`, or let Terraform and Helm finish on different profile ids.
- Do not claim Guacamole success from HTTP 202, bootstrap `succeeded`, URL
  delivery, WebSocket upgrade, or guacd `ready` without display synchronization
  and a sustained, continuously-read tunnel.
- Do not reuse `/dev-login/`, one admin session, or one participant session for
  all virtual users in the acceptance gate.
- Do not log, serialize, or report signed Guacamole URLs/tokens, actor secrets,
  raw protocol/display frames, raw API bodies, provider payloads, Terraform
  state, or private target addresses.
- Do not raise `guacamoleClient.replicas` above one, route terminal/Guacamole
  bytes through Redis, or mistake Redis channel-layer metrics for tunnel load.
- Do not use average CPU, `/health`, ready replicas, or “no HTTP 500s” as the
  sole gate. Tail latency, tunnel drops, restarts, pool pressure, backend health,
  and metric completeness are independent evidence.
- Do not use HPA scale-out during the gate to compensate for an under-sized
  minimum, and do not allow scale-down/rolling replacement to sever active
  tunnels.
- Do not make manual `kubectl`, Helm `--set`, Cloud Console, or `gcloud`
  mutations the normal event procedure. They defeat the authored contract.
- Do not broaden Cloud Armor, IAM, NetworkPolicy, range firewall, public RDP,
  GKE control-plane access, or secret access to make the load generator work.
- Do not add a second config schema, runtime renderer, Guacamole client,
  Identity Platform client, exception hierarchy, metrics/result vocabulary,
  deployment workflow, or persistence model.

## Non-Goals And Implementation Boundaries

- No issue implementation, numeric profile authoring, infrastructure resize,
  workflow dispatch, or live load run in this preflight.
- No change to #1346/ADR-047 range-plane quota, reservation, placement,
  provisioning, warm-pool, or participant-access authorization contracts.
- No generic multi-cloud event-capacity framework. The catalog is GCP
  shared-service policy; a later AWS parity issue may reuse the vocabulary only
  after its topology is mapped.
- No Guacamole auth/token-store redesign, multiple guacamole-client replicas,
  direct Guacamole login, browser auth bypass, or durable connection rows.
- No new public diagnostics endpoint, telemetry store, dashboard platform,
  Prometheus/statsd deployment, service mesh, pgBouncer, or Redis-based tunnel
  accounting.
- No CTF scoring/load redesign, scenario schema change, range creation/destruction
  by the gate, or production load without explicit target acknowledgement and
  event authorization.

## Validation Expectations

This documentation-only preflight must pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation must add focused contract/projection/drift/gate tests and run
the repository-required checks for every touched surface: installation package
tests and contract drift, event-load and range-smoke tests, Terraform fmt/
validate/TFLint, Helm schema/render and chart-contract tests, actionlint,
kube-linter, kubeconform, platform Ruff/import-linter/settings tests, and the
full ADR guard. Acceptance additionally requires the real 30-participant
public-path gate against a clean profile-selected deployment; mocked app/cloud
internals cannot satisfy that live claim.
