# Operation NORTHSTORM — Event Retrospective / Lessons Learned

**Event:** Polaris CTF at BSides Ottawa, 15–16 April 2026
**Operators:** ~110 participants across per-range Kali workstations + shared CTFd
**Window:** Originally 5:45 PM – 10:00 PM EDT (extended to 11:00 PM EDT Apr 16)

This document captures lessons from running the live event plus lessons that generalize
to any CTF of this shape (per-participant ranges + shared scoreboard + AI-assisted flow).

---

## Content bugs that only surface during live play

### 1. Every flag value must be verified against the actual baked artifact, not just the design doc

**What happened.** The "Follow the Money" challenge (M1 / flag 6) had a flag value configured
in CTFd (`FLAG{c6f8d2b3e91a4507}`) that did not exist anywhere in the `boreas-annual-2025.pdf`
baked onto the A0 containers. The design doc said "the flag is printed near the Kursk line
item." The PDF had the Kursk line. It did not have the flag. Participants followed the hints
exactly and found nothing.

**Why.** The PDF generator script at bake time either never added the flag or added it in a
way that didn't survive rendering. Nobody verified the rendered artifact post-bake.

**Fix during event.** Regenerated the PDF locally with reportlab, embedded the flag as a
`PO ref: FLAG{…}` line under the Kursk row, pushed to all 110 polaris-vms via an SSM fan-out.

**Takeaway.**

- **Pre-event, run every challenge's hint path against a real deployed range.** Not "the
  design looks right." Not "the sync script returned success." Actually open the challenge,
  follow Hint 1, then Hint 2, confirm you land on the flag.
- **For static flags embedded in files:** after bake, grep the artifact for the flag value.
  `pdf2txt.py annual.pdf | grep FLAG{` would have caught this in five seconds.
- **Have a hotfix path ready.** The PDF was pushed via SSM fan-out. Having that pattern
  rehearsed (via `apply_splice_watcher.py`) is what made a 90-second fix possible instead of
  a 30-minute fire drill.

### 2. Warm-up challenges must match the actual participant environment

**What happened.** `Start Here — Kali Warm-Up` was designed around "find the helper script
`flag_submit.sh` that submits flags to CTFd." Problem: the script needed a `CTFD_TOKEN` env
var participants didn't have, and — more fundamentally — **Kali has no network route to
CTFd in this deployment**. The helper couldn't ever have worked. The warm-up was broken
on premise, not just configuration.

**Fix.** Redesigned the warm-up as "find the hidden orientation file `/home/kali/.polaris/welcome.txt`
and submit the flag printed inside." Flag text is plain and visible via `cat`. Baked into
the Dockerfile and pushed to running ranges via the apply-splice-watcher hotfix path.

**Takeaway.**

- **Design warm-ups around the actual participant flow, not the design-doc flow.** Participants
  work in two browser tabs: CTFd on personal laptop, Shifter terminal UI into their Kali box.
  Anything that assumes they can run a submission tool on Kali is broken by construction.
- **Warm-ups should be "did my env come up" checks, not real puzzles.** Goal: prove the
  participant can submit a flag and move on. Low bar, obvious path, no surprises.

### 3. Sync scripts that PATCH objects must include every polymorphic column

**What happened.** Mid-event, participants reported "hints are unclickable, page loads slow."
Investigation found CTFd was returning HTTP 500 on `/api/v1/challenges/<id>` with
`sqlalchemy.exc.InvalidRequestError: Row with identity key (Hints, (92,), None) can't be
loaded ... polymorphic discriminator column 'hints.type' is NULL`. 70 of 104 hints in the
DB had `type = NULL`.

**Why.** The `ensure_hints` function in `sync_polaris_ctfd_onboarding.py` builds the PATCH
payload without the `type` field. CTFd's schema validation treats that as "unset" and writes
NULL into the discriminator. Every hint the sync ever touched ended up with null type.

**Fix during event.** `UPDATE hints SET type='standard' WHERE type IS NULL;` — done in
one SQL.

**Takeaway.**

- **When building an API sync tool against a framework with polymorphic models (CTFd, anything
  SQLAlchemy-based), always include the discriminator field in PATCH payloads.** Going one
  layer deeper: write an integration test that synced-then-queried round-trips without
  losing fields.
- **This is a generalizable CTFd gotcha.** Fix `ensure_hints`, `ensure_static_flag`,
  `upsert_challenge`, and any similar function to always include `type`. They're probably
  all bugged the same way.

---

## Performance under load

### 4. Measure before resizing

**What happened.** User reported "CTFd is getting crushed, fix it." Instinctive response:
scale the EC2 up. But before touching anything: CPU was 1–3%, memory 1 GB of 16 GB, CPU
credits full, DB at 0.01% CPU. The host was idle.

Actual problem was two layered issues:

1. The hint-type NULL bug (§3) returning 500s on challenge API calls, which manifested as
   "hints unclickable" because the AJAX POST 500'd silently.
2. nginx proxy buffers at default (tiny), causing CTFd's 1–2 MB JS bundles to spill to disk
   via `buffered to a temporary file` on every single page load. This was the "slow page
   load" half of the complaint.

**Fix during event.**

- Backfilled NULL hint types (one SQL).
- `proxy_buffer_size 16k; proxy_buffers 16 64k; proxy_busy_buffers_size 128k` — JS bundles
  stay in memory.
- Added `location /themes/ { expires 1h; add_header Cache-Control "public, max-age=3600, immutable"; }`
  so returning participants fetch static assets from browser cache, not the wire.
- SIGHUP'd gunicorn via `docker kill --signal HUP ctfd-ctfd-1` to respawn workers stuck on
  the earlier 500-storm.

**Takeaway.**

- **Resizing is a last resort, not a first instinct.** Under 110 concurrent CTF users,
  `t3.xlarge` is massively over-provisioned. Network-bound issues look the same as CPU-bound
  to a user — both cause slow page loads. Check metrics before acting.
- **Pre-event nginx tuning for CTFd is worth doing once, for keeps.** `proxy_buffers` defaults
  are tuned for small API responses, not for serving Webpack bundles through a reverse proxy.
- **Static asset caching should be on by default.** CTFd's bundle filenames include hashes,
  so `Cache-Control: immutable` is safe — new bundles get new filenames.
- **Gunicorn SIGHUP is a no-downtime worker reset** for a containerized CTFd. No need for
  `docker restart`.

### 5. 500 errors poison worker pools

Even after fixing the NULL type rows, some participant sessions stayed slow until they
hard-refreshed. The mechanism is probably twofold: browsers had poisoned cache from error
pages (fixed by the cache headers + refresh), and gunicorn workers had stuck connections
from the earlier error storm (fixed by SIGHUP).

**Takeaway.** After fixing a correctness bug that caused error bursts, always:
(a) flush Redis (`redis-cli FLUSHALL`),
(b) SIGHUP gunicorn workers,
(c) tell participants to hard-refresh.

---

## Participant experience / flow model

### 6. The deployment model must drive every UX decision

The single most consequential fact about this event's deployment is: **Kali cannot reach
CTFd.** Participants work in two browser tabs on their personal laptop. CTFd is tab A
(scoreboard, submission). Shifter terminal UI is tab B (terminal into Kali with Claude
Code). Nothing on Kali can POST to CTFd.

I internalized this after the user corrected me twice in the same session. It is now a
memory. But it bit us in the form of:

- A warm-up that assumed Kali could call CTFd
- A `flag_submit.sh` helper that couldn't work by design
- Doc copy that said "use the helper script on your Kali box"
- Me briefly suspecting a participant was cheating because they submitted 16 flags in 1.6s
  (reality: agentic Claude produced the flags, operator batched the submission from tab A)

**Takeaway.** Write the deployment model down, early, in one sentence. Review every piece of
content and every tool against it before bake. Anything that requires Kali→CTFd traffic is
broken by construction; delete it.

### 7. Agentic AI changes what "normal" CTF pacing looks like

With Claude Code preconfigured on every Kali box, a single operator can parallelize OSINT,
document parsing, Modbus reads, and binary analysis across many challenges simultaneously.
Claude works in background while the operator does other things. Result: bursts of 10–20
correct submissions within 1–2 seconds when the operator flips back to the CTFd tab are
not unusual and not cheating.

"Zero incorrect submissions across 27 consecutive solves" — also not cheating. Claude is
computing values from solved artifacts, not guessing.

**Takeaway.**

- **Brief organizers on the new normal.** What looked like cheating flags in classical CTF
  telemetry is the intended experience here. Tell any volunteers monitoring the scoreboard.
- **Real cheating signatures to look for instead:**
  - Flags for challenges that are prereq-gated and not unlocked for that user.
  - Multiple accounts from the same IP submitting in pattern.
  - Flags submitted in manifest-JSON order rather than investigation order.

---

## CTFd / operational gotchas

### 8. Token auth requires `Content-Type: application/json`

CTFd's `@app.before_request tokens()` handler only honors the `Authorization` header when
`request.mimetype == "application/json"`. `Accept: application/json` alone is ignored. If
you're writing a tool or an ad-hoc curl against the CTFd API, you need both. Spent 20 minutes
debugging why my fresh-minted token was returning 302 to `/login`.

### 9. API tokens default to short TTL

I minted tokens with 2-hour expiry multiple times and had to re-mint mid-hotfix. At event
time, mint an 8–12 hour token so it lives past the event window. Store in `~/.cache/` with
`chmod 600`.

### 10. SSM SendCommand maxes at 50 instances per call

Hit this twice. Fan-outs across 110 ranges must batch:

```python
for i in range(0, len(ids), 50):
    batch = ids[i:i+50]
    ssm.send_command(InstanceIds=batch, ...)
```

Use Python/boto3 for this, not shell. Bash word-splitting of instance-ID lists interacts
badly with the AWS CLI's argument validation; I lost time on "Value '[i-… i-… …]' failed to
satisfy constraint" errors.

### 11. SSM "Pending" invocations can take 30+ seconds to dispatch

Batches with `MaxConcurrency=25` on a 50-instance SendCommand can leave 22 instances in
`Pending` long after the first 28 finish. This isn't a failure — SSM will eventually
dispatch them. But if you're in an event window, re-send the stuck IDs as a second batch
rather than waiting.

### 12. The `meetup+N` / `meetup+N` naming scheme

Predictable deterministic credentials (email `meetup+N@bsidesottawa.ca`, password matching
`meetup+N`) saved a lot of headache. Each participant could self-assign from the pool. No
secret credential distribution logistics. For a 110-person event where attribution doesn't
matter, this is the right tradeoff.

---

## Pre-event process

### 13. A 10-minute smoketest saves a 60-minute fire drill

The Follow the Money content bug would have been caught by anyone solving the challenge
once against a live range before the event started. Same for the warm-up (which would have
caught the Kali→CTFd unreachability). Budget time to smoketest at least:

- Warm-up end-to-end (login as a participant account, read the challenge, follow the hint
  path on Kali, submit the flag).
- One main-campaign challenge (e.g., Company Info → FLAG{…}).
- One parallel-objective challenge (e.g., Mission 6's Q4 Risk Review).
- One challenge that touches a pivot (Mission 3 or 4 gate flag).

Ten minutes. Catches almost every integration bug.

### 14. Pages, challenges, and the AMI are three different deploy paths

CTFd pages live in `scenario-dev/polaris/build/ctfd-pages/*.md` and sync via
`sync_polaris_ctfd_onboarding.py`. CTFd challenges live in `ctfd-challenges.json` and
`ctfd-onboarding.json`. Per-range content (anything under `/home/kali/…`, `/usr/share/nginx/html/…`)
lives in the polaris-vm AMI or is pushed at range-start time.

Editing one does not update the others. The Dockerfile at `scenario-dev/polaris/build/a14/Dockerfile`
is what affects the test-range docker-compose bake. The polaris-vm AMI is built separately via
`shifter/packer/scripts/kali/*.sh` and does **not** include the A14-kali content overlay.
Per-range content for the live event is applied via `scripts/polaris-aws-range/apply_*.py`
scripts that SSM into running polaris-vm hosts.

If you change content and expect it live, verify which path you need:

- **Pages:** pages-only sync against CTFd.
- **Challenges, hints, flags:** full sync or onboarding sync; PATCH includes all polymorphic
  columns (§3).
- **Per-range files:** extend or write a new `apply_*.py` that fans out via SSM.

### 15. Keep the original JSON as the source of truth

Editing challenges directly in CTFd's admin UI creates drift from `ctfd-challenges.json`.
Next time the sync script runs, the UI edits get overwritten. The fix applied directly to the
live DB during the event (§3) has to be backported into `ctfd-challenges.json` or it gets
clobbered on the next full sync.

**Takeaway.** Post-event, reconcile: pull live CTFd state, diff against JSON, update JSON so
the next sync is a no-op.

---

## Collaboration / communication patterns

### 16. Event-window urgency changes the default question cadence

Pre-event, ask before acting. Event-window, state the fix in one sentence, execute, confirm
afterwards. Asking "should I …?" three times in a row during active incidents eats time.
When the user said "it's getting crushed," the right move was: measure, state the hypothesis,
apply, report. Not: "do you want me to resize?"

### 17. Safety confirms in one sentence, not three

When the user asked whether my re-deploy would only affect the briefing deck (not CTFd
challenges), a one-sentence scope confirmation was the right answer. No need to enumerate
everything I'm not touching. "Yes — only the 4 files at `/var/www/polaris-briefing/`, zero
CTFd state touched."

### 18. Memory saves compounded the win

Four memories added during this event will make the next event materially less painful:

- Polaris participant flow (two tabs, Kali can't reach CTFd)
- Polaris uses agentic Claude — burst solves are normal
- Never touch Polaris CTFd challenge content without explicit scope
- Don't frame AI as a refuser in participant docs

If I had these memories at the **start** of prep, I'd have saved probably 40 minutes of
re-deriving and being corrected.

### 19. Shell escaping + SSM is a tax

Multiple SSM commands failed mid-session because of shell quoting interactions between the
AWS CLI, the SSM document, and the remote bash. Every time: the fix was wrapping the whole
script in base64, shipping that, decoding on the box, then executing. Pattern:

```bash
cat > /tmp/script.sh <<'SCRIPT'
# ... real work here ...
SCRIPT
B64=$(base64 -i /tmp/script.sh | tr -d '\n')
aws ssm send-command ... --parameters "commands=[\"echo $B64 | base64 -d > /tmp/s.sh && bash /tmp/s.sh\"]"
```

Save this as a snippet. Don't fight shell escaping on event day.

---

## Would-do-differently for event 2

1. **Two-hour pre-event smoketest window.** Run through at least one challenge per mission
   end-to-end against a real deployed range. Fix broken flags/hints before event starts.
2. **Rendered-artifact validation in the bake pipeline.** `pdftotext` every generated PDF
   and grep for the expected flag value; fail the bake if missing.
3. **Pre-tune the CTFd nginx config.** `proxy_buffers`, `Cache-Control` on `/themes/` — bake
   this into the terraform user_data template (`ctfd-userdata.sh.tftpl`) so every CTFd
   instance starts with it.
4. **Fix the polymorphic-type bug in the sync scripts** (§3) so no future sync poisons hints
   again.
5. **Mint an 8-hour admin token at event start.** Put it in a known location. Document which
   token is "the event token" so re-minting mid-event doesn't cost 10 minutes.
6. **Pre-build the SSM fan-out pattern as a general script.** `apply_splice_watcher.py` and
   `apply_kali_bedrock_shard.py` already follow the pattern. A third variant for ad-hoc
   content pushes (drop file X at path Y on every polaris-vm, idempotent, batched) would
   have saved 15 minutes on the PDF hotfix.
7. **Put the Discord support link on the Start Here page before the event, not mid-event.**
8. **Have the briefing deck served from the CTFd server from day 1, not as a post-event
   thought.** `polaris.keplerops.com/briefing/` is the right URL.
9. **Event window starts 15 min early.** 5:45 PM open, 6:00 PM brief — gives time for the
   first "I can't log in" round before any content pressure.

---

## Things that went right

1. **The briefing deck aesthetic worked.** Themed classification-stamp cold-open + mission
   cards + closing "GOOD HUNTING, OPERATOR" set the right tone. Worth preserving.
2. **Equal-peer mission framing.** Treating M1–M9 as peers (not M6–M9 as "practice lanes")
   was the right call. Participants spread across all nine instead of piling on the chain.
3. **The Mission Log / Surfaces / AI Assistant / Getting Unstuck CTFd page set.** Operators
   had reference material they could flip back to without leaving CTFd.
4. **Predictable `meetup+N` creds.** Zero credential-distribution drama.
5. **`apply_splice_watcher.py` hotfix pattern.** Saved the day for both the welcome.txt drop
   and the PDF rollout. Extend this, don't replace it.
6. **Memory-augmented sessions.** The feedback and project memories I saved mid-event (terminal.js
   UI, agentic pacing, Kali unreachability, challenge-content hands-off) made later decisions
   faster and more aligned.
7. **Event end-time extension was two lines.** Config patch via API, done in 30 seconds.
   CTFd's config API is tidy when you know it.
