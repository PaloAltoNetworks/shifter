# SPA Design System Foundation Preflight (#1299)

Status: pre-implementation guidance

Date: 2026-07-03

Issue: GitHub #1299, "SPA cutover: design system foundation"

This issue is requirement-free. The GitHub issue title, body, constraints, and
acceptance criteria are the shipping contract. This note is intentionally not an
implementation plan and does not implement the SPA cutover.

## Scope Boundary

Issue #1299 should define the SPA-facing design-system contract before feature
modules rebuild Django-template screens. Treat the deliverable as a reusable
foundation and migration map, not as a page redesign or feature migration.

Keep these surfaces separate:

1. Design-system source artifacts: token inventory, component inventory, state
   matrix, accessibility baseline, and migration map.
2. Existing Django template/static CSS surfaces under
   `shifter/shifter_platform/templates/` and `shifter/shifter_platform/static/`.
3. Future SPA shared UI primitives and feature modules, in the location selected
   by the SPA architecture issue. This preflight does not choose that framework
   or package layout.
4. Backend HTTP/API concerns under `/api/v1/`, DRF serializers, permissions,
   shared error envelopes, and service facades.
5. Domain state, authorization, validation, persistence, audit, and logging,
   which remain owned by existing Python services and shared cross-cutting
   layers.

Deprecated Angular/Cortex-XDR design notes under
`shifter/shifter_platform/documentation/docs/_deprecated/` are not authoritative
for the SPA cutover. Use the current operational Shifter direction from
`docs/design/ux-003-oss-shifter-research-personas.md`,
`docs/design/ux-003-information-architecture-sitemap.md`, and the active static
assets instead.

## Architecture Decisions And Guardrails

- Preserve the product tone: dense, operational, dark, low-decoration, and
  state-forward. Do not introduce a marketing-style, module-local, or
  one-off palette.
- Start the token inventory from the live incumbents:
  `static/css/theme.css`, `sidebar.css`, `dropdown.css`, page/app CSS, and the
  UX-002/UX-003 design notes. Normalize them into semantic tokens rather than
  copying raw values into each component.
- Token coverage must include color, type, spacing, radius, elevation, focus
  rings, motion, z-index, and semantic statuses. Status tokens must distinguish
  UI feedback (`error`, `success`, `warning`, `info`) from domain statuses such
  as range provisioning, challenge availability, CTF event state, upload state,
  and risk severity.
- Component ownership must be explicit. Shared primitives belong in the SPA
  shared UI boundary chosen by the SPA architecture work; feature modules may
  wrap primitives for domain data but must not fork buttons, tables, dialogs,
  alerts, tabs, filters, empty/loading states, or detail panels.
- App shell and navigation must reuse the UX-003 IA, taxonomy, and role/mode
  concepts. Do not create parallel navigation schemas inside CTF, Mission
  Control, Scenario Editor, Risk Register, and Documentation.
- The state matrix must be component-level, not workflow-level. Hover, focus,
  disabled, loading, error, success, destructive confirmation, and
  permission-denied are reusable UI states; domain workflows keep their own
  service-owned status machines.
- Accessibility is part of the primitive contract: keyboard operation, visible
  focus, screen-reader names, form validation linkage, color contrast, reduced
  motion, and non-color-only status communication are baseline requirements.
- Django coexistence is a first-class migration mode. Until a screen is fully
  owned by the SPA, server-rendered templates continue to use Django's static
  pipeline, `{% static %}`, `{% trans %}` / `{% blocktrans %}`, and the existing
  base-template block contract.
- No new ADR is required for this foundation alone. Update ADR docs only if the
  implementation adds an enforceable guardrail, changes static asset policy,
  changes i18n policy, changes the SPA architecture decision, or weakens/changes
  CI gates.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1299 |
| --- | --- | --- |
| Visual tokens and primitives | `shifter/shifter_platform/static/css/theme.css`, `sidebar.css`, `dropdown.css` | Inventory and rationalize before adding SPA tokens. Do not create a second unrelated palette or duplicate component styles. |
| App/page CSS migration evidence | `static/css/ctf-*`, `mc-*`, `scenario-editor-base.css`, `ngfw-*`, `upload-ui.css`, `terminal.css` | Use these as the migration map input from template/page patterns to shared primitives or app-owned wrappers. |
| Product IA and taxonomy | `docs/design/ux-003-information-architecture-sitemap.md` | Preserve participant/organizer mode, route taxonomy, breadcrumbs, contextual tabs, and modal guidance. |
| Product tone | `docs/design/ux-003-oss-shifter-research-personas.md`, `docs/design/ux-002-oss-visual-identity-preflight.md` | Keep operational density, semantic color use, quiet cards, and debranded neutral identity. |
| Template shell | `templates/mission_control/base.html`, `ctf/base.html`, `risk_register/base.html`, `scenario_editor/base.html`, `partials/icon_sidebar.html`, `partials/ctf_participant_sidebar.html` | During coexistence, preserve current CSS/script block contracts and sidebar behavior. |
| Static asset pipeline | `config/settings.py` `STATICFILES_DIRS` / `STORAGES`, WhiteNoise manifest storage, `Dockerfile` `compilemessages` then `collectstatic` | SPA assets must remain build-time static artifacts. Do not generate per-request CSS/JS or bypass manifest/static checks. |
| Frontend quality gates | `shifter/shifter_platform/package.json`, `eslint.config.js`, `.stylelintrc.json`, `.github/workflows/_quality.yml` | Extend existing lint/test surfaces instead of adding untracked frontend checks. |
| Template i18n | ADR-016 in `docs/adr/index.yaml`, `tests/config/test_i18n_configuration.py` | Do not move user-facing strings out of an enforced i18n path. A future SPA string catalog/extraction gate needs explicit architecture review. |
| Inline-style/static gates | `tests/*/test_inline_styles.py`, `tests/test_misc_inline_styles.py`, `docs/architecture/static-css-migration-preflight-414.md` | Shared primitives should reduce inline style pressure, not reintroduce style attributes or template-local style blocks. |
| API boundary | `config/api_urls.py`, `config/_drf_settings.py`, `shared.api.errors`, `documentation/docs/technical/dev/api.md` | SPA components talk to canonical DRF endpoints and error envelopes. Do not add ad-hoc JSON view contracts for UI convenience. |
| Auth and scopes | `shared.api_tokens.authentication`, `shared.api_tokens.scopes`, `shared.api_tokens.permissions`, DRF `SessionAuthentication` | Browser SPA uses session auth and CSRF. Programmatic bearer token semantics stay platform-owned. |
| Domain authorization | `shared.auth`, `ctf.views._access`, risk-register access checks, app services | Hidden or disabled controls are UX affordances only; services and endpoints remain the security boundary. |
| Logging and redaction | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint` | Component diagnostics, demos, and tests must not log tokens, cookies, signed URLs, private hostnames, or provider payloads. |
| Import/layer enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, ADR-001 | Shared UI/API helpers must not create Python cross-app imports or duplicate service workflows. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: browser clients pass through Django sessions,
  `CsrfViewMiddleware`, and DRF `SessionAuthentication` for unsafe API methods.
  Do not store platform API tokens, invite tokens, CSRF tokens, or signed URLs in
  SPA state, localStorage, examples, or component props beyond the existing
  flow's narrow need.
- Authorization surface: navigation visibility, disabled buttons, and
  permission-denied states do not authorize anything. Backend endpoints and
  services must keep enforcing CTF event membership/organizer checks, CMS
  authoring checks, Mission Control ownership, risk-register access, and token
  scopes.
- Static asset surface: design tokens, CSS, JS, icons, and examples are public
  cacheable artifacts. They must contain no per-user data, tenant identifiers,
  live cloud identifiers, secrets, or secret-bearing URLs, and must remain
  discoverable by Django staticfiles/WhiteNoise manifest storage.
- Template/XSS surface: bootstrap data from Django to the SPA must use existing
  safe patterns such as `json_script` and finite server-side mappings. Do not
  interpolate untrusted strings into CSS custom properties, `url(...)`, class
  names, HTML IDs, or inline scripts.
- Payload and schema validation surface: DRF serializers validate HTTP shapes;
  existing Pydantic/domain schemas and services validate scenarios, uploads,
  credentials, range specs, CTF workflows, and risk data. Do not duplicate those
  rules in component props or frontend-only validators.
- Error-envelope surface: the SPA should consume the platform DRF envelope from
  `shared.api.errors` and fixed legacy JSON messages during migration. Do not
  invent per-component exception shapes or surface raw `str(exc)`, provider
  payloads, stack traces, tokens, cookies, or signed URLs.
- Config/env surface: this foundation should not require new environment
  bindings. If the SPA architecture later introduces build-time settings, bind
  only non-secret public configuration, document it through the platform config
  manifest path, and ensure bundlers do not inline secrets.
- OS/runtime exposure surface: do not pass bearer tokens, CSRF tokens, signed
  URLs, provider IDs, private keys, or screenshots with secrets through npm
  scripts, process argv, build logs, GitHub summaries, story/demo fixtures, or
  generated static bundles.
- Logging/observability surface: UI work should normally add no server logging.
  If diagnostics are added, use ECS logging and redaction helpers server-side;
  keep browser console messages generic and secret-free.
- Persistence/audit surface: design tokens and component inventory are not
  runtime persistence. If a later UI preference or audit-worthy action is
  needed, use existing models/services/audit paths rather than a design-system
  store.
- i18n/accessibility surface: Django-rendered strings remain under ADR-016.
  SPA-rendered user-facing strings must not silently escape extraction,
  translation review, accessible-name review, or validation-message coverage.
- Import-boundary surface: backend code touched for the SPA must keep using
  shared service facades and `shared` contracts. Do not add CTF to Mission
  Control imports, Mission Control to CTF imports, direct `cyberscript` imports
  outside `shared`, or app-local copies of shared DTOs.

## Extensibility Seams

- Token seam: model tokens as `primitive -> semantic -> component` aliases in
  the design artifact. Feature components consume semantic/component aliases,
  not raw colors, spacing values, z-index numbers, or hand-coded focus rings.
- Component seam: shared primitives expose variants and states; feature modules
  pass domain data and event handlers. The obvious next change should be adding
  a component variant or status mapping, not editing every feature screen.
- Migration seam: keep the migration map data-shaped with columns such as
  current template, current CSS selector/file, target primitive, owner,
  migration status, and notes. It is an inventory and review artifact, not a
  second runtime schema.
- Mode/density seam: participant versus organizer mode and dense operational
  views should be parameters in shell/navigation/component usage. Do not hardcode
  a single feature module's layout assumptions into shared primitives.
- Motion seam: animation durations/easing and reduced-motion behavior belong in
  tokens or primitive defaults. Adding a future motion style should not require
  rewriting each loading indicator, toast, tab, or dialog.
- Z-index seam: define named layers for shell, sticky headers, dropdowns,
  dialogs, toasts, terminal/fullscreen surfaces, and tooltips. Components should
  not invent local high z-index values.

## Whole-Repo Scope

Likely implementation should inspect, and may touch, these surfaces:

- `docs/design/ux-003-information-architecture-sitemap.md`,
  `docs/design/ux-003-oss-shifter-research-personas.md`, and
  `docs/design/ux-002-oss-visual-identity-preflight.md`.
- `shifter/shifter_platform/static/css/theme.css`, `sidebar.css`,
  `dropdown.css`, page/app CSS files, and static JS modules/tests.
- `shifter/shifter_platform/templates/**` base templates, partials, and page
  templates for the migration inventory only.
- `shifter/shifter_platform/config/settings.py`, `config/api_urls.py`,
  `config/_drf_settings.py`, and static/i18n tests if the runtime asset or
  string boundary changes.
- `shifter/shifter_platform/shared/api_tokens/**`, `shared/api/errors.py`,
  `shared/errors.py`, `shared/log_sanitize.py`, and `shared/auth.py` for API
  and authorization reuse.
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/adr_guard.py`, `.github/workflows/_quality.yml`,
  `shifter/shifter_platform/package.json`, `.stylelintrc.json`, and
  `eslint.config.js` if enforceable gates or frontend tooling change.

Usually out of scope for #1299:

- Terraform, Kubernetes, runner, cloud, or runtime secret delivery changes.
- Database models, migrations, repositories, and durable audit changes.
- Replacing OIDC, Identity Platform, Django sessions, CSRF, or platform API
  tokens.
- Migrating feature screens, endpoints, or workflows.

## Gotchas And Anti-Patterns

- Do not copy the deprecated Angular/XDR theme material forward as the new
  design system.
- Do not create a SPA-only palette, Bootstrap-like fork, CSS-in-JS theme, or
  component style that cannot coexist with the current Django templates during
  migration.
- Do not treat color names as domain statuses. A badge can render a range state;
  it must not define the range state vocabulary.
- Do not duplicate API DTOs, serializers, validators, exception envelopes,
  permission concepts, or workflow state machines in frontend components.
- Do not make hidden navigation, disabled buttons, or client-side route guards
  the only permission check.
- Do not put raw secret material, signed URLs, tokens, cookies, CSRF values,
  private hostnames, cloud identifiers, or provider payloads in sample data,
  Storybook/demo fixtures, screenshots, logs, error messages, or static bundles.
- Do not regress keyboard paths, visible focus, accessible names, reduced motion,
  color contrast, form validation messages, or screen-reader-only context while
  making controls visually denser.
- Do not reintroduce inline `style=""` attributes, template-local `<style>`
  blocks, or untracked asset generation to bridge migration gaps.
- Do not weaken `collectstatic`, Stylelint, ESLint, Jest, Django i18n, ADR guard,
  or import-linter checks to make the design-system work pass.
- Do not edit `CHANGELOG.md` directly; user-visible UI changes need the repo's
  normal changelog fragment path if the implementation changes shipped UI.

## Non-Goals

- No SPA framework selection, package scaffolding, router cutover, feature-page
  rewrite, or backend endpoint migration.
- No new token runtime, theme engine, tenant branding system, persistence model,
  or user preference store.
- No new API authentication scheme, frontend-held bearer-token model, or
  session/CSRF bypass.
- No replacement of existing domain services, repositories, schemas, validators,
  exception hierarchies, audit stores, or logging format.
- No public behavior change to Django templates while this foundation is only an
  inventory/design-system contract.
