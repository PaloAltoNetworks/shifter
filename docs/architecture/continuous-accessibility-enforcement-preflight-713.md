# Continuous Accessibility Enforcement Preflight (#713)

Status: accepted architecture decision; enforcement implementation is a
follow-up

Date: 2026-09-06

Requirements: UX-010, UX-050

Issue: GitHub #713, "ADR: continuous accessibility enforcement"

This decision defines continuous accessibility governance. It does not add the
browser gate, remediate a page, perform the initial audit, or make a WCAG
conformance claim.

The accepted decision is ADR-055 in `docs/adr/index.yaml`. Its closed
`accessibility-enforcement/v1` interface contract is validated by
`adr-registry`; that structural check prevents the architecture contract from
silently weakening, but it does not claim that the browser, audit, or release
gates have shipped. [Issue #1526](https://github.com/Brad-Edwards/shifter/issues/1526)
owns that follow-up implementation.

## Boundary and conformance meaning

The target is WCAG 2.2 Level AA. A conforming page must satisfy every Level A
and Level AA success criterion, and a complete user process cannot be declared
conforming when one of its pages or states fails. Automated tools cover only a
subset of those criteria. A passing automated scan is therefore regression
evidence, not a WCAG conformance verdict.

The governed surface is every human-facing web page or view Shifter ships or
relies on in a supported user journey:

- the Django-hosted React SPA and its anonymous, authenticated, denied, empty,
  error, dialog, and workflow states;
- retained Django HTML, including platform and CTF authentication, password
  reset, workspace invitation acceptance, privacy, and Django administration;
- the public MkDocs site selected by ADR-038; and
- deployment-managed third-party web UI, currently Guacamole and the optional
  standalone CTFd board, when an enabled deployment profile makes that UI part
  of a supported journey.

APIs, WebSockets, health/CSP-report endpoints, email bodies, CLI/TUI output,
internal design pages excluded from MkDocs, and content inside a scenario guest
are not web-page conformance targets under this ADR. Their own accessibility
requirements remain possible. Operator-authored challenge/Markdown content and
external identity-provider pages do not excuse the Shifter-owned shell or
process. When content outside Shifter's control prevents full conformance, the
release record must use WCAG's partial-conformance semantics and provide an
accessible supported alternative; it must not silently remove that content
from the tested page.

## Tool and cadence decision

Use the existing frontend package and test stack. Do not introduce a second
browser runner.

| Cadence | Required signal | Posture |
| --- | --- | --- |
| Relevant frontend changes | Existing `eslint-plugin-jsx-a11y` and Vitest plus `vitest-axe` | Blocking in the existing path-routed SPA quality job, with zero violations and no debt baseline |
| Every pull request | Full-page Playwright scans using `@axe-core/playwright` against every registered PR surface/state in Chromium at desktop and narrow/reflow viewports | A dedicated read-only job in `deploy.yml` and a direct dependency of `PR Gate`; no path-based skip |
| Nightly on the integration branch | The same registered browser matrix in Chromium, Firefox, and WebKit; tool `incomplete` results are retained for human triage | A thin scheduled workflow calls the package-owned command; a failure or newly unresolved incomplete result is release-blocking and gets a tracking issue, but creates no second baseline or ruleset |
| On demand / release candidate | The same runner and surface identifiers against an allowlisted deployed target for integration-only journeys, including Guacamole/CTFd where enabled | Release evidence; never a free-form authenticated URL scanner |
| Triggered manual audit | WCAG-EM-based evaluation with keyboard, zoom/reflow, contrast/forced-colors and reduced-motion checks, and real screen-reader/browser combinations | Required before the first conforming release, before a release containing a new or materially changed surface/process, after an accessibility-critical incident, and at least annually |

The axe ruleset is the union of WCAG 2.0, 2.1, and 2.2 Level A/AA tags supported
by the pinned engine (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, and
`wcag22aa`). Omitting the earlier tags would omit inherited WCAG requirements.
Best-practice rules may be reported separately but must not be conflated with a
WCAG failure or used to calculate conformance.

Playwright is already the repository's browser-test incumbent and supports
authenticated workflows and visible state transitions. Pa11y would add a
second Chromium orchestration/configuration surface around overlapping engines.
Lighthouse accessibility is an axe-derived weighted score that omits manual
audits; a numeric threshold can stay green while a required success criterion
fails. Neither is adopted as a conformance or release gate. They may be used by
an auditor as non-authoritative aids.

## Coverage contract

Keep one test-owned accessibility surface matrix under the existing
`shifter/shifter_platform/frontend/e2e/` boundary. Each entry has a stable
surface/state id, a route reference or built-doc URL, an actor fixture, a
deterministic state fixture, viewport class, readiness assertion, and the
source path responsible for remediation. Those are test coordinates, not an
application route, authorization, DTO, or workflow schema.

Completeness is fail-closed:

- reconcile SPA entries with the route objects that construct
  `frontend/src/router.tsx`;
- reconcile server-rendered entries with human-facing Django URL patterns from
  `config/urls.py`, `mission_control/urls.py`, `cms/scenario_editor/urls.py`,
  `ctf/urls.py`, and `workspaces/public_urls.py` while explicitly classifying
  non-page endpoints;
- scan every page emitted by `mkdocs build --strict`, not a separately copied
  docs URL list; and
- require an explicit deployed-profile entry for a supported third-party UI
  that cannot run in the hermetic PR stack.

A new route or built documentation page without a matrix entry fails before a
scan can pass. A removed route leaves a stale entry and also fails. Dynamic
routes use deterministic synthetic identifiers; the matrix must not copy
domain records or authorization rules. Broad catch-all routes do not count as
coverage for arbitrary paths.

At minimum, the matrix exercises each distinct shell/template and each complete
critical process, plus high-risk variations: anonymous/authenticated/denied
access, validation errors, empty and populated data, open dialogs/menus/tabs,
loading completion, destructive confirmation, and responsive layout. Axe does
not inspect inactive hidden content, so the test must expose a state and assert
its readiness before scanning. A redirect to login, generic error page, empty
mount node, failed API bootstrap, scan exception, zero executed rules, or
unexpected `incomplete` result is not a passing page.

Canvas/terminal behavior, visual focus order, keyboard traps, timing, content
meaning, and cross-origin/new-tab integrations remain explicit manual-audit
items. In particular, an axe pass over the terminal shell does not prove xterm
or the Guacamole client is screen-reader usable.

## Baseline ratchet (UX-050)

The accessibility baseline is an exact finding set, not a count or a permitted
threshold. A fingerprint contains the stable surface/state id, execution
project (browser, viewport, and theme), axe rule id, WCAG tags, frame path, and
normalized target. It contains no rendered HTML, user data, tokens, or response
body.

On a pull request, compare the proposed baseline with the trusted base-branch
artifact using the existing ADR ratchet/base-reference convention. The
committed head baseline must equal the still-observed subset of the base
baseline:

- a new or changed fingerprint fails;
- a resolved fingerprint must be removed, so stale allowances fail;
- baseline additions, count-only substitutions, selector swaps, and tool
  crashes fail; and
- an axe/ruleset upgrade that discovers debt fails until the finding is fixed or
  separately waived. A dependency update is not permission to rebaseline.

The initial enforcement change may capture the current browser findings once,
reviewed against the full matrix. That no-base enrollment path is valid only
when the trusted base has no accessibility artifact, the seeded artifact
exactly equals the observed findings, and the PR changes tooling, fixtures,
workflow, dependency, baseline, and guidance files only—not product components,
templates, routes, or stylesheets. After enrollment, missing or malformed base
state fails closed. It does not baseline manual failures, `incomplete` results,
missing/unreachable surfaces, authentication/setup failures, or scanner errors.
Baseline debt remains non-conformance and must have tracking issues; the
baseline is only the migration mechanism that prevents new automated debt.

## Manual audit and release evidence

The initial audit covers the whole governed inventory before any release is
described as conforming. Later audits are required when a release adds a
surface, adds a step to a complete process, or changes navigation, semantics,
keyboard/focus behavior, forms/validation, authentication, timing/motion,
responsive layout, color/status communication, terminal/remote access, or an
accessibility-relevant framework/theme dependency. Copy-only changes may be
declared non-material in review with a rationale; a PR label alone is not
evidence. An accessibility-critical incident triggers a new audit of the
affected process before the next release. Run a full inventory audit at least
annually even if no release has triggered one.

Use an accessibility-trained reviewer who did not author the primary UI change
where practicable. The review includes keyboard-only operation, 200% and 400%
zoom/reflow, forced-colors/high-contrast and reduced-motion behavior, and at
least one Windows screen reader/browser pair and one Apple screen
reader/browser pair. Include mobile assistive technology when the changed
surface claims mobile support. User testing with people with disabilities is
strongly preferred for new critical workflows and is not replaced by expert
screen-reader testing.

The durable deliverable is a reviewed Markdown record under
`docs/audit/accessibility/`. It records the exact audited commit and deployed
build/environment where applicable, surface-matrix revision, WCAG version and
level, WCAG-EM scope/sample, OS/browser/assistive-technology versions, complete
processes and states tested, findings mapped to success criteria, linked issues
and waivers, reviewer/approver, date, and conclusion (`pass`,
`pass-with-active-waivers`, or `fail`). It points to bounded CI/run evidence; it
does not copy traces, DOM dumps, screenshots, cookies, participant data, or raw
logs into Git.

The release check runs before the write-capable Release Please action can create
a tag or GitHub Release. When surface-affecting changes exist since the previous
release, it requires a passing reviewed record whose `audited_through` commit is
an ancestor of the candidate and proves that every later commit changes only
audit/release metadata, not a governed surface. This avoids the impossible
self-referential requirement for a report to name its own commit. Missing,
stale, wrong-SHA, wrong-profile, failed, or unapproved evidence blocks release.

## Triage and waiver policy

PR findings stay on the PR and block `PR Gate`. Scheduled, deployed, or manual
findings receive a GitHub issue with UX-010/UX-050 traceability, affected
surface/state and user task, WCAG success criterion, reproduction environment,
severity/user impact, owner, and target release. Axe `impact` is diagnostic
priority, not permission to ignore a Level A/AA failure.

`docs/adr/exceptions.yaml` remains the only waiver registry. A valid
accessibility waiver is one exact finding (or an enumerated exact set), names
ADR-055, the surface/state and WCAG criterion, explains user impact and why
immediate remediation is infeasible, identifies an accessible alternative or
compensating control, links the remediation issue, has an owner and short
expiry no later than the next planned release, and is approved through the
existing ADR CODEOWNER boundary. The primary implementer must not self-approve
a waiver.

Do not overload exception `paths` or `checks` with a finding fingerprint. If the
current exception schema cannot express exact accessibility scope, extend its
canonical validation and central `Violation` filtering once with an optional
exact-fingerprint field. The browser runner must not implement a second waiver
parser, expiry check, suppression file, or inline `disableRules` policy.

An approved waiver can authorize release under UX-010's governance clause, but
it does not make the failure conformant. A release with an active WCAG failure
must not make an unqualified WCAG 2.2 AA conformance claim; its record discloses
the bounded exception or partial-conformance scope.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Frontend package/tooling | `frontend/package.json`, lockfile, `eslint.config.js`, `vite.config.ts`, `playwright.config.ts` | Add the browser adapter and package-local commands here; keep one lock and one browser runner. |
| Fast accessibility checks | `jsx-a11y` recommended rules, `src/test/eslint-a11y-canary.test.ts`, existing Vitest `vitest-axe` page tests | Preserve these complementary checks and the canary; browser coverage does not replace component/lint feedback. |
| SPA routes and shared UI | `frontend/src/router.tsx`, `app/RootLayout.tsx`, `components/ui/*`, `app/state-map.ts`, `index.css` | Derive coverage from the real router and reuse Radix/shadcn semantics, state mapping, focus, and token patterns. Do not invent page-local accessibility primitives. |
| Django page routes/host | `config/urls.py`, app `urls.py`, `shared.spa_host`, `templates/**`, `static/{css,js}/**` | Reconcile the real resolver and scan the actual rendered document; do not maintain a copied route universe. |
| Docs publication | ADR-038, `mkdocs.yml`, `.github/workflows/docs.yml`, `mkdocs build --strict` | Scan built public output; excluded internal docs remain excluded. Do not create a second docs build/config. |
| CI routing | `deploy.yml` `PR Gate`, `_quality.yml`, `.github/quality-path-filters.yaml`, `scripts/quality_ownership` | Make the every-PR job a direct `PR Gate` dependency rather than hiding it behind `_quality.yml`'s deliberate docs-only/path skips. Do not create a parallel path router; accessibility impact and quality ownership are different concepts. |
| Ratchet and waivers | ADR-019 base-ref pattern; `adr_guard.Violation`; `docs/adr/exceptions.yaml`; central exception loading/filtering | Compare against the trusted base and reuse one dated-waiver policy. No count threshold or tool-local suppressions. |
| Release | ADR-042, `.github/workflows/release-please.yml`, `docs/DEVELOPMENT_WORKFLOW.md` | Gate before the write-capable release action. A GitHub Release that already exists is too late to block. |
| Browser security/auth | ADR-029, ADR-036, Django sessions/CSRF, CTF account boundary, `AllowedHostsOriginValidator`, `frontend/src/api/client.ts` | Exercise normal boundaries with synthetic actors; never weaken CSP, CSRF, origin, scope, or backend authorization for the scanner. |
| Errors/logging | `shared.api.errors`, `frontend/src/api/errors.ts`, `shared.log_sanitize`, ECS logging | Fail on wrong/error states and emit bounded scanner diagnostics. Do not expose raw envelopes, DOM, trace, or secrets. |
| Persistence/evidence | Git baseline, `docs/audit/`, GitHub issues/runs | Add no application model, migration, repository, audit row, service, or telemetry store. |

No application controller, serializer, DTO, domain service, repository,
exception hierarchy, persistence model, or runtime feature flag is warranted by
the gate. Accessibility fixes discovered later remain in the component/page
that owns the behavior and reuse its existing API validation, authorization,
error, state, and logging contracts.

## Cross-cutting layers the implementation must pass

| Layer | Required behavior |
| --- | --- |
| Authentication and authorization | PR scans use synthetic local actors for anonymous, ordinary authenticated, CTF participant/organizer, staff, and denied cases. Sessions are established through existing Django/CTF boundaries; route handles and hidden controls stay advisory, while backend permissions remain authoritative. No test-only production endpoint, browser API token, `csrf_exempt`, or authorization bypass. |
| Secret handling | Hermetic PR jobs use no cloud, IdP, CTFd-admin, or deployment credential. Session cookies, CSRF tokens, invitation/reset tokens, and deployed-test credentials stay in mode-restricted temporary state, never committed, printed, uploaded, or interpolated into screenshots/DOM reports. Live credentials come from an approved protected environment. |
| URL/config validation | Reuse `SPA_E2E_BASE_URL` only behind a parsed mode-aware policy: PR mode is loopback/same-origin; deployed mode selects a closed allowlisted environment origin. Reject credentials, fragments, non-HTTP(S) schemes, redirects across origins, and free-form PR-controlled targets. Add no Vite-exposed secret or duplicate Django env setting. |
| Browser/CSP/origin policy | Scan the production-shaped Django/WhiteNoise page with current CSP, referrer, permissions, session, CSRF, host, and WebSocket-origin protections intact. Playwright's test injection is not a reason to add `unsafe-inline`, `unsafe-eval`, a remote script source, or a route-local CSP exception. |
| Input/data validation | Create deterministic state through existing fixtures/services/models and submit browser mutations through normal serializers/forms. Do not copy domain validators into the surface matrix or seed malformed data by bypassing database constraints. |
| OS/process exposure | Package scripts receive non-secret mode/project selectors. Cookies, tokens, passwords, signed Guacamole URLs, and raw page content never enter argv, process listings, shell tracing, or `GITHUB_OUTPUT`. Use fixed argv/package commands and bounded timeouts. |
| Error envelopes | Assert the expected page identity and ready state before scanning. A shared API error, auth redirect, exception page, timeout, scanner crash, missing rule execution, or malformed result fails as itself; do not scan the fallback page and report a false pass or add a new application exception family. |
| Logging/artifacts | Diagnostics contain stable surface/state id, route template (not live identifiers), axe rule/WCAG tags, normalized target, and help URL. Omit axe's raw HTML, request/response bodies, cookies, storage state, private URLs, and participant/provider data. Authenticated Playwright traces/screenshots are off by default and are never public artifacts. |
| Persistence/audit | Test data uses the ephemeral local database and is torn down. The only durable policy state is the reviewed baseline, audit record, issue, and existing exception registry. Accessibility checking adds no runtime audit event or user preference. |
| Workflow/release security | PR execution stays GitHub-hosted with `contents: read`, no `id-token: write`, no protected environment, and no `pull_request_target`. Deployed on-demand runs bind a closed environment. Workflow changes retain full-SHA action pins, quality-path ownership validation, `actionlint`, and ADR guard. Release evidence is checked by a read-only predecessor before the Release Please job receives write permissions. |

## Extensibility seam

The seam is a surface/state matrix entry parameterized by stable id, canonical
route reference, actor, deterministic state setup, browser, viewport, theme,
readiness assertion, execution tier (`pr`, `nightly`, or `deployed`), and
remediation source. Those execution dimensions are part of a finding's stable
coordinates, so a browser- or viewport-specific defect cannot substitute for
another occurrence. Adding another route, role, responsive layout, deployment
profile, or browser project adds data and a fixture at that seam; it does not
add another runner, route schema, auth model, waiver file, or workflow router.

Keep the axe tag set and browser projects as named package-level configuration
so a future WCAG revision or supported-browser change is made once. Keep
surface-impact classification separate from `.github/quality-path-filters.yaml`:
the former asks whether a manual audit is stale, while the latter asks which
blocking engineering jobs own a changed production path.

## Gotchas and anti-patterns

- Do not equate zero axe violations, a Lighthouse score, or `jsx-a11y` success
  with WCAG conformance.
- Do not scan only the mount shell, happy path, desktop viewport, visible
  default tab, or unauthenticated login page.
- Do not use counts, severity thresholds, broad selector exclusions, disabled
  rules, per-test ignores, snapshot rewrites, or changed-pages-only selection.
- Do not let a redirect, permission-denied state, API failure, blank page,
  scanner exception, or zero-rule run masquerade as the requested page.
- Do not copy React or Django routes, authorization policies, domain DTOs,
  validators, error shapes, or state machines into the accessibility matrix.
- Do not parse `docs/adr/exceptions.yaml` in JavaScript or add an axe/Pa11y/
  Lighthouse-specific waiver file.
- Do not upload authenticated traces, full axe JSON/HTML snippets, screenshots,
  storage state, cookies, reset/invite links, signed URLs, or private fixture
  content.
- Do not weaken CSP, CSRF, session, host/origin, token-scope, or backend
  authorization controls to make automation convenient.
- Do not silently exclude xterm, Guacamole, CTFd, external authentication, or
  operator-authored content from complete-process manual review.
- Do not allow an expired waiver, stale audit, or post-audit UI change to pass a
  release, and do not describe `pass-with-active-waivers` as conformance.
- Do not run the first audit only after Release Please has created the release.

## Non-goals and implementation boundary

- No accessibility remediation or visual redesign under #713.
- No accessibility CI/workflow/package/route/browser-test implementation under
  this ADR issue. The narrow ADR-registry validator protects the accepted
  decision itself; it is not the accessibility gate.
- No replacement of React, Vite, Playwright, Vitest, `jsx-a11y`, the design
  system, Django templates, MkDocs, or Release Please.
- No new application API, schema, serializer, validator, service, repository,
  model, migration, exception hierarchy, logger, metric, or audit store.
- No accessibility certification, legal opinion, or conformance claim before
  the initial full audit and remediation/waiver review.
- No attempt to make automated tools judge content meaning, keyboard usability,
  screen-reader announcements, focus order, timing, terminal interaction, or
  third-party user experience that requires human evaluation.

## Traceability handoff

UX-010 and UX-050 remain `DRAFT` while #713 records architecture only. Keep
#713 linked as their design record; before #1526 begins the runtime/CI
implementation, transition both requirements to `ACTIVE` through the
repository's Ground Control workflow. Do not create `IMPLEMENTS` links while a
requirement remains `DRAFT`, and reconcile code/test links before closing the
follow-up issue.

## Sources

- [WCAG 2.2, including conformance requirements](https://www.w3.org/TR/WCAG22/)
- [WCAG Evaluation Methodology (WCAG-EM)](https://www.w3.org/WAI/test-evaluate/conformance/wcag-em/)
- [Playwright accessibility testing](https://playwright.dev/docs/accessibility-testing)
- [axe-core API and WCAG tags](https://github.com/dequelabs/axe-core/blob/develop/doc/API.md)
- [axe-core rule inventory](https://github.com/dequelabs/axe-core/blob/develop/doc/rule-descriptions.md)
- [Lighthouse accessibility scoring](https://developer.chrome.com/docs/lighthouse/accessibility/scoring)
- [Pa11y runner and threshold model](https://github.com/pa11y/pa11y)
