# RAES In-Tenant Artifact Preparation Preflight

Issue: GitHub #1583, "In-tenant artifact preparation (optional BigRAE backend capability)."

Status: implementation architecture and validation record. The supplied
GEN-002 requirement governs executable architecture enforcement; #1583 supplies
the capability scope. ADR-053/034 govern ownership and ingestion; ADR-054/046
govern deployment and internal authority. The existing ADRs, including
ADR-034-R9, suffice.

Implementation baseline, 2026-09-14: the dependency upgrade to `raes==3.5.0` /
`raes-env-packs==5.2.0` and its compatibility repairs precede the reviewed
[design](raes-in-tenant-artifact-preparation-design-1583.md). The implementation
follows the accepted authority direction: the RAE runtime controls the backend;
the GCE adapter materializes open portable intent and reports observations back
through the runtime contract.

Shifter maintains the adapters, declared profiles, concrete build material and
scenario-specific preparation code needed by this repository. Upstream supplies
portable contracts and authored permission, not Shifter's cloud recipes. A
missing Shifter adapter is repository implementation work. Versioned build code
runs inside an explicitly installed adapter's isolated environment; neither pack
registration nor authored permission installs that code or grants cloud authority.

## GEN-002: Enforcement And Evidence

Apply the existing governance chain, not a preparation-specific policy framework.
`docs/adr/index.yaml` and `exceptions.yaml` remain authoritative; `_guard/_registry.py`
selects executable checks, and `_guard/checks/adr_registry.py` validates registry
structure and the registered typed contracts. A rule's prose, evidence path or
empty `checks` list does not make its runtime behavior executable or verified.

| Accepted constraint | Existing enforcement to retain | Evidence #1583 must supply at its owning boundary |
| --- | --- | --- |
| ADR-001 / ADR-031 / ADR-032 | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, public RAES accessor/conformance suites | Real service-facade calls and pinned upstream contracts; no portable-schema fork or provisioner dependency on RAES. |
| ADR-034-R8/R9 / ADR-053 | Pack, resolution, inventory and launch suites | Explicit permission, no-worker reuse, independent verification and admitted immutable binding; registration alone proves none of these. |
| ADR-006 / ADR-054 | Kubernetes/IAM checks and `test_gcp_job_launcher_manifests.py` parity/denial patterns | Effective dedicated preparation identity, admission, private pull, egress and cloud-guest denial; current Deployment checks and provisioner policy do not cover a new Job family automatically. |
| ADR-043 / ADR-046 / ADR-054 | Operation-envelope, PostgreSQL lifecycle, actor/token and strict-audit suites | Attempt-scoped access, duplicate/cancel/revoke races, atomic admission and recoverable cleanup against real persistence. |
| ADR-002 / ADR-003 / ADR-004-R24 / ADR-019 | Guardrail docs, quality ownership, skip/routing checks and boundary-mock ratchet | Each changed production path reaches blocking checks; tests exercise real first-party behavior and mock external effects only. |

Local pre-commit and `.claude/hooks/adr_guard_hook.py` run different subsets;
neither substitutes for `adr_guard.py --all --level ci`. Preserve the complete
CI route: `deploy.yml` Quality selection → `_quality.yml` path classification /
independent `guard_selfcheck` → conformance and owning suites → `PR Gate`.
Use `.github/quality-path-filters.yaml` and `scripts/quality_ownership` for path
ownership. Conformance does not honor `skip_tests`; the protected deploy caller
passes `skip_tests: false`, while the reusable guard-test job itself can be
skipped. Do not mistake test presence for unavoidable execution. New conformance
checks must be reachable from the required profiles and CI route, including
when test skipping is exercised. Record any deferred enforcement as a narrowly
scoped, owned, dated exception in `docs/adr/exceptions.yaml`, never a new skip
switch, growing baseline, or silent advisory gate. This preflight adds no check
or exception and does not claim deployed-cloud evidence.

The preparation worker is owned Python in `shifter/packer`, so `_quality.yml`
publishes its package-configured coverage artifact and the Sonar job consumes it.
Sonar source exclusions also exclude tests from bug and smell analysis while
coverage continues to use the test-produced report. This keeps the 80% changed
code gate tied to production paths and makes a missing packer report fail loudly.

## Boundary

Preparation is a tenant/product-surface BigRAE capability: an isolated,
ephemeral worker may create an operator-owned backend artifact *only* from an
upstream-declared, explicitly permitted materialization specification that the
selected backend declares it can execute. It is neither a catalog,
distribution/promotion channel, entitlement service, nor a generic image-build
API.

Preparation is an availability producer for the one server-owned resolution
seam in `shared.raes.artifact_resolution`; it is not another resolver. A
completed, admitted, immutable result may become backend inventory and then be
selected and generation-fenced by the existing launch path. It must complete
before range provisioning is authorized. The provisioner never starts, resumes,
or polls a preparation job.

The current backend manifest truthfully declares only `exact-artifact`; it has
no materialization mechanism. Do not advertise a preparation route until the
released public RAES/Environment Packs materialization contract, its validator,
the exact mechanism profile, and the real isolated adapter are all present.

## Guardrails

- Consume the pinned public RAES and Environment Packs materialization models,
  validators, route/profile identity, and diagnostics. Do not parse SDL or
  release-tool output, import private upstream modules, or introduce a Shifter
  portable materialization DTO, recipe language, or diagnostic vocabulary. A
  bounded Shifter adapter-registration manifest and internal operation records
  are necessary operational contracts, not competing RAES schemas. Keep RAES
  imports in `shared.raes`; the standalone provisioner stays dependency-light.
- Preserve author posture: absent is not a request; exact accepts only its
  authored immutable identity; opaque, externally governed, unsupported, or
  non-buildable requirements fail through the existing typed resolution result.
  A missing registry mapping never creates a build request. Constrained/open
  behavior remains unavailable unless the upstream contract and a declared,
  independently verified mechanism specifically permit it.
- Keep selection, preparation readiness, trust/admission, acquisition, and
  realization timing independent. A successful build is not provenance,
  admission, publication, or a reason to overwrite an existing exact mapping.
  Store the immutable output identity and verified provenance/admission evidence
  through the existing portable inventory projection; retain the result rather
  than a mutable tag or worker transcript.
- Preparation has a distinct durable lifecycle because it is not a range
  operation, but it must reuse the existing transactional mutation, lease,
  idempotency, bounded retry, result-inbox/disposition, request correlation,
  audit, and cleanup conventions. Do not overload `Range` status,
  `ProvisionerLaunchIntent`, `OperationInput`, `RaesPackageSource`, image-map
  notes, or an outbox row as preparation state. A duplicate request must converge
  on one immutable result or a stable terminal failure; stale worker completion
  must be fenced out.
- The worker is a separately admitted workload identity and Job contract, not a
  new command accepted by the provisioner launcher and not the provisioner
  service account. Its Kubernetes/RBAC/admission policy must pin its image,
  command grammar, service account, labels, bounded resources/deadline,
  non-root/read-only/drop-ALL posture, allowed volumes, and literal versus
  Secret-backed environment keys. The current `restrict-provisioner-jobs`
  policy deliberately cannot be widened to allow arbitrary build commands.
- The worker receives only an opaque preparation id on argv. It retrieves its
  validated, bounded input through a least-privilege read boundary; recipe,
  artifact/provider references, signed URLs, credentials, payload bytes, and
  secrets stay out of argv, generic environment projections, labels, annotations,
  events, audit JSON, metrics, logs, and public status responses. No shell
  interpolation or package-supplied executable hook is a controller/launcher
  seam. Authorized registration/detail surfaces necessarily accept or expose
  bounded manifest identities; Kubernetes necessarily sees a private image pull
  reference. Protect those surfaces by access control, not a promise that the
  required reference is absent everywhere.

## Post-Setup Extension And Authority Boundaries

- ADR-054 makes the deployment the customer security boundary. Organization,
  workspace, content-author, application-administrator and cloud-operator
  authority remain independent. `RaesPackageSource.scenario_id` is globally
  unique within the deployment; `RaesImageMapping` is keyed by provider/source
  alias/version and its service filters only by provider. Neither model proves
  account/project/region ownership or workspace-private visibility. Bind adapter
  registrations, operations, evidence, inventory and reuse to the trusted
  deployment/backend scope. Resolve workspace permissions through
  `workspaces.services` where applicable; do not invent another tenant model or
  silently claim workspace privacy for the existing deployment-wide registry.
- CMS session/token permissions and `validate_cms_authoring_user` authorize pack
  registration, not executable installation. Adapter administration needs an
  explicit operation in the owning authorization policy, active actor checks at
  the service boundary, exact token scope, and strict audit. Staff, Threat
  Research, workspace admin, a pack dependency or a profile declaration must not
  implicitly grant cloud IAM, registry access, or installation authority. Apply
  the same scoped checks to list/detail, preparation, cancellation and evidence
  reads, including CLI/service callers; foreign and missing identities must not
  become an enumeration oracle.
- Private packs use `cms.services.register_pack`, `pack_validation`,
  `RaesPackageSource`, `shared.raes.object_source` and the existing launch
  staging boundary. Repo content must be operator-staged under the configured
  root; object content uses configured private object storage and bounded,
  immutable retrieval. Registration currently records conformance `pending`;
  it neither performs object conformance nor provides automatic promotion to
  `passed`. The after-setup walkthrough must exercise the trusted validation /
  conformance promotion as well as preparation and launch. Do not bypass that
  gate, require a source checkout/platform image rebuild, or create a second
  private-pack loader. Acquisition/entitlement remains outside ingestion.
- One versioned adapter manifest binds the worker protocol version, adapter
  version and manifest digest, full upstream profile identities, backend,
  specification/input contract, output/verifier contract and immutable registry
  image digest. Reject unknown versions/fields, duplicate or ambiguous matches,
  mutable image tags, undeclared input overrides, and mismatched locks before
  dispatch. Requested privileges are bounded requirements intersected with an
  administrator's grant, never raw IAM/RBAC/PodSpec supplied by the manifest.
  Preserve the upstream distinction between a specification reference and its
  profile-defined build material. Verify both the reference and actual input
  bytes/identities; a list of locked-input names is not verification.
- Registration must feed a validated runtime projection into both capability
  evaluation and a **dedicated preparation** Job admission profile. Effective
  support is the intersection of installed/enabled exact adapter versions,
  qualified backend support and tenant grants. The static
  `backend-manifest.json` and `manifest.py` remain canonical for shipped support;
  private entries must not require editing/releasing that artifact or publish
  private metadata in the public manifest. Reuse its upstream model/builder and
  fail closed while runtime admission/config projection is missing or stale.
- Reuse `KubernetesTaskRunner` / `KubernetesTaskProfile` for Job mechanics.
  The inspected working-tree profile includes `image_pull_secrets`,
  `resource_requests`, `resource_limits` and `active_deadline_seconds`; build on
  these parameters rather than introducing another Job builder. Their presence
  does not validate a grant or qualify preparation admission. The provisioner
  policy still pins one configured image, service account, argv and env grammar.
  A preparation admission check must bind the
  whole registered image/identity/grant/command tuple, cover every preparation
  workload rather than trusting caller labels, and deny foreign service
  accounts and image-pull secrets. Merely allowing any digest-pinned image under
  the provisioner account is unsafe. An additional adapter within an already
  supported worker protocol/security profile must install as tenant data without
  a release or rebuild; a new privileged runtime is not an ordinary extension.
- Operations pin adapter/manifest/image/verifier versions and the effective
  grant/policy revision in addition to package/profile/specification/input and
  backend identity. Include those identities in idempotency and reject reuse of
  a caller key with different input. Serialize dispatch against disable/retire
  transitions. Upgrade never retargets an operation; disable stops new starts;
  retirement keeps referenced versions, registry access and bounded cleanup
  authority until in-flight work is resolved. Emergency revocation/cancellation
  fences result admission first and retains independently controlled cleanup;
  it must not leave a malicious adapter with indefinite credentials. Artifact
  admission/revocation and retention remain independent from adapter retirement.

## Incumbents And Required Gates

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Portable semantics and resolution | `shared.raes.artifact_resolution`, `artifact_inventory`, `manifest`, `backend-manifest.json` | Supply normalized admitted availability facts to the existing resolver; declare a mechanism only after executable support exists. |
| Pack/source trust | `cms.scenarios.pack_validation`, `shared.raes.package_loader`, `object_source`, `RaesPackageSource` | Reuse containment, bounded extraction/download, upstream validation, immutable package identity, and canonical digest checks before reading a permitted spec. |
| Inventory and binding | `RaesImageMapping`, `engine.services._raes_image`, `RaesArtifactSatisfactionBinding`, `shared.raes.artifact_binding` | Admit one complete portable identity plus integrity/provenance evidence; launch persists the selected byte-free binding and never looks up mutable worker state. |
| Range launch and transport | `cms.services._raes_range_create`, `engine.launch_intents`, `engine.operation_inputs`, `shared.operation_envelope`, `shared.raes.operation_input` | Keep preparation before this boundary; reuse immutable generation-fenced range transport rather than adding preparation behavior to it. |
| Async reliability | launch intents, `OperationResultInbox`, result applier, transactional outbox, worker heartbeat/lease conventions | Give preparation the same idempotency, fencing, retry/DLQ, terminal disposition, and cleanup discipline without conflating it with provisioning. |
| Admission pressure | `shared.rate_limit.consume_fixed_window`; durable reservation patterns in Engine capacity admission and CTF communication backpressure | Reuse the shared counter and transaction patterns, not those domains' range/event records. Bound preparation's outstanding operations and cloud resources as well as request rate; retain cleanup capacity during saturation. |
| API/auth/audit/errors | CMS permissions and actor validation, `shared.api.errors`, `shared.errors`, `RequestIDMiddleware`, `shared.audit`, `shared.log_sanitize` | Server-select target and authorize mutations; use bounded stable diagnostics and one strict successful-mutation audit. |
| Job isolation/secrets | `shared.cloud.kubernetes`, `shared.cloud.sensitive_env`, provider task-runner profiles, GCP/Helm admission-policy parity tests | Create a dedicated closed worker profile and least-privilege identity; preserve ephemeral Secret refs and never broaden provisioner authority. |
| Config/deployment | `config/_raes_settings.py`, `_runtime_env.py`, `_env_manifest.py`, `env-manifest.json`, runtime inventory, renderers, Terraform/Helm/Kubernetes projections | Add a setting or secret only if the isolated adapter genuinely needs it, then keep every generated/runtime/admission projection in parity. |
| Build material and verification | `shifter/packer/{*.pkr.hcl,gcp/,scripts/,tests/}`, especially existing cleanup, encrypted-AMI verification and GCP build-evidence scripts | Reuse compatible recipe/verification components inside qualified adapters. Audit mutable downloads, inputs and credential residue before reuse; existing maintainer bake recipes are not automatically qualified tenant profiles. Do not invoke their CI publication/promotion workflow. |

## Independent Admission And Durable Completion

- `engine.services._raes_image` validates field completeness and digest syntax;
  it accepts supplied integrity/provenance references and updates a mutable
  alias-keyed row. It is not an independent image verifier. Prepared availability
  needs authoritative readback of the immutable provider resource, owning
  account/project and location, readiness and profile-specific properties.
  AMI ids/GCE URLs, image families, build exit codes and labels do not prove the
  portable content digest. The profile must define that identity/evidence
  relationship. Verify required encryption/KMS usability, bootability and image
  properties, and remove build credentials and machine/participant identities
  before capture; preserve only deliberately authored fixed scenario content.
- The builder reports a candidate, never `admitted=true`. Verification runs
  outside the builder's authority and uses a pinned verifier contract; private
  installer permission does not make worker-supplied evidence authoritative.
  An adapter manifest's verifier-image digest is a requested implementation,
  not its own trust anchor: deployment policy must independently qualify that
  verifier/profile pair. A different Job running installer-selected code under
  the same unrestricted authority is not independent verification. Bind readback
  to the provider's immutable resource identity, not a recreatable name/family,
  and prevent builder mutation of the admitted output after verification.
  The service rechecks operation/attempt, ownership, authorization policy and
  cancellation fences when committing admission. Provider readback happens
  outside database transactions, followed by a short locked commit against the
  same immutable identity. An unavailable provider or unverifiable result stays
  failed/indeterminate; it never becomes success by timeout.
- Reuse `artifact_inventory` / `artifact_resolution` as the sole availability
  and selection seam. Current availability deliberately leaves constraint and
  locked-input facts empty without a verifier. Extend that projection with
  verified, requirement-bound facts, not claims inferred from candidate
  presence. Preserve the materialization profile/spec/input provenance through
  admission and the upstream satisfaction disclosure. Resolve existing admitted
  availability before dispatch and again under the concurrency fence: route
  declaration order must not accidentally choose a build ahead of reusable
  supply. Do not overwrite an unrelated alias or treat `(provider, alias)` as
  an immutable prepared-artifact key. Evolve the existing inventory boundary.
- The existing `shared.operation_envelope` is expressly
  `shifter.provisioner-operation`, with closed range/NGFW discriminators; the
  result applier resolves `Range`/`Instance`. Reuse its canonical digest,
  bounded validation and native `shared.exceptions.ValidationError`, and the
  launch outbox's transactional claim / lease / retry / create-or-observe
  conventions. Do not route preparation through those range-specific records
  or copy their controller loops into a second workflow framework. The owning
  service gets distinct preparation state and a bounded worker input/result
  contract. A guessed opaque id is not read/write authority: enforce an
  authenticated operation/attempt grant on input, result and cleanup access;
  never give private worker code the provisioner's table-wide SQL credentials
  or permission to update inventory/audit/adapter registration.
- Persist attempt and provider resource ownership before ambiguous effects can
  be forgotten. At-least-once dispatch and provider timeout need deterministic
  create-or-observe behavior, conflicting-result detection, bounded retries,
  heartbeat/reconciliation and separately retryable cleanup. Cloud cleanup must
  cover disks, snapshots, guests, networks, temporary grants and staged data
  after process loss as well as cancellation; Job TTL/Secret owner references
  alone only clean Kubernetes resources. Never delete a foreign resource or an
  admitted artifact referenced by a launch. Database constraints and atomic
  state/inventory/audit commits, not Redis or logs, are workflow truth.

## Cross-Cutting Security And Runtime Checks

- **Authorization and input shapes:** CMS permission classes, authoring actor
  validation, workspace/backend/range admission, package validation, public
  upstream materialization validation, backend capability validation, inventory
  write validation, and the existing closed operation-envelope/binding parsers
  each validate their own projection. Ordinary preparation input identifies
  registered objects; the server binds the cloud target and immutable input.
  Adapter administration is a separate validated manifest/grant surface. Reuse
  DRF session/token authentication, `active_actor_user`, token scope validation,
  CSRF/same-origin session rules and the shared frontend API client. No
  `csrf_exempt` path, scope wildcard or second browser credential store.
  `require_scope` checks only the token dimension; compose live actor/object
  policy and recheck in the service. Scope names belong in
  `shared.api_tokens.scopes`, with `shared.api.schema` / generated-client parity;
  copying the CMS authoring scope does not authorize adapter installation.
- **Secrets and OS exposure:** `shared.cloud.sensitive_env` keeps only actual
  secret values in short-lived Secret-backed entries. Workload identity supplies
  cloud access. Fixed argv arrays and the closed Job admission grammar prevent
  shell/code injection; private bounded staging and explicit cleanup prevent
  artifact or credential residue. The worker requires no public IP and only the
  backend/object endpoints its materialization contract needs. Registry pull
  authentication belongs to kubelet/provider pull wiring (or bounded
  `imagePullSecrets`), not recipe environment. `sensitive_env` is a name-based
  classifier, not a detector of secret URLs: `_URL`/`_REF` suffixes are explicitly
  treated as plain. Never hide a signed URL or token in such a field. Check child
  processes, `/proc`-visible argv/environment, shell tracing, Packer logs,
  termination messages, crash output, temporary files and captured images too.
  Explicit private staging, bounded disk/memory/CPU/runtime/concurrency budgets,
  and cleanup are part of the worker contract. No host Docker socket, hostPath,
  privileged pod or provisioner node-pool/management-network inheritance.
- **Network and cloud authority:** preserve restricted Pod Security, dedicated
  workload identity and deny-by-default RBAC/IAM. Build guests and independent
  verifiers have separate minimal authority. Bind `PassRole`/service-account
  impersonation and object/secret/KMS permissions to the selected deployment's
  exact resources; apply the existing IAM scope checkers. Private registry and
  input endpoints require controlled egress, TLS/credential audience and
  redirect handling; manifest references must not become arbitrary URL fetches
  to metadata, internal services or another tenant. Kubernetes network policy
  does not secure a separately launched cloud VM: verify its firewall/egress
  and metadata identity too. Build egress is not permission to weaken the
  range's `installation.range_egress` policy.
- **Configuration shapes:** `installation.schema.RootConfig` checks the root
  shape and rejects obvious secret payloads; it cannot establish that every
  single-line value is a reference. `installation/settings_aws.py` /
  `settings_gcp.py` and the selected backend bundle validate backend settings
  and reference semantics. `config` remains the composition
  root. Bootstrap policy and runtime worker configuration pass those validators,
  `_runtime_env`, generated `_env_manifest` / `env-manifest.json`, installation
  `render.py` / `runtime_inventory*`, `scripts/gcp/render_runtime_env.py`, Helm
  `values.schema.json`, ConfigMap/Secret projections, Terraform validators, and
  the dedicated admission policy together. Post-setup adapter registrations
  are tenant operational data, not per-adapter env variables or Terraform
  source edits. Unknown security profiles fail closed without broadening the
  provisioner's literal/Secret env or command allowlists.
  Validate persisted grant configuration through one closed, versioned parser
  before use: a JSONField, digest or `active` flag does not validate identity,
  permissions, pull-secret ownership, budgets or endpoints. Revalidate the
  normalized projection at dispatch/admission. Helper-read environment settings
  need explicit `EnvBinding(name, default, source_file)` entries in
  `config/_env_manifest.py`; its AST walker sees only literal reads. Regenerate
  `env-manifest.json` through the existing command, not hand-maintained copies.
- **Persistence and error envelopes:** persist bounded, immutable, non-secret
  request/result/provenance references with a schema version and generation or
  lease fence. Expected non-realizability stays an upstream typed result; API
  failures use `shared.api.errors` with request id. Reuse existing domain
  exceptions (`CMSError`, Engine errors, `shared.cloud.exceptions`) at their
  owning boundaries; no parallel hierarchy or invented portable diagnostic
  codes. `api_error_response` sanitizes formatting, and its details projection
  does not redact arbitrary strings/dictionary keys. Supply authored safe
  messages and allowlisted details; never reflect raw upstream, worker, cloud,
  storage, SQL, parser, Job stopped-reason or subprocess text.
- **Observability:** log request/preparation/operation correlation ids, selected
  backend, mechanism-profile id, outcome code, attempt count, and duration.
  Use `safe_log_value` or fingerprints as appropriate; never log the spec,
  artifact/provider reference, evidence, command, environment, secret, or
  transcript. Audit the authorized state transition, not a copy of worker data.
  `safe_log_value` escapes/truncates but does not remove secrets; do not forward
  `str(exc)` or provider response bodies through it. Keep failure evidence in
  access-controlled storage with bounded retention. Use existing audit
  vocabulary/strict policy and request correlation, worker health/heartbeat and
  low-cardinality outcome/duration metrics; keep private profile names and
  unique operation ids out of metric labels.
  `shared.audit.vocabulary` owns action/entity values and `shared.audit.events`
  owns event/request shapes. `strict=True` enforces persistence failure behavior,
  not enum or payload validation; the dataclass and ORM choices are not a closed
  input parser. Use the canonical vocabulary (extend it centrally only where
  necessary), valid entity attribution and `RequestAudit` / actor attribution;
  do not emit unregistered preparation strings or lose token/request identity.

## Repository-Wide Verification Surface

Alongside the incumbents above, implementation must preserve `.importlinter`,
`scripts/check_layer_imports/layer_imports.yaml`, ADR-031/032/043, and the
standalone `raes_plan`, operation-input and artifact-binding consumers. Check
the pinned public accessor/conformance tests when upstream versions change;
do not relax authored OS/VM/access requirements or READY's realization gate to
make a preparation specimen launch.

Extend the established tests for `tests/cms/{test_pack_validation,
test_register_pack_command,test_raes_image_registry_api}.py`,
`tests/shared/raes/{test_object_source,test_artifact_inventory,
test_artifact_resolution,test_artifact_binding}.py`, launch outbox/result
application and `tests/shared/cloud/` Job reconciliation/Secret cleanup.
`tests/platform/test_gcp_job_launcher_manifests.py`, cloud runtime-role parity,
Helm rendering, runtime inventory, env-manifest, Packer and IAM checker tests
cover boundaries unit service tests cannot prove.

Required evidence includes an already-running tenant receiving a private pack
and adapter, trusted conformance, preparation, independent readback and normal
launch; no-worker reuse; session/token and CLI/service denials; malformed locks,
mutable references, foreign resources and private-data leakage; install/disable/
upgrade/retire/cancel races; duplicate dispatch/result conflicts; registry,
provider, database and audit outages; and orphan cleanup after worker loss.
Exercise effective denied IAM/network paths, not just matching labels or mocked
success. A GCE specimen does not certify AMI support, and design/unit evidence
does not certify native cloud effects.

Run `python3 scripts/adr_guard/adr_guard.py --all --level ci`; for touched
subsystems also run platform Ruff/import-linter, Packer checks, actionlint,
Terraform/TFLint/IAM checks, kube-linter/kubeconform and Helm policy parity as
required by `AGENTS.md` / `.gc/plan-rules.md`. Capability delivery also needs
user/technical documentation coverage under ADR-022. This docs-only preflight
requires no cloud mutation or tenant execution.

## Extensibility And Non-Goals

The extension seam is a tenant-registered, immutable adapter manifest keyed by
full upstream profile identity, backend and worker protocol version, with
parameterized granted authority, pull authentication, resource/egress budgets
and independent verification. Its input is the validated upstream specification
plus server-selected tenant/backend policy; its output is a candidate for
independent admission into existing inventory. Built-in and private adapters use
this same seam. Scenario-specific code stays in profile build material. A future
scenario or private registry must not require conditionals in CMS, RAES SDL
handling, the range provisioner or a rewritten canonical deployment manifest.

Out of scope: defining RAES materialization semantics; building every missing
image; exact-artifact substitution; dynamic composition; catalog/discovery,
publication, promotion, replication, distribution, entitlement, or artifact
download services; maintainer CI image pipelines (#1469/#1470/#1471); and any
long-running build, live probe, pull, or cloud mutation on catalog or range
provisioning paths.
