---
id: CTF-707
title: "Event Metadata"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T07:23:16.931933Z
updated_at: 2026-03-19T03:07:16.214511Z
---

# CTF-707: Event Metadata

## Statement

Events shall have a name, description, rules text, and scenario template selection. The name and description shall be displayed to participants on the event listing and detail pages. Rules text shall be presented to participants before registration. Scenario template selection shall determine the range configuration provisioned for each participant.

## Rationale

Event metadata is the minimum information needed to create and present a CTF event. Without a name and description, events cannot be listed. Without rules, participants have no expectations. Without scenario template selection, the system cannot provision the correct range environment. This is foundational to event creation.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFEvent model - name, description, scenario_id fields)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/event.html` (Participant event detail template - displays name and description)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/dashboard.html` (Participant dashboard template - displays event name)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/event_form.html` (Event form - scenario template selection dropdown)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#663` (CTF-707: Event Metadata)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/range/provision.py` (Range provisioning uses event.scenario_id (provision_participant_range))
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (Participant views - event detail, dashboard display name/description)
