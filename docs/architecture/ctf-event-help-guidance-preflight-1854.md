# Per-Event CTF Help Guidance Preflight (#1854)

Status: pre-implementation guidance

Issue: GitHub #1854, "Allow per-CTF-event customizable help and guidance
docs for participants"

Requirement: none. The issue title, body, and acceptance criteria are the
shipping contract.

This note fixes the repository-wide boundaries for event-specific participant
guidance. It does not implement the feature or prescribe an implementation
sequence. No new ADR is required while the work remains inside ADR-001
(service boundaries), ADR-013/029 (shared SPA and canonical API), ADR-036
(browser security), and ADR-040 (runtime-first OpenAPI contract).

## Accepted Deviations (implementation, #1854)

Two boundaries below were changed by an explicit product decision at
implementation time; the shipped design follows these, and the rest of the note
remains binding.

1. **Separate "Briefing" surface, not a replacement of `/ctf/help/`.** The
   sections below render guidance by replacing the generic help body and name a
   "new participant route/navigation concept" a non-goal. The accepted decision
   is instead a dedicated participant **Briefing** surface at `/ctf/briefing/`
   (SPA route + a conditional entry point on the event home page); the generic
   Help route and its content are left untouched. The event-owned storage,
   reserved-slug singleton, sanitize-at-render, bounds, authorization, and
   untranslated-boundary decisions are unchanged.
2. **Briefing is SPA-only; no legacy renderer.** Because `CTFEventPage` is an
   SPA-only concept (CTF-1303 shipped no legacy Django template/view for custom
   pages), the Briefing is likewise SPA-only and rendered through
   `MarkdownContent`/`react-markdown`. There is therefore no legacy Django
   briefing view/template and no server-side `markdown`+`bleach` renderer in
   this change — that obligation below was premised on replacing the *legacy*
   `help.html` body, which is no longer touched. Legacy `templates/ctf/help.html`
   stays generic and unchanged, satisfying the no-regression criterion.

## Architecture Decisions

### Reuse the event-page concept

`CTFEventPage` is already the per-event, organizer-authored Markdown concept.
Its organizer CRUD, participant projection, soft-delete behavior, per-event
slug uniqueness, SPA query hooks, and `MarkdownContent` renderer are the
canonical incumbents. Help guidance must specialize that concept; it must not
add a `help`/`briefing` text field to `CTFEvent`, another page model, a JSON
blob, a scenario-side database row, or a second serializer hierarchy.

Reserve the exact event-page slug `help` for the event's participant guidance.
Define that value once in CTF-owned code and resolve it through one event-page
service/query boundary; do not scatter title comparisons or magic strings
through views and components. The existing conditional unique constraint on
`(event, slug)` makes this a per-event singleton. Soft-deleting that page
restores fallback behavior.

The organizer-facing event-page editor remains the authoring surface. It should
make the reserved help page discoverable and editable rather than introducing
a separate event-form field or workflow. Existing non-help custom pages remain
ordinary event pages.

The participant surface stays at `/ctf/help/`. A confirmed active-event help
page replaces the generic help body because generic onboarding can contradict
event-specific instructions. When no active help page exists, each rollout
mode renders its existing generic help unchanged:

- legacy mode retains `templates/ctf/help.html` and its Django translations;
- SPA mode retains the current `HelpPage.tsx` generic topics.

An API/database/read failure is not proof that guidance is absent. It must
render the incumbent bounded error/retry state rather than silently showing
potentially wrong generic instructions.

### Guidance is event-owned, not scenario-owned

The accepted persistence owner is the event instance. The same scenario may be
run with different dates, access paths, credentials policy, and onboarding, so
the participant read must never query CMS, scenario files, object storage, or
`scenario_id` at request time.

Scenario-supplied defaults are a future source adapter, not a second runtime
concept. Such an adapter may validate/import a snapshot into the same reserved
event page through the same CTF service boundary. It must not extend the
challenge-only CTF content hydration contract silently, couple help rendering
to `CTFContentHydrationReceipt`, or mark challenge content as drifted merely
because an organizer edits guidance.

### Store Markdown source; make rendering safe by construction

Store bounded Markdown source so organizers can edit it. Sanitization belongs
at every HTML output boundary, not as a one-time destructive write transform.
No path may interpret guidance as a Django template, React HTML, executable
code, or a placeholder language.

- SPA rendering reuses `frontend/src/features/ctf/MarkdownContent.tsx` and
  `react-markdown`. Raw HTML stays disabled: no `rehype-raw`,
  `dangerouslySetInnerHTML`, DOM parser shortcut, or component-local Markdown
  renderer. Pin an explicit safe URL/element policy for guidance rather than
  relying on library defaults.
- Legacy rendering uses one CTF-owned renderer built from the already-declared
  `markdown` and `bleach` dependencies. Convert Markdown, then clean the
  produced HTML with an explicit allowlist before marking it safe. Do not clean
  Markdown source and do not call `mark_safe` before cleaning.
- Guidance permits text structure, lists, code, and safe links. It does not
  permit raw HTML, styles, forms, scripts, SVG/MathML, iframes, objects,
  embeds, images/data URLs, event-handler attributes, or
  `javascript:`/`data:`/`vbscript:`/`file:` URLs. External links must use the
  existing safe referrer posture and non-opener relationship when opened in a
  new context.

The global CSP in `config/_browser_security.py` is defense in depth, not the
sanitizer. It can run in report-only mode and currently allows `data:` images,
so it cannot make an unsafe Markdown renderer acceptable. This feature needs
no new CSP origin.

### Keep authorization and mutation policy at existing boundaries

Organizer writes continue through `CTF_ORGANIZER_PERMISSIONS`,
`ctf:event:write`, `_resolve_owned_event`, session CSRF/API-token scope checks,
and service-layer `assert_actor_owns_event`. The existing custom-page views
currently mutate `CTFEventPage` directly; help work must not add another direct
ORM path. Factor page create/update/delete/read behavior behind one CTF-owned
service boundary and have the existing page API and help lookup reuse it.

Participant reads continue through `CTF_PARTICIPANT_PERMISSIONS`,
`ctf:play:read`, and `_resolve_active_participant`. The event comes only from
the actor's active participant context; never accept an event id, slug override,
or scenario id from the participant request. Legacy mode must apply the same
active-event selection rule. Anonymous or authenticated non-participant access
may retain the generic public help, but it must never reveal an event page.

Writes must retain `CTFBaseModel.full_clean()`, the active-row manager, soft
delete, and the database uniqueness constraint. Bound the title, slug, body
characters/UTF-8 bytes, and per-event page count in the authoritative
serializer/service policy before persistence. Use the database constraint as
the concurrency backstop and translate a duplicate-help race into the shared
controlled conflict/validation response, never a 500.

### The untranslated boundary is explicit

Organizer-authored guidance is stored and shown verbatim in the organizer's
chosen language. Shifter does not machine-translate it and does not extract it
into Django message catalogs. The editor and organizer documentation must say
that the body is not translated and that the organizer owns its language.
Platform-owned chrome remains translatable; the no-guidance legacy fallback
continues to use the existing `{% trans %}`/`{% blocktrans %}` strings.

Do not add a nominal locale field without a selection and fallback contract.
If localized variants are later required, centralizing lookup behind the
event-page service allows selection to evolve to `(event, slug, locale)` without
changing the participant route or creating another content store.

## Cross-Cutting Incumbents And Obligations

| Layer | Canonical incumbent | Obligation |
| --- | --- | --- |
| Persistence | `ctf.models.CTFEventPage`, `CTFBaseModel`, `SoftDeleteManager`, `unique_active_ctf_event_page_slug` | Reuse the row, validation-on-save, active-only reads, soft deletion, ordering, and DB singleton. Do not add an event field/model/JSON schema. |
| Organizer API | `ctf.api.organizer.insights.EventPagesView` / `EventPageDetailView`, `EventPageWriteSerializer` | Reuse the existing CRUD and response schema; add bounded body/page-count policy once and route mutation through a CTF service. |
| Organizer authority | `CTF_ORGANIZER_PERMISSIONS`, `HasCTFEndpointScope`, `_resolve_owned_event`, `assert_actor_owns_event` | Require active session or scoped token, organizer role, `ctf:event:write`, exact event ownership, and service-layer defense in depth. |
| Participant API | `ParticipantPagesView`, `_resolve_active_participant`, `EventPageSerializer`, `ctf:play:read` | Resolve only the actor's active event. Reuse the page DTO; do not expose an organizer-selected event or deleted page. |
| SPA transport | `frontend/src/api/client.ts`, `useCtfPages`, `ctfKeys`, generated `schema.d.ts` | Keep same-origin session credentials, CSRF on writes, request IDs, TanStack caching, and typed shared errors. Invalidate both organizer and participant page keys after page mutation. |
| SPA rendering | `MarkdownContent.tsx`, `react-markdown`, `remark-gfm` | Keep raw HTML inert and add the bounded guidance element/URL policy at the canonical renderer, not in `HelpPage`. |
| Legacy rendering | Django template autoescape plus declared `markdown`/`bleach` packages | Use one allowlist renderer and pass only cleaned output to the template. Preserve the existing template as the absent-guidance fallback. |
| Browser policy | `config/_browser_security.py`, Django CSP middleware, referrer and permissions policies | Keep deny-by-default browser headers; request no new origins and do not rely on report-only CSP as sanitization. |
| Validation | `EventPageWriteSerializer`, model `full_clean()`, DB constraint | Apply one shared content-size limit and closed render policy; do not duplicate validators in a form, component, and service with different values. |
| Errors | `_CtfApiError`, `shared.api.errors`, SPA `ApiError` / `describeMutationError` | Return stable codes, controlled messages, field details, and request id. Never return Markdown fragments, sanitizer diagnostics, SQL errors, or exception strings. |
| Logging | `CTFBaseModel` lifecycle logs, `shared.log_sanitize` | Log sanitized/fingerprinted event/page identifiers, outcome, and bounded lengths only. Never log guidance bodies or links. |
| Audit | `shared.audit` and `ctf.services.audit` | Record guidance mutations with existing `CONFIG` plus `CREATE`/`UPDATE`/`DELETE` vocabulary and actor attribution; record ids/lengths, not body content. Do not add an audit table or make audit payloads a second content store. |
| API contract | runtime DRF serializers/annotations, `openapi/v1.json`, generated `frontend/src/api/schema.d.ts`, ADR-040 | Keep runtime schema authoritative and regenerate artifacts; do not hand-edit generated contracts or create a help-only duplicate DTO. |
| Rollout | `PLATFORM_SPA_ENABLED`, `CTF_WORKSPACE_SPA_ENABLED`, `ctf.urls._page` | Preserve SPA/legacy route parity and rollback. No new flag or environment setting is needed. |
| Architecture/workflow | ADR-001/013/029/036/040, `.importlinter`, layer-import rules, ADR guard | Keep the feature inside CTF plus shared cross-cutting helpers and preserve all repository gates. |

## Security And Runtime Path

The intended data path is:

`organizer JSON/form input -> DRF/form shape and size validation -> organizer
role/scope/ownership -> CTF page service -> model full_clean + DB constraint ->
raw Markdown row -> active-event participant lookup -> safe SPA or legacy
renderer -> global browser headers`.

Every cross-cutting gate on that path has a distinct job:

- **Authentication and request integrity:** Django session/API-token
  authentication, active-actor checks, token scopes, and CSRF protect the write.
- **Authorization:** event ownership is checked at the HTTP boundary and again
  in the CTF service. Participant selection is active-event scoped.
- **Shape/resource validation:** serializer/service/model bounds prevent
  unbounded request, database, response, and render work. The render allowlist
  is not a substitute for those bounds.
- **Persistence/concurrency:** atomic mutation plus the conditional unique
  constraint preserves the singleton under concurrent creates; soft deletion
  controls fallback.
- **Output safety:** source remains inert data. Both rollout paths apply their
  output-context policy on every render.
- **Browser containment:** CSP, referrer policy, same-origin fetches, and secure
  cookies remain unchanged as defense in depth.
- **Error/log containment:** shared envelopes and sanitizers prevent bodies,
  links, SQL/sanitizer detail, and stack traces crossing error or log surfaces.

Guidance is participant-visible plaintext data, not a secret store. The editor
must warn organizers not to paste flags, passwords, invitation/reset tokens,
presigned URLs, or participant-specific credentials. In particular, do not
interpolate `participant_password_override`, range credentials, environment
variables, or template placeholders into Markdown. The body never belongs in
an environment variable, process argument, shell command, temporary file,
object-storage key, metric label, or trace attribute.

There is no provider, Terraform, Kubernetes, host-network, filesystem, CLI, or
subprocess change. Runtime exposure is limited to HTTP JSON/form bodies,
database text, HTML/React output, and the existing application logs/audit
surface.

## Gotchas And Anti-Patterns

- Do not use `CTFEvent.description` or `rules` as help storage; their meaning and
  placement already differ.
- Do not read `scenarios/<name>/help.html` at participant-request time, import
  arbitrary scenario HTML, or make CMS/scenario access imply CTF authorization.
- Do not duplicate the page model, write serializer, exception hierarchy,
  ownership checks, Markdown renderer, fetch client, query cache, or fallback
  copy.
- Do not key behavior on the mutable display title `"Help"`; use the one
  reserved slug constant.
- Do not show the reserved help page again in the generic event-pages accordion
  when it already owns `/ctf/help/`.
- Do not treat a fetch failure as an empty result. Fallback is allowed only
  after a successful lookup proves the page is absent.
- Do not sanitize only on write. Stored rows can predate policy, be restored,
  or arrive through admin/data operations; every render must remain safe.
- Do not enable raw HTML for Markdown, trust CSP to stop XSS, permit images or
  embeds, or add broad sanitizer tags/protocols for one worked example.
- Do not leak organizer content through validation messages, logs, audit state,
  analytics labels, OpenAPI examples, or snapshots.
- Do not forget multi-event users, disqualified-but-view-eligible reads,
  soft-deleted pages, duplicate-create races, SPA cache invalidation, legacy
  rollback, or sanitizer/library upgrade regression tests.
- Do not silently claim platform translation for organizer prose. Keep the
  untranslated contract visible in the editor and documentation.

Hostile render tests must cover raw `<script>`, event-handler attributes,
`javascript:` and `data:` links, image/error payloads, iframe/object/embed,
SVG/MathML, malformed Markdown, deep nesting, long links/code blocks, and
content at/over the size boundary in both SPA and legacy modes. Access evidence
must cover another organizer's event, participant event switching, anonymous
generic help, absent/deleted guidance fallback, and API failure without
fallback. Contract, frontend typecheck/lint/Vitest/axe/build, CTF Django tests,
import-linter, and ADR guard remain the applicable gates.

## Non-Goals And Boundaries

- No scenario-pack schema or CTF challenge-hydration contract change.
- No automatic import from `autarchy-ai/penumbra-scenarios`; its POLARIS prose
  is a worked content example only.
- No WYSIWYG editor, file upload, remote embed, asset proxy, template variables,
  secret substitution, or participant-specific personalization.
- No locale negotiation or machine translation; organizer prose is explicitly
  untranslated for this issue.
- No new participant route, navigation concept, API version, authentication
  mechanism, environment variable, rollout flag, sanitizer dependency, audit
  store, or observability backend.
- No redesign of generic help, event rules/descriptions, arbitrary custom-page
  navigation, scenario authoring, or event lifecycle policy.
