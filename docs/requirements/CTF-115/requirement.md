---
id: CTF-115
title: "Per-Challenge Connection Info"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T07:23:03.277450Z
updated_at: 2026-03-26T20:11:29.994135Z
---

# CTF-115: Per-Challenge Connection Info

## Statement

The system should support associating specific connection information (for example host, port, service endpoint) with individual challenges. When a challenge references a specific service on a participant's range VM, the system shall display the participant-specific connection details alongside the challenge description.

## Rationale

Range-integrated challenges often target specific services on specific VMs. Participants need to know which host:port to attack for each challenge. Without per-challenge connection info, participants must manually figure out which VM and port correspond to each challenge, adding unnecessary friction.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge model - NO connection_info field found)
- IMPLEMENTS → CODE_FILE `ctf/bridges.py` (cms_get_target_instances() bridge function)
- IMPLEMENTS → CODE_FILE `ctf/views.py` (challenge_detail() connection info resolution)
- IMPLEMENTS → CODE_FILE `ctf/services/challenge.py` (_CHALLENGE_MUTABLE_FIELDS includes connection fields)
- IMPLEMENTS → CODE_FILE `templates/ctf/participant/challenge_detail.html` (Connection info display in challenge detail template)
- TESTS → TEST `tests/ctf/test_services/test_connection_info.py` (Connection info resolution tests (matching, no-target, unmatched, port handling))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#548` (CTF-115: Per-Challenge Connection Info)
