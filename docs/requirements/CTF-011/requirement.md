---
id: CTF-011
title: "Import/Export & Data Management"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:21.269023Z
updated_at: 2026-03-26T06:33:57.412225Z
---

# CTF-011: Import/Export & Data Management

## Statement

The CTF layer could support importing challenge content from external sources (including CTFd-format challenge packs) and exporting event data for reuse, analysis, or sharing with other Shifter instances.

## Rationale

Import/export enables challenge reuse across events and leveraging community challenge libraries. Many challenge authors publish challenge packs in CTFd format; import support lets Shifter organizers use this existing content without manual recreation. Export enables post-event reporting and sharing challenge sets across Shifter deployments.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant.py` (Participant CSV bulk import service (partial: imports participants, not challenges))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/forms.py` (CTFParticipantImportForm - CSV upload form for participant import)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_participant_views.py` (Tests for participant CSV import views)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#625` (CTF-011: Import/Export & Data Management)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_people.py` (Participant import views (CSV form + JSON API) - partial import capability)
