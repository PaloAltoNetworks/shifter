# ACES Source-Backed Content Delivery Preflight

Issue: GitHub #1564, "deliver source-backed ACES content."

Status: pre-implementation architecture guidance. This note does not implement
content preparation, persistence, object transfer, guest realization, manifest
claims, tests, or live evidence.

## Boundary And Decisions

#1564 is full delivery, not the rejected fail-closed formalization. A source-
backed `file`, `dataset` (`source` and/or `items`), or source-backed `directory`
must have a verified guest effect on Linux and Windows before the range becomes
ready. Creating a directory, copying a source descriptor, or preserving fields
in a projection is not delivery (ADR-032-R6).

The secure flow is one existing pipeline with a narrow identity adjunct:

1. CMS resolves the registered pack through the current repo/object resolver,
   validates containment and the upstream pack contract, and verifies the
   canonical associated-artifact digest.
2. While that immutable verified root is live, the shared ACES boundary binds
   each compiled content resource address to explicit pack-contained source
   input and a supported deterministic materializer. It prepares a bounded
   payload, hashes it, and promotes it through `shared.cloud.ObjectStorage` to a
   normalized content-addressed key in the existing platform assets bucket.
3. The dispatch call carries the serialized plan plus a versioned tuple of
   server-owned delivery bindings. A binding contains only content resource
   address, `sha256` digest, normalized storage key, and byte count. It contains
   no bytes, URL, bucket, credential, guest path, command, or generated config.
4. Engine persists the bindings in a dedicated private relation in the same
   transaction as the range, separately from `range_config` and
   `ProvisionerLaunchIntent.payload`. The provisioner is still launched with
   only `aces-range provision --request-id <uuid>`.
5. The provisioner reads plan and bindings by request id, validates both at its
   separate trust boundary, requires an exact one-to-one join for every content
   shape that needs delivery, retrieves the immutable object through its
   provider-neutral storage adapter and workload identity, and verifies the
   digest before guest mutation.
6. The existing authenticated guest-execution path streams raw bytes through
   standard input to a server-named private staging file. OS-specific content
   realization installs atomically and a readback/digest hook proves the guest
   effect. Failure follows the existing apply cleanup and failed-range path; it
   must occur before `READY`.

The object key is server-derived from the digest under one configured prefix.
The configured `STORAGE_BUCKET_NAME`, not a bucket carried in the binding, is
the storage authority. Content-addressed writes are idempotent and safe to
reuse. A failed DB transaction may leave an unreferenced immutable object for
the existing bucket lifecycle/retention policy to reap; range destroy must not
delete a digest object that another range may reference.

The no-payload rule concerns source-backed delivery payloads. Existing genuine
inline `Content.text` remains authored ACES intent in the compiled plan; #1564
must neither migrate it into the adjunct nor use it as permission to put source
payload bytes in the plan or instance metadata.

## Contract Gaps That Must Fail Closed

The pinned ACES model does not make `source.name` a pack-relative path, and the
scenario-pack contract says consumers decompose `assets/`; it does not define a
source-to-file mapping. Polaris also demonstrates that current source packages
are heterogeneous generator inputs (PDF, mail, database, SMB tree, archives),
not uniformly the bytes to copy. `dataset` may contain only item metadata and
has no destination, while `format` is an open string. These are load-bearing
contract facts, not implementation details.

Therefore implementation must consume a released upstream content-source
mapping/materialization contract if one is available. Otherwise the Shifter pack
profile needs one narrow static delivery projection, validated with the pack
and covered by its associated-artifact inventory. Resolution is keyed by the
full `(source.name, source.version, content type, format)` identity and the
compiled content address; omitted versions or formats may resolve only when the
profile has exactly one unambiguous match. It must never select `package.yaml`,
an asset, or a generator by filename convention, extension, directory order,
scenario id, or Polaris-specific name.

Format materialization is an explicit allowlisted seam. Raw file and directory
payloads, generated documents, and service-backed datasets may need different
deterministic materializers and different guest readback probes. Package build
scripts are reference tooling, not trusted runtime plugins: do not execute pack
code, shell commands, containers, Terraform, or arbitrary generators in CMS.
If no supported deterministic materializer and proof probe exists for an
authored shape -- especially items-only datasets -- the pack is non-realizable.
Do not widen `supported_content_types` until every admitted shape has Linux and
Windows conformance evidence; the coarse manifest cannot hide a format gap.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Pack catalog/auth | `cms.services.register_pack`, `AcesPackageSource`, `PackageSourceRecord`, `validate_cms_authoring_user` | Keep one source-agnostic registration/auth/audit workflow; do not add a content-delivery endpoint or catalog. |
| Pack trust | `cms.scenarios.pack_validation`, `shared.aces.package_loader`, `shared.aces.object_source` | Reuse upstream validation, exact associated-artifact digest, repo containment, bounded object download, and safe archive extraction before materialization. |
| ACES producer/admission | `shared.aces.runtime_target`, `composition_envelope`, `manifest`, `launch_aces_package` | Extract public ACES content once inside `shared.aces`; do not restate SDL or plan payload schemas in CMS/Engine. |
| Dispatch/lifecycle | `shared.aces.dispatch_port`, `cms.aces.dispatch.CmsAcesDispatchPort`, `engine.services.create_aces_range` | Extend the existing flag-gated dispatch call with the validated identity adjunct and preserve request-id idempotency, ownership admission, transaction, receipt, status, and cleanup. |
| Persistence/read | `engine.models.Range`, Engine migrations/grants, `provisioner_db_aces.get_aces_range_data_by_request_id` | Keep the plan in `range_config`; store private immutable bindings separately and read them in the same request-owned lookup. Grant provisioner `SELECT` only. |
| Object storage | `shared.cloud.ObjectStorage` and adapters; provisioner `cloud.ObjectStorage` and adapters; `STORAGE_BUCKET_NAME` | Reuse the provider registry, identity preconditions, workload identity, and existing assets bucket. Extend the provisioner protocol with bounded head/download; never mint a presigned URL. |
| Guest execution | `executors.factory.build_guest_execution_context`, `GuestSSHExecutor`, `SetupOrchestrator`, `SetupStep` | Extend the authenticated, strict-host-key transport with a binary-stdin operation; reuse readiness, retry, timeout, and verification orchestration. Do not add another SSH/WinRM/SSM client. |
| Errors/logging | `AcesPackageError`, `CMSError`, `shared.errors`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact`, `SetupError` | Translate to stable bounded classes/codes. Log correlation and content address only; never bodies, keys, paths, executor output, URLs, or provider exceptions. |
| Capability/evidence | `shared.aces.manifest`, generated `backend-manifest.json`, `realization_ledger`, backend conformance and composition parity tests | Restore all three content types only after genuine cross-boundary Linux/Windows readback evidence. |

`AcesOperationRecord`, `Range.provisioned_instances`, range events/snapshots,
`Scenario.definition`, audit JSON, and launch-intent payloads are observation,
legacy intent, or delivery-control surfaces. None is a content-binding store.

## Cross-Cutting Security And Validation Layers

- **API and authorization:** existing CMS authoring permissions
  (`threat_research_required`, `CMS_WRITE_PERMISSIONS`, exact
  `cms:authoring:write`, `validate_cms_authoring_user`) remain authoritative.
  Launch reuses owner, active-range, launchability, backend-admission, and strict
  audit checks. No guest or participant API is added.
- **Registration/source shape:** `PackRegistrationSerializer` is transport
  validation; `PackageSourceRecord` and `validate_package_source()` remain the
  domain allowlist and digest/provenance authority. The private delivery
  binding is derived server-side and is never accepted from a request.
- **Pack and byte trust:** repo paths pass `resolve_pack_root`; object packs pass
  identity-pinned bounded download and safe extraction; both pass
  `validate_pack` and `verify_pack_digest`. Every selected input must be in the
  associated-artifact inventory, containment-checked without symlink races,
  size/count bounded, and independently hashed after materialization.
- **ACES admission:** SDL parsing/validation, backend manifest diagnostics,
  composition envelope, serialized-plan version/shape/topology checks, and the
  feature flag all run before dispatch. The provisioner repeats its plain-data
  plan validation and validates binding version, digest syntax, byte bound,
  canonical key, uniqueness, no extras, and exact content-address join before
  storage or cloud mutation.
- **Persistence/config:** bytes and locators never enter `range_config`, API
  DTOs, `AcesOperationRecord`, snapshots, events, diagnostics, audit, or launch
  intents. Reuse `STORAGE_BUCKET_NAME`; if a prefix or size policy becomes
  configurable, add it once through typed config, `config/env-manifest.json`,
  runtime renderers, Kubernetes admission/env allowlists, Terraform variables,
  and parity tests. Never pass a per-delivery key, digest, URL, token, or bucket
  through env.
- **Cloud IAM:** platform/CMS may promote objects only under the delivery
  prefix; provisioner gets read-only access to that prefix. Reuse GCP Workload
  Identity and AWS task-role credentials. The guest receives no cloud identity,
  credential, URL, or object key.
- **Process/OS exposure:** the request-id-only CLI stays canonical. Payloads and
  identities do not enter argv, environment, startup scripts, GCE/AWS instance
  metadata, Terraform values, shell command text, PowerShell arguments, or
  template contexts. Local staging uses private files, bounded streaming,
  digest verification, and unconditional cleanup.
- **Guest path/archive safety:** validate absolute path dialect against the
  target OS; reject NULs, traversal, reserved/management paths, unsafe parents,
  reparse points/symlinks, and destination escapes. Directory archives reject
  absolute/traversal/link/device entries and enforce entry/expanded-byte caps.
  Install under a controlled staging root with no-follow checks and atomic
  replacement. `sensitive` content gets least-readable POSIX mode or Windows
  ACL; do not rely on quoting alone.
- **Guest proof:** file proof hashes exact installed bytes; directory proof uses
  a deterministic tree manifest/digest; a dataset materializer supplies a
  format-specific observable readback, not a marker file. Verification is
  idempotent and mandatory on retries. Coordinate this hook with #1569 so there
  is one readiness/failure decision.
- **Errors and observability:** storage, SSH, PowerShell, parser, extraction, and
  readback failures become a fixed content-delivery failure code/message before
  range event/API projection. Do not feed raw `str(exc)`, object keys, guest
  paths, stdout/stderr, or payload fragments into `status_reason`, logs, audit,
  events, or diagnostics. Metrics may count phase, OS, type, result, duration,
  and byte-size bucket; labels must not carry source names or locators.

## Extensibility Seam

The seam is a bounded materializer/probe selected by content type and declared
format, returning a deterministic payload plus its verification policy. Adding
one future format should add one allowlisted materializer/probe and conformance
fixture without changing dispatch, persistence, storage, guest authentication,
or lifecycle code. Provider variation stays behind the two existing object-
storage protocols; OS variation stays behind the existing guest execution
context. The binding version is the rolling-deploy seam: readers reject unknown
versions and tolerate only the explicitly supported set.

## Whole-Repository Scope

Implementation must evaluate these canonical surfaces, including their tests:

- ADR-024, ADR-031, ADR-032, ADR-034; this note; the #1563 realizability note;
  the #1578 ingestion note; `docs/architecture/aces-cutover-evidence-1264.md`;
- `cms/models/scenarios.py`, `cms/services/_content_ingestion.py`,
  `cms/services/_aces_range_create.py`, `cms/scenarios/{registry,pack_validation}.py`,
  `cms/aces/dispatch.py`, and CMS auth/audit/error adapters;
- `shared/aces/{package_loader,object_source,runtime_target,composition_envelope,dispatch_port,manifest,realization_ledger}.py`,
  `shared/cloud/**`, `shared/log_sanitize.py`, and shared errors/API envelopes;
- `engine/models.py`, `engine/services/_aces_range.py`, Engine migrations and
  explicit `provisioner_lambda` grants, `engine/ecs/_env.py`, launch intents,
  range events, snapshots, operation records, and cleanup/status paths;
- `shifter/engine/provisioner/{provisioner_db_aces,aces_plan,aces_composition,aces_gcp_composition,aces_gcp_apply,aces_range_ops,aces_snapshot}.py`,
  provisioner `cloud/**`, `executors/**`, and `orchestrators/**`;
- `config/_aces_settings.py`, `config/_cloud.py`, `config/env-manifest.json`, runtime env renderers,
  `platform/terraform/**`, `platform/k8s/**`, and Helm admission/env parity;
- shared ACES producer/consumer parity and conformance tests, CMS repo/object
  pack launch tests, Engine persistence/idempotency tests, provisioner parser,
  storage, executor, Linux/Windows realization/readback and no-leak tests, plus
  the live backend validation/cutover evidence surface.

## Gotchas And Anti-Patterns

- Do not put payloads in base64 startup scripts, instance metadata, plans,
  range config, JSON fields, event payloads, diagnostics, argv, or env.
- Do not pass a presigned URL to the guest or let the guest call object storage.
- Do not infer source bytes from `source.name`, `format`, extension, path,
  package directory order, or scenario identity; do not copy `package.yaml` as
  realization and do not execute pack build/generator code in the web process.
- Do not duplicate ACES content models, pack schemas, digest/containment logic,
  cloud factories, SSH clients, setup orchestration, lifecycle state, audit,
  errors, or manifest authorities.
- Do not treat dataset item names, a descriptor, marker, parent directory, or
  successful upload/SSH exit as proof of guest effect.
- Do not join a delivery object by mutable content name or target path. Join by
  compiled resource address and independently validate digest/key identity.
- Do not log normalized object keys merely because they contain no credential;
  the issue contract excludes object locators from observability surfaces.
- Do not overwrite a content-addressed object, delete shared objects on range
  destroy, leave partial guest files, follow destination links, or retry a
  non-idempotent dataset import without a format-specific policy.
- Do not restore manifest claims from parser/unit evidence alone. Require actual
  producer-to-provisioner-to-guest Linux and Windows readback, tamper/failure,
  sensitive-permission, and no-leak evidence with the flag on; flag-off behavior
  remains byte-for-byte legacy.

## Non-Goals

- No standalone artifact store, acquisition/entitlement system, marketplace,
  public content API, guest cloud credential, or participant download service.
- No replacement of the ACES plan, SDL, pack contract, CMS catalog, Engine
  lifecycle/events, object-storage boundary, or guest executor hierarchy.
- No general remote-execution redesign, arbitrary runtime plugin system, image
  bake redesign, or migration of genuine inline text content.
- No ACES-native cutover and no change to
  `SHIFTER_ACES_NATIVE_PROVISIONING` default-off behavior.
- No declaration of `file`, `dataset`, or `directory` support until the full
  shape/OS matrix and in-guest evidence exists.

The documentation gate is:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
