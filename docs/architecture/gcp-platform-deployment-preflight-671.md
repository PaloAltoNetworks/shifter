# GCP Platform Deployment Preflight

Issue: GitHub #671, PLAT-002 "GCP Platform Deployment."

This note records the repository-wide architecture guardrails for continuing
GCP platform parity work. It is not an implementation plan.

ADR-027 note: legacy `cms/experiments` task execution was removed by issue
#1195. References below to experiment runner paths describe the pre-removal
state and are not current implementation guidance.

## Decision Boundary

PLAT-002 spans two related but separate concerns:

- the platform control plane deployed on GCP-native services
- the provider-specific operations the platform and provisioner perform at
  runtime

The control-plane deployment contract is Terraform for GCP infrastructure plus
the Shifter Helm chart installed by bootstrap-generated values. Runtime provider
selection is driven by validated configuration and `CLOUD_PROVIDER`, then
dispatched through the existing platform and provisioner adapter families.

Do not introduce a second backend selector, second root config parser, second
runtime env renderer, or second provider abstraction. The existing split is:

- public deployment intent: `shifter.yaml` via `shifter/installation`
- GCP infrastructure: `platform/terraform/gcp`
- GCP workload packaging: `platform/charts/shifter`
- bootstrap/rendering: `scripts/bootstrap/deploy.py` and
  `scripts/gcp/render_runtime_env.py`
- Django runtime adapter selection: `shifter/shifter_platform/shared/cloud`
- provisioner adapter selection: `shifter/engine/provisioner/cloud`

Existing ADRs already cover the accepted decisions, so this preflight does not
add a new ADR:

- ADR-005: cloud expansion must preserve provider seams and AWS continuity
- ADR-006: Kubernetes workloads must meet restricted Pod Security Standards
- ADR-007: GCP control-plane deployments are Helm-packaged and bootstrap-managed
- ADR-008: GCP bootstrap fails closed and uses private operator access
- ADR-009: AWS and GCP identity stacks stay behind a shared auth seam
- ADR-011: OSS deployments use root-configured backend bundles

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for PLAT-002 |
| --- | --- | --- |
| Backend selection and config shape | `shifter/installation/schema.py`, `loader.py`, `contract.py`, `registry.py` | `shifter.yaml` selects the backend bundle. Do not infer GCP from branch names, Terraform dirs, Helm values, or ad hoc env files. |
| Runtime inventory | `shifter/installation/runtime_inventory.py`, `config/_env_manifest.py`, `config/env-manifest.json` | New runtime env keys need a single owner and must be reflected in the inventory/manifest when they become checked-in surfaces. |
| GCP infrastructure | `platform/terraform/gcp/modules/platform-core` and child modules | Extend the module hierarchy and its variable/output validation. Do not make runtime code call Terraform output files directly. |
| GCP workload packaging | `platform/charts/shifter`, especially `values.yaml`, environment values, `templates/configmap-runtime.yaml`, `templates/secret-guacamole-runtime.yaml`, `templates/networkpolicies.yaml` | Helm is authoritative for GCP control-plane workloads; Kustomize assets are supporting/legacy validation surfaces unless an ADR changes that. |
| Runtime env rendering | `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/deploy.py::render_gcp_helm_values` | Generated env carries non-secret config and secret references. Secret values belong in Secret Manager or Kubernetes Secrets. |
| Secret hydration | `shifter/shifter_platform/entrypoint.sh`, `entrypoint-lib.sh`, `engine/secrets.py` | DB/app/Guacamole/Redis secrets are fetched from the active provider secret store and fail closed. Do not duplicate fetchers in app code. |
| Platform cloud operations | `shared/cloud/types.py`, `shared/cloud/__init__.py`, provider packages under `shared/cloud/aws` and `shared/cloud/gcp` | Domain code calls protocol factories: storage, task runner, queue consumer/publisher, secrets. No direct `boto3`, Google SDK, ECS, Pub/Sub, GCS, or Secret Manager calls in domain workflows. |
| Provisioner cloud operations | `shifter/engine/provisioner/cloud/types.py`, `cloud/__init__.py`, provider packages under `cloud/aws` and `cloud/gcp` | The provisioner remains Django-free and uses its own adapter family for event bus, config store, DB auth, secrets, storage, and network inventory. |
| Async workers | `config/_cloud.py`, `shared/management/commands/run_worker.py`, `shared/cloud/*/queue.py` | Preserve consumer/publisher ID separation. AWS SQS URL and GCP Pub/Sub topic/subscription are different shapes behind `QUEUE_*` config. |
| Task execution | `engine/ecs.py`, `cms/experiments/ecs.py`, `shared/cloud/gcp/task_runner.py` | Runtime orchestration is via `TaskRunner`; GCP maps cluster to namespace and task definition to image. Sensitive provisioner env must route through ephemeral Kubernetes Secrets. |
| Range/provider state | `engine.models.Range.provisioned_instances`, `engine/services/_common.py` | Provider-specific instance details belong in `provider_metadata` under the existing JSON payload and resolvers, not in new GCP-only Django models. |
| Auth | `config/identity_platform.py`, `config/views.py`, `platform/.../identity-platform`, ADR-009 | GCP uses Identity Platform browser-side flows. Django only verifies tokens and creates sessions after email verification, allow-list, and MFA checks. |
| Error responses | `shared/errors.py`, cloud exception modules, service-layer `ValueError` mapping | Client envelopes must use fixed/sanitized messages. Provider error text and secret references stay in logs only, with sanitization. |
| Logging | `shared/log_sanitize.py`, `shifter/engine/provisioner/log_redact.py`, `config/_posture.py` | Log non-secret posture and sanitized identifiers. Secret values, raw provider payloads, and multiline user-controlled values must not reach logs. |

## Cross-Cutting Layers The Design Must Pass

Security layers:

- Auth surface: GCP portal auth must stay on Identity Platform +
  FirebaseUI/browser SDKs. New GCP work must not collect passwords in Django,
  bypass `is_allowed_identity_email`, bypass MFA enrollment checks, or reuse the
  AWS OIDC runtime secret path.
- Secret-handling surface: secret values live in GCP Secret Manager,
  Kubernetes Secrets created at deploy time, or process memory after
  `entrypoint.sh` hydration. ConfigMaps, generated env files, Helm values,
  Terraform variable files, workflow YAML, and logs may contain only references
  or non-secret config.
- Env-binding shape: runtime keys flow through the existing renderer,
  Helm `.Values.runtimeEnv`, `config/_cloud.py`, and `config/settings.py`.
  Add new keys to the checked-in runtime inventory/manifest instead of
  creating an untracked env contract.
- Config validators: `shifter-config validate`, runtime inventory checks,
  Terraform variable validation, `adr_guard`, kube-linter, kubeconform,
  actionlint, and import-linter are repo-level gates. A local file-level change
  is not complete if it fails one of these outer gates.
- OS/process exposure: deploy and bootstrap commands must remain argv arrays.
  Do not pass passwords, tokens, private keys, Secret Manager payloads, or
  generated JSON secret bundles in process argv or echoed shell strings.
  Existing patterns use stdin, temp files with cleanup, Secret Manager access,
  and Kubernetes `Secret` objects.
- Kubernetes admission surface: chart and task-runner workloads must satisfy
  restricted PSS, non-root execution, dropped capabilities, read-only root files
  where established, explicit writable volumes, Workload Identity service
  accounts, default-deny NetworkPolicies, and Cloud Armor on public backends.
- Error-envelope leakage: provider SDK exceptions, Terraform output payloads,
  Pydantic rejected inputs, Identity Platform API bodies, and secret references
  must not be surfaced directly to clients. Use fixed-vocabulary or sanitized
  messages and log sanitized detail.

Maintainability layers:

- Reuse `shifter/installation` for public backend config and renderer bridge
  logic. Do not parse `shifter.yaml` in workflows, Django, Terraform helpers, or
  shell snippets.
- Reuse `scripts/gcp/render_runtime_env.py` and
  `scripts/bootstrap/deploy.py::render_gcp_helm_values` for generated GCP
  runtime config. Do not hand-maintain a second generated values file.
- Reuse `shared.cloud` and provisioner `cloud` protocols before adding any
  provider-specific call site.
- Reuse `engine/services/_common.py` for provider metadata resolution and
  `engine/secrets.py` for late secret reads.
- Reuse `shared.errors.classify_user_message` / `safe_user_message` and the
  existing cloud exception types instead of adding new response or exception
  hierarchies for GCP.

Extensibility layers:

- Backend selection stays at the backend-bundle level. The next reasonable
  variation is `gcp-prod` or a more mature GCP bundle schema, not a new
  low-level capability selector exposed to users.
- Provider capability seams belong in the two adapter protocol packages. Add a
  method or protocol only when a real cross-provider operation exists; do not
  add an abstraction for one GCP-only helper.
- Environment-specific posture belongs in validated variables or generated
  values (`gcp-dev`, future `gcp-prod`) layered over shared chart defaults.
  Avoid hardcoding project IDs, domains, admin CIDRs, image tags, node sizes, or
  secret names into Python.
- Range/provisioner metadata should remain provider-neutral at the outer shape
  (`cloud_provider`, `provider_metadata`) so AWS, GCP/GDC, and future providers
  can add nested details without rewriting Mission Control and engine services.

Whole-repo surfaces in scope:

- `.github/workflows/_gcp-dev.yml`, deploy secret docs, and actionlint if CI
  wiring changes.
- `shifter/installation/**` if backend-bundle settings, required secrets,
  generated outputs, or runtime inventory change.
- `scripts/bootstrap/deploy.py`, `scripts/gcp/render_runtime_env.py`, and their
  tests for bootstrap/runtime rendering changes.
- `platform/terraform/gcp/**`, `.tflint.hcl`, and `docs/adr/exceptions.yaml`
  for GCP infrastructure changes.
- `platform/charts/shifter/**` and `platform/k8s/gcp/**` for workload, RBAC,
  NetworkPolicy, runtime env, or secret binding changes.
- `shifter/shifter_platform/config/**`, `entrypoint.sh`,
  `entrypoint-lib.sh`, `shared/cloud/**`, `engine/**`, `cms/**`, and
  provisioner `cloud/**` for runtime behavior changes.

## Gotchas And Anti-Patterns

- Do not conflate provider with backend. `gcp` backend selection is a public
  installation concern; low-level provider adapters are internal runtime
  dispatch.
- Do not conflate secret values with secret references. `APP_SECRET_ID`,
  `DB_SECRET_ID`, and `REDIS_SECRET_ID` are references; passwords, API tokens,
  private keys, JSON auth keys, and Redis AUTH strings are values.
- Do not bypass Helm for the GCP control plane with ad hoc `kubectl apply`
  assets unless a new ADR changes ADR-007.
- Do not weaken AWS behavior while adding GCP parity. Existing AWS env aliases
  and adapter behavior are compatibility contracts.
- Do not create GCP-only duplicate schemas for scenario, range, instance,
  credential, or experiment data. Use existing Pydantic specs, model validators,
  and provider metadata.
- Do not let `latest` image tags, blank public hostnames, missing managed TLS,
  empty GKE authorized CIDRs, plaintext Redis, missing Secret Manager bundles,
  or world-open SSH/RDP become fallback behavior.
- Do not log raw Terraform outputs, Secret Manager payloads, provider SDK
  request/response bodies, identity tokens, kubeconfigs, or generated env file
  contents.
- Do not treat experiment script execution as GCP parity unless the AWS-only
  SSM RunCommand contract in `cms/experiments/orchestrator/execution_plan.py`
  is intentionally replaced behind a provider seam.

## Non-Goals

- Do not redesign Identity Platform, Cognito/OIDC, CTF magic-link auth, or
  Django session creation.
- Do not migrate the whole deployment model away from Terraform + Helm as part
  of a PLAT-002 implementation slice.
- Do not build a generic vault service, generic cloud SDK wrapper, or new
  cross-cloud dependency-injection container.
- Do not rotate real credentials, rewrite git history, merge into `main`, or
  close the tracking issue as part of architecture preflight.
- Do not implement missing GCP feature parity in this note. Follow-on code
  changes should use the boundaries above with the specific feature in front of
  them.

## Validation

Any implementation that changes architecture, workflows, hooks, or
`shifter/shifter_platform` must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Then add the stack-native checks for touched surfaces:

- `uv run --project shifter/installation shifter-config validate shifter.yaml`
  and `uv run --project shifter/installation shifter-config runtime-inventory --check`
  for root config or runtime inventory changes.
- `cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter`
  for Django/platform import-boundary changes.
- `TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"`
  for Terraform changes.
- `actionlint` for workflow changes.
- `kube-linter lint --config .kube-linter.yaml platform/k8s/` and
  `kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml`
  for Kubernetes or chart-rendered workload changes.
