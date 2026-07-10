# Native CTF — Smoke & Validation Protocol

Validates the **native Shifter CTF** (the `ctf/` app at `/ctf/`): events, challenges,
flags, prerequisites, scoring, teams, scoreboard, and per-participant range
provisioning. The standalone Polaris CTFd is out of scope.

Run this against a freshly deployed tenant before trusting it for a real event
(for example, before a Polaris scenario run). The protocol has two parts:

- **Part 1–2 — Smoke:** the organizer and participant happy paths work end to end.
- **Part 3 — Regression guards:** the concurrency, integrity, and state-machine
  failure modes found in the native CTF (see [Known open issues](#known-open-issues)).
  These are scripted negative tests; several currently **fail** until the linked
  issues are fixed — that is the point of having them.

Each check is marked **[CLI/DB]** (an operator runs it with cloud credentials) or
**[Browser]** (an operator drives the UI; interactive login needs Cognito MFA and
cannot be automated).

---

## Setup

```bash
export DOMAIN="shifter.keplerops.com"      # the tenant's portal domain
export AWS_PROFILE="proof"                  # cloud profile for this tenant
export AWS_REGION="us-east-2"
```

### Running management commands

Do **not** use a bare `docker exec portal python manage.py …`. The container's
entrypoint fetches `DJANGO_SECRET_KEY` and the DB/cache/S3 credentials from Secrets
Manager into the main process; a fresh `docker exec` does not inherit them and the
command fails with `DJANGO_SECRET_KEY environment variable is required`.

Use the secrets-aware path instead — either the `shifter-ops` MCP
`run_manage_command` tool, or run inside the container with the entrypoint
environment sourced. Throughout this doc, `manage <cmd>` is shorthand for "run
`<cmd>` via the secrets-aware path."

### Accounts you will need

| Role | How |
| --- | --- |
| **Organizer** | A user in the CTF Organizer group. Seed via `manage shell` or an existing admin. |
| **Participant A / B** | Two users in the CTF Participant group, registered to the test event. B is only needed for team and concurrency checks. |

---

## Part 1 — Organizer journey

> Goal: an organizer can build a complete, releasable event.

### 1.1 Reachability **[CLI/DB]**

```bash
curl -s -o /dev/null -w "/ctf/ : %{http_code}\n" "https://${DOMAIN}/ctf/"        # expect 302 -> login
curl -s "https://${DOMAIN}/health/" | grep -q '"DatabaseBackend": "working"' && echo "db OK"
```

### 1.2 Create an event **[Browser]**

1. Log in as the organizer; open `/ctf/admin/events/`.
2. Create an event with a name, an `event_start` in the near future, an `event_end`
   a few hours out, `max_participants`, `team_size_limit` (if teams), and a
   `scoreboard_freeze_at`.

**[CLI/DB] verify** the event row and that registration scheduled its lifecycle tasks:

```bash
manage shell -c "from ctf.models import CTFEvent, CTFScheduledTask; e=CTFEvent.objects.latest('created_at'); \
print('event', e.id, e.status); \
print('tasks', list(CTFScheduledTask.objects.filter(event=e).values_list('task_type','scheduled_for')))"
# expect EVENT_START / EVENT_END (and CLEANUP_RANGES) PENDING with the times you set
```

### 1.3 Add challenges, flags, prerequisites **[Browser]**

1. Create at least three challenges: one **static-flag**, one **multi-flag**, one
   with `max_attempts` set (for the attempt-limit checks).
2. Add a flag to each. For the multi-flag challenge, add two valid flags.
3. Set a **prerequisite**: challenge B requires challenge A.
4. Set a non-zero **hint** with a penalty on one challenge.
5. Release the challenges (or schedule release).

**[CLI/DB] verify** flags are stored hashed and the prerequisite exists:

```bash
manage shell -c "from ctf.models import CTFChallenge, CTFChallengePrerequisite as P; \
[print(c.title, c.flags.count(), 'released' if c.is_released else 'unreleased') for c in CTFChallenge.objects.all()]; \
print('prereqs', list(P.objects.values_list('challenge__title','required_challenge__title')))"
```

### 1.4 Invite participants / open registration **[Browser]**

1. Invite Participant A (and B) by email, or open self-registration.
2. Activate the event when `event_start` arrives (or trigger it).

**[CLI/DB] verify** participant rows and active status:

```bash
manage shell -c "from ctf.models import CTFEvent, CTFParticipant; e=CTFEvent.objects.latest('created_at'); \
print('status', e.status, 'participants', CTFParticipant.objects.filter(event=e).count())"
```

---

## Part 2 — Participant journey

> Goal: a participant can register, solve, score, and get a working range.

### 2.1 Register & view challenges **[Browser]**

1. Log in as Participant A; open `/ctf/`.
2. Register to the event; open the challenge list.
3. Confirm the prerequisite challenge B is **locked** until A is solved.

### 2.2 Submit flags & scoring **[Browser + CLI/DB]**

1. Submit a **wrong** flag for challenge A → rejected, attempt recorded.
2. Submit the **correct** flag → solved; points appear; B unlocks.
3. Use the hint on another challenge, then solve it → points reflect the hint penalty.

**[CLI/DB] verify** the authoritative rows and the materialized score agree:

```bash
manage shell -c "from ctf.models import CTFParticipant, CTFSubmission; p=CTFParticipant.objects.get(user__email='A@example.com', event__status='active'); \
print('cached_score', p.cached_score, 'cached_solves', p.cached_solve_count); \
print('correct_rows', CTFSubmission.objects.filter(participant=p, is_correct=True).count())"
# cached_solve_count MUST equal the number of distinct solved challenges
```

### 2.3 Scoreboard **[Browser + CLI/DB]**

1. Open `/ctf/scoreboard/` — A appears with the right score.
2. After `scoreboard_freeze_at`, new solves must **not** change the visible board.

### 2.4 Participant range lifecycle **[Browser + CLI/DB]**

1. From the challenge/range page, **provision** a range. Status goes
   `provisioning → running`.
2. **Stop**, **Start**, **Restart**, then **Destroy** the range.

**[CLI/DB] verify** each transition reaches the real range (this is the seam that
breaks in [#1139](#known-open-issues)):

```bash
manage shell -c "from ctf.models import CTFParticipant; p=CTFParticipant.objects.get(user__email='A@example.com', event__status='active'); \
print('range_instance_id', p.range_instance_id, 'range_status', p.range_status)"
# cross-check the range actually exists / changed state in CMS/engine:
aws ec2 describe-instances --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --filters "Name=tag:RangeRequestId,Values=*" "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[].Instances[].{Id:InstanceId,State:State.Name}' --output text
```

---

## Part 3 — Regression guards

Scripted negative tests for the failure modes the adversarial audit confirmed.
Each names the issue it guards and the pass criterion. Run them with two
participants and a scriptable concurrent client (`asyncio`, or `xargs -P`/`hey`
against the submit/join endpoints with valid session cookies).

### G-A. TOCTOU on count/uniqueness invariants

The native CTF performs several "check then write" operations with no row lock and
no DB backstop, so concurrent requests bypass the invariant.

| Check | Trigger | Pass criterion | Issue |
| --- | --- | --- | --- |
| Double-score | N concurrent `POST /ctf/api/challenge/<id>/submit` with the **correct** flag | exactly 1 `is_correct` row; `cached_score` == single challenge points | [#1135](https://github.com/Brad-Edwards/shifter/issues/1135) |
| Attempt brute-force | N concurrent submits with distinct wrong guesses on a `max_attempts`-capped challenge | total attempt rows ≤ `max_attempts` | [#1137](https://github.com/Brad-Edwards/shifter/issues/1137) |
| Team overflow | `team_size_limit+3` concurrent `POST /ctf/team/join/` with one invite code | `team.members.count() <= team_size_limit` | [#1140](https://github.com/Brad-Edwards/shifter/issues/1140) |
| Prereq cycle | concurrent `add_prerequisite(A→B)` and `(B→A)` | no A↔B cycle; duplicate insert raises `IntegrityError` | [#1144](https://github.com/Brad-Edwards/shifter/issues/1144) |
| Participant cap | concurrent invites for distinct emails at `max_participants-1` | `event.participants.count() <= max_participants` | [#1145](https://github.com/Brad-Edwards/shifter/issues/1145) |
| File cap | concurrent uploads at `MAX_FILES_PER_CHALLENGE-1` | file count ≤ cap; `order` values unique | [#1147](https://github.com/Brad-Edwards/shifter/issues/1147) |

```bash
# Example: double-score guard. Capture A's session cookie, then:
seq 20 | xargs -P 20 -I{} curl -s -o /dev/null -b "$COOKIE" \
  -X POST "https://${DOMAIN}/ctf/api/challenge/${CHALLENGE_ID}/submit" \
  --data "flag=${CORRECT_FLAG}"
manage shell -c "from ctf.models import CTFSubmission; \
print('correct_rows', CTFSubmission.objects.filter(participant_id='${PID}', challenge_id='${CHALLENGE_ID}', is_correct=True).count())"
# PASS iff correct_rows == 1
```

Backstop check — the partial unique constraints exist after migrations:

```bash
manage makemigrations --check --dry-run        # expect "No changes"
manage shell -c "from django.db import connection; c=connection.cursor(); \
c.execute(\"select conname from pg_constraint where conname like 'ctf_%uniq%'\"); print(c.fetchall())"
```

### G-B. Team scoring distinctness

Two participants on one team both solve challenge X.

- **Pass:** `team.cached_score == points(X)` (not `2×`); the freeze recompute
  (`_recompute_team_scoreboard`) yields the same value. Issue [#1138](https://github.com/Brad-Edwards/shifter/issues/1138).

### G-C. Range lifecycle pk vs range_id

Provision a participant range, then in the DB force `RangeInstance.range_id` to
differ from its `pk` (the production case — `range_id` is set asynchronously):

```bash
manage shell -c "from cms.models import RangeInstance; r=RangeInstance.objects.latest('created_at'); \
r.range_id = (r.range_id or 0) + 1000; r.save(update_fields=['range_id']); print('pk', r.pk, 'range_id', r.range_id)"
```

Drive **stop / start / destroy** from the participant UI.

- **Pass:** each operates on the correct range — no `CMSError "Range not found"`,
  no orphaned running range after destroy. Issue [#1139](https://github.com/Brad-Edwards/shifter/issues/1139).
  (Unit tests mock the bridges and miss this; it must be exercised live.)

### G-D. Cross-event authz isolation

Register A in two events (one active, one not). Disqualify A from one.

- **Pass:** A stays in the CTF Participant group, `get_user_role(A).active_ctf_event`
  is non-None and points at an eligible event, `is_ctf_participant(A)` is True, and
  a participant page for the other event loads `200`. Issue [#1142](https://github.com/Brad-Edwards/shifter/issues/1142).

### G-E. Scoreboard freeze under pause

`scoreboard_freeze_at` in the past, event ACTIVE; record a solve after the freeze.
Pause the event.

- **Pass:** `GET /ctf/scoreboard/` and `/api/.../scoreboard` do **not** show the
  post-freeze solve while PAUSED. Issue [#1143](https://github.com/Brad-Edwards/shifter/issues/1143).

### G-F. Event-task reschedule on window edit

Open registration (schedules `EVENT_END` at T). Activate. Edit `event_end` to T+1h.

- **Pass:** the pending `EVENT_END` `CTFScheduledTask.scheduled_for` now equals T+1h
  and no stale PENDING task remains at T. Issue [#1141](https://github.com/Brad-Edwards/shifter/issues/1141).

```bash
manage shell -c "from ctf.models import CTFScheduledTask; \
print(list(CTFScheduledTask.objects.filter(task_type='EVENT_END', status='PENDING').values_list('scheduled_for', flat=True)))"
```

### G-G. API error contract

| Check | Trigger | Pass criterion | Issue |
| --- | --- | --- | --- |
| Import bad input | `POST /ctf/api/events/<id>/participants/import/` with `{"participants": ["x"]}` | HTTP `400` per-item envelope, never `500` | [#1149](https://github.com/Brad-Edwards/shifter/issues/1149) |
| Range status participant | user in two events; poll `api_range_status` | returns the **active** event's range (same as the range page); excludes ineligible rows | [#1148](https://github.com/Brad-Edwards/shifter/issues/1148) |
| Multi-flag emptied | remove all flags of a multi-flag challenge, submit the old flag | fails **loudly**, not a silent always-False | [#1146](https://github.com/Brad-Edwards/shifter/issues/1146) |

---

## Part 4 — Teardown

```bash
# Destroy any participant ranges, then confirm none are orphaned (cost guard).
manage shell -c "from ctf.services.range import cleanup_event_ranges; from ctf.models import CTFEvent; \
cleanup_event_ranges(CTFEvent.objects.latest('created_at').id)"
aws ec2 describe-instances --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --filters "Name=tag:RangeRequestId,Values=*" "Name=instance-state-name,Values=running,stopped" \
  --query 'length(Reservations[].Instances[])'
# expect 0 once destroys complete
```

Delete the test event when finished.

---

## Known open issues

As of this protocol's writing, the native CTF has the following confirmed bugs.
Part 3 guards will **fail** against them until they are fixed; treat a failing
guard as expected for a listed issue, and as a regression for anything else.

| Severity | Issue | Summary |
| --- | --- | --- |
| High | [#1135](https://github.com/Brad-Edwards/shifter/issues/1135) | Concurrent correct submissions double-score |
| High | [#1137](https://github.com/Brad-Edwards/shifter/issues/1137) | Attempt-limit / cooldown bypass (flag brute-force) |
| High | [#1138](https://github.com/Brad-Edwards/shifter/issues/1138) | Team score double-counts (non-distinct Sum) |
| High | [#1139](https://github.com/Brad-Edwards/shifter/issues/1139) | Lifecycle bridges use `pk` where engine wants `range_id` |
| High | [#1140](https://github.com/Brad-Edwards/shifter/issues/1140) | Team-join capacity TOCTOU |
| High | [#1141](https://github.com/Brad-Edwards/shifter/issues/1141) | Event window edit doesn't reschedule EVENT_END (ranges destroyed early) |
| Medium | [#1142](https://github.com/Brad-Edwards/shifter/issues/1142) | Disqualify strips platform-wide group (locks user out of other events) |
| Medium | [#1143](https://github.com/Brad-Edwards/shifter/issues/1143) | Pause lifts scoreboard freeze |
| Medium | [#1144](https://github.com/Brad-Edwards/shifter/issues/1144) | Prerequisite-cycle TOCTOU |
| Medium | [#1145](https://github.com/Brad-Edwards/shifter/issues/1145) | Participant-cap TOCTOU |
| Low | [#1146](https://github.com/Brad-Edwards/shifter/issues/1146) | `verify_flag` sentinel fallback (silently unsolvable) |
| Low | [#1147](https://github.com/Brad-Edwards/shifter/issues/1147) | File-cap TOCTOU |
| Low | [#1148](https://github.com/Brad-Edwards/shifter/issues/1148) | `api_range_status` resolves wrong participant |
| Low | [#1149](https://github.com/Brad-Edwards/shifter/issues/1149) | Participant import 500 on non-object input |
