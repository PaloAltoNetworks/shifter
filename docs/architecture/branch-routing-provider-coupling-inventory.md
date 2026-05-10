# Branch Routing and Provider Coupling Inventory

Status: current-state inventory for #1111

Tracking:

- Parent issue: <https://github.com/Brad-Edwards/shifter/issues/1109>
- Issue: <https://github.com/Brad-Edwards/shifter/issues/1111>
- Architecture decision: `ADR-011` in [the ADR registry](../adr/index.yaml)

## Purpose

This inventory maps the places where deployment behavior is currently selected
by branch name, provider-specific paths, or scattered runtime settings. It is a
source map for the root-configured backend-bundle migration, not the final
design.

Pulumi is not part of the target architecture. Existing Pulumi-related names in
the source map are compatibility names only unless a later migration issue
explicitly renames them.

## Summary

The current deployment model couples four concerns that should be separated:

- Git branch names select deployment intent.
- Terraform, Helm, Kubernetes, and bootstrap scripts encode provider-specific
  entrypoints outside one public installation contract.
- Runtime code selects provider behavior from environment variables that are
  generated differently by each provider path.
- Some provider assumptions are security controls and must migrate as controls,
  not as incidental naming cleanup.

The replacement model should route these concerns through:

- root configuration for installation intent and selected backend,
- backend metadata for provider-owned tools, generated outputs, secrets,
  health checks, and deploy entrypoints,
- CI matrix validation for supported backend examples,
- compatibility documentation for legacy names that cannot be renamed in one
  change.

## Source Map

| Area | Sources | Current assumptions | Proposed replacement |
| --- | --- | --- | --- |
| Branch-targeted deployment entrypoint | `.github/workflows/deploy.yml` | `main`, `dev`, `aws-dev`, and `gcp-dev` imply provider and environment. Pull requests and pushes route to different reusable workflows based on `github.base_ref` or `github.ref`. Path filters decide which component jobs run. | A root config selects the backend and deployment profile. CI validates checked-in backend examples through a matrix. Deployment uses explicit workflow input or command invocation, not branch name. Path filters can remain an optimization after backend intent is already explicit. |
| AWS reusable workflows | `.github/workflows/_core.yml`, `.github/workflows/_range.yml`, `.github/workflows/_shifter-engine.yml`, `.github/workflows/_shifter-platform.yml` | `environment` plus `is_dev` selects Terraform working directories, S3 backend files, AWS roles, ECR repositories, ECS task families, and service names. | The AWS backend bundle owns its Terraform entrypoints, state backend template, required roles/secrets, image targets, validation commands, and deploy commands. Dev/prod examples become profiles or sample configs, not branch-derived behavior. |
| GCP reusable workflow | `.github/workflows/_gcp-dev.yml` | The workflow is GCP-specific and assumes the `gcp-dev` Terraform environment, GCS state bucket naming, GCP Workload Identity Federation, Artifact Registry image roots, Identity Platform bootstrap, Kubernetes overlays, and GCP edge promotion. | The GCP backend bundle owns its Terraform/Kubernetes entrypoints, generated runtime env, bootstrap steps, required secrets, image roots, edge promotion checks, and health checks. CI validates the GCP example through the backend matrix. |
| Django runtime settings | `shifter/shifter_platform/config/settings.py` | `CLOUD_PROVIDER` defaults to `aws`. Generic names such as `CLOUD_REGION`, `STORAGE_BUCKET_NAME`, and `RANGE_EVENTS_TOPIC_ID` coexist with AWS aliases such as `AWS_REGION`, `AWS_S3_BUCKET_NAME`, and `SNS_RANGE_EVENTS_ARN`. GCP runtime values are added separately. | A validated root config and selected backend generate one runtime settings surface. Backward-compatible env aliases can remain temporarily, but runtime code should consume backend-derived canonical keys. |
| Portal cloud factories | `shifter/shifter_platform/shared/cloud/__init__.py` | Factories select object storage, task runner, queue, publisher, and secrets implementations from `settings.CLOUD_PROVIDER`. The provisioner container name remains `pulumi-provisioner` for compatibility. | A backend registry maps the selected backend to capability implementations. The public bundle owns which adapters are valid. Compatibility names should be documented and hidden from the user-facing setup path where possible. |
| Provisioner cloud factories | `shifter/engine/provisioner/cloud/__init__.py` | Provisioner adapters select event bus, config store, database auth, secrets, object storage, and network inventory from `CLOUD_PROVIDER`. | The provisioner should receive backend-derived configuration or a generated runtime env from the same selected backend as the portal. Adapter selection should be a backend capability lookup, not an independent provider switch. |
| Engine task runner behavior | `shifter/shifter_platform/engine/ecs.py`, `shifter/shifter_platform/cms/experiments/ecs.py` | Task execution conditionally builds AWS ECS settings or GCP runner settings. GCP runtime forwarding depends on a hardcoded allowlist of environment variables. AWS network settings use ECS cluster, task definition, subnet, security group, and public IP assumptions. | Backend metadata should describe the task runner capability, required runtime keys, env propagation contract, and network placement. Runtime code should call the selected backend task capability through a stable interface. |
| GCP generated runtime and edge manifests | `scripts/gcp/render_runtime_env.py`, `scripts/gcp/render_edge_manifest.py` | Terraform outputs are transformed into provider-specific runtime env and Kubernetes edge manifests. Auth mode, Identity Platform values, bucket names, Pub/Sub topics, task image root, and edge security values are generated here. | Backend-owned renderers should generate canonical runtime outputs from backend metadata and Terraform outputs. The root config should feed renderer inputs such as domain, public hostname, and secure mode. |
| Bootstrap entrypoints | `scripts/bootstrap/deploy.py`, `scripts/bootstrap/runner.py`, `scripts/gcp/**`, `scripts/local-provisioner-env.sh` | Bootstrap and helper scripts know provider paths, state layout, generated env files, and legacy provisioner naming. Some scripts are specific to local AWS/ECS assumptions. | Backend bundles should expose setup, doctor, render, deploy, and teardown commands with machine-readable prerequisites. Compatibility helpers can remain as backend-specific implementation details. |
| AWS Terraform layout | `platform/terraform/environments/dev/**`, `platform/terraform/environments/prod/**`, `platform/terraform/modules/**`, `platform/terraform/global/**` | AWS environment directories encode root, portal, range, S3 backend files, tfvars, Cognito, ECR/ECS, networking, state, and policy assumptions. Some resources retain Pulumi-era names or moved blocks. | The AWS backend bundle should own the AWS Terraform roots and profile examples. State backend, account/region, identity, network, image, and task settings should be declared as backend contract inputs or generated outputs. |
| GCP Terraform and Kubernetes layout | `platform/terraform/gcp/**`, `platform/charts/shifter/**`, `platform/k8s/gcp/**` | GCP has a separate Terraform root, Helm chart values, base Kubernetes manifests, and overlays. The current overlay is environment-specific and wired to GCP managed TLS, Identity Platform, Secret Manager, Cloud Armor, GKE, Artifact Registry, and GCS state. | The GCP backend bundle should own these entrypoints and publish the contract between Terraform outputs, Helm/Kustomize inputs, generated runtime env, and Kubernetes health checks. |
| Documentation | `shifter/shifter_platform/documentation/docs/technical/dev/ci-cd.md`, `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/cicd.md`, `shifter/shifter_platform/documentation/docs/technical/architecture.md`, deprecated technical docs | Docs still describe branch-targeted deploys, AWS/GCP branch behavior, and some legacy naming. | User-facing setup docs should describe root config and backend bundles. Compatibility docs should list legacy branch and Pulumi-era names only when they matter for migration or troubleshooting. |

## Branch Routing Replacement Map

| Current branch behavior | Current effect | Replacement |
| --- | --- | --- |
| Pull request to `main` | Plans AWS production changes through the AWS reusable workflows when relevant paths change. | Validate production-shaped AWS example config through a backend matrix. Production deployment remains an explicit invocation against a selected root config/profile. |
| Push to `main` | Applies AWS production deployment. | Remove implicit production deployment from branch name. Require explicit deploy input or command with selected backend/profile and protected environment approvals. |
| Pull request to `aws-dev` | Plans AWS development changes through AWS reusable workflows. | Validate AWS development example config in CI. Development deploy intent is an explicit profile or workflow input. |
| Push to `aws-dev` | Applies AWS development deployment. | Require explicit AWS backend deploy invocation. Keep branch names for Git workflow only if desired, not as architecture selectors. |
| Pull request to `gcp-dev` | Validates GCP Terraform and Kubernetes manifests. | Validate the GCP backend example in the CI backend matrix. |
| Push to `gcp-dev` | Runs the GCP deployment flow with fast-deploy behavior and GCP-specific bootstrap. | Require explicit GCP backend deploy invocation with backend metadata controlling Terraform, image, bootstrap, Kubernetes, and edge promotion steps. |
| Pull request to `dev` | Runs broad validation across AWS and GCP paths. | Keep broad validation through a backend matrix. The matrix reads backend examples rather than inferring deployment target from `dev`. |
| Push to `dev` | Runs validation-only AWS/GCP paths. | Keep validation-only behavior if useful, but make backend coverage explicit in CI configuration. |
| Manual `workflow_dispatch` | Allows manual execution of branch-routed workflow logic. | Manual dispatch should accept explicit backend/profile inputs and resolve all behavior from root config plus backend metadata. |

## Runtime Provider Coupling

### Portal

The portal uses `settings.CLOUD_PROVIDER` as the runtime selector for shared
cloud factories. The factories currently cover object storage, async task
execution, queue consumption, queue publishing, and secrets.

Target replacement:

- root config selects a backend,
- backend registry resolves capability implementations,
- generated runtime env carries canonical backend keys,
- compatibility env aliases are read only during migration.

### Provisioner

The provisioner independently reads `CLOUD_PROVIDER` and chooses provider
adapters for event bus, config store, database auth, secrets, object storage,
and network inventory.

Target replacement:

- the provisioner receives generated runtime env from the selected backend,
- adapter selection uses the same backend identity as the portal,
- provider-specific auth and inventory assumptions stay behind capability
  interfaces.

### Task Execution

Task execution currently mixes AWS ECS-specific configuration with GCP-specific
runtime forwarding. The GCP env allowlist is a provider contract embedded in
portal code.

Target replacement:

- task runner capability is declared by the selected backend,
- backend metadata defines required task settings and env propagation,
- runtime code invokes a stable task runner interface,
- network placement and public-access assumptions are validated by backend
  doctor checks.

## Terraform, Kubernetes, And Generated Runtime Coupling

### AWS

AWS support is spread across reusable workflows and Terraform environment
directories. The environment name selects S3 backend files, account roles,
region, Terraform roots, Cognito setup, ECS/ECR settings, range infrastructure,
and portal infrastructure.

Target replacement:

- AWS backend metadata declares Terraform roots and state backend inputs,
- example profiles replace branch-derived `dev` and `prod` behavior,
- AWS-specific generated outputs feed canonical runtime settings,
- existing roles, state, identity, and network controls remain explicit
  backend prerequisites.

### GCP

GCP support has a dedicated workflow, Terraform tree, Helm chart, Kubernetes
overlays, generated runtime env, and generated edge manifest. Terraform outputs
are the bridge from infrastructure to runtime and deployment.

Target replacement:

- GCP backend metadata declares Terraform, Helm/Kustomize, render, bootstrap,
  deploy, and health commands,
- generated runtime env becomes a backend-owned output with a stable schema,
- edge promotion checks remain backend-owned safety gates,
- GCP-specific identity, Secret Manager, Cloud Armor, TLS, GKE, GCS state, and
  Workload Identity Federation assumptions remain explicit.

## Legacy Compatibility Names

These names should be treated as compatibility surface, not evidence that
Pulumi remains part of the target architecture.

| Compatibility name | Sources | Migration handling |
| --- | --- | --- |
| `pulumi-provisioner` image/container/repository names | AWS workflows, GCP workflow outputs, `shared/cloud/__init__.py`, Terraform variables, tests | Preserve until a dedicated rename issue migrates image repositories, task families, container names, tests, and docs together. Hide from new setup docs where possible. |
| `PULUMI_*` env aliases | `settings.py`, engine task config, bootstrap helpers, tests | Keep as read aliases during migration. Canonical generated runtime keys should use backend-neutral names. |
| Terraform moved blocks and module/resource aliases with Pulumi names | AWS Terraform environments and engine-state modules | Preserve moved blocks to avoid state churn. Rename only with a state migration plan. |
| `pulumi_stack` model and migration names | Portal models, migrations, and related tests | Treat as data-model compatibility until a schema migration explicitly changes the public and database contract. |
| Deprecated docs that mention Pulumi | Deprecated technical docs | Do not use as target architecture. Either leave clearly deprecated or update in documentation cleanup work. |

## Security-Sensitive Provider Assumptions

The following are controls or trust-boundary assumptions. They must migrate as
explicit backend requirements and validation checks, not as naming cleanup.

| Control area | Current sources | Migration requirement |
| --- | --- | --- |
| CI and architecture guardrails | `scripts/adr_guard/**`, `.github/workflows/**`, `.importlinter`, `.tflint.hcl`, `.kube-linter.yaml`, `.gitleaks.toml`, ADR registry | Keep ADR guard, import boundaries, leak checks, Terraform linting, Kubernetes validation, and workflow linting equivalent or stronger during migration. |
| AWS identity and access | AWS reusable workflows, Terraform IAM, Cognito config, OIDC roles | Preserve explicit role assumption, least-privilege IAM, Cognito/OIDC auth boundaries, required verification/MFA behavior, and protected production approval paths. |
| AWS state and network isolation | AWS Terraform backend files, VPC/subnet/security group modules, ECS task settings | Preserve state backend controls, private subnet placement, security group restrictions, network firewall assumptions, and disabled public task IP behavior unless an ADR records a change. |
| GCP identity and access | `_gcp-dev.yml`, GCP Terraform, Identity Platform bootstrap, Secret Manager, Workload Identity Federation | Preserve WIF, Secret Manager boundaries, Identity Platform verification/MFA behavior, first-operator bootstrap constraints, and service-account scoping. |
| GCP state, cluster, and edge controls | GCP Terraform, `platform/k8s/gcp/**`, Helm values, generated edge manifest | Preserve GCS state controls, GKE cluster access controls, managed TLS, Cloud Armor, public hostname checks, edge promotion checks, and private operator access assumptions. |
| Kubernetes workload security | `platform/k8s/gcp/base/*.yaml`, Helm chart templates, ADR-006 evidence | Preserve pod security context, non-root execution, dropped capabilities, seccomp profiles, resource requests/limits, and admission-compatible manifests. |
| Runtime secret handling | `settings.py`, provider secrets stores, generated runtime env, bootstrap scripts | Keep secret identifiers distinct from secret values, avoid writing sensitive values into generated docs or logs, and ensure backend doctor checks detect missing secret wiring before deploy. |

## Replacement Ownership

| Replacement bucket | Owns |
| --- | --- |
| Root config | Selected backend, deployment name, domain/public hostname, profile, and high-level installation intent. |
| Backend metadata | Required tools, required secrets, provider prerequisites, Terraform/Helm/Kubernetes entrypoints, generated outputs, runtime env schema, validation checks, health checks, setup docs, and teardown support. |
| CI matrix validation | Supported backend examples, schema validation, backend doctor dry-runs, Terraform validation, Kubernetes rendering validation, and architecture guardrail evidence. |
| Compatibility docs | Legacy branch names, legacy Pulumi-era names, env aliases, state migration caveats, and troubleshooting for existing deployments. |
| Runtime registry | Capability adapter lookup for identity, storage, queues/events, secrets, task execution, network inventory, database auth, and generated runtime settings. |

## Follow-On Work

- #1112 should define the root config schema fields needed by this inventory.
- #1113 should turn backend metadata expectations into a versioned contract and
  registry.
- #1114 should replace direct provider/env switches with backend-derived runtime
  loading.
- #1116 and #1117 should migrate AWS and GCP through compatibility paths that
  preserve the listed security controls.
- #1118 should replace branch-targeted docs and CI routing with backend matrix
  validation and explicit deployment invocation.
- #1119 should decide which local backend capabilities are in scope for the
  first local bundle.
