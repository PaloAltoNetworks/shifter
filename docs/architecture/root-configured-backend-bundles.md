# Root-Configured Backend Bundles

Status: planning, constrained by ADR-011

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1109>

Current-state inventory:
[Branch Routing and Provider Coupling Inventory](branch-routing-provider-coupling-inventory.md)

## Context

Shifter currently mixes runtime provider seams with branch-targeted deployment
behavior. The application already has useful cloud adapter boundaries, but the
public deployment model is still hard to explain: branch names imply provider
and environment intent, while Terraform, Helm, generated env files, and Django
settings each carry part of the final deployment shape.

That model is workable for a controlled internal deployment, but it is a poor
fit for an OSS repository. Users should be able to choose the backend they want
and validate that choice from a single installation contract.

Pulumi is not part of the target architecture. Existing Pulumi-related names
should be treated as legacy compatibility names unless an implementation issue
explicitly migrates them.

## Recommendation

Shifter OSS should use a root-configured backend bundle model:

```text
root config -> selected backend bundle -> generated runtime, infra, validation, and deploy behavior
```

The public model should be:

```yaml
backend: aws
deployment:
  name: shifter
  domain: shifter.example.com
```

Internally, a backend bundle may decompose into capability adapters for identity,
storage, queueing, task execution, secrets, infrastructure, and range execution.
That decomposition should remain an implementation detail unless an advanced
configuration mode is deliberately introduced later.

## Architecture Principles

- One root config is authoritative for backend selection and deployment-level
  settings.
- A backend is the OSS unit of choice. Users select `aws`, `gcp`, `local`, or a
  future backend, not a mix of low-level capabilities.
- Branch names must not be architectural deployment selectors.
- Backend bundles own their required settings, generated outputs, validation
  checks, infrastructure entrypoints, health checks, and setup docs.
- Runtime code should select adapters from validated backend configuration, not
  from branch routing or scattered environment assumptions.
- Shared contracts remain under `shared`, and cross-layer access continues to go
  through service boundaries.
- Existing AWS and GCP behavior should migrate through compatibility paths that
  preserve current security controls.

## Root Config Schema Preflight

Scope for `GEN-2001`, `PLAT-2001`, `GEN-2002`, and #1112: define the root
installation config contract and its validation boundary only. Do not implement
backend migration, workflow replacement, runtime adapter rewiring, cross-install
orchestration, or a public capability-composition model as part of the schema
definition.

The authoritative root file is **`shifter.yaml`** at the repository root, and the
contract is implemented by the `installation` package
([`shifter/installation/`](../../shifter/installation/README.md)): the typed schema,
a fail-fast loader, worked examples, and the `shifter-config validate` CLI. The
backend bundle contract and registry referenced below are #1113; the `local`
backend is #1119.

### Contract Boundary

- The root config is user-authored installation intent. It selects one backend
  bundle, deployment identity, public domain/hostname intent, and profile-level
  settings. It is not a generated runtime env file, Terraform output file, Helm
  values file, Kubernetes manifest, or CI branch selector.
- The root config models exactly one standalone Shifter deployment. It must not
  introduce fleet, install registry, tenant-to-install mapping, parent/child
  deployment, remote cluster inventory, cross-install dependency, or centralized
  rollout concepts in the OSS app model.
- Secret material must stay out of the root config. The schema may accept secret
  references, provider secret names, GitHub secret names, or bootstrap prompts,
  but not raw secret values, access tokens, passwords, private keys, or service
  account JSON.
- Backend-specific settings must be namespaced behind the selected backend
  bundle and validated by that bundle contract. The public root schema must not
  expose low-level identity/storage/queue/task/secrets capability composition in
  the default UX.
- Unknown backends, unknown root keys, conflicting settings, unsupported
  profile/backend combinations, missing required settings, and insecure public
  posture must fail before Terraform, Helm, Django startup, worker startup, or
  deployment scripts run.
- Root config examples must be machine-validated by the same parser used by
  setup, doctor, CI, and render commands. Documentation examples are not a
  second schema.

### Incumbents To Reuse

| Concern | Canonical incumbent | Root config guardrail |
| --- | --- | --- |
| Shared contracts and layer boundaries | `shared/`, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `ADR-001` | Put any cross-runtime contract behind `shared` or a repo-level script contract that does not import Django app layers directly. Do not create provider schemas separately inside each app. |
| Schema validation | Existing Pydantic v2 schema style in `shared.schemas`, `cyberscript.schemas`, `cms.scenarios.schema`, and `cms.experiments.schemas`; script-local validators in `scripts/bootstrap/deploy.py` | Use one authoritative typed model/parser for the root config. If YAML is the UX format, use a structured parser and central validation instead of ad hoc regex/string parsing. |
| Runtime env binding | `shifter/shifter_platform/config/settings.py`, `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/deploy.py::render_gcp_helm_values`, Helm `runtimeEnv` | Treat runtime env as derived output. Generate canonical keys first and keep AWS/Pulumi-era aliases as compatibility only while migration work requires them. |
| Cloud capability seams | `shifter/shifter_platform/shared/cloud/__init__.py`, `shared/cloud/types.py`, `shifter/engine/provisioner/cloud/__init__.py`, `ADR-005-R1` | Backend selection may feed the existing factories, but domain code must continue to call cloud-neutral factories/protocols instead of provider-specific modules. |
| Identity/auth | `ADR-009`, `config/settings.py`, `config/oidc.py`, `config/identity_platform.py`, `scripts/bootstrap/deploy.py::ensure_gcp_identity_platform_operator` | Backend config may choose the identity stack through backend metadata; it must not move provider credential collection into Django or bypass domain/email/MFA/bootstrap controls. |
| Secrets | `shared.cloud.*.secrets`, `engine/provisioner/cloud/*/secrets.py`, `scripts/bootstrap/deploy.py` Secret Manager/GitHub secret helpers, `.gitleaks.toml` | Store and pass secret identifiers, not values. Keep generated secret-bearing Helm values in temporary/staged outputs or provider secret stores, and never echo secret values in diagnostics. |
| Logging and error text | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log`, existing CLI `error()`/`warn()` fail-fast style | Validation errors should name paths/keys and remediation, but must not include secret values, token payloads, or unescaped user-controlled strings. Do not add a parallel exception hierarchy unless a caller boundary needs it. |
| Infrastructure validators | `terraform validate`, `.tflint.hcl`, `kubeconform`, `.kube-linter.yaml`, `ADR-006`, `ADR-008` | Backend doctor checks must invoke or front-run these validators instead of replacing them. Security posture checks such as managed TLS, public hostname, and authorized admin CIDRs stay fail-closed. |
| Workflow/architecture gates | `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py`, `.github/workflows/_quality.yml`, `ADR-002`, `ADR-003`, `ADR-011` | Root config work must preserve ADR guard, import boundaries, secret scanning, branch-independent deploy intent, and documented guardrail changes. |

### Security Layers The Design Must Pass

- Auth surface: backend-derived config must satisfy the existing `AUTH_PROVIDER`
  paths and `ADR-009` controls. AWS remains OIDC/Cognito-compatible; GCP remains
  Identity Platform with provider-side credential collection, verified email,
  MFA, and bootstrap-owned first-operator seeding.
- Secret-handling surface: root config accepts references only. Provider secret
  adapters and bootstrap helpers resolve values at runtime or deployment time.
  Secret values must not be committed, logged, rendered into docs/examples, or
  passed through command-line argv.
- Env-binding shape: generated env must match `settings.py` canonical keys and
  existing alias windows. Any new key must have one owner, one renderer, and one
  validation source; generated ConfigMaps must not carry values that should be
  Kubernetes Secrets or provider secrets.
- Config validators: the root parser validates shape and cross-field conflicts;
  backend bundles validate provider requirements; Terraform, Helm, Kubernetes,
  actionlint, import-linter, and ADR guard keep their existing authority.
- OS/process exposure: deployment and doctor commands should continue to use
  argv-array subprocess calls, temporary credential files with cleanup, and
  interactive secret prompts via `getpass` where values must be collected.
- Error envelopes and logs: CLI failures should be deterministic nonzero exits
  with sanitized messages. Django-facing validation should use existing
  validation/error response patterns rather than a new global error envelope.

### Extensibility Seam

The schema needs an explicit version/profile/backend seam so the next backend
or profile does not require redefining the root contract. The root parser owns
root keys and dispatches selected-backend settings to backend bundle validation;
backend bundles own provider-specific requirements, generated outputs,
entrypoints, health checks, and docs. Future `local` or production variants
should add backend/profile data behind that seam, not add another authoritative
root file or branch convention.

### Anti-Patterns

- Treating branch names, Terraform environment directories, Helm values,
  generated env files, or provider-local docs as additional authoritative config.
- Duplicating root schema definitions across scripts, Django settings, Terraform
  variables, Helm values, and examples.
- Letting runtime code independently infer provider from `CLOUD_PROVIDER` while
  setup/doctor uses a different root config interpretation.
- Mixing public backend selection with low-level capability composition in the
  default UX.
- Recording secret values, bootstrap passwords, service-account JSON, access
  tokens, or private keys in root config, argv, logs, examples, ConfigMaps, or
  plan comments.
- Weakening ADR, import, Terraform, Kubernetes, actionlint, gitleaks, or CI
  enforcement to make the schema migration easier.

### Non-Goals

- Do not design a fleet manager, multi-install controller, hosted control plane,
  marketplace, plugin runtime, or centralized upgrade service.
- Do not move provider credential collection, secret value storage, identity
  policy, deployment state, Terraform state, or Kubernetes runtime manifests
  into the root config.
- Do not rename legacy Pulumi-era or AWS/GCP compatibility surfaces as part of
  schema definition unless a dedicated migration issue owns the state, workflow,
  tests, and documentation impact.

## Setup And Doctor UX Preflight

Scope for `GEN-2002` and #1115: expose a backend-aware setup and validation
experience that proves the selected backend is ready before Terraform, Helm,
Django, workers, or provisioners mutate infrastructure or start runtime work.
This is a UX and validation boundary, not a new deployment orchestrator.

### Command Boundary

- Setup may create or update the root config and guide secret/bootstrap
  reference creation. It must not become a second source of backend truth.
- Doctor is read-only by default. It may inspect local files, tool availability,
  provider identity, secret existence, rendered outputs, Terraform/Helm/K8s
  validity, and reachable health endpoints, but it must not run `apply`,
  `upgrade --install`, `kubectl apply`, secret version writes, first-user
  seeding, or destructive cleanup.
- The public UX should reuse the existing CLI grammar, dry-run behavior,
  non-interactive behavior, and `info`/`warn`/`error` fail-fast style from
  `scripts/bootstrap/deploy.py`. If a new entrypoint is introduced, it should
  call the same parser/check/render functions rather than fork bootstrap logic.
- CI-facing validation should use the same root parser and backend doctor checks
  as the local UX. Documentation examples and workflow examples must not carry a
  parallel interpretation of valid config.

### Checks To Reuse

| Layer | Canonical incumbent | Doctor guardrail |
| --- | --- | --- |
| CLI dependency checks | `scripts/bootstrap/deploy.py::check_dependencies`, command-specific tool lists | Extend the command-specific dependency model for backends. Do not scatter `shutil.which` checks across backend scripts. |
| Provider security preflight | `validate_gcp_control_plane_security_inputs`, GCP edge promotion checks, AWS Cognito/OIDC and Terraform input conventions | Preserve fail-closed checks for hostname, managed TLS, admin CIDRs, provider auth, and identity bootstrap prerequisites before deploy. |
| Render validation | `scripts/gcp/render_runtime_env.py`, `scripts/gcp/render_edge_manifest.py`, `render_gcp_helm_values`, Helm `runtimeEnv` | Doctor should render to memory or temp paths and compare against the backend contract. Do not hand-build env files in a separate path. |
| Infrastructure validation | `terraform init -backend=false`, `terraform validate`, `.tflint.hcl`, Helm template rendering, `kubeconform`, `.kube-linter.yaml`, `ADR-006`, `ADR-008` | Doctor may front-run these checks and summarize them, but it must not replace their authority or mask their exact failures. |
| Runtime validation | `config/settings.py`, `/health/`, Django `check --deploy`, cloud factories in `shared.cloud` and `engine/provisioner/cloud` | Validate generated runtime keys against canonical settings and factories before startup. Runtime provider selection must still flow from validated backend config. |
| Tests | `scripts/bootstrap/tests/test_deploy.py`, `scripts/gcp/tests/*`, shared cloud factory tests, `tests/config/*` | Add contract tests around setup/doctor parsing, read-only behavior, redaction, and backend dispatch rather than only snapshotting terminal output. |

### Security Layers

- Auth surface: setup/doctor may verify the selected backend's auth mode and
  required references, but provider credential collection stays in existing
  provider flows. GCP first-operator handling continues through
  `ensure_gcp_identity_platform_operator`; AWS remains Cognito/OIDC-compatible.
- Secret-handling surface: checks must verify secret references, names, access,
  or freshness without printing or storing secret payloads. If a payload must be
  read for an existing backend check, use existing provider secret helpers,
  temporary files with cleanup, and redacted diagnostics.
- Env-binding shape: generated runtime values must keep secret identifiers in
  ConfigMaps and secret values in Kubernetes Secrets or provider stores.
  Doctor should fail when a value crosses that boundary.
- OS/process exposure: subprocess calls use argv arrays. Do not pass passwords,
  service-account JSON, private keys, access tokens, or bootstrap secrets in
  argv, dry-run output, plan comments, shell snippets, or log messages.
- Error envelopes and logs: CLI output should identify the failing check,
  config path, canonical owner, and remediation. User-provided paths, hostnames,
  and provider messages should be sanitized before logging.

### Extensibility Seam

Backend bundles should contribute setup and doctor metadata behind the same
version/profile/backend seam as the root config schema: required tools, required
secret references, provider prerequisites, renderers, validators, health checks,
and whether a check is read-only. Adding a `local` backend or a production
profile should add backend/profile check data, not a new setup command family or
branch-derived validation path.

### Anti-Patterns

- A doctor command that mutates infrastructure, writes provider secrets, applies
  Kubernetes manifests, seeds users, or silently repairs state.
- Separate root config parsers for setup, doctor, render, CI, Terraform docs, or
  Django settings.
- Treating `CLOUD_PROVIDER`, branch names, Terraform directories, Helm values,
  or generated env files as the source of truth when the root config exists.
- Printing provider credentials, secret payloads, env dumps, Terraform outputs
  with sensitive values, or command lines containing tokens.
- Marking doctor green when Terraform, Helm, Kubernetes, ADR guard, import
  boundaries, or security posture checks failed downstream.

## Draft Requirements

These requirements have been created in Ground Control as `DRAFT` requirements.
They should remain `DRAFT` while the architecture is reviewed and transition to
`ACTIVE` only when implementation starts.

| UID | Title | Type | Priority | Statement |
| --- | --- | --- | --- | --- |
| `PLAT-2001` | Root installation configuration | Functional | MUST | Shifter must have one authoritative root installation configuration that selects the backend bundle and supplies deployment-level settings used to derive runtime, infrastructure, and validation behavior. |
| `PLAT-2002` | Backend bundles are the OSS backend selection unit | Constraint | MUST | OSS users must choose a complete backend bundle rather than composing low-level provider capabilities in the default setup path. |
| `PLAT-2003` | Backend bundle contract | Interface | MUST | Each backend bundle must expose a stable machine-readable contract for required settings, generated outputs, infrastructure entrypoints, validation checks, health checks, and documentation. |
| `PLAT-2004` | Branch-independent deployment targeting | Constraint | MUST | Deployment target selection must come from explicit configuration or invocation, not from repository branch names. |
| `PLAT-2005` | Backend-derived runtime configuration | Functional | MUST | Django, workers, and provisioner processes must derive provider and capability adapter selection from validated backend configuration. |
| `PLAT-2006` | AWS/GCP compatibility and security preservation | Non-functional | MUST | Migration of existing AWS and GCP support must preserve current security controls, guardrails, and operational safety unless an ADR records an intentional change. |
| `GEN-2001` | Standalone OSS deployment scope | Constraint | MUST | This repository must model one standalone Shifter deployment and avoid cross-install orchestration concepts in the OSS app model. |
| `GEN-2002` | Backend-aware setup and validation UX | Functional | SHOULD | Users should be able to initialize, configure, and validate their selected backend before applying infrastructure or starting the application. |

## ADR Status

`ADR-011` accepts the root-configured backend bundle direction and supersedes
the branch-routing portions of `ADR-005`.

Follow-on implementation should preserve the adapter seam rule in `ADR-005-R1`,
keep identity provider details behind the `ADR-009` auth seam, and update ADR
evidence only when corresponding files change.

## Issue Map

- #1110 Draft requirements and ADR for root-configured backend bundles.
- #1111 Inventory branch routing and provider coupling. See
  [Branch Routing and Provider Coupling Inventory](branch-routing-provider-coupling-inventory.md).
- #1112 Define root installation config schema.
- #1113 Define backend bundle contract and registry.
- #1114 Derive runtime configuration from selected backend bundle.
- #1115 Add backend-aware setup and doctor validation UX.
- #1116 Migrate AWS support into a backend bundle.
- #1117 Migrate GCP support into a backend bundle.
- #1118 Replace branch-targeted deployment docs and CI routing.
- #1119 Define initial local backend scope.

## Suggested Sequence

1. Use the current-state inventory to define the root config schema and backend
   bundle contract.
2. Implement config loading, backend registry, and doctor validation.
3. Migrate AWS and GCP through compatibility paths.
4. Replace branch-targeted docs and CI routing with backend validation and
   explicit deployment invocation.

## Open Questions

- Should the local backend be Docker Compose first, Kubernetes first, or staged?
- Which commands should form the public setup UX: `make`, a Python CLI, Django
  management commands, or a small standalone tool? (#1112 ships `shifter-config
  validate`; the broader setup/doctor UX is #1115.)
- Which existing Pulumi-related names are harmless compatibility aliases, and
  which require migration to avoid confusing users?

## Resolved

- The first-class root config file is `shifter.yaml` at the repository root; the
  contract is the `installation` package (`shifter/installation/`). (#1112)
