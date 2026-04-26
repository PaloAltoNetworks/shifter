# Port Checklist

## 1. Start Clean

- [ ] Create a new extraction branch from `origin/dev`.
- [ ] Do not merge or cherry-pick the branch wholesale.
- [ ] Port the CTF feature set manually or selectively cherry-pick only the CTF commits.

Suggested source commits:
- [ ] `d809892a` Phase 1 CTF foundation
- [ ] `6d731c13` Phase 2 auth and routing
- [ ] `5ec3a922` Phase 3 event management
- [ ] `56d86742` Phase 4 challenge management
- [ ] `34c416d5` planning docs plus participant service groundwork
- [ ] `6c2f3e66` Phase 5 participant management
- [ ] Selective CTF-only content from `1866fd63`

## 2. Port Core CTF App

- [ ] Port `shifter/shifter_platform/ctf/__init__.py`
- [ ] Port `shifter/shifter_platform/ctf/admin.py`
- [ ] Port `shifter/shifter_platform/ctf/apps.py`
- [ ] Port `shifter/shifter_platform/ctf/context_processors.py`
- [ ] Port `shifter/shifter_platform/ctf/enums.py`
- [ ] Port `shifter/shifter_platform/ctf/exceptions.py`
- [ ] Port `shifter/shifter_platform/ctf/forms.py`
- [ ] Port `shifter/shifter_platform/ctf/models.py`
- [ ] Port `shifter/shifter_platform/ctf/urls.py`
- [ ] Port `shifter/shifter_platform/ctf/views.py`
- [ ] Port `shifter/shifter_platform/ctf/migrations/0001_initial.py`
- [ ] Port `shifter/shifter_platform/ctf/services/__init__.py`
- [ ] Port `shifter/shifter_platform/ctf/services/challenge.py`
- [ ] Port `shifter/shifter_platform/ctf/services/event.py`
- [ ] Port `shifter/shifter_platform/ctf/services/participant.py`
- [ ] Port `shifter/shifter_platform/ctf/services/scoring.py`
- [ ] Port `shifter/shifter_platform/ctf/services/submission.py`

## 3. Port Templates

- [ ] Port `shifter/shifter_platform/templates/ctf/base.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/help.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/login.html`
- [ ] Port all organizer templates under `shifter/shifter_platform/templates/ctf/admin/`
- [ ] Port all participant templates under `shifter/shifter_platform/templates/ctf/participant/`
- [ ] Port `shifter/shifter_platform/templates/partials/ctf_organizer_sidebar.html`
- [ ] Port `shifter/shifter_platform/templates/partials/ctf_participant_sidebar.html`

## 4. Port Config and Routing

- [ ] Merge the CTF auth changes from `shifter/shifter_platform/config/dev_auth.py`
- [ ] Merge the CTF auth changes from `shifter/shifter_platform/config/oidc.py`
- [ ] Merge the CTF routing changes from `shifter/shifter_platform/config/urls.py`
- [ ] Merge the CTF entry-point changes from `shifter/shifter_platform/config/views.py`
- [ ] Merge only the CTF-specific settings from `shifter/shifter_platform/config/settings.py`

## 5. Port Management Model Changes

- [ ] Port the CTF-related `UserProfile` fields in `shifter/shifter_platform/management/models.py`
- [ ] Do not reuse `shifter/shifter_platform/management/migrations/0002_userprofile_active_ctf_event_userprofile_user_type.py`
- [ ] Create a new management migration on top of `origin/dev` as `0003`

## 6. Port Tests

- [ ] Port `shifter/shifter_platform/ctf/tests/__init__.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/conftest.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/factories.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/test_auth.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/test_challenges.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/test_events.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/test_models.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/test_participant_views.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/test_integration/__init__.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/test_services/__init__.py`
- [ ] Port `shifter/shifter_platform/ctf/tests/test_views/__init__.py`

## 7. Port Phase 7 Selectively And Edit First

Bring these over only after the fixes in `02-fixes-before-deploy.md` are applied:

- [ ] Port edited `shifter/shifter_platform/ctf/services/range.py`
- [ ] Port edited `shifter/shifter_platform/ctf/services/notification.py`
- [ ] Port edited `shifter/shifter_platform/ctf/views.py`
- [ ] Port edited `shifter/shifter_platform/ctf/urls.py`
- [ ] Port `shifter/shifter_platform/templates/ctf/admin/notification_form.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/admin/notification_list.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/admin/range_list.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/email/announcement.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/email/announcement.txt`
- [ ] Port `shifter/shifter_platform/templates/ctf/email/credentials.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/email/credentials.txt`
- [ ] Port `shifter/shifter_platform/templates/ctf/email/invitation.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/email/invitation.txt`
- [ ] Port `shifter/shifter_platform/templates/ctf/email/reminder.html`
- [ ] Port `shifter/shifter_platform/templates/ctf/email/reminder.txt`
- [ ] Port the updated tests for notification and range behavior

## 8. Leave Behind With The Docker Migration

- [ ] Do not port `shifter/shifter_platform/docker-compose.yml`
- [ ] Do not port `shifter/shifter_platform/docker-compose.deploy.yml`
- [ ] Do not port `shifter/shifter_platform/Dockerfile`
- [ ] Do not port `shifter/shifter_platform/Dockerfile.worker`
- [ ] Do not port anything under `shifter/shifter_platform/nginx/`
- [ ] Do not port `shifter/shifter_platform/config/celery.py`
- [ ] Do not port `shifter/shifter_platform/engine/tasks.py`
- [ ] Do not port `shifter/shifter_platform/engine/receivers.py`
- [ ] Do not port `shifter/shifter_platform/engine/signals.py`
- [ ] Do not port `shifter/shifter_platform/cms/receivers.py`
- [ ] Do not port `shifter/shifter_platform/mission_control/receivers.py`
- [ ] Do not port anything under `shifter/shifter_platform/engine/provisioner/`
- [ ] Do not port docker deploy scripts or env-example changes tied to the new runtime

## 9. Explicitly Exclude From The First Extraction

- [ ] Exclude `shifter/shifter_platform/ctf/tasks.py` from the first deployable extraction
- [ ] Exclude Celery beat scheduling from the first deployable extraction
- [ ] Keep event lifecycle and notification sends manual in the first release
