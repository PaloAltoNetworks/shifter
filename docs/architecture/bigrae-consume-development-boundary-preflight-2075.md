# BigRAE Consume And Development Boundary Preflight

Issue: GitHub #2075, "Supersede ADR-033 distribution-plane model; align
Shifter/BigRAE ADRs to OpenRAE ownership (hub#3)."

Status: pre-implementation architecture guidance. This note does not make the
ADR or binding-document changes owned by #2075. The issue is the authoritative
contract for this requirement-free run.

## Boundary Decision

OpenRAE/hub#3 assigns Shifter's future identity, BigRAE, the organizational and
SaaS backend role. BigRAE consumes RAES environment packs and owns tenant-facing
control-plane behavior: tenancy, authentication, policy, secrets, scheduling,
audit, operations, and range realization. It also has a development surface for
its own CI, build, test, deploy tooling, and isolated runner fleet.

BigRAE does not have a distribution plane. RAES owns semantics, contracts, and
conformance; Catalog owns pack and reusable-asset discovery; env-packs owns the
packs; and Hub owns journey definition and cross-repository sequencing.
Consuming an upstream-published pack, recording its immutable identity, checking
whether a backend can realize it, or staging its content for one tenant does not
transfer publication, promotion, replication, channel, or catalog ownership to
BigRAE.

The repository still uses `Shifter` in code, settings, infrastructure names,
and historical records. Current architecture prose should define
"BigRAE (currently named Shifter in this repository)" once, then use BigRAE for
the target product boundary and Shifter only for concrete current identifiers.
This issue is not the product or repository rename.

## ADR Guardrails

- ADR-053 is the active two-surface decision: tenant/product plus development.
  It must contain no third distribution surface and no suggestion that BigRAE
  curates, blesses, publishes, promotes, or replicates environment packs or a
  catalog.
- ADR-033 remains historical evidence, with `status` set to `superseded` and an
  explicit `superseded_by` value of `ADR-053`. Do not delete or rewrite its old
  decision into something it never decided.
- Carry the full ADR-033-R2 runner-isolation rule into ADR-053, including the
  #1546 dev-tenant amendment: runner state is separate from platform state,
  platform teardown cannot remove the deploy mechanism, and one dev tenant
  cannot borrow another tenant's fleet. Active references to that rule should
  point to ADR-053.
- Rewrite `product-development-surfaces.md` in place as ADR-053's binding note.
  Keeping the existing path avoids a second surface document and unnecessary
  inbound-link churn. The note should state the OpenRAE ownership split directly
  and retain only the tenant/product and development concerns.
- Keep ADR-034's uniform, source-agnostic, entitlement-blind registration
  contract and the exact, constrained, open, and absent satisfiability rules.
  Replace `in-box`, `shipped catalog`, `private-distribution`, and
  `pack-published` ownership language with origin-neutral input language or an
  explicit upstream owner. Environment Packs "publication profile" remains a
  valid upstream contract term; it is not a BigRAE distribution plane.
- A checked-in bootstrap manifest is a deployment/development seed consumed by
  `register_pack`, not a BigRAE catalog or release channel. Its existence proves
  the uniform ingestion path only. It must not be cited as evidence that BigRAE
  owns pack publication or distribution.
- Preserve ADR-037 and ADR-042 unchanged. Publishing BigRAE's own software,
  provenance attestations, backend capability manifests, or cloud runtime state
  is distinct from distributing RAES environment packs.

## Canonical Incumbents To Reuse

This is a documentation-only correction. It must describe the existing runtime
boundaries rather than introduce replacements for them.

| Concern | Canonical incumbent | Boundary to preserve |
| --- | --- | --- |
| Upstream pack semantics and conformance | Exact `raes` / `raes-env-packs` pins in `shifter/shifter_platform/pyproject.toml` and `uv.lock`; `cms.scenarios.pack_validation` | Consume public upstream models, validators, diagnostics, and canonical digest rules. Do not vendor or restate an environment-pack schema. |
| Registration service | `cms.services.register_pack` and `PackRegistrationRequest` | API, CLI, and bootstrap callers share one authorization, validation, transaction, duplicate, audit, and retry policy. Do not create a distribution-specific registration workflow. |
| Authentication and authorization | `CMS_WRITE_PERMISSIONS`, exact `cms:authoring:write`, and `shared.auth.validate_cms_authoring_user` | Authorization answers who may register content in a tenant. It is not acquisition entitlement, source trust, conformance, or launchability. |
| Transport and domain validation | `PackRegistrationSerializer`; `shared.schemas.raes_package_source.validate_package_source`; `RaesPackageSource.save()` | The serializer bounds HTTP shape. The shared validator owns source/contract/status allowlists, digest and reference shapes, and bounded provenance for every caller. |
| Pack trust and containment | `cms.scenarios.pack_validation`, `shared.raes.package_loader`, and `shared.raes.object_source` | Keep upstream validation, repository-root containment, safe archive extraction, immutable object identity, and digest verification separate from entitlement and distribution. |
| Catalog persistence and projection | `RaesPackageSource`, `ScenarioMetadata`, and `cms.scenarios.registry` | Keep the source row provenance-only, metadata as the sole access overlay, and the registry as the launchability authority. Registration is not conformance or launchability. |
| Satisfiability and realization | `shared.raes.artifact_resolution`, `shared.raes.realizability`, `shared.raes.manifest`, and the checked backend manifest | Preserve upstream exact/constrained/open/absent semantics and backend-declared capability checks. Do not add a BigRAE publication model or second resolver. |
| Durable realization transport | `shared.raes.artifact_binding`, operation-input envelopes, and ADR-043 | Carry only a bounded, generation-fenced, byte-free selected binding. The provisioner must not regain catalog or selection authority. |
| Errors and public responses | `cms.exceptions.CMSError`, `shared.errors`, and `shared.api.errors` | Reuse the bounded platform error envelope and stable domain results. Do not expose parser, storage, provider, path, or entitlement details. |
| Audit and logs | `shared.audit`, `RequestIDMiddleware`, `shared.log_sanitize`, and provisioner `log_redact` | Retain strict mutation audit, server-owned request correlation, and bounded sanitized logs. Provenance references are not raw audit or log payloads. |
| Configuration and storage | `config/_raes_settings.py`, `config/env-manifest.json`, `shared.cloud.types.ObjectStorage`, and deployment renderers | Preserve the existing package-root, object-store, prefix, and resource-bound settings. A source credential must not enter the registration DTO or manifest. |
| Development runner isolation | ADR-033-R2, the dedicated GCP runner Terraform root, `scripts/bootstrap`, and runner routing guards | Carry the rule into ADR-053 without redesigning runner lifecycle, credentials, networking, state, or workflow routing. |

## Cross-Cutting Layers

The #2075 change itself crosses only repository documentation and policy
validation. It adds no executable input, request path, secret, environment
binding, process, persistence write, or error response. Consequently it must not
change authentication, authorization, CSRF, secret handling, runtime config,
OS-level exposure, database schemas, logging, audit, or API error behavior.

The architecture described by the corrected prose continues to pass these
existing layers:

- **Authentication and authorization:** session or token admission,
  `CMS_WRITE_PERMISSIONS`, exact token scope, and service-level authoring
  validation all remain in force. Pack origin or upstream catalog membership
  never grants tenant authority.
- **Shape and trust validation:** the DRF serializer bounds transport shape;
  `validate_package_source()` owns the shared record rules; upstream pack
  validation and canonical digest verification admit foreign input; the
  registry revalidates persisted rows before launchability; realization uses
  the backend manifest and the existing artifact-resolution seam.
- **Secrets and environment:** pack bodies, source credentials, tokens, signed
  URLs, and provider responses remain outside DTOs, provenance, audit, errors,
  logs, and environment manifests. Existing non-secret package settings remain
  the only configuration shapes in this issue.
- **OS and process exposure:** #2075 creates no process invocation. Existing
  realization rules keep plans, artifacts, credentials, provider references,
  and environment maps out of argv and child environments; no pack-supplied
  code or shell command is executed during registration.
- **Persistence and errors:** `RaesPackageSource` remains reference-only and
  `ScenarioMetadata` remains the access overlay. Expected non-realizability is
  a typed domain result; failures continue through `CMSError` and the shared API
  envelope without raw exception leakage.
- **Repository policy:** `docs/adr/index.yaml` remains JSON-syntax YAML and each
  ADR keeps the registry's required keys and globally unique IDs. The canonical
  gate is `make policy`, which runs ADR conformance, import boundaries,
  whitespace checks, and Vale over changed Markdown. Public `docs/ops` changes
  also remain subject to the strict MkDocs build; internal `docs/architecture`
  notes are intentionally excluded from the public site.

No new ADR-registry status framework or guard script is warranted here. The
explicit `superseded_by` field required by #2075 is sufficient; generalized ADR
lifecycle validation belongs in separately scoped governance work.

## Extensibility Seams

The content seam remains explicit `source_kind`, `contract_kind`,
`contract_profile`, and immutable package/lock identity, with central allowlists
and resolver adapters. A future upstream source, catalog integration, pack
profile, or backend mechanism contributes normalized input facts or one adapter
at those seams. It must not create source-specific API endpoints, tables,
permissions, exception families, or a BigRAE distribution plane.

The naming seam is the single BigRAE/Shifter transition statement above.
Current symbols and deployment identifiers can be renamed in a coordinated
follow-up without re-editing the ownership model or changing its meaning.

## Gotchas And Anti-Patterns

- Do not globally replace `publish`, `distribution`, or `promotion`. Python
  distributions, the upstream Environment Packs publication profile, BigRAE's
  own software releases, backend-manifest publication, and cloud-state
  publication are legitimate uses. Remove only current claims that BigRAE owns
  environment-pack or catalog distribution.
- Do not replace the distribution plane with a renamed `delivery`, `supply`,
  `channel`, `marketplace`, `blessed packs`, or `in-box catalog` plane.
- Do not turn Catalog discovery or Hub journey sequencing into BigRAE database,
  API, scheduler, or workflow concepts. BigRAE consumes their outputs through
  existing pack identity and registration seams.
- Do not rewrite `CHANGELOG.md` history. Historical release text may describe
  what an old change claimed; active ADRs and current guides define the present
  boundary.
- The current bootstrap README says the manifest is empty, while
  `manifest.yaml` declares an in-box seed pack. Correct current guidance without
  deleting the pack, renaming runtime symbols, or treating the manifest as a release
  catalog in this issue.
- Do not duplicate RAES schemas, satisfiability rules, package validation,
  `RaesPackageSource`, launchability logic, exception hierarchies, error
  envelopes, audit events, log sanitizers, config manifests, or runner workflow
  logic merely to express the new ownership wording.
- Do not weaken exact/constrained/open/absent semantics, make absence an image
  request, equate registration with trust, or equate upstream availability with
  authorization to launch.

## Non-Goals And Scope Limits

- No runtime behavior, API, OpenAPI, DTO, model, migration, dependency, pack
  content, manifest entry, Terraform, workflow, runner, or deployment change.
- No Shifter-to-BigRAE code, setting, resource-tag, repository, package, or URL
  rename.
- No relocation or deletion of the checked-in in-box seed pack; cross-repository
  movement belongs to Hub/env-packs sequencing.
- No marketplace, catalog client, pack downloader, entitlement system,
  subscription model, credential broker, signing service, artifact store, or
  new preparation workflow.
- No change to BigRAE's own software release and provenance responsibilities
  under ADR-037 and ADR-042.
- No redesign of uniform ingestion, satisfiability, realizability, runner
  isolation, or range realization. This issue corrects ownership language while
  preserving those contracts.
