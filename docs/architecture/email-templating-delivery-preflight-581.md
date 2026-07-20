# Email Templating And Delivery Preflight

Issue: GitHub #581 / PLAT-103, shared email templating and delivery service.

This note records the architecture boundary for platform email. It is not an
implementation plan and does not require a new ADR: existing settings,
secret-handling, logging, template-rendering, and scheduler/outbox boundaries
already cover the risk.

## Decisions

- `shared.email` is the shared mail rendering and delivery entrypoint. Feature
  code should not construct `EmailMultiAlternatives`, select Django email
  backends, or catch SMTP/provider exceptions independently.
- Default application-owned templates are trusted Django templates. They live in
  filesystem template directories such as `templates/ctf/email/` and may use
  normal Django tags, filters, objects, and inline CSS needed for mail clients.
- Organizer-authored CTF template bodies are untrusted and must stay on the
  placeholder-only policy in `ctf.services.email_template`; never route them
  through Django's template engine.
- Shared email async semantics are fire-and-forget latency hiding, not durable
  delivery. If a future requirement needs retry, audit, or guaranteed delivery,
  introduce an explicit email outbox/worker contract instead of overloading the
  range event outbox or pretending an in-process thread pool is durable.
- Delivery failure is operational telemetry only. It must be logged with
  sanitized values and must not roll back, block, or alter the triggering user
  workflow unless that workflow explicitly requested a mail-send status.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Django email backend config | `config/_email.py`, `config/settings.py` re-export | Keep provider selection and `DEFAULT_FROM_EMAIL` here. Do not add feature-local backend selection or provider SDK calls. |
| Runtime env rendering | `scripts/gcp/render_runtime_env.py`, `shifter/installation/runtime_inventory.py`, `config/_env_manifest.py` | Any new email env binding must be represented in the manifest/inventory and renderer tests; do not hand-edit generated JSON. |
| Secret hydration | `shifter/shifter_platform/entrypoint.sh`, provider secret stores | ESP API keys are runtime secrets in `EMAIL_API_KEY`; only secret references such as `EMAIL_API_KEY_SECRET_ID` may appear in rendered env files. |
| Shared render/send helpers | `shared.email.render_template()`, `send_email()`, `send_email_async()` | Reuse the shared helper contract instead of duplicating MIME assembly, sender fallback, or fail-soft delivery handling. |
| CTF notification integration | `ctf.services.notification._render_email()` and `_send_email()` | Preserve the default/custom template split and the `invitation` to `invite` notification-type mapping. |
| Custom template policy | `ctf.services.email_template`, `CTFEmailTemplate.clean()` | Validation, render-time checks, migrations, and APIs must share one placeholder parser and allowlist. |
| Scheduled CTF work | `CTFScheduledTask` and scheduler handlers | Use this for scheduled notification workflow timing; do not create parallel scheduler rows for CTF email. |
| Durable event delivery | `RangeEventOutbox` and `drain_range_event_outbox` | This is for range/experiment event bus messages, not outbound email. Do not mix payload schemas or lifecycle states. |
| Logging sanitation | `shared.log_sanitize.safe_log_value()` / `safe_log_fingerprint()` | Log ids, counts, and fixed failure classes. Do not log bodies, rendered output, invite tokens, magic links, ESP keys, or raw provider payloads. |
| User-facing errors | `shared.errors`, `ctf.exceptions`, existing JSON envelopes | API/template validation errors must be authored and sanitized; provider exceptions must not escape to clients. |

## Cross-Cutting Layers

- Auth surface: email sending is a side effect of already-authorized feature
  workflows. The shared service must not grow authorization rules; callers keep
  using their existing view/service gates such as CTF organizer ownership.
- Template policy gate: trusted filesystem templates go through
  `shared.email.render_template()`. Custom CTF database bodies go through
  `allowed_placeholders()`, `find_template_violations()`,
  `build_safe_context()`, and `render_safe_body()` at render time as well as at
  write validation time.
- Secret-handling surface: `EMAIL_API_KEY`, SendGrid/Mailgun keys, SES/IAM
  credentials, invite tokens, magic-link URLs, access URLs, and rendered bodies
  are secrets or sensitive operational data. Keep them out of logs, argv,
  checked-in env, generated ConfigMaps, migration output, and exception text.
- Env-binding shape: `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`,
  `EMAIL_API_KEY_SECRET_ID`, `EMAIL_API_KEY`, `MAILGUN_SENDER_DOMAIN`,
  `CTF_FROM_EMAIL`, and any future sender knobs must pass through the existing
  settings modules, env manifest, runtime renderer, deployment docs, and smoke
  harnesses consistently.
- Config validators: production runtime imports must fail closed in
  `config/_email.py` or the renderer when a selected provider is incomplete.
  Console/no-delivery is acceptable only when selected explicitly.
- OS/process exposure: do not shell out to mail CLIs, template linters, or
  provider tools with subjects, bodies, recipient lists, tokens, or API keys in
  command-line arguments. Keep delivery inside Django/Python provider backends.
- Error-envelope surface: send failures are logged and suppressed by the shared
  helper. Public API responses should report the triggering operation's result,
  not raw SMTP/provider errors or stack traces.
- Transaction boundary: when a triggering action writes database state and then
  sends mail, capture a scalar render context and dispatch after commit
  (`transaction.on_commit`) so emails do not announce rolled-back state.

## Extensibility Seam

The useful seam is an explicit template key plus scalar context contract, not a
new templating framework. Future default notifications should add a filesystem
template pair and call `shared.email.render_template(template_path, context)`.
Future custom CTF placeholders should add one notification-type allowlist entry
and one scalar in `build_safe_context()`.

Sender variation belongs behind the existing `from_email` parameter and
`config/_email.py` backend settings. Queue/durability variation belongs behind a
separate email outbox/worker contract if a future requirement raises delivery
from best-effort to guaranteed.

## Gotchas And Anti-Patterns

- Do not conflate trusted Django templates with organizer-authored placeholder
  templates. The model help text may still mention Django syntax, but runtime
  policy is placeholder-only for custom CTF bodies.
- Do not pass rich models, querysets, users, range state, provider responses, or
  arbitrary context dicts into an untrusted renderer. Flatten to allowed scalar
  strings first.
- Do not add feature-local email schemas, exception hierarchies, log redactors,
  settings parsers, provider clients, or retry loops when an incumbent already
  owns that concern.
- Do not claim fire-and-forget thread-pool delivery is reliable. Worker restart,
  process exit, executor saturation, or unbounded queue growth can lose or delay
  messages.
- Do not let async rendering perform database reads on long-lived pool threads
  without Django DB hygiene (`close_old_connections`) and bounded admission.
- Do not let mail send status become the source of truth for domain state.
  Notification records may count attempted/sent messages, but business actions
  must remain authoritative in their own models.

## Non-Goals

- No redesign of Django settings, provider selection, secret hydration, or
  deployment runtime env generation.
- No new mail provider abstraction, Celery deployment, durable email outbox, or
  retry/DLQ semantics for PLAT-103's current SHOULD-level best-effort delivery.
- No new CTF notification storage model, scheduler model, authorization model,
  or custom-template grammar.
- No removal of Django template features from trusted filesystem templates and
  no removal of inline CSS from HTML email templates.
- No changes to range event outbox semantics, WebSocket notifications,
  Guacamole bootstrap, or CTF range scheduling except as callers of the shared
  email service.
