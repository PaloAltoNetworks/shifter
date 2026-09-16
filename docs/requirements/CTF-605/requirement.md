---
id: CTF-605
title: "User Banning"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:22.905246Z
updated_at: 2026-03-26T06:10:47.505287Z
---

# CTF-605: User Banning

## Statement

The system could support banning participants from a CTF event. A banned participant shall be unable to access event content, submit flags, or view challenges for that event. Banning shall not affect the user's platform account or ability to log in to other parts of the system. Banning shall preserve the participant's submission history for audit purposes. Organizers shall be able to unban participants.

## Rationale

Banning handles disruptive behavior, suspected cheating, or unauthorized access during live events. CTFd supports user banning. While rare in enterprise settings, the capability is needed for larger events or events involving external participants.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums_registration.py` (ParticipantStatus enum with BANNED and DISQUALIFIED states)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant.py` (disqualify_participant() service function)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (submit_flag() - missing banned participant check)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/__init__.py` (CTF services public API - exports disqualify_participant, no unban)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#654` (CTF-605: User Banning)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (CTF views - ctf_register and ctf_participant_required lack ban checks)
