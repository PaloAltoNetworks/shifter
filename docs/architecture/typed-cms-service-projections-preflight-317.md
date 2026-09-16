# Typed CMS Service Projections Preflight (#317)

Status: pre-implementation guidance

Date: 2026-08-02

Issue: GitHub #317, "Give cms.services dict[str, Any] projections proper
schema types."

This issue is requirement-free. The GitHub issue is the shipping contract. This
note records boundary decisions and guardrails; it is not an implementation
plan.

## Scope Boundary

The four service returns remain plain dictionaries with their current JSON and
template behavior:

- `cms.services.list_agents`
- `cms.services.initiate_upload`
- `cms.services.list_scenarios`
- `cms.services.get_scenario`

Use native `TypedDict` contracts under `shared/schemas/` for static checking.
Do not return Pydantic objects, add service-exit parsing, or serialize and parse
the dictionaries again. The values have already passed their authoritative
runtime boundaries, and existing DRF, Django-template, JavaScript, and test
consumers rely on mapping behavior.

TypedDict is not runtime validation, authorization, serialization, or
redaction. Existing runtime checks remain authoritative.

## Architecture Decisions

- Keep this contract family separate from CyberScript authoring schemas. A CMS
  projection describes a service result; it is not an `AgentConfig` model, an
  upload-token payload, a scenario template, or a public OpenAPI serializer.
  The module must be shared-native and must not import `cms` or CyberScript.
- Give each stable mapping its own type. The agent list item must include the
  current `agent_type` and `agent_type_display` keys in addition to the fields
  listed in the migrated issue. The upload result must include exactly
  `presigned_url`, `s3_key`, `upload_token`, and `expected_os`.
- Model `expected_os` as non-null at the service boundary. Agent installer
  initiation rejects a `FileFormat` without `os_slug` before constructing the
  result. The DRF response currently permits null, but a looser presentation
  schema must not weaken the service invariant.
- Define the scenario projection around the common catalog metadata produced
  for every source: identity, description, scenario type, access overlay,
  default/launchability state, and agent requirements. Source-specific
  authoring content may be optional JSON-shaped fields, but must not be copied
  into a second hierarchy of TypedDicts that duplicates
  `cms.scenarios.schema` or CyberScript.
- Do not use a discriminated scenario union as though `scenario_type` selected
  one immutable payload shape. `cms.scenarios.cutover.apply_cutover_routes`
  can re-back a legacy public entry with RAES while retaining legacy display
  and structural fields. The registry projection is deliberately an overlay,
  not the authored template union.
- Annotate the constructors/producers, not only the public service return
  lines. A cast at the service boundary would hide missing or mistyped keys
  from mypy and defeat the issue.
- Preserve the public `cms.services` facade and direct `shared` contract
  imports. Do not expose or import private `cms.services._*` modules across
  layers.
- No ADR change is required. This selects an existing static-contract pattern
  and does not create a new repository-wide architecture rule.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #317 |
| --- | --- | --- |
| Static dictionary contracts | `shared.messages.payloads`, `shared.channels.payloads` | Follow the existing stdlib-only TypedDict pattern. Do not add a validation framework. |
| Agent output construction | `cms.services._common._agent_projection_dict`, `_assert_agent_projection_shape` | Keep one projection builder and its existing runtime model-shape assertion; do not add a Pydantic copy. |
| Agent persistence and ownership | `AgentConfig.active_for_user`, `SoftDeleteManager`, `select_related("os")` | Keep the user filter, active-row filter, ordering, and joined OS lookup. Never project `s3_key`, hashes, or owner data in the list item. |
| Upload request validation | `UploadInitiateSerializer`, `_validate_caller_user`, `_validate_nonempty_str`, `_validate_positive_int` | DRF owns HTTP shape; CMS owns callable/domain checks. A response type must not duplicate either. |
| Upload policy and trust | `cms.assets.validation`, `shared.uploads.inspection`, quota settings, `cms.assets.s3`, `cms.assets.upload_token` | Preserve extension/format checks, quota, provider adapter, signed user-bound expiry, and later object/header verification. |
| Upload response schema | `UploadInitiateResponseSerializer`, committed `openapi/v1.json`, generated SPA `schema.d.ts` | Keep runtime result and published response fields aligned. TypedDict does not replace the serializer or OpenAPI drift gate. |
| Scenario authoring validation | `cms.scenarios.schema`, `cms.scenarios.loader`, `Scenario.to_template` | Keep `yaml.safe_load`, slug/path containment, and Pydantic `TypeAdapter`/model validation as the runtime source of truth. |
| Scenario catalog policy | `cms.scenarios.registry`, `ScenarioMetadata`, `cms.scenarios.cutover` | Preserve collision handling, enabled/staff-only filtering, source overlay, and fail-closed launchability. Do not move policy into the type module. |
| Scenario presentation | `cms.scenarios.catalog_presentation`, `ScenarioListItemSerializer`, `CatalogEntrySerializer` | Reuse the bounded presentation/serializer seams where an HTTP surface needs less than the internal registry payload. Do not treat a return annotation as an allowlist. |
| Authentication and scopes | `MissionControlReadAPIView`, `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, API-token scope permissions, `threat_research_required` | Keep caller and surface authorization ahead of each projection. TypedDict grants no authority. |
| Errors | `CMSError`, `shared.api.errors.api_error_response`, `shared.errors.classify_user_message` | Preserve current exception translation and the canonical bounded API error envelope. Do not introduce schema-specific exceptions. |
| Logging | module loggers and `shared.log_sanitize.safe_log_value` / `safe_log_id` | Never log upload tokens, presigned URLs, raw provider responses, or unsanitized caller strings. |
| Static enforcement | `shifter/shifter_platform/pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/_quality.yml` | Full platform mypy is blocking. Do not add `Any`, broad casts, ignores, or a CI exemption to make the annotations pass. |
| Architecture enforcement | `.importlinter`, `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml` | Keep shared contracts dependency-free and preserve public service boundaries. |

## Cross-Cutting Layers The Design Must Pass

### Agent listing

- Authorization: Mission Control reads pass session/API-token authentication,
  active-actor resolution, read scope, and then the service's user validation.
  `AgentConfig.active_for_user` is the ownership boundary; the default soft-delete
  manager excludes deleted rows.
- Persistence and response allowlist: the ORM projection exposes display fields
  only. It must not grow storage keys, hashes, user identifiers, or other model
  fields through generic model serialization.
- Serialization and errors: DRF's `AgentListItemSerializer` and the committed
  OpenAPI artifact remain the public response contract. Internal failures keep
  the existing exception behavior; a static type must not create a new client
  error family.

### Upload initiation

- Authorization and input shape: the Mission Control upload-write permission,
  active actor, request serializer, and CMS validators all remain in place.
- Policy/config shape: `AGENT_USER_STORAGE_QUOTA_MB`,
  `AGENT_UPLOAD_URL_EXPIRES`, `AWS_S3_BUCKET_NAME`, and `SECRET_KEY` continue to
  be read through validated Django settings and the existing storage adapter.
  No new environment variable or local `os.environ` read belongs in this work.
- Secret handling: `presigned_url` and `upload_token` are short-lived bearer
  capabilities delivered only in the authenticated JSON response. Do not log,
  persist, add real OpenAPI examples for, put in process argv, shell commands,
  job manifests, or plain environment variables. The browser session stores the
  existing token fingerprint, not the token.
- Runtime trust: extension/format validation, quota, HMAC signing, user binding,
  expiry, later object identity/size checks, and magic-byte inspection are not
  replaced by a result type.
- Error envelope: provider errors remain translated to `CMSError` and then a
  classified, bounded API message. Pydantic `ValidationError` must not become a
  new unmapped response path.

### Scenario projections

- Authorization: `list_all_scenarios(user=...)` owns enabled/staff-only
  filtering for user-facing lists; staff review uses its separately protected
  surface. `get_scenario` has no actor parameter and must not be mistaken for an
  authorization check merely because its result is typed.
- Source validation: YAML templates pass slug/path containment, `yaml.safe_load`,
  and Pydantic validation; database scenarios pass `Scenario.to_template`; RAES
  rows pass the shared package-source contract and fail-closed launchability.
  Types do not replace any source gate.
- Presentation/redaction: registry entries can contain source-specific authored
  content. DRF serializer declarations used only by `extend_schema` do not
  filter a raw `Response`. Any future narrowing of HTTP scenario output must use
  an explicit bounded projection/serializer invocation and receive its own
  compatibility and security review; this static-typing issue must not claim to
  have performed that redaction.
- Config and OS exposure: cutover routing continues through validated
  `RAES_CATALOG_CUTOVERS` settings. Scenario dictionaries do not move into argv,
  shell text, or environment variables as part of this work.

## Extensibility View

The extension seam is the projection producer, not a generic schema factory:

- a new agent display field is added once to the agent projection type, builder,
  runtime assertion where appropriate, serializer, and consumer contract;
- a new upload backend still returns the same upload-initiation projection
  through the existing storage adapter; if a future upload kind legitimately has
  no OS, introduce an explicit kind/discriminator rather than making today's
  installer invariant nullable pre-emptively;
- a new scenario source supplies the common catalog metadata and keeps its
  authored payload behind its own schema/loader. It must not require a copy of
  that authoring schema in the CMS service projection module.

## Whole-Repo Scope

The contracts are observed by the following existing surfaces:

- `shifter/shifter_platform/shared/schemas/`
- `shifter/shifter_platform/cms/services/{_common,_agents,_uploads,_scenarios}.py`
- `shifter/shifter_platform/cms/scenarios/{schema,loader,registry,cutover,catalog_presentation}.py`
- `shifter/shifter_platform/cms/models/{assets,scenarios}.py`
- `shifter/shifter_platform/mission_control/api/{ranges,uploads,serializers}.py`
- `shifter/shifter_platform/mission_control/{context_processors,views,upload_session}.py`
- `shifter/shifter_platform/ctf/bridges.py`
- targeted CMS service, scenario-registry, Mission Control API, OpenAPI-contract,
  template, and SPA contract tests

Canonical configuration and enforcement in scope are
`shifter/shifter_platform/pyproject.toml`, `.importlinter`,
`.pre-commit-config.yaml`, `.github/workflows/_quality.yml`,
`scripts/adr_guard/adr_guard.py`, `openapi/v1.json`, and the generated frontend
API types. They should be verified, not weakened or duplicated.

## Gotchas And Anti-Patterns

- Do not return Pydantic models or call `model_validate`/`model_dump` solely to
  validate these service outputs.
- Do not annotate only the service return and use `cast` to conceal an untyped
  producer.
- Do not define a generic `Projection = dict[str, object]`; it preserves the
  original problem under a new name.
- Do not duplicate scenario Pydantic models, agent model fields, agent-type
  choices, upload token payloads, storage-provider DTOs, or DRF serializers in
  `shared/schemas`.
- Do not conflate the upload-initiation response with the signed upload-token
  payload. They have different fields, trust, lifetime, and consumers.
- Do not conflate registry catalog metadata, full authoring detail,
  `catalog_presentation` API DTOs, and hydrated launch templates.
- Do not assume `scenario_type` alone proves a homogeneous dict shape after a
  cutover overlay.
- Do not broaden scenario or agent responses through model `__dict__`, generic
  serializer/model dumping, or `total=False` on required common keys.
- Do not remove the agent runtime assertion or any input/auth/security validator
  on the theory that TypedDict validates at runtime.
- Do not log or persist bearer capability fields, and do not expose raw schema,
  provider, or stack errors through the API error envelope.
- Do not opportunistically redesign `create_agent(**kwargs)` or
  `create_credential(**kwargs)`. `AgentUploadSpec` already owns the internal
  agent-create input bundle, while credential data legitimately varies and is
  validated through `CredentialType.spec_class`/model validation. Input API
  tightening is separate work.

## Non-Goals And Implementation Boundaries

- No service behavior change, public API shape change, persistence migration,
  scenario-format change, upload protocol change, or new runtime dependency.
- No new DTO base class, schema registry, parser, validator, exception
  hierarchy, serializer family, repository, or workflow.
- No change to authentication, API-token scopes, scenario access policy,
  launchability, soft-delete semantics, upload quota, signing, object
  inspection, audit behavior, or logging framework.
- No broad typing cleanup of unrelated `dict[str, Any]` returns.
- No `**kwargs` redesign in this issue.
