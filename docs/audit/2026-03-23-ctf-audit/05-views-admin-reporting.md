# Chunk Report: Views, Admin Surfaces, Reporting

Status: `Partial`

## What Still Looks Good

- Organizer pages exist for events, challenges, participants, ranges, notifications, analytics, teams, and the admin scoreboard.
- Participant pages exist for dashboard, event, challenges, challenge detail, range, scoreboard, and team flows.
- The subsystem is not missing its UI surface area; the main issue is that some important surfaces are wired incorrectly or only partially satisfy the requirement text.

## Findings

### 1. The participant scoreboard view and API are wired to different payload shapes

Evidence:

- `shifter/shifter_platform/ctf/views.py:404-410`
- `shifter/shifter_platform/templates/ctf/participant/scoreboard.html:15-55`
- `shifter/shifter_platform/ctf/views.py:2171-2177`
- `shifter/shifter_platform/ctf/services/scoring.py:105-113`

Why it matters:

- The view passes `rankings`, but the template checks `scoreboard`.
- The API returns `rankings`, but the JavaScript waits for `data.scoreboard`.
- The service emits `solve_count`, while the template renders `entry.solves`.

Assessment:

- The participant scoreboard service logic exists, but the participant scoreboard surface is effectively broken.

Requirement impact:

- `CTF-401`

### 2. The scoreboard does not implement row click-through to solve history

Evidence:

- `shifter/shifter_platform/templates/ctf/participant/scoreboard.html:31-56`

Why it matters:

- `CTF-401` explicitly requires participants to be able to click a row and see that participant's solve history.
- The current rows are plain table rows with no link target.

### 3. Challenge solve-rate analytics are calculated against submitters, not total participants

Evidence:

- `shifter/shifter_platform/ctf/services/scoring.py:239-252`

Why it matters:

- The requirement defines solve percentage as solves divided by total participants.
- The implementation divides by distinct submitters for that challenge.

Assessment:

- This inflates solve rate and weakens organizer analytics.

Requirement impact:

- `CTF-407`

### 4. Flag format guidance is challenge-level, not event-level

Evidence:

- `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html:70-72`

Why it matters:

- `CTF-116` describes an event-level flag-format hint shown on the event page.
- The implementation stores and renders flag format per challenge.

### 5. Submission history surfaces exist, but not at the completeness level described by the requirement

Evidence:

- `shifter/shifter_platform/ctf/views.py:1121-1135`
- `shifter/shifter_platform/ctf/views.py:1831-1854`

Why it matters:

- Organizers can inspect participant submissions and challenge submissions.
- Participants can fetch their own submissions.
- What is still missing from the requirement text is a full event-wide organizer search/filter surface and an explicit event configuration toggle for participant self-history.

Requirement impact:

- `CTF-1305`

## Requirement Readout From This Chunk

- Partial: `CTF-013`, `CTF-116`, `CTF-1305`, `CTF-401`, `CTF-407`

Notes:

- `CTF-013` is only partial because the surfaces exist, but some of the underlying analytics are wrong or thinner than the requirement suggests.

## Recommendation

Highest-value surface fixes:

1. Make the participant scoreboard use the same payload contract as the scoring service.
2. Add click-through solve-history behavior to scoreboard rows or narrow the requirement.
3. Recompute challenge solve rate against total event participants.
4. Decide whether flag format and submission-history visibility are event-level features or challenge-level conveniences, then align the model and UI.
