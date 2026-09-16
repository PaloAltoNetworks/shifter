---
id: CTF-001
title: "Challenge Management"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:20.896712Z
updated_at: 2026-03-30T04:36:13.746955Z
---

# CTF-001: Challenge Management

## Statement

The CTF layer shall provide challenge management capabilities including creating, organizing, configuring, and publishing CTF challenges with support for multiple flag types, categorization, difficulty levels, file attachments (using the platform's shared storage abstraction), prerequisites, visibility controls, and scheduling. Challenges are the content model that CTF adds to the Shifter platform.

## Rationale

Challenges are the core content unit of CTF events and the primary thing CTF adds to the Shifter platform. Organizers need a rich challenge management system to build engaging competitions with varied, well-structured challenge sets that make CTF events effective training exercises. (CTFd provides similar capabilities as a standalone platform; Shifter integrates these as a feature within its existing platform architecture.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF Models - Challenge, Event, Team, Participant, Submission models)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (CTF Challenge Service - CRUD, flag hashing, flag verification)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/forms.py` (CTF Forms - CTFChallengeForm with flag hashing)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py` (CTF Enums - ChallengeCategory, ChallengeDifficulty, EventStatus)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_challenges.py` (CTF Challenge Tests)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py` (CTF Model Tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#511` (CTF-001: Challenge Management)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_challenges.py` (CTF Views - Challenge CRUD views, participant challenge views, API endpoints)
