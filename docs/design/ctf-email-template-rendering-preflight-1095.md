# CTF Email Template Rendering Preflight - Issue 1095

## Scope

Issue #1095 is a requirement-free security hardening pass for custom
per-event CTF email templates. Organizer-authored `CTFEmailTemplate.html_body`
and `text_body` are untrusted template-like content and must not be rendered
with Django's template engine. Default filesystem email templates remain
trusted application templates and must continue through `shared.email`.

This is not a new notification system, a general templating framework, a
mail-delivery redesign, or a new CTF authorization model.

## Architectural Decisions

- Keep a hard boundary between trusted application templates and untrusted
  organizer-authored email bodies. `shared.email.render_template()` remains the
  canonical path for default templates under `templates/ctf/email/`; custom
  database templates must use a CTF-owned placeholder-only renderer.
- Render-time safety is mandatory even when persistence-time validation has
  already run. Stored rows can predate validators, arrive through admin/model
  writes, or be restored from backups, so `_render_email()` must fail closed on
  unsupported syntax instead of trusting the database.
- The placeholder grammar is only `{{ name }}` over an explicit allowlist of
  scalar values. Dotted attributes, filters, tags, blocks, loops, includes, and
  method calls are out of scope for organizer templates.
- Validation and rendering must share one CTF-domain parser/policy helper. Do
  not keep one regex in the API and another parser in the renderer.
- Subject overrides are stored as plain text today. If subjects ever gain
  placeholders, they must use the same safe helper and allowlist; do not route
  custom subjects through Django templates as a shortcut.
- Any migration or cleanup for existing `CTFEmailTemplate` rows must use the
  same policy shape as runtime validation, be idempotent, and avoid logging raw
  template bodies.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Trusted email rendering | `shared.email.render_template()` | Keep default non-custom templates on this path; they legitimately use Django tags, filters, i18n, conditionals, loops, and object attributes. |
| Email delivery | `shared.email.send_email()` via `ctf.services.notification._send_email()` | Do not reimplement `EmailMultiAlternatives`, async sending, sender selection, or delivery error handling. |
| Custom render entrypoint | `ctf.services.notification._render_email()` | Preserve the `(html_content, text_content, custom_subject)` contract and the `invitation` -> `invite` notification-type mapping. |
| Custom template persistence | `CTFEmailTemplate`, `CTFBaseModel.save()` / `full_clean()` | Model-level `clean()` is the broadest guard for API, admin, and direct model saves; view-only validation is not enough. |
| Organizer auth | `@login_required`, `@ctf_organizer_required`, `_resolve_owned_event_json()` | Keep event ownership checks at the view boundary for the JSON API. |
| Service auth pattern | `ctf.services.authorization.assert_actor_owns_event()` | If template write behavior moves into services, apply the same defense-in-depth pattern used by organizer-owned CTF content. |
| JSON body shape | `_parse_body_object()` and `_get_body_str()` in `ctf.views` | Reuse current 400-envelope parsing/type checks; do not add a second request parser or serializer only for templates. |
| Domain errors | `ctf.exceptions.CTFValidationError` and existing view `JsonResponse({"error": ...})` patterns | Do not create a parallel template exception hierarchy or leak raw parser internals to clients. |
| Logging | module loggers plus `shared.log_sanitize.safe_log_value()` | Log event/template ids, notification type, counts, and policy classes; never log raw HTML/text bodies, invite tokens, access URLs, participant emails without sanitization, or failure payloads. |
| Data migrations | Django migrations using `apps.get_model()` and historical models | Keep migration logic self-contained; do not import live services/models from migrations. |
| Architecture gates | `.importlinter`, `.ground-control.yaml`, `scripts/adr_guard/adr_guard.py` | CTF may depend on `shared`, not `engine` or `mission_control`; security checks must not be weakened. |

## Security Layers

- Auth surface: API writes stay behind `@login_required`,
  `@ctf_organizer_required`, and event ownership. This limits authorship but
  is not a sandbox, so render-time substitution still treats custom bodies as
  untrusted.
- Service boundary: notification sending, participant resend-invite, scheduled
  sends, and organizer failure/start/end notices all reach
  `ctf.services.notification._render_email()`. The safe renderer must cover
  every custom-template send path, not only the direct notification API.
- Template policy gate: the CTF-owned placeholder parser must reject `{% ... %}`,
  `{# ... #}`, dotted names, filters, bracket syntax, unmatched delimiters, and
  unknown placeholders. It must substitute only values produced by an explicit
  allowlist builder, not arbitrary objects from the current context dict.
- Scalar shaping: allowed values should be strings, ints, booleans, dates
  formatted deliberately, or URLs built by existing code. Do not expose
  `CTFEvent`, `CTFParticipant`, `User`, `RangeInstance`, failures lists, querysets,
  or other rich objects to the placeholder engine.
- Persistence validators: new or updated rows must be rejected before storage
  through API/model/admin paths. Existing active rows must be cleaned,
  soft-deleted, or otherwise made non-renderable when they contain unsupported
  syntax; soft-deleted rows should not silently re-enter the active render path.
- Secret-handling surface: invitation tokens, magic links, access URLs,
  participant emails, provisioning failure text, and custom bodies must not be
  logged, echoed in exception text, written to process argv, or captured in
  migration output.
- OS/runtime exposure: this issue should stay inside Django/Python string
  handling and database migrations. Do not shell out to a template linter, pass
  bodies in command-line arguments, write bodies to temp files, or add runtime
  environment variables.
- Error envelope: API validation failures should return the existing
  `{"error": ...}` JSON shape with a fixed, user-safe reason and field label.
  Send-time failures should fail closed for that recipient/template and log a
  sanitized operational event without exposing the body or traceback to
  participants.

## Extensibility Seam

The seam belongs in one CTF-owned safe-template helper parameterized by
`notification_type` and an allowlist map, for example:

- parser/validator for the placeholder-only grammar;
- renderer that accepts a body string plus an already-scalar allowlist;
- allowlist builder that maps each `NotificationType` to display-safe scalar
  keys such as event name, participant name, deliberately formatted event
  times, access URLs, announcement subject/body, or failure counts.

That lets the next variation add one approved placeholder or one notification
type without changing the grammar, the API parser, the migration cleanup, and
the render path independently. If future channels add SMS or in-app templates,
make the channel another explicit policy parameter; do not infer policy from a
template filename or from the raw context object shape.

## Gotchas And Anti-Patterns

- The local preflight found `ctf.views._validate_template_bodies()` still
  compiling request input with `django.template.Template`; the issue context
  says this was already hardened in #885, so the implementation must reconcile
  that mismatch and keep validation Django-free.
- Do not rely on "Django templates cannot execute arbitrary Python" as a
  security argument. Attribute traversal and no-arg method calls are enough to
  make organizer templates an information-exposure boundary.
- Do not pass the current rich `context` dict to the safe renderer and hope the
  parser prevents access. Build a separate scalar dictionary first.
- Do not use `string.Template`, `format_map`, Jinja sandboxing, or Django custom
  filters as a drop-in fix unless the chosen mechanism enforces the exact
  placeholder grammar and unknown-placeholder policy.
- Do not let default templates regress. Their Django tags, i18n blocks, filters,
  conditionals, loops, and object attributes are trusted application code.
- Do not add duplicate notification-type mappings, duplicate variable schemas,
  duplicate parsers, or endpoint-local validators.
- Do not log rejected bodies, rendered output, participant magic links, access
  URLs, or provisioning failure details as raw strings.

## Non-Goals

- Rewriting `CTFNotification`, scheduling, participant invitation lifecycle, or
  shared mail delivery.
- Changing default email template contents or removing Django template features
  from trusted filesystem templates.
- Introducing a general-purpose user-authored templating feature outside CTF
  email bodies.
- Adding new template storage models, new notification channels, new background
  workers, or new event workflow states.
- Changing CTF participant/organizer role semantics, scoring, range
  provisioning, or Guacamole/Mission Control integration.
