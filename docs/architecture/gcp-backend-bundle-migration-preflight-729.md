# GCP Backend Bundle Migration Preflight

Status: pre-implementation design constraint for issue #729

Issue: <https://github.com/Brad-Edwards/shifter/issues/729>

This note applies the existing backend-bundle architecture to the GCP control
plane. It introduces no new platform abstraction. ADR-007, ADR-008, ADR-009,
ADR-011, ADR-017, ADR-025, ADR-037, and ADR-039 remain authoritative.

## Decision

The `gcp` entry in `installation.registry` is the declarative description of
one installation backend. It selects and describes existing GCP deployment and
runtime seams; it does not replace them with a generic deploy engine.

The authority chain is:

```text
shifter.yaml operator intent
  -> installation.loader + selected BackendBundle validation
  -> existing GCP renderer with explicit inputs
       (normalized root config + validated Terraform outputs + verified image identity)
  -> existing Terraform, Helm/bootstrap, and runtime renderers
  -> role-scoped env / Secret references / Kubernetes artifacts
  -> existing Django and standalone-provisioner cloud factories
```

Those values are parameters to the existing renderer, not a second public schema,
persisted DTO, or new framework. The renderer must make their sources explicit so
it cannot read arbitrary parent-process environment. This parameter boundary is
the extension seam for another GCP profile or deployment transport: those variants
supply the same normalized intent and derived outputs without changing domain
services or turning bundle metadata into executable code.

The following concepts stay separate:

| Concept | Authority | Boundary |
| --- | --- | --- |
| Installation backend | `RootConfig.backend` and `installation.registry` | Selects the GCP bundle and provider-neutral adapter constructors. |
| Deployment profile | `RootConfig.deployment.profile` | Selects supported GCP defaults/overlays; it is not a branch name. |
| Identity provider | `AUTH_PROVIDER` and ADR-009 | GCP emits `identity_platform`, but cloud selection is not authentication. |
| Range realization | `GCP_RANGE_BACKEND` / `GCP_RANGE_PLANE` and ADR-039 | Chooses GCE/GDC realization behind existing range operations; it is not another installation backend. |
| Resource ownership | existing persisted `cloud_provider` fields | Historical cleanup/routing metadata, not the live installation selector. |
| Delivery orchestration | existing bootstrap and workflow entrypoints | Executes reviewed commands; the registry remains data-only. |

## Bundle Contract

The migration must complete the existing `BackendBundle` rather than add a GCP
schema, registry, capability model, command runner, or exception family elsewhere.

- The GCP `settings_model` is closed with `extra="forbid"`. It owns only
  operator-authored GCP intent, including the existing example's `project_id`
  and `region`. It must compose or delegate `settings.range_egress` to
  `installation.range_egress.RangeEgressPolicy`; copying its fields or
  validators into a GCP model would create conflicting cross-backend policy.
- `deployment.name`, `deployment.domain`, and `deployment.profile` remain root
  fields. In particular, `deployment.domain` is the public-hostname authority.
  A temporary `GCP_PUBLIC_HOSTNAME`/Terraform compatibility input may be read at
  the deploy boundary, but a mismatch must fail rather than choose a winner.
- Every existing workflow, Terraform, Helm, runtime-env, identity, storage,
  Pub/Sub, Secret Manager, task-runner, and range input must be classified as
  one of: root intent, a secret reference, a validated infrastructure output,
  a renderer-owned derived value, or a documented compatibility-only input.
  An unclassified environment variable is not part of the bundle contract.
- `RequiredSecret` records only logical operator-supplied references. Secrets
  created by Terraform stay provider-owned: their IDs are classified
  `GeneratedOutput` secret references and their payloads stay in Secret Manager
  or an ephemeral Kubernetes Secret. Do not require a second root reference for
  a secret that the deployment creates and owns.
- `GeneratedOutput` must enumerate the actual GCP projection, not only
  `CLOUD_PROVIDER`, `APP_SECRET_ID`, and `DB_SECRET_ID`. Each output declares its
  owner, source, destination, sensitivity, and exact `ProcessRole` consumers.
  `IDENTITY_PLATFORM_API_KEY` is browser client configuration rather than an
  authentication secret, but it still needs an explicit classification and
  must not be dumped through logs or error messages.
- Capabilities are claimed only where the existing factories provide them:
  storage, queues, task runner, secrets, config store, event bus, database auth,
  and network inventory. Bundle metadata describes those protocols; it does not
  hold provider class paths or dispatch domain operations.
- `ValidationCheck` command specs remain structured, repository-relative argv
  using declared tools. They identify canonical validation front doors; they do
  not encode shell pipelines, credentials, or an alternative workflow language.
- Any contract/publication change follows
  `installation/published_contract/MIGRATIONS.md`; generated JSON is never
  hand-edited. A settings-schema change must pass the compatibility gate and
  carry the required version/migration story if it narrows an already published
  surface.

## Canonical Incumbents

The implementation must build on these existing boundaries.

| Concern | Canonical incumbent |
| --- | --- |
| Root shape, YAML safety, aggregation, sanitized errors | `installation.schema`, `installation.loader`, `installation.errors` |
| Bundle schema, registry, generated-output classification | `installation.contract`, `installation.registry` |
| Cross-backend range-egress shape and Terraform bridge | `installation.range_egress`, `installation.render` |
| Runtime key ownership and public env shape | `installation.runtime_inventory`, `config/env-manifest.json` |
| GCP derived-runtime validation | `scripts/gcp/render_runtime_env.py` |
| Local/CI prerequisite and secure-input gates | `scripts/bootstrap/preflight.py`, `scripts/bootstrap/bootstrap_core.py` |
| Authoritative GCP packaging and deployment | `scripts/bootstrap/gcp_control_plane.py`, `scripts/bootstrap/deploy.py`, `platform/terraform/gcp/**`, `platform/charts/shifter/**`, `platform/k8s/gcp/**` |
| CI compatibility path | `.github/workflows/_gcp-dev.yml` |
| Django cloud protocols and provider factory | `shifter_platform/shared/cloud/types.py`, `shifter_platform/shared/cloud/__init__.py` |
| Standalone provisioner protocols and provider factory | `engine/provisioner/cloud/types.py`, `engine/provisioner/cloud/__init__.py` |
| GCP task transport and sensitive env split | `shared/cloud/gcp/task_runner.py`, `shared/cloud/sensitive_env.py`, `engine/ecs.py` |
| Identity verification and immutable binding | `config/identity_platform.py`, `config/views.py`, `management/services.py` |
| Runtime secret hydration | `shifter_platform/entrypoint.sh`, `entrypoint-lib.sh` |
| Provider-neutral operational errors | `shared/cloud/exceptions.py`, `engine/provisioner/cloud/exceptions.py` |
| Public errors and safe logging | `shared/api/errors.py`, `shared/errors.py`, `shared/log_sanitize.py`, `engine/provisioner/log_redact.py`, `config/_posture.py` |
| Durable task/event state | `ProvisionerLaunchIntent`, `RangeEventOutbox`, the outbox drainer, and the range reconciler |
| Shared functional smoke logic | `cms.management.commands.run_post_deploy_smoke`, `cms/post_deploy_smoke/**` |

The two cloud-protocol and exception modules are an intentional process
boundary: the standalone provisioner must remain Django-free. Similar-looking
types are not grounds to add a third shared contract or force either process to
import the other.

## Cross-Cutting Security Path

The intended design passes every boundary below before it is considered valid.

| Layer | Required behavior |
| --- | --- |
| Root parser and shape | `load_root_config` rejects unreadable or malformed YAML, duplicate/merge keys, unknown root fields, invalid backend/profile/domain, and raw-looking secret material. Errors use value-free `ConfigIssue` records. No script or workflow reparses YAML. |
| Backend settings and secret references | The selected bundle validates a closed settings model and reference grammar once. Cross-backend range egress stays in its canonical validator. Unknown fields and unresolved required references fail before Terraform or cluster mutation. |
| Bootstrap and IaC policy | Existing bootstrap preflight and Terraform variable validations continue to reject missing hostname/TLS, broad or absent authorized GKE CIDRs, insecure Redis, invalid network posture, and incomplete identity/email inputs. Bundle validation is earlier feedback, not a replacement for the IaC backstop. |
| Supply-chain identity | Existing image build, SBOM/provenance, immutable digest rendering, GitHub attestation verification, Binary Authorization, and exact admission image checks remain before rollout. A bundle profile cannot enable a tag or verification bypass. |
| Renderer shape checks | `render_runtime_env.py` continues to fail closed on missing Terraform outputs, disabled managed TLS, empty public hostname or identity domain, incomplete email, insecure Redis, or mutable provisioner image identity. The renderer consumes explicit parameters, not ambient env wholesale. |
| Runtime env classification | `GeneratedOutput`, `runtime_inventory`, and `env-manifest.json` agree on key ownership, sensitivity, optionality, and role. Public values and secret references may reach ConfigMaps; secret payloads may not. Static and generated GCP env files cannot own the same key. |
| Kubernetes policy | Helm and Kustomize renders preserve restricted PSS, default-deny and explicit-CIDR NetworkPolicies, Workload Identity, least-privilege RBAC, Cloud Armor BackendConfig, managed TLS, and the equivalent base/chart provisioner admission policies. A new task env key updates the explicit forwarding list, sensitive classifier, both admission copies, and their denial/parity tests. |
| Identity seam | Browser authentication remains Identity Platform. Django accepts only the CSRF-protected session exchange, verifies revoked tokens with Firebase Admin credentials, requires literal verified email plus allowed domain/email and TOTP MFA, and binds immutable issuer/subject identity. Backend selection never bypasses or substitutes for these gates. |
| Secret hydration and OS exposure | Runtime artifacts carry provider references only. Workload Identity fetches payloads at startup; per-Job sensitive values use ephemeral Secret-backed `valueFrom`. Payload parsing and CLI submission use stdin or protected temporary files, never process argv. Command logging uses redacted argv and must not print config, references, Terraform output objects, provider responses, or environment maps. |
| Adapter and public errors | Installation failures stay `InstallationConfigError`; provider operations retain the existing process-local cloud exceptions. Internal diagnostics are bounded and sanitized. HTTP, WebSocket, health, and event surfaces use the existing fixed/sanitized envelopes and never expose raw provider or configuration exception text. |
| Persistence and delivery | Backend selection is process configuration. Existing Engine state, launch-intent idempotency, transactional outbox, retry/DLQ, and authoritative reconciliation remain in force. Bundle metadata neither persists a new selector nor becomes a queue/event schema. |

Observability should log one normalized non-secret startup posture: selected
backend, deployment profile/environment, and supported capability names. Secret
references, internal hosts, account identifiers, Terraform output payloads, and
identity tokens are not posture fields. Provider identifiers needed for
correlation use the existing masking/fingerprinting helpers.

## Compatibility Contract

`_gcp-dev.yml`, `scripts/bootstrap/deploy.py`, GCP Terraform roots, the Shifter
Helm chart, GCP Kustomize assets, and `render_runtime_env.py` remain the reviewed
implementation entrypoints during this migration. The bundle points to and
feeds them. Replacing branch routing or creating a fully generic deployment
orchestrator belongs to the follow-on routing work, not issue #729.

Compatibility inputs are read-side aliases only:

- Root-derived values are written into the existing Terraform/renderer inputs.
  A legacy environment or tfvar may temporarily supply the same field, but
  conflicting values fail closed and new documentation authors only the root
  field.
- Existing secret-bearing GitHub environment protections and Workload Identity
  Federation gates remain intact. Moving a reference into `shifter.yaml` does
  not authorize moving the secret value there.
- Existing Terraform moved blocks, resource names, Secret Manager IDs, Helm
  value names, Kustomize overlays, `pulumi-provisioner` image-root naming, and
  persisted provider values remain readable until their owners have an explicit
  deprecation/removal migration. Compatibility names do not become bundle or
  range selectors.
- The migration is complete only when every root value that changes GCP runtime
  behavior has one renderer-owned downstream projection and the old authoring
  path is either removed or documented as an alias with conflict detection.

## Validation And Smoke Expectations

GCP bundle conformance is layered; no single probe substitutes for the others.

| Gate | Expected evidence |
| --- | --- |
| Contract | Root config, closed GCP settings, secret-reference grammar, registry invariants, runtime inventory, examples, and published-contract drift/compatibility tests pass. |
| Pre-mutation GCP validation | Existing bootstrap preflight; Terraform format/init-without-backend/validate, TFLint and policy checks; runtime-env rendering from representative Terraform outputs; Helm/Kustomize rendering; admission parity/denial tests; kube-linter and strict kubeconform all pass. |
| Artifact smoke | The shared built-image stack smoke still proves the production image boots and serves dependency-aware `/health/`; it does not by itself prove GCP deployment or range behavior. |
| Deployment security | Attestation and exact digest verification precede mutation; Helm deploy is atomic and waits; managed certificate/edge readiness, workload rollout, and HTTPS `/health/` are verified without exposing credentials. |
| GCP functional smoke | Invoke the existing `run_post_deploy_smoke` domain command through a GKE-appropriate execution transport, using a dedicated automation identity. It must exercise a real GCP range create, guest-connectivity probe, teardown, and cleanup/reconciliation. Do not fork the smoke domain logic into a GCP copy. |

`HealthCheck` metadata describes stable, read-only targets such as
`https://<deployment.domain>/health/`. Credentialed functional smoke and
mutation remain workflow/bootstrap responsibilities, not registry command data.

## Gotchas And Anti-Patterns

- Do not merge `CLOUD_PROVIDER`, `AUTH_PROVIDER`, deployment profile,
  `GCP_RANGE_BACKEND`, and persisted resource provider into one "provider" enum.
- Do not add another GCP config model in a workflow, renderer, Terraform JSON,
  Django settings, or Helm values. Terraform may retain resource-level
  validation; it does not become a second operator-intent schema.
- Do not make the registry import provider SDKs, Django, adapter classes, or
  callable deployment entrypoints. Structured validation metadata is not an
  execution framework.
- Do not copy the workflow environment into a runtime ConfigMap or task. Forward
  explicit role keys and preserve the secret/reference distinction.
- Do not weaken managed TLS, Cloud Armor, authorized control-plane CIDRs,
  restricted PSS, NetworkPolicy, Workload Identity, Redis AUTH/TLS, resource-
  scoped IAM, image provenance, admission, or environment approval gates to
  make bundle selection easier.
- Do not expose Terraform `sensitive` output payloads, Secret Manager references,
  Firebase tokens, provider exceptions, or rejected settings through validation,
  logs, health responses, events, or API envelopes.
- Do not add GCP branches to domain services. Branch only at the existing Django
  and standalone-provisioner composition roots and ADR-039 substrate factory.
- Do not add a database table, API field, request option, event field, or task
  argv `--provider` for installation selection.
- Do not treat the current AWS/SSM smoke wrapper as provider-neutral. Reuse the
  management command and probe logic; provide only the GKE execution transport.
- Do not hand-edit generated runtime env, generated contract JSON, Terraform
  outputs, or compatibility files that already have canonical renderers.

## Non-Goals

- Replacing `_gcp-dev.yml` branch routing or designing the later backend matrix.
- Redesigning GCP Terraform resources, Helm packaging, GKE/GDC topology, Cloud
  Armor, managed certificates, networking, or state storage.
- Replacing Identity Platform, changing account-binding/MFA policy, or unifying
  cloud and identity provider selection.
- Redesigning shared cloud protocols, task dispatch, range lifecycle/status,
  persistence, events, retries, reconciliation, or ADR-039 semantics.
- Renaming legacy resources, image roots, persisted provider fields, or aliases
  without a separately reviewed migration.
- Adding a new deployment framework, workflow DSL, secret resolver service,
  exception hierarchy, logging framework, repository layer, or public DTO.
