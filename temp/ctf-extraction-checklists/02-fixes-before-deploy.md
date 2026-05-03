# Fixes Before Deploy

## Must Fix

- [ ] Implement a real participant registration flow.
  Current gap: `register_participant()` exists, but the invite-token flow does not call it end to end.

- [ ] Fix invitation timestamps.
  Change `invited_at` handling so participants are not marked as already invited before the email send path runs.

- [ ] Fix participant range ownership.
  Do not create participant ranges as `event.created_by`. Range creation must run as the actual participant user.

- [ ] Add organizer ownership checks to the new phase 7 views and APIs.
  Range and notification endpoints must enforce `event.created_by_id == request.user.pk`.

- [ ] Remove Celery dependency from the MVP extraction.
  Keep notification send and event/range lifecycle actions manual unless `dev` already has an approved scheduler path.

- [ ] If any scheduling is kept, redesign scheduled notification execution.
  It needs a task type keyed to the actual notification record, not a blanket reminder task.

- [ ] Renumber the management migration on top of `origin/dev`.
  The CTF `UserProfile` fields need a new `0003`, not the branch's `0002`.

## Strongly Recommended

- [ ] Hide or disable unfinished organizer pages.
  Current placeholders: team list, organizer scoreboard, analytics.

- [ ] Decide whether `CTFEvent.range_config` is part of launch scope.
  If yes, port the migration and wire organizer input properly.
  If no, hard-code a known-good range setup for the first event.

- [ ] Decide how email will run on `dev`.
  If SES-backed email is required, port only the needed backend dependency and email settings.

- [ ] Review `ctf/services/__init__.py` export behavior after the phase 7 edits.

- [ ] Re-run authorization checks on all organizer views after merge.

## Nice To Have After Launch

- [ ] Revisit scheduled reminders and announcements after the first deployment.
- [ ] Revisit team mode after the first deployment.
- [ ] Revisit automated range spin-up and cleanup after the first deployment.
