# Guacamole Token Affinity Preflight (#928)

Status: pre-implementation guidance

Date: 2026-06-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/928>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Scope Boundary

Issue #928 re-examines the first-click RDP/login-redirect failure after #395 /
PR #855. The suspected defect is not the token-readiness retry already added in
`mission_control.guacamole`; it is task affinity between:

1. the server-side `/api/tokens` exchange performed by Portal Django through
   `GUACAMOLE_API_BASE_URL`, and
2. the browser's `/guacamole` request routed by the public load balancer.

Do not implement the issue in this note. The implementation that follows must
confirm the behavior with task-correlated logs first, then keep the fix inside
the existing Portal access broker, Guacamole topology, secret, config, and
deployment contracts.

## Architecture Decisions

- Guacamole token minting and browser session serving must be task-affine when
  Guacamole auth tokens are process-local. A retry around `/api/tokens` is
  defense in depth for transient 5xx/readiness failures; it is not a fix for a
  token minted on task A and consumed on task B.
- Until a shared Guacamole token/session store or browser/load-balancer-bound
  mint path is proven and implemented, the reliable topology is a single
  `guacamole-client` task/replica per deployment and horizontal scale on
  `guacd`, the per-connection protocol worker.
- `guacd` capacity and `guacamole-client` token/web affinity are separate
  concerns. Do not use the client replica count as the event-capacity knob when
  the token store is task-local.
- `GUACAMOLE_BASE_URL` and `GUACAMOLE_API_BASE_URL` are intentionally different
  contracts: public browser route versus server-to-server token route. The
  implementation must not collapse them accidentally, and must not assume ALB
  or GCLB stickiness applies to the internal service-discovery/ClusterIP route.
- Apply the chosen topology consistently to every deployment surface that uses
  the same server-side JSON-auth token exchange. The AWS prod baseline currently
  exposes `guacamole_client_desired_count`; the GCP Helm values expose
  `guacamoleClient.replicas`. If #928 is scoped to AWS only, record the GCP
  residual risk explicitly rather than leaving an unacknowledged equivalent
  topology.
- Keep Portal as the user auth boundary. Do not enable direct Guacamole login,
  OIDC fallback, permanent Guacamole connection rows, or browser-side auth
  workarounds to mask failed JSON auth.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #928 |
| --- | --- | --- |
| Guacamole JSON-auth broker | `shifter/shifter_platform/mission_control/guacamole.py` | Keep signing, encryption, `/api/tokens`, retry, and final URL construction here. Do not add a second token client or schema. |
| Async bootstrap envelope | `mission_control/guacamole_bootstrap.py`, `views/_guacamole_bootstrap.py`, `GuacamoleBootstrapRequest` | Reuse pollable status, TTL, bounded workers, `Retry-After`, and sanitized failure handling. Do not invent a parallel workflow. |
| Request parsing and auth | `mission_control/views/_guacamole.py` | Keep `@login_required`, `@require_POST`, CSRF, `_parse_json_body`, `_require_instance_uuid`, `_get_guac_settings`, `_ViewError`, and `classify_user_message`. |
| Range/NGFW authorization and credentials | `engine.services.get_rdp_connection_info`, `get_ssh_connection_info`, `connect_ngfw_terminal`; `engine.secrets`; `shared.cloud` | Mission Control must continue asking services for authorized connection data. Do not fetch range credentials in views, JS, CTF, or Terraform. |
| Runtime settings | `config/settings.py`, `entrypoint.sh`, AWS SSM parameters, GCP `scripts/gcp/render_runtime_env.py` | Reuse `GUACAMOLE_JSON_AUTH_SECRET`, `GUACAMOLE_BASE_URL`, `GUACAMOLE_API_BASE_URL`, bootstrap worker/retry settings, and provider secret hydration. |
| AWS topology | `platform/terraform/modules/guacamole/**`, environment portal roots, `modules/portal/ssm`, `modules/portal/ec2/user_data.sh` | Use existing `guacamole_client_desired_count`, `guacd_desired_count`, Cloud Map, ALB target group, SG, log group, and deploy verification surfaces. |
| GCP topology | `platform/charts/shifter/**`, `platform/k8s/gcp/base/**`, `scripts/bootstrap/deploy.py`, `scripts/gcp/render_runtime_env.py` | Use existing Helm values, service, ingress, NetworkPolicy, BackendConfig, and rendered runtime env contracts. |
| Observability and reports | Guacamole ECS log groups, ALB/ingress access logs, portal app logs, `docs/architecture/event-load-harness-preflight-926.md` | Confirm task mismatch using task/log-stream identifiers and aggregate outcomes. Never log or publish Guacamole tokens, signed URLs, encrypted payloads, RDP passwords, or SSH keys. |
| Tests | `tests/mission_control/test_guacamole_readiness.py`, `test_views_guacamole.py`, `test_api_instance_ssh_url.py`, `test_api_ngfw_ssh_url.py`, platform static tests | Extend behavior/static tests at public boundaries. ADR-019 forbids adding first-party internal patch seams. |
| Enforcement | ADR guard, `.importlinter`, `.tflint.hcl`, `.kube-linter.yaml`, kubeconform, actionlint | Run the stack-native validators for every touched surface; do not weaken guardrails for a topology fix. |

## Cross-Cutting Layers

- Auth surface: browser requests stay behind Django login/session, CSRF, and
  Mission Control/engine authorization. Token affinity work must not bypass
  `_get_user`, `Range.get_active_for_user`, READY-state checks, instance UUID
  membership, NGFW ownership, or existing role gates.
- Secret-handling surface: `GUACAMOLE_JSON_AUTH_SECRET` and guacamole-client
  `JSON_SECRET_KEY` must still be the same provider-secret value. RDP passwords
  and SSH private keys remain provider secret-store values resolved through
  `engine.secrets` / `shared.cloud`. Auth tokens and generated URLs are
  credential-bearing and must not be logged, committed, emitted in reports, or
  passed through shell traces.
- Env-binding shape: `GUACAMOLE_BASE_URL` is the browser URL. `GUACAMOLE_API_BASE_URL`
  is the server-to-server mint URL. AWS binds these through SSM and EC2 user
  data; GCP binds them through rendered runtime env/ConfigMap. Any change must
  satisfy those existing parsers and avoid adding synonym settings.
- Config validators: Terraform changes must satisfy Terraform fmt/validate,
  TFLint, Checkov policy, ADR-004 tfvars/secret checks, and RDS/KMS guardrails
  when touched. Kubernetes/Helm changes must satisfy ADR-006 PSS/NetworkPolicy
  expectations, kube-linter, and kubeconform for rendered manifests. Python
  import changes must satisfy `.importlinter` and ADR-001.
- OS/process exposure: it is acceptable for non-secret ARNs and URLs to flow as
  Docker/Kubernetes env. Secret values are hydrated by `entrypoint.sh` or
  Kubernetes Secret refs, not exposed in command argv. Do not put Guacamole
  auth tokens, full token URLs, JSON-auth payloads, private keys, or RDP
  passwords into cloud-init logs, SSM command strings, shell argv, workflow
  logs, screenshots, or generated artifacts.
- Error-envelope surface: expected Guacamole mint/bootstrap failures should use
  the existing `BootstrapFailure` / pollable JSON shape with bounded,
  non-sensitive messages. Engine validation remains sanitized 400s. A browser
  redirect to Guacamole login is a failed first-click outcome, not an acceptable
  degraded success path.
- Logging and observability surface: use task IDs, log stream names, target
  group target IDs, status codes, request IDs, protocol labels, target IDs, and
  durations. If current logs cannot correlate minting task and serving task,
  add only non-secret correlation. Do not enable verbose Guacamole/Tomcat logs
  that print request bodies, `data=...`, or `token=...`.
- Persistence surface: existing `GuacamoleBootstrapRequest.result_url` already
  holds a short-lived token URL for polling. Do not lengthen token lifetime,
  create a durable token repository, add Django models, or write Guacamole DB
  connection rows unless a separate lifecycle/revocation/cleanup design is
  accepted.

## Whole-Repo Scope

Likely in-scope surfaces for the implementation are:

- `shifter/shifter_platform/mission_control/guacamole.py`
- `shifter/shifter_platform/mission_control/guacamole_bootstrap.py`
- `shifter/shifter_platform/mission_control/views/_guacamole.py`
- `shifter/shifter_platform/config/settings.py`
- `shifter/shifter_platform/entrypoint.sh`
- `shifter/shifter_platform/tests/mission_control/**`
- `shifter/shifter_platform/tests/platform/**`
- `platform/terraform/modules/guacamole/**`
- `platform/terraform/modules/portal/ssm/**`
- `platform/terraform/modules/portal/ec2/user_data.sh`
- `platform/terraform/environments/{dev,prod}/portal/**`
- `.github/workflows/_shifter-platform.yml` if deploy verification or runtime
  convergence changes
- `platform/charts/shifter/**`, `platform/k8s/gcp/base/**`,
  `scripts/gcp/render_runtime_env.py`, and `scripts/bootstrap/deploy.py` if the
  GCP-equivalent topology is changed or explicitly validated
- Guacamole technical docs and architecture notes if the implemented contract
  differs from the older direct `?data=` sequence documentation

Out of scope unless the evidence points there:

- range guest provisioning, xrdp startup, RDP password generation/rotation,
  CTF scoring, terminal websocket byte transport, Redis channel-layer posture,
  OIDC provider redesign, WAF/Cloud Armor policy, and range firewall exposure.

## Extensibility Seam

Use the existing topology/config seams first:

- `guacamole_client_desired_count` / `guacamoleClient.replicas`: web/token tier
  cardinality.
- `guacd_desired_count` / `guacd.replicas`: protocol-worker capacity.
- `GUACAMOLE_API_BASE_URL`: server-to-server mint path.
- `GUACAMOLE_BASE_URL`: browser-serving path.

The next reasonable variation is allowing multiple guacamole-client tasks after
one of two architectures is proven:

1. a Guacamole-supported shared token/session store, with explicit lifecycle,
   revocation, and failure semantics; or
2. a mint path that is truly bound to the same load-balancer target as the
   browser session.

If that second mode ships, introduce one explicit validated topology posture at
the Terraform/Helm edge instead of relying on an implicit relationship between
replica count, API URL, and load-balancer stickiness. Until then, keep the
single-client posture simple and scale `guacd`.

## Evidence Bar

The diagnosis must show, without exposing secrets:

- the Portal bootstrap request that minted the Guacamole auth token;
- the guacamole-client task/log stream that handled `/api/tokens`;
- the guacamole-client task/target that handled the browser `/guacamole` /
  client navigation;
- whether mismatch correlates with first-click login redirects/failures; and
- the deployed shape: portal instance/pod count, `guacamole-client` task/replica
  count, and `guacd` task/replica count.

The acceptance run must use fresh browser sessions and real Portal auth/session
paths. If the selected architecture pins `guacamole-client` to one task, "all
guacamole-client tasks" means the sole configured task; if multiple client
tasks remain configured, the test must prove 20/20 cold first-click connects
across those tasks, not just across portal instances.

## Gotchas And Anti-Patterns

- Do not treat ALB/GCLB browser stickiness as applying to Django's direct
  service-discovery or ClusterIP `/api/tokens` call.
- Do not keep `guacamole_client_desired_count > 1` or
  `guacamoleClient.replicas > 1` with the current internal mint path unless
  evidence proves tokens are shared across tasks or another affinity mechanism
  is in place.
- Do not move the retry loop to JavaScript, add blind browser sleeps, open
  multiple tabs, or retry browser navigation with fresh tokens.
- Do not broaden Security Groups, NetworkPolicies, WAF/Cloud Armor, or range
  RDP/SSH exposure to compensate for token affinity.
- Do not add duplicate request DTOs, validation helpers, exception classes,
  HTTP-client abstractions, secret readers, or CTF-specific RDP flows.
- Do not store Guacamole tokens in Redis/Django cache or pre-create Guacamole
  DB rows as a quick workaround without a separate token lifecycle and cleanup
  design.
- Do not rely on committed `terraform.tfvars` example baselines as the only
  deployment source; AWS deploys render `local.auto.tfvars` from secrets per
  ADR-011-R7.
- Do not hand-edit `CHANGELOG.md` for the eventual fix. A user-visible runtime
  fix should use a `changelog.d/928.fixed.md` fragment.

## Non-Goals

- No implementation in this preflight note.
- No replacement of Guacamole JSON auth, no direct Guacamole login fallback, no
  OIDC redesign, and no permanent connection provisioning.
- No new observability platform, public diagnostics endpoint, metrics schema,
  persistence model, or architecture enforcement rule.
- No change to range provisioning, guest readiness, terminal websocket
  capacity, CTF domain workflows, or scenario schemas unless the log evidence
  proves the failure lives there.
- No weakening of ADR guard, import-linter, Terraform, Kubernetes, Checkov,
  gitleaks, actionlint, or deploy-verification gates.

## Validation Expectations

Run the repository architecture gate for any implementation touching this
surface:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Add the stack-native validators for touched files:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

For tests, prefer public-boundary behavior/static coverage: Mission Control
Guacamole URL/bootstrap tests, platform topology assertions, and the live
20/20 cold first-click acceptance run. Keep ADR-019's boundary-mock rule intact.

## Implemented (#928)

Status: implemented. The shipped change applies the single-client topology
prescribed above and makes it structurally enforced rather than configuration
that can drift back:

- AWS: the `guacamole-client` ECS service `desired_count` is **hard-pinned to
  the literal `1` in the module** (`platform/terraform/modules/guacamole/ecs.tf`),
  not wired to a per-environment input. AWS prod deploys render
  `local.auto.tfvars` from secrets, so pinning only the checked-in tfvars
  baseline is defeatable — a generated value of `2` would reconcile the service
  back to multiple client tasks. Moving the invariant to the module boundary
  means no input (committed or generated) can scale the client tier above one
  task. `var.guacamole_client_desired_count` is retained for input compatibility
  but carries a `validation` block rejecting any value other than `1`, so a
  stray generated value fails the plan rather than scaling silently. The service
  no longer carries `lifecycle { ignore_changes = [desired_count] }`, so
  Terraform owns and reconciles the count instead of leaving a stale running
  value. The committed prod/dev tfvars still set `guacamole_client_desired_count
  = 1` for clarity and to satisfy the validation.
- AWS: the `guacamole-client` autoscaling target and policy were removed from
  `platform/terraform/modules/guacamole/ecs.tf`. The single
  `guacamole_enable_autoscaling` flag (and the `autoscaling_*` capacity bounds)
  now governs **guacd only** — the per-connection capacity tier. The client tier
  can no longer be scaled to N>1, which is what would silently re-introduce the
  token/task affinity failure during an event.
- GCP: `guacamoleClient.replicas` is pinned to `1` in
  `platform/charts/shifter/values-gcp-prod.yaml` (dev was already `1`) for
  cross-provider parity. The chart has no HorizontalPodAutoscaler, so `replicas`
  is the sole client-count knob.
- `mission_control/guacamole.py`'s `/api/tokens` readiness retry (PR #855) is
  retained unchanged as defense in depth.
- The invariant is guarded by static topology tests in
  `tests/platform/test_guacamole_topology.py` (no client autoscaling resource,
  no `ignore_changes` on the client service, the module hard-pins the client
  `desired_count` to literal `1` and does not read the per-env input, the input
  variable validates to `1`, prod client count/replicas == 1, guacd autoscaling
  retained).

Future multi-client mode remains an explicit, validated change (a shared
Guacamole token/session store, or a mint path bound to the same load-balancer
target as the browser session) — not an implicit consequence of a replica
count. The live 20/20 cold first-click acceptance run is performed at/after
deploy against the production surface.
