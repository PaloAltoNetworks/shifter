---
id: CTF-1305
title: "Submission History"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T20:39:10.693422Z
updated_at: 2026-03-26T06:38:56.462239Z
---

# CTF-1305: Submission History

## Statement

The system should record and display all flag submission attempts. Organizers shall be able to view, search, and filter all submissions across an event (correct, incorrect, by participant, by challenge, by time). Participants shall be able to view their own submission history per challenge if the event configuration permits. The system shall display submission type (correct/incorrect), the provided value, timestamp, and the submitting participant.

## Rationale

Submission history is essential for organizers to detect cheating, debug flag issues, and understand participant behavior. Participant self-viewing helps them track their own progress and avoid resubmitting the same incorrect answers. Organizers need filtering by type (correct/incorrect), participant, challenge, and full-text search for effective event management. (CTFd provides a full submissions admin interface with similar capabilities.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/admin.py::CTFSubmissionAdmin` (CTFSubmissionAdmin - Organizer view/search/filter of all submissions)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py::CTFSubmission` (CTFSubmission model - Records all submission attempts with correctness, flag, timestamp, participant)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py::challenge_detail` (challenge_detail view - Participant views own submissions per challenge)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py::api_submissions` (api_submissions - Participant API to view own submission history)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py::admin_participant_detail` (admin_participant_detail - Organizer views participant submission history)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (Submission service - get_participant_submissions, get_challenge_submissions, get_correct_submissions)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_people.py::admin_participant_detail` (Organizer participant detail view - submission history context)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_participant_views.py` (Admin participant detail tests - organizer-visible submission history)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
