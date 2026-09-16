# SPA Cohesive UX: Use Cases, Layout System, and Rationale (#1368)

Date: 2026-07-08

Issue: #1368, "SPA Cutover -- cohesive UX: use cases, IA & wireframes (all surfaces)"

Milestone: SPA Cutover, Phase 2

Status: Design foundation for review

Related artifacts:

- `docs/design/ux-003-information-architecture-sitemap.md` (the maintained IA,
  sitemap, navigation model, and taxonomy; updated by this pass per ADR-013).
- `docs/design/ux-003-oss-shifter-research-personas.md` (personas and JTBD).
- `docs/design/spa-design-system-foundation-1299.md` (the locked Apple-dark
  Tailwind v4 plus shadcn/ui system).
- `docs/architecture/spa-cohesive-ux-preflight-1368.md` (binding guardrails).

## Purpose and Scope

This document is the design foundation for Phase 2 of the SPA cutover. It
develops the use cases per surface, the shared layout and pattern system, the
rationale for departures from today's experience. The canonical information architecture, sitemap, navigation
model, and taxonomy live in the maintained UX-003 artifact, which this pass
updates rather than duplicates (ADR-013).

This is a design artifact. It does not implement SPA routes, shell components, a
navigation registry, feature flags, serializers, or wireframe fixtures. The
maintainer scoped this issue to the design foundation. The real platform shell
scaffolding is delivered by #1369, and the per-surface workspaces by #1370
through #1373.

In scope surfaces:

- App shell, global navigation, home and dashboard, and the authentication
  surfaces.
- Mission Control (range operations, terminals, assets).
- Scenario Editor (scenario authoring).
- CTF (participant and organizer).
- Admin (users, cost tracking, platform settings).

Out of scope: the MkDocs documentation site and the static privacy notice, per
the issue.

## Method

The information architecture was derived fresh from the personas and the current
surfaces rather than adopted from the prior model, then compared against UX-003
at the end. The derivation, the points where it confirms the prior model, and
the points where it departs are recorded in the "Rationale" section below and
folded into the maintained UX-003 artifact. The persona and JTBD anchors are the
ones published in `ux-003-oss-shifter-research-personas.md`:
`persona-panw-consultant-demo-operator`, `persona-conference-ctf-attendee`,
`persona-internal-trainer`, `persona-oss-contributor-evaluator`, and
`persona-self-hosting-oss-adopter`.

## Modes, Not Roles

Two operating frames emerge from the personas:

- Participant mode: the bounded CTF and learning experience. Serves
  `persona-conference-ctf-attendee`, plus the demo operator and trainer when
  they take part.
- Operator mode: the operational, authoring, governance, and administration
  experience. Serves the demo operator, trainer, self-hoster, and contributor
  evaluator.

Mode is a user-facing frame. It is not an authorization fact. A user with access
to both modes switches between them, which changes the navigation structure and
the default landing page but never grants permission. CTF participant, CTF
organizer, staff, superuser, and Threat Research access remain
authorization facts enforced by the backend. The navigation may hide or disable
controls for clarity, and every endpoint and service stays the authority. This
follows ADR-013-R3 and ADR-013-R4.

## Use-Case Catalog

Each entry names the actor (a persona anchor), the job to be done, the current
pain, the authoritative backend owner, and known API or readiness gaps that the
per-surface implementation issues must close. Backend owners and API readiness
are drawn from the current route and API modules; where an item needs
verification, the implementing issue confirms the endpoint shape before
building.

### App Shell, Home, Dashboard, and Authentication

Backend owners: `config.views` (`home`, `dashboard_router`, `platform_login`,
`identity_platform_session`, `logout_view`, `dev_login`), `shared/api/bootstrap.py`
(the SPA session bootstrap), `shared.auth`, and the provider auth stack (OIDC,
Identity Platform, CTF magic links).

| Actor | Job | Current pain | Backend owner | API and readiness gaps |
| --- | --- | --- | --- | --- |
| Demo operator | Land after login on a usable operational view, not a placeholder | Home is a public placeholder; the dashboard router only redirects | `config.views.dashboard_router`; `bootstrap` | No aggregate dashboard read; the home and dashboard need a summary payload (verify whether it extends bootstrap or adds a read endpoint in #1369) |
| Any operator or participant | Sign in through the configured provider and land in the right mode | Login is a separate provider round trip; mode is implicit | `platform_login`; `identity_platform_session`; provider stack | Auth stays server and provider driven; the SPA starts after a Django session exists (no change needed here) |
| Any authenticated user | See who I am, my current mode, and my active range or event context | Context is scattered across app headers | `bootstrap`; `mission_control.context_processors.active_range`; `ctf.context_processors.ctf_navigation` | Active range and event summaries should extend the bootstrap serializer and generated types (design seam; built in #1369) |
| Any user hitting a surface they cannot access | Get a clear access-denied state, not a raw error | Access errors vary by surface | resource permission classes; `bootstrap` advisory flags | Use one shared access-denied workspace pattern |

### Mission Control

Personas served: demo operator, trainer, self-hoster.

Backend owner: the `mission_control` app, with a mature `/api/v1` surface
(`mission_control/api/urls.py`): range lifecycle (launch, cancel, destroy,
pause, resume), current range, agents, scenarios, uploads (initiate, complete,
cancel), Guacamole RDP and SSH URL issuance, NGFW create, list, and destroy,
and credential create and delete. Terminal and range status use Django Channels
websockets (`mission_control/routing.py`).

| Actor | Job | Current pain | Backend owner | API and readiness gaps |
| --- | --- | --- | --- | --- |
| Demo operator | Launch and monitor a range with one operational view of provisioning, health, credentials, terminal access, and cleanup | `pain-fragmented-operational-state`: range state crosses several pages | `mission_control` range and status views; active-range context processor | Range lifecycle and status APIs exist; confirm a single status read plus websocket for live updates in #1370 |
| Demo operator | When something fails, see the next action clearly: retry, inspect, reset, deprovision, or escalate | Ambiguous states such as provisioning, available, running, and unhealthy carry no operator meaning | range lifecycle views | Map domain lifecycle states to design-system intents and accessible labels (state-mapping seam) |
| Self-hoster | Read state labels that map to real infrastructure lifecycle without friendly copy hiding risk | Labels do not always match infrastructure reality | range services | Preserve backend state names in UX copy; no invented states |
| Operator | Reach a terminal or remote desktop for a range instance | Terminal access is a separate surface | Guacamole URL views; websocket terminal | Guacamole URL issuance and websocket transport exist; the workspace layout hosts them (built in #1370) |
| Operator | Manage assets: agents, NGFW instances, and reusable credentials | Assets are separate list pages with distinct patterns | agents, NGFW, credential views | APIs exist; unify under the list and detail patterns in this document |

### Scenario Editor

Personas served: trainer, contributor evaluator, demo operator.

Backend owner: `cms.scenario_editor` and `cms.scenarios.schema`, with a `/api/v1`
surface (`cms/api/urls.py`) that includes the catalog list and detail and YAML
validation. Scenario create, edit, clone, export, and enable or staff-only
toggles currently run through the Django page and action routes.

| Actor | Job | Current pain | Backend owner | API and readiness gaps |
| --- | --- | --- | --- | --- |
| Trainer | Create or adapt a scenario and understand required machines, services, flags, credentials, and validation before launch | `pain-authoring-confidence`: readiness is not presented as one workflow | `cms.scenario_editor`; `cms.scenarios.schema` | Confirm scenario create, edit, clone, export, and toggle endpoints on `/api/v1` for #1371; today several are Django action routes (verify) |
| Trainer or contributor | See YAML errors tied to the domain concept being edited, not raw parser output | Validation output is parser centric | YAML validation view; scenario schema | The validate-yaml endpoint exists; surface field-linked validation in the editor pattern |
| Contributor evaluator | Move between the editor language and repository concepts | `pain-surface-vocabulary-drift` | scenario schema and taxonomy | Preserve the taxonomy in editor labels (UX-003) |
| Trainer | Compare scenarios by difficulty, mode, estimated time, and required resources without opening each file | Metadata is not scannable | catalog list view | Confirm the catalog list returns the comparison fields for the list pattern |

### CTF Participant

Personas served: conference attendee, trainer, demo operator (as facilitators).

Backend owner: the `ctf` app, with a broad `/api/v1` participant surface
(`ctf/api/urls.py`): event detail, challenges and challenge detail, flag
submission, hint use and listing, challenge rating, submissions, range status
and access, and scoreboard. Navigation context comes from
`ctf.context_processors.ctf_navigation`.

| Actor | Job | Current pain | Backend owner | API and readiness gaps |
| --- | --- | --- | --- | --- |
| Conference attendee | Understand the event, team status, available challenges, scoring, and hints on arrival | `pain-mixed-skill-onboarding`: unclear progression punishes beginners | event, challenge, and scoreboard views | Participant reads exist; the dashboard and list patterns present calm progression and explicit next steps |
| Conference attendee | Find a solvable challenge quickly and know what to do next | Challenge instructions, range connection, scoring, and flavor blur together | challenge detail and submission views | Separate instructions, hints, files, and submission into contextual tabs (detail pattern) |
| Conference attendee | Access range resources and recover from failed attempts without hunting through admin surfaces | Range access lives away from the challenge | range status and access views | Present range access in participant context; avoid organizer surfaces |
| Beginner participant | Distinguish platform problems from personal mistakes | A loud UI makes the event feel harder than the task | challenge and range views | Use the operational error state with a request id, and calm status presentation |

### CTF Organizer

Personas served: demo operator, trainer.

Backend owner: the `ctf` app organizer `/api/v1` surface: event list, detail,
and force-delete, challenge list and detail, participants list, import, and
detail, ranges list and provisioning, brackets, scoreboard admin,
notifications, invitations, flags, and challenge files.

| Actor | Job | Current pain | Backend owner | API and readiness gaps |
| --- | --- | --- | --- | --- |
| Demo operator | Run a customer event and see which teams are blocked and whether ranges are healthy | `pain-fragmented-operational-state` across event, range, and participant pages | event, participant, and range views | Reads exist; the operator dashboard aggregates event health for #1372 |
| Demo operator | Intervene before frustration spreads by seeing participant progress and blockers | Progress is spread across pages | participant and scoreboard views | Present participant progress in the detail and list patterns |
| Trainer | Manage challenges, brackets, scoring, and communications for a cohort | Each is a separate admin flow | challenge, bracket, scoreboard, and notification views | Function-based `api_*` views exist; confirm shapes for #1372 |
| Organizer | Perform destructive actions such as force-delete safely | Destructive actions are easy to confuse with routine edits | force-delete and delete views | Route destructive actions through the confirmation pattern |

### Admin (Shifter Admin)

Personas served: self-hoster, demo operator.

Backend owner: the `management` app (user profiles, groups, and Cognito or
Identity group sync) and Django admin (`/admin/`). Cost tracking has no portal
surface today; the operational cost tooling lives outside the portal. This is
the largest readiness gap in this pass.

| Actor | Job | Current pain | Backend owner | API and readiness gaps |
| --- | --- | --- | --- | --- |
| Self-hoster | Manage users, groups, and access without dropping into Django admin | User administration is Django admin only | `management` app; Django admin | No `/api/v1` user administration surface exists; #1373 needs a management API, or it hosts Django admin behind the shell as an interim step (decide in #1373) |
| Self-hoster | See platform cost and spend to support deployment decisions | No portal cost view exists | none in the portal | Cost tracking has no portal API; #1373 must define whether cost is surfaced and from where. Do not surface live cloud identifiers or secret-bearing data |
| Self-hoster or operator | Change platform and account settings | Settings are per-surface today | `mission_control` settings and account menu | Consolidate account and platform settings under the shell account menu and an Administer settings surface |

## Layout and Pattern System

The layout system defines a small set of reusable page templates and the shell
regions they fill. Feature modules fill slots with domain data; they do not
invent new shells. Every template is expressed with the locked design system:
Tailwind v4, shadcn/ui, lucide icons, the Apple-dark tokens, and the Shifter
mark. No new visual language is introduced.

### Shell Regions

- Global top bar: the Shifter mark, the current mode with a mode switch when the
  user has both, the active range or event context when relevant, the account
  menu, and the theme toggle.
- Primary side navigation: role-aware, grouped by the information architecture
  for the current mode, rendered from the shared navigation contract.
- Page header: the current object title, breadcrumbs on nested object pages, and
  the primary actions.
- Content area: the page template body.
- Contextual subnavigation: tabs within a single entity.
- Notification region: toasts and page-level banners.
- Modal layer: bounded, reversible, or confirmatory actions only.

### Page Templates

| Template | Purpose | Primary surfaces | Key shadcn primitives |
| --- | --- | --- | --- |
| Dashboard or Overview | Role-aware landing with scannable status, primary actions, and recent activity | Home, Operate overview, CTF participant and organizer home | Card, Badge, Skeleton |
| List | Index with filters, table or cards, row and bulk actions, and pagination | Risks, Scenarios, Events, Ranges, Participants, Challenges, Credentials, NGFW, Agents, Users | Table, Input, Select, Badge, Button |
| Detail | Entity header plus contextual tabs and panels | Risk, Event, Challenge, Range, Scenario, Participant | Tabs, Card, Badge, Alert |
| Editor | Create and edit forms, including structured YAML editing, with field-linked validation | Risk form, Scenario create, edit, and YAML, Event and Challenge create and edit | Input, Textarea, Label, Select, Alert, Dialog |
| Workspace | Full-height interactive surface with minimal chrome | Terminal and Guacamole, range console | full-bleed content region |
| Admin table | Dense management tables | Users, cost | Table, Badge, Button |
| Destructive confirmation | Confirm delete, deprovision, force-delete, or revoke | all surfaces with destructive actions | AlertDialog |

### Required States Per Template

Every template must define these states, not only the happy path:

- Loading: a skeleton that matches the eventual layout.
- Empty: no data yet, with a primary call to action.
- Filtered-empty: no matches, with a clear-filters affordance.
- Permission denied: the advisory access-denied workspace state; the API stays
  the authority and returns the real status.
- Validation error: field-linked, tied to the domain concept.
- Backend error: the safe message plus the request id from the shared error
  envelope; no stack traces, provider errors, tokens, or signed URLs.
- Stale or not found: a recoverable not-found state.
- Long-running: an in-progress state that disables re-submission and does not
  auto-retry unsafe mutations.
- Degraded or offline: a reduced state when a dependency is unavailable.
- Read-only or deleted: a non-editable state for closed or soft-deleted records.

### Accessibility (AA) Built In

Accessibility is part of the pattern contract, not a later pass. Every template
carries: semantic landmarks (banner, navigation, main), a skip link, keyboard
paths and a sensible focus order, focus management on route change and on modal
open and close (including a focus trap), accessible names, form-error linkage
through described-by relationships, status that is not conveyed by color alone
(icon plus text plus color), reduced-motion support, and token contrast that
already meets AA from the design-system foundation. SPA strings need an
extraction and translation path before broad cutover, consistent with ADR-016.

### Domain Status to Intent Mapping

One mapping translates domain values to design-system intents and accessible
labels. Intents render domain state; they do not define the state machine. The
next status value adds one mapping entry, not a new badge component or color
token.

| Domain value | Intent | Note |
| --- | --- | --- |
| Range or provisioning: provisioning, available or running, unhealthy or failed, deprovisioning | pending, success, danger, warning | Operator meaning must be explicit |
| Event: draft, active, ended | neutral, success, muted | |
| Challenge: locked, available, solved | muted, neutral, success | |
| Upload or validation: uploading, valid, invalid | pending, success, danger | |

## Navigation UX Rendered From the Shared Contract

The canonical sitemap, navigation model, and taxonomy live in UX-003. This
section describes only how the shared navigation contract renders across the
shell, so the implementing issues have a consistent target.

- Participant mode shows the Participate primary navigation: Event Home,
  Challenges, Range, Scoreboard, Team, and Help.
- Operator mode shows a role-aware landing (Home) and the operator groups:
  Operate, Author, and Administer.
- The top bar carries product identity, the current mode and mode switch, the
  active range or event context, and the account menu. It does not duplicate the
  side navigation.
- Breadcrumbs appear on nested object pages, not on dashboards or list pages.
- Contextual tabs appear within a single entity: event tabs, challenge tabs,
  range tabs, and scenario tabs.

Each navigation entry carries the UX-003 minimum contract (surface, audience,
route name, permission policy, owner app, and purpose) plus the presentation
fields this pass adds (group, icon key, route path, active context, feature
flag, and children). This parameterizes one contract. Adding a surface adds one
entry rather than editing every shell component. The centralized contract is
built in #1369; the per-surface issues register their entries into it.

## Rationale for Departures From Today's UX

The fresh derivation from personas and surfaces confirmed several prior instincts
and departed on a few. Recording both is the point of the exercise.

Confirmed by the fresh derivation:

- The Participant and Operator mode split. Both the attendee persona and the
  operational personas need distinct frames, and the frames must stay
  structurally distinct (ADR-013-R4).
- The operator groupings Operate and Author. The operational and authoring
  jobs cluster cleanly and map to code ownership,
  which serves `pain-surface-vocabulary-drift`.

Departures from the prior Django-era model:

- Administer is promoted to a first-class operator surface for users, cost
  tracking, and platform settings. The prior model folded platform
  administration into Django admin. The self-hoster persona needs deployment and
  administration visibility as a product surface, not a framework escape hatch.
- The first authenticated screen is a role-aware operational dashboard, not a
  public placeholder. The demo operator persona needs range and event health on
  landing.
- The mode switch is explicit in the shell. Users with both accesses move
  between modes without a permission change.
- Learn and Docs are deferred from the SPA navigation for this cutover. The
  documentation site remains a platform surface and stays out of scope per the
  issue; the maintained IA records it as a surface, not as SPA navigation yet.

Alternatives considered and set aside:

- A single flat navigation with every surface at the top level. Rejected: it
  produces more than ten top-level items, erases the mode distinction, and works
  against `pain-fragmented-operational-state`.
- A purely task-oriented navigation that cuts across surfaces by verb. Rejected:
  it breaks the alignment between surface names and code ownership that
  contributors and self-hosters rely on.
- Merging Operate and Administer. Rejected: the audiences and cadence differ.
  Administration is lower-frequency, platform-lifecycle work.

## API-Readiness and Capability Matrix

The per-surface implementation issues consume this matrix instead of
rediscovering gaps. Readiness reflects the current API modules; items marked
"verify" require the implementing issue to confirm the endpoint shape before
building.

| Surface | Canonical `/api/v1` | Style | Special transport | Largest gap |
| --- | --- | --- | --- | --- |
| App shell, home, auth | bootstrap read | DRF APIView | none | No aggregate dashboard read; active-context summaries not yet in bootstrap |
| Mission Control | range lifecycle, agents, scenarios, uploads, Guacamole URLs, NGFW, credentials | DRF APIView | Guacamole, terminal and status websockets | Confirm a single range status read for the operational view |
| Scenario Editor | catalog list and detail, YAML validate | DRF APIView | none | Scenario create, edit, clone, export, and toggle may still be Django action routes (verify) |
| CTF participant | event, challenges, submit, hints, submissions, range status and access, scoreboard | function-based `api_*` | range websockets | Broad but function-based; confirm shapes and pagination |
| CTF organizer | events, participants, ranges, brackets, scoreboard, notifications, invitations, flags, files | function-based `api_*` | none | Aggregate event-health read for the organizer dashboard |
| Admin | none for users or cost | none | none | No user-administration API and no portal cost API; #1373 defines the surface |

## Acceptance-Criteria Mapping

The issue lists wireframes as a deliverable. The maintainer replaced static
wireframes with real SPA scaffolding as the medium, delivered in #1369 through
#1374, and scoped this issue to the design foundation. The acceptance criteria
map to this pass as follows.

| Issue acceptance criterion | Satisfied by |
| --- | --- |
| Cover all in-scope surfaces with one coherent IA, navigation, and layout language | The use-case catalog covers every in-scope surface; the layout and pattern system and the UX-003 navigation model give one coherent language |
| Use the locked Apple-dark design system and logo, with no new visual language | The layout and pattern system is expressed with the existing tokens, shadcn/ui, lucide, and the Shifter mark; the "locked foundation" is not restyled |
| Accessibility (AA) designed in, not deferred | The "Accessibility (AA) Built In" section makes AA part of the pattern contract |
| The per-surface implementation issues can build directly against this design | The shared navigation contract, the layout slots, the state-mapping seam, and the API-readiness matrix are the direct build target for #1369 through #1373 |

## Handoff to Implementation Issues

- #1369 (App shell and global navigation) builds the centralized navigation
  contract, the shell regions, the home and dashboard, the auth-adjacent
  surfaces, and the routing and mount pattern behind a rollout flag, with the
  legacy path preserved.
- #1370 (Mission Control), #1371 (Scenario Editor), #1372 (CTF), and #1373
  (Admin) fill the layout slots for their surfaces and register their navigation
  entries. Each reads the capability matrix for its known gaps.
