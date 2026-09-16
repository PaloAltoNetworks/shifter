# CTF Communications And RAES Inject Realization Preflight

Status: accepted architecture guidance

Date: 2026-08-14

Requirements: `CTF-008`, `CTF-010`, `CTF-012`, `CTF-014`

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/2047>

Domain-model implementation slice: <https://github.com/Brad-Edwards/shifter/issues/2048>

Delivery-engine slice: [#2049 preflight](ctf-communication-delivery-engine-preflight-2049.md).
That note records the post-#2048 repository state and specializes the execution
guardrails below; descriptions here of not-yet-added #2048 facilities are historical.
Its CTF-010 guidance distinguishes future scheduling from due-time release and
preserves CMS ownership of range expiry independently of communication delivery.

This decision defines the boundaries for one CTF communications capability. It
does not implement that capability and is not an implementation plan.

## Scope And Ownership

CTF owns communication meaning: authoring, content revisions, event audiences,
trigger policy, recipient snapshots, delivery state, participant read and
acknowledgement state, and RAES inject realization. Platform facilities remain
transport or cross-cutting services:

- `shared.email` owns email rendering/delivery mechanics and provider selection;
- `shared.notifications` owns browser-notification queueing and WebSocket fan-out;
- `shared.audit` owns durable audit evidence;
- `workspaces.services` owns workspace identity and membership policy;
- `shared.raes` is the only layer allowed to import and interpret RAES; and
- the CTF scheduler owns due-time execution for CTF work.

Do not create a generic platform messaging app merely because delivery crosses
email and WebSocket transports. Conversely, do not put email-provider, channel
layer, workspace-role, or RAES contract semantics into CTF persistence.

Every external HTTP operation remains part of the canonical versioned platform
surface under `/api/v1/ctf/`, including the narrowly authenticated range-trigger
ingress. Do not create a second Django service, listener, API root, app-local
schema endpoint, or unversioned `/ctf/api/` compatibility surface. Internal RAES
realization enters through a typed service adapter, not a second public HTTP API.

### CTF-014 Is A Constraint, Not A New Extension Surface

CTF-014 does not authorize this capability to add another plugin, theme, or
translation mechanism. The relevant incumbents already exist:

- trusted installed Django apps register custom flag/scoring behavior through
  `ctf.extensions` from their own `AppConfig.ready()`;
- event branding is the existing bounded `CTFEvent.logo_url`, `theme_color`, and
  `description` projection rendered by the canonical CTF presentation; and
- UI/filesystem-template translation uses Django `LocaleMiddleware`,
  `USE_I18N`, `LOCALE_PATHS`, gettext calls/template tags, and the existing
  `locale/` catalog.

Communication source normalizers, content profiles, trigger profiles, audience
profiles, and channel adapters are closed application-owned policy, not
`ctf.extensions` registrations. Do not add communication registration to
`ctf.apps.CtfConfig.ready()`: it runs in web, worker, scheduler, migration, and
management-command processes and is not a durable lifecycle or deployment
admission gate. A new installed extension may use only the already accepted CTF
extension contracts; it cannot acquire recipient, scheduling, RAES, workload
ingress, or transport authority by registering a callable.

Organizer-authored locale variants are immutable campaign data selected by a
normalized locale tag. They are not UI strings, gettext catalogs, automatic
translations, or a replacement for Django i18n. Event branding is presentation
data and must not be reused as a message content profile, link-host allowlist,
email wrapper, or authorization scope. This issue adds no plugin registry,
branding fields, locale model, translation editor, or per-event language pack.

## Canonical Vocabulary

The following terms are deliberately distinct:

| Term | Meaning and owner |
| --- | --- |
| `CommunicationCampaign` | CTF authoring aggregate: purpose, immutable workspace scope, event targets, audience specification, channel policy, acknowledgement policy, trigger specification, and lifecycle. Mutable only while draft. |
| `MessageRevision` | Immutable, locale-aware subject and safe-document content plus renderer-profile version and digest. Editing creates another revision; a released intent never changes revision. |
| `AudienceSpec` | Closed CTF selector over target events, participant public UUIDs, teams, or event participant profiles. It is not an ORM predicate language and never contains email addresses. |
| `TriggerSpec` | Closed declaration of manual, event lifecycle, absolute time, RAES shared-time/script occurrence, or allowlisted range signal. It is data, not code, a webhook, a dotted callable, or a plugin entry point. |
| `CommunicationIntent` | Immutable normalized occurrence produced after source validation and authorization. Static, dynamic, manual, timed, and RAES sources converge here. It pins campaign, revision, scope, event targets, occurrence identity, source attribution, and channel policy. |
| `RecipientSnapshot` | Server-resolved event participation at intent release. One row identifies an internal CTF participant and its event/team/user projection; any delivery coordinate is captured as encrypted sensitive data, never as authority. |
| `DeliveryAttempt` | One transport attempt for one snapshot, with a stable idempotency key, attempt number, due time, bounded result class, and truthful transport status. Transactional in-app availability is not a transport attempt. |
| `ParticipantReceipt` | In-app state for `read_at` and explicit `acknowledged_at`. It is independent of email acceptance, WebSocket publication, or socket write. |
| Audit evidence | Body-free security and workflow evidence emitted through `shared.audit`. Audit rows support investigation; they are not campaign, queue, or delivery state. |

`CTFNotification` currently conflates authoring, content, aggregate status,
scheduling, recipient filtering, and a claimed send count. It is compatibility
state, not the target domain model. `WebSocketNotification` is a transport replay
row, not a campaign, inbox item, delivery receipt, or acknowledgement record.

## Scope Lattice And Authorization

The scope lattice is explicit and monotonic:

```text
deployment -> workspace -> event -> range generation -> team -> participant -> user
```

- Deployment scope is platform-operator authority, not a participant audience.
- A campaign is bound to exactly one workspace. Every target event carries the
  same immutable internal `workspace_id` scalar. A campaign cannot infer scope
  from its creator, an email domain, a Django group, a team, a scenario, a range,
  or a cached frontend context.
- An event's teams and participants remain CTF-owned membership. Workspace
  membership does not grant event visibility, organizer authority, range access,
  or communication readership.
- A range generation is a trigger/source fence. It is never a recipient group.
- A user is an authentication and transport principal. The authoritative
  audience identity is the event-scoped participant row; the same user in two
  events is two participations and is not silently collapsed through an ambient
  user lookup.

ADR-046 previously kept CTF events unbound. Cross-event workspace confinement
cannot be proved under that posture. CTF events therefore gain an immutable
scalar `workspace_id` specifically as the event tenancy boundary. New event
creation accepts a public workspace UUID and resolves it through a new explicit
`WorkspaceOperation.USE_CTF_COMMUNICATIONS`; omission uses the creator's personal
compatibility workspace. That operation is granted to every defined workspace role
because it proves tenant membership only; it never grants CTF event or recipient
authority. Existing events backfill to the creator's personal workspace and fail
loud on an unresolvable owner. No CTF model imports a workspace model or holds a
cross-layer foreign key.

`USE_CTF_COMMUNICATIONS` is an active-workspace operation. New event creation,
campaign mutation/release, and due-time reauthorization fail when the bound
workspace is archived; historical inbox, receipt, and audit reads remain
available under their existing retention and authorization rules. This policy is
implemented once in `workspaces.services`, never by CTF reading `archived_at` or
comparing workspace role strings.

Interactive authorization is additive, never substitutive:

1. authenticate through the canonical session/API-token chain;
2. authorize the bound workspace through `workspaces.services` for the explicit
   CTF communication operation;
3. authorize the notification capability separately on every target event; and
4. repeat live authorization when a scheduled human-authored intent becomes due.

Programmatic organizer endpoints additionally require new exact
`ctf:communication:read` or `ctf:communication:write` scopes from the central
API-token registry. The existing broad `ctf:event:write` scope does not satisfy
either scope and, like every API-token scope, never replaces workspace or event
authorization. Declare those scopes through
`shared.api_tokens.permissions.require_scope` (or make the CTF compatibility
gate delegate to that same machine-readable permission) so
`shared.api.schema.PlatformAutoSchema` emits the real `x-required-scopes`.
Do not extend the app-local `HasCTFEndpointScope`/view-tuple mechanism as a
second scope system: the current mechanism enforces requests but does not
publish its scopes in the committed OpenAPI contract. Participant
inbox/read/acknowledgement remains session-bound; CTF participant accounts
cannot acquire platform API tokens.

The actor model is closed and additive:

| Actor | Allowed authority |
| --- | --- |
| Django superuser | Strict-audited platform-root action, still one workspace per campaign. |
| Event owner or notification-capable moderator | Manual authoring/release only for every separately authorized target event. A judge has no communication authority. |
| Participant | Own parent-scoped inbox, read, and acknowledgement only. |
| API-token caller | The live user plus a live token with the exact communication scope, workspace authorization, and every event capability. |
| Scenario-authored automation | A closed declaration accepted during an authorized event/scenario release; it is not an independent principal. |
| RAES runtime service | An internal realization caller constrained to a validated source/occurrence/context projection; it cannot select ambient scope or audience. |
| Range workload | One generation-fenced declaration/occurrence signal and nothing else. |

A scheduled session-authored action persists the actor's non-secret user identity.
A scheduled API-token action additionally persists only the non-secret token-row
identity; due execution requires that same user to remain active and that token to
remain live with the exact scope before workspace and per-event authorization is
repeated. Raw token material is never persisted in scheduler or intent state.

The event owner already holds every event capability. The current delegated
`moderator` role receives the `notifications` capability through
`ctf.services.event.staff.actor_has_event_capability`; `judge` does not. A
future co-organizer title must map through that same central capability policy,
not acquire endpoint-local special cases. Until such a role exists, it is not an
implicit synonym for any current staff role.

A Django superuser is the only current platform-operator override, following the
explicit-root precedent in ADR-048. The CTF service, not a view decorator,
applies and strict-audits that override. `is_staff`, Django model permissions,
workspace admin, API-token scope, cloud IAM, and identity-provider groups are not
platform communication authority. One campaign remains single-workspace even for
a superuser; a cross-workspace broadcast requires separate campaigns unless a
later ADR adds a narrower, explicit capability. Organizer endpoints that expose
this override cannot reuse `CTF_ORGANIZER_PERMISSIONS` unchanged:
`HasCTFOrganizer` currently checks only CTF organizer-group membership and would
deny an otherwise valid superuser before the service decision. Their coarse
HTTP gate authenticates an active session/token principal and applies the exact
token scope; the central communication authorization service then decides
owner, delegated notification capability, or audited superuser override.

Collections and nested lookups always start from the persisted workspace and
event targets. Participant/team UUIDs are resolved with their parent event in the
query. Missing and unauthorized objects share an opaque denial, so identifiers
cannot be used as cross-tenant membership probes.

## Audience Resolution

`AudienceSpec` supports exactly the product scopes required by umbrella issue
#2047 and its #2048 domain-model slice: one participant, an explicit participant
set, one or more teams, one event, or multiple events. It stores public CTF
identifiers and a closed membership profile, never email addresses, arbitrary
user IDs, SQL/ORM expressions, or a free-form filter JSON object.

General event communication reuses `viewing_participant_q()` so banned
participants are not silently re-admitted and disqualified participants retain
the established read posture. Purpose-specific incumbent predicates remain
distinct: invitations target invitation/login-info eligibility, reminders
target registered participants, and range-ready triggers resolve the one bound
participant server-side. These policies belong in one audience resolver; views,
serializers, scheduler handlers, and RAES adapters must not restate them.

Recipient membership and delivery coordinates are snapshotted when an intent is
released, not when a draft is saved. A timed intent resolves the live audience at
its due occurrence after reauthorization. Snapshot creation and the durable
delivery commands are one database transaction, with uniqueness constraints so a
retry cannot grow the audience. A changed address after the snapshot does not
change who was authorized to receive the intent. Email coordinates needed by a
worker use the existing field-encryption boundary and are erased by retention;
plain addresses never enter task metadata, logs, audit state, or WebSocket
payloads.

## Trigger And RAES Boundary

Every source produces the same `CommunicationIntent` after passing its own trust
gate:

- manual organizer/platform action: actor, workspace, and every event capability;
- static scenario content: exact validated package/scenario identity and an
  allowlisted authored declaration;
- timed action: the existing CTF scheduler, UTC due time, and stored source actor;
- dynamic platform action: the authoritative service event that owns the state
  transition; and
- range action: authenticated, generation-bound ingress naming only one allowed
  declaration and occurrence.

RAES remains the portable semantic authority. Only `shared.raes` may import the
pinned RAES packages and inspect public `Inject`, `Event`, `Script`, `Story`, and
`ParticipantInjectDelivery` contracts. It exposes a bounded immutable projection
to CTF containing only released-contract identity, classification, authored
references, occurrence/order coordinates, participant binding, content
references, policy/evidence references, and a digest. CTF persists its realization
state; it does not define `ShifterInject`, copy the RAES schema into a serializer,
accept a Shifter-authored portable inject document, or round-trip its projection
back as RAES.

The projection preserves, rather than flattens, these distinctions:

- disclosure is informational delivery;
- external direction remains direction with its own acknowledgement policy and
  is never relabeled as disclosure; and
- intervention includes a control effect and is not complete merely because its
  explanatory message was displayed.

An intervention may execute only through an existing CTF -> `ctf.bridges` ->
public CMS/Engine participant-control service boundary that re-resolves the exact
event, participant, range, and current operation generation. Communication code
never imports Engine/CMS models, invokes a provisioner, accepts a command, or
turns text into control. No currently accepted boundary realizes arbitrary RAES
interventions, so an intervention profile without an exact typed mapping is
unsupported and fails before intent persistence, delivery, or effect. Delivering
only the prose would be a silent semantic approximation and is prohibited.
[ADR-058](raes-participant-control-realization-envelope-1967.md) selects
explicitly reviewed, bounded native GCE range pause/resume around an admitted
portable proposal; it does not add a portable effect tag or turn text into
control. An ADR-051 integration still needs the exact released typed mapping,
GEN-2005 authority, #1968 implementation and #1969 real-boundary evidence.
The core control path does not depend on communications #2050/#2054; these
integrations consume the core, preserving the dependency direction.

RAES shared-time, script order, story/event identity, participant-delivery
identity, scenario/package digest, and range generation form occurrence evidence.
Wall-clock scheduling uses UTC and the existing CTF scheduler, but it retains the
RAES order/coordinate rather than treating shared time as a Unix timestamp. The
idempotency key is derived from the validated occurrence identity plus the bound
range generation, not from guest time or request arrival order. Unknown versions,
delivery kinds, audience profiles, content profiles, control profiles, or
ambiguous participant mappings fail closed before any row or notification is
created.

## Safe Rich-Content Profile

Organizer and scenario content is untrusted even when its author may manage the
event. The first profile is `ctf-communication-markdown/v1`:

- subject: required plain text, trimmed, no control characters, at most 200
  Unicode code points;
- source body: UTF-8 Markdown, at most 65,536 bytes;
- allowed structure: paragraphs, headings, emphasis, strong emphasis, ordered
  and unordered lists, block quotes, inline code, and fenced code blocks;
- raw HTML, inline style, script, event attributes, forms, SVG/MathML, iframe,
  object/embed, template elements, and executable URLs are rejected rather than
  stripped and accepted;
- images, audio, video, remote embeds, data/blob URLs, and inline attachments are
  unsupported in v1;
- links are at most 2,048 characters and are either same-origin relative paths or
  `https` URLs whose normalized hostname is in a deployment-owned allowlist;
  credentials, IP literals, localhost, non-HTTPS schemes, redirects/shorteners not
  themselves allowlisted, and participant/range-supplied URLs are rejected;
- external links render with `noopener noreferrer`; no server-side URL fetch is
  performed; and
- rendered output is capped at 131,072 bytes.

One versioned CTF profile is normative. A backend parser/policy enforces it at
revision creation and again at render/read as defense in depth. Browser code
extends the existing canonical `MarkdownContent` component with a closed
content-profile parameter and the deployment-owned host allowlist; it renders to
ordinary React elements without `rehype-raw` or `dangerouslySetInnerHTML`. Do not
create a second CTF Markdown renderer. Backend/email and browser projections share
one adversarial conformance fixture corpus so their separate runtimes cannot drift.
Email uses the same validated document to produce escaped HTML and plain text
behind `shared.email`. The global deny-by-default CSP in ADR-036 remains
authoritative and is not widened for communication content.

This profile is distinct from `CTFEmailTemplate`. Trusted filesystem templates
continue through `shared.email.render_template`; organizer-authored email
wrappers continue through the placeholder-only policy in
`ctf.services.email_template`. Neither template system becomes the rich-document
parser, and a rich message body is not exposed as a template object or arbitrary
context.

Each message revision has one required default locale and optional explicitly
tagged variants using normalized BCP 47 tags. Selection is exact tag, then base
language, then the revision's default. There is no automatic translation,
locale-dependent authorization, locale inferred from email domain, or fallback
to another revision. Locale is a presentation parameter at the immutable
revision seam. Product UI and trusted filesystem-template strings continue
through Django/gettext; storing authored variants must not create a second UI
translation catalog or translation workflow.

Acknowledgement policy is closed: `none`, `read`, or `explicit`. A successful
authenticated inbox-body read may set `read_at`; only an explicit participant
POST may set `acknowledged_at`. Email backend acceptance, provider delivery,
WebSocket publication, socket write, preview, organizer impersonation, and a
control effect do not satisfy either state. An external-direction profile may
require explicit acknowledgement; intervention effect evidence stays separate.

Communication bodies, recipient snapshots, encrypted delivery coordinates,
attempts, and participant receipts are retained until 90 days after the latest
target event ends, then purged/anonymized in bounded batches. The value is one
typed server setting (`CTF_COMMUNICATION_RETENTION_DAYS`, allowed range 1-365),
not per-request input. `WebSocketNotification` retains its independent existing
transport TTL (default seven days). Body-free `shared.audit` evidence follows the
audit system's own archive policy and is never extended by the communication
setting.

## Durable Command, Fan-Out, And Delivery Semantics

PostgreSQL is authoritative. Releasing an intent atomically writes the immutable
intent, recipient snapshots/in-app availability, initial selected-transport
delivery commands, and a strict audit event. The request, scheduler, RAES
adapter, and range ingress never call email or WebSocket delivery before commit.

The durable delivery state is CTF-owned and domain-specific. Reuse the database
outbox/worker pattern established by ADR-025 and Engine launch/result workers,
but do not reuse `RangeEventOutbox`, its payload schema, or its event types.
`CTFScheduledTask` remains the due-time registry and carries only a bounded intent
or occurrence identifier; it does not carry bodies, recipient lists, addresses,
RAES payloads, provider options, or commands.

External transport delivery is at-least-once across process failure. One stable
key per `(intent, recipient snapshot, transport)` collapses enqueue and worker
replay; an attempt number distinguishes retries. Email cannot promise exactly-once delivery
across the crash window after provider acceptance and before the database commit,
so duplicate mail remains a documented residual risk. A stable message identity
is supplied where the backend supports it, but status does not overclaim provider
deduplication.

Email workers call the synchronous `shared.email` boundary. PLAT-103 may extend
that boundary with a stable accepted/retryable/permanent result and provider
receipt reference; CTF must not select providers, parse provider exceptions, or
call an ESP SDK. `shared.email.send_email_async` and its process-local executor
are not a durability mechanism and are not used by the durable path.

The in-app inbox reads CTF recipient/receipt state created transactionally at
release. WebSocket fan-out is an optional reference-only wake-up carrying safe
message/receipt identifiers through `shared.notifications`; the browser fetches
the authorized inbox representation. It is not a selectable delivery channel.
`WebSocketNotification.delivered_at` means written to a socket, not read. When
the shared subsystem is disabled or publication fails, the durable inbox remains
available and no in-app attempt is marked failed or received; realtime degradation
is operator-visible and the participant can load or poll the inbox. Email-only is
an explicit policy, but the system never silently changes selected channels.

Attempt statuses are truthful and transport-specific: queued/claimed/retry due,
backend accepted, permanent failure, or cancelled. Optional WebSocket wake-up
publication is separate transport telemetry and never participates in campaign
success. `SENT` never means every participant received or read the content.
Campaign status is a derived aggregate over in-app availability and selected
transport attempts. Retry uses bounded exponential backoff with jitter and a
terminal failure state; backlog, retry exhaustion, and oldest-due age are
operator-visible. Cancellation stops only not-yet-claimed work. It cannot recall
provider-accepted email, a published browser notification, a participant read,
or a completed intervention.

Participant removal or deletion prevents inclusion in every future snapshot and
immediately removes inbox/read/acknowledgement authority through the canonical
parent-scoped participant predicate. In the removal transaction, unclaimed
delivery commands for that participation are cancelled and its encrypted
delivery coordinates are erased; claimed or provider-accepted attempts retain
their truthful terminal state. The immutable, event-qualified snapshot identity
remains bounded historical evidence until normal retention, is never retargeted
to another user or email, and is not exposed through participant APIs.

Event cancellation prevents new releases and due-time materialization for that
event, cancels its pending scheduled occurrences and event-qualified unclaimed
delivery commands, and leaves accepted/published/read history truthful until the
normal retention deadline. A multi-event draft containing a cancelled target
must be replaced rather than silently narrowing its target set; an already
released multi-event intent cancels only work qualified to the cancelled event.
Range replacement similarly fences all unclaimed generation-bound work for the
old generation. The old intent and occurrence remain historical evidence; a
replacement range requires a new generation-qualified occurrence and
idempotency identity, while communication that was never range-bound is
unaffected.

## Adversarial Range Ingress Threat Model

Assume every participant-controlled range asset, guest administrator, process,
script, token available inside the guest, and emitted request is compromised.
Range ingress is a constrained trigger signal, not an authoring or delivery API.

The accepted request is a bounded, closed, versioned shape containing only an
allowlisted declaration identifier, occurrence/nonce, and protocol version. It
cannot name a workspace, event, scenario, campaign, content, subject, locale,
link, channel, user, email, team, participant, control action, policy, or delivery
time. Unknown and duplicate fields fail before domain handling.

There is no existing guest-range-to-portal authentication principal to reuse.
The first accepted ingress profile therefore uses a dedicated, revocable opaque
range-trigger capability: a public locator plus a CSPRNG secret shown/delivered
once, with only a SHA-256 verifier persisted and constant-time comparison. This
reuses the cryptographic verifier pattern of `shared.api_tokens.ApiToken`, but
not its `ApiToken` row, `shf_` bearer scheme, user principal, or scope registry.
The server-side credential row pins issuer deployment, endpoint audience,
expiry/revocation, current operation generation, scenario/package digest, and
allowed declaration profile. The dedicated HTTP authentication scheme (for
example `RangeTrigger`, not generic `Bearer`) accepts the credential only from
`Authorization`, never query/body/cookie input. The ingress view's authentication
chain contains only that scheme and does not fall through to session or user-token
authentication.
The unrelated CMS upload-token HMAC and outbound `CTFWebhook` signature are not
workload authentication and must not be adapted into it.

Ingress must pass all of these gates before effect:

1. authenticate a workload/capability identity with issuer, audience, expiry,
   and deployment binding; a normal participant session or `shf_` user token is
   not workload identity;
2. resolve the credential server-side to one CMS/Engine range and current
   operation generation through one frozen scalar projection exposed by the
   public CMS service facade and `ctf.bridges`;
3. join that range exactly to its CTF participant, event, immutable workspace,
   scenario identity, and validated RAES package digest;
4. prove the declaration is allowlisted for that exact scenario/profile and the
   occurrence is valid for that participant delivery;
5. enforce database uniqueness/replay fencing plus shared-cache rate limits per
   deployment, range generation, and declaration; and
6. commit strict audit evidence and the normalized intent/command before any
   delivery or control effect.

Credentials are short-lived and rotation-capable. They are minted only after a
generation is reserved and delivered through an accepted provider secret/private
file boundary; if no such delivery boundary exists for a backend, range ingress
stays disabled there. They do not appear in process argv, command
strings, user data, task metadata, logs, audit state, guest-visible instance
metadata, or general-purpose environment dumps. Stealing a range credential can
at most replay allowed declarations for that exact current generation until its
expiry; it cannot widen audience, content, links, channels, scope, or control.
Destroy/recovery/reassignment invalidates the generation binding. Guest wall
clock is never trusted.

Malformed, unauthorized, stale, replayed, exhausted, or unsupported requests
return one bounded outcome and no scope oracle. Logs contain stable reason
classes and sanitized/fingerprinted identifiers, not request bodies, credentials,
recipient data, authored content, provider errors, or RAES parser diagnostics.

## Incumbents And Cross-Cutting Gates

| Concern | Canonical incumbent and obligation |
| --- | --- |
| Layering | ADR-001, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `ctf.services.notification`, and `ctf.bridges`. Keep CTF on public `shared`, `workspaces.services`, and CMS service facades; RAES imports stay under `shared.raes`. The current layer allowlist does not admit CTF -> `workspaces.services`; implementation must add that one documented public-service edge with ADR-051, never a `workspaces.models` edge. |
| CTF customization | `ctf.extensions`, `ctf.apps.CtfConfig`, `CTFEvent.logo_url/theme_color/description`, `config/settings.py` i18n middleware/settings, and `locale/`. These incumbents remain separate: no communication plugin registrations, `ready()` workflow, theme engine, message-to-brand coupling, locale model, or custom translation infrastructure. |
| Event authority | `ctf.api._base`, organizer `_resolve_owned_event`, `ctf.services.authorization`, and `ctf.services.event.staff.actor_has_event_capability`. Add one central communication capability; do not duplicate role checks in channels or triggers. |
| Workspace authority | ADR-046 and `workspaces.services.authorize_workspace` / `authorize_bound_workspace`. Add active-workspace `USE_CTF_COMMUNICATIONS` to the closed role matrix for every workspace role as a tenancy-membership proof; preserve authorized historical reads after archive. The current authorization functions do not reject `Workspace.archived_at`, so the new operation's active-state rule must be implemented once inside `workspaces.services`, not assumed at callers. Never compare workspace role strings or `archived_at` in CTF or treat that proof as event authority. |
| Participant policy | `viewing_participant_q`, existing invitation/reminder/range-ready service predicates, `CTFParticipant`, and `CTFTeam`. Resolve every recipient under its event. |
| Closed contracts | `ctf.content_bundle`, `shared.operation_envelope`, and `shared.schemas` demonstrate exact-key, version, byte-bound, duplicate-key, digest, and stable-error patterns. Reuse the pattern/helpers, not their unrelated schemas. |
| Scheduler | `CTFScheduledTask`, `ScheduledTaskType`/`Status`, `run_ctf_scheduler`, row claiming, stale recovery, heartbeat, and handler registry. Timing points at intent IDs only. |
| Email | `config/_email.py`, `shared.email`, `ctf.services.notification._email`, and `ctf.services.email_template`. Keep provider choice, secrets, MIME, trusted templates, and placeholder policy in their owners. |
| Browser delivery | `shared.notifications`, `WebSocketNotification`, `SharedNotificationConsumer`, `notification_user_topic_group`, `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, `config.websocket_auth.CTFAccountWebSocketBoundary`, and ADR-018 channel posture. Use reference-only wake-ups and existing topic authorization. Temporary CTF accounts are currently denied `/ws/notifications/`; admit exactly that route only when `live_participant_for_user` succeeds and the required password change is complete, retain the consumer's topic authorization, and never add a broad `/ws/` bypass. |
| Browser content | ADR-036, `config/_browser_security.py`, `frontend/src/features/ctf/MarkdownContent.tsx`, and its tests. Extend that renderer through a closed profile parameter and shared conformance fixtures; no second Markdown renderer, CSP exception, raw HTML, second origin, or browser token store. |
| Persistence | Django migrations, the UUID/timestamp conventions shared by `CTFBaseModel`, `transaction.atomic`, row locks, conditional updates, database constraints, and PostgreSQL concurrency tests. Workflow state is typed columns/rows, not JSON metadata, Redis, or process memory. Do not inherit `CTFBaseModel` soft-delete/restore behavior blindly for immutable or retention-limited content/PII: pruning must actually erase or irreversibly anonymize the retained material. |
| Sensitive fields | `shared.field_encryption`, runtime field-encryption key validation, and `shared.log_sanitize`. Encrypt transient coordinates; never log bodies, addresses, tokens, URLs, or provider payloads. |
| Audit | `shared.audit` and `ctf.services.audit`. Add only `AuditEntityType.COMMUNICATION`; reuse existing action/actor values, the CTF UUID-to-positive-int projection, and bounded exact public IDs in body-free state. Strict release/cancel/ingress/control decisions are atomic; do not create a communication audit schema. |
| API and errors | ADR-040, `config.middleware.CTFAccountBoundaryMiddleware`, explicit DRF serializers, new exact `ctf:communication:read/write` scopes in `shared.api_tokens.scopes`, `shared.api_tokens.permissions.require_scope`, session CSRF, `shared.api.errors`, the existing `CTFError` family and service-to-HTTP mapping, request IDs, `shared.api.schema.PlatformAutoSchema`, committed OpenAPI, and generated TypeScript types. Delivery outcomes are typed state/reason values, not one exception subclass per channel. Do not extend the CTF-only `HasCTFEndpointScope` tuple convention for this surface: it currently does not emit `x-required-scopes`. A range-ingress authenticator needs its own OpenAPI authentication extension/security declaration and must not advertise `ApiTokenAuth`. No writable `ModelSerializer`, raw exception, second/per-channel exception hierarchy, or legacy flat envelope. DRF's default JSON parser loses duplicate keys, so hostile closed shapes use one size-bounded exact-key/duplicate-key parser before serializer validation. |
| Rate limiting | `shared.rate_limit.consume_fixed_window`, the configured Django cache/Redis posture, and existing CTF/launch conventions. Limits are shared across portal processes and keyed by bounded identities; workload ingress fails closed on limiter-backend failure and never uses process-local counters. |
| Range binding | `CTFParticipant.range_instance_id`, CMS `RangeInstance` (`workspace_id`, `scenario_id`, request), Engine `Range.provisioner_operation_id`/immutable `OperationInput`, and the registered RAES package source/digest are the facts. Expose one frozen, scalar, generation-current authorization projection through `cms.services` and `ctf.bridges`; CTF must not import or join CMS/Engine models or trust cached `range_status`. |
| Workload credential | `ApiToken` supplies the opaque locator/verifier/constant-time pattern only. The range-trigger capability is a separate non-user principal and authentication scheme with no new signing key; it must not reuse `ApiToken`, CMS upload tokens, participant sessions, or webhook signatures. |
| Runtime config | `config/_ctf_content_settings.py` demonstrates bounded fail-loud CTF settings, while `config/_channels.py` owns Redis/channel posture and the existing `WEBSOCKET_NOTIFICATIONS_ENABLED`, replay, and retention settings remain the browser-transport controls. `config/_env_manifest.py` and generated `config/env-manifest.json`; `shifter/installation/runtime_inventory_gcp.py`; `scripts/gcp/render_runtime_env.py`; `scripts/bootstrap/{gcp_control_plane,aws_eks}.py`; `platform/charts/shifter/{values.yaml,values.schema.json,templates/configmap-runtime.yaml}`; and the retained AWS EC2 `platform/terraform/modules/portal/ec2/user_data.sh` plus `scripts/portal-deploy/deploy_portal.sh` are the parity surfaces when a setting is deployment-configurable. Enabling the currently parked notification transport must carry its existing controls through those shapes; it must not add a second enablement flag. `CTF_COMMUNICATION_RETENTION_DAYS` and a dedicated `CTF_COMMUNICATION_ALLOWED_LINK_HOSTS` (not `ALLOWED_HOSTS`, branding logo hosts, CSP, or CORS origins) are typed/bounded; malformed normalized host entries fail startup. Secrets stay in provider secret stores, never ConfigMaps/values/Terraform state. |
| Worker operations | `run_ctf_scheduler`, `docker-compose.yml`, Helm and GCP `ctf-scheduler` deployments, AWS EC2/portal deploy container lists, `scripts/stack-smoke`, and `tests/platform/test_ctf_scheduler_startup.py` are the incumbent heartbeat, graceful-shutdown, supervision, and parity pattern. A transport-delivery/prune process must be represented consistently across the same local/AWS/GCP shapes (without blocking the timing scheduler), or the durable channel remains disabled. |
| Documentation | ADR-022 and `docs/adr/documentation-coverage.yaml`. Shipping requires participant, organizer, scenario-author, technical, operator, and API documentation, all discoverable from their section indexes. |

## Security Layers And Host Exposure

- HTTP/manual: `CTFAccountBoundaryMiddleware`, canonical DRF session/API-token
  authentication, active principal, exact communication scopes, CSRF for browser
  mutations, active-workspace authorization, per-event capability, one
  size-bounded duplicate-aware JSON parser, explicit serializers, service
  reauthorization, and opaque denials. Participant endpoints remain under the
  exact permitted `/api/v1/ctf/` boundary.
- Workload ingress: a distinct non-`Bearer` scheme as the view's only
  authentication class, closed pre-parse
  request-size limit, exact generation/scenario/declaration binding, replay and
  shared-cache rate controls that fail closed on backend outage, and
  audit-before-effect. It never reuses participant sessions or API tokens. Its
  OpenAPI operation declares only the dedicated authentication scheme; generated
  docs/examples never contain a live locator or secret.
- WebSocket: `AllowedHostsOriginValidator` -> `AuthMiddlewareStack` ->
  `CTFAccountWebSocketBoundary` -> `SharedNotificationConsumer` remains the full
  chain. The account boundary may admit only the exact shared notification route
  when the existing live-participant/password-change checks pass; topic
  authorization still decides access and a prefix/wildcard bypass is prohibited.
- RAES: public contract parser/validator inside `shared.raes`, exact supported
  version/profile, occurrence and participant mapping, and fail-closed unsupported
  semantics before persistence.
- Content: byte and structure bounds, centralized safe-profile parser, link-host
  policy, no media/executable HTML, render-time revalidation, CSP, and escaped
  channel projections.
- Persistence: immutable revisions/intents/snapshots, database uniqueness and row
  claims, transactional command enqueue, generation fencing, bounded retries,
  partial-failure state, cancellation rules, and retention pruning.
- Email/channel configuration: `config/_email.py` and `config/_channels.py` keep
  production fail-loud behavior, provider secret hydration, Redis TLS/AUTH, and no
  fallback to an unintended backend.
- OS/process: management-command argv contains only non-secret numeric tuning;
  no subject/body/address/token/provider URL is placed in argv, shell commands,
  environment dumps, temp/public files, Kubernetes manifests, Terraform state,
  Helm history, or SSM command text.
- Errors and telemetry: shared envelopes/close codes expose stable authored
  messages only. Logs and metrics use low-cardinality state/channel/reason/count
  dimensions; audit and logs omit message bodies and delivery coordinates.

## Compatibility And Cutover Boundary

- Historical `CTFNotification` rows remain factual. Sent counts cannot be
  expanded into invented per-recipient success; import them only as explicitly
  legacy aggregate evidence.
- Draft/scheduled legacy notifications and their pending `SEND_NOTIFICATION`
  tasks must be transformed atomically to the new campaign/intent reference or
  fail the migration. Do not run legacy and new delivery writers in parallel.
- Existing notification endpoints may project the legacy response shape from the
  new service for a bounded compatibility window. A breaking removal follows
  ADR-040 and `openapi/v1.retirements.json`; it is not hidden behind an alias,
  alternate unversioned route, or dual schema.
- `CTFEmailTemplate` remains the per-event legacy email-wrapper contract for its
  supported types. It is not widened into campaign content or RAES storage.
- The shared WebSocket table, route, topic registry, enablement flag, replay
  bound, and prune command are reused as transport. They are not migrated into
  CTF workflow truth.
- `CTFWebhook` remains the legacy outbound event-integration surface. Its
  arbitrary URL, shared secret, process-local executor/retry loop, and last-only
  status are the wrong direction and guarantees for range ingress or durable
  communication; it is not a trigger, audience, channel, or delivery adapter.

## Extensibility Seams

The primary seam is a validated `CommunicationIntent` parameterized by:

- immutable `MessageRevision` and content-profile version;
- immutable workspace plus explicit event targets;
- closed audience and trigger profiles;
- source/occurrence evidence, including RAES identity where applicable;
- explicit channel policy; and
- acknowledgement policy.

A future channel adds one adapter from the same delivery command/result contract;
it does not edit trigger authorization, audience resolution, scheduler topology,
or persistence status meanings. A future safe-content feature adds a new profile
version or allowed token/link policy; it does not weaken v1. A future RAES
delivery/control profile extends the `shared.raes` projection and exact control
mapping; it does not add a Shifter portable inject schema. A future source adds a
new authenticated normalizer; it cannot bypass the common intent release gate.
None of these are runtime plugin points: adding one is an application change
that extends the relevant closed vocabulary, validators, authorization matrix,
OpenAPI/profile contract, tests, and deployment evidence together.

The deployment parameters are limited to operational policy:
`CTF_COMMUNICATION_RETENTION_DAYS`, normalized
`CTF_COMMUNICATION_ALLOWED_LINK_HOSTS`, fan-out/worker batch sizes, retry
ceilings, and rate budgets. They are typed, bounded, server-owned, and
provider-neutral. They
never carry campaigns, content, recipients, RAES bodies, or credentials.

## Verification Obligations

The later implementation is incomplete without maintained tests for:

- the complete actor matrix (owner, notification-capable moderator, judge,
  participant, unrelated organizer, staff-only user, superuser, API token,
  scenario automation, RAES service, and range workload);
- single- and multi-event workspace confinement, per-event authorization,
  revoked membership at due time, opaque denial, and no ambient nested lookup;
- recipient profiles, team/event containment, banned/disqualified behavior,
  encrypted coordinates, address changes, and participant-account anonymization;
- content byte/structure/output bounds, duplicate/unknown input fields, Unicode
  controls, Markdown parser abuse, XSS vectors, disallowed URL schemes/hosts/IPs,
  remote media, CSP, locale fallback, read, and explicit acknowledgement;
- RAES public fixtures for disclosure, external direction, intervention,
  shared-time/script ordering, occurrence identity, exact participant mapping,
  conflicting replay, and every unsupported-profile failure;
- hostile ingress identity, issuer/audience/expiry, event/scenario/package/range
  generation binding, declaration allowlist, replay, rate limits, audit ordering,
  and proof that arbitrary recipients/content/links/channels/control cannot be
  selected;
- range-trigger credential creation/show-once behavior, verifier mismatch,
  constant-time comparison seam, revocation/rotation, wrong authentication
  scheme, no session/user-token fallback, generation invalidation, and secret
  absence from every host/process surface;
- PostgreSQL row claiming and concurrency, crash/restart at enqueue/claim/send
  boundaries, at-least-once idempotency, retry/backoff, partial failure,
  cancellation, aggregate truth, worker health, and retention pruning;
- event-representative fan-out/backpressure and query budgets across multiple
  events and thousands of participants, with disabled/failed WebSocket preserving
  inbox availability, no transport rows, and bounded Redis/email worker load;
- AWS/GCP/local runtime configuration parity, email-provider failure, Redis
  fail-closed posture, secret redaction, and non-secret argv; and
- legacy row/task/API/template cutover, OpenAPI compatibility, generated client,
  migrations, and rollback from the supported pre-cutover backup boundary.

Architecture and platform changes run `adr_guard`, import-linter, migration and
OpenAPI drift checks, and the matching actionlint/TFLint/Kubernetes/Helm validators
required by `AGENTS.md`.

## Documentation Obligations

When the feature ships, update:

- `docs/features/ctf.md` for the participant inbox, read, and acknowledgement
  semantics;
- `docs/features/ctf-organizer-guide.md` for campaigns, audiences, scheduling,
  status truth, cancellation, and safe content;
- a discoverable scenario-author page under `docs/scenarios/` for supported RAES
  inject/trigger/content profiles and fail-closed diagnostics;
- `docs/technical/shifter_platform/ctf.md` for the domain, worker, persistence,
  authorization, RAES, and transport boundaries;
- `docs/technical/dev/installation-config.md` or the canonical operator config
  page for retention, link allowlists, worker/runtime settings, and channel
  prerequisites; and
- the OpenAPI/client documentation for participant inbox/acknowledgement,
  organizer campaign operations, and any workload ingress contract.

Add a `ctf-communications` entry to
`docs/adr/documentation-coverage.yaml`, tied to `CTF-008`, naming the participant
and organizer user docs plus the CTF technical doc. The scenario-author page must
be linked from `docs/scenarios/index.md`; user and technical pages remain linked
from their existing section indexes. Do not add the manifest entry before the
shipping docs actually describe the feature.

## Gotchas And Anti-Patterns

- Do not rename `CTFNotification` and keep its conflated schema.
- Do not register communication triggers, audiences, channels, renderers, or
  RAES handlers in `ctf.extensions` or `AppConfig.ready()`, and do not treat an
  installed Django app as trusted to select recipients or execute control.
- Do not treat email submission, provider acceptance, WebSocket publication,
  socket write, or notification replay as recipient delivery/read/acknowledgement.
- Do not send before transaction commit or mark an aggregate sent while attempts
  are pending/failed.
- Do not use the Engine range event outbox, shared audit log, Redis, scheduler
  metadata, or `WebSocketNotification` as communication workflow state.
- Do not store recipient emails as authorization identities or accept them in an
  audience request.
- Do not infer workspace from event creator, user profile, email domain, CTF team,
  scenario, range owner, or frontend selection.
- Do not authorize only the first event in a multi-event campaign.
- Do not let a workspace role, `is_staff`, judge role, broad `ctf:event:write`
  scope, or cached UI capability grant communication authority by itself.
- Do not put a superuser-capable endpoint behind `HasCTFOrganizer` unchanged;
  that coarse gate runs before the audited service override and recognizes only
  organizer-group membership.
- Do not add the communication scopes only to CTF view tuples. Use the shared
  machine-readable scope permission so runtime enforcement, OpenAPI
  `x-required-scopes`, and generated types describe the same boundary.
- Do not treat an archived workspace as active for authoring/release, or hide
  archive policy in CTF instead of `workspaces.services`; the incumbent
  `authorize_workspace` functions do not supply that check implicitly today.
- Do not parse or import RAES outside `shared.raes`, copy its models, relabel an
  unsupported delivery, drop shared-time/order identity, or deliver intervention
  prose without its supported control effect.
- Do not let a range workload choose a body, subject, link, channel, recipient,
  event, schedule, or command. A signed request containing those fields is still
  overpowered.
- Do not authenticate range workloads with participant sessions, `ApiToken`, the
  CMS upload token, a webhook secret, a query token, cloud metadata claims alone,
  or a credential whose server record is not fenced to the current operation
  generation.
- Do not use generic `Bearer` for range ingress, append workload auth to the normal
  session/API-token chain, persist raw user/range token material in a scheduled
  task, or skip live-token checks when due work was scheduled through an API token.
- Do not accept arbitrary HTML, sanitize by regex, execute template syntax,
  enable iframe/remote embeds, widen CSP, or rely on frontend escaping alone.
- Do not make URL syntax/SSRF checks stand in for the communication link-host
  allowlist; browser navigation and server fetches are different policies.
- Do not add a second scheduler, Celery/RQ, in-process thread, cron fragment,
  provider SDK, mail retry loop, second/per-channel notification exception
  hierarchy, or error envelope.
- Do not reuse `CTFWebhook` as inbound trigger authentication or as a delivery
  adapter, and do not treat WebSocket wake-up failure as loss of a persisted
  inbox item.
- Do not rely on a normal DRF serializer/parser to detect duplicate JSON keys,
  or implement separate ad hoc request validators in manual, scheduler, RAES,
  and range paths.
- Do not grant temporary CTF accounts a `/ws/` prefix bypass; the only new account
  boundary admission is the exact shared notification route, followed by normal
  topic authorization.
- Do not hide PII/content in JSON metadata, audit free text, provider receipt
  blobs, metrics labels, task errors, env vars, argv, or test snapshots.
- Do not rely on soft delete for the retention deadline: a restorable row still
  contains the message body or delivery coordinate and has not been purged.
- Do not promise exactly-once email, cross-channel ordering, recall after send,
  or intervention success from communication status.

## Non-Goals

- A generic arbitrary-code trigger/plugin host or workflow engine.
- Changes to the existing CTF flag/scoring Django-app extension contracts,
  event-branding model/presentation, or Django/gettext UI translation workflow.
- Unrestricted outbound webhooks, arbitrary participant-supplied URLs, remote
  media, HTML email authoring, or executable browser content.
- A platform marketing/CRM/bulk-email system or contacts database.
- Workspace membership replacing CTF event/team/participant authorization.
- Reimplementing portable RAES inject/event/script/story semantics in CTF.
- Giving range workloads authoring, audience, channel, scheduling, or control
  authority.
- Treating communication delivery as proof of a domain state transition or
  participant comprehension.
- Replacing PLAT-103 email provider configuration, PLAT-105 WebSocket transport,
  the CTF scheduler, shared audit, or the canonical API/error stack.
- Media/attachment delivery and arbitrary RAES intervention realization in the
  first content/control profile.
