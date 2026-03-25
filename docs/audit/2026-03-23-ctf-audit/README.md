# CTF Audit - 2026-03-23

This audit reviews the current `ctf` implementation against:

- implementation quality
- conceptual and abstraction clarity
- architectural consistency
- use of shared schema, data model, logging, and exception patterns
- whether `ACTIVE` Ground Control requirements are implemented

Scope notes:

- `ACTIVE` requirements only. `DRAFT` requirements were intentionally excluded.
- The audit is based on the current worktree as reviewed on 2026-03-23.
- Existing user changes in the CTF area were left untouched.

## Overall Judgment

The repo still has a clear quality baseline in the CMS-to-engine path: `cms.services.create_range` and the shared schemas remain the strongest example of clean orchestration, boundary clarity, and shared-contract usage. The CTF subsystem has moved away from that standard.

The largest issues are not cosmetic. There are several concrete correctness and requirement gaps:

1. Hint penalties do not persist and therefore do not reliably affect scoring.
2. Scheduled reminder execution is still stubbed, while scheduled notifications are modeled as reminder tasks.
3. Participant range access mixes CMS and engine identifiers and appears to use the wrong ID space.
4. The participant scoreboard surface is wired to the wrong context/API keys and is effectively broken.
5. Event-scoped participant context is under-modeled: most participant flows use `get_participant_by_user(...).first()` instead of the stored `active_ctf_event`.
6. The `ctf` layer is not covered by the repo's layer-import guardrails, so the newer subsystem is less protected than the older CMS/engine path.

## Artifacts

- `00-rubric.md`: audit rubric and scoring dimensions
- `01-audit-map.md`: chunking strategy used for this audit
- `02-architecture-shared-contracts.md`: shared patterns, boundaries, and architectural consistency
- `03-domain-model-scoring-participants.md`: challenge, scoring, flag, team, and participant domain review
- `04-range-automation-notifications.md`: range integration, scheduling, and notifications
- `05-views-admin-reporting.md`: participant/admin surfaces, reporting, and analytics
- `06-active-requirements-matrix.md`: `ACTIVE` Ground Control requirement coverage matrix

## Ground Control Snapshot

As of 2026-03-23:

- `shifter` has 29 `ACTIVE` requirements, all in the CTF area.
- 13 of those 29 `ACTIVE` requirements currently have no `TESTS` trace link in Ground Control:
  - `CTF-010`
  - `CTF-013`
  - `CTF-1001`
  - `CTF-1002`
  - `CTF-1006`
  - `CTF-103`
  - `CTF-104`
  - `CTF-111`
  - `CTF-1305`
  - `CTF-401`
  - `CTF-406`
  - `CTF-407`
  - `CTF-906`

## Verification Limits

I ran `./.venv/bin/pytest tests/ctf -q -n 0` from `shifter/shifter_platform`.

- `255` tests passed
- `164` errors occurred during setup because PostgreSQL was unavailable in this environment

That means the audit is source-backed, but runtime confidence for DB-backed paths is lower than I would want for a final signoff.
