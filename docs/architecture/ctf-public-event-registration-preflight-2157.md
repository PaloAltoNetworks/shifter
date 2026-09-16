# CTF Public Event Registration Preflight (#2157)

Status: pre-implementation guidance

Date: 2026-09-14. Repository baseline: `ab5bcbdcd`.

Requirements: none; GitHub issue #2157 is the authoritative contract.

This note fixes the public/private, intake/admission, and publication boundaries
for an opt-in event splash and registration page. It adds no runtime route,
model, migration, API, or UI behavior and is not an implementation plan.

## Decision and concept boundary

The public page is an explicitly published, bounded projection of one CTF event.
It is not a public version of the authenticated participant SPA and it does not
make an event, workspace, participant roster, or arbitrary event page public.

- Add one event-owned boolean publication switch, defaulting to false at both
  model and migration layers. Event status, content presence, scoreboard
  visibility, or workspace membership must never imply publication. An
  organizer must enable each event deliberately and can disable it immediately.
  The enable control previews the exact public projection so the organizer sees
  what enabling will disclose.
- Use the existing immutable event UUID as the v1 public locator. Do not add a
  slug table or mutable name-derived identity for v1.
- Render an exact, server-owned Django GET/POST route before the CTF SPA
  catch-all. Keep `shared.spa_host.platform_spa_host` authenticated and keep the
  main React bootstrap, route guards, and participant account boundary intact.
- Treat an anonymous submission as an untrusted **registration request**, not a
  participant, invitation, user, workspace member, reserved seat, team member,
  or range request. Store it in one CTF-owned pending-intake aggregate.
- V1 submission means only “request received.” It performs no account or range
  provisioning and sends no email, webhook, password, invite token, or other
  externally amplified effect. Organizer approval, when supplied, is a separate
  authenticated participant-admission command.

`CTFParticipant` deliberately has no pending or invited lifecycle: organizer
add/import/generate paths create an isolated user and a registered participant.
Calling those paths from an anonymous request would conflate untrusted intake,
capacity admission, credentials, access, provisioning, and retention. Do not
add a synthetic `PENDING` participant status or reuse `WorkspaceInvitation`,
team invite codes, password-reset tokens, or event-page rows to represent intake.

No new ADR is required while this remains a CTF-owned aggregate that preserves
ADR-001 layer ownership, ADR-013 public error safety, ADR-036 audit vocabulary,
ADR-040 runtime-first API contracts, ADR-046 workspace isolation, ADR-051 CTF
workspace confinement, and ADR-052 event capability authorization. A generic
platform registration domain, workspace-derived CTF authority, automatic
cross-domain membership/provisioning, or externally hosted public content would
need a separate accepted decision.

## Public visibility and publication projection

One CTF service seam must resolve public state from `(event_public_id, at)` and
return only a closed presentation projection plus an open/closed disposition.
GET and POST use the same service policy; templates and views do not reconstruct
event state. `at` is an injected, timezone-aware instant so deadline behavior is
defined and testable.

The page is discoverable only when the event is live, not soft-deleted, explicitly
enabled, bound to a non-null `workspace_id`, and in `EventStatus.REGISTRATION`.
Missing, deleted, disabled, unbound, and lifecycle-ineligible events return the
same metadata-free 404 page. This is defense in depth for legacy rows while the
current nullable workspace migration/model shape remains wider than ADR-051's
target invariant. Enabling an unbound event must fail validation. The durable
configuration should also prevent an enabled/unbound combination with a database
check; model validation alone is bypassable by bulk/queryset writes.

Use `CTFEvent.effective_registration_deadline` as the only registration cutoff.
At `now >= effective_registration_deadline`, submission is closed. While the
event remains in `REGISTRATION`, an explicitly enabled page may stay visible
with an authored “registration closed” state; other event statuses are not
public in v1. A status change never toggles the publication switch.

The public allowlist is the event UUID already present in the route, name,
event start/end, effective registration deadline, and a bounded safe-text
description. It excludes owner/staff/workspace details, scenario and range
configuration, capacity hints and counts, participants and teams, rules,
challenges, pages, invite codes, credentials, and all internal relationships.
Times use the repository's timezone-aware values and one stated display zone.

`CTFEventPage` and its `briefing` reserved slug remain authenticated participant
content. They have no public-audience classification, and exposing all page rows
would silently publish organizer-authored material. Render the existing event
description as escaped text for v1: the repository has a safe React Markdown
renderer, but no canonical server-side public Markdown renderer. Django template
autoescaping stays enabled; do not use `mark_safe`, raw HTML, or a private-page
renderer in the public path. Apply one authored description size bound at the
public projection/publish boundary and fail closed or omit oversized legacy
content rather than creating a view-local rule.

`logo_url` accepts arbitrary URLs, and `theme_color` is not fully protected from
invalid direct writes. Do not issue a visitor-side request to an organizer URL,
weaken CSP, or emit dynamic inline style. V1 may use Shifter-owned static branding.
If the event logo is shown, the public projector must accept only same-origin
HTTPS assets resolved against `shared.site_url.validated_site_url()` and omit any
invalid legacy value. Rich public Markdown, externally hosted branding, or an
explicit public event-page audience is a later publication-policy change.

## Intake persistence and admission

The pending aggregate belongs under `ctf.models` and extends `CTFBaseModel` for
UUID identity, timestamps, soft deletion, and `full_clean()` on normal saves. Its
minimum PII is name and normalized email, scoped to one event. Use a conditional
database uniqueness constraint for one live normalized email per event and a
bounded event/disposition/time index for organizer review. Do not collect a
password, phone, affiliation, provider identity, team choice, or free-form data
that v1 does not need.

The POST service owns normalization, deadline/publication policy, idempotency,
and persistence. Within `transaction.atomic()`, lock the event row, re-read the
publication switch, workspace binding, status, and effective deadline, then
insert or observe the unique request. This shared event mutex linearizes submit
with disable/lifecycle changes only when the toggle and relevant lifecycle
mutations acquire that mutex too; every participating writer must lock before
its decisive state check and commit. Map a uniqueness race to the same generic
success as an existing request; do not expose whether an email is already a
request, participant, invitation, or platform account.

Pending requests do not consume `max_participants`, workspace quota, participant
capacity, or range capacity. Apply a separate bounded outstanding-request limit
under the event lock so a distributed sender cannot grow the intake table without
bound. At approval time, recheck current participant/team/capacity policy; intake
time does not reserve a seat.

If organizer review/conversion is in scope, expose requests through a separate,
bounded, paginated organizer DTO under the existing participant capability. Do
not union fake pending participants into `ParticipantSummarySerializer`. Approval
must enter one canonical participant-admission transaction that owns the existing
event lock, participant/team capacity, normalized-email uniqueness,
`provision_participant_seat`, and provisioning wake-up. Refactor that incumbent
seam if necessary rather than duplicating its checks. Rejection/approval/expiry
is an explicit request disposition and strict audited mutation; the public POST
does not receive participant credentials.

Use the existing `CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS` policy and the CTF
scheduler's established purge cycle unless product policy deliberately requires
a separate documented retention period. Pending and rejected PII must be
anonymized or removed after the bounded event-relative retention window, including
cancelled events. Extending the incumbent purge owner is preferable to a second
cleanup daemon. The public page must link the current `/privacy/` surface, and the
enable control must warn organizers that the repository's privacy copy is an
operator-supplied placeholder; do not make unsupported compliance claims.

## Canonical incumbents to reuse

| Concern | Canonical incumbent | Required use |
| --- | --- | --- |
| Event configuration | `ctf.models.CTFEvent`; `EventWriteSerializer` / `EventDetailSerializer`; `ctf.services.event._crud._EVENT_MUTABLE_FIELDS` | Put the one opt-in flag in the existing event configuration path. Default it off and validate publication there; do not create a second settings object or env flag. |
| Event timing/state | `EventStatus.REGISTRATION`; `CTFEvent.effective_registration_deadline`; event lifecycle services | Centralize visible/open/closed policy and use one exact deadline inequality. Do not copy time checks into template, form, API, and service. |
| Event content | `CTFEvent` metadata; `ctf.services.event.pages`; `frontend/src/features/ctf/MarkdownContent.tsx` | Publish only the explicit safe projection. Keep `CTFEventPage` participant-scoped and do not copy the React renderer into a server template. |
| Public browser route | `workspaces.public_views` response hardening; `ctf.urls`; Django forms/templates/CSRF middleware | Use an exact server-rendered route, `never_cache`, safe methods, CSRF, autoescape, no-store/no-referrer headers, and no public catch-all. |
| Organizer authority | `CTF_ORGANIZER_PERMISSIONS`; `ctf.api.organizer._base._resolve_owned_event`; `EventCapability.CONFIG` / `PARTICIPANTS`; exact `ctf:event:{read,write}` scopes | Toggle requires CONFIG; review and disposition require PARTICIPANTS. Platform admission, token scope, and event capability all remain additive. |
| Participant admission | `ctf.services.participant.lifecycle.add_participant`; `ctf.services.participant.accounts.provision_participant_seat` | Preserve the one account/participant/provisioning boundary for approved intake. Public submission never calls it directly. |
| Model behavior | `CTFBaseModel`; active managers; model/DB constraints; `transaction.atomic()` and `select_for_update()` | Enforce soft-delete, validation, uniqueness, and concurrency durably. Do not rely on serializer or UI checks alone. |
| Rate limiting | `shared.rate_limit.consume_fixed_window`; `caches["launch_rate_limit"]`; `shared.audit.get_client_ip` | Use atomic cross-worker source/event/fleet budgets, trusted proxy parsing, and hashed source keys. Charge malformed attempts and fail closed on cache failure. |
| Errors | `ctf.exceptions`; `_CtfApiError`; `shared.api.errors.api_error_response` | Reuse CTF service exceptions and the v1 envelope for organizer JSON. Public HTML uses fixed authored states and never renders exception or database text. |
| Audit/logs | `shared.audit`; CTF audit helpers; `RequestIDMiddleware`; `shared.log_sanitize`; ECS logging | Strict-audit toggle and disposition with IDs/state only. Log bounded outcome/reason and request correlation; never log registration PII or request bodies. |
| URL generation/config | `shared.site_url.validated_site_url`; existing Redis and retention settings; environment manifest/install inventories | Build share links from validated `SITE_URL`, not request Host. This design needs no new secret, environment variable, CLI argument, or provider config. |
| API/SPA contracts | Runtime DRF serializers, `openapi/v1.json`, generated `frontend/src/api/schema.d.ts`, shared frontend API clients | Regenerate published types for organizer field/endpoints; do not hand-edit the schema or introduce a second client/error contract. |

## Cross-cutting security and runtime layers

1. **Cloud edge.** AWS WAF managed rules/coarse IP limiting and GCP Cloud Armor
   request filtering remain additive defenses. Their capabilities differ, so
   the application limiter is mandatory and provider-neutral; no infrastructure
   change is needed for v1.
2. **Host and transport.** Existing load balancer/ingress TLS, `ALLOWED_HOSTS`,
   HTTPS redirect, HSTS, trusted proxy handling, and `SecurityMiddleware` run
   before the view. Build outbound share links only from validated `SITE_URL`.
3. **Routing and account boundary.** The exact public route precedes the CTF SPA
   catch-all. It neither weakens `platform_spa_host` nor treats an authenticated
   or temporary-account session as public-registration authority.
4. **Request admission.** `RequestIDMiddleware`, `CsrfViewMiddleware`, explicit
   safe/POST method decorators, a Django `Form`, tight body/field limits, and no
   file upload shape the request. Rate limits run before detailed validation and
   consume failures too. Do not widen Django upload limits.
5. **Domain policy.** The one public-state service revalidates opt-in, active row,
   workspace binding, `REGISTRATION`, and deadline. The POST repeats these checks
   under the event lock immediately before persistence.
6. **Persistence.** `CTFBaseModel.full_clean`, normalized fields, database checks
   and uniqueness, soft-delete semantics, atomic locking, durable backlog bounds,
   and scheduled retention constrain bypass and concurrency paths.
7. **Output and browser policy.** Template autoescape, static same-origin assets,
   CSP, clickjacking, permissions, `Cache-Control: private, no-store`,
   `Referrer-Policy: no-referrer`, and `X-Robots-Tag: noindex, nofollow` protect
   the public surface. CSP is defense in depth, not a sanitizer.
8. **Errors, telemetry, and audit.** Missing/ineligible variants collapse to 404;
   duplicate/existing-account variants collapse to generic success. Throttling
   returns 429 plus bounded `Retry-After`; limiter or persistence unavailability
   returns generic 503 and creates no request. Organizer JSON uses the shared
   request-ID envelope. Metrics, if justified, use the existing fail-soft CTF
   pattern and closed low-cardinality labels only.

No token, password, secret, email, name, or raw IP belongs in a URL/query string,
environment value, process argument, subprocess, temporary file, cache key,
audit context, metric label, or log. The HTTPS form and the bounded database row
are the only intended plaintext-PII surfaces; Redis receives only hashed source
identity. `safe_log_value` prevents log injection but is not sensitive-data
redaction.

An anonymous DRF `APIView` is not a drop-in alternative: DRF views are CSRF
exempt at Django middleware level and session authentication ordinarily enforces
CSRF for authenticated sessions. If a public JSON POST is later required, it
must add an explicit anonymous-CSRF/origin contract, a concrete serializer, and
the shared error envelope rather than assuming `AllowAny` is safe.

## Extensibility seam

Keep one locator-independent public-state resolver and one request-intake
service. A future vanity slug can map to the immutable event ID before entering
that resolver; a future waitlist/display-after-close policy can extend its closed
disposition without changing templates into policy owners. A future approval
source can pass a closed server-derived source/request reference into the one
participant-admission service without giving intake rows participant semantics.
These are seams in existing CTF services, not a reason to add a generic workflow,
publication, or registration framework now.

## Required negative assurances

Coverage must prove default-off behavior for new, migrated, and direct-ORM rows;
indistinguishable missing/disabled/unbound/deleted/wrong-state responses; the
exact deadline edge; hostile description/logo/theme storage; CSRF, method,
content, and size rejection; cross-worker throttling and limiter failure; generic
duplicate/account outcomes; concurrent duplicate, disable, deadline, and backlog
races; cross-event isolation; retention; organizer scope/capability and strict
audit; and absence of users, participants, ranges, outbound messages, webhooks,
or provisioning work after public submission. Header tests must cover no-store,
no-referrer, noindex, CSP compatibility, and no visitor-side remote fetch.

## Non-goals and anti-patterns

V1 does not publish schedules, scoreboards, rules, challenges, event pages,
participants, teams, workspaces, or range state. It does not add vanity slugs,
social discovery/indexing, public APIs, email verification, self-selected
passwords, automatic approval/provisioning, external CAPTCHA, remote branding,
or a new deployment feature flag. Team placement remains an organizer admission
decision unless separately specified.

Do not infer enablement, expose arbitrary model serialization, use request Host
for links, perform remote image fetches, trust CSP as sanitation, store raw IP,
log/audit PII, reveal duplicate/account existence, use the process-local default
cache for limits, fail open when Redis is unavailable, treat edge rate limits as
the application control, make pending rows consume participant capacity, or
duplicate deadline/capacity/account-provisioning logic. Do not weaken auth, CSRF,
CSP, cache, proxy, workspace, or event-capability policy to make the route fit.
