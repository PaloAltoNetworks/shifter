---
id: CTF-602
title: "Participant Invitation"
status: DRAFT
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:22.794291Z
updated_at: 2026-03-26T07:07:11.579772Z
---

# CTF-602: Participant Invitation

## Statement

The system shall support organizer-initiated participant invitations via the platform's email service (PLAT-103). Invitations shall contain a unique link that pre-registers the recipient for the event. Invited participants shall be able to accept or decline. The system shall track invitation status (pending, accepted, declined, expired). Organizers shall be able to resend or revoke invitations.

## Rationale

Invitation-based registration is essential for private or enterprise CTF events where not everyone should be able to self-register. For Shifter, organizers need to invite specific consultants or customer contacts to controlled events rather than opening registration publicly. (CTFd supports invite-only events.)

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/services/participant.py` (Participant service - invite, bulk import, resend invite logic)
- IMPLEMENTS → CODE_FILE `ctf/services/notification.py` (Notification service - send_invitations, email rendering, magic link URL builder)
- IMPLEMENTS → CODE_FILE `ctf/models.py` (CTFParticipant model - invite_token, invite_token_expires, status, is_invite_valid)
- IMPLEMENTS → CODE_FILE `ctf/views.py` (Views - ctf_register (magic link auth), organizer invite/resend APIs, admin participant views)
- IMPLEMENTS → CODE_FILE `ctf/enums.py` (ParticipantStatus enum - tracks INVITED/REGISTERED/ACTIVE/COMPLETED/DISQUALIFIED (missing DECLINED/EXPIRED))
- IMPLEMENTS → CODE_FILE `templates/ctf/email/invitation.html` (Invitation email HTML template with magic link)
- IMPLEMENTS → CODE_FILE `templates/ctf/email/invitation.txt` (Invitation email plain text template with magic link)
- IMPLEMENTS → CODE_FILE `ctf/urls.py` (URL routing for registration, invite send, resend-invite endpoints)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#651` (CTF-602: Participant Invitation)
