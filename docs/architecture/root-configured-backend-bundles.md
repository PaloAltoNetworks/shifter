# Root-Configured Backend Bundles

Status: current architecture, constrained by ADR-011

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1109>

## Summary

Shifter uses one root installation config, `shifter.yaml`, to select the
deployment backend and deployment profile.

The implementation lives in `shifter/installation/`:

- `schema.py` validates root fields.
- `loader.py` reads YAML, rejects duplicate keys and merge keys, and dispatches
  backend checks.
- `contract.py` defines the backend bundle contract.
- `registry.py` contains the supported backend bundles.
- `runtime_inventory.py` records checked-in runtime config surfaces and validates
  env-key drift without reading values.
- `cli.py` exposes `shifter-config`: `init` (scaffold a starting `shifter.yaml`),
  `validate`, `doctor` (backend-aware pre-deploy validation, #727), `render`,
  `render-runtime`, `runtime-inventory`, and `contract`.
- `doctor.py` / `_doctor_model.py` / `_doctor_seams.py` implement the backend-aware
  `doctor` executor (#727); `scaffold.py` implements `init`.
- `examples/` contains validated AWS and GCP examples.

Contract publication guidance for issue #1323 lives in
`docs/architecture/backend-bundle-contract-publication-preflight-1323.md`.
Cross-backend Helm packaging and AWS EKS bundle constraints for issue #1324
live in `docs/architecture/aws-eks-helm-packaging-preflight-1324.md`.
GCP migration constraints for issue #729 live in
`docs/architecture/gcp-backend-bundle-migration-preflight-729.md`.
Backend-aware setup and doctor UX constraints for issue #727 live in
`docs/architecture/backend-aware-setup-doctor-preflight-727.md`.

Published operator docs:

- `shifter/installation/README.md`
- `docs/technical/dev/installation-config.md`
- `docs/technical/dev/setup.md`

## Root Config Boundary

`shifter.yaml` is user-authored installation intent. It is not a Terraform
output file, Helm values file, generated runtime environment file, Kubernetes
manifest, or CI branch selector.

The root config owns:

- schema version
- selected backend
- deployment name
- deployment domain
- deployment profile
- logical secret references
- backend-specific settings mapping

`.shifter.yaml` is a separate checked-in policy namespace for `mcp/ops`. It is
not the public installation config and must not become a deployment secret
store. Gitignored `.env` files remain local/operator inputs only; checked-in
runtime env files are either static non-secret overlays or generated
placeholders validated by the runtime inventory.

The root schema validates root shape. Backend bundles validate backend-owned
settings and secret reference grammar when they declare those validators.

## Supported Backends

| Backend | Profiles | Required secrets | Settings validation |
| --- | --- | --- | --- |
| `aws` | `prod`, `dev`, `proof` | `django_secret_key`, `db_password` | Closed `AwsSettings` model: `region` (required); unknown keys rejected. Secret references validated against a machine-readable grammar (#728). |
| `gcp` | `prod`, `dev` | `django_secret_key` | Closed `GcpBackendSettings` model: `project_id`, `region` (required); unknown keys rejected. Secret reference validated against a machine-readable grammar (#729). |

`range_egress` under `settings` is the shared, cross-backend egress policy
(PLAT-220); it is owned and validated by `installation.range_egress` for every
backend, so a backend's closed settings model does not redeclare it.

## Validation

Run from the repository root:

```bash
uv run --project shifter/installation shifter-config validate shifter.yaml
uv run --project shifter/installation shifter-config runtime-inventory --check
```

Validation rejects:

- missing config files
- invalid YAML
- duplicate YAML mapping keys
- YAML merge keys (`<<`)
- non-mapping top-level YAML
- unknown top-level fields
- unknown `deployment` fields
- missing required fields
- unknown backend names
- unsupported profile/backend combinations
- malformed deployment names or domains
- malformed secret names or references
- missing required backend secrets
- secret names not used by the selected backend
- checked-in generated runtime env stubs with assignments
- duplicate keys between static runtime env files and renderer-owned keys
- unregistered checked-in runtime secret env assignments

Validation errors are path-based and do not echo rejected input values.

## Secret Handling

`shifter.yaml` stores references, not secret values.

Accepted reference forms are backend-described strings such as provider secret
names, GitHub Actions secret names, environment variable names, or the literal
`prompt`.

The schema rejects recognizable raw secret material, including PEM blocks,
multi-line values, and implausibly long values. Short raw values can look like
references, so `gitleaks` remains part of enforcement.

Generated backend outputs classify sensitive data as:

- `public`
- `secret-reference`
- `secret-value`

`secret-value` outputs may only be placed in a Kubernetes Secret or provider
secret store.

## Runtime Binding

Runtime configuration is a deploy-time projection of validated installation
intent, not a second operator-authored contract:

```text
shifter.yaml
  -> installation.loader.load_root_config
  -> selected BackendBundle settings/secrets validation
  -> backend-owned renderer plus validated infrastructure outputs
  -> process-role runtime bindings
  -> existing Django and provisioner cloud factories
```

Only deployment tooling reads `shifter.yaml`. Portal, worker, and provisioner
containers consume the derived bindings; they do not mount, parse, persist, or
live-reload the root file. A configuration change takes effect through the
normal render/deploy/restart path.

The selected backend identity is emitted once for every consuming process role.
All deployed roles must receive the same value, and deployed startup must fail
when it is absent or unsupported rather than silently defaulting to AWS. Explicit
development, test, and build defaults remain governed by
`config._runtime_env.runtime_allows_dev_defaults`. Django management-command
workers import the same settings modules as the portal and must not gain a
separate loader or provider selector.

`installation.registry` remains declarative: it owns backend identity,
capabilities, settings validation, generated-output metadata, sensitivity, and
process roles. It does not import Django or provider adapter implementations.
Runtime operations continue through the existing protocol/factory seams in
`shifter_platform.shared.cloud` and `engine/provisioner/cloud`; domain services
must not branch on the backend or import provider SDKs. Backend metadata,
task-runner dispatch, and ADR-039's per-range substrate adapter are distinct
concepts. `GCP_RANGE_BACKEND` / `GCP_RANGE_PLANE` are range realization choices,
not alternative installation backend selectors.

Every root setting that affects a runtime must become a declared generated
output with an owner, destination, sensitivity, and `ProcessRole`. Infrastructure
identifiers discovered after provisioning may join the projection as validated
renderer inputs; they are derived state, not competing installation intent.
Renderers must emit only the keys required by the destination role. They must not
copy the parent process environment wholesale.

Backend selection is not derived from branch names, workflow refs, Terraform
directory names, Helm values, or compatibility names such as
`pulumi-provisioner`.

### Runtime validation and security gates

The derivation path must preserve these existing cross-cutting gates:

| Boundary | Canonical incumbent | Required behavior |
| --- | --- | --- |
| Root YAML and config shape | `installation.loader`, `installation.schema` | Reject malformed/duplicate/merged YAML, unknown fields, invalid backend/profile combinations, and raw-looking secret material before rendering. Use the sanitized `InstallationConfigError`; never surface rejected values. |
| Backend-owned settings | `BackendBundle.settings_model` and `secret_reference_issues` | Use one closed (`extra="forbid"`) model per backend and normalize once in `load_root_config`. Do not recreate the model in a renderer, Django settings, Terraform, or a workflow. Both AWS (`installation.settings_aws.AwsSettings`, #728) and GCP (`installation.settings_gcp.GcpBackendSettings`, #729) ship closed models in dedicated modules; the `local` backend (#1119) remains provisional until its migration. |
| Output classification | `GeneratedOutput`, `OutputSensitivity`, `OutputDestination`, `ProcessRole` | Keep secret values out of runtime env files, ConfigMaps, Terraform variables, Helm values, dry-run output, and plan/log surfaces. Runtime files may carry public values and secret references only. |
| Runtime env shape | `installation.runtime_inventory` (with the per-backend `runtime_inventory_aws` / `runtime_inventory_gcp` key sets), `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/aws_eks.py` `render_aws_values`, `config/env-manifest.json` | Keep renderer-owned, static, optional, and secret-backed keys classified and drift-tested. The backend bundle `generated_outputs` are derived from the per-backend inventory so the contract and renderer cannot drift. A new key must update every applicable inventory/manifest/test surface rather than bypassing them. |
| Django/worker startup | `config._runtime_env`, `config._cloud`, `django.core.exceptions.ImproperlyConfigured` | Resolve the normalized binding at the composition root, apply existing dev/test default policy, and fail deployed startup on missing or unsupported configuration. Workers reuse this exact path. |
| Identity selection | ADR-009, `AUTH_PROVIDER`, `config._oidc_settings`, `config.identity_platform` | Keep identity-provider selection distinct from the cloud backend. If a backend renderer emits `AUTH_PROVIDER`, validate its allowlist and continue through the existing issuer, token, verified-email, immutable-subject, MFA, and bootstrap authorization gates; a matching cloud backend is not identity validation. |
| Secret hydration | `entrypoint.sh`, provider secret stores | Pass references through deployment artifacts and fetch values at startup. Secret payloads flow through stdin/environment, never command argv, generated public files, or log messages. Preserve the current reference/value distinction and existing KMS/workload-identity controls. |
| Provisioner task dispatch | `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, `shared.cloud.sensitive_env`, `GCPTaskRunner`, `restrict-provisioner-jobs` admission policy | Keep explicit env-key forwarding, sensitive values in ephemeral Secret-backed `valueFrom` entries, pinned images/commands, and fail-closed literal/secret allowlists. Any binding change must keep the base and Helm admission policies plus their structural tests synchronized. |
| Adapter errors and observability | `shared.cloud.exceptions`, `engine/provisioner/cloud/exceptions.py`, `config._posture`, `shared.log_sanitize` | Keep installation validation errors separate from cloud-operation errors. Log only normalized non-secret posture (backend, profile/environment, capability names) and bounded/sanitized diagnostics; never dump root config, env mappings, secret references, Terraform output payloads, or provider responses. |
| Persistence and delivery | Engine resource state, `ProvisionerLaunchIntent`, range-event outbox/reconciler | The active installation backend is process configuration, not a new database row, request field, launch-intent field, or event field. Existing persisted `cloud_provider` values remain historical resource ownership/cleanup metadata, never a live selector. |
| Public error surfaces | `shared.api.errors`, `shared.errors`, coarse health responses and status events | Configuration failures stop startup or task dispatch. They do not pass raw installation/provider exception text, config paths, references, or capability details into HTTP, WebSocket, health, or event envelopes. Reuse fixed or sanitized public messages. |

Unsupported backend/capability combinations fail before infrastructure mutation or
task submission. Runtime factory errors remain a defense-in-depth backstop, not
the primary validator.

The process/OS boundary carries only the classified projection. Backend names may be
literal environment values because they are public, but root config blobs, provider
credentials, secret values, and secret references must not appear in process argv.
Provisioner argv remains the existing validated operation plus request identifier;
backend selection is not a request-controlled `--provider` option. Long-lived
containers must not receive a mounted root config merely to re-prove selection.

### Whole-repository and extensibility guardrails

The active-provider read is currently scattered beyond the two cloud factory modules.
The implementation must account for Django cloud settings and startup posture,
capacity metrics, browser CSP/storage selection, Engine task dispatch and terminal
credential guards, provisioner cloud/executor factories, Terraform/range/NGFW/state
helpers, and Polaris bootstrap. These sites must consume their composition root's one
validated selection. A legacy persisted resource with no provider tag may keep its
documented compatibility interpretation; that historical fallback must not become a
live process default.

The host/config surfaces are also one contract: AWS portal/worker/provisioner Terraform
environment declarations; the GCP renderer, static/generated env ownership,
Kustomize/Helm ConfigMaps, task-runner forwarding, and both admission-policy copies;
the portal and provisioner Docker build inputs; and CI/deploy path filters. If the
provisioner image consumes `installation` as the portal image already does, an
`installation/**` change must exercise and rebuild both consumers. Env-manifest,
runtime-inventory, admission drift, built-image smoke, actionlint, Terraform, Helm,
kube-linter, and kubeconform checks remain synchronized with the surfaces they guard.

The extension parameter is the selected `BackendBundle`, `ProcessRole`, and
`BackendCapability`. Runtime composition roots may own a lazy constructor map keyed by
backend and capability; executable class/import paths do not belong in the declarative
installation registry. A future backend adds a bundle/settings model, classified
outputs, only the adapter constructors for capabilities it claims, and conformance
evidence. It must not require provider branches in domain services, public DTOs,
events, worker workflow, or ADR-039's range-substrate port. New capability enum members
are never auto-claimed by existing bundles.

### Gotchas and anti-patterns

- `CLOUD_PROVIDER` is renderer-owned for both backends (PLAT-2005): GCP emits it from
  `scripts/gcp/render_runtime_env.py` (a generated key in the runtime inventory, not a
  static overlay literal), and AWS derives it from `shifter.yaml` at deploy time via
  `shifter-config render-runtime` into `cloud_provider.auto.tfvars`, which the portal and
  engine-provisioner modules receive as `var.cloud_provider`. Do not reintroduce a
  hardcoded task-definition/overlay literal or an implicit AWS default; the deployed
  backend identity must come from the selected bundle.
- Both AWS (#728) and GCP (#729) ship closed `settings_model`s. PLAT-2005 may use the
  validated backend identity and registry-declared capabilities, but must not make adapter
  selection depend on arbitrary backend settings where a backend has not yet supplied a
  closed model.
- `AUTH_PROVIDER`, `CLOUD_PROVIDER`, deployment profile/environment, and
  `GCP_RANGE_BACKEND` / `GCP_RANGE_PLANE` are separate concepts. Do not normalize them
  into one provider enum or infer one from another inside domain code.
- Do not fall through to AWS for an unknown provider in optional subsystems such as
  metrics or browser storage policy. Unsupported means a startup/configuration error,
  not AWS-compatible behavior.
- Do not hardcode supported-provider lists in exception messages or duplicate a
  capability matrix in settings, Terraform, Helm, or the provisioner. Derive support
  from the installation registry; keep executable adapter wiring only at composition
  roots.
- Do not update only a renderer or factory. Generated env inventories, Django's env
  manifest, AWS task definitions, GCP admission allowlists, Docker inputs, workflow path
  filters, and focused tests are downstream consumers of the same contract.

### Runtime binding non-goals

- No database model, repository, API DTO, request parameter, session value, or
  per-tenant override for installation backend selection.
- No second backend registry or exception hierarchy in Django, workers,
  provisioner code, renderers, Terraform, Helm, or workflows.
- No provider SDK objects, Terraform output shapes, or bundle metadata exposed to
  domain services.
- No removal of compatibility env aliases in this change; aliases are read-side
  migration aids and must not become new authoring surfaces.
- No redesign of task dispatch, range lifecycle/persistence, ADR-039 substrate
  semantics, authentication, secret storage, or provider infrastructure.

## Backend Bundle Contract

A backend bundle declares:

- backend identity and supported profiles
- required command-line tools
- required logical secrets and accepted reference grammar
- generated outputs, destination, sensitivity, and consuming process roles
- validation checks
- health checks
- cloud-neutral capabilities
- backend-owned repository paths and docs

Validation command specs are argv arrays, not shell strings. The contract rejects
shell metacharacters, absolute host paths, path traversal, and tokens with
internal whitespace.

## Published Contract Artifact

The backend-bundle contract is published as a committed, versioned JSON artifact so
downstream backend-bundle authors and tooling can build against it without reading
Shifter internals (issue #1323, ADR-011-R8).

- `shifter/installation/published_contract/backend-bundle-contract.json` — the published
  artifact: the contract version, the supported versions, the `BackendBundle` JSON schema,
  and the registered backends. It is **generated** from `contract.py` and `registry.py`;
  never hand-edit it.
- `shifter/installation/published_contract/backend-bundle-contract.v<N>.json` — the
  immutable frozen snapshot of contract version `N`; the breaking-change gate compares the
  current artifact against the current version's snapshot, and `export` never overwrites one.
- `shifter/installation/published_contract/MIGRATIONS.md` — the per-version changelog and
  migration notes, and the procedure for changing the contract.

The published version is the backend `contract_version`
(`SUPPORTED_CONTRACT_VERSIONS`), independent of `RootConfig.version` and of the
`installation` package version.

Regenerate and check the artifact from the repository root:

```bash
uv run --project shifter/installation shifter-config contract export
uv run --project shifter/installation shifter-config contract check
```

The `installation` test lane enforces three gates, so the published contract cannot fall
behind the code or break silently:

- **drift** — the committed artifact must equal the freshly generated one;
- **breaking change** — a backward-incompatible shape change (removed field, removed enum
  value, newly required field) versus the current version's immutable frozen snapshot
  requires an explicit `contract_version` bump and a migration note;
- **registry conformance** — every published backend record validates against the published
  JSON schema.

A new backend bundle (for example a deferred Azure bundle) is written against this
published artifact — the JSON schema and the `aws`/`gcp` reference entries — plus a
registry entry and a worked `examples/` config. Authors do not need to read Shifter
runtime internals.

### Validating a candidate bundle

The published JSON schema encodes the security-relevant contract validators: identifier
grammars, safe command `argv` tokens (an executable at `argv[0]`, no shell metacharacters,
no absolute paths, no `..` traversal), repository-relative owned paths, the supported
contract versions, and the rule that a `secret-value` output may only target a Kubernetes
Secret or provider secret store. A downstream author can therefore validate a candidate
against the schema with any Draft 2020-12 validator.

`installation.validate_published_bundle(record)` is the **authoritative, parity-complete**
validator: it runs the published schema **and** the full `BackendBundle` contract, so it
additionally enforces the cross-collection invariants JSON Schema cannot express (unique
record names, every validation check's executable listed in `required_tools`). A bundle it
accepts cannot be one the internal contract would reject, closing the supply-chain gap where
a hostile bundle passes a public validator that omits Shifter's custom validators.

## Source Of Truth

Do not create a second root-config parser in scripts, Django settings,
Terraform, Helm, or examples. Import or execute the `shifter/installation`
package instead.

Do not treat CI branch names, Terraform environment directories, Helm values, or
generated env files as additional authoritative backend selectors.
