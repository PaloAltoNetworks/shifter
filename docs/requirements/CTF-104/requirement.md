---
id: CTF-104
title: "Static Flag Validation"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-03-18T05:28:21.514764Z
updated_at: 2026-10-05T17:17:34.223314Z
---

# CTF-104: Static Flag Validation

## Statement

The system shall validate participant flag submissions by comparing the submitted string against a stored expected value. A static flag is stored and matched as its inner value: surrounding whitespace and one optional outer `FLAG{...}` (case-insensitive prefix) or `{...}` wrapper are removed from both the stored and the submitted value, and the results are compared exactly, honoring the flag's case-sensitivity setting, so `FLAG{value}`, `{value}`, and `value` are all accepted. This supersedes the earlier literal "exact string matching" wording, which required participants to reproduce the wrapper exactly. The system shall record each submission attempt with timestamp, submitted value, and result (correct/incorrect). A correct submission shall be recorded as a solve and shall not be reversible.

## Rationale

Static flag validation is the most fundamental CTF mechanic, the participant finds a hidden string and submits it to prove they solved the challenge. Every scoring, ranking, and statistics feature depends on reliable flag validation. Recording attempts enables cheat detection and analytics. (CTFd uses this as its primary validation method.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (Flag submission service (submit_flag, duplicate prevention, submission recording))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (Flag verification service (verify_flag, static-flag normalization))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFSubmission model (submitted_flag, submitted_at, is_correct, participant/challenge FKs))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_submission.py` (Exact static flag submission tests through add_flag and submit_flag service path)
- IMPLEMENTS → GITHUB_ISSUE `539` (Issue #539 - automated coverage and Ground Control TESTS trace links for active CTF requirements)
