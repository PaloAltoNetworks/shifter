# ACES image registry management surface preflight (#1566)

Status: pre-implementation guidance

Date: 2026-07-13

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1566>

Issue title: Tenant-facing management surface for the ACES image registry

This note fixes the architecture boundary for adding a tenant-facing way to
register, list, and disable `engine.models.AcesImageMapping` rows. It is not an
implementation plan. The issue is requirement-free; the GitHub issue title,
body, and acceptance criteria are the shipping contract.

## Decision Boundary

Expose the existing tenant registry through an operator-safe surface, but keep
`engine.services.upsert_aces_image_mapping` as the single validated write path.
The surface may be a Django management command, a Mission Control API, or both.
It must not be Django admin, direct model mutation, a new registry table, a
parallel JSON/YAML config registry, or a provisioner-side write path.

No new ADR is required while the work stays inside ADR-032-R2: authored ACES
`source` identity resolves to concrete provider images at realization through
backend-owned registry data, and missing mappings fail loud.

## Required Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Write validation and idempotency | `engine.services._aces_image` / `upsert_aces_image_mapping` / `AcesImageMappingOptions` | All register and disable mutations delegate here. Do not duplicate provider, natural-key, disk-size, or soft-disable validation. |
| Persistence contract | `engine.models.AcesImageMapping` | Preserve `(provider, source_name, source_version)` as the natural key, blank `source_version` as the any-version fallback, and `enabled=False` as disable. Do not delete mappings for normal retirement. |
| Read realization | `provisioner_db.get_aces_image_candidates`, `aces_image_resolver.resolve_from_candidates`, `aces_gce_image.resolve_gce_image` | The provisioner remains read-only and applies exact-version / any-version rules. Do not move matching logic into the management/API surface. |
| ACES launch gating | `SHIFTER_ACES_NATIVE_PROVISIONING`, `cms.services.create_range_dispatch`, `cms.scenarios.registry` | The new surface is inert for launch behavior with the flag off; it may manage data, but must not make ACES catalog entries launchable or alter cyberscript paths. |
| Mission Control API shape | `mission_control.api._base`, `shared.api.errors`, `shared.api_tokens.scopes`, `shared.log_sanitize` | Any API endpoint must use DRF serializers, shared error envelopes, exact token scopes, actor resolution, and sanitized logging. |
| CMS authoring policy | `shared.auth.can_edit_cms_authoring`, `cms.api.permissions.CMS_*_PERMISSIONS` | If exposed as a tenant/operator API, use the existing staff/Threat Research authoring gate or an explicitly named new scope/policy. Do not let participant-only users manage registry data. |
| Management command style | existing Django commands such as `run_aces_backend_validation` and engine drainers | Use `CommandError` for bounded failures, `safe_log_value` for operator-controlled values in logs, and non-secret stdout summaries. |
| Validation evidence | `docs/architecture/aces-cutover-evidence-1264.md`, `scenario-dev/aces-validation/shifter-aces-validation.sdl.yaml` | Document that the validation package needs a `gce` mapping for `source_name=alpine`, `source_version=3.19`. |

## Cross-Cutting Layers

### Security and auth

- **HTTP authentication:** a Mission Control/API surface must pass
  `IsAuthenticatedSessionOrApiToken` and a concrete actor permission before any
  registry read or mutation.
- **Authorization:** registry mutation is operator/staff authoring behavior, not
  participant range lifecycle. Reuse `can_edit_cms_authoring` or add a narrowly
  named API-token scope in `shared.api_tokens.scopes`; never reuse range,
  upload, NGFW, credential, or participant permissions by analogy.
- **Serializer/body validation:** DRF serializers own HTTP shape checks
  (required fields, booleans, positive disk size, max lengths). The service
  remains the final validator, so API and command behavior cannot drift.
- **Secret handling:** image refs, machine types, disk types, source names, and
  notes are non-secret operator data, but they are still user-controlled. Do not
  log raw multiline values, environment dumps, request bodies, or provider
  error bodies. Use `safe_log_value`; no registry value belongs in a secret
  store or command-line token.
- **OS-level exposure:** a management command should avoid secret-like inputs in
  argv by design. The registry fields are not credentials, but do not add flags
  that accept provider credentials, service-account keys, tokens, or raw ACES
  package bodies.
- **Error envelopes:** API failures must return the shared `{error:{code,
  message, details?, request_id?}}` envelope through `shared.api.errors` or
  `MissionControlAPIView` helpers. Do not return `str(exc)` from generic
  exceptions.

### Maintainability

Keep the surface thin. Listing should project `AcesImageMapping` rows with an
allowlisted DTO, and mutations should call `upsert_aces_image_mapping`. If a
list helper is needed for reuse between command and API, place it beside
`engine.services._aces_image`; do not teach the provisioner resolver, catalog
registry, or validation command to own registry querying.

### Extensibility

The parameter seam is `provider`. Preserve it in command/API input and response
even if the first live path is only `gce`, because `AcesImageMapping.Provider`
already includes provider choices and the resolver is provider-scoped. Do not
derive provider from image-ref prefixes, package source, ACES manifest profile,
or deployment environment. A future AWS resolver should add provider-specific
read/realization behavior without changing the tenant-management contract.

## Gotchas and Anti-Patterns

- Do not conflate package registration (`AcesPackageSource`) with image
  realization (`AcesImageMapping`). A package being conformant or launchable
  does not imply its images are realizable.
- Do not infer a mapping from `os_family`, node address, scenario id, package
  ref, or manifest capability. Authored `source.name` plus optional version is
  the key; source-less base OS lookup is the only sanctioned `os_family` image
  policy.
- Do not implement disable as delete. Disabled rows must remain visible enough
  for audit/operator diagnosis while excluded from provisioner resolution.
- Do not copy exact-version / any-version selection into the API or command.
  That matching remains in `aces_image_resolver`.
- Do not add raw provider image validation by cloud API call on every write.
  Shape checks are useful, but live provider verification belongs to validation
  runs or provider-specific preflight, not to the canonical registry mutation.
- Do not make this surface a launch toggle. `SHIFTER_ACES_NATIVE_PROVISIONING`
  and catalog launchability remain separate gates.

## Non-Goals

- No Django admin surface.
- No new ACES schema, SDL extension, launch DTO, provisioner config schema, or
  migration away from ADR-032.
- No package-source management, conformance workflow, image build/promotion
  workflow, or cloud-provider image existence probe.
- No participant-facing UI and no broad Mission Control lifecycle permission.
- No change to cyberscript scenario hydration, legacy `RangeSpec` image
  profiles, or existing GCE role-profile env variables.
