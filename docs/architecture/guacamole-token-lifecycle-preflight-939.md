# Guacamole Token Lifecycle Preflight (#939)

Status: pre-implementation guidance

Date: 2026-06-21

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/939>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract.

## Scope Boundary

Issue #939 closes the persistence lifecycle gap in the asynchronous Guacamole
bootstrap flow:

- generated Guacamole client URLs carry bearer token material;
- `GuacamoleBootstrapRequest.result_url` currently persists that URL until the
  row expires or is manually deleted;
- expired bootstrap rows are not pruned by an active lifecycle job.

The fix belongs in the existing Mission Control Guacamole bootstrap boundary and
the existing runtime scheduler/deploy surfaces. It must not redesign
Guacamole authentication, range authorization, credential resolution, CTF event
tasks, or platform networking.

## Architecture Decisions

- Treat `result_url` as secret-bearing. It contains the Guacamole auth token
  returned by `/api/tokens`, so a database read can become live RDP/SSH access
  for the remaining token lifetime.
- `succeeded` must continue to mean "URL is ready to deliver", not "URL was
  already delivered." The implementation needs an explicit consumed/delivered
  state or equivalent durable marker so the row can keep non-secret lifecycle
  metadata while clearing the token field immediately after the URL is returned
  to the client.
- The status endpoint is the delivery boundary. The first owner-scoped poll
  that returns the final Guacamole URL must atomically consume the value and
  clear token material from persistence before the response leaves the view.
  A repeated poll should return an authored non-sensitive terminal state such
  as already delivered or gone, not the URL again.
- The worker must not persist a token URL for an already-expired bootstrap. If a
  slow build finishes after `expires_at`, it should fail/expire without saving
  `result_url`; otherwise the status endpoint can correctly return 410 while a
  token remains parked in the row until pruning.
- Pruning is a Mission Control bootstrap lifecycle concern. A scheduled host may
  be the existing `ctf-scheduler` process for operational convenience, but the
  deletion query and policy must remain Mission Control-owned. Do not put
  Guacamole bootstrap rows into `CTFScheduledTask`, create fake CTF events, or
  import Mission Control models/services into `ctf` in a way that violates the
  import contracts.
- At-rest encryption is defense in depth only. Clearing on delivery and pruning
  expired rows are mandatory. If token-bearing material must be persisted for
  the short ready-to-deliver window, reuse the existing field encryption key and
  encryption patterns rather than introducing a second key hierarchy or per-call
  KMS dependency.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #939 |
| --- | --- | --- |
| Bootstrap persistence | `mission_control.models.GuacamoleBootstrapRequest` | Extend the existing model/status vocabulary and indexes. Do not add a parallel token table or cache repository. |
| Bootstrap worker lifecycle | `mission_control.guacamole_bootstrap` | Keep enqueue, TTL, bounded workers, queue-full behavior, DB connection cleanup, success/failure persistence, and pruning policy here or in a Mission Control service it owns. |
| Delivery endpoint | `mission_control.views._guacamole_bootstrap` | Reuse owner-scoped lookup, `Retry-After`, `_mark_expired`, and JSON response shape. Add consume-and-clear at the status response boundary. |
| Guacamole token broker | `mission_control.guacamole` | Keep JSON-auth signing, encryption, `/api/tokens`, retry, and URL construction here. Do not add a second token client. |
| Authorization and credentials | `engine.services.get_rdp_connection_info`, `get_ssh_connection_info`, `connect_ngfw_terminal`; `engine.secrets`; `shared.cloud` | Continue resolving range/NGFW ownership and secret values inside engine service boundaries. This issue only changes lifecycle of the generated URL after authorization succeeds. |
| Management command style | `shared.management.commands.prune_notifications` | A standalone prune command should follow the simple command pattern and call a reusable lifecycle function that returns counts. |
| Periodic scheduler process | `ctf.management.commands.run_ctf_scheduler` | If reused as the process host, preserve heartbeat, signal handling, bounded per-cycle work, and import-linter boundaries. Do not make CTF own Mission Control cleanup semantics. |
| Settings parser | `config/settings.py` `_env_int` / `_env_bool` | New lifecycle knobs, if needed, are typed non-secret settings parsed once. Prefer existing TTL before adding more knobs. |
| Runtime env binding | AWS `platform/terraform/modules/portal/ssm`, `platform/terraform/modules/portal/ec2/user_data.sh`, `scripts/portal-deploy/deploy_portal.sh`; GCP `scripts/gcp/render_runtime_env.py`, Helm/Kustomize scheduler workloads | New non-secret scheduler cadence/batch settings must flow through every runtime that starts the scheduler, not only local Django settings. |
| Encryption | `FIELD_ENCRYPTION_KEY`, `encrypted_model_fields`, `cms.credential_encryption` | Reuse repo-native field encryption if a token-bearing field remains persisted. Do not add a new secret store or ad hoc crypto helper. |
| Logging and errors | `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint`, `shared.errors.classify_user_message`, bootstrap `_clean_error_message` | Log request IDs, protocol, target IDs, counts, status, and durations only. Never log final URLs, Guacamole tokens, encrypted payloads, RDP passwords, or SSH keys. |
| Tests | `tests/mission_control/test_views_guacamole.py`, `test_api_instance_ssh_url.py`, `test_api_ngfw_ssh_url.py`, `test_guacamole_readiness.py`, `static/js/terminal-guacamole.test.js`, deploy renderer tests | Extend public-boundary behavior tests. ADR-019 forbids growing first-party internal patch seams. |
| Enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, ADR guard, ADR-004 secret checks, ADR-019 boundary-mock policy, Terraform/Kubernetes/actionlint checks for touched deployment files | Do not weaken guardrails to make cleanup scheduling easier. |

## Cross-Cutting Layers

- Auth surface: HTTP launch endpoints keep `@login_required`, `@require_POST`,
  CSRF, `_get_user`, and existing engine authorization. Status/open endpoints
  keep `@login_required`, `@require_GET`, UUID routing, and
  `(pk=request_id, user_id=authenticated_user_id)` lookups. A cleanup job must
  never bypass these gates to disclose or replay a URL.
- Authorization and validation surface: `engine.services` remains authoritative
  for active range, range `READY`, instance UUID membership, NGFW ownership,
  host resolution, and credential references. `GuacamoleBootstrapRequest`
  protocol/status choices remain the persistence contract; add any delivered
  state through the model/migration rather than string constants in views.
- Secret-handling surface: provider secrets stay behind `engine.secrets` and
  `shared.cloud`. `GUACAMOLE_JSON_AUTH_SECRET` is hydrated by `entrypoint.sh`
  from Secrets Manager/Secret Manager IDs. Generated URLs, auth tokens, JSON
  auth payloads, RDP passwords, and SSH keys must not be logged, cached, written
  to temp files, or kept in DB after delivery.
- At-rest storage surface: `result_url` is the only known token-bearing
  bootstrap column. If encryption is used for its ready-to-deliver window, reuse
  `FIELD_ENCRYPTION_KEY`-backed field encryption and keep clearing mandatory.
  Do not persist token material in `error_message`, `metadata`, audit rows,
  Redis, Django cache, or a new "delivered URL" column.
- Env-binding shape: existing Guacamole settings are `GUACAMOLE_BASE_URL`,
  `GUACAMOLE_API_BASE_URL`, `GUACAMOLE_BOOTSTRAP_WORKERS`,
  `GUACAMOLE_BOOTSTRAP_TTL_SECONDS`, `GUACAMOLE_BOOTSTRAP_INLINE`, and retry
  knobs. New lifecycle settings should stay in the `GUACAMOLE_BOOTSTRAP_*`
  namespace and be non-secret integers such as cadence, batch size, or delivered
  retention.
- Config validators: Django settings should fail loud on invalid integers.
  AWS SSM-fed values must be validated in both `user_data.sh` and
  `scripts/portal-deploy/deploy_portal.sh` before they reach Docker argv. GCP
  rendered env/Helm values must keep Kubernetes manifests valid under
  kube-linter and kubeconform. Python import changes must satisfy
  `.importlinter`.
- OS/process exposure: non-secret lifecycle integers can be Docker/Kubernetes
  env. Token-bearing URLs cannot appear in container args, SSM commands, shell
  traces, health checks, process listings, deployment logs, screenshots, or
  generated reports. Management commands should emit counts only.
- Error-envelope surface: expected expired/delivered/replayed polls should use
  authored fixed messages and appropriate 4xx/410 responses. Do not return raw
  exception text, provider errors, secret references, or token-bearing URLs in
  JSON or HTML opener responses.
- Observability surface: useful signals are non-secret counts and durations:
  consumed rows, cleared rows, pruned delivered rows, pruned expired rows,
  expired-running rows, queue-full events, and prune errors. Use
  `safe_log_value` for user-controlled or opaque identifiers.
- Persistence and transaction surface: delivery must be race-safe. Use a
  row-level lock or equivalent conditional update so two concurrent status
  polls cannot both receive the same token URL. Pruning must be bounded by batch
  size/order and must not delete non-expired `PENDING`/`RUNNING` work.

## Extensibility Seam

Keep one Mission Control lifecycle seam around bootstrap rows:

- create: existing enqueue/worker code sets TTL and non-secret metadata;
- ready: worker stores the short-lived URL only if still before expiry;
- consume: status view atomically returns the URL once and clears token
  material, recording delivered state/time if the row remains;
- prune: scheduled lifecycle function deletes delivered and expired terminal
  rows in bounded batches.

Parameterize only the policy points that are likely to vary by deployment:
bootstrap TTL, delivered-row retention, prune cadence, and prune batch size.
That lets future protocols, a shared Guacamole token store, or a different
scheduled runner reuse the same lifecycle without editing browser code, CTF
flows, engine authorization, or platform network topology.

## Whole-Repo Scope

Likely in scope for the future implementation:

- Django bootstrap path:
  `shifter/shifter_platform/mission_control/models.py`,
  `mission_control/migrations/**`,
  `mission_control/guacamole_bootstrap.py`,
  `mission_control/views/_guacamole_bootstrap.py`,
  `mission_control/views/_guacamole.py`, and `mission_control/urls.py`.
- Runtime settings:
  `shifter/shifter_platform/config/settings.py` and `entrypoint.sh` if
  lifecycle settings or field-encryption behavior changes.
- Scheduler/deployment:
  `ctf/management/commands/run_ctf_scheduler.py` only as an operational host,
  `shared/management/commands/prune_notifications.py` as command-style
  precedent, AWS `platform/terraform/modules/portal/ssm/**`,
  `platform/terraform/modules/portal/ec2/user_data.sh`,
  `scripts/portal-deploy/deploy_portal.sh`, GCP `scripts/gcp/render_runtime_env.py`,
  `platform/charts/shifter/templates/ctf-scheduler-deployment.yaml`, and
  `platform/k8s/gcp/base/ctf-scheduler-deployment.yaml` if new env or runner
  wiring is added.
- Browser compatibility:
  `static/js/terminal-guacamole.js`, `terminal-guacamole.test.js`,
  `templates/mission_control/terminal.html`, and
  `templates/ctf/participant/range.html` only if response semantics change.
  Preserve the opener URL compatibility path for clients that consume `url`
  directly from the POST response.
- Tests:
  Mission Control bootstrap status tests for single-use delivery and row
  clearing, worker-expired-before-success behavior, prune function/management
  command tests, public RDP/SSH/NGFW URL behavior, JS polling tests, AWS deploy
  script tests, and GCP renderer/manifest tests for new env settings.
- Documentation:
  update the Guacamole technical doc if the implemented behavior changes the
  currently stale direct `?data=` sequence or documents the token lifecycle.

Out of scope unless direct evidence requires it: Security Groups, NetworkPolicy,
ALB/GCLB affinity, Guacamole client replica count, range provisioning, guest
RDP/SSH readiness, CTF scoring, CTF participant invite tokens, terminal
websocket byte transport, and OIDC/direct Guacamole login.

## Gotchas And Anti-Patterns

- Do not leave `status=succeeded` with an empty `result_url` and no delivered
  marker. That makes clients, pruning, and operators infer lifecycle state from
  a cleared secret field.
- Do not return the URL and then clear it in a later best-effort operation. The
  database state must be cleared as part of the delivery transaction.
- Do not let two tabs, repeated polls, or opener plus JS polling receive the
  same token URL twice. Duplicate delivery extends the useful life of a stolen
  DB row and makes the acceptance criterion ambiguous.
- Do not rely on pruning as the only cleanup. Pruning is eventual; clearing on
  delivery is the immediate security control.
- Do not use encryption as a substitute for clearing, TTL, or pruning. An
  encrypted token-bearing row is still a durable credential escrow.
- Do not create `CTFScheduledTask` rows for Guacamole bootstrap cleanup. The
  model requires a CTF event and would conflate unrelated domains.
- Do not import `mission_control` from `ctf` directly or bypass
  `.importlinter` with hidden model access. If the scheduler process hosts the
  cleanup, keep ownership and imports at an accepted management-command or
  Mission Control boundary.
- Do not add a second request DTO, exception hierarchy, URL schema, secret
  adapter, scheduler framework, or audit table for this issue.
- Do not store generated URLs in Redis/Django cache, browser localStorage,
  analytics, audit details, or session state to avoid database persistence.
- Do not log `token=`, `data=`, full `result_url`, encrypted JSON auth payloads,
  RDP passwords, SSH private keys, or raw provider exception payloads.
- Do not hand-edit `CHANGELOG.md` for the implementation. A user-visible
  security fix should use `changelog.d/939.security.md`.

## Non-Goals

- No implementation is performed by this preflight.
- No replacement of Guacamole JSON auth, no direct Guacamole login fallback,
  and no permanent Guacamole DB-managed connection provisioning.
- No new cloud secret store, KMS grant pattern, metrics platform, queue, or
  scheduler framework unless the existing scheduler/deploy surfaces cannot
  satisfy the cadence safely.
- No range provisioning, guest credential generation, RDP password rotation,
  SSH key rotation, CTF workflow, scoring, or participant invite-token changes.
- No weakening of ADR guard, import-linter, boundary-mock policy, secret
  scanning, Terraform, Kubernetes, actionlint, CSRF, session auth, or websocket
  origin validation.
- No Ground Control requirement or traceability work; this run is issue-driven.

## Validation Expectations

Run the repository architecture gate for implementation touching this surface:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Add stack-native checks for touched files:

- `cd shifter/shifter_platform && uv run ruff check . && uv run ruff format --check .`
- `cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter`
  when imports change.
- Targeted Mission Control tests proving delivery clears `result_url`, repeated
  polls do not replay the URL, expired worker completions do not persist a URL,
  and pruning deletes delivered/expired terminal rows only.
- Deploy script, Terraform, actionlint, Helm/Kustomize, kube-linter, and
  kubeconform checks when runtime scheduler/env surfaces are touched.
