# Chunk Report: Architecture And Shared Contracts

Status: `Partial`

## What Still Looks Strong

- The repo still has a strong architectural exemplar in the CMS-to-engine path. Shared schemas, typed orchestration, and centralized logging remain a solid baseline.
- The CTF app does have a real exception hierarchy in `ctf/exceptions.py`, which is a good foundation.
- The bridge module is the right idea: CTF does need a single place for cross-domain calls.

## Findings

### 1. The `ctf` layer is outside the repo's import-boundary enforcement

Evidence:

- `scripts/check_layer_imports/layer_imports.yaml:9-27`

Why it matters:

- `engine`, `cms`, `management`, and `mission_control` have explicit allowed-import rules.
- `ctf` does not appear in that config at all.
- That means the newer subsystem is operating without the same architecture guardrails that protect the older high-quality paths.

Assessment:

- This is a structural consistency gap, not just a tooling nicety.

### 2. The CTF exception hierarchy exists, but services do not use it consistently

Evidence:

- `shifter/shifter_platform/ctf/exceptions.py`
- `shifter/shifter_platform/ctf/services/event.py:25-28`

Why it matters:

- `ctf/services/event.py` defines `EventNotModifiableError(Exception)` even though the subsystem already has `CTFStateError`.
- That splits the error model and weakens predictable error handling.

Assessment:

- Exception design is partially coherent, but not consistently enforced.

### 3. The bridge contract does not match the engine model it claims to abstract

Evidence:

- `shifter/shifter_platform/ctf/bridges.py:155-178`
- `shifter/shifter_platform/engine/models.py:297-300`

Why it matters:

- `ctf/bridges.py` treats `engine_range.provisioned_instances` as a dictionary with `.get()`, `.items()`, and `.values()`.
- The engine model documents that field as a JSON array.
- That is exactly the kind of cross-boundary drift the bridge was supposed to prevent.

Assessment:

- This is a real contract-integrity bug and a sign that the abstraction boundary is not being maintained with the same rigor as the CMS/engine path.

### 4. Participant context is not event-scoped even though the profile stores an active event

Evidence:

- `shifter/shifter_platform/ctf/services/participant.py:239-253`
- `shifter/shifter_platform/ctf/services/participant.py:461-475`

Why it matters:

- The user profile stores `active_ctf_event`, which suggests a clear event-selection model.
- Most participant flows call `get_participant_by_user(user)` with no `event_id`, and that helper simply returns `.first()`.
- In a multi-event future, that creates ambiguity for range access, scoreboard, and challenge context.

Assessment:

- The conceptual model says "active event", but the runtime selection model is "first row found". That is architectural debt with user-facing consequences.

## Recommendation

Highest-value architecture fixes:

1. Add `ctf` to `scripts/check_layer_imports/layer_imports.yaml`.
2. Remove ad hoc local exception types and standardize on `CTFError` subclasses.
3. Define one canonical range reference contract for CTF: when a field holds a CMS `RangeInstance` PK, never treat it as an engine `Range` PK.
4. Make participant lookups event-aware by default, using `active_ctf_event` when no explicit event is supplied.
