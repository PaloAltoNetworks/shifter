# Scenario Expressiveness Gap Tracking Preflight

Issue: GitHub #676, "PLAT-007: Scenario Expressiveness Gap Tracking."

Status: pre-implementation architecture guidance. This note does not implement
an ACES capability, change production behavior, modify requirement or issue
state, or authorize ACES cutover.

## Decision

PLAT-007 is a governance and traceability constraint, not a new runtime
feature. ADR-024, the ACES migration parity inventory, and the existing ACES
issue-triage convention are the canonical control surfaces. Do not create a
runtime gap registry, database model, API, feature flag, exception hierarchy,
or second backlog schema.

Before a scenario capability outside the current CyberScript vocabulary is
relied on for an event or production range, the repository-visible record must:

- classify the missing capability using an existing ADR-024 inventory category;
- distinguish ACES-owned authored meaning from Shifter-owned realization,
  product policy, security, and validation;
- cite the ACES SDL/profile issue when upstream vocabulary or conformance is
  missing, and retain the Shifter inventory row as the cutover audit record
  when the gap affects Shifter parity;
- name evidence that will prove the gap closed through the normal Shifter path;
- keep any temporary current-stack workaround explicitly non-canonical and
  removable.

The existing `docs/architecture/aces-migration-parity-inventory.yaml` row shape
is sufficient. A new gap gets a stable row only when no existing row accurately
covers it; otherwise update the existing row and its linked issue evidence.
Broad concern must not produce duplicate rows, and an issue label, milestone,
or prose-only TODO is not sufficient production-reliance evidence.

ADR-031 and ADR-032 control the current ACES runtime boundary. ACES source is
compiled by the pinned upstream tooling inside `shared.aces`; the serialized
ACES `ProvisioningPlan` is carried through the ACES-native CMS/engine path and
validated again by the separate provisioner. It must not be translated into a
CyberScript `RangeSpec` or a Shifter-owned intermediate scenario contract.

## Classification Guardrails

The Polaris examples must be separated before ownership is assigned:

- **Multiple containers on one host:** distinguish authored workload or
  composition meaning from a backend image/bake optimization and from multiple
  infrastructure nodes. Missing authored composition vocabulary is an ACES
  SDL/profile gap. Image selection and container realization remain backend
  concerns, but must be keyed by authored/compiled identity and must not sniff a
  Polaris scenario id.
- **Per-flag network gating:** do not conflate CTF answer validation or
  challenge release with network ACL realization. Shifter CTF services retain
  scoring, flag, release, abuse-control, and participant authorization
  authority. If authored state transitions need network effects, the transition
  meaning belongs in an ACES profile; the backend may realize only validated,
  compiled network intent. Flag values must never enter plans, firewall names,
  diagnostics, logs, or provider state.
- **Per-range agentic-tool configuration:** separate non-secret authored run or
  participant-runtime parameters from provider credentials, model tokens,
  prompts, commands, and operator policy. Missing portable semantics belong in
  an ACES experiment/participant-runtime profile. Shifter-owned credentials and
  provider configuration stay behind existing config and secret-delivery
  boundaries and must not become SDL, catalog provenance, sidecar payload,
  process argv, or logs.

These are different concepts and may require different inventory rows. A single
generic "scenario options" object would erase ownership and validation
boundaries.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required boundary |
| --- | --- | --- |
| Migration policy | ADR-024 in `docs/adr/index.yaml` and `docs/architecture/aces-migration-adr.md` | Current CyberScript/CMS behavior remains authoritative until parity and cutover gates pass. |
| Gap ledger | `docs/architecture/aces-migration-parity-inventory.yaml` | Reuse its stable row ids, closed categories, owner/evidence fields, and next-issue convention; it is an audit ledger, not runtime input. |
| Issue disposition | `docs/architecture/aces-cyberscript-issue-triage.md` | Use maintain/migrate/supersede/close; do not silently convert a CyberScript request into private backend behavior. |
| Ledger validation | `scripts/adr_guard/adr_guard.py` check `aces-parity-inventory-path-integrity` and `docs/adr/exceptions.yaml` | Reuse the existing safe YAML/path check and dated exception mechanism; do not add another parser or waiver list. |
| ACES contract ownership | Pinned `aces-sdl` packages, confined by `.importlinter` to `shared.aces` | Upstream models, parser, planner, manifest, profiles, and conformance are authoritative for authored ACES meaning. |
| Package/catalog admission | `shared.schemas.aces_package_source`, `cms.models.AcesPackageSource`, `cms.scenarios.registry`, `shared.aces.package_loader` | Keep provenance reference-only, verify refs/digests and pack containment, require supported contract/profile and passed conformance, prevent legacy-id shadowing, and fail closed on unsupported sources. |
| ACES plan admission | `shared.aces.runtime_target`, `shared.aces.manifest`, `shared.aces.domain_topology`, `shared.aces.composition_envelope`, `shared.aces.network_family` | Reuse the capability ledger and common validate/apply path; unsupported terms block dispatch with bounded diagnostics. |
| Product launch | `cms.services.create_range_dispatch`, `create_aces_native_range`, and current `create_range` | Keep the ACES path feature-gated and parallel; reuse caller, active-range, backend-admission, audit, status, and failure handling without modifying legacy hydration. |
| Engine/provisioner boundary | `engine.services.create_aces_range`, `shared.aces.dispatch_port`, `shifter/engine/provisioner/aces_plan.py` | Persist the serialized compiled plan, keep dispatch idempotent by request id, and repeat version, shape, identity, topology, reference, and capability checks before mutation. |
| Product authority | `ctf.services.*`, `cms.services`, `engine.services`, Mission Control read/access services | Keep scoring, flags, users, range lifecycle, status, access, audit, and operator behavior in their owning services. |
| Persistence | `engine.models.Range.range_config`, `shared.models.AcesOperationRecord`, participant-runtime sidecars, and ACES content-delivery bindings | Reuse the existing artifact appropriate to the concern; do not hide new semantics in JSON, audit rows, events, or a convenient sidecar. |
| Errors and diagnostics | `cms.exceptions.CMSError`, `shared.api.errors`, `shared.errors`, ACES typed diagnostics, and provisioner `AcesPlanError` | Translate at boundaries and return curated messages; do not expose raw parser, provider, guest, storage, or secret-bearing errors. |
| Logging and audit | `shared.log_sanitize`, provisioner `log_redact`, and the existing audit service | Log bounded ids, codes, profiles, counts, and status only; never payloads, flags, prompts, commands, tokens, or provider dumps. |
| Config and secrets | `config/_aces_settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, provider secret adapters, and sensitive-env helpers | Add operator knobs only through canonical settings/inventory/rendering; carry secret references through secret channels, never authored semantics or argv. |
| Layer enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, and ADR guard | Only `shared.aces` imports ACES tooling; cross-app access remains through approved service facades. |

## Cross-Cutting Layers

The PLAT-007 tracking change itself is repository documentation and
traceability. It must not add an authentication surface, runtime configuration,
secret binding, process invocation, persistence schema, public error envelope,
or runtime logger. The applicable input boundary is the parity inventory's
`yaml.safe_load`-based ADR guard. Inventory text must never be executed,
expanded through a shell, or used to read referenced file contents.

Any later capability implementation passes these layers in order:

1. **Authoring and semantic validation:** upstream ACES parsing, profile/schema
   validation, planning, and conformance own authored meaning. No Shifter
   shape-sniffing or duplicate validator may substitute for them.
2. **Package and catalog admission:** pack containment and digest validation,
   `validate_package_source`, explicit contract/profile/source allowlists,
   conformance status, collision prevention, and
   `SHIFTER_ACES_NATIVE_PROVISIONING` launch gating all fail closed.
3. **Product authorization and admission:** existing session/API-token and
   exact-scope gates apply if an API changes; service-layer ownership,
   caller/user validation, active-range policy, backend admission, and CTF
   participant/organizer rules remain authoritative. Catalog visibility is not
   authorization.
4. **Platform plan validation:** `shared.aces.runtime_target` uses the declared
   manifest/capability envelope and one validate/apply interpretation path.
   Errors prevent dispatch and yield bounded, sanitized diagnostics.
5. **Persistence and dispatch:** the compiled plan keeps its kind, transport
   contract version, and ACES producer version; engine creation is transactional
   and request-id idempotent. Content/evidence bindings remain separate,
   versioned, bounded, and byte/secret-free.
6. **Separate provisioner trust boundary:** `aces_plan.parse_plan` repeats
   envelope, version-window, resource-type, payload, identity, alias,
   cross-reference, topology, network, composition, and credential-policy
   checks before cloud, Terraform, SSH, SSM, or guest mutation.
7. **OS, secret, and error exposure:** tokens, credentials, flags, prompts,
   commands, provider configuration, and payload bodies stay out of argv,
   diagnostics, status reasons, logs, audit JSON, snapshots, and API errors.
   Use existing secret managers, authenticated guest delivery, sensitive-env
   separation, redaction helpers, and curated error envelopes.

## Extensibility Seam

The tracking seam is the existing inventory row, parameterized by stable id,
surface, one owner category, ACES target, Shifter owner, validation evidence,
and next issue kind. The runtime seam is the explicit ACES
contract/profile/capability discriminator plus compiled resource addresses.

The next profile, source kind, participant-runtime capability, or composition
term should widen the central allowlist/manifest and its shared validators and
conformance evidence. It must not require scenario-id branches across CMS,
engine, CTF, Mission Control, provisioner, Terraform, or workflows.

## Gotchas And Anti-Patterns

- Do not treat a successful one-off range, standalone Polaris script, manual
  Terraform variable, image bake, or provisioner branch as closure of an
  expressiveness gap.
- Do not add new CyberScript fields, private YAML keys, environment variables,
  provider tags, plan resource names, or audit/event JSON as a shadow SDL.
- Do not use `RangeSpec`, `Scenario.definition`, `range_config`, operation
  sidecars, participant sidecars, or catalog provenance as a generic options
  bag.
- Do not equate preserving a field with realizing its effect. Capability claims
  require observable, non-vacuous backend evidence through the normal Shifter
  path.
- Do not copy ACES models, profiles, validators, status enums, diagnostics,
  exception families, or conformance logic into Shifter.
- Do not authorize by scenario id, catalog row, profile string, sidecar
  existence, UI visibility, or possession of a request id.
- Do not weaken current CyberScript behavior or ACES feature gating while a gap
  is open. A workaround is not cutover authority.
- Do not place secret or scenario-sensitive values in the parity inventory,
  issue bodies, ADR examples, test names, logs, snapshots, or diagnostics.

## Non-Goals And Boundaries

- No implementation of the three Polaris capability examples.
- No ACES SDL/profile, CyberScript, CMS schema, model, migration, API, UI,
  engine, provisioner, Terraform, image, CTF, Mission Control, or workflow
  change.
- No ACES cutover, feature-flag change, backend capability claim, conformance
  claim, or production-workaround approval.
- No new tracker, duplicate inventory schema, automatic issue creator, or
  runtime enforcement service.
- No requirement transition, traceability mutation, GitHub issue disposition,
  or implementation plan.
