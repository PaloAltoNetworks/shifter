# Chunk Report: Domain Model, Scoring, Challenges, Participants

Status: `Partial`

## What Still Looks Good

- The event lifecycle model is clearer than many other parts of the subsystem.
- Challenge difficulty, first blood, attachments, and programmable/http flag hooks all have credible source-level implementations.
- The service split across `challenge`, `submission`, `scoring`, and `participant` is directionally correct.

## Findings

### 1. Hint usage is not persisted, so hint penalties do not reliably apply

Evidence:

- `shifter/shifter_platform/ctf/services/submission.py:143-177`
- `shifter/shifter_platform/ctf/services/submission.py:206-278`

Why it matters:

- `submit_flag()` decides whether to apply a penalty from `_check_hint_used(...)`.
- `use_hint()` does not persist anything; it only logs and returns the hint text.
- `_check_hint_used()` looks only for previous `CTFSubmission` rows with `hint_used=True`.

Result:

- If a participant reveals a hint and then submits the correct flag on the first attempt, the solve can still receive full points.

Requirement impact:

- `CTF-203`, `CTF-002`, and `CTF-206`

### 2. The penalty floor is wrong for 100 percent hint penalties

Evidence:

- `shifter/shifter_platform/ctf/models.py:539-550`

Why it matters:

- The requirement says net score for a hint-penalized solve must never go below zero.
- The implementation uses `max(1, self.points - reduction)`.

Result:

- A 100 percent penalty still awards `1` point instead of `0`.

Requirement impact:

- `CTF-203`

### 3. Flags currently have two sources of truth

Evidence:

- `shifter/shifter_platform/ctf/forms.py:295-338`
- `shifter/shifter_platform/ctf/services/challenge.py:154-173`
- `shifter/shifter_platform/ctf/services/challenge.py:402-437`

Why it matters:

- `CTFFlag` is the richer current model.
- `CTFChallenge.flag_hash` still exists and is actively populated for backward compatibility.
- Validation first checks `challenge.flags`; if none exist, it falls back to `challenge.flag_hash`.

Assessment:

- The compatibility story is understandable, but the abstraction is not crisp.
- This makes challenge/flag behavior harder to reason about and increases migration risk.

### 4. Categories are globally fixed, not organizer-defined per event

Evidence:

- `shifter/shifter_platform/ctf/enums.py:88-110`
- `shifter/shifter_platform/ctf/models.py:433-437`

Why it matters:

- `CTF-102` requires categories to be definable per event by organizers.
- The implementation hardcodes categories as a global enum.

Assessment:

- Grouping and filtering exist, but the actual requirement is only partially met.

### 5. The participant lifecycle is intentionally collapsed from invited to registered

Evidence:

- `shifter/shifter_platform/ctf/services/participant.py:89-100`
- `shifter/shifter_platform/ctf/services/participant.py:430-452`

Why it matters:

- The code creates participants in `INVITED`, then immediately auto-registers them and links a Django user.
- That removes the distinction between invitation and completed registration for organizer-added users.

Assessment:

- This may be a deliberate product simplification, but it does not match the richer lifecycle described by the requirements and surrounding copy.

## Requirement Readout From This Chunk

- Strongly implemented: `CTF-103`, `CTF-104`, `CTF-108`, `CTF-118`, `CTF-201`, `CTF-205`
- Clearly partial: `CTF-002`, `CTF-005`, `CTF-006`, `CTF-101`, `CTF-102`, `CTF-116`, `CTF-1305`, `CTF-206`
- Clearly broken: `CTF-203`

## Recommendation

Highest-value domain fixes:

1. Add a real hint-usage record and make scoring consume it deterministically.
2. Change the hint penalty floor from `max(1, ...)` to `max(0, ...)`.
3. Decide whether `CTFChallenge.flag_hash` is legacy read-only or still a first-class source of truth; right now it is both.
4. Replace fixed challenge categories with event-scoped category records if `CTF-102` is meant literally.
5. Either embrace auto-registration as the product model and update the requirements/UX language, or restore a true invited-to-registered transition.
