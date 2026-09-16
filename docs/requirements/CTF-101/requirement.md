---
id: CTF-101
title: "Challenge CRUD"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:21.411948Z
updated_at: 2026-03-26T06:34:39.140033Z
---

# CTF-101: Challenge CRUD

## Statement

The system shall support creating, reading, updating, and deleting CTF challenges. Each challenge shall have: a title, description (supporting Markdown), point value, one or more flags, category assignment, and a visibility state. Challenges shall be scoped to a single CTF event.

## Rationale

CRUD operations on challenges are the foundational data management capability that CTF adds to the Shifter platform. Every other challenge feature (categories, flags, hints, scoring) depends on challenges existing as first-class entities. These fields represent the minimum data model needed for organizers to create effective challenge sets within Shifter.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF models - CTFChallenge model with CRUD fields, category, points, visibility, event scoping)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (Challenge service - CRUD operations, flag hashing, and flag verification logic)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/forms.py` (CTF forms - Django forms for challenge create/update input validation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py` (CTF enums - ChallengeCategory, ChallengeDifficulty, and other enum definitions)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_challenges.py` (Challenge tests - Tests for challenge CRUD operations and validation)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py` (CTF model tests - Tests for CTFChallenge model validation and properties)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_challenges.py` (CTF views - HTTP endpoints for challenge CRUD and event management)
