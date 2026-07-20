# GCP Provisioner Launch Boundary Preflight (#1518)

Status: implemented by the dedicated launch-intent worker and matching Kubernetes identity boundary

Date: 2026-07-12

Issue: GitHub #1518, "REV1 Security: isolate provisioner Job and Secret
mutation privileges"

This is a requirement-free security hardening run. The issue title, body, and
acceptance criteria are the shipping contract. This note fixes the ownership
boundary; it is not an implementation plan and contains no withheld abuse path.

## Boundary And Decisions

One dedicated `provisioner-launcher` workload identity must be the sole
Kubernetes API principal that creates provisioner Jobs and creates, patches, or
deletes their ephemeral sensitive-env Secrets. The launcher identity and the
Job runtime identity are deliberately different:

- `provisioner-launcher` submits and observes the canonical Job and owns the
  per-Job Secret lifecycle. It must not receive the provisioner's cloud
  mutation roles.
- `provisioner` is assigned only to the submitted Job and retains the existing
  Workload Identity mapping needed to mutate range infrastructure. It must not
  receive Kubernetes Job/Secret mutation RBAC.
- `portal`, `ctf-scheduler`, and general `workers` may request provisioning
  through the application workflow, but must have neither the launcher Role
  nor an auto-mounted Kubernetes API token merely to request work.

The existing synchronous in-process route is the central design constraint:
`cms.services` currently calls `engine.services` directly, and those services
call `engine.ecs` / `GCPTaskRunner` in the portal or scheduler process. Narrowing
RBAC without first moving the final launch operation behind the dedicated
worker would break range launch. The implementation must preserve the existing
domain validation and persistence in CMS/engine, but make the final
`GCPTaskRunner.run_task()` call executable only by the dedicated engine launch
worker.

Use the existing engine worker separation and transactional-outbox conventions
for that handoff. A database-backed launch-intent queue is deliberate: directly
publishing to a cloud queue alongside the domain-state transaction would create
an unprotected dual write. The durable row must contain a minimal,
runtime-validated launch intent (operation/resource family plus canonical
request id and a separate operation-generation binding), not a serialized
hydrated `RequestSpec`, provisioner environment, Secret body, or Kubernetes
object. Engine state already keyed by `request_id` is the source from which the
launcher reconstructs the existing `engine.ecs` call. Do not conflate launch
intents with the existing provisioner-produced `RangeEventOutbox` event stream,
whose ownership and retry semantics differ.

`shared.cloud.gcp.task_runner.GCPTaskRunner` remains the sole Job and per-Job
Secret builder. Do not introduce a launcher HTTP API, a second Job DTO, a
second sensitive-env classifier, or provider-specific domain workflow.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| User/domain authorization | CMS service validation and ownership checks in `cms/services/_range_create.py`, `_range_destroy.py`, `_ngfws.py`; shared `RequestSpec`/range schemas | Moving launch must not bypass or duplicate these checks. |
| Engine persistence and idempotency | `engine.services`, `Request.request_id`, `Range` task-id fields, transaction patterns, and the outbox/drainer pattern in `engine.models.RangeEventOutbox` | Persist one launch intent per request/operation; redelivery must not launch a second Job. Reuse the pattern, not the event table or event semantics. |
| Internal transport | `RangeEventOutbox` locking/backoff conventions, management-command workers, and the provider-neutral task adapter | Keep the launch handoff database-transactional and worker-owned; do not add a DB-plus-cloud-queue dual write or reuse the status-event table. Runtime-validate the persisted command at both enqueue and consume boundaries. |
| Task abstraction | `shared.cloud.types.TaskRunner`, `shared.cloud.get_task_runner()`, `engine/ecs.py` | Only the dedicated worker invokes GCP `run_task`; keep AWS behind the same protocol. |
| Job and Secret shape | `shared/cloud/gcp/task_runner.py`, `shared.cloud.PROVISIONER_CONTAINER_NAME` | One builder owns labels, args, ServiceAccount, security contexts, volumes, env refs, ownerReference installation, unwind, status, and task ids. |
| Sensitive env | `shared/cloud/sensitive_env.py`, `_GCP_PROVISIONER_ENV_KEYS`, `tests/shared/cloud/test_sensitive_env.py` | Sensitive values remain per-Job Secret-backed and never enter queue payloads, Job literal env, ConfigMaps, argv, logs, or snapshots. |
| Errors and logs | `CloudTaskError`, `CloudQueueError`, `shared.log_sanitize`, `shared.api.errors`, module loggers | Keep the existing hierarchy/envelope. Expose a stable dispatch failure; do not forward raw Kubernetes response bodies or Secret data. |
| Kubernetes identity/policy | base and Helm `serviceaccounts.yaml`, `rbac-job-launcher.yaml`, `validatingadmissionpolicy-provisioner-jobs.yaml` | RBAC and admission must name the same dedicated launcher principal and stay equivalent across both deployment sources. |
| Runtime config | `config/_cloud.py`, `config/env-manifest.json`, `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/gcp_control_plane.py`, chart values | Keep `ENGINE_TASK_*` as the runtime Job contract. The launcher KSA is deployment identity, not another spelling of `ENGINE_TASK_SERVICE_ACCOUNT_NAME` (the Job's `provisioner` KSA). |
| Cloud identity | `platform/terraform/gcp/modules/portal/iam/main.tf` workload/resource matrix and bootstrap Helm annotation renderer | Give the launcher only its worker/runtime-secret and queue needs. Never map it to the privileged provisioner GSA or copy provisioner roles. |
| Platform hardening | ADR-006, restricted PSS, default-deny NetworkPolicy, `.kube-linter.yaml`, kubeconform, ADR guard, `.importlinter` | Identity splitting must not weaken existing pod, network, import, or deployment checks. |

## Cross-Cutting Security Layers

The intended design must pass every layer below.

1. **External auth and domain validation.** DRF/session/token permissions and
   CMS ownership/launchability validation continue to authorize the user's
   request. A queue message is internal work, not proof of end-user authority;
   it references already-authorized, persisted engine state.
2. **Durable-message shape.** The engine consumer must parse a discriminated,
   versioned, bounded message and validate its operation and request id before
   lookup. Reuse shared schemas for referenced domain state. Do not mistake the
   existing `TypedDict` payloads or `parse_sns_message()` for runtime validation.
3. **Kubernetes authentication.** Only the engine launcher Deployment mounts
   the `provisioner-launcher` KSA token. Portal, scheduler, and non-launching
   workers set `automountServiceAccountToken: false`. A separate GSA, if needed
   for startup secrets/queue access, follows the Terraform IAM matrix and is
   not the Job's privileged `provisioner` GSA. The provisioner Job uses GKE
   Workload Identity but does not mount a Kubernetes API token.
4. **Kubernetes RBAC.** One namespaced launcher Role grants only required Job
   create/get/delete and Secret create/patch/delete verbs;
   one RoleBinding names only `provisioner-launcher`. Portal, scheduler,
   `workers`, and `provisioner` have no provisioner Secret mutation or Job
   launch grant. Split read-only observation into a separate Role only if a
   demonstrated caller needs it.
5. **Admission.** The provisioner ValidatingAdmissionPolicy must require the
   same launcher username as RBAC and continue to fail closed on the canonical
   namespace, runtime KSA, pinned runtime image, entrypoint/args, explicit env
   list and Secret refs, container count/name, labels, volumes/mounts,
   backoff/TTL, and pod/container security posture. The current policy's
   literal-presence tests are not semantic CEL tests and its env contract is
   looser than the builder; implementation must close those drift gaps rather
   than declaring the existing comments sufficient.
6. **Secret handling and lifecycle.** `split_env()` remains authoritative.
   `GCPTaskRunner` creates a deterministic per-intent Secret before the Job,
   recovers it after ambiguous create responses, patches it with the Job
   ownerReference, and unwinds newly created resources on definitive failure.
   Redelivery recreates a missing deterministic Secret or reasserts its exact
   labels and current payload before repairing ownership. Admission messages,
   audit logs, exception text, and queue payloads contain no secret values;
   tests use synthetic values only. Secret names remain fingerprints in
   application logs.
7. **Configuration validators.** New deployment knobs must be represented in
   chart values/bootstrap render tests; new application env only when
   unavoidable, then also in `_cloud.py`, `env-manifest.json`, both runtime
   renderers, and their tests. Base, default Helm, and environment-specific
   Helm renders must preserve the same identity matrix.
8. **OS/process exposure.** Kubernetes tokens exist only in the launcher pod's
   projected filesystem. Secrets are never shell arguments, environment
   render output, Helm values, Terraform outputs, or subprocess command text.
   Local subprocess mode remains an explicit development path, not a
   production bypass.
9. **Error and observability envelopes.** Queue and Kubernetes failures remain
   `CloudQueueError`/`CloudTaskError` internally and map to the existing stable
   user-facing failure state. Log request id, operation, task id, namespace,
   policy name, and sanitized/fingerprinted identifiers; do not persist or
   return raw admission bodies, Secret objects, tokens, or hydrated specs.
   Kubernetes and GCP audit logs provide principal-level evidence.

## Implemented Enforcement

GCP callers now persist a versioned, runtime-validated, secret-free
`ProvisionerLaunchIntent` instead of calling the Kubernetes task runner in the
portal, scheduler, or general engine worker process. Each intent stores the
domain projection's operation-generation UUID separately from its minimal
payload, and the worker locks and compares that generation before dispatch so
a stale intent cannot become authorized again when a lifecycle status repeats.
The dedicated `worker-provisioner-launcher` drains those intents by claiming
one row immediately before dispatch, with row locking, recoverable RUNNING
leases, permanent operation idempotency, bounded retry/backoff, per-intent
heartbeat refresh, and sanitized error storage. Before dispatch it reloads the
referenced engine Request and Range/NGFW projection and rejects an operation
that current domain state does not authorize. Each projection retains a stable
operation-family generation UUID, so unrelated model saves cannot create a new
intent while a transition is in flight, and a database uniqueness constraint
allows only one intent for each generation even across legacy/request command
aliases. The generation update and intent insert
commit in one database transaction, and the drainer retains the projection lock
through provider acceptance so a newer generation cannot overtake a validated
launch. Kubernetes requests are time-bounded below the recovery lease, so this
linearization cannot hold a domain row indefinitely. The intent UUID reserves a
deterministic provider task reference; GCP dispatch uses create-or-observe Job
semantics, so a crash after API-server acceptance cannot create a second Job;
observed Jobs must match the reserved identity annotation, image, command,
runtime service account, and deterministic Secret before they are accepted as
recovery. Ambiguous creates reconcile the accepted Job's effective Secret
identity and never unwind a previously accepted Job on a transient patch
failure. Ambiguous Secret outcomes are recovered through the deterministic
per-intent name; ambiguous Job outcomes preserve the Secret until
non-acceptance is definitive;
failed lifecycle episodes close their generation, and dead-lettered generations
rotate on the next authorized request, so a deliberate same-operation retry
creates new work without turning duplicate delivery into a second launch;
when dispatch retries exhaust, the DLQ transition also moves only the
still-current Range or NGFW projection to the existing sanitized failure state
(and emits the standard Range status event). Generation checks prevent a stale
intent from overwriting a newer lifecycle episode, while lease fencing prevents
a worker whose claim expired mid-dispatch from overwriting its successor's
result;
only that Deployment uses the `provisioner-launcher` service account and mounts
its Kubernetes token.

The base and Helm deployment sources bind `job-launcher` only to
`provisioner-launcher`. Portal, CTF scheduler, and general workers are tokenless
and have no Job/Secret mutation binding. The fail-closed admission policy names
the same launcher principal while continuing to constrain the privileged
runtime service account, image, command family, exact literal and Secret-backed
environment-name allowlists (including duplicate rejection), literal values
pinned to `platform-runtime`, required database bindings, deterministic Secret
references, single-execution Job controls, exact bounded volumes/mounts, and
pod/container security context. Lifecycle hooks and all container probe fields are absent, so
no auxiliary command-execution surface can bypass the canonical argv grammar.
The Helm launcher username, runtime service account, jobs/platform namespaces,
runtime ConfigMap, RBAC, and admission binding render from the same values.
Default-deny egress is opened only from the launcher pod to the GKE service CIDR
on TCP/443; the generated Kustomize and Helm paths enforce the same boundary.
Tests evaluate the rendered CEL with a compatible CEL
runtime rather than a separately implemented Python oracle. `GCPTaskRunner`
remains the sole Job/Secret builder and the
privileged Job continues to run as the distinct `provisioner` identity.
It receives no Kubernetes API token.

## `resourceNames` And Equivalent Constraints

Kubernetes RBAC cannot use `resourceNames` to constrain `create`, and the
current Jobs and Secrets receive deterministic per-intent names that are not
known at deployment time.
Pretending a prefix is an RBAC resource-name constraint would be ineffective.
Use `resourceNames` for any truly fixed named read/update target that remains,
and use the equivalent controls for dynamic objects: a dedicated namespaced
principal, no competing RoleBindings, admission checks on creator and canonical
object shape/labels/Secret references, and ownerReference garbage collection.
Never grant `deletecollection`, wildcard resources, wildcard verbs, Secret
`get/list/watch`, or Role/RoleBinding/ServiceAccount mutation to the launcher.

## Extensibility Seam

The seam is a deployment-level **launch profile**, not a new generic job
framework. Its parameters are launcher KSA/username, target namespace, runtime
KSA, provisioner container name, pinned image parameter, allowed operation
families, required labels, allowed env names/Secret-ref form, and Job security
posture. Helm values/bootstrap own deploy-time identity names; the existing GCP
task builder owns object construction; policy tests prove both agree. Adding a
future distinct privileged task means adding a separate explicit profile,
Role, and policy binding, not widening this one.

## Adversarial Evidence Required

- Offline effective-authorization tests must compute the rendered RoleBinding
  subject/verb/resource matrix and prove portal, scheduler, general workers,
  and provisioner cannot mutate Secrets or launch provisioner Jobs, while the
  launcher has exactly the required verbs.
- Admission tests must evaluate allowed and denied requests semantically (or
  exercise API-server server-side dry-run), including wrong caller, runtime
  KSA, image, command/args, env/Secret ref, sidecar/init container, volume,
  labels, and security posture. String-searching CEL expressions is not enough.
- Deployment verification should use non-persisting `kubectl auth can-i --as`
  checks for all principals and server-side dry-run for representative Job and
  Secret denials. Tests and logs must describe expected denials without
  publishing withheld exploit detail.
- Static-base and Helm-rendered resources, default and supported environment
  values, Terraform KSA/GSA bindings, token automount, sensitive-env routing,
  ownerReference unwind, and duplicate-message idempotency remain regression
  surfaces.

## Gotchas And Anti-Patterns

- Do not only rename the `workers` RoleBinding; portal and scheduler currently
  execute the launch path in-process, so that change alone is an outage.
- Do not serialize hydrated `RequestSpec`, NGFW credentials, provisioner env,
  Secret bodies, or Kubernetes manifests onto the engine queue.
- Do not perform a database write plus queue publish as an unprotected dual
  write, and do not acknowledge before durable launch state is recorded.
- Do not reuse the status-event outbox table for launch commands or invent a
  second exception hierarchy, validation schema, task runner, or workflow
  engine.
- Do not bind the launcher KSA to the provisioner GSA, allow the provisioner KSA
  to create Jobs/Secrets, or leave portal/scheduler tokens mounted after their
  RBAC is removed.
- Do not treat labels, name prefixes, NetworkPolicy, PSS, image pinning alone,
  or a structural CEL string test as authorization.
- Do not broaden GCP IAM, Kubernetes wildcard verbs/resources, Secret read
  access, admission failure policy, or CI exceptions to make the split pass.
- Do not expose raw provider/admission errors through Range error text, API
  responses, audit context, or worker logs.

## Non-Goals And Implementation Boundary

- This implementation changes the GCP launch handoff and identity boundary; it
  does not authorize unrelated manifest, identity, or workflow expansion.
- No AWS ECS/IAM redesign, provisioner cloud-role redesign, dynamic Secret
  Manager project/broker work (#1586), or range/NGFW command redesign.
- No new public launcher API, generic Kubernetes object broker, task schema,
  repository layer, controller family, or user-visible workflow.
- No change to end-user authorization, scenario validation, sensitive-env
  classification semantics, or provisioner Job runtime identity. The
  provider-neutral `TaskRunner` receives only an optional idempotency identity;
  its dispatch/status contract and provider ownership remain unchanged.
