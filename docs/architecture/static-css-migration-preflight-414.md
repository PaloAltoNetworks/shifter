# Static CSS Migration Preflight (#414)

Status: pre-implementation guidance

Date: 2026-06-29

Issue: GitHub #414, "Migrate inline styles and `<style>` blocks to static CSS
files"

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

ADR-027 note: legacy experiment templates and static CSS were removed by issue
#1195. References below to `cms/experiments` describe the pre-removal state and
are not current implementation guidance.

## Scope Boundary

Treat this as a browser-facing Django template and static-asset hardening pass,
not a portal redesign. The goal is to remove inline `style=""` attributes and
template-local `<style>` blocks from rendered portal pages while preserving the
current UI, auth behavior, template context behavior, JavaScript state
contracts, and static-asset packaging.

Keep these surfaces separate:

1. Browser page templates under `shifter/shifter_platform/templates/` and
   `shifter/shifter_platform/cms/experiments/templates/`.
2. Shared theme/component CSS under `shifter/shifter_platform/static/css/`.
3. App/page-owned CSS under namespaced static paths such as
   `static/mission_control/css/`, `static/ctf/css/`, and `static/cms/css/`.
4. JavaScript-controlled visibility and layout state in
   `shifter/shifter_platform/static/js/`.
5. HTML email templates under `templates/ctf/email/`, where inline CSS is a
   separate mail-client compatibility decision.
6. Django admin HTML generated from Python, which uses Django admin asset
   extension points rather than the portal base templates.

HTML email inline styles, generated documentation HTML under
`documentation/docs/`, and Python-built Django admin snippets should not be
silently mixed into the portal-template migration. If the issue owner wants
those surfaces changed too, handle them as explicit follow-ups with their own
compatibility tests.

## Architecture Decisions

- Keep Django's static-file pipeline as the asset boundary. Static CSS is loaded
  with `{% load static %}` and `<link rel="stylesheet" href="{% static '...' %}">`;
  do not generate per-request CSS files, embed CSS in views, or bypass
  `collectstatic`.
- Preserve the current custom base-template block contract unless the whole
  base/child set is deliberately migrated. The portal bases expose
  `{% block extra_css %}` today; adding `{% block extrastyle %}` only in child
  templates would silently drop CSS. If `extrastyle` is introduced, base
  templates must expose or alias it and rendered-template tests must prove the
  linked assets remain present.
- Keep global tokens, shared components, and existing inline-style replacement
  utilities in `static/css/theme.css`. Keep sidebar/dropdown/documentation
  primitives in their existing shared CSS files. Put app/page-only CSS in the
  owning app namespace instead of growing one global catch-all file.
- Reuse existing utility classes for simple one-declaration replacements
  (`d-none`, `d-inline`, `flex-1`, spacing, text alignment). Use page/app CSS
  for semantic layouts, state styles, and repeated component shapes.
- Preserve JavaScript behavior when extracting `display: none` and similar
  stateful declarations. Several front-end modules mutate `element.style.display`;
  moving initial state to CSS can make `element.style.display` read as empty.
  Class-based state is fine, but the template, JS, and JS tests must move
  together.
- Do not claim complete CSP compliance from this issue alone. Removing inline
  CSS improves the future `style-src` posture, but inline scripts and external
  script/style sources remain separate CSP blockers.
- No new ADR is needed unless the implementation adds a new enforceable
  architecture guardrail, changes static-file storage policy, changes workflow
  gates, or adds a CSP policy.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #414 |
| --- | --- | --- |
| Static-file settings | `config/settings.py` `STATIC_URL`, `STATICFILES_DIRS`, `STATIC_ROOT`, `STORAGES` | Keep WhiteNoise/manifest storage and test storage semantics. Do not add a parallel static serving path or runtime static generation. |
| Built-image static packaging | `shifter/shifter_platform/Dockerfile`, `scripts/stack-smoke/page_smoke.py` | `collectstatic` runs at image build as `appuser`; stack smoke catches missing linked local `/static/` assets from built pages. |
| Base template CSS loading | `mission_control/base.html`, `ctf/base.html`, `documentation/base.html`, `risk_register/base.html`, `scenario_editor/base.html`, `experiments/base.html` | Use the existing `{% load static %}` plus CSS block pattern. Do not add child-only block names the base does not render. |
| Shared visual language | `static/css/theme.css`, `sidebar.css`, `dropdown.css`, `documentation.css` | Reuse variables and components; avoid duplicate theme files or one-off color systems. |
| Existing extracted CSS | `static/css/ngfw-detail.css`, `ngfw-wizard.css`, `terminal.css`, `upload-ui.css` | Build on the extracted-page pattern, then move/page-namespace files deliberately if the implementation changes paths. |
| Inline-style structural tests | `tests/scenario_editor/test_inline_styles.py`, `tests/mission_control/test_ngfw_detail.py` | Generalize the existing file-scan pattern instead of adding ad hoc checks per app. Use explicit exceptions for email/admin/generated docs. |
| Rendered-page tests | `tests/mission_control/test_views.py`, `tests/integration/mission_control/test_page_renders.py`, CTF view suites | Prove changed pages still render through the real template stack; avoid patching `render` or first-party context processors for style migration tests. |
| JS behavior tests | `static/js/*.test.js`, especially dashboard/ngfw/dropdown/terminal/ctf range tests | Update tests alongside any class/state contract change; do not rely only on static file scans. |
| i18n template scan | `tests/config/test_i18n_configuration.py` | Keep `{% load i18n %}` / `{% trans %}` behavior intact while moving CSS blocks. |
| Sanitized logging/errors | `shared.log_sanitize.safe_log_value`, `shared.errors`, `shared.api.errors` | Static migration should normally add no runtime logging or error envelopes. If asset diagnostics are added, sanitize paths and never log request secrets. |

## Cross-Cutting Layers

- Auth surface: portal pages still enter through Django middleware,
  `AuthenticationMiddleware`, view decorators, and existing context processors.
  Static CSS files are public cacheable assets, so they must not contain
  per-user, tenant, token, credential, serial-number, or request-specific data.
- Authorization surface: styles are presentation only. Do not move role,
  feature-flag, active-range, CTF event, or ownership decisions into CSS class
  naming, static files, or JavaScript-only gates. Templates may keep emitting
  server-derived finite state classes such as status names.
- Template/XSS surface: keep Django autoescaping and existing `json_script`
  patterns. Do not interpolate untrusted values into `<style>` blocks,
  `style=""`, CSS custom properties, `url(...)`, or generated class names.
  Dynamic visual state should map trusted finite values to known classes.
- Static asset surface: linked CSS must be discoverable by Django staticfiles
  and by WhiteNoise manifest storage. Missing files should fail in source tests,
  `collectstatic`, or stack smoke rather than in production.
- Config/env surface: this issue should not need new settings or environment
  bindings. If a later CSP or static policy knob is introduced, bind it through
  `config/settings.py`, keep it non-secret unless proven otherwise, and update
  the env manifest/runtime surfaces.
- Secret-handling surface: CSS, filenames, static URLs, test failure messages,
  and stack-smoke output must not include CSRF tokens, session cookies, bearer
  tokens, OIDC values, upload tokens, private keys, presigned URLs, or raw
  provider diagnostics.
- OS/runtime exposure: do not shell out with secret-bearing arguments or write
  runtime-generated CSS into the immutable app tree. The production image builds
  static artifacts once with `collectstatic` as the non-root app user.
- Error-envelope surface: no browser/API error contract should change. Missing
  asset checks belong in tests/smoke output; user-facing API envelopes are out
  of scope for a CSS extraction.
- Observability surface: no new metrics framework is needed. If temporary
  inventory scripts are added, keep their output to file paths/counts and avoid
  request or user data.
- Persistence surface: no models, migrations, audit tables, or durable events
  are needed.
- Import-boundary surface: static extraction must not add Python cross-app
  imports, duplicate DTOs, schemas, validators, or exception hierarchies.

## Extensibility Seam

The seam is style ownership, not a new styling framework:

- `static/css/theme.css`: shared tokens, base components, and broadly reused
  utilities.
- `static/css/<shared-component>.css`: cross-app primitives already loaded by
  multiple bases, such as sidebar/dropdown/documentation.
- `static/<app>/css/<page-or-feature>.css`: app/page styles loaded only by the
  relevant template block.
- A future structural style gate should be parameterized by template roots and
  explicit exception globs so adding a new Django app or a deliberate email/admin
  exception is data-shaped, not a copy of the scanner.

This keeps the next obvious changes cheap: app namespacing, CSP tightening,
adding another Django app, or moving a shared component from a page stylesheet
into the global theme without rewriting every template.

## Gotchas And Anti-Patterns

- Do not replace inline styles with hundreds of globally named one-off classes.
  Shared utilities are acceptable for simple declarations; page-specific
  selectors belong with the owning page/app.
- Do not create duplicate theme systems. The deprecated `xdr-theme.css` /
  `xdr-sidebar.css` references in experiments are not backed by files in the
  current static tree and should not be copied forward as a pattern.
- Do not use `style` attributes for initial hidden state just because existing
  JS later writes `style.display`; fix the state contract deliberately.
- Do not move template-condition semantics into CSS. CSS may style
  `status-ready`; it must not decide whether the current user can see a control.
- Do not use user-controlled strings as class names without a finite server-side
  mapping.
- Do not break email rendering by extracting email CSS to external files that
  common mail clients will ignore.
- Do not edit `CHANGELOG.md` directly; a user-visible portal change needs a
  towncrier fragment under `changelog.d/414.<type>.md`.
- Do not call the CSP benefit complete while inline scripts and third-party
  assets remain in page templates.

## Non-Goals

- No view, service, repository, model, migration, API serializer, or domain
  workflow redesign.
- No new CSS preprocessor, frontend build pipeline, design system rewrite, or
  component framework.
- No CSP header rollout unless separately scoped and tested.
- No static-file storage redesign, CDN migration, or container runtime change.
- No behavior changes to authentication, authorization, CTF navigation, active
  range context, upload flows, terminal flows, or documentation rendering.
- No automatic restyling beyond preserving the existing rendered UI while moving
  CSS to cacheable static assets.
