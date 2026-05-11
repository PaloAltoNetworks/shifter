# UX-003 Information Architecture And Sitemap

Date: 2026-05-11

Issue: #1093

Requirement: `UX-003` - Single information architecture across the platform

Status: Draft design artifact for review

Architecture decision: `ADR-013` records the implementation constraint that
future navigation work must use a shared, role-aware platform navigation
contract rather than duplicating app-local navigation schemas.

## Purpose

This document defines the platform-wide information architecture for Shifter.
It covers CTF, Mission Control, Scenario Editor, Risk Register, and
Documentation as one product instead of five unrelated Django apps.

This is not a visual design system, wireframe set, route migration plan, or
template implementation. Later implementation work should treat this document as
the maintained source of truth for surface naming, sitemap placement, navigation
rules, and cross-surface taxonomy.

## Evidence And Inputs

Primary source files:

- `docs/design/ux-003-oss-shifter-research-personas.md`
- `shifter/shifter_platform/config/urls.py`
- `shifter/shifter_platform/ctf/urls.py`
- `shifter/shifter_platform/mission_control/urls.py`
- `shifter/shifter_platform/cms/scenario_editor/urls.py`
- `shifter/shifter_platform/cms/experiments/urls.py`
- `shifter/shifter_platform/risk_register/urls.py`
- `shifter/shifter_platform/documentation/urls.py`
- `shifter/shifter_platform/templates/partials/icon_sidebar.html`
- `shifter/shifter_platform/templates/partials/ctf_participant_sidebar.html`

Persona and JTBD anchors come from the UX research artifact:

- `persona-panw-consultant-demo-operator`
- `persona-conference-ctf-attendee`
- `persona-internal-trainer`
- `persona-oss-contributor-evaluator`
- `persona-self-hosting-oss-adopter`
- `surface-ctf`
- `surface-mission-control`
- `surface-scenario-editor`
- `surface-risk-register`
- `surface-documentation`
- `pain-fragmented-operational-state`
- `pain-mixed-skill-onboarding`
- `pain-surface-vocabulary-drift`
- `pain-docs-not-role-routed`
- `pain-authoring-confidence`

## IA Principles

1. One product, two primary modes. Shifter has a participant mode and an
   organizer/operator mode. A user may have access to both, but navigation must
   make the current mode explicit.
2. Navigation visibility is not authorization. Links may be hidden for clarity,
   but access must still be enforced by the existing view decorators, role
   checks, and permission policies.
3. Surface names should match user jobs and repository concepts. Do not rename a
   product surface unless the code ownership and documentation language can move
   with it.
4. Operational state takes priority over decorative identity. Range health,
   event progress, scenario readiness, risk status, and documentation role
   routing need to be scannable.
5. Shared navigation contracts belong under a shared boundary in later
   implementation. Do not create five parallel navigation schemas inside the
   five apps.

## Current-State Inventory

Audience values:

- Participant: event attendee or learner.
- Organizer: facilitator, trainer, operator, staff user, or threat researcher.
- Both: useful to both audiences when permission allows it.
- System: authentication, redirects, health, or framework administration.

### Platform Shell

| Current page | Route | Primary user | Primary purpose |
| --- | --- | --- | --- |
| Home / coming soon | `/` | System | Public landing placeholder. |
| Platform login | `/login/` | Both | Route users to the configured auth provider. |
| Identity Platform session exchange | `/auth/identity/session/` | System | Exchange a verified identity token for a Django session. |
| Dashboard router | `/dashboard/` | Both | Send authenticated users to the current default dashboard. |
| Logout | `/logout/` | Both | End the current session through the configured provider. |
| Developer login | `/dev-login/` | System | Local development login entry point. |
| Developer logout | `/dev-logout/` | System | Local development logout entry point. |
| Django admin | `/admin/` | Organizer | Framework administration. |
| Health checks | `/health/` | System | Service health endpoint. |

### CTF

The CTF app already has a clear participant and organizer split in URLs:
participant pages live under `/ctf/`, and organizer pages live under
`/ctf/admin/`. The participant base template can switch to a CTF-specific
sidebar, while organizer pages use the shared icon sidebar.

#### CTF Participant Pages

| Current page | Route | Primary user | Primary purpose |
| --- | --- | --- | --- |
| Participant dashboard | `/ctf/` | Participant | Event entry point with current participant state. |
| Registration | `/ctf/register/` | Participant | Join or register for the active event. |
| Event overview | `/ctf/event/` | Participant | Read event rules, timing, and contextual details. |
| Challenge list | `/ctf/challenges/` | Participant | Browse available challenges and progression. |
| Challenge detail | `/ctf/challenges/<challenge_id>/` | Participant | Read challenge instructions, hints, files, and submit flags. |
| Participant range | `/ctf/range/` | Participant | Access range status and participant resources. |
| Scoreboard | `/ctf/scoreboard/` | Participant | Compare event scoring and rank. |
| Team | `/ctf/team/` | Participant | Inspect team membership and status. |
| Join team | `/ctf/team/join/` | Participant | Join or create a team where event rules allow it. |
| Help | `/ctf/help/` | Participant | Get CTF-specific help. |

#### CTF Organizer Pages

| Current page | Route | Primary user | Primary purpose |
| --- | --- | --- | --- |
| Organizer dashboard | `/ctf/admin/` | Organizer | Monitor and manage CTF operations. |
| Events | `/ctf/admin/events/` | Organizer | List CTF events. |
| Create event | `/ctf/admin/events/create/` | Organizer | Configure a new event. |
| Event detail | `/ctf/admin/events/<event_id>/` | Organizer | Inspect one event and its operations. |
| Edit event | `/ctf/admin/events/<event_id>/edit/` | Organizer | Change event configuration. |
| Force-delete event | `/ctf/admin/events/<event_id>/force-delete/` | Organizer | Perform destructive event cleanup. |
| Challenges | `/ctf/admin/events/<event_id>/challenges/` | Organizer | List event challenges. |
| Create challenge | `/ctf/admin/events/<event_id>/challenges/create/` | Organizer | Add a challenge to an event. |
| Challenge detail | `/ctf/admin/challenges/<challenge_id>/` | Organizer | Inspect challenge configuration and submissions. |
| Edit challenge | `/ctf/admin/challenges/<challenge_id>/edit/` | Organizer | Change challenge configuration. |
| Upload challenge file | `/ctf/admin/challenges/<challenge_id>/upload/` | Organizer | Attach files to a challenge. |
| Participants | `/ctf/admin/events/<event_id>/participants/` | Organizer | Monitor and manage participants. |
| Import participants | `/ctf/admin/events/<event_id>/participants/import/` | Organizer | Bulk import event participants. |
| Add participant | `/ctf/admin/events/<event_id>/participants/add/` | Organizer | Add a participant manually. |
| Participant detail | `/ctf/admin/participants/<participant_id>/` | Organizer | Inspect one participant, progress, and range state. |
| Teams | `/ctf/admin/events/<event_id>/teams/` | Organizer | Manage event teams. |
| Scoreboard admin | `/ctf/admin/events/<event_id>/scoreboard/` | Organizer | Inspect and manage event scoring. |
| Brackets | `/ctf/admin/events/<event_id>/brackets/` | Organizer | Manage event brackets or cohorts. |
| Create bracket | `/ctf/admin/events/<event_id>/brackets/create/` | Organizer | Add a bracket. |
| Edit bracket | `/ctf/admin/brackets/<bracket_id>/edit/` | Organizer | Change bracket configuration. |
| Delete bracket | `/ctf/admin/brackets/<bracket_id>/delete/` | Organizer | Remove a bracket. |
| Ranges | `/ctf/admin/events/<event_id>/ranges/` | Organizer | Monitor participant range provisioning. |
| Notifications | `/ctf/admin/events/<event_id>/notifications/` | Organizer | List event notifications. |
| Create notification | `/ctf/admin/events/<event_id>/notifications/create/` | Organizer | Send or schedule event communication. |
| Email templates | `/ctf/admin/events/<event_id>/email-templates/` | Organizer | Manage event email copy. |
| Analytics | `/ctf/admin/events/<event_id>/analytics/` | Organizer | Review event analytics and outcomes. |

### Mission Control

Mission Control is the operational surface for ranges, terminals, assets,
credentials, scripts, and NGFW resources. It also currently mounts experiments
under `/mission-control/experiments/`; this design treats experiments as an
adjacent organizer workflow until a separate product decision promotes it to a
top-level surface.

| Current page | Route | Primary user | Primary purpose |
| --- | --- | --- | --- |
| Dashboard / ranges | `/mission-control/` | Organizer | Launch and monitor ranges. |
| Agents | `/mission-control/agents/` | Organizer | Inspect or delete available agents. |
| Terminal | `/mission-control/terminal/` | Both | Access terminal sessions when a range is available. |
| Settings | `/mission-control/settings/` | Organizer | Change user or platform settings. |
| Help | `/mission-control/help/` | Both | Read Mission Control help. |
| Walkthrough | `/mission-control/walkthrough/` | Participant | CTF-only participant walkthrough entry from the shared sidebar. |
| NGFW list | `/mission-control/ngfw/` | Organizer | List NGFW instances. |
| NGFW setup | `/mission-control/ngfw/setup/` | Organizer | Configure NGFW provisioning. |
| NGFW detail | `/mission-control/ngfw/<app_id>/` | Organizer | Inspect one NGFW instance. |
| NGFW deprovision | `/mission-control/ngfw/<app_id>/deprovision/` | Organizer | Confirm NGFW deprovisioning. |
| Credentials | `/mission-control/credentials/` | Organizer | List reusable credentials. |
| Add credential | `/mission-control/credentials/add/` | Organizer | Create a credential. |
| Credential detail | `/mission-control/credentials/<credential_id>/` | Organizer | Inspect one credential. |
| Files | `/mission-control/files/` | Organizer | List uploaded scripts or files. |
| Upload file | `/mission-control/files/upload/` | Organizer | Upload a script or file. |
| Delete file | `/mission-control/files/<script_id>/delete/` | Organizer | Remove an uploaded script or file. |

#### Experiments Mounted Under Mission Control

| Current page | Route | Primary user | Primary purpose |
| --- | --- | --- | --- |
| Experiments | `/mission-control/experiments/` | Organizer | List experiments. |
| Create experiment | `/mission-control/experiments/create/` | Organizer | Create an experiment from a scenario and resources. |
| Experiment detail | `/mission-control/experiments/<experiment_id>/` | Organizer | Inspect experiment configuration and runs. |
| Start experiment | `/mission-control/experiments/<experiment_id>/start/` | Organizer | Start an experiment. |
| Cancel experiment | `/mission-control/experiments/<experiment_id>/cancel/` | Organizer | Cancel a running experiment. |
| Scripts | `/mission-control/experiments/scripts/` | Organizer | List experiment scripts. |
| Upload script | `/mission-control/experiments/scripts/upload/` | Organizer | Upload an experiment script. |
| Delete script | `/mission-control/experiments/scripts/<script_id>/delete/` | Organizer | Remove an experiment script. |
| Experiment download | `/mission-control/experiments/<experiment_id>/download/` | Organizer | Download experiment outputs. |
| Run artifact download | `/mission-control/experiments/<experiment_id>/runs/<run_number>/artifacts/<artifact_id>/download/` | Organizer | Download one run artifact. |

### Scenario Editor

Scenario Editor is the authoring surface for scenario templates. It is limited
to staff or Threat Research users by the existing shared access policy.

| Current page | Route | Primary user | Primary purpose |
| --- | --- | --- | --- |
| Scenario list | `/scenario-editor/` | Organizer | Browse scenarios and readiness metadata. |
| Create scenario | `/scenario-editor/create/` | Organizer | Create a scenario through form fields. |
| Create scenario from YAML | `/scenario-editor/create/yaml/` | Organizer | Create a scenario from structured YAML. |
| Scenario detail | `/scenario-editor/<scenario_id>/` | Organizer | Inspect scenario definition and metadata. |
| Edit scenario | `/scenario-editor/<scenario_id>/edit/` | Organizer | Edit scenario fields. |
| YAML editor | `/scenario-editor/<scenario_id>/editor/` | Organizer | Edit scenario YAML. |
| Delete scenario | `/scenario-editor/<scenario_id>/delete/` | Organizer | Remove a scenario. |
| Clone scenario | `/scenario-editor/<scenario_id>/clone/` | Organizer | Duplicate a scenario for adaptation. |
| Toggle enabled | `/scenario-editor/<scenario_id>/toggle-enabled/` | Organizer | Change scenario availability. |
| Toggle staff-only | `/scenario-editor/<scenario_id>/toggle-staff-only/` | Organizer | Change scenario visibility. |
| Export scenario | `/scenario-editor/<scenario_id>/export/` | Organizer | Download a scenario definition. |

### Risk Register

Risk Register is an organizer and self-hosting surface for platform risk,
exceptions, mitigations, API keys, and audit-oriented status.

| Current page | Route | Primary user | Primary purpose |
| --- | --- | --- | --- |
| Risk list | `/risk-register/` | Organizer | List current and historical risks. |
| Risk detail | `/risk-register/risks/<risk_id>/` | Organizer | Inspect one risk, comments, and status. |
| Create risk | `/risk-register/risks/create/` | Organizer | Record a risk. |
| Edit risk | `/risk-register/risks/<risk_id>/edit/` | Organizer | Change risk details. |
| Delete risk | `/risk-register/risks/<risk_id>/delete/` | Organizer | Soft-delete a risk. |
| Restore risk | `/risk-register/risks/<risk_id>/restore/` | Organizer | Restore a deleted risk. |
| Close risk | `/risk-register/risks/<risk_id>/close/` | Organizer | Mark a risk closed. |
| Reopen risk | `/risk-register/risks/<risk_id>/reopen/` | Organizer | Reopen a closed risk. |
| Add comment | `/risk-register/risks/<risk_id>/comments/add/` | Organizer | Add risk discussion or review notes. |
| Delete comment | `/risk-register/risks/<risk_id>/comments/<comment_id>/delete/` | Organizer | Remove a risk comment. |
| API keys | `/risk-register/api-keys/` | Organizer | List Risk Register API keys. |
| Create API key | `/risk-register/api-keys/create/` | Organizer | Create an API key. |
| Revoke API key | `/risk-register/api-keys/<key_id>/revoke/` | Organizer | Revoke an API key. |

### Documentation

Documentation is the shared knowledge surface. Today it has one index and a
catch-all nested page route.

| Current page | Route | Primary user | Primary purpose |
| --- | --- | --- | --- |
| Documentation index | `/docs/` | Both | Start from the docs tree. |
| Documentation page | `/docs/<path>/` | Both | Read a specific guide, reference, scenario, or technical page. |

## Proposed Sitemap

### Top-Level Platform Structure

```text
Shifter
|-- Participate
|   |-- Event Home
|   |-- Challenges
|   |-- Range
|   |-- Scoreboard
|   |-- Team
|   `-- Help
|-- Operate
|   |-- Overview
|   |-- Ranges
|   |-- CTF Events
|   |-- Participants
|   |-- Challenges
|   |-- Assets
|   |   |-- Agents
|   |   |-- NGFW
|   |   |-- Credentials
|   |   `-- Files
|   |-- Terminal
|   |-- Experiments
|   `-- Settings
|-- Author
|   |-- Scenarios
|   |-- Scenario Create
|   |-- Scenario YAML Editor
|   `-- Scenario Export
|-- Govern
|   |-- Risk Register
|   |-- Risk Detail
|   |-- API Keys
|   `-- Audit / Review Queues
`-- Learn
    |-- Role Start
    |   |-- Participant
    |   |-- Facilitator
    |   |-- Trainer
    |   |-- Contributor
    |   `-- Self-Hoster
    |-- Getting Started
    |-- How-To
    |-- Scenarios
    |-- Features
    |-- Reference
    `-- Technical
```

### Participant Surface

Participant mode is a bounded CTF and learning experience. It should not expose
organizer configuration, risk operations, or scenario authoring unless the same
user switches into an organizer role.

Primary navigation:

1. Event Home
2. Challenges
3. Range
4. Scoreboard
5. Team
6. Help

Secondary/contextual navigation:

- Challenge detail tabs: Instructions, Hints, Files, Submission, Related
  walkthrough.
- Range detail tabs: Status, Access, Credentials, Terminal, Troubleshooting.
- Event context: Rules, schedule, announcements, scoring model.

Personas and JTBD served:

- `persona-conference-ctf-attendee`: clear challenge progression and recovery.
- `persona-internal-trainer`: learner-facing progression and support material.
- `persona-panw-consultant-demo-operator`: participant state that can be
  explained during a live event.
- `pain-mixed-skill-onboarding`: calm entry points and explicit next steps.

### Organizer Surface

Organizer mode is the operational and authoring experience. It combines
facilitation, range operations, scenario authoring, risk governance, and
documentation for operators.

Primary navigation:

1. Operate
2. Author
3. Govern
4. Learn

Operate navigation:

- Overview
- Ranges
- CTF Events
- Participants
- Challenges
- Assets
- Terminal
- Experiments
- Settings

Author navigation:

- Scenarios
- Create Scenario
- YAML Editor
- Validation
- Export

Govern navigation:

- Risks
- Exceptions and Mitigations
- API Keys
- Review Dates

Learn navigation:

- Facilitator guides
- Trainer guides
- Contributor guides
- Self-hosting guides
- Technical reference

Personas and JTBD served:

- `persona-panw-consultant-demo-operator`: event and range health in one
  operational model.
- `persona-internal-trainer`: scenario readiness, participant readiness, and
  reusable course preparation.
- `persona-self-hosting-oss-adopter`: risk, deployment, security, and
  operational responsibility.
- `persona-oss-contributor-evaluator`: surface names that map to code
  ownership.
- `pain-fragmented-operational-state`: shared placement for range, event,
  participant, credential, terminal, and cleanup state.
- `pain-authoring-confidence`: authoring grouped around scenario validity and
  launch readiness.
- `pain-docs-not-role-routed`: documentation entry points routed by role.

## Navigation Model

### Global Frame

The product should use one global frame for authenticated users:

- A compact global top bar identifies Shifter, current mode, current event or
  range context when one is active, and account actions.
- A role-aware side nav holds the primary surface links for the current mode.
- A page header states the current object and primary actions.
- Breadcrumbs appear on nested object pages, not on single-level dashboards.

The existing left sidebar can evolve into this shared frame, but the source of
navigation truth should be centralized in later implementation rather than
hard-coded separately by each app.

### Mode Switching

Users with both participant and organizer access need an explicit mode switch:

- Participant mode: "Participate" appears as the current mode and routes to the
  active event experience.
- Organizer mode: "Operate", "Author", "Govern", and "Learn" appear as
  organizer surfaces.
- Switching modes changes navigation structure and default landing page, but it
  does not grant permissions.

Users with only participant access should not see organizer surfaces. Users with
only organizer access should not be forced through CTF participant pages.

### Side Navigation

Use side navigation for durable surfaces that users revisit frequently:

- Participant: Event Home, Challenges, Range, Scoreboard, Team, Help.
- Organizer: Overview, Ranges, CTF Events, Assets, Terminal, Experiments,
  Scenarios, Risks, Docs.

Side navigation items must map to stable route names and permission policies.
The minimum future contract for a side-nav item is:

```text
surface
audience
route_name
permission_policy
owner_app
purpose
```

### Top Navigation

Use top navigation for platform-level context, not for every app:

- Product identity.
- Current mode.
- Active event or range switcher when relevant.
- Search or command entry if added later.
- Account menu and logout.

Do not duplicate the full side nav in the top nav.

### Breadcrumbs

Use breadcrumbs on nested object pages:

- `Operate > CTF Events > Event > Participants > Participant`
- `Operate > CTF Events > Event > Challenges > Challenge`
- `Author > Scenarios > Scenario > YAML Editor`
- `Govern > Risks > Risk`
- `Learn > Technical > Platform Infrastructure > Networking`

Do not use breadcrumbs on shallow landing pages such as dashboards, list pages,
or the participant event home.

### Contextual Subnavigation

Use tabs or local subnav inside a single object where the user is still working
on one entity:

- Event: Overview, Participants, Teams, Challenges, Ranges, Scoreboard,
  Notifications, Analytics.
- Challenge: Overview, Flags, Hints, Files, Prerequisites, Submissions.
- Range: Status, Access, Credentials, Terminal, Lifecycle.
- Scenario: Overview, Resources, YAML, Validation, Export.
- Risk: Overview, Mitigation, Comments, History.

### Modals And Overlays

Use modals only for bounded, reversible, or confirmatory actions:

- Confirm destructive actions such as force-delete, deprovision, revoke, or
  delete.
- Collect short forms where the user can complete the task without losing
  context.
- Show transient upload or validation progress when the underlying page remains
  the task owner.

Use full pages for complex creation and editing:

- Event creation.
- Challenge editing.
- Scenario YAML editing.
- Range provisioning.
- Risk creation and editing.
- API key creation.

Overlays must not become hidden routes for privileged functionality. They must
call the same permission-checked endpoints as full-page flows.

## Taxonomy

Use one canonical name per concept.

| Canonical term | Definition | Avoid using as synonym |
| --- | --- | --- |
| Platform | The whole Shifter product across CTF, Mission Control, Scenario Editor, Risk Register, and Documentation. | App, portal when referring to the whole product. |
| Surface | A user-facing product area with a stable job and navigation placement. | App when talking to users. |
| Mode | The user's current operating frame: Participant or Organizer. | Persona, role. |
| Role | Permission-relevant user classification such as CTF Participant, CTF Organizer, staff, or Threat Research. | Mode, persona. |
| Persona | Research archetype from the UX-003 research artifact. | Role, group. |
| Event | A time-bound CTF or training delivery with participants, teams, challenges, scoring, and communication. | Mission, course, campaign. |
| Participant | A learner or competitor taking part in an event. | User when event membership matters. |
| Organizer | A facilitator, trainer, operator, or staff user managing event or platform operations. | Admin except for Django admin. |
| Team | A participant grouping inside an event. | Bracket, cohort. |
| Bracket | A scoring or grouping partition inside an event. | Team. |
| Challenge | A CTF task solved by a participant or team for points. | Scenario, mission. |
| Hint | Assistance attached to a challenge. | Walkthrough. |
| Scoreboard | Event scoring display. | Leaderboard unless deliberately renamed everywhere. |
| Range | Provisioned lab infrastructure for a user, team, event, or scenario. | Environment, lab when referring to the managed resource. |
| Asset | Operational resource used by a range or workflow: agent, NGFW, credential, script, or file. | Scenario resource when it is managed outside the scenario definition. |
| Agent | Managed endpoint or automation participant available to Mission Control. | Instance unless the object is an infrastructure instance. |
| NGFW | Next-generation firewall resource managed by Mission Control. | Firewall when the product object specifically means NGFW. |
| Credential | Reusable secret or access material managed by Mission Control. | Password, key, secret in UI labels unless the subtype matters. |
| File | Uploaded script or file managed by Mission Control. | Attachment unless attached to a CTF challenge. |
| Scenario | Reusable range or exercise definition authored in Scenario Editor. | Challenge, event, mission. |
| Scenario YAML | Structured source representation for a scenario. | Config blob. |
| Experiment | Organizer-run execution workflow mounted under Mission Control today, usually combining a scenario, scripts, and artifacts. | Scenario, range, event. |
| Risk | Tracked security, operational, or governance concern. | Issue unless referring to GitHub issues. |
| Mitigation | Action or control that reduces a risk. | Fix unless a code fix is specifically meant. |
| API key | Revocable credential for API access. | Token unless API docs require the protocol term. |
| Documentation | User and technical knowledge surfaced under `/docs/`. | Help when referring to canonical docs. |
| Guide | Task-oriented documentation. | Reference. |
| Reference | Stable factual documentation for APIs, architecture, or concepts. | Guide. |
| Walkthrough | Step-by-step event or scenario assistance. | Hint, guide. |

## Maintenance Rule

This artifact must be updated whenever a new user-facing surface, page family,
or shared domain concept is added.

Minimum update checklist for future changes:

1. Add the page family to Current-State Inventory with route, audience, and
   purpose.
2. Place the surface in the Proposed Sitemap or explain why it remains
   contextual under an existing surface.
3. Update Navigation Model if the new surface changes mode switching, side nav,
   breadcrumbs, contextual subnav, or modal usage.
4. Add or revise Taxonomy terms if the new surface introduces a concept that
   crosses app boundaries.
5. Cite the persona, JTBD, or pain-point anchor served by the new surface.

## Requirement And Acceptance Mapping

| Source | Clause or criterion | Satisfied by |
| --- | --- | --- |
| `UX-003` | The platform shall expose a single navigation model spanning CTF, Mission Control, Scenario Editor, Risk Register, and Documentation. | Proposed Sitemap and Navigation Model. |
| `UX-003` | Participant and organizer surfaces shall be visually and structurally distinguished. | IA Principles, Participant Surface, Organizer Surface, Mode Switching, and Side Navigation. |
| `UX-003` | A maintained sitemap and taxonomy shall exist as design artifacts in the repository. | This document, Proposed Sitemap, Taxonomy, and Maintenance Rule. |
| `UX-003` | The maintained artifact shall be updated whenever a new surface is added. | Maintenance Rule. |
| Issue #1093 | Current-state inventory for every page grouped by app with primary user and purpose. | Current-State Inventory. |
| Issue #1093 | Proposed sitemap spanning all five apps with clear participant and organizer top-level surfaces. | Proposed Sitemap. |
| Issue #1093 | Navigation model covering top nav, side nav, breadcrumbs, and modal or overlay patterns. | Navigation Model. |
| Issue #1093 | Taxonomy with one name per cross-surface concept. | Taxonomy. |
| Issue #1093 | Decisions traced to personas and JTBD entries from research output. | Evidence And Inputs, Participant Surface, Organizer Surface. |
