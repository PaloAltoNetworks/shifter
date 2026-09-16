---
id: CTF-119
title: "Challenge Topics"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T20:38:52.862447Z
updated_at: 2026-03-29T02:37:42.776213Z
---

# CTF-119: Challenge Topics

## Statement

The system should support assigning one or more topics to each challenge from a managed topic taxonomy. Topics shall represent knowledge areas or attack techniques (for example, SQL Injection, Privilege Escalation, Network Analysis). Topics shall be distinct from categories and tags, categories organize challenges within an event, tags are freeform labels, and topics are a controlled vocabulary of subject matter. Participants and organizers shall be able to filter challenges by topic.

## Rationale

Topics enable filtering challenges by attack technique across events, which is valuable for building structured training paths. An organizer creating a new event can search existing challenges by topic to find relevant content. Topics represent a controlled vocabulary of subject matter distinct from freeform tags and event-scoped categories. (CTFd supports Topics as a similar classification axis.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFTopic model and topics M2M on CTFChallenge)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (_resolve_topics() and topics in create_challenge/update_challenge)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_challenges.py` (TestChallengeTopics: create, update, cross-event reuse, uniqueness, clear tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#552` (CTF-119: Challenge Topics)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant_challenges.py` (Topic filtering in participant_challenges() and topics in API responses)
