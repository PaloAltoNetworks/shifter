---
id: CTF-118
title: "Programmable Flag Validation"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T20:38:48.685011Z
updated_at: 2026-03-26T06:36:52.548888Z
---

# CTF-118: Programmable Flag Validation

## Statement

The system could support programmable flag validation where custom code or an HTTP callback determines whether a submission is correct. Programmable flags shall support: code-based validators (custom logic executed server-side) and HTTP-based validators (submission forwarded to an external endpoint that returns pass/fail). Validator configuration shall be per-flag.

## Rationale

Programmable flags enable dynamic validation logic, for example, verifying a submission against the participant's specific range state, checking that an exploit actually worked on the target VM, or validating flags that change per participant. HTTP-based validators allow delegation to external services for validation, which is important for range-integrated challenges. (CTFd supports Programmable and HTTP flag types beyond static and regex.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/validators/_registry.py` (Programmable validator registry)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/validators/_http.py` (DNS-pinned HTTP validation transport and strict verdict parsing)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge/_flag_verify.py` (Programmable/HTTP verification dispatch and validator configuration)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge/_flag_crud.py` (Programmable/HTTP flag creation and updates)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/flag.py` (CTFFlag programmable/HTTP type and validator configuration)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_programmable_flags.py` (Programmable and HTTP flag validation tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#509` (CTF-118: Programmable Flag Validation)
