# Browser Security Policy Preflight (#1520)

Status: pre-implementation guidance

Date: 2026-07-11

Issue: GitHub #1520, "REV1 Security: add a staged browser security policy
baseline"

This issue is requirement-free. The GitHub issue title, body, acceptance
criteria, and `docs/architecture/rev1/security.md` are the shipping contract.
This note is intentionally not an implementation plan.

## Scope Boundary

Treat this as one portal-wide HTTP response policy spanning the legacy Django
templates and the Vite SPA, not as a template-by-template hardening feature or
an ingress-only header patch.

Keep these concepts separate:

1. Policy definition and staging: one reviewed CSP candidate, initially sent as
   `Content-Security-Policy-Report-Only`, with an explicit later enforcement
   mode.
2. Browser report transport: a narrow, unauthenticated, same-origin machine
   endpoint that accepts browser-generated violation formats.
3. Monitoring: normalized, bounded events in the existing application log
   pipeline and its provider-owned alert/query surface.
4. Source remediation: external static files and event listeners by default;
   reviewed Django nonces or stable hashes only where extraction is materially
   worse.
5. Governance: deviations from the global policy are dated ADR exceptions,
   not view-local decorators or undocumented allowlist growth.
6. Email HTML: `templates/ctf/email/**` is not a browser document surface and
   its mail-client-compatible inline CSS is not a CSP exception.

The baseline remains defense in depth. It does not replace output encoding,
DOM-XSS remediation, CSRF, authentication, authorization, host/origin checks,
WAF/Cloud Armor, upload validation, or WebSocket origin validation.

## Current Inventory

The tracked-source inventory on 2026-07-11 found:

| Surface | Current evidence | Boundary |
| --- | --- | --- |
| Inline script elements | 31 `<script>` elements without `src`: 30 executable blocks and one explicit `application/json` data block, across 27 templates | Executable blocks are enforcement debt. Inert data belongs in Django `json_script`; nine additional `json_script` filters render inert data blocks at runtime. |
| Inline event handlers | 65 `onclick` / `onchange` / `onsubmit` attributes, including handlers inside Scenario Editor DOM templates | Nonces do not authorize event-handler attributes. Move these to external listeners; do not use `unsafe-hashes`. |
| Portal inline CSS | One `<style>` block in `templates/privacy/notice.html`; zero browser-template `style=` attributes | Move the block through the existing static CSS pipeline. |
| Email inline CSS | 20 `style=` attributes under `templates/ctf/email/**` | Explicitly outside browser CSP. Preserve for mail-client compatibility. |
| Runtime inline-style writes | 47 direct writes: 21 in external `static/js`, 23 in legacy template scripts, and three React `style` props | These are enforcement debt under `style-src-attr 'none'`, even though they are not literal `style=` attributes in source. Replace them with bounded CSS classes or CSS custom properties before enforcement; nonces and hashes do not authorize DOM style-property writes. |
| Dynamic code execution | No `eval()` or `new Function()` match in tracked first-party JavaScript or checked-in vendor bundles | Keep both absent. Remote libraries and generated Vite output still require runtime/report-only verification. |
| DOM HTML sinks | Existing `innerHTML` use in Scenario Editor, Mission Control, CTF challenge feedback, sidebar, and terminal code | Do not expand these sinks while extracting scripts. Dynamic/user-derived values stay on `textContent` or reviewed DOM construction paths. |

The executable inline-script owners are:

- `templates/documentation/base.html`;
- `templates/scenario_editor/{form,list,yaml_create,yaml_editor}.html`;
- `templates/ctf/admin/{bracket_list,challenge_detail,event_force_delete,event_form,notification_form,participant_detail,participant_list,range_list}.html`;
- `templates/ctf/participant/{challenge_detail,range,scoreboard,walkthrough}.html`;
- `templates/mission_control/agents.html`, `settings.html`,
  `credentials/{add,detail,list}.html`, and
  `ngfw/{deprovision,detail,list,wizard}.html`, plus `dashboard.html`.

The source/origin inventory also includes:

- same-origin WhiteNoise/static and Vite assets;
- `cdn.jsdelivr.net` for Mermaid, participant Chart.js, and terminal xterm
  assets;
- Mermaid's incumbent `@10` ES-module import is only major-version pinned and
  has no SRI-capable import path. Give it an exact reviewed pin or move it into
  the existing checked-in/build asset pipeline before treating it as approved;
- `unpkg.com` for Split.js; unlike the other terminal assets, its incumbent
  entry has no SRI hash and must not be grandfathered silently;
- `www.gstatic.com` plus the Firebase authentication/token connection origins
  used by Identity Platform;
- provider-specific signed-upload connections: the exact S3 bucket/region host
  on AWS and `storage.googleapis.com` on GCP;
- same-origin HTTP and WebSocket connections;
- `data:` images used by the QR generator and static CSS.

Regenerate this inventory at implementation time. Static scanning is necessary
but not sufficient: xterm, Chart.js, Mermaid, Firebase, and the built SPA may
create styles or use code-generation paths only at runtime.

## Architecture Decisions

- Use Django 6.0's built-in
  `django.middleware.csp.ContentSecurityPolicyMiddleware`, `SECURE_CSP`,
  `SECURE_CSP_REPORT_ONLY`, `django.utils.csp.CSP`, and, only where reviewed
  nonces remain, `django.template.context_processors.csp`. Do not add
  `django-csp`, a custom CSP serializer, a custom nonce generator, or a second
  CSP header middleware.
- Where a reviewed executable inline element remains, include Django's
  `CSP.NONCE` sentinel in the applicable directive and render only the lazy
  per-response `{{ csp_nonce }}` on that element. A nonce setting or context
  processor without the sentinel is not an effective nonce policy; a nonce on
  an event handler or DOM style write is never effective.
- Keep the CSP middleware beside `SecurityMiddleware` and outside WhiteNoise in
  the global middleware chain so legacy HTML, the SPA host, redirects, errors,
  APIs, and built static responses pass through one boundary. A small custom
  middleware may set only the headers Django does not own:
  `Permissions-Policy` and `Reporting-Endpoints`.
- Keep one code-owned policy artifact. A validated `BROWSER_CSP_MODE` seam may
  select `report-only` or `enforce`; it must not accept a serialized policy or
  arbitrary source list from the environment. Invalid modes fail at settings
  import with `ImproperlyConfigured`.
- Start with the candidate in `SECURE_CSP_REPORT_ONLY` and an empty
  `SECURE_CSP`. Enforcement moves the same reviewed candidate to `SECURE_CSP`;
  it is not a separately copied policy. Reporting remains enabled after
  enforcement.
- Use a deny-by-default candidate: `default-src 'none'`; `base-uri`,
  `object-src`, `frame-src`, `media-src`, and `worker-src` set to `'none'`;
  `frame-ancestors 'none'`; `form-action 'self'`; `font-src 'self'`;
  `img-src 'self' data:`; and explicit `script-src`, `style-src`, and
  `connect-src` lists. Set `script-src-attr 'none'` and
  `style-src-attr 'none'` so inline handlers/styles cannot hide behind a broad
  fallback.
- Allow only exact currently required external origins. Never use `*`, broad
  `https:`, `data:` for scripts, `unsafe-inline`, `unsafe-eval`, or
  `unsafe-hashes`. Prefer the existing WhiteNoise/Vite and checked-in vendor
  paths to shrink CDN trust. Any retained CDN asset stays version-pinned and
  SRI-protected where the loading mechanism supports SRI.
- Build provider-dependent `connect-src` entries from the already resolved
  cloud/storage/auth configuration. Direct signed uploads are part of the
  browser contract; do not break them, allow all of `https:`, or introduce a
  second bucket/provider setting solely for CSP.
- Use both `report-uri /security/csp-report/` and a named `report-to csp`
  group backed by `Reporting-Endpoints: csp="/security/csp-report/"`. The W3C
  reporting channel is best effort, so a synthetic delivery check and operator
  query are required evidence; absence of reports is not proof of compliance.
  The monitored destination is complete only when the normalized event is
  queryable in each deployed provider and the existing operator notification
  path can detect failed synthetic delivery. Do not alert on raw violation
  volume until report-only noise has been baselined.
- Do not request violation code samples. `report-sample` can place page or user
  data in telemetry and is unnecessary for the static inventory.
- Make `SECURE_REFERRER_POLICY = "same-origin"` explicit. Django 6.0 currently
  supplies this value as a framework default, and the SPA repeats it in a meta
  element, but an implicit framework default is not the repository contract.
  Preserve the invite/registration response's stricter `no-referrer` override.
- Enable this exact initial permissions baseline globally:
  `accelerometer=(), autoplay=(), camera=(), display-capture=(),
  encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(),
  magnetometer=(), microphone=(), payment=(), picture-in-picture=(),
  publickey-credentials-create=(), publickey-credentials-get=(),
  screen-wake-lock=(), usb=(), web-share=(), xr-spatial-tracking=()`.
  Clipboard features are deliberately not disabled: terminal copy/paste and
  participant walkthrough copying use `navigator.clipboard` today.
- Do not use per-view CSP overrides as the normal extension mechanism. Django's
  override decorators replace the whole base policy rather than merging it.
  A truly unavoidable override requires a complete policy, narrow path,
  regression coverage, and a `docs/adr/exceptions.yaml` entry for ADR-036 with
  owner, reason, expiry, and affected paths.

## Browser Report Boundary

The same-origin collector is transport and observability plumbing, not a public
business API:

- Exact route and method: POST only at `/security/csp-report/`; no `/api/v1`
  schema, DRF serializer, API token scope, session requirement, model, or
  repository.
- Authentication/CSRF: deliberately anonymous and narrowly CSRF-exempt because
  browsers generate reports without an application CSRF token. It performs no
  privileged or domain mutation.
- Shape: accept the legacy `application/csp-report` object and the Reporting API
  `application/reports+json` batch. Bound the request bytes, batch length,
  nesting, string lengths, and accepted field set before logging.
- Output: fixed empty 204 for accepted reports and fixed empty 4xx responses
  for invalid method/media/size/shape. Never return parser exceptions, report
  contents, stack traces, or the shared API error envelope.
- Data minimization: discard code samples and `original-policy`; strip
  credentials, query strings, and fragments from document, blocked, referrer,
  and source URLs; keep only bounded origin/path, effective directive,
  disposition, status, and line/column fields. Treat every field as
  attacker-controlled.
- Logging: reuse `config._logging_config.ECSFormatter`, request IDs, and
  `shared.log_sanitize`. Extend the formatter's bounded label vocabulary if
  structured dimensions are needed; do not create a second JSON logger or log
  raw request bodies.
- Persistence: application logs are the evidence sink. Do not create a CSP
  report table, audit action, outbox event, queue, exception hierarchy, or
  retention job.
- Abuse boundary: keep the AWS WAF and GCP Cloud Armor in front. CSP payloads
  can legitimately resemble XSS/SQLi, so any body-inspection carve-out must be
  exact-path and retain method, body-size, reputation, and rate controls. Never
  disable a managed rule globally to make reports arrive. Enforce the small
  body limit at the edge as well as in the view: under ASGI, application-level
  parsing may occur only after the server has already spooled the request body.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1520 |
| --- | --- | --- |
| Global security headers | `config/settings.py` `SecurityMiddleware`, `XFrameOptionsMiddleware`, `SECURE_*`, `X_FRAME_OPTIONS` | Add explicit referrer policy and native CSP beside these; do not move header ownership to ALB/GCLB or templates. |
| CSP implementation | Django 6.0.6 `ContentSecurityPolicyMiddleware`, `CSP`, `SECURE_CSP*`, CSP context processor | One policy and Django-generated lazy per-response nonces. |
| Non-Django headers | `config/middleware.py` response middleware pattern | One narrow middleware for Permissions Policy and Reporting Endpoints only, using `setdefault`. |
| Static assets | `STATICFILES_DIRS`, WhiteNoise manifest storage, `Dockerfile` Vite build + `collectstatic`, `shared.spa.vite_asset_urls` | Externalize code/styles through the existing immutable asset path. |
| Template-to-JS data | Django `json_script`, existing static JS modules and `addEventListener` patterns | Do not replace inline assignments with templated JavaScript or unsafe HTML interpolation. |
| Third-party assets | `config/_terminal_assets.py`; `static/js/vendor/**`; participant Chart SRI; Vite/npm lock | Reuse pins and assets, close Split.js SRI debt and Mermaid's floating-major/import-integrity debt, and avoid a duplicate CDN registry. |
| Cloud/storage origin | `config/_cloud.py`; `shared.cloud` AWS/GCP storage adapters; signed-upload CORS modules | The CSP allowlist follows the incumbent provider endpoint, not a parallel upload-origin setting. |
| Logging and redaction | `config/_logging_config.py`, `config/_posture.py`, `shared/log_sanitize.py`, `RequestIDMiddleware` | Emit sanitized low-cardinality events and log the resolved non-secret policy mode at boot. |
| AWS telemetry | `module.ec2.log_group_name`, Docker `awslogs`, `platform/terraform/modules/log-aggregation`, environment SNS alert topic | Reuse the portal log group/aggregation and existing operator notification destination. Do not misuse capacity metric names for CSP events. |
| GCP telemetry | container stdout/stderr in GKE/Cloud Logging; Helm `platform-runtime` ConfigMap | Keep the application event provider-neutral; use the incumbent GCP log query/alert surface. |
| Edge abuse controls | `platform/terraform/modules/portal/alb` WAF; `platform/terraform/gcp/modules/portal/ingress` Cloud Armor | Exact-path report handling only; preserve all other managed rules and ingress boundaries. |
| Config inventory | `config/_env_manifest.py`, `config/env-manifest.json`, `scripts/gcp/render_runtime_env.py`, `shifter/installation/runtime_inventory.py` | Register the mode wherever it is environment-bound; do not hide a dynamic lookup from manifest checks. |
| Exception governance | `docs/adr/index.yaml`, `docs/adr/exceptions.yaml`, `adr_guard` expiry/schema validation | Policy waivers reference ADR-036 and carry owner, reason, expiry, and paths. |
| Regression tests | existing `tests/config/test_settings.py`, SPA host suites, legacy view suites, inline-style scans, and `scripts/stack-smoke/page_smoke.py` | Assert real middleware responses and built-image headers; extend existing scans rather than add per-app policy logic. |

## Cross-Cutting Layers

- Public edge and TLS: AWS requests pass ALB HTTPS, WAF, and the portal target;
  GCP requests pass managed TLS, Cloud Armor, GCLB, and the GKE service. The app
  remains the header authority. Proxies must neither overwrite nor concatenate
  a second CSP.
- Host/proxy validation: `HealthCheckMiddleware`, `ALLOWED_HOSTS`,
  `SECURE_PROXY_SSL_HEADER`, HTTPS redirect, and the path-scoped health admission
  stay unchanged. The report route receives no host bypass.
- HTTP middleware: request ID and in-flight accounting continue to bracket the
  request; Security, native CSP, WhiteNoise, sessions, locale, common, CSRF,
  authentication, messages, X-Frame-Options, and optional OIDC refresh retain
  their responsibilities. CSP does not replace any of them.
- WebSocket auth/origin: `AllowedHostsOriginValidator` and
  `AuthMiddlewareStack` remain authoritative. `connect-src` merely permits the
  browser connection and must not broaden accepted WebSocket origins.
- CSP shape validation: Django serializes mappings but does not validate CSP
  directive semantics. Use `CSP` constants, a code-owned directive map, exact
  response tests, browser/runtime reports, and an external syntax check in the
  validation evidence. Do not treat successful settings import as policy
  validation.
- Environment binding: only the bounded mode is a rollout parameter. If it is
  wired at runtime, AWS SSM/user-data/redeploy and GCP renderer/runtime-inventory
  paths must validate and carry the same enum. The full policy and reporting
  endpoint remain reviewed code-owned constants.
- Secret handling: a CSP nonce is per-response public authorization material,
  not a session/CSRF/request ID, credential, environment value, database field,
  or log field. Report URLs and payloads may contain sensitive query data even
  when browsers attempt to strip it; sanitize again server-side.
- OS/process exposure: the non-secret mode may cross container environment or
  Docker argv after enum validation. Never put a reporting-service credential,
  capability URL, nonce, raw policy, or report payload in process argv.
- Error envelopes: normal Django/DRF errors remain on their existing fixed or
  `shared.api.errors` surfaces and receive global headers. The report collector
  has a deliberately empty machine response and introduces no exception class.
- Persistence/retention: no application persistence. Existing CloudWatch/log
  aggregation and GCP logging own retention and monitoring; acceptance evidence
  must show a synthetic report reaches that surface.

## Extensibility Seam

The next reasonable change is promoting the candidate from report-only to
enforcement, followed by adding one new provider/browser capability without
forking policy by UI stack.

The seam belongs in one browser-policy settings module:

- input: validated `report-only` / `enforce` mode plus already-resolved
  provider/auth/storage origins;
- output: the mutually consistent `SECURE_CSP` and
  `SECURE_CSP_REPORT_ONLY` mappings, the reporting endpoint header, and the
  fixed Permissions/Referrer policies;
- invariant: legacy templates, SPA hosts, errors, redirects, and APIs receive
  the same response policy;
- forbidden input: a serialized CSP, comma-separated arbitrary origin list,
  secret-bearing report URL, or per-route mode from user data.

Adding a cloud storage provider or browser capability should update this one
origin/capability seam plus tests and deployment inventory, not settings,
middleware, templates, ALB, GCLB, and SPA code independently.

## Whole-Repo Scope For The Later Implementation

- Application boundary: `shifter/shifter_platform/config/{settings.py,middleware.py,urls.py,_logging_config.py,_posture.py}` and a focused browser-policy module.
- Browser surfaces: `templates/**`, `static/js/**`, `static/css/**`,
  `config/_terminal_assets.py`, and the Vite frontend only where inventory or
  remediation proves necessary.
- Tests: `tests/config`, representative legacy Mission Control/CTF suites, SPA
  host suites with flags both on and off, a generalized inline-code inventory
  scan, and built-image `scripts/stack-smoke/page_smoke.py` coverage.
- AWS runtime/monitoring when the mode or collector edge is wired:
  `platform/terraform/modules/portal/{ssm,ec2,alb}`, environment portal roots,
  `scripts/portal-deploy/deploy_portal.sh`, and the existing log aggregation /
  alert topic.
- GCP runtime/monitoring when wired: `scripts/gcp/render_runtime_env.py` and its
  tests, `shifter/installation/runtime_inventory.py`, Helm/Kustomize runtime
  config, `platform/terraform/gcp/modules/portal/ingress`, and Cloud Logging
  monitoring evidence.
- Governance/docs: `docs/adr/{index.yaml,exceptions.yaml}`, this preflight,
  operator security documentation, and a changelog fragment when behavior
  ships.

## Gotchas And Anti-Patterns

- Do not add a CSP meta tag. Report-only, `frame-ancestors`, and reporting
  semantics require HTTP headers, and the SPA meta referrer is not the global
  policy authority.
- Do not add `unsafe-inline` just to quiet the initial report stream. Report-only
  is expected to reveal current debt and provides no active protection.
- Do not assume a nonce fixes `onclick`, `onchange`, `onsubmit`, `style=`,
  `javascript:` URLs, DOM `.style` writes, or React `style` props. It authorizes
  matching script/style elements only.
- Do not reuse CSRF tokens, request IDs, session IDs, or one process-wide value
  as a CSP nonce. Do not cache full HTML containing a nonce.
- Do not hash template blocks containing dynamic data or translations. Move data
  through `json_script`; reserve hashes for byte-stable reviewed content.
- Do not turn on `unsafe-hashes` for event handlers. External listeners are the
  existing maintainable pattern.
- Do not let changing a CDN URL automatically expand CSP. Keep the source list
  reviewed and add a cross-check that configured assets are covered.
- Do not overlook signed S3/GCS uploads or Firebase API calls when tightening
  `connect-src`; same-origin page tests alone will miss them.
- Do not claim tracked-source `eval` scans prove generated or third-party code is
  clean. Exercise the built SPA, xterm, Chart, Mermaid, and Firebase paths under
  report-only.
- Do not log full reports, URL queries, `original-policy`, code samples, cookies,
  auth headers, or user identity. A report endpoint is attacker-controlled log
  ingress.
- Do not let WAF/Cloud Armor body signatures silently discard all reports, and
  do not globally weaken those signatures. Scope any carve-out to the exact
  report path and keep rate/size controls; a `Content-Length` check in the view
  is not an edge body-size control.
- Do not put the collector under authenticated DRF or create a second error
  schema. Browser report media types and trust semantics are different from the
  platform API.
- Do not create a CSP report model, repository, audit action, outbox, queue, or
  cleanup scheduler. The incumbent log pipeline already owns telemetry
  persistence and retention.
- Do not remove the invite response's `no-referrer`, X-Frame-Options, HSTS,
  no-sniff, secure cookies, CSRF, or WebSocket origin checks after adding CSP.
- Do not disable clipboard permissions: current terminal and walkthrough UX
  relies on them. Capability changes need usage inventory and browser tests.
- Do not treat email inline styles as browser-policy exceptions or migrate them
  through WhiteNoise.

## Non-Goals

- No issue implementation, header enablement, collector endpoint, infrastructure
  mutation, or enforcement transition in this preflight.
- No formal Ground Control requirement.
- No new authentication scheme, API DTO, domain exception hierarchy, database
  schema, repository, audit vocabulary, queue, or report-retention service.
- No replacement of OIDC/Identity Platform, signed object-storage uploads,
  WhiteNoise, Vite, WAF/Cloud Armor, or the existing logging stack.
- No general DOM-XSS/Trusted Types migration, COEP/CORP redesign, service worker,
  iframe/Guacamole embedding, or frontend rewrite.
- No change to HTML-email styling or mail-client compatibility.

## Standards And Framework References

- [Django 6.0 CSP guide](https://docs.djangoproject.com/en/6.0/howto/csp/)
- [Django 6.0 CSP reference](https://docs.djangoproject.com/en/6.0/ref/csp/)
- [Content Security Policy Level 3](https://w3c.github.io/webappsec-csp/)
- [Reporting API](https://w3c.github.io/reporting/)
- [Permissions Policy](https://w3c.github.io/webappsec-permissions-policy/)
