# Validation And Cutover Checklist

## 1. Merge Order

- [ ] Create extraction branch from `origin/dev`
- [ ] Port core CTF app and templates
- [ ] Merge config and auth changes
- [ ] Create the new management migration
- [ ] Port edited phase 7 files
- [ ] Hide unfinished organizer pages if they are still placeholders

## 2. Test Runs

Run from `shifter/shifter_platform`:

- [ ] `TESTING=1 ./.venv/bin/python manage.py check`
- [ ] `TESTING=1 ./.venv/bin/python manage.py makemigrations --check --dry-run`
- [ ] `TESTING=1 ./.venv/bin/python -m pytest ctf/tests`
- [ ] `TESTING=1 ./.venv/bin/python -m pytest tests/engine/services/test_create_range.py tests/engine/services/test_destroy_range.py tests/engine/services/test_pause_range.py tests/engine/services/test_resume_range.py tests/mission_control/test_engine_services.py`

## 3. Manual Smoke Test

- [ ] Organizer can log in and access the CTF dashboard
- [ ] Organizer can create an event
- [ ] Organizer can create challenges and publish the event
- [ ] Organizer can add or import participants
- [ ] Invite email flow completes without skipping participants
- [ ] Participant can accept invite or complete the intended registration path
- [ ] Participant can log in and reach the participant dashboard
- [ ] Participant can view the event and challenge list
- [ ] Participant can provision a range through the existing `dev` runtime path
- [ ] Multiple participants can each get their own range without user-ownership collisions
- [ ] Participant can submit a flag and receive scoring updates
- [ ] Organizer can send an announcement manually
- [ ] Organizer range and notification pages reject access to events they do not own

## 4. Deployment Gate

- [ ] Do not deploy if participant registration still depends on unfinished invite-token wiring
- [ ] Do not deploy if multi-participant range provisioning still creates ranges as the organizer
- [ ] Do not deploy if organizer ownership checks are missing on phase 7 endpoints
- [ ] Do not deploy if invitation emails are still skipped by `invited_at` state
- [ ] Do not deploy if the extraction still depends on Celery beat or the docker runtime migration

## 5. Cutover Notes

- [ ] Keep the first launch operationally simple: manual sends, manual lifecycle actions, existing runtime
- [ ] Defer docker migration hardening to a separate branch and deployment window
- [ ] Capture any remaining docker migration requirements as a follow-up plan, not as launch scope
