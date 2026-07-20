# SPA Scenario Editor Workspace Preflight (#1371)

Status: pre-implementation guidance

Date: 2026-07-13

Issue: GitHub #1371, "SPA Phase 2: Scenario Editor workspace"

Requirement: none. The GitHub issue title, body, constraints, and acceptance
criteria are the shipping contract.

This note sets repo-wide architecture guardrails for moving Scenario Editor into
the platform SPA. It is not an implementation plan and does not implement SPA
routes, components, APIs, serializers, services, persistence, rollout, or
legacy-route retirement.

## Scope Boundary

#1371 must build on the accepted SPA, information architecture, and shell work:

- ADR-013: one shared, role-aware platform IA and navigation contract.
- ADR-029: React 18, TypeScript, Vite, React Router v7, TanStack Query v5, one
  Django origin, canonical `/api/v1/`, session plus CSRF for browser calls, and
  no browser-held `shf_` API tokens.
- `docs/design/spa-cohesive-ux-1368.md`: the Scenario Editor use cases, page
  templates, required states, taxonomy, and known API-readiness gaps.
- `docs/architecture/spa-platform-shell-preflight-1369.md`: shared shell,
  navigation metadata, bootstrap, route ownership, and rollout conventions.
- `docs/architecture/cms-drf-api-preflight-1122.md`: the established CMS DRF,
  authentication, actor, scope, service, validation, error, and audit boundary.
- The existing `cms.scenario_editor` service facade, scenario registry and
  schema, `Scenario` and `ScenarioMetadata` persistence, and catalog
  presentation DTO.

No new ADR is required if #1371 stays inside ADR-013 and ADR-029. Update the ADR
registry and enforcement docs only if implementation changes an enforceable
guardrail such as the frontend stack, API/auth posture, import boundaries,
schema ownership, scenario source/editability rules, rollout/route-retirement
policy, static asset policy, navigation source of truth, or CI gates.

The current `/api/v1/cms/` surface covers catalog list/detail, YAML validation,
and create-from-YAML. It does **not** yet cover the complete issue contract:
structured create, custom scenario edit, clone, soft delete, export, or explicit
availability/audience updates. Those are API-consolidation gaps to close through
the canonical CMS API and existing services, not reasons for the SPA to call
legacy Django JSON or form-action routes.

Existing coverage is not automatically the final contract. The YAML create/
update helpers and export helper currently reconstruct an allowlist containing
`instances`, `subnets`, and `ngfw`; that can discard a future structural field.
The YAML request serializer is unbounded, and the parser currently logs a raw
`YAMLError`, whose rendering can include input context. Treat those as known
losslessness/resource/logging gaps at the canonical server boundary, not as
behavior to reproduce in the SPA.

## Architecture Decisions And Guardrails

- The SPA owns presentation, editor draft state, route state, loading/empty/
  permission/error states, accessible interaction, and client orchestration. It
  does not own authoring authorization, source capability policy, scenario
  validation, YAML parsing/serialization, persistence, audit, or catalog
  resolution.
- Preserve the distinction between the heterogeneous read catalog and mutable
  content. `cms.scenarios.catalog_presentation` is a bounded, read-only
  projection over built-in YAML, custom database, and ACES sources. Only a
  custom database `Scenario` is the mutable content aggregate. Do not turn every
  catalog row into a CRUD resource.
- Preserve the existing public backend boundaries. DRF views call
  `cms.scenario_editor.services`; the facade coordinates the private
  `_validation`, `_crud`, `_metadata`, `_persistence`, and `_yaml` concerns.
  Views and serializers must not import those private modules or reproduce
  their workflows.
- `cms.scenarios.schema` remains the structural source of truth. DRF serializers
  validate HTTP shapes and describe response DTOs, but must not become a second
  scenario schema. Frontend types come from the generated OpenAPI schema; do not
  hand-copy field sets, enum choices, or validation rules into TypeScript.
- The current editor validation contract is `ScenarioTemplate` (demo), even
  though model hydration uses the wider `AnyScenarioTemplate` union. That union
  is not permission to add CTF or ACES authoring to #1371. A new authorable
  scenario kind needs a separately reviewed service/schema/source-capability
  decision.
- Structured editing and YAML editing are two projections of one persisted
  `Scenario.definition`, not two models, draft tables, schemas, or lifecycle
  systems. Both paths must enter the same service validation and persistence
  boundary. The browser must not parse or emit authoritative YAML.
- A projection that cannot round-trip a schema field must fail visibly or offer
  the lossless YAML path. It must never silently discard fields. In particular,
  do not copy the legacy form/YAML helper's hard-coded `instances`, `subnets`,
  and `ngfw` reconstruction into new code; clone already establishes the safer
  structural-definition projection/reset pattern.
- Map the issue's “publish” language onto the existing explicit availability
  overlay, `ScenarioMetadata.enabled`. Do not invent draft/published states,
  publication records, review workflow, or a new status enum. Saving content
  must not implicitly change `enabled` or `staff_only`; those are separate,
  explicit desired-state mutations.
- Expose metadata updates as explicit desired state, not “toggle” commands. An
  idempotent `enabled: true|false` or `staff_only: true|false` request avoids
  stale-read inversion and is extensible to another client. The canonical
  `_metadata.update_metadata` service already has this shape.
- Preserve source capability and immutability rules server-side. UI capability
  metadata may drive affordances, but hiding a button is advisory. Default
  scenarios remain code-managed, ACES entries remain read-only provenance, and
  only custom database scenarios support content update and soft delete.
- Keep availability, audience, authoring permission, validity, and launch
  readiness separate. `enabled`, `staff_only`, `can_edit_cms_authoring`,
  validation results, and `launchable` answer different questions and must not
  be collapsed into a single “status” or “published” boolean.
- Field-linked validation must be a typed server projection of authoritative
  YAML/Pydantic diagnostics, using structured locations and safe messages in
  the shared API error/domain-result shapes. React must not parse today's flat
  error strings, duplicate Pydantic rules, or create a feature-local exception
  hierarchy.
- Use an optimistic revision seam for content writes before adding autosave or
  long-lived drafts. `Scenario.updated_at` is the existing minimum revision
  candidate: an expected revision can reject stale updates with a canonical
  conflict response. Without conflict handling, keep saves explicit and warn
  about unsaved navigation rather than silently overwriting cached edits.
- Preserve server-side export through the scenario-editor service, but repair
  its current hard-coded projection before claiming lossless export. If the
  shared JSON client needs a download/raw-response extension, add it once at
  the transport boundary; do not serialize YAML in React or add a feature-local
  fetch client that calls a legacy export route.
- Preserve one audit event per successful service mutation. DRF and React must
  not add a second audit path. Operational logs carry request ids and sanitized
  identifiers, never scenario definitions or YAML bodies.
- Preserve rollout and rollback. Scenario Editor SPA route ownership requires
  the platform master flag plus a dedicated, default-off, non-secret server
  flag evaluated per request and surfaced through typed bootstrap state. Legacy
  Django routes remain the fallback until a later rollout issue explicitly
  retires them.
- Route takeover must distinguish pages from unsafe legacy actions. A SPA
  catch-all must not swallow legacy POST/validation/export/action URLs or change
  methods accidentally. Flag-off behavior must preserve the complete legacy
  surface; flag-on routing needs an explicit compatibility decision for each
  same-path GET/POST legacy route.

## Scenario Concepts And Capabilities

These concepts are deliberately independent. The server remains authoritative
for the capability decision.

| Concept | Meaning | Must not be treated as |
| --- | --- | --- |
| `scenario_type` | Domain schema/workflow discriminator recognized by broader registry/hydration code | Persistence source, edit permission, or proof that #1371 authors that type |
| custom `Scenario` row | User-authored, database-backed content aggregate | A catalog projection or runtime instance |
| built-in YAML entry / `is_default` | Repository-managed scenario content | A custom scenario that may be overwritten or deleted |
| ACES catalog entry | Read-only package provenance and catalog presentation | A YAML/custom scenario that can be edited, cloned, exported, or deleted |
| `enabled` | Availability overlay stored in `ScenarioMetadata` | Validation, launch readiness, or a new publication workflow |
| `staff_only` | Audience visibility overlay | CMS authoring permission |
| `launchable` | Server-derived technical readiness for a workflow | Visibility, validity, or authoring capability |
| `InstanceConfig` / `SubnetConfig` / `DCConfig` | Nested template-definition contracts | Runtime `cms.models.Instance`, `Subnet`, or `App` records |

Source capability baseline:

| Source | Read/catalog | Content create/edit | Clone/export | Delete | Availability/audience |
| --- | --- | --- | --- | --- | --- |
| Built-in YAML | Yes | No | Existing clone/export semantics only | No | Yes, metadata overlay |
| Custom database `Scenario` | Yes | Yes | Yes | Soft delete | Yes, metadata overlay |
| ACES package | Read-only provenance | No | No | No | Yes, metadata overlay |

Do not infer these capabilities from `scenario_type` or from client-side route
selection. If the API presents action capabilities, derive them from the same
registry/source policy that the mutation service enforces.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1371 |
| --- | --- | --- |
| SPA architecture | ADR-029; `frontend/src/router.tsx`; `frontend/src/api/client.ts`; `frontend/src/api/queryClient.ts` | One router, one query client, one typed fetch transport, generated API types, `/api/v1/` only. |
| Shell and IA | ADR-013; `frontend/src/app/nav.ts`; `frontend/src/components/app-shell.tsx`; UX-003; `docs/design/spa-cohesive-ux-1368.md` | Register the Author surface in the shared route/nav contract; do not fork the shell or taxonomy. |
| Design/accessibility | `frontend/src/index.css`; `frontend/src/components/ui/*`; `frontend/src/app/state-map.ts`; `frontend/src/components/page-header.tsx` | Reuse Apple-dark Tailwind v4, shadcn/ui, logo/favicon, state intents, focus management, forms, alerts, skeletons, and `AlertDialog`. |
| API mount/schema | `config/api_urls.py`; `cms/api/urls.py`; drf-spectacular; `frontend/src/api/schema.d.ts` | Extend canonical CMS v1 routes and regenerate types. No ad hoc JSON routes or manually maintained DTOs. |
| API auth/actor/scopes | `config/_drf_settings.py`; `cms/api/permissions.py`; `shared/api/permissions.py`; `shared/api_tokens/*`; `shared.auth` | Keep fail-closed bearer handling, session/CSRF, exact CMS read/write scopes, actor resolution, and active staff/Threat Research checks. |
| Scenario service boundary | `cms/scenario_editor/services.py`; `_crud.py`; `_metadata.py`; `_persistence.py`; `_validation.py`; `_yaml.py` | Call the public facade and extend it only when a missing use case cannot be expressed; do not move workflows into DRF or React. |
| Domain schema | `cms/scenarios/schema.py`; `Scenario.to_template()` | Pydantic owns structural and cross-field validation. Serializer/client constraints may mirror it only with drift tests. |
| Catalog/source policy | `cms/scenarios/registry.py`; `cms/scenarios/catalog_presentation.py` | Preserve source resolution, metadata overlay, staff-review projection, ACES allowlisting, and launchability separation. |
| Persistence | `cms/models/scenarios.py`; `shared/db/soft_delete.py`; `transaction.atomic`; `unique_active_scenario_id` | Preserve active-only reads, partial uniqueness, actor/timestamp fields, model validation, metadata overlay, and soft delete. |
| Errors | `shared/api/errors.py`; `shared/errors.py`; `frontend/src/api/errors.ts`; `frontend/src/api/client.ts`; `ScenarioEditorError` | Use shared envelopes and safe public messages. Add structured validation details, not another exception family or string parser. |
| Logging/audit | `config/middleware.py` request-id middleware; `config/_logging_config.py`; `shared/log_sanitize.py`; `audit_scenario_change` | Correlate with request ids, sanitize user-controlled ids, and audit once from services without definition/YAML content. |
| Rollout/static host | `config/settings.py`; `config/_env_manifest.py`; `config/env-manifest.json`; `shared/spa_host.py`; `shared/spa.py`; platform SPA bootstrap | Default-off per-surface server flag, legacy fallback, public non-secret Vite bundle, WhiteNoise manifest. No build-time rollout state. |
| Browser policy | `config/_browser_security.py`; Django middleware ordering; `templates/spa/platform.html` | Same-origin, nonce-free external bundle, no unsafe inline/eval, no new CORS or second origin. |
| Tests/gates | `tests/cms/api/*`; `tests/scenario_editor/*`; `uat/SCENARIO_EDITOR_TEST_PLAN.md`; frontend Vitest/axe/Playwright; `.importlinter`; ADR guard | Test HTTP, service, schema, route rollback, accessibility, and browser workflows at their owning layers. |

## Cross-Cutting Layers The Design Must Pass

- Authentication surface: the SPA page starts after a Django session exists.
  `/api/v1/cms/` retains the global `ApiTokenAuthentication`-first and
  `SessionAuthentication`-second order. A supplied malformed, revoked, expired,
  or wrong-prefix bearer token fails closed and never falls through to a valid
  browser session.
- Authorization surface: `IsAuthenticatedSessionOrApiToken`, exact
  `cms:authoring:read`/`cms:authoring:write` scopes, `HasCMSAuthoringActor`,
  `can_edit_cms_authoring`, and service-level
  `validate_cms_authoring_user` all remain in the path. A token scope is not CMS
  membership, and bootstrap/nav capability is not authorization.
- Account-boundary surface: `CTFAccountBoundaryMiddleware` continues to reject
  temporary participant accounts outside their allowed CTF surface before CMS
  behavior executes. Scenario routes and APIs must not bypass it.
- CSRF/cookie surface: unsafe browser calls use same-origin cookies and
  `X-CSRFToken` through the shared SPA client, Django `CsrfViewMiddleware`, and
  DRF session authentication. Do not add `csrf_exempt`, a CSRF-exempt session
  authenticator, browser bearer tokens, or token persistence.
- Request/shape surface: DRF serializers own path/query/body and response
  shapes. Apply the repository's existing CMS HTTP validation and shared error
  conventions consistently; do not pass an unvalidated request dict to
  services. Generated OpenAPI types are a client convenience, never a runtime
  trust boundary.
- Domain-validation surface: `validate_scenario_id`, `yaml.safe_load`,
  editor-owned `ScenarioTemplate`, its cross-field checks,
  `Scenario.to_template()` hydration, and model constraints remain
  authoritative. The wider `AnyScenarioTemplate` hydration union does not
  broaden the editor contract. Client checks may improve feedback but cannot
  replace any server gate.
- Source/policy surface: the registry resolves built-in, database, and ACES
  sources; the service enforces default/ACES immutability and custom-scenario
  mutations. API capability data and UI actions must agree with that policy.
- Persistence surface: custom content uses `Scenario` inside the existing
  atomic persistence functions, active-row uniqueness, actor fields, model
  validation, and soft delete. `ScenarioMetadata` remains the source-neutral
  availability/audience overlay; no browser persistence or parallel draft table
  is introduced.
- Error-envelope surface: canonical API failures use
  `{"error":{"code","message","details?","request_id?"}}`; domain YAML
  validation may use a typed `valid: false` result. Field diagnostics must have
  stable locations/codes and safe messages. Never return raw YAML parser,
  Pydantic internals, stack traces, SQL errors, file paths, or arbitrary
  exception text.
- Secret/content-handling surface: session and CSRF cookies, bearer tokens,
  future scenario credentials/flags, full definitions, YAML bodies, internal
  hostnames, provider payloads, and ACES raw SDL/content must not enter static
  bundles, localStorage/sessionStorage, URL/query fragments, process argv,
  logs, audit payloads, schema examples, snapshots, screenshots, or CI output.
  React renders names/descriptions/errors as text; no `dangerouslySetInnerHTML`
  or unsanitized Markdown.
- Parser/resource surface: `yaml.safe_load` avoids arbitrary constructors, but
  client validation is not a parser security boundary. If payload size,
  collection bounds, duplicate-key rejection, or alias/merge policy is
  hardened, define it once in the canonical server parser/schema and apply it
  to both legacy and v1 callers with parity tests. A frontend-only limit is not
  sufficient. Do not log the raw `YAMLError`; log a safe category and bounded
  location because the exception rendering can include YAML input context.
- Logging/observability surface: `X-Request-ID` flows through the shared client
  and `RequestIDMiddleware`; ECS logging and `safe_log_value`/`safe_log_id`
  handle correlation and redaction. Log actor/action/safe identifiers and
  outcomes, not request bodies or definitions. Do not claim service audit is
  transactional or request-context-rich unless that behavior is explicitly
  changed and tested.
- Audit surface: successful create/update/clone/delete/metadata operations use
  `audit_scenario_change` and the shared audit vocabulary/port once. Validation
  failures and presentation reads do not create a competing SPA/DRF audit
  vocabulary.
- Config/env surface: the dedicated rollout flag is a non-secret Django runtime
  setting, default false, exposed as typed bootstrap state. Because helper-based
  `_env_bool(name, ...)` calls are not automatically visible to the AST manifest
  collector, a new binding must be represented by the canonical
  `_env_manifest.py` mechanism and `env-manifest.json`, with settings/bootstrap/
  route tests. Do not use `VITE_*` for rollout state.
- Deployment/runtime surface: if operators must set the flag in deployed
  environments, thread that same non-secret name through the canonical AWS
  `scripts/portal-deploy/deploy_portal.sh` container environment and/or GCP
  `scripts/gcp/render_runtime_env.py` plus ConfigMap overlay as applicable. It
  does not belong in Secret Manager and must not be embedded at Vite build time.
- Browser/static surface: `shared.spa_host`, `shared.spa`,
  `templates/spa/platform.html`, Vite, staticfiles, and WhiteNoise serve a public
  bundle under the existing CSP candidate. No inline script/style, eval, new
  external origin, CORS relaxation, or user-specific bundle content.
- OS/process surface: this workspace is in-process browser/DRF/Pydantic/ORM
  work. It should add no subprocess, shell, temp-file, provider CLI, background
  worker, or secret-bearing argv/env handoff. Export remains an HTTP response,
  not a server-side temp-file command.
- Import/layer surface: CMS uses its public service facade and `shared`
  contracts. Only `shared` may import `cyberscript` directly; do not add direct
  frontend/CMS imports, cross-app private imports, or a second contract package.
- Accessibility/i18n surface: list/detail/editor/confirmation states meet WCAG
  2.1 AA: keyboard reachability, visible focus, labels/descriptions, error
  association and summary, non-color status meaning, focus restoration,
  accessible dialogs, and a keyboard-safe code editor with a way to move focus.
  SPA strings must follow the platform's eventual shared extraction path; do
  not misuse Django template translation as a React runtime abstraction.

## Extensibility Seams

- Capability seam: present a server-derived source/capability projection keyed
  by stable scenario id and source kind. The next source or authoring capability
  should add one policy mapping and tests, not client conditionals based on
  `scenario_type`, `is_default`, or route names.
- Definition seam: structured fields, YAML, clone, export, and future schema
  variants all consume one lossless structural-definition contract plus an
  explicit identity/metadata reset policy. A new Pydantic field must not require
  edits to several hard-coded allowlists merely to survive a round trip.
- Validation seam: expose ordered diagnostics with a stable code, location path,
  and safe message, parameterized by representation (`structured` or `yaml`). A
  future editor widget can bind the same diagnostic without parsing prose.
- Concurrency seam: content writes carry an expected revision derived from
  `updated_at` (or a later reviewed opaque revision). A future autosave or
  collaborative editor can build on conflict detection without replacing the
  persistence contract.
- Metadata seam: one explicit metadata update shape accepts optional desired
  `enabled` and `staff_only` values. A future visibility attribute extends that
  shape and service policy instead of adding another read-invert-write action.
- Catalog seam: keep filtering, ordering, and pagination as query parameters on
  the canonical catalog read. If standard pagination is introduced, use the
  configured DRF pagination contract with an explicit v1 compatibility decision
  rather than inventing a Scenario-only response envelope.
- Rollout seam: route prefix, dedicated flag, legacy fallback, SPA host, nav
  metadata, bootstrap feature flag, and client route are the shared takeover
  parameters. Later Scenario subroutes or legacy retirement extend that data,
  not another host or router.
- Transport seam: extend the shared client once for a typed JSON request or a
  server file response. New editor operations must not create per-feature
  authentication, retry, error, or download transports. Unsafe mutations are
  never auto-retried.

## Whole-Repo Scope

#1371 implementation must evaluate these surfaces together:

- Architecture/design: ADR-013, ADR-016, ADR-029,
  `docs/design/spa-cohesive-ux-1368.md`, UX-003,
  `docs/architecture/spa-cutover-architecture-1300.md`, the shell and CMS API
  preflights, the ACES read-only presentation preflight, clone-definition
  preflight, and this note.
- Frontend: `shifter/shifter_platform/frontend/package.json`, `vite.config.ts`,
  `src/router.tsx`, `src/api/*`, `src/app/*`, `src/components/*`, and the new
  Scenario Editor feature folder.
- Django shell/config: `config/urls.py`, `config/api_urls.py`,
  `config/settings.py`, `config/_env_manifest.py`, `config/env-manifest.json`,
  `config/_drf_settings.py`, `config/_browser_security.py`, middleware,
  `shared/spa.py`, `shared/spa_host.py`, and bootstrap serializers.
- CMS API and domain: `cms/api/*`, `cms/scenario_editor/*`,
  `cms/scenarios/schema.py`, `cms/scenarios/registry.py`,
  `cms/scenarios/catalog_presentation.py`, `cms/models/scenarios.py`, and the
  public CMS service imports used by callers.
- Shared concerns: `shared/auth.py`, `shared/api/*`, `shared/api_tokens/*`,
  `shared/db/soft_delete.py`, `shared/errors.py`, `shared/exceptions.py`,
  `shared/log_sanitize.py`, audit vocabulary/ports, and request-id handling.
- Legacy compatibility: `cms/scenario_editor/urls.py`, views, form helpers,
  templates, static JavaScript/CSS, and `uat/SCENARIO_EDITOR_TEST_PLAN.md` as
  behavior/rollback evidence only, never SPA data contracts or schema sources.
- Runtime/deployment when the flag is operable there:
  `scripts/portal-deploy/deploy_portal.sh`, `scripts/gcp/render_runtime_env.py`,
  GCP runtime env tests, and `platform/k8s/gcp` ConfigMap overlays. No secret
  surface should change for a boolean rollout flag.
- Enforcement/workflows if touched: `.github/workflows/**`, `.importlinter`,
  `scripts/adr_guard/**`, frontend ESLint/Vitest/Playwright config, root/frontend
  package scripts, and documentation coverage manifests.

## Verification Guardrails For The Later Implementation

- Backend coverage must prove session and token authorization, exact read/write
  scopes, inactive/regular users, malformed bearer fail-closed behavior, CSRF,
  shared envelopes/status codes, structured diagnostics, source capability and
  immutability, explicit metadata desired state, soft delete, and stale-write
  behavior if the revision seam is implemented.
- Routing coverage must prove both platform and Scenario Editor flags are
  required, flag-off legacy behavior, flag-on page/deep-link ownership,
  anonymous login flow, permission denial, and exclusion or intentional handling
  of every legacy unsafe/action route.
- Frontend coverage must include browse, create, structured edit, YAML validate,
  explicit save/availability, destructive confirmation, loading, empty,
  filtered-empty, validation, permission, server error, conflict/unsaved-change,
  and rollback paths. Use Vitest plus accessibility checks and Playwright for the
  critical browser flows.
- OpenAPI generation must be reproducible and drift-tested against Pydantic
  field/choice ownership where response serializers mirror the domain schema.
  Do not satisfy type checking with parallel manual DTOs.
- Note the current gate gap explicitly: the frontend package has a Playwright
  command, but the shared SPA quality job does not currently execute it. If
  #1371 claims browser-flow CI coverage, wire it through the canonical workflow
  and update the ADR enforcement documentation rather than treating a local run
  as a permanent gate.
- Run targeted Django/service/API tests, frontend lint/typecheck/Vitest/build
  and Playwright as applicable, import-layer checks, and the required ADR guard.
  Workflow changes also require `actionlint`; architecture-enforcement changes
  require matching ADR registry/enforcement updates.

## Gotchas And Anti-Patterns

- Do not redesign the locked Apple-dark Tailwind v4 plus shadcn/ui theme, logo,
  favicon, typography, or state/color language.
- Do not build a Scenario-only shell, navigation model, fetch wrapper, query
  cache, DTO package, error envelope, exception hierarchy, status enum, audit
  vocabulary, validation engine, or workflow state machine.
- Do not call legacy `/scenario-editor/...` JSON, form POST, validation, or
  export routes from SPA data code. Missing v1 coverage is an explicit API gap.
- Do not conflate catalog entries with mutable `Scenario` rows; source with
  `scenario_type`; `enabled` with validity or launchability; `staff_only` with
  authoring permission; or nested template configs with runtime models.
- Do not make built-in YAML or ACES content editable, and do not infer editability
  from a field that the client can manipulate.
- Do not copy the legacy role/OS option lists or form reconstruction. They
  already drift from the Pydantic schema and can reject or drop valid structure.
- Do not parse flat validation prose in React. Do not expose raw Pydantic/YAML
  internals merely to make it field-linked.
- Do not reconstruct, clone, or export YAML in the browser. Do not silently
  remove unknown/future definition fields during a structured edit. Do not
  assume the current server export/YAML form helpers are lossless merely because
  they are server-side; their fixed three-field projection is a known gap.
- Do not implement read-then-toggle mutations, silent autosave, unguarded
  last-write-wins, or automatic retry of create/edit/delete/metadata mutations.
- Do not add localStorage/sessionStorage drafts containing definitions. Browser
  memory plus an unsaved-change guard is the initial boundary unless durable
  drafts receive a separately reviewed contract.
- Do not log, audit, snapshot, render as HTML/Markdown, or place in URL/argv the
  YAML body, full definition, future credentials/flags, raw ACES content,
  cookies, CSRF values, bearer tokens, or exception traces.
- Do not add `csrf_exempt`, CORS, another origin, inline scripts, `eval`, or
  `dangerouslySetInnerHTML` to make the editor work.
- Do not weaken or bypass service validation, model validation, registry source
  policy, soft-delete managers, API scopes, actor validation, CSP, generated
  schema, import-linter, ADR guard, or frontend quality checks.
- Do not remove or redirect away legacy Django behavior in #1371. Retirement is
  a later, explicitly authorized rollout decision.

## Non-Goals And Implementation Boundaries

- No implementation is included in this preflight.
- No new visual language, branding, shell, information architecture, router,
  auth mechanism, token format, exception family, persistence abstraction, or
  scenario workflow state machine.
- No new draft/review/publication model. “Publish” uses the existing explicit
  availability metadata unless a future issue deliberately changes the domain.
- No redesign of CMS authoring roles, API-token scopes, scenario source
  precedence, ACES ingestion, CTF schema or authoring, launch workflows, runtime
  range models, audit storage, or soft-delete semantics.
- No legacy route/template deletion, URL retirement, data migration, or default
  scenario write support.
- No provider, Terraform, Kubernetes, worker, object-storage, terminal, or
  Guacamole changes beyond propagating a non-secret runtime rollout flag through
  an already applicable canonical deployment surface.
- No broad API-consolidation work beyond the `/api/v1/` Scenario Editor
  operations required for #1371. Gaps outside that shipping contract remain in
  their tracking issues.
- No claim that SPA internationalization, parser resource hardening, catalog
  pagination, optimistic concurrency, or Playwright CI is already solved. Where
  #1371 depends on one, close the smallest canonical gap or document the bounded
  limitation without inventing a feature-local substitute.
