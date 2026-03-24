# Chunk Report: Range Integration, Automation, Notifications

Status: `Partial`

## What Still Looks Good

- The scheduler loop itself is sensibly structured: it claims tasks with `select_for_update(skip_locked=True)`, marks stale tasks failed, and emits useful logs.
- Event automation captures the right kinds of tasks: spin-up, start, end, cleanup, reminder.
- Range provisioning is at least conceptually integrated with the existing CMS path instead of reimplementing provisioning inside CTF.

## Findings

### 1. Reminder task execution is still stubbed

Evidence:

- `shifter/shifter_platform/ctf/management/commands/run_ctf_scheduler.py:202-206`

Why it matters:

- The scheduler sees due `SEND_REMINDER` tasks and does not execute reminder delivery.
- It only logs a warning.

Requirement impact:

- `CTF-008`, `CTF-010`, `CTF-1001`

### 2. Scheduled notifications are all encoded as reminder tasks

Evidence:

- `shifter/shifter_platform/ctf/services/notification.py:363-370`

Why it matters:

- `schedule_notification()` always creates a `SEND_REMINDER` task, even for scheduled announcements.
- It stores `notification_id` in task metadata, but the reminder handler does not consume metadata at all.

Assessment:

- The scheduling abstraction does not reflect notification intent.
- This is both a modeling problem and a runtime problem.

Requirement impact:

- `CTF-008`, `CTF-010`, `CTF-1001`

### 3. CTF stores a CMS `RangeInstance` PK, but the participant range view treats it like an engine `Range` PK

Evidence:

- `shifter/shifter_platform/ctf/services/range.py:83-89`
- `shifter/shifter_platform/ctf/views.py:361-366`

Why it matters:

- `provision_participant_range()` stores the CMS `RangeInstance` ID.
- `participant_range()` then queries `engine.models.Range` using that same integer.

Assessment:

- This is an ID-space bug, not just naming confusion.
- It directly threatens `CTF-009`, `CTF-901`, and `CTF-906`.

### 4. The bridge and the engine disagree on the shape of provisioned instance data

Evidence:

- `shifter/shifter_platform/ctf/bridges.py:155-178`
- `shifter/shifter_platform/engine/models.py:297-300`

Why it matters:

- The bridge assumes a mapping keyed by instance UUID.
- The engine model says the field is a JSON array.

Assessment:

- Even if runtime data currently happens to work, the contract is underspecified and fragile.

### 5. Scheduler comments are stale relative to the codebase

Evidence:

- `shifter/shifter_platform/ctf/services/event.py:552-557`

Why it matters:

- `_schedule_event_tasks()` still says there is no background worker and a future management command will be needed.
- `run_ctf_scheduler.py` now exists.

Assessment:

- This is lower severity than the runtime bugs above, but it is still a clarity problem in a subsystem where operational behavior matters.

## Requirement Readout From This Chunk

- Partial: `CTF-008`, `CTF-009`, `CTF-010`, `CTF-1001`, `CTF-1002`, `CTF-1006`, `CTF-901`, `CTF-906`

Notes:

- `CTF-1002` is directionally implemented because pre-spinup time and throttling exist.
- `CTF-1006` is not fully met in application terms; the current design still depends on separate scheduler process management.

## Recommendation

Highest-value integration fixes:

1. Implement `SEND_REMINDER` for real and route scheduled announcements through the correct handler type.
2. Define one CTF range reference type and use it consistently end-to-end.
3. Normalize the `provisioned_instances` contract so the bridge and engine agree on one structure.
4. Decide whether `CTF-1006` is meant literally. If yes, the current separate scheduler-process model does not satisfy it.
