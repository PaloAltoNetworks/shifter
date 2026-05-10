# UX-003 OSS Shifter Research Personas

Date: 2026-05-10

Issue: #1092

This is the v1 desk-research artifact for the OSS Shifter redesign. It
documents who Shifter is for, what they are trying to get done, and where the
current product experience creates friction. It is intentionally not an
information architecture, wireframe, design system, or visual mockup.

## Evidence Boundary

Sources used:

- Existing Shifter surfaces: CTF, Mission Control, Scenario Editor, Risk
  Register, and Documentation.
- Existing CTF research in `docs/research/ctf-mixed-skill-design-research.md`
  and `docs/research/ctf-timing-completion-research.md`.
- Existing UX-002 visual identity boundary in
  `docs/design/ux-002-oss-visual-identity-preflight.md`.
- The APTL reference in `../aptl`, especially the dark operational deck and
  the Svelte lab UI. The reference is used as tone evidence only.
- Direct product context from maintaining Shifter as an OSS cyber range and CTF
  platform.

Not used:

- Unsanitized customer support logs, tenant identifiers, private URLs, tokens,
  screenshots with secrets, or telemetry dumps.
- User interviews. Those can be added later without changing this document's
  structure.

## Design Direction Evidence

The APTL reference points toward a dark operational interface: black or near
black base, quiet borders, a narrow top or bottom stripe, dense typography,
plain status text, and restrained semantic color. Its strongest qualities are
focus, scan speed, and a feeling that the product is an instrument rather than
marketing.

Downstream Shifter design work should treat that as the preferred direction:

- Prefer dark stripe and operational chrome over decorative panels.
- Use color for state, severity, ownership, or mode, not for random section
  framing.
- Keep cards quiet when they are needed. Avoid nested cards and loud colored
  bounding boxes.
- Keep typography dense and legible. Large type should be reserved for true
  page-level hierarchy.
- Preserve inspection workflows: users need to compare range state, challenge
  state, credentials, scenario YAML, and risk records without visual noise.

Anti-pattern for future UX issues: random colored bounding boxes, gradient
frames, chroma outlines, or unrelated accent blocks around content. That visual
language does not match Shifter's operational audience.

## Personas

### persona-panw-consultant-demo-operator

Name: Maya, PANW consultant running customer demo events.

Context:

Maya runs short customer-facing workshops and demos. She cares about a reliable
storyline, clean setup, and the ability to recover quickly when a participant's
range, login, or challenge state is wrong.

Primary goals:

- Launch and monitor a customer event without reading implementation details.
- See which teams are blocked and whether ranges are healthy.
- Explain scenario intent and product touchpoints without exposing internal
  plumbing.
- Reset, reprovision, or guide a participant with minimal context switching.

Pain points:

- Status is split across event pages, range pages, terminal access, and
  operational documentation.
- Event urgency makes ambiguous states expensive. "Provisioning", "available",
  "running", and "unhealthy" need specific operator meaning.
- Visual identity matters because the UI is projected or screen-shared in front
  of customers. Branding residue or noisy decoration distracts from the demo.

### persona-conference-ctf-attendee

Name: Jordan, conference attendee in CTF mode.

Context:

Jordan may be a first-time CTF participant, a working security practitioner, or
an expert player. They have limited time, may be using an unfamiliar laptop, and
need quick orientation.

Primary goals:

- Understand the event, team status, available challenges, scoring, and hints.
- Find a solvable challenge quickly and know what to do next.
- Access range resources and walkthrough material without hunting through admin
  surfaces.
- Recover from failed attempts without feeling lost.

Pain points:

- Mixed-skill events punish unclear progression. Beginners need entry points;
  experts need enough depth and parallel work.
- Participants need a clear distinction between challenge instructions, range
  connection details, scoring, and narrative flavor.
- A loud UI can make the event feel harder than the task. Dense, calm state
  presentation is more useful than spectacle.

### persona-internal-trainer

Name: Priya, internal trainer preparing a cohort.

Context:

Priya runs repeated training sessions for analysts, engineers, or field teams.
She needs predictable setup, reusable scenarios, and post-session evidence about
where learners struggled.

Primary goals:

- Prepare a course path from existing scenarios and documentation.
- Adjust difficulty and support material for different cohorts.
- Monitor progress during the session and identify students who need help.
- Capture lessons learned for the next delivery.

Pain points:

- Scenario readiness, participant readiness, and range readiness are related but
  not presented as one teaching workflow.
- Difficulty metadata is useful only when it maps to observable learner tasks.
- Trainers need documentation that distinguishes "how to run the event" from
  "how to solve the exercise".

### persona-oss-contributor-evaluator

Name: Sam, OSS contributor evaluating Shifter.

Context:

Sam is deciding whether Shifter is worth contributing to or extending. They may
start from GitHub, local setup docs, architecture notes, or a running demo.

Primary goals:

- Understand what Shifter does, what is stable, and where contribution is
  welcome.
- Find the right subsystem and local development path.
- Make a small change without tripping hidden architecture or workflow rules.
- See how UI concepts map to code ownership.

Pain points:

- OSS evaluators are sensitive to unclear mental models. If CTF, Mission
  Control, Scenario Editor, Risk Register, and Documentation feel unrelated,
  the system looks larger than it is.
- Contribution confidence depends on naming. Product surfaces, backend
  concepts, and repo paths should line up.
- Contributors need an honest view of rough edges without internal-only terms.

### persona-self-hosting-oss-adopter

Name: Alex, self-hosting OSS adopter.

Context:

Alex wants to deploy Shifter for a team, lab, or internal program. They care
about installation, security posture, ongoing maintenance, and whether the
platform can survive real use.

Primary goals:

- Install Shifter with a clear backend/deployment model.
- Understand required infrastructure, secrets, identity, and operational
  responsibilities.
- Confirm that ranges, events, and documentation work for their environment.
- Upgrade safely and troubleshoot without product-team context.

Pain points:

- Self-hosters need deployment truth before visual polish. Ambiguous setup
  states erode trust.
- Security defaults, secret handling, and cloud-provider boundaries must be
  visible without requiring source spelunking.
- Documentation must answer "what do I own?" as much as "what button do I
  click?"

## Jobs To Be Done By Surface

### surface-ctf

Personas served: `persona-panw-consultant-demo-operator`,
`persona-conference-ctf-attendee`, `persona-internal-trainer`.

Jobs:

- When I join an event, I want to understand the rules, challenge set, scoring,
  and team state so I can start without facilitator help.
- When I am stuck, I want hints, walkthrough context, or easier adjacent work so
  I can keep momentum instead of dropping out.
- When I facilitate an event, I want to see participant progress and blockers so
  I can intervene before frustration spreads.
- When a challenge or range dependency is unhealthy, I want the UI to separate
  platform issues from participant mistakes.

### surface-mission-control

Personas served: `persona-panw-consultant-demo-operator`,
`persona-internal-trainer`, `persona-self-hosting-oss-adopter`.

Jobs:

- When I run a range, I want one reliable operational view of provisioning,
  instance health, credentials, terminal access, and cleanup.
- When something fails, I want the next action to be obvious: retry, inspect,
  reset, deprovision, or escalate.
- When I share the interface in a live setting, I want it to look calm and
  professional without proprietary branding residue.
- When I self-host, I want state labels that map to real infrastructure
  lifecycle and do not hide risk behind friendly copy.

### surface-scenario-editor

Personas served: `persona-internal-trainer`, `persona-oss-contributor-evaluator`,
`persona-panw-consultant-demo-operator`.

Jobs:

- When I create or adapt a scenario, I want to understand required machines,
  services, flags, credentials, and validation constraints before launch.
- When YAML or structured scenario input is invalid, I want errors tied to the
  domain concept I was editing, not just parser output.
- When I compare scenarios, I want difficulty, mode, estimated time, and
  required resources to be visible without opening every file.
- When I contribute a scenario, I want the editor's language to match repository
  concepts so I can move between UI and code.

### surface-risk-register

Personas served: `persona-self-hosting-oss-adopter`,
`persona-oss-contributor-evaluator`, `persona-panw-consultant-demo-operator`.

Jobs:

- When I operate Shifter, I want risks, exceptions, and mitigations visible
  enough to support deployment decisions.
- When a risk affects a demo, training, or self-hosted deployment, I want to
  know ownership, status, and next review date.
- When I evaluate the OSS project, I want security posture to be direct and
  credible, not hidden behind marketing language.

### surface-documentation

Personas served: all personas.

Jobs:

- When I arrive cold, I want a clear path for my role: participant, facilitator,
  trainer, contributor, or self-hoster.
- When I follow setup docs, I want prerequisites, secrets, commands, and
  expected results separated from conceptual explanation.
- When I troubleshoot, I want known states, failure modes, and recovery steps
  written in the same vocabulary as the UI.
- When I plan future UX work, I want persona and JTBD anchors that justify IA,
  design-system, and mockup decisions.

## Current-State Pain Points

### pain-fragmented-operational-state

Affected personas: demo operator, trainer, self-hoster.

Observation:

Range and event state crosses multiple surfaces. Users need to synthesize health,
participant status, credentials, terminal access, provisioning, and teardown from
several places.

Interpretation:

Future IA should make operational state scannable before decorative identity.
The APTL-style dark stripe is useful here because it leaves room for dense state
tables and concise status text.

### pain-mixed-skill-onboarding

Affected personas: CTF attendee, trainer, demo operator.

Observation:

Existing CTF research shows mixed-skill audiences need easy entry points,
parallel work, hints, and clear difficulty progression.

Interpretation:

CTF UX should reduce intimidation. Avoid visual treatments that make beginner
work look like a high-stakes security console. Use calm hierarchy, progressive
challenge grouping, and explicit "what next" affordances.

### pain-surface-vocabulary-drift

Affected personas: contributor, trainer, self-hoster.

Observation:

The product has several named surfaces with distinct jobs. When labels,
documentation, and repo paths do not reinforce those boundaries, users must
build their own model.

Interpretation:

Future IA should preserve the existing surface names unless a specific issue
renames them. Documentation and UI should make the relationship between surface,
user job, and implementation area obvious.

### pain-branding-and-visual-noise

Affected personas: demo operator, CTF attendee, self-hoster.

Observation:

UX-002 removed proprietary branding contamination, but the final OSS visual
identity is still open. Generic LLM-generated redesigns often replace brand
residue with arbitrary colored frames, glowing boxes, and decorative gradients.

Interpretation:

Shifter should not go there. The stronger direction is restrained operational
chrome: dark base, narrow stripe, quiet separators, semantic color, and plain
content density.

### pain-docs-not-role-routed

Affected personas: all personas.

Observation:

Different users arrive with different intents, but documentation is usually
organized by system topic. A participant, facilitator, contributor, and
self-hoster do not need the same first page.

Interpretation:

Documentation IA should add role-routed entry points while keeping canonical
technical references in one place.

### pain-authoring-confidence

Affected personas: trainer, contributor, demo operator.

Observation:

Scenario authoring requires confidence that a scenario is complete, valid, and
appropriate for an audience before it is used live.

Interpretation:

Scenario Editor redesign work should emphasize validation state, required
resources, audience fit, and launch readiness over decorative card grids.

## Citation Map For Follow-Up UX Work

Future issues can cite these stable anchors:

- Personas: `persona-panw-consultant-demo-operator`,
  `persona-conference-ctf-attendee`, `persona-internal-trainer`,
  `persona-oss-contributor-evaluator`, `persona-self-hosting-oss-adopter`.
- Surfaces: `surface-ctf`, `surface-mission-control`,
  `surface-scenario-editor`, `surface-risk-register`,
  `surface-documentation`.
- Pain points: `pain-fragmented-operational-state`,
  `pain-mixed-skill-onboarding`, `pain-surface-vocabulary-drift`,
  `pain-branding-and-visual-noise`, `pain-docs-not-role-routed`,
  `pain-authoring-confidence`.

## Acceptance Mapping

- Personas: covered in `Personas` with five distinct archetypes.
- JTBD: covered in `Jobs To Be Done By Surface` across all existing Shifter
  surfaces.
- Current-state pain points: covered in `Current-State Pain Points`.
- Future redesign citation support: covered by stable anchors in `Citation Map
  For Follow-Up UX Work`.
