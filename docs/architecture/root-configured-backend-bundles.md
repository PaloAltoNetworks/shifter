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

## Backend Bundle Contract And Registry Preflight

Scope for `PLAT-2002`, `PLAT-2003`, `PLAT-2005`, and #1113: define the
machine-readable backend bundle contract and the registry that replaces the
provisional backend list in `shifter/installation/backends.py`. Do not migrate
AWS, GCP, local, runtime adapter selection, CI branch routing, or setup/doctor
orchestration as part of the contract definition. The contract should make those
later changes lower-risk by naming the backend-owned inputs, outputs, checks, and
adapter capabilities in one place.

### Contract Boundary

- A backend bundle is the default OSS unit of selection. Public setup chooses one
  bundle such as `aws`, `gcp`, or `local`; it must not expose identity, storage,
  queueing, task execution, secrets, infrastructure, or range execution as
  independently user-composable capabilities.
- The registry owns backend identity, display metadata, maturity, supported
  profiles, required tools, required secret references, required root
  `settings` shape, generated output descriptors, validation checks, health
  checks, docs links, backend-owned file roots, and capability declarations.
- The registry is not a deployment orchestrator, plugin runtime, Terraform
  wrapper, Django settings module, workflow router, or provider credential
  store. It should describe and dispatch to existing implementation entrypoints.
- The registry is checked-in contract data/code, not a database-backed runtime
  registry. Do not add persistence, migrations, tenant scoping, or dynamic
  backend install state for #1113.
- The contract belongs in the Django-free installation layer unless an ADR
  records a different owner. Django, workflows, bootstrap scripts, and CI should
  import or invoke that same contract instead of maintaining their own backend
  tables.
- Registry command/check entries must resolve to typed repo-owned entrypoints or
  argv-array command specs. Do not store raw shell strings, user-controlled
  Python import strings, or absolute host paths in backend metadata.
- Backend-specific root `settings` validation belongs to the selected backend
  bundle. The root schema continues to own root keys only: `version`, `backend`,
  `deployment`, `secrets`, and that `settings` is a mapping.
- Capability declarations may map to existing adapter protocols, but domain code
  must continue to call `shared.cloud` and `engine/provisioner/cloud` service
  seams. The bundle contract must not teach domain code to import provider
  packages directly.
- Generated runtime, infrastructure, Helm, Kubernetes, and CI values are derived
  outputs. They are not alternate authoritative config files and must not accept
  low-level capability overrides that disagree with the selected backend.

### Contract Fields

The initial registry should be small but structured enough that setup, doctor,
CI, docs generation, and runtime derivation can share it:

| Field | Owner | Guardrail |
| --- | --- | --- |
| `contract_version` | Registry | Version the backend contract shape independently of root `shifter.yaml` so future metadata fields can be added compatibly. Unknown major versions fail closed. |
| `name`, `title`, `maturity`, `description` | Registry | Stable backend identity for selection and documentation. Do not infer backend from branch names, Terraform directories, or `CLOUD_PROVIDER`. |
| `supported_profiles` | Registry | Replaces the hard-coded `ALLOWED_PROFILES` data in `installation.backends`; adding a profile is data, not a new root schema. |
| `settings_schema` | Backend bundle | Validates `RootConfig.settings` for the selected backend only. Use typed Pydantic-style validation and aggregated sanitized errors. |
| `required_tools` | Backend bundle | Feeds setup/doctor dependency checks; extend the command-specific model in `scripts/bootstrap/deploy.py::check_dependencies` instead of scattering `shutil.which`. |
| `required_secrets` | Backend bundle | Declares logical secret references and provider reference grammar. Secret values remain in provider stores, GitHub secrets, Kubernetes Secrets, or interactive prompts, never in `shifter.yaml`. |
| `generated_outputs` | Backend bundle | Names runtime env keys, Terraform variables/outputs, Helm values, Kubernetes artifacts, and compatibility aliases produced by backend renderers. Each output descriptor must declare owner, renderer/check source, destination, and sensitivity (`secret-reference`, `secret-value`, or `public/non-secret`) so generators cannot place secrets in ConfigMaps, docs, dry-runs, or plan comments. |
| `validation_checks` | Backend bundle | References existing validators such as root config validation, Terraform validate/TFLint, Helm rendering, kubeconform, kube-linter, actionlint, import-linter, and ADR guard. |
| `health_checks` | Backend bundle | Describes read-only post-render or post-deploy probes, their required credentials, expected timeout, and safe failure text without turning doctor into a mutating deploy command. |
| `capabilities` | Backend bundle | Declares which existing cloud-neutral protocols the backend satisfies: storage, queue consumer/publisher, task runner, secrets, config store, event bus, database auth, and network inventory. |
| `owned_files` and `docs` | Backend bundle | Points to backend-owned Terraform, Helm, Kubernetes, script, example, and docs roots so validation and docs generation can find them without branch routers. |

### Incumbents To Reuse

| Concern | Canonical incumbent | Backend contract guardrail |
| --- | --- | --- |
| Root config parser | `shifter/installation/schema.py`, `loader.py`, `errors.py`, `cli.py` | Build the registry beside this parser and replace `backends.py` data with registry data. Do not add another YAML parser or backend table in workflows, Django, or scripts. |
| Validation error model | `installation.errors.ConfigIssue` and `InstallationConfigError` | Reuse aggregated path-based issues for backend settings validation. Messages must not carry rejected secret values. |
| Schema style | Existing Pydantic v2 models in `installation.schema`, `cms.scenarios.schema`, and `cms.experiments.schemas` | Use typed models and model validators rather than ad hoc dict walking once data crosses the contract boundary. |
| Portal cloud seams | `shifter/shifter_platform/shared/cloud/types.py` and `shared/cloud/__init__.py` | Backend capabilities point at these protocols/factories. Do not bypass them from CMS, CTF, engine views, or services. |
| Provisioner cloud seams | `shifter/engine/provisioner/cloud/types.py` and `cloud/__init__.py` | Provisioner capability selection must receive the same backend identity as the portal, not infer a second provider from ambient env. |
| Runtime env binding | `config/settings.py`, `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/deploy.py::render_gcp_helm_values`, Helm `runtimeEnv` | The bundle contract names canonical env keys and compatibility aliases. Renderers produce those keys; settings consume them. |
| Identity/auth | `ADR-009`, `config/settings.py`, `config/oidc.py`, `config/identity_platform.py`, `ensure_gcp_identity_platform_operator` | Backend metadata may choose the auth mode, but provider credential collection and app-session gates stay in the existing auth seams. |
| Secrets | `shared.cloud.*.secrets`, `engine/provisioner/cloud/*/secrets.py`, bootstrap secret helpers, `.gitleaks.toml` | Registry entries declare references and checks only. Do not log, commit, echo, or pass secret payloads through argv. |
| Logging and redaction | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log`, installation errors | Contract/doctor diagnostics name backend, path, check, owner, and remediation while redacting provider messages and user-controlled values where needed. |
| Infrastructure validation | Terraform validate/TFLint, Helm template rendering, kubeconform, kube-linter, `.importlinter`, ADR guard | Backend validation references these existing authorities. It may front-run or aggregate them, but must not replace or soften their failures. |

### Security Layers

- Auth surface: backend metadata may select `AUTH_PROVIDER`, but must satisfy the
  existing OIDC/Cognito and Identity Platform boundaries. GCP continues to keep
  browser credential collection in Identity Platform, enforce verified email and
  MFA before app sessions, and seed the first operator through bootstrap-owned
  logic.
- Secret-handling surface: root config and backend settings hold references
  only. The selected bundle validates the reference grammar; provider adapters
  and bootstrap helpers resolve values. Secret payloads must not appear in
  `shifter.yaml`, registry data, generated docs, logs, ConfigMaps, dry-run
  output, GitHub comments, or process argv.
- Env-binding shape: bundle outputs must match canonical `settings.py` keys and
  document any AWS/Pulumi-era aliases as compatibility. ConfigMaps carry
  non-secret runtime values; Kubernetes Secrets or provider stores carry secret
  values.
- Config validators: validation order is root schema, selected bundle settings,
  backend prerequisite checks, renderer checks, infrastructure validators, and
  runtime startup checks. Unknown backend, unsupported profile, unknown setting,
  missing required tool/secret, insecure public posture, and conflicting outputs
  fail before mutation.
- OS/process exposure: checks and renderers use argv-array subprocess calls and
  temporary credential files with cleanup. Passwords, private keys, service
  account JSON, access tokens, and bootstrap secrets use existing prompt or
  provider-secret paths, never shell snippets or command-line flags. Registry
  metadata is data, not executable text: command specs are structured argv
  arrays or stable repo-owned check IDs.
- Error envelopes and logs: CLI/doctor paths return deterministic nonzero exits
  with sanitized `ConfigIssue`-style messages. Django-facing callers keep using
  existing Django validation and response patterns; do not add a global backend
  exception hierarchy unless a caller boundary requires it.

### Extensibility Seam

The required seam is root `version` + backend `contract_version` + `backend` +
`profile` + backend-owned `settings_schema`. Adding the initial `local` backend,
a production GCP profile, or a future backend should add registry data,
bundle-specific settings validation, and backend-owned render/check entries
behind that seam. It should not require changing the root schema, adding a
branch router, adding another authoritative config file, or teaching domain code
about provider packages.

### Anti-Patterns

- Creating separate backend registries in `installation`, Django settings,
  Terraform, Helm values, GitHub Actions, and docs.
- Treating capability composition as the default OSS UX or allowing users to mix
  AWS identity with GCP queues, local storage, or ad hoc task execution without a
  later ADR-defined advanced mode.
- Letting `CLOUD_PROVIDER`, `AUTH_PROVIDER`, branch names, generated env files,
  Terraform directories, or Helm values override the selected backend bundle.
- Forking provider-specific exception hierarchies, validators, CLI output
  models, or secret-reference grammars when the installation error model and
  cloud protocol exceptions already cover the boundary.
- Putting arbitrary executable code, shell fragments, absolute local paths, or
  network-fetched backend definitions in the registry.
- Embedding GCP env allowlists, AWS network assumptions, image names, health
  checks, or secret keys in portal code instead of backend-owned metadata and
  renderers.
- Weakening ADR guard, import boundaries, actionlint, TFLint, kubeconform,
  kube-linter, gitleaks, Identity Platform checks, or network/TLS controls to
  make backend migration easier.

### Non-Goals

- Do not implement AWS, GCP, or local bundle migration in #1113.
- Do not introduce a public plugin marketplace, fleet manager, multi-install
  controller, remote cluster inventory, or centralized rollout service.
- Do not move Terraform state, provider credentials, identity policies, secret
  values, or Kubernetes runtime manifests into the registry.
- Do not persist backend bundles in the application database or introduce a
  runtime plugin installation lifecycle.
- Do not rename Pulumi-era compatibility names, database fields, image
  repositories, task families, or Terraform moved blocks unless a dedicated
  migration issue owns state and compatibility impact.

## Backend-Derived Runtime Configuration Preflight

Scope for `PLAT-2005` and #1114: make Django, workers, and provisioner
processes derive provider and capability adapter selection from the validated
root config plus selected backend bundle. Do not implement backend migration,
new provider adapters, setup/doctor orchestration, or CI branch-routing
replacement as part of this runtime derivation boundary.

### Runtime Boundary

- Runtime derivation starts from the same validated `RootConfig` and backend
  registry contract used by setup, doctor, examples, and CI. Django settings,
  worker startup, provisioner startup, and task-launch paths must not parse
  `shifter.yaml` independently or maintain a second backend table.
- The selected backend bundle owns the canonical runtime output schema:
  backend identity, auth provider, cloud region/project/account identifiers,
  queue identifiers, storage identifiers, task-runner settings, secret
  references, network placement, health endpoints, and compatibility aliases.
- Environment variables remain the process binding layer for Django, workers,
  Kubernetes, ECS, and local subprocesses, but they are derived outputs, not an
  authority that can override the selected backend. `CLOUD_PROVIDER` and
  `AUTH_PROVIDER` become compatibility/runtime binding keys emitted by the
  backend renderer, not ad hoc selectors set by workflows or branch names.
- Portal code continues to use `shared.cloud` factories and protocols. Workers
  continue to enter through `shared.management.commands.run_worker` and the
  queue config from settings. Provisioner code continues to use its Django-free
  `cloud` factory/protocol layer. Domain services must not import
  provider-specific adapter packages directly.
- The portal and provisioner must receive the same backend identity and
  compatible capability map. A portal-derived task launch must not forward a
  GCP runtime allowlist while the provisioner independently infers AWS from a
  missing env var.
- Runtime startup should fail closed on missing or conflicting derived keys
  before processing requests, polling queues, launching tasks, or provisioning
  infrastructure.

### Incumbents To Reuse

| Concern | Canonical incumbent | Runtime guardrail |
| --- | --- | --- |
| Root config and validation | `shifter/installation/schema.py`, `loader.py`, `errors.py`, `cli.py` | Runtime derivation consumes validated `RootConfig` and backend registry data. Do not add a Django-local YAML parser or a provisioner-local root schema. |
| Django env binding | `shifter/shifter_platform/config/settings.py` | Keep one canonical settings surface for derived env keys and compatibility aliases. Backend renderers produce the keys settings already consumes or explicitly add one owner for any new key. |
| Portal capability adapters | `shifter/shifter_platform/shared/cloud/__init__.py`, `shared/cloud/types.py`, `shared/cloud/exceptions.py` | Backend capabilities dispatch through existing factories/protocols and `CloudError` subclasses. Do not fork provider-specific exceptions or call adapters directly from app layers. |
| Worker startup | `shared.management.commands.run_worker`, `settings.QUEUE_CONFIG`, `get_queue_consumer()` | Workers inherit the same derived runtime env as Django and resolve queue consumer IDs through the existing queue config shape. Do not create backend-specific worker commands. |
| Task runner launch | `engine/ecs.py`, `cms/experiments/ecs.py`, `shared.cloud.types.TaskRunner` | Move provider-specific task settings and env propagation into backend-owned runtime descriptors. Preserve local provisioner mode as a compatibility path, but do not let it become a second backend selector. |
| Provisioner capability adapters | `shifter/engine/provisioner/cloud/__init__.py`, `cloud/types.py`, `cloud/exceptions.py`, `config.py`, `range_terraform_runner.py` | Provisioner startup reads the derived backend identity and capability env emitted by the same backend bundle as the portal. GDC/AWS branching stays behind provisioner seams until replaced by registry dispatch. |
| Runtime renderers | `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/deploy.py::render_gcp_helm_values`, Helm `runtimeEnv`, Kubernetes `platform-runtime` ConfigMap | Backend runtime renderers extend or wrap these existing render paths. They must label sensitivity and keep secret values out of ConfigMaps and dry-run output. |
| Auth seams | `ADR-009`, `config/settings.py`, `config/oidc.py`, `config/identity_platform.py`, `ensure_gcp_identity_platform_operator` | Backend metadata selects the auth mode, but credential collection, verified email, MFA, operator bootstrap, and session creation stay in the existing provider auth boundaries. |
| Logging and redaction | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log`, `installation.errors.ConfigIssue` | Startup and derivation diagnostics name backend, config path, generated key, and remediation while redacting provider errors, secret references where sensitive, and user-controlled strings. |

### Security Layers

- Auth surface: the derived `AUTH_PROVIDER` value must match the selected
  backend's identity capability and `ADR-009`. AWS keeps the OIDC/Cognito path;
  GCP keeps Identity Platform browser credential collection, verified email,
  MFA, and bootstrap-owned first-operator seeding. Runtime derivation must reject
  incompatible backend/auth pairs before Django URL/auth backends initialize.
- Secret-handling surface: root config and backend settings contain secret
  references only. Runtime renderers classify every output as
  `public/non-secret`, `secret-reference`, or `secret-value`; only
  `public/non-secret` and approved `secret-reference` keys may enter
  ConfigMaps, logs, dry-runs, GitHub comments, or task env forwarding.
  Secret-value outputs stay in provider secret stores, Kubernetes Secrets, or
  temporary files with cleanup.
- Env-binding shape: generated env must satisfy `settings.py`, worker
  `QUEUE_CONFIG`, portal task-runner settings, provisioner cloud config, and the
  Helm/Kubernetes `runtimeEnv` shape. Unknown keys, duplicate canonical owners,
  conflicting compatibility aliases, and provider-specific required keys missing
  for the selected backend fail before runtime startup.
- Config validators: validation order is root schema, selected backend settings
  schema, backend runtime output validation, renderer sensitivity checks, Helm
  and Kubernetes shape validation, Django `check --deploy` where applicable, and
  provisioner startup checks. Runtime derivation may aggregate these failures but
  must not mask downstream validators.
- OS/process exposure: local provisioner subprocesses, bootstrap renderers, and
  task launchers use argv arrays. Do not pass passwords, private keys, service
  account JSON, access tokens, or generated secret payloads in process argv,
  command strings, shell snippets, or logged dry-run commands.
- Error envelopes and logs: CLI/setup/doctor paths should report sanitized
  `ConfigIssue`-style path failures. Django-facing failures should use existing
  Django startup, validation, and response patterns. Provisioner failures should
  use existing `CloudError`/runtime exceptions without adding a parallel backend
  exception hierarchy.

### Extensibility Seam

The required seam is a typed runtime-output descriptor owned by each backend
bundle and keyed by `contract_version`, backend, profile, process role, and
capability. Process role must be explicit (`portal`, `worker`, `provisioner`,
`experiment-task`, `range-task`) so a future `local` backend, a production GCP
profile, or a different task runner adds data and render/check entries behind
the registry rather than adding branch routers or widening low-level capability
composition in the public config.

### Runtime Gotchas

- `settings.py` currently defaults `CLOUD_PROVIDER` to `aws`; derived runtime
  work must remove the risk that a missing generated key silently selects AWS.
- The provisioner has its own `CLOUD_PROVIDER` readers because it cannot import
  Django settings. It needs an explicit generated binding from the same backend
  bundle, not a second inference path.
- `engine/ecs.py` contains a GCP provisioner env allowlist that is already a
  backend runtime contract embedded in portal code. Move the ownership to
  backend metadata/renderers before adding another provider or role.
- `platform/k8s/gcp/overlays/gcp-dev/platform-runtime.env` is compatibility
  input and currently includes guest-password-style defaults. Runtime derivation
  must not preserve that pattern for new outputs; secret values belong in secret
  stores or Kubernetes Secrets.
- Pulumi-era names such as `pulumi-provisioner` and `PULUMI_*` aliases are
  compatibility surfaces. Hide them behind canonical backend-neutral descriptors
  unless a dedicated migration issue owns the rename.

### Anti-Patterns

- Adding a `get_backend()` helper in Django, another one in the provisioner, and
  a third one in scripts that can disagree.
- Letting `CLOUD_PROVIDER`, `AUTH_PROVIDER`, task image names, queue IDs,
  Terraform outputs, Helm values, or branch names override the selected backend.
- Passing a large inherited `os.environ` into task launches or local provisioner
  subprocesses without a backend-owned allowlist and sensitivity classification.
- Duplicating queue/storage/task/secrets protocols instead of extending
  `shared.cloud.types` or `engine/provisioner/cloud/types` only when a real
  capability requires it.
- Emitting provider SDK errors, token payloads, secret names that reveal
  sensitive tenancy, or unsanitized user-controlled config values into logs.

### Non-Goals

- Do not make runtime derivation a deployment orchestrator, plugin runtime,
  fleet manager, or persistence-backed backend registry.
- Do not change domain service ownership, import boundaries, model schemas,
  queue handler contracts, or CTF/CMS/mission-control workflows as part of
  deriving backend config.
- Do not introduce public low-level capability composition. The runtime registry
  may decompose a backend internally, but the OSS user still selects a backend
  bundle.
- Do not rename compatibility env vars, task families, image repositories,
  database fields, or Terraform state keys without a dedicated migration issue
  and state-compatibility plan.

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
- The backend bundle contract and registry are the `installation.contract` and
  `installation.registry` modules; they supersede the provisional
  `installation.backends` list. The root schema derives backend/profile
  validation from the registry, and the loader runs the selected backend
  bundle's per-backend `settings` and secret-reference checks. The shipped
  `aws`/`gcp` registry entries are provisional (no `settings_model` or
  `reference_pattern` yet); the AWS/GCP migration issues (#1116/#1117) fill in
  the per-backend settings schema, secret-reference patterns, and renderer /
  validation-check wiring. (#1113)
