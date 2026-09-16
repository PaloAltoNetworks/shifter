---
id: CTF-102
title: "Challenge Categories"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:21.446320Z
updated_at: 2026-03-26T06:36:07.487894Z
---

# CTF-102: Challenge Categories

## Statement

The system shall support organizing challenges into named categories (for example web exploitation, cryptography, forensics, reverse engineering, pwn, OSINT, misc). Categories shall be definable per event by organizers. The challenge listing UI shall group and filter challenges by category.

## Rationale

Categories are the primary organizational axis for CTF challenges. Participants use categories to find challenges matching their skill set, and without them, a flat list of 20+ challenges becomes unnavigable, participants waste time finding relevant challenges instead of solving them. (CTFd uses categories as its core organizational structure.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py` (ChallengeCategory enum - defines 9 named categories (web, forensics, crypto, reverse, pwn, misc, osint, hardware, network))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge model - category CharField with ChallengeCategory.choices(), indexed, ordered by category)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenges.html` (Participant challenges UI - category filter buttons and challenges grouped by category sections)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/challenge_list.html` (Admin challenge list UI - challenges grouped by category with headers and counts)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/challenge_form.html` (Challenge create/edit form - category select dropdown from ChallengeCategory.choices() for organizer selection)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_challenges.py` (Challenge tests - tests challenge creation/listing with category field using ChallengeCategory enum values)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant_challenges.py` (Challenge views - category_filter via query param, challenges_by_category grouping for participant and admin views)
