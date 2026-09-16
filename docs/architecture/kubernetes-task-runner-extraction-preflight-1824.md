# Provider-Neutral Kubernetes Task Runner Preflight (#1824)

Status: pre-implementation guidance

Date: 2026-08-01

Issue: GitHub #1824, "runtime: extract a provider-neutral Kubernetes task runner"

This is a requirement-free maintenance run. The GitHub issue title, body, and
acceptance criteria are the shipping contract. This note is not an
implementation plan.

No ADR change is needed if the implementation stays inside ADR-011's
root-configured backend-capability model, ADR-044's backend-neutral Helm package
boundary, and the existing provisioner Job security decisions. Update the ADR
registry only if the implementation changes an enforceable policy, public
backend-selection model, or Kubernetes admission/RBAC contract.

## Scope Boundary

Extract the Kubernetes Job mechanics that are not GCP concepts:

- Kubernetes client loading and API invocation wrapper.
- Job name generation/parsing, create-or-observe lifecycle, ambiguous-create
  recovery, foreground delete/interrupt, and status-to-`TaskRunner` mapping.
- Pure Job/Secret manifest construction where provider choices are injected as
  data or strategy objects.

Keep these GCP/provider-specific concerns outside the neutral core:

- Workload Identity annotations and KSA-to-GSA ownership.
- The `provisioner-launcher` submitter identity, `provisioner` runtime identity,
  GCP RBAC/admission resources, and `shifter.dev/task-runner: gcp` labels.
- GCP runtime env projection and its admission allowlists.
- Secret projection policy and naming where it is part of the GCP admission
  contract.

`shared.cloud.gcp.task_runner.GCPTaskRunner` should remain the GCP adapter and
backward-compatible import surface. The neutral Kubernetes package should be an
internal implementation dependency, not a new public task orchestration API.

## Architecture Decisions And Guardrails

- Reuse `shared.cloud.types.TaskRunner` and `shared.cloud.get_task_runner()`.
  Do not add a second task-runner protocol, backend selector, queue, launcher
  DTO, controller, repository, or workflow service.
- Put neutral code under the cloud-neutral `shared.cloud` layer, for example a
  `shared.cloud.kubernetes` package, and keep provider adapters as thin
  injectors. The neutral package must have no `shared.cloud.gcp.*` imports and
  no AWS imports.
- Keep provider SDK imports lazy. The Kubernetes Python client is an optional
  runtime dependency for Kubernetes-backed flows and must not be imported at
  module import time for AWS-only processes.
- The neutral core must not read Django settings directly. Resolve
  `ENGINE_TASK_*`, namespace, service account, image pull policy, backoff/TTL,
  labels, annotations, and runtime profile choices in the provider adapter and
  pass them into the core.
- Preserve `shared.cloud.PROVISIONER_CONTAINER_NAME` as the cross-provider
  provisioner container-name contract. The neutral core should receive a
  container name or profile; it should not own or redefine
  `"pulumi-provisioner"`.
- Preserve current GCP behavior externally: task ids, idempotent naming,
  Secret ownerReference/unwind semantics, foreground interrupt dispositions,
  status payload shape, logging safety, and `CloudTaskError` boundaries.
- Keep non-provisioner Kubernetes tasks on their current minimal contract.
  Provisioner hardening is not a generic default unless a reviewed runtime
  profile explicitly opts in and tests prove compatibility.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse for #1824 |
| --- | --- | --- |
| Backend/capability selection | `installation.contract.BackendCapability.TASK_RUNNER`, `installation.registry`, `shared.cloud.__init__` | Continue resolving task delivery from validated backend capability. Do not create `backend: kubernetes`, `backend: aws-eks`, or an env-driven runner selector. |
| Task interface | `shared.cloud.types.TaskRunner`, `CloudTaskError` | Keep the protocol and exception envelope. A Kubernetes helper may raise internal errors, but provider adapters translate at the existing boundary. |
| Provisioner identity | `shared.cloud.PROVISIONER_CONTAINER_NAME`, `engine.ecs` dispatch tests, AWS ECS task definition test | Keep the constant cloud-neutral and use it at dispatch. Do not duplicate the string in a new profile without a drift test. |
| Launch authorization and argv grammar | `engine.launch_intents`, `engine.ecs.dispatch_provisioner_command`, `ProvisionerLaunchIntent` | Preserve identifier-only commands and idempotency. Do not move authorization, generation fencing, or command validation into the Kubernetes core. |
| Runtime env forwarding | `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, `installation.runtime_inventory`, `config/env-manifest.json`, `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/gcp_control_plane.py` | Use the existing GCP projection. Any new key must update every manifest/inventory/test surface; this extraction should not need new env keys. |
| Sensitive env classification | `shared.cloud.sensitive_env.split_env`, `tests/shared/cloud/test_sensitive_env.py` | Reuse the classifier. Do not add a provider-local sensitive-name list or route secret values through literal env. |
| GCP Job/Secret semantics | Current `shared/cloud/gcp/_task_runner/*` modules and tests | Move behavior, not concepts. Keep deterministic Secret recovery, ownerReference repair, cleanup/unwind, request timeouts, and create-or-observe semantics intact. |
| Kubernetes admission/RBAC | `platform/k8s/gcp/base/*`, `platform/charts/shifter/templates/*`, `tests/platform/test_gcp_job_launcher_manifests.py` | GCP policy must keep mirroring the GCP adapter's provisioner profile. If comments or paths change, update base and chart together. |
| Helm packaging | ADR-044, `platform/charts/shifter/values.schema.json`, `capabilities.kubernetesJobLauncher` | A neutral code module does not mean the chart renders Job-launch resources for every provider. Keep AWS/EKS disabled unless a separate Kubernetes runner contract enables it with tests. |
| Import boundaries | `.importlinter`, layer-import checks, ADR-001 | Keep shared contracts under `shared`; product layers call public facades and provider-neutral protocols only. |
| Observability and redaction | module loggers, `shared.log_sanitize.safe_log_fingerprint`, `CloudTaskError` | Log task refs, namespaces, image identities, decision names, and safe fingerprints only. Do not log env maps, Secret bodies, kubeconfigs, tokens, or raw provider payloads. |

## Cross-Cutting Layers The Intended Design Must Pass

1. **Root/backend config shape.** `config._runtime_env.resolve_cloud_provider`,
   `installation.loader`, closed backend settings models, and
   `BackendCapability.TASK_RUNNER` remain the backend gate. The design satisfies
   this by leaving provider selection in `shared.cloud.get_task_runner()` and
   injecting Kubernetes wiring from the selected adapter.
2. **Runtime env and Helm value shape.** `config._cloud`, `config/env-manifest.json`,
   GCP renderers, `platform-runtime`, and `values.schema.json` own
   `ENGINE_TASK_NAMESPACE`, `ENGINE_TASK_IMAGE`,
   `ENGINE_TASK_SERVICE_ACCOUNT_NAME`, and image pull/backoff/TTL settings. The
   neutral core receives resolved values and does not introduce a parallel env
   schema.
3. **Launch authorization and parser gates.** External auth, domain validation,
   `ProvisionerLaunchIntent`, and `engine.launch_intents.validate_provisioner_command`
   stay before `TaskRunner.run_task`. The Kubernetes core accepts only the
   already validated `list[str]` command and task identity.
4. **Kubernetes authentication and RBAC.** The GCP launcher KSA is the only
   token-bearing workload with Job/Secret mutation grants in `shifter-jobs`.
   The neutral core does not create identities or broaden Role/RoleBinding
   subjects; GCP adapter wiring continues to run under that deployment
   identity.
5. **Admission policy.** `restrict-provisioner-jobs` in both static base and
   Helm render continues to fail closed on launcher username, runtime service
   account, image, entrypoint/args grammar, literal/Secret env allowlists,
   container count/name, labels, bounded volumes/mounts, backoff/TTL, and
   pod/container security. The GCP adapter's injected profile must still render
   exactly what this policy admits.
6. **Secret-handling surface.** `split_env()` decides sensitive versus literal
   env. Sensitive values go through a pluggable projection strategy that, for
   current GCP behavior, creates per-intent Kubernetes Secrets, references them
   with `secretKeyRef`, repairs ownerReferences, and unwinds on failure. Secret
   values never enter argv, ConfigMaps, Helm values, logs, test snapshots, or
   `CloudTaskError` text.
7. **Pod Security and network policy.** ADR-006, PSS labels, default-deny
   NetworkPolicies, no API token in provisioner Jobs, read-only root filesystem,
   non-root identity, drop-ALL capabilities, and bounded writable volumes remain
   part of the GCP provisioner profile. Generic defaults must not silently relax
   or apply those fields to unrelated tasks.
8. **OS/process exposure.** The implementation continues to use the Kubernetes
   Python client and argv arrays. It must not shell out with rendered Job specs,
   kubeconfigs, credentials, or secret payloads in command arguments or
   interpolated shell strings.
9. **Error envelopes and public surfaces.** Provider adapter failures remain
   `CloudTaskError` internally and map through existing Engine status/failure
   paths. Public HTTP, WebSocket, event, audit, and worker logs must not expose
   raw Kubernetes response bodies, env maps, Secret names beyond safe
   fingerprints, tokens, or provider diagnostics.
10. **Validation gates.** Python import boundaries, focused
    `tests/shared/cloud/*` runner tests, `tests/platform/test_gcp_job_launcher_manifests.py`,
    Helm/base admission parity, ADR guard, kube-linter, kubeconform, and any
    touched runtime-render tests remain the external validators of the moved
    code.

## Extensibility Seam

The durable seam is a Kubernetes task profile injected into the neutral runner.
It should be parameterized around the fields a future Kubernetes-backed provider
or task kind would legitimately vary:

- namespace and task id/name strategy;
- launcher identity and target runtime service account;
- runner label value and Shifter labels/annotations;
- image, image pull policy, backoff, TTL, and single-execution controls;
- command-family/admission profile name, without moving command validation out
  of Engine;
- env classifier and secret projection strategy;
- pod/container security posture and writable-volume profile;
- ownerReference/unwind policy for any generated Secret-like object; and
- status/interrupt identity projection.

This is not a public backend-composition mode. The next obvious variation is an
AWS/EKS Kubernetes Job runner using IRSA, but ADR-044 explicitly keeps
`capabilities.kubernetesJobLauncher: false` for AWS today. Adding that future
runner should mean adding an AWS adapter/profile and matching chart/admission
tests, not editing domain dispatch, inventing `aws-eks`, or widening the GCP
provisioner policy.

## Gotchas And Anti-Patterns

- Do not move GCP code into `shared.cloud.kubernetes` by path alone while
  retaining hidden `shared.cloud.gcp.*` imports, GCP labels, or Django settings
  reads inside the neutral package.
- Do not rename `shifter.dev/task-runner: gcp`, `pulumi-provisioner`, Secret
  name prefixes, labels, volume names, annotations, or task-id formats as part
  of this extraction.
- Do not make `service_account_name`, Workload Identity, IRSA, or Secret
  projection global Kubernetes defaults. They are provider/profile inputs.
- Do not duplicate the provisioner Job schema in Helm, Terraform, admission
  fixtures, and Python. One injected profile plus parity tests is the limit.
- Do not route sensitive env through `envFrom`, literal env, ConfigMaps, Helm
  values, Terraform outputs, subprocess argv, logs, or exception messages.
- Do not broaden AWS/EKS chart rendering because a neutral Python module exists;
  chart capability gating remains a deployment contract.
- Do not hide behavior changes behind compatibility re-exports. Existing GCP
  conformance and manifest tests must pass or fail on an explicit, reviewed
  contract update.

## Non-Goals

- No implementation in this preflight note.
- No new formal Ground Control requirement.
- No new public task-runner protocol, Kubernetes object broker, workflow engine,
  database table, queue payload, API endpoint, or repository layer.
- No redesign of Engine launch authorization, launch-intent persistence,
  command grammar, range/NGFW workflows, runtime env generation, provider
  secret stores, or public backend-bundle selection.
- No AWS ECS-to-EKS task delivery migration under #1824.
- No Kubernetes manifest, RBAC, admission, Terraform, Helm values, or workflow
  behavior change unless required to keep comments/tests aligned with the moved
  canonical builder path.

## Validation Expectations

For code changes under `shifter/shifter_platform`, run focused runner tests and
import boundaries:

```bash
cd shifter/shifter_platform && uv run pytest tests/shared/cloud/test_gcp_task_runner.py tests/shared/cloud/test_gcp_task_runner_sensitive_env.py tests/shared/cloud/test_gcp_task_runner_interrupt.py tests/shared/cloud/test_sensitive_env.py tests/shared/cloud/test_gcp_runtime_role_parity.py tests/shared/cloud/test_factory.py tests/shared/cloud/test_types.py
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
```

If Kubernetes manifests, Helm templates, chart values, or admission comments are
touched, also run:

```bash
cd shifter/shifter_platform && uv run pytest tests/platform/test_gcp_job_launcher_manifests.py
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

For architecture changes, keep the repo-required ADR guard in the validation
set:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
