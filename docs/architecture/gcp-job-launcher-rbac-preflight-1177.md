# GCP Job Launcher RBAC Preflight (#1177)

Status: pre-implementation guidance

Date: 2026-06-27

Issue: GitHub #1177, "[Security][High] Platform service accounts can create
arbitrary Jobs in the provisioner namespace"

This is a requirement-free security hardening run. The GitHub issue title,
body, and acceptance criteria are the shipping contract. This note is not an
implementation plan.

## Scope Boundary

The security invariant is: only the validated provisioner task-runner contract
may create Jobs that run as the `provisioner` Kubernetes service account in the
`shifter-jobs` namespace.

The fix must close the Kubernetes authorization/admission gap without replacing
the existing cloud task-runner abstraction. It may use either a narrow
job-launcher service or a Kubernetes admission policy, but the outcome must be
the same: a token from a general platform workload cannot successfully submit an
arbitrary privileged provisioner Job.

Do not turn this into a new workflow engine, task schema, or provider
abstraction. The existing `shared.cloud` task-runner contract remains the
canonical application boundary.

## Architecture Decisions

- Keep `shifter/shifter_platform/shared/cloud/gcp/task_runner.py` as the
  canonical builder for GKE provisioner Jobs. It already owns the Job shape,
  labels, container args, service-account assignment, security context,
  writable volume set, sensitive-env Secret flow, ownerReference cleanup, and
  task-id/status mapping.
- Keep `shared.cloud.PROVISIONER_CONTAINER_NAME` as the cross-provider
  provisioner identity. Do not duplicate the `"pulumi-provisioner"` string in a
  policy, launcher, chart, or test without tying it back to this incumbent.
- The Kubernetes control must validate the built Job's non-secret contract:
  namespace, `serviceAccountName`, container name, image, allowed command
  families, required Shifter labels, restart/backoff/TTL posture, Pod/container
  security posture, and absence of extra containers or privilege additions.
- Secrets are not a policy input. Admission or launcher validation may check
  that sensitive values are referenced through Secret refs, but must not compare
  or log secret values.
- `platform/k8s/gcp/base` and `platform/charts/shifter` are both deployment
  sources. Any RBAC, ServiceAccount, admission, or launcher manifest change must
  keep the static base and Helm-rendered output equivalent.
- If a launcher service is chosen, keep it as a narrow infrastructure adapter
  behind the existing task-runner path. It should accept only the existing
  `run_task`-level inputs or an even narrower provisioner request shape, validate
  them, and submit the canonical Job. It must not become a general "create any
  Kubernetes object" endpoint.
- If admission policy is chosen, make the policy deny by default for Jobs that
  use `serviceAccountName: provisioner` and allow only the canonical provisioner
  template. Direct `jobs.create` access is acceptable only if admission makes
  arbitrary Jobs non-persistent and tests prove the denial.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1177 |
| --- | --- | --- |
| Task abstraction | `shared.cloud.types.TaskRunner`, `shared.cloud.get_task_runner()` | Do not add a second orchestration interface for provisioner work. |
| Provisioner identity | `shared.cloud.PROVISIONER_CONTAINER_NAME` | Reuse this constant as the source of truth for provisioner container identity. |
| Engine dispatch | `engine/ecs.py` `runner.run_task(... container_name=PROVISIONER_CONTAINER_NAME ...)` | Preserve the existing range/NGFW command construction and argument validation. |
| GCP Job builder | `shared/cloud/gcp/task_runner.py` | Extend or constrain this builder; do not hand-roll a parallel Job manifest schema. |
| Sensitive env policy | `shared/cloud/sensitive_env.py` and `tests/shared/cloud/test_sensitive_env.py` | Keep sensitive values in per-Job Secrets and out of Job specs, logs, argv, and policy fixtures. |
| Runtime env binding | `config/_cloud.py`, `config/env-manifest.json`, `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/deploy.py` | Reuse `ENGINE_TASK_NAMESPACE`, `ENGINE_TASK_IMAGE`, and `ENGINE_TASK_SERVICE_ACCOUNT_NAME`; new knobs need manifest/tests. |
| Kubernetes sources | `platform/k8s/gcp/base/**`, `platform/charts/shifter/**` | Keep base and Helm output in lockstep. |
| Current RBAC invariant test | `tests/platform/test_gcp_job_launcher_manifests.py` | Extend this file or the same test style for RBAC/admission invariants instead of adding a disconnected checker. |
| Platform IAM | `platform/terraform/gcp/modules/portal/iam/main.tf` | Do not broaden Workload Identity or GCP IAM while fixing Kubernetes RBAC. |
| K8s guardrails | ADR-006 in `docs/adr/index.yaml`, `.kube-linter.yaml`, kubeconform, ADR guard | Preserve PSS, default-deny NetworkPolicy, and rendered-manifest validation. |
| Import boundaries | `.importlinter` | Keep any Python policy/launcher helper in `shared` or provider infrastructure; do not make app layers import each other. |
| Error/log patterns | `shared.cloud.exceptions.CloudTaskError`, module loggers, `shared.log_sanitize` | Use existing error envelopes and sanitized logs; no new exception hierarchy for admission denial. |

## Cross-Cutting Layers

- Auth surface: the current token-bearing workloads are `portal`,
  `worker-engine`, and `ctf-scheduler` in `shifter-platform`; the privileged
  runtime identity is the `provisioner` service account in `shifter-jobs`.
  Implementation must prevent those platform tokens from creating arbitrary
  Jobs that run as `provisioner`. If a launcher service is introduced, its
  caller authentication and NetworkPolicy must be explicit and scoped to the
  existing job-launching workloads.
- Kubernetes RBAC/admission: the final control belongs at the Kubernetes API
  boundary. The design must either remove raw `jobs.create` from general
  platform service accounts or prove that admission denies every non-canonical
  Job using `serviceAccountName: provisioner` before persistence.
- Workload Identity and GCP IAM: `portal`, `workers`, and `provisioner` GCP
  service accounts are managed in `platform/terraform/gcp/modules/portal/iam`.
  Do not grant extra GCP roles to compensate for Kubernetes authorization
  failures. Terraform changes must pass TFLint and keep role membership tied to
  the existing KSA-to-GSA map.
- Runtime env shape: GCP deploy renders `ENGINE_TASK_NAMESPACE=shifter-jobs`,
  `ENGINE_TASK_SERVICE_ACCOUNT_NAME=provisioner`, and immutable
  `ENGINE_TASK_IMAGE` values through the existing renderers. Admission or
  launcher configuration should derive from those seams or a single adjacent
  policy value, not a duplicated env contract.
- Secret handling: `split_env()` and per-Job Kubernetes Secrets are the existing
  secret boundary. Sensitive env values, Secret payloads, service-account
  tokens, Identity Platform keys, database passwords, Redis AUTH, and GDC access
  material must not appear in ConfigMaps, rendered policy fixtures, process
  argv, logs, admission error messages, or test snapshots.
- Config validators: Kubernetes changes must satisfy ADR-006 restricted Pod
  Security and NetworkPolicy rules, `kustomize build` plus kube-linter,
  kubeconform, and chart render tests. Python changes under
  `shifter_platform` must satisfy import-linter and focused unit tests.
- OS/process exposure: keep bootstrap/deploy command execution on argv arrays
  and do not pass rendered Job specs or secrets through shell strings. Local
  provisioner mode in `engine/ecs.py` is a developer fallback and must not be
  used as a production bypass for the Kubernetes control.
- Error envelopes: admission or launcher denials should surface as
  `CloudTaskError` from the task-runner boundary with fixed, operation-labeled
  messages. Do not include full Kubernetes objects, Secret bodies, tokens, or
  raw provider response bodies in user-facing errors.
- Observability: use Kubernetes audit/admission logs, GCP audit logs, and the
  existing module logger style. Log task ids, namespaces, image references,
  command family, and policy decision names only; do not log env payloads or
  full request objects.

## Extensibility Seam

The seam is a small provisioner Job policy/profile, not a new task framework.
It should be parameterized around the fields the next reasonable variation
would change:

- allowed submitter identities
- target namespace and `serviceAccountName`
- provisioner container name
- allowed image repository/root or digest policy
- allowed command families such as range and NGFW operations
- required labels/annotations used for correlation and cleanup

Keep the policy close to the GCP task-runner/manifest tests so adding a future
non-provisioner GKE task profile requires one explicit profile/test update, not
copying a second Job schema through Terraform, Helm, Django settings, and
admission fixtures.

## Whole-Repo Scope

Likely in scope for the implementation:

- `platform/k8s/gcp/base/rbac-job-launcher.yaml`
- `platform/k8s/gcp/base/serviceaccounts.yaml`
- `platform/k8s/gcp/base/networkpolicies.yaml` if a launcher service is added
- `platform/charts/shifter/templates/rbac-job-launcher.yaml`
- `platform/charts/shifter/templates/serviceaccounts.yaml`
- `platform/charts/shifter/templates/networkpolicies.yaml` if a launcher
  service is added
- `platform/charts/shifter/values*.yaml` for policy or launcher parameters
- `shifter/shifter_platform/shared/cloud/gcp/task_runner.py`
- `shifter/shifter_platform/shared/cloud/__init__.py`
- `shifter/shifter_platform/shared/cloud/sensitive_env.py` only if the env
  contract changes
- `shifter/shifter_platform/engine/ecs.py` only if dispatch needs a narrow
  policy seam
- `shifter/shifter_platform/config/_cloud.py`,
  `shifter/shifter_platform/config/env-manifest.json`,
  `scripts/gcp/render_runtime_env.py`, and `scripts/bootstrap/deploy.py` only if
  new runtime knobs are unavoidable
- `platform/terraform/gcp/modules/portal/iam/main.tf` only if Workload Identity
  binding changes are required
- Tests under `shifter/shifter_platform/tests/shared/cloud/`,
  `shifter/shifter_platform/tests/engine/ecs/`, `shifter/shifter_platform/tests/platform/`,
  `scripts/gcp/tests/`, and `scripts/bootstrap/tests/` matching the touched
  seams

Usually out of scope:

- AWS ECS task-definition/IAM redesign.
- New domain DTOs, repositories, controllers, exception packages, or workflow
  services.
- Broad GCP IAM changes, node IAM changes, or provisioner Secret Manager
  permission changes.
- Reworking CTF, CMS, Mission Control, queue, storage, or range-domain
  authorization.

## Gotchas And Anti-Patterns

- Do not close the issue by changing only Python builder validation while
  leaving general platform tokens able to submit arbitrary Jobs directly to the
  Kubernetes API.
- Do not close the issue by changing only RBAC subject names while preserving a
  broad `jobs.create` binding with no launcher/admission constraint.
- Do not trust labels or annotations supplied by an untrusted Job creator unless
  the control also proves the creator cannot choose arbitrary spec fields.
- Do not create a duplicate provisioner Job schema in Helm, Terraform, an
  admission fixture, and Python. One canonical builder plus one policy/profile
  is enough.
- Do not weaken restricted Pod Security, NetworkPolicy default-deny,
  automount-token tests, Workload Identity scoping, kube-linter, kubeconform,
  ADR guard, or import-linter to make the fix fit.
- Do not treat NetworkPolicy as the authorization boundary. It can limit access
  to a launcher service, but it cannot stop a pod with a valid Kubernetes token
  from calling the apiserver if RBAC/admission permits it.
- Do not put sensitive env values, Secret bodies, Kubernetes bearer tokens, or
  rendered manifests with secrets into logs, GitHub step summaries, test
  snapshots, Terraform outputs, ConfigMaps, or process argv.
- Do not conflate the `workers` KSA/GSA with the privileged `provisioner` KSA/GSA.
  Platform workers may request work; the provisioner identity performs the
  privileged runtime work.

## Non-Goals

- No implementation in this preflight note.
- No new formal Ground Control requirement.
- No new generic job-launching product surface.
- No replacement of `shared.cloud` provider factories or the ECS-compatible
  `TaskRunner` protocol.
- No redesign of provisioner command semantics, range/NGFW workflows, GDC guest
  networking, Secret Manager bundles, Redis, database, Identity Platform, or
  Cloud Armor.
- No public proof-of-concept payloads or private attack-path details in docs,
  tests, comments, or PR text.

## Validation

For any implementation touching Kubernetes, GCP Terraform, workflows, hooks, or
`shifter/shifter_platform`, run the repo-required guardrails for the touched
surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

Add focused tests that prove:

- platform service accounts cannot create arbitrary Jobs that use
  `serviceAccountName: provisioner`
- only the canonical provisioner template is admitted or launched
- Helm-rendered and static base manifests express the same RBAC/admission
  posture
- sensitive provisioner env values remain Secret-backed and absent from Job
  literal env values
