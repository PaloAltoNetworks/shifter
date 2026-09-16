---
id: CTF-120
title: "Challenge Ratings"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T20:38:56.896572Z
updated_at: 2026-03-29T04:21:23.169446Z
---

# CTF-120: Challenge Ratings

## Statement

The system could support participant ratings of challenges. Participants who have solved a challenge could rate it on a numeric scale. The system shall display the average rating and rating count per challenge. Rating visibility shall be configurable per event (public, organizer-only, or disabled).

## Rationale

Ratings help organizers identify well-received vs frustrating challenges and improve challenge design over time, especially when challenge libraries are reused across events. Participant feedback on challenge quality is valuable for iterating on content. (CTFd supports a similar challenge rating feature.)

## Traceability

- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_challenges.py` (TestChallengeRatings: rate after solve, before solve fails, update, validation, average, disabled)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallengeRating model and rating_visibility on CTFEvent)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (rate_challenge() and get_challenge_rating() service functions)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/enums.py` (RatingVisibility enum (PUBLIC, ORGANIZER, DISABLED))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/urls.py` (api_rate_challenge URL route)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/migrations/0016_add_challenge_ratings.py` (Migration adding CTFChallengeRating table and rating_visibility field)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html` (Rating display and rating form UI in challenge detail template)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/forms.py` (rating_visibility field in event admin form)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/event.py` (Event service with rating_visibility handling)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/event_form.html` (Rating visibility config in event admin form template)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_events.py` (Event tests covering rating_visibility field)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#554` (CTF-120: Challenge Ratings)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/play.py` (api_rate_challenge endpoint and rating context in challenge detail views)
