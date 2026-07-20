# Configurable Cookie And Privacy Notice Preflight (#67)

Status: pre-implementation guidance

Date: 2026-07-01

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/67>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Add portal plumbing for:

- a dismissible notice about strictly necessary browser storage used for
  authentication, session behavior, and notice dismissal; and
- a public `/privacy/` shell for operator-supplied privacy notice content.

Keep these concepts separate:

1. Functional browser storage disclosure: factual UI copy about existing auth,
   session, CSRF, and dismissal storage.
2. Consent management: out of scope until the product introduces non-essential
   cookies, analytics, advertising, or tracking.
3. Privacy notice shell: a neutral content container and replacement seam owned
   by the deployment operator.
4. Legal policy text: out of scope for this OSS change. The project must not
   bind Palo Alto Networks, maintainers, or deployment operators, and must not
   assert GDPR compliance.

## Architecture Decisions

- Prefer client-local dismissal state in `localStorage` over adding another
  cookie. If a cookie is used instead, it must be strictly necessary,
  non-identifying, `SameSite=Lax`, and `Secure` whenever the deployment is
  served over HTTPS.
- The dismissal key should be namespaced and versioned, for example
  `shifter.cookieNotice.dismissed.v1`, and should not contain user IDs,
  emails, timestamps, route names, or organization details.
- The notice should be implemented as one shared template partial plus one
  static JavaScript asset and shared theme styles. Include it from the existing
  HTML shells that render portal pages rather than duplicating markup and
  storage logic in every app.
- The notice copy must use disclosure language, not consent language. Use
  actions such as "Dismiss," not "Accept," "Agree," "Consent," or preference
  controls.
- `/privacy/` should be a public, GET/HEAD-only route with no login requirement
  and no personalized sidebar/profile data. It should render a neutral
  placeholder until the operator replaces the content.
- The privacy content seam belongs at the template/static-content boundary. A
  stable operator-replaceable template such as `privacy/notice_content.html`
  is sufficient. If the implementation adds an environment-selected template,
  validate the setting at startup and restrict it to a safe template prefix.
- Do not route the public privacy notice through the authenticated in-app docs
  app. The docs renderer is useful precedent for sanitization, but `/docs/` is
  intentionally login-protected and should not become the public privacy route.
- No new database table, model, service layer, audit event, API endpoint, or
  consent-preference abstraction is needed for this issue.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #67 |
| --- | --- | --- |
| Root routes and simple portal views | `config.urls`, `config.views` | Add `/privacy/` at the root URL layer. Do not create an app-local legal-policy controller. |
| Template shells | `templates/mission_control/base.html`, `templates/ctf/base.html`, `templates/risk_register/base.html`, `templates/scenario_editor/base.html`, `templates/documentation/base.html`, auth/public templates | Include one shared notice partial from relevant rendered HTML shells. Avoid divergent copies. |
| Static assets | `shifter/shifter_platform/static/js/*`, `static/css/theme.css`, Django `{% static %}`, WhiteNoise manifest storage | Put dismissal behavior in a static JS file and style it with existing theme variables. Do not inline route-specific scripts everywhere. |
| Existing local browser persistence | `static/js/sidebar.js`, `static/js/terminal*.js` | Reuse the localStorage pattern, but keep this key non-identifying and notice-specific. |
| Auth/session/CSRF storage | Django `SessionMiddleware`, `CsrfViewMiddleware`, auth backends in `config._oidc_settings` / `config.identity_platform`, `ensure_csrf_cookie` where already used | The notice describes this existing behavior; it must not change auth, CSRF, SameSite, secure-cookie, or OIDC/Identity Platform flows. |
| Template context | `config.settings.TEMPLATES` context processors | Anonymous-safe context processors already return empty/false values. Do not add request-path DB work just for this notice. |
| Public/static content rendering | Django templates with autoescape; `documentation.views._render_markdown` as sanitizer precedent only | Prefer trusted template/static content. If Markdown/operator HTML is accepted, reuse the established bleach-style allowlist through a public helper rather than `mark_safe`. |
| Config binding | `config.settings` parsers, `config._runtime_env.required_runtime_env`, `config/_env_manifest.py`, `config/env-manifest.json` | New env settings must be non-secret, validated, and added to the manifest. Avoid env knobs when a template override is enough. |
| Logging | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | No display/dismissal logging is needed. If template configuration fails, log only validated template identifiers, not content, cookies, or headers. |
| Error leakage controls | Existing authored HTML errors and `shared.errors` for APIs | `/privacy/` is HTML, not JSON. Do not add an API envelope. If any JSON is introduced, use existing bounded error-message patterns. |
| Import boundaries | `.importlinter`, ADR-001 | Shared UI plumbing belongs in templates/static/config/shared. Do not introduce CTF, CMS, Mission Control, or risk-register cross-imports. |
| Tests | Existing Django view/template tests and Jest `static/js/*.test.js` | Test rendered behavior, storage persistence, public privacy route, and absence of `/terms/`. Avoid first-party internal patching. |
| Release notes | `changelog.d/README.md` convention | The implementation is user-visible and should add `changelog.d/67.added.md`. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: authenticated pages keep using Django sessions plus existing
  OIDC, Identity Platform, magic-link, or dev-login flows. The cookie notice is
  passive client UI and must not create a new login gate, auth middleware,
  session setting, user preference model, or bypass.
- CSRF and mutation surface: notice dismissal should not call the server. If a
  future server-side dismissal endpoint is introduced, it must stay behind
  session auth and `CsrfViewMiddleware`; this issue should not use
  `csrf_exempt`.
- Request validation surface: `/privacy/` should accept only GET/HEAD and no
  caller-controlled template, file path, or content parameter. Any
  environment-selected template name must be parsed in settings, rejected if
  blank, absolute, path-traversing, or outside the approved prefix, and covered
  by tests.
- Template/XSS surface: default placeholder copy is static and autoescaped.
  Operator-provided templates are trusted deployment artifacts. Do not render
  arbitrary HTML from environment variables, database rows, query strings, or
  uploaded files. If Markdown support is added, sanitize with a bounded
  allowlist.
- Secret-handling surface: session cookies, CSRF tokens, ID tokens, invite
  tokens, bearer tokens, Guacamole URLs, private IP overlays, and user emails
  must not be copied into notice state, privacy content, logs, docs examples,
  JavaScript console output, data attributes, or rendered legal placeholders.
- Config/env surface: a fixed template override needs no new config. A new
  setting must live in `config.settings` or a split settings module, be listed
  by `config/env-manifest.json`, and be wired through deployment renderers only
  as a non-secret value.
- OS/runtime exposure surface: do not put privacy notice body text, cookies,
  tokens, or legal commitments in process argv, Terraform outputs, Kubernetes
  ConfigMap examples, GitHub summaries, or shell-visible env dumps. A template
  name is non-secret; legal content belongs in files/templates controlled by
  the operator.
- Error-envelope surface: browser-facing failures should be generic HTML
  behavior. Missing/misconfigured operator content should fail loudly in tests
  or startup checks without serializing filesystem paths, template search
  internals, or raw exception text to users.
- Observability surface: no analytics, tracking event, beacon, metric,
  third-party script, or audit row is introduced by this issue. Existing ECS
  logs and request IDs are enough for route errors.
- Static-asset surface: assets are served through Django staticfiles and
  WhiteNoise. Include them with `{% static %}` so collectstatic/manifest storage
  continues to own cache-busting.
- Import-boundary surface: Python changes should stay in `config` for the root
  view or `shared` only if a reusable template/content helper is genuinely
  needed. Do not make feature apps import each other to share notice behavior.

## Extensibility Seam

The required seam is the operator-owned notice content include, not a consent
framework:

- notice UI state: a single versioned localStorage key for dismissal;
- notice copy: one shared partial that can link to `/privacy/`;
- privacy content: one replaceable template/static content file rendered by the
  public route; and
- optional future selector: a validated non-secret template-name setting if
  operators need deployment-time selection among packaged notice variants.

The obvious future variation is adding non-essential cookies. That should be a
separate consent-management decision with its own storage schema, preferences
UI, legal text, and audit/retention review. Do not pre-build that framework for
this issue.

## Whole-Repo Scope

Likely implementation touches some of:

- `shifter/shifter_platform/config/urls.py` and `config/views.py` for
  `/privacy/`.
- `shifter/shifter_platform/templates/**` for the public privacy shell,
  replaceable content template, and shared cookie notice partial.
- `shifter/shifter_platform/static/js/` and `static/css/` for dismissal
  behavior and styling.
- `shifter/shifter_platform/tests/config`, template tests, and
  `static/js/*.test.js` for route and localStorage behavior.
- `shifter/shifter_platform/documentation/docs/**` or `docs/dev/**` for
  operator replacement documentation.
- `config/env-manifest.json` and env renderers only if a new env setting is
  added.
- `changelog.d/67.added.md` for the user-visible portal change.

Usually out of scope:

- Terraform, Kubernetes, workflows, ADR registry, or secret-delivery changes
  unless a new deployment-facing setting or mounted content path is introduced.
- DRF, API tokens, audit tables, database migrations, service facades, or
  background jobs.

## Gotchas And Anti-Patterns

- Do not call the notice a consent banner. A dismissible disclosure for
  strictly necessary storage is not a granular consent mechanism.
- Do not add `/terms/`, terms-of-service copy, organization-specific policy
  text, controller identity, processor list, retention period, lawful basis,
  transfer statement, or rights workflow as OSS-authored commitments.
- Do not claim the portal is GDPR-compliant because this route exists.
- Do not add analytics, advertising tags, tracking pixels, telemetry beacons,
  third-party consent SDKs, or new non-essential cookies.
- Do not store dismissal in the Django session or user profile; that turns a
  local UI affordance into persistence and retention surface area.
- Do not put dismissal state, tokens, cookies, or user identifiers in query
  strings, hidden form fields, server logs, audit rows, or template context.
- Do not use `mark_safe`, raw HTML from env vars, or query-selected template
  names for operator content.
- Do not fork the notice markup across Mission Control, CTF, risk register,
  docs, auth, and scenario editor templates.
- Do not weaken `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  `SECURE_SSL_REDIRECT`, `ALLOWED_HOSTS`, CSRF trusted origins, or auth
  middleware to make the notice appear.
- Do not add a generic legal-policy service, repository, exception hierarchy,
  schema package, or preference model before there is a real domain contract.

## Non-Goals

- No implementation, route, template, JavaScript, CSS, settings, migration, or
  test change is made by this preflight note.
- No legal advice, approved privacy policy, terms of service, GDPR compliance
  determination, retention schedule, data-controller identity, processor list,
  transfer statement, or rights workflow is authored here.
- No non-essential cookies, analytics, advertising, tracking, preference center,
  consent logs, or consent APIs.
- No changes to authentication, session issuance, CSRF behavior, OIDC,
  Identity Platform, CTF magic links, or dev-login.
- No new Ground Control requirement or traceability link; issue #67 is the
  authoritative contract.

## Validation

For this documentation-only architecture preflight, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups should also run the stack-native checks for changed
surfaces, especially Django view/template tests, Jest tests for the static
notice script, `uv run ruff check .`, `uv run ruff format --check .`, and
`uv run lint-imports --config ../../.importlinter` from
`shifter/shifter_platform` when Python code changes.
