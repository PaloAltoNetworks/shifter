# SPA Verification Gates Preflight (#1526)

Status: pre-implementation guidance; coverage/LCOV and authenticated functional
E2E enforcement are already present, the browser accessibility gate is not,
and two acceptance-criteria conflicts require issue clarification before the
issue can be declared complete

Date: 2026-09-07

Issue: GitHub #1526, "REV1 Frontend: enforce SPA coverage, E2E, and browser
accessibility gates"

This is a requirement-free maintenance issue. The issue is the shipping
contract. This note fixes the current-repository boundaries and records two
places where that contract now conflicts with accepted architecture. It is not
an implementation plan.

## Decision and contract conflicts

No new application ADR, API, schema, service, repository, persistence model, or
exception hierarchy is warranted. The work belongs to the existing frontend
package and repository quality gates. ADR-029 owns the SPA boundary, ADR-040
owns its generated API contract, ADR-045 owns Risk Register removal, ADR-055
owns accessibility enforcement, and the #1529 testing preflight owns absolute
and changed-code coverage policy.

Two issue clauses cannot be implemented literally against the current tree:

1. The create/edit/archive/restore/comments/history flow was the former Risk
   Register workflow. ADR-045 requires that product, including its routes,
   comment model, API, permissions, frontend modules, and compatibility aliases,
   remain removed. The maintained SPA has no comments domain. Workspace
   lifecycle now provides create/rename/archive/restore, and shared audit
   provides read-only history, but they are separate domain contracts and are
   not a valid silent substitute for a Risk Register comments workflow. The
   issue must explicitly remove the retired flow or name maintained replacement
   journeys before this criterion can be claimed.
2. The issue requests retained authenticated Playwright traces. ADR-055 forbids
   authenticated traces, cookies, storage state, request/response bodies, and
   signed URLs from public artifacts. This public-repository workflow has no
   incumbent restricted evidence store. A public `upload-artifact` trace is
   therefore forbidden even when all users and records are synthetic. The issue
   must accept bounded privacy-safe diagnostics instead, or name an approved
   access-controlled retention boundary before retained authenticated traces
   can be claimed.

Do not code around either conflict. In particular, do not resurrect Risk
Register under another name and do not weaken the artifact rule because test
credentials are synthetic. The remaining browser-axe gate is architecturally
viable under the decisions below.

## Coverage boundary

The current preflight run on 2026-09-06 passed 533 Vitest tests in 88 files and
measured 80.77% statements, 71.85% branches, 75.26% functions, and 82.25%
lines. The generated LCOV includes `main.tsx`, `router.tsx`, `RootLayout.tsx`,
`bootstrap-context.tsx`, `api/bootstrap.ts`, `api/queryClient.ts`, and
`state-map.ts`; focused tests for their main composition, authorization,
bootstrap, error, and retry policies are now present. These figures confirm the
current absolute gate, but they do not replace the risk-behavior contract below
or become durable policy values in this note.

`frontend/vite.config.ts` remains the sole owner of the SPA's measured source
universe and absolute thresholds. Measure owned executable `src/**/*.ts(x)`;
exclude tests, test support, and the generated `api/schema.d.ts`, but do not
exclude a first-party entrypoint or composition root merely because it is
awkward to unit test. Set statement, branch, function, and line floors against
the final corrected baseline using the one-point buffer already established in
`docs/dev/testing.md`. Thresholds may only stay level or rise. Do not enable a
tool mode that silently rewrites them.

The numeric package floor and risk coverage are complementary. Explicit tests
must cover router construction/deep links/not-found behavior, bootstrap loading,
401 redirect, bounded non-auth failure and recovery, route authorization,
query retry policy, and representative mutation failure/retry-by-user behavior.
A high aggregate percentage cannot substitute for those behaviors, and a list
of critical files must not become a second route or application schema.

SonarCloud remains the single changed-code authority. The existing path-routed
SPA job already publishes LCOV with `if-no-files-found: error`; the existing
`sonarcloud` job restores it, `sonar.javascript.lcov.reportPaths` includes it,
and the SPA is no longer coverage-excluded. Preserve that one path. The
server-side `raes-strict` gate enforces 80% new-code coverage and PR analysis
uses full history and waits for the quality gate. A missing LCOV artifact or a
failed SPA producer must continue to fail the scan prerequisite; do not add a
second diff-coverage script or parse terminal output.

## Test ownership and boundaries

- Vitest owns deterministic component, hook, client, router, and composition
  tests. Reuse `src/test/setup.ts`, `src/test/utils.tsx`, Testing Library,
  `vitest-axe`, the real TanStack Query policy, and the existing convention of
  mocking only `apiFetch` at the HTTP boundary. Test retry and recovery through
  user-visible behavior; do not duplicate backend validation in TypeScript.
- Django API and service tests continue to own serializer validation,
  authorization, transactions, row locks, audit atomicity, and persistence
  semantics. Browser coverage complements these tests; it does not replace or
  re-express them.
- Playwright remains the only browser runner. Extend the authenticated harness
  in `playwright.config.ts`, `e2e/auth.setup.ts`, `e2e/support/actors.ts`, and
  the existing journey specs; do not create another server, login, actor, or
  browser-fixture stack. Browser tests use the actual Django-hosted built SPA,
  normal same-origin session/CSRF behavior, canonical API endpoints,
  deterministic synthetic actors, and a fresh job-local database. Mutations
  travel through the UI and normal API/service boundaries.
- Accessibility uses ADR-055's single surface/state matrix and
  `@axe-core/playwright` ruleset. Component axe remains fast feedback and does
  not prove color contrast. A page identity/readiness assertion precedes every
  browser scan; redirects, denied/error pages when not expected, zero executed
  rules, scanner exceptions, and unexpected `incomplete` results fail.
- Functional scenarios and accessibility states may share actor/data fixtures
  and the Playwright config, but they remain distinct evidence. Do not encode a
  business workflow in the accessibility inventory or call an axe pass an E2E
  functional assertion.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required boundary |
| --- | --- | --- |
| Frontend package | `frontend/package.json`, lockfile, `vite.config.ts`, `playwright.config.ts`, `eslint.config.js` | One package, lock, coverage config, and browser runner; clean installs use `npm ci`. |
| SPA composition | `src/main.tsx`, `src/router.tsx`, `app/RootLayout.tsx`, `app/bootstrap-context.tsx`, `api/queryClient.ts` | Test the real composition and derive route coverage from the route objects; no copied route registry. |
| API and errors | `src/api/client.ts`, `csrf.ts`, `errors.ts`, generated `schema.d.ts`, and aliases in `types.ts` | Preserve same-origin session credentials, CSRF, request IDs, the shared error envelope, and generated wire types. |
| UI state | `components/ui/*`, `components/confirm-dialog.tsx`, `app/state-map.ts`, existing page tests | Reuse loading, alert, form, confirmation, focus, and status patterns; no page-local test-only variants. |
| Server contracts | DRF serializers/permissions, domain service facades, `shared.api.errors`, `shared.audit`, `shared.log_sanitize` | Seed preconditions through valid fixtures/services and exercise normal endpoints; backend policy remains authoritative. |
| Auth/session | `config.dev_auth`, `workspaces.management.commands.seed_e2e`, `e2e/auth.setup.ts`, and `e2e/support/actors.ts`; normal Django session/CSRF middleware, `config.api_bootstrap`, `shared.api.permissions`, and domain authorization | Reuse the current hermetic actor/session setup. Dev auth stays loopback/job-local and cannot mint authority by itself; actor roles are deterministic setup state and endpoints reauthorize. |
| Production-shaped host | `shared.spa_host`, Django/WhiteNoise build, `Makefile::test-platform-e2e`, `_quality.yml::shifter-platform-e2e`, and `scripts/stack-smoke`'s real OIDC/session harness | Extend the existing job-local Django host for PR evidence; keep the deployed OIDC harness as a distinct later execution tier. Do not introduce a Vite-only fake application server or another auth stack. |
| CI routing | `deploy.yml` `PR Gate`, `_quality.yml`, `.github/quality-path-filters.yaml`, `scripts/quality_ownership` | Functional/coverage work follows existing ownership; ADR-055's every-PR accessibility job is a direct `PR Gate` dependency, not a second path router. |
| Analysis | `sonar-project.properties`, SPA LCOV, `raes-strict` SonarCloud gate | One 80% changed-code authority plus package-local absolute floors; missing reports fail closed. |
| Accessibility policy | ADR-055, `docs/adr/exceptions.yaml`, central `adr_guard` exception filtering | One exact-finding baseline and waiver policy; no rule disables, count threshold, or JavaScript waiver parser. |

## Cross-cutting layers the design must pass

| Layer | Required behavior |
| --- | --- |
| Runtime/test config | Start the Django stack with the existing `TESTING`, `ENVIRONMENT`, `TEST_DB_BACKEND`, `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, host, database, channel, and static-file shapes. `config._runtime_env`, `_database_settings`, `_browser_security`, `_channels`, and the env manifest remain authoritative. Test-runner selectors are not new application settings. |
| Authentication and authorization | Use synthetic anonymous, ordinary, authoring, CTF participant/organizer, staff, and denied actors as required by the registered state. `dev_login` may establish a hermetic session only under its existing development and peer gates; it must not become a production bypass or manufacture staff/threat-research authority. `RootLayout` route handles are advisory. DRF permission classes, CTF account middleware, and domain services remain authoritative, including on direct/deep-linked navigation. |
| CSRF, host, origin, and CSP | Keep Django session authentication, CSRF cookie/header validation, `ALLOWED_HOSTS`, browser-policy middleware, same-origin fetches, and WebSocket origin checks enabled. Playwright or axe injection is not permission to add `csrf_exempt`, widen trusted origins/hosts, disable secure policy, or run against an arbitrary remote URL. |
| Input and schema validation | Browser mutations use the generated OpenAPI projection, DRF serializers, and domain service validators. Fixture setup may create valid prerequisites through existing factories/services/models, but must not bypass database constraints to reproduce an application state or copy enums/DTOs into the test matrix. |
| Persistence and cleanup | Use a fresh job-local database and temporary media/static state, migrate once, use stable per-scenario identifiers, and tear down on success, failure, and cancellation while preserving the original exit status. Never reuse a developer or deployed database. Parallel mutation tests require isolated actors/data or deliberate serialization. |
| Secrets and OS exposure | PR tests need no cloud or deployed IdP credential. Session cookies, CSRF values, reset/invite tokens, auth codes, signed URLs, and secret values stay out of argv, process listings, shell tracing, cache keys, `GITHUB_OUTPUT`, logs, screenshots, and public artifacts. URL-validation failures must describe the violated rule without echoing the raw configured URL, which may itself contain rejected credentials. If a helper must cross a process boundary, use memory/stdin or a mode-0600 temporary file and pass only its path. |
| Error envelopes | Preserve `{error: {code, message, details?, request_id?}}` through `shared.api.errors` and `frontend/src/api/errors.ts`. Assert the intended page/state before functional or axe checks. Do not swallow a 401/403/5xx, malformed JSON, timeout, scanner failure, or fallback page and report success; add no test exception family. |
| Logging and observability | Reuse `X-Request-ID`, bounded GitHub diagnostics, test reports, LCOV, and privacy-safe axe fingerprints. Application logs remain sanitized through `shared.log_sanitize`; tests add no runtime telemetry or audit store. Never dump the environment, DOM, response bodies, cookie jar, or raw trace. |
| Workflow policy | Hosted PR jobs use `contents: read`, no `id-token: write`, no protected environment or cloud secrets, no `pull_request_target`, and fully pinned actions. Preserve `if-no-files-found: error`, quality-ownership self-routing, `actionlint`, the Sonar wait, and ADR guard. |

## Extensibility seam

The primary seam is one package-owned Playwright fixture/matrix model:
stable scenario or surface/state id, canonical route reference, actor fixture,
deterministic state setup, readiness assertion, viewport/browser/theme, and
execution tier. Adding a maintained route, role, responsive state, or deployed
profile extends that data and its owning fixture; it does not add a runner,
route schema, auth mechanism, workflow router, or waiver store.

Keep coverage thresholds and include/exclude patterns in `vite.config.ts`, and
keep browser project/ruleset/base-target policy in `playwright.config.ts` plus
the closed execution profile. `SPA_E2E_BASE_URL` must be parsed by that profile:
PR mode admits loopback/same-origin only; any later deployed mode selects a
closed allowlisted environment and rejects credentials, fragments,
cross-origin redirects, and unsupported schemes.

## Whole-repository scope

The quality design passes through the frontend package/config/tests and its
existing authenticated actor fixtures, Django SPA host and security/auth
settings, `workspaces.management.commands.seed_e2e`, existing test-data/service
seams, `scripts/stack-smoke`, `_quality.yml`, `deploy.yml`, the quality path
contract, Sonar configuration, ADR-055's surface/baseline policy, the central
exception registry, contributor testing documentation, and the required
architecture checks. Application serializers, services, repositories, models,
migrations, and runtime logging are incumbents to exercise, not normal change
targets.

## Gotchas and anti-patterns

- Do not restore or alias Risk Register, add a generic comments abstraction, or
  relabel unrelated workspace/audit behavior as the retired acceptance flow.
- The `/risks/` strings retained as arbitrary request paths in
  `src/api/client.test.ts` test the generic HTTP client only. They are not a
  route, schema, fixture contract, or evidence that the removed feature exists;
  do not use them to resolve the issue ambiguity.
- Do not upload authenticated Playwright traces, storage state, screenshots,
  raw axe JSON/HTML, or response bodies to public Actions artifacts.
- Do not enforce coverage by parsing console text, add a second diff calculator,
  hide code with exclusions, lower a floor, or let aggregate coverage mask the
  required composition/auth/failure behaviors.
- Do not use Vite mocks or network interception for end-to-end assertions; do
  not use a Playwright login shortcut that bypasses Django session creation.
- Do not echo the raw `SPA_E2E_BASE_URL` in configuration errors; rejecting an
  embedded credential does not make that credential safe to print in CI logs.
- Do not duplicate routes, OpenAPI DTOs, enums, validation, authorization,
  mutation retry policy, error envelopes, logging sanitization, audit events,
  or workflow path logic in test support.
- Do not treat hidden controls or a client route denial as proof of backend
  authorization, and do not auto-retry unsafe mutations.
- Do not treat jsdom axe, browser axe, or a numeric score as WCAG conformance.
  Preserve the manual-audit and exact-finding rules from ADR-055.
- Do not let fixture/setup/auth failures, redirected login pages, empty mounts,
  stale records, scanner errors, or zero-rule runs become green tests.

## Non-goals and implementation boundary

- No Risk Register restoration, comments feature, or replacement product.
- No application feature, API/DTO/schema change, serializer/service refactor,
  database migration, runtime feature flag, exception hierarchy, logging sink,
  telemetry pipeline, or audit persistence change for the gate.
- No replacement of React, Vite, Vitest, Playwright, Testing Library,
  TanStack Query, axe, Django/WhiteNoise, SonarCloud, or the canonical CI router.
- No live cloud/IdP/range dependency in the blocking PR lane and no claim that
  hermetic browser evidence proves deployed Cognito, Guacamole, CTFd, or a live
  range.
- No WCAG conformance claim from automation and no expansion of #1526 into the
  full manual-audit/release program beyond preserving ADR-055's boundary.
