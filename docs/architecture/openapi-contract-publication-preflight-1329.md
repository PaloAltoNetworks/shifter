# `/api/v1/` OpenAPI Contract Publication Preflight

Status: pre-implementation architecture guidance

Date: 2026-07-14

Issue: GitHub #1329, "Publish the /api/v1/ OpenAPI contract with CI drift and
breaking-change gates"

This is a requirement-free run. The GitHub issue title, body, scope, and
acceptance criteria are the shipping contract. This note sets architecture
boundaries; it is not an implementation plan.

## Scope Boundary

#1329 publishes the existing DRF `/api/v1/` surface as a deterministic,
committed OpenAPI artifact. The runtime source remains Django URL routing, DRF
serializers/views, permissions, and drf-spectacular annotations. The artifact
is generated publication output and is the API source of truth for downstream
consumers; it must never become a hand-maintained second runtime schema.

The current committed `frontend/src/api/schema.d.ts` is a generated SPA
projection, not the public contract. It must be generated from the committed
OpenAPI artifact so the SPA, MCP tooling, and external clients all consume the
same publication. Do not generate a second OpenAPI document independently in
the frontend lane.

This issue publishes the routes already owned by `config/api_urls.py`. It does
not authorize adding the route-consolidation endpoints tracked by #1328,
changing domain behavior, retiring legacy routes, or converting non-DRF
services into API contracts.

## Architecture Decisions

- Generate OpenAPI from `config.api_urls`, `config._drf_settings`, the existing
  per-app DRF serializers/views, and drf-spectacular annotations. Do not derive
  it from frontend types, models alone, prose tables, example payloads, or a
  separately authored schema.
- Publish canonical OpenAPI JSON with stable ordering and formatting. The
  generation environment must be hermetic: test settings, SQLite, no live
  database, cache, cloud, secret store, provider API, or network dependency.
- A schema-generation warning or graceful fallback is a contract defect, not
  acceptable publication output. Generation and OpenAPI validation must fail
  on every warning/error before drift or compatibility comparison runs.
- Keep three concepts distinct: runtime DRF source, current published artifact,
  and trusted compatibility baseline. Drift compares runtime generation with
  the current artifact. Breaking-change analysis compares the proposed
  artifact with the base branch's already-published artifact (or an immutable
  per-major snapshot), never solely with a baseline the same PR can rewrite.
- Keep HTTP compatibility semantics outside workflow YAML and shell. CI invokes
  a pinned OpenAPI-aware compatibility checker or a small package-local wrapper;
  it does not implement path/field comparison in ad hoc shell. The backend
  bundle JSON-Schema checker in `shifter/installation/_schema_compat.py` is a
  workflow precedent, not an OpenAPI compatibility engine, and must not be
  stretched across the concept boundary.
- Reuse runtime request/response serializers as contract components. Schema-only
  serializers may describe the shared error envelope and deliberate non-model
  responses, but they must live at the DRF boundary and must not duplicate
  service validation, persistence models, domain DTOs, or exception classes.
- Document both authentication alternatives accurately: same-origin Django
  session cookie plus CSRF for unsafe browser requests, and `shf_` bearer token
  for programmatic requests. Bearer-token scopes are application scopes, not
  OAuth2 scopes; expose the exact per-operation requirement with a documented
  OpenAPI extension or equivalent metadata rather than declaring a fictitious
  OAuth2 flow.
- JSON API failures use the canonical `shared.api.errors` envelope and one
  reusable OpenAPI component. Deliberate non-JSON success routes (download,
  redirect, or browser bootstrap) declare their actual status codes and media
  types; the schema must not pretend they return JSON.

## `/api/v1/` Versioning And Compatibility Policy

`v1` is the public API major, not the Django package version, frontend version,
OpenAPI patch version, or a migration-note sequence. `NamespaceVersioning`, the
URL namespace, `ALLOWED_VERSIONS`, schema `info.version`, artifact location, and
compatibility baseline must agree on that major.

Changes that remain in `/api/v1/` are backward-compatible additions:

- a new path or operation with no effect on existing operations;
- a new optional request parameter or optional request-body property;
- a new optional response object field, with consumers required to tolerate
  unknown object fields;
- a wider set of accepted request values while preserving prior meanings;
- documentation, examples, descriptions, and deprecated markers that do not
  change machine-readable behavior.

The following are breaking for an existing consumer and require a parallel
`/api/v2/`, an explicit major-version update across the versioning surfaces,
and a migration note. The existing `/api/v1/` remains available during its
documented migration window:

- removing or renaming a path, operation, parameter, request field, response
  field, component, or security scheme;
- making an input required, narrowing accepted input, or changing parameter
  location/style/explode semantics;
- widening a response type, making a response field optional or nullable,
  adding a possible response enum/discriminator value to a closed union, or
  changing a field's meaning or units;
- changing success/error status codes, content types, pagination shape, error
  envelope shape, stable error codes, or operation identifiers;
- changing an operation from public to authenticated, removing an auth
  alternative, tightening role/scope requirements, or adding an unsafe method
  without its session-CSRF contract;
- changing defaults in a way that alters observable behavior for an omitted
  input.

Correcting an inaccurate published schema is still a compatibility change for
clients that coded against it. Resolve generator fallbacks and inaccurate
annotations before the initial baseline is published; after publication, do
not silently call a correction "drift." A narrowly justified exception, if
ever necessary, belongs in `docs/adr/exceptions.yaml` with owner, expiry,
affected surface, and migration evidence.

The migration note is machine-verifiable release evidence keyed to the old and
new major. A PR label, commit-message token, schema `info.version` edit by
itself, or overwriting the v1 baseline does not authorize a break.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Root API routes and major | `config/urls.py`, `config/api_urls.py`, `config/_drf_settings.py` | Keep `/api/v1/`, `NamespaceVersioning`, allowed versions, schema view, docs view, pagination, and DRF defaults aligned. |
| Schema generator | drf-spectacular settings and annotations | Extend existing serializers and `@extend_schema`; do not add a second generator or handwritten OpenAPI source. |
| Runtime DTO and validation boundary | `config/api_*.py`, `cms/api/serializers.py`, `mission_control/api/serializers.py`, `risk_register/api/serializers.py`, and CTF's DRF boundary | The same serializers that validate/render HTTP payloads describe the contract. Service/domain validation remains behind them. |
| Authentication | `shared/api_tokens/authentication.py`, DRF `SessionAuthentication` | Preserve fail-closed bearer handling and CSRF-protected sessions; never put a programmatic token in browser code. |
| Scope registry and permissions | `shared/api_tokens/scopes.py`, `shared/api_tokens/permissions.py`, per-app permission classes | Publish exact operation requirements from the existing scope vocabulary and permission composition; do not create a schema-only scope list. |
| Error envelope | `shared/api/errors.py`, `shared/errors.py` | Reuse stable code/message/details/request_id behavior and sanitization; schema components describe it rather than replacing it. |
| API schema extensions | `shared/api/schema.py` | Extend the existing authentication extension and place shared schema-only response components here or in a cohesive sibling. |
| Pagination | `REST_FRAMEWORK.DEFAULT_PAGINATION_CLASS`, `PAGE_SIZE`, view/queryset conventions | Publish the actual DRF pagination shape; do not invent a frontend-only list envelope. |
| Logging and audit | `shared/log_sanitize.py`, `shared.audit`, existing per-app audit/service paths | Generation emits no request data. Runtime changes needed for truthful schemas retain the existing sanitized logs and mutation audit paths. |
| SPA consumer | `frontend/package.json` `gen:api`, `frontend/src/api/schema.d.ts`, `frontend/src/api/client.ts` | Generate TypeScript from the committed OpenAPI artifact; keep the single session/CSRF-aware client and typed error class. |
| CI routing | `.github/quality-path-filters.yaml`, `.github/workflows/_quality.yml` | Run the contract gate in the existing `shifter_platform` lane, which already covers the whole package and lockfile; do not rely on an incomplete serializer-only path list. |
| Publication precedent | ADR-011-R8 and `shifter/installation/publication.py` | Reuse the drift/baseline/migration-ledger workflow shape and sanitized diagnostics, not its JSON-Schema-specific compatibility code. |
| Architecture control | ADR-029, ADR-040, `scripts/adr_guard/**` | Preserve the canonical API boundary; add a coded ADR check only when implementation introduces an enforceable rule that existing CI tests cannot protect. |

## Cross-Cutting Layers The Design Must Pass

### Security and validation

- **URL/version gate:** `config.urls` exposes the surface only through the `v1`
  namespace; `NamespaceVersioning`, `ALLOWED_VERSIONS`, and the generator's
  selected API version must agree. The artifact must contain only the intended
  `/api/v1/` paths, not legacy per-app JSON routes, health/admin endpoints, or
  the schema/docs endpoints unless deliberately included.
- **HTTP shape validation:** DRF serializers and parser behavior remain the
  request/response authority. Schema annotations reference those serializers;
  they do not copy `validate_*`, model constraints, service validators, or
  scenario/Pydantic schemas into OpenAPI-only DTOs.
- **Authentication gate:** `ApiTokenAuthentication` remains first and fails
  closed when a bearer credential is present but invalid; session auth remains
  the browser alternative. The contract lists alternatives per operation and
  marks genuinely public operations with empty security rather than inheriting
  authentication accidentally.
- **Authorization/scope gate:** `require_scope`, the central
  `shared.api_tokens.scopes` registry, and per-app actor/role permissions remain
  authoritative. OpenAPI metadata describes these gates but does not enforce or
  redefine them. Scope changes are reviewed as compatibility/security changes.
- **CSRF gate:** unsafe session-authenticated operations require Django's CSRF
  cookie/header posture. The header is conditional on the session alternative;
  bearer clients must not be told to mint or store a browser CSRF cookie.
- **Secret-handling gate:** generation uses no real credential and must not
  inspect live environment values. Credential/password/token fields are marked
  `writeOnly` or omitted from responses as runtime serializers require. Do not
  publish example bearer tokens, cookies, credentials, presigned URLs, provider
  identifiers, raw settings, or secret references/values.
- **Environment/config gate:** run through the existing Django test-settings
  posture (`TESTING=1`, explicit SQLite selection, deterministic locale/timezone
  where needed). Satisfy `config._runtime_env` and database setting validators
  with non-secret CI environment values; do not add a parallel schema settings
  module or weaken required production settings.
- **OS/process exposure:** generation and comparison require no bearer token,
  cloud credential, database password, or service access. Do not place secrets,
  schema bodies, or migration payloads in process argv. Use repository-relative
  artifact paths and bounded diagnostics; any third-party executable follows
  ADR-037 pin/checksum provenance.
- **Error-envelope leakage:** `shared.api.errors` and `shared.errors` continue
  to sanitize user messages; contract and checker failures may name paths,
  methods, component fields, versions, and repository-relative files, but never
  raw request bodies, exception input, headers, cookies, tokens, or env dumps.

### Persistence, observability, and workflow

- **Persistence boundary:** publication adds no database model, migration,
  repository, cache key, or stored API-version row. Schema generation must not
  depend on production data or query live persistence. Model-backed serializers
  may expose metadata without making the database the publication oracle.
- **Service and audit boundary:** making an endpoint schema-complete must not
  move authorization, ownership, mutation, audit, or transaction behavior out
  of the existing service path. In particular, retain Risk Register audit,
  Mission Control/CMS service orchestration, and CTF role/participant checks.
- **Logging/observability:** the generator/checker is a build-time quality gate,
  not a runtime telemetry producer. Runtime request correlation stays
  `X-Request-ID` plus the optional `request_id` error field, with existing safe
  logging. Do not add a second request-ID or logging envelope for OpenAPI.
- **CI workflow:** the gate runs with `contents: read`, no cloud permissions or
  repository writes, and is required by the existing aggregate quality/PR gate.
  Workflow changes retain action SHA pinning, actionlint, secret scanning,
  ADR guard, Python lint/type/test gates, and frontend generation/typecheck.
- **Trusted-base comparison:** breaking analysis must have base history or a
  protected immutable snapshot. A shallow checkout that silently falls back to
  the PR's artifact is fail-open and prohibited.

## Current Baseline Blockers

A preflight generation on 2026-07-14 using the existing documented command
surface produced 84 paths but reported 593 errors (55 unique causes) and five
warnings while exiting successfully. The output contained `ApiTokenAuth` and
`cookieAuth`, but no reusable error schema and no machine-readable application
scopes. The main blockers are:

- legacy-wrapped CTF `APIView`s without discoverable request/response
  serializers;
- several Mission Control `APIView`s whose response-only annotations do not
  make request serializers discoverable;
- operation-ID collisions in CTF routes;
- one unresolved serializer method-field type;
- canonical error responses and per-operation scopes absent from the schema.

Do not commit that graceful-fallback output as the compatibility baseline. The
initial published artifact must be warning/error-free and complete enough that
a downstream client needs no Python source or frontend handwritten types to
interpret paths, parameters, bodies, responses, auth, scopes, pagination, and
errors.

## Extensibility Seam

The seam is the existing API major passed explicitly through schema generation,
artifact path, compatibility-base path, and migration-note lookup. It must be
possible to publish `v2` alongside `v1` by selecting another Django namespace
and output/baseline location, without editing v1, copying compatibility logic,
or branching on app names in CI.

Parameterize the checker/generator by API major and paths; validate that the
selected major agrees with `NamespaceVersioning` output and schema metadata.
Do not introduce a database-backed version registry or a general contract
platform for this single obvious variation.

## Whole-Repo Scope

The future implementation must evaluate changes against:

- `docs/adr/index.yaml` ADR-029 and ADR-040
- `docs/architecture/spa-cutover-architecture-1300.md`
- `shifter/shifter_platform/config/urls.py`
- `shifter/shifter_platform/config/api_urls.py`
- `shifter/shifter_platform/config/_drf_settings.py`
- `shifter/shifter_platform/config/api_bootstrap.py`
- `shifter/shifter_platform/config/api_dashboard.py`
- `shifter/shifter_platform/shared/api/**`
- `shifter/shifter_platform/shared/api_tokens/**`
- `shifter/shifter_platform/{cms,ctf,mission_control,risk_register}/api/**`
- each included app's URL configuration, models/enums, services, permissions,
  audits, and tests where they determine the wire contract
- `shifter/shifter_platform/frontend/package.json`
- `shifter/shifter_platform/frontend/src/api/schema.d.ts`
- `shifter/shifter_platform/frontend/src/api/client.ts`
- `shifter/shifter_platform/pyproject.toml` and `uv.lock`
- `.github/quality-path-filters.yaml`
- `.github/workflows/_quality.yml`
- `.pre-commit-config.yaml` if a local contract check is added
- `scripts/adr_guard/**` only if implementation adds an ADR-level baseline
  immutability check

No Terraform, Kubernetes, Helm, Docker runtime, cloud provider, or production
database layer should consume or generate the artifact. The portal image may
continue serving the authenticated schema/docs views, but runtime serving is
not the committed artifact's authority.

## Gotchas And Anti-Patterns

- Do not hand-edit OpenAPI or maintain parallel backend/frontend schemas.
- Do not bless generator fallbacks, warnings, unstable operation IDs, or
  unresolved serializer fields because the document passes JSON-schema
  validation or the command exits zero.
- Do not compare only raw, nondeterministically formatted text. Canonicalize
  output for drift; use OpenAPI semantics for compatibility.
- Do not let a PR overwrite the compatibility oracle it is checked against.
- Do not treat all type changes symmetrically: request compatibility and
  response compatibility run in opposite producer/consumer directions.
- Do not declare API-token scopes as OAuth2 scopes or invent wildcard scopes.
- Do not infer scopes from URL names, serializer names, or prose when the
  existing permission classes and central registry own them.
- Do not add a second exception hierarchy, validation layer, pagination
  wrapper, request-ID shape, API client, API version registry, or route list.
- Do not leak serializer examples containing secrets or expose write-only
  credentials in response components.
- Do not force non-JSON success flows into a JSON schema; model their actual
  content and keep JSON error envelopes truthful.
- Do not narrow runtime responses merely to make a diff tool green. A reported
  break requires a real version/migration decision, not checker suppression.
- Do not make compatibility approval depend on PR labels, branch names, commit
  messages, or an unstructured prose search.

## Non-Goals

- No OpenAPI artifact, checker, workflow, serializer, route, or frontend type is
  implemented by this preflight.
- No route consolidation from #1328 and no new `/api/v1/` product capability.
- No change to service behavior, persistence, transactions, auditing, logging,
  domain exceptions, auth policy, token scope vocabulary, or pagination.
- No retirement of legacy Django/API routes and no SPA cutover decision beyond
  ADR-029.
- No OAuth2 authorization server, client-credential flow, CORS change, browser
  bearer-token storage, or CSRF exemption.
- No live schema registry, artifact upload service, database version table, or
  runtime dependency on the committed file.
- No Ground Control requirement UID for this requirement-free issue.
