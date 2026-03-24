# Audit Map

The codebase was divided into chunks that line up with both architectural boundaries and requirement clusters.

## Chunk 1: Architecture And Shared Contracts

Focus:

- boundary discipline
- layer rules
- shared enums, schemas, logging, exceptions
- multi-event context selection

Primary files:

- `scripts/check_layer_imports/layer_imports.yaml`
- `shifter/shifter_platform/config/logging.py`
- `shifter/shifter_platform/shared/*`
- `shifter/shifter_platform/cms/services.py`
- `shifter/shifter_platform/engine/services.py`
- `shifter/shifter_platform/ctf/bridges.py`
- `shifter/shifter_platform/ctf/exceptions.py`
- `shifter/shifter_platform/ctf/services/event.py`
- `shifter/shifter_platform/ctf/services/participant.py`

## Chunk 2: Domain Model, Scoring, Challenges, Participants

Focus:

- challenge CRUD and flags
- scoring and hint penalties
- teams and participant lifecycle
- category/difficulty/flag format modeling

Primary files:

- `shifter/shifter_platform/ctf/models.py`
- `shifter/shifter_platform/ctf/forms.py`
- `shifter/shifter_platform/ctf/services/challenge.py`
- `shifter/shifter_platform/ctf/services/submission.py`
- `shifter/shifter_platform/ctf/services/scoring.py`
- `shifter/shifter_platform/ctf/services/participant.py`

## Chunk 3: Range Integration, Automation, Notifications

Focus:

- participant range provisioning and access
- scheduler framework and task handlers
- event automation
- notification delivery and scheduling

Primary files:

- `shifter/shifter_platform/ctf/services/range.py`
- `shifter/shifter_platform/ctf/services/event.py`
- `shifter/shifter_platform/ctf/services/notification.py`
- `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py`
- `shifter/shifter_platform/ctf/bridges.py`
- `shifter/shifter_platform/engine/models.py`

## Chunk 4: Views, Admin Surfaces, Reporting

Focus:

- participant challenge/range/scoreboard flows
- organizer dashboards and analytics
- submission history surfaces
- whether the UI/API wiring actually matches the service layer

Primary files:

- `shifter/shifter_platform/ctf/views.py`
- `shifter/shifter_platform/templates/ctf/participant/*`
- `shifter/shifter_platform/templates/ctf/admin/*`

## Why This Split

This split keeps the review aligned with the way failures currently present:

- architecture drift is cross-cutting
- scoring and participant lifecycle issues are domain-model problems
- scheduler/range/notification issues are integration problems
- scoreboard and analytics issues are surface-wiring problems

That makes it easier to decide what should be fixed first and by whom.
