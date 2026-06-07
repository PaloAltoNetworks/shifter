# Lessons — Vancity / May 2026 event (in-progress notes)

Live observations from the May 7, 2026 cohort (20 participants, ~4 hr session).
Captured during the run for post-event review.

## Onboarding confusion

- **Participants didn't know where to start.** After the magic link landed them
  on the orientation page, the next action wasn't obvious. The "First Moves"
  list mentions Start Here, but the page is dense and the first instinct was
  to look at the desktop / file manager rather than CTFd.
  - The cohort had to ask, and Brad pointed them at the **CTFd Kali Quickstart
    page** which is where the practical "where do I go" info lives.
  - Reflex fix: lead the deck/orientation with a single very prominent
    "Open the Kali Quickstart" callout. The current ordering forces them to
    derive the next click.

- **Brad didn't surface "where to go" verbally fast enough.** After the
  briefing finished, there was a gap before participants knew what to do
  with their browser tabs. Reflex fix for next event: as part of the
  briefing closing, walk through the literal click path on a projected
  screen — magic link → orientation → Kali Quickstart → ENTER RANGE.

## CTFd flag-submission format

- **CTFd should accept either `FLAG{hash}` or just `hash`.** Right now it
  rejects bare hash submissions, which trips up participants who copy only
  the hex string. Need to either:
  - Configure CTFd flag entries with two regex patterns (`FLAG\{[0-9a-f]+\}`
    and the bare-hex variant), or
  - Add a flag-normalisation hook (CTFd plugin or custom theme JS) that
    wraps `FLAG{...}` around bare hex on submission.
  - Keep the canonical answer-key in `FLAG{...}` form for clarity in
    walkthroughs and content packs, but accept both forms on the wire.

## Guacamole flakiness during the run

- **Confirmed: same symptom as BSides Ottawa.** Multiple connect attempts
  needed before a Guac session establishes; participants often see the
  password challenge instead of the connected Kali desktop. Recovery is
  to retry 2-4 times.
- The intended fix was already pushed to TF: `guacamole_db_instance_class`
  bumped from `db.t3.small` to `db.m5.xlarge` (commit `c7b3af2db` on
  2026-05-07). It got applied via the deploy pipeline but the
  `dev-portal-guacamole-db` is still running `db.t3.small` because the
  RDS module doesn't set `apply_immediately = true` — the class change
  is sitting in `PendingModifiedValues` waiting for the next maintenance
  window. So at event time the DB is still the undersized one.
- **Action items for the rds module:**
  - Set `apply_immediately = true` on the rds-module variable (or pass
    through from the wrapper) so future class/parameter changes take
    effect on the next reconcile rather than the next maintenance window.
  - Also consider: the same module is used by `dev-portal-db` (the main
    portal DB) — same flag should apply. For prod, gate with explicit
    maintenance windows.
- **Mid-event mitigation that was NOT taken:** running
  `aws rds modify-db-instance --apply-immediately` to force the queued
  class change costs ~5 min Guac downtime mid-event. Decided not worth
  the disruption; participants are getting through with retries. Worth
  re-evaluating if Guac becomes blocking.

## CTFd flags missing from 38/39 challenges (LIVE-EVENT BUG)

- Mid-event participants reported submissions being rejected for the
  Mission 1 "Company Info" flag (`FLAG{8f3a2c1e9b7d4056}`). Investigation
  found the challenge in CTFd had **zero flags configured**. Same for
  every other Mission 1-5 challenge — only the warm-up had a flag
  attached. 38 of 39 challenges were unsubmittable.
- **Fix at runtime:** posted the missing flags directly via
  `POST /api/v1/flags` for each challenge (one round-trip per challenge,
  ~5 sec total). Participants resubmitting succeeded.
- **Root cause** (suspected — needs confirmation post-event in
  `scripts/ctfd-workshop/sync_polaris_ctfd.py`): the sync upserts
  challenges by name. On the *first* sync the script also creates flag
  rows. On a subsequent re-sync (challenge already exists → "update
  challenge" path) it appears to skip the flags-sync block. Multiple
  re-syncs were run today (M6-9 trim, Ottawa/Discord removal,
  Before-You-Begin callout, etc.) — at some point along the way the
  flag rows were lost or never re-created and the sync didn't notice.
- **Action items:**
  - Audit `sync_polaris_ctfd.py`. It must idempotently ensure flags
    exist on every run, not just on initial create. Same for hints —
    the warm-up's hints synced via `create hint:` log lines but I
    didn't verify mission-challenge hints; those may also be missing.
  - Add a verify pass at end-of-sync: for every challenge, GET its
    flags and fail loudly if empty.
  - Consider switching from name-keyed to id-keyed sync (challenge id
    in the source JSON) so updates are unambiguous.

## Follow the Money — flag missing from PDF (LIVE-EVENT BUG)

- 6 participants finished M1 except "Follow the Money." Investigation
  showed the PDF at `http://boreas-systems.ctf/internal/boreas-annual-2025.pdf`
  contains the supplier hint (`Kursk Heavy Industries - actuator
  assemblies $12,000,000`) but the literal `FLAG{c6f8d2b3e91a4507}` is
  not in the file — not in body text, not in metadata
  (Author/Subject/Keywords), not in raw bytes. Same regression as a
  prior event.
- **Root cause:** `content-packages/polaris/boreas-annual-report/package.yaml`
  contains `flag-6: placeholder-flag-06-value` in metadata and
  `"FLAG-06: placeholder-flag-06-value"` in the `hidden` block.
  The bake-time PDF generator did not substitute these placeholders
  with the real flag value, so the rendered PDF ships placeholder text
  (or no flag at all). The hint copy says "search for the buried Kursk
  Heavy Industries line item" — that buried line was supposed to be
  the flag.
- **Live-event fix:** patched the CTFd flag entry for "Follow the
  Money" via `PATCH /api/v1/flags/{id}` from `static FLAG{c6f8d2b3e91a4507}`
  to `regex (?i)Kursk Heavy Industries`. Participants submitting the
  supplier name (case-insensitive) now get credit. Single API call,
  no SSM into ranges, no redeploy.
- **Action items:**
  - Audit the bake-time PDF generator (probably under
    `scenario-dev/polaris/build/A0-boreas-website/` content build).
    Substitution must replace every `placeholder-flag-NN-value` with
    the matching `FLAG-NN` from the scenario flag table.
  - Add a smoke test to the bake: for every challenge with a flag,
    verify the literal flag string appears somewhere in the rendered
    artefact (PDF, HTML, etc.). Fail the bake if missing.
  - Consider eliminating placeholder substitution entirely — embed
    the actual flag in the YAML and hide via styling/encoding.

## What worked — keep this

A counterweight to the bug list above. Real wins from the cohort.

### The full Polaris chain was exercised live

Three operators (**Christopher Yee**, **Elise Radcliffe**, **Vigneshwar
Kanagavel**) rode the entire designed campaign from M1 through the M4
trigger and into the bunker, in ~5 hours, in their **first** red-team
CTF:

- M1 OSINT — front company recon, employee directory, careers page,
  DNS reconnaissance, supplier finance audit
- M2 corporate compromise — intranet → mail → fileshare → AD →
  Kerberoast → DCSync → Pass-the-Hash → Domain Admin
- M2 / M4 entry pivot — analyst desk for the on-call engineer,
  ssh into A15
- M4 Lights Out — modbus writes to A5 SCADA generator (regs
  200/100/10/11) to deliberately crash the plant; recovered
  `FLAG{a7f2c8d0e5b34169}` from the post-failure HMI page
- Splice watcher fires automatically on each of the three ranges —
  `a14-kali` attached to `splice-link` docker network without any
  manual intervention
- Operators recognize the new network and start enumerating modbus
  controllers in the bunker

Every prior real-world cohort attempting Polaris had been pre-trained
or had OT/ICS background. This cohort had **none of that** and three
of them ran the chain anyway.

### Infrastructure held up under load

- 21 ranges (20 cohort + 1 spare) provisioned in **208 seconds** via
  `provision_event_ranges` — single API call, fully concurrent ECS
  Fargate provisioner tasks, all 21 hit READY without a single failure.
- Splice watcher fired correctly on three independent ranges with
  zero operator intervention. The systemd service detected the SCADA
  runaway state on each range's A5 container and attached `a14-kali`
  to `splice-link`. Worked exactly as designed.
- Mid-event range swap (Ranjeet → spare1's range; Chintan → spare2's
  range) worked: reassign user_id on `engine.Range` + `cms.RangeInstance`,
  swap participant pointers, resend invite. Zero downtime, no re-bake.
- 17-container compose stack on each polaris-vm stayed up with low
  load (max ~0.7 on the busiest range). m5.2xlarge sizing is correct.

### Mid-event content + access fixes were possible without redeploy

- CTFd page edits (Ottawa/Discord/M6-9 cleanup, Before-You-Begin
  callout, Start Here link) shipped via `sync_polaris_ctfd.py` page
  upsert — live within seconds, no aws-dev push.
- Missing CTFd flags (38/39 challenges had no flag rows) patched in
  via `POST /api/v1/flags` directly — bypassed the broken sync path.
- Follow the Money's missing-flag-in-PDF unblocked by switching the
  CTFd flag entry from a static string to a case-insensitive regex on
  "Kursk Heavy Industries" — single PATCH, six participants instantly
  unstuck.
- Per-participant magic-link resend via `ctf.services.resend_invite`
  worked cleanly for ad-hoc fixes (Brad's verify, Ranjeet's swap,
  Vigneshwar's lost email, Chintan's late add).

### Decisions that paid off

- **Ripping the claude-smoke-test gate from the bedrock shard step.**
  The smoke test caught the Sonnet-4.5-deprecation regression (good)
  but at the cost of tying every range provision to Bedrock latency
  and a 60s timeout. Standard scenarios don't gate on claude. Removing
  the gate let the 21 ranges come up in 208s instead of being
  bottlenecked. Keep this discipline.
- **No-magic-link-send-until-confirmed.** Created participants via
  `invite_participant` (no email), held the bulk send until the
  shipping fix was deployed and one range was verified end-to-end.
  Avoided sending 20 invitations to a broken portal.
- **The proper service path** (`provision_event_ranges`) over the
  hand-rolled `cms.services.create_range` calls. The bulk service
  set `participant.range_instance_id` and `range_status` correctly
  so `/participant/range/` resolved on first login. The hand-rolled
  path I used in early testing produced orphan ranges.

## Bedrock model deprecation (LIVE-EVENT BUG)

- Pre-flight test of `claude` inside `a14-kali` was timing out (60s
  `timeout` killed it) on every range. Network, VPCE, IAM, IMDS hop
  limit all checked out. Direct `aws bedrock-runtime invoke-model`
  from operator laptop (different network, same account) returned
  `AccessDeniedException: ... aws-marketplace:Subscribe ... `.
- **Root cause:** `us.anthropic.claude-sonnet-4-5-20250929-v1:0` had
  been deprecated/unsubscribable for the account. The model was still
  listed `ACTIVE` in `list-foundation-models` and the inference
  profile was `ACTIVE` too, but `invoke-model` rejected with the
  marketplace error. AWS does not surface deprecation cleanly via the
  list/describe APIs.
- `us.anthropic.claude-sonnet-4-6` invoked cleanly under the existing
  `bedrock-claude-code` IAM policy (which already wildcards
  `arn:aws:bedrock:*:*:foundation-model/*` and
  `arn:aws:bedrock:*:*:inference-profile/*`). No IAM change needed.
- **Fix:** swap `claude-sonnet-4-5-20250929-v1:0` → `claude-sonnet-4-6`
  across:
  - `shifter/engine/provisioner/plans/polaris_range_bootstrap.py`
    (the `anthropic_model` default)
  - `shifter/packer/scripts/kali/claude-code.sh`
  - `shifter/packer/scripts/ubuntu/claude-code.sh`
  - `scripts/config-claude.sh` (local dev)
  Haiku 4.5 is unchanged — still the small/fast model.
- **Action items:**
  - Treat the model id as a release-managed input. Bake AMIs are
    immutable and embed the value in the kali AMI's
    `/etc/profile.d/claude-code.sh` and `/root/.bashrc`. Anything
    using a stale AMI with Sonnet 4.5 will silently retry-and-timeout.
  - Add a pre-event smoke that does a single `bedrock-runtime
    invoke-model` against the configured model from the operator
    laptop. If that returns AccessDenied, every range will be broken.
    Should run as part of pre-event tagged release.
  - Consider a release-time check in CI that hits AWS Bedrock to
    verify all configured model ids are invocable. Catch regressions
    before they ship to ranges.

## Architectural inconsistency: a14-kali vs standard kali AMI

- The standard shifter kali AMI (`shifter/packer/kali.pkr.hcl`) bakes
  `claude-code` via `packer/scripts/kali/claude-code.sh`: installs
  the npm package and writes `/etc/profile.d/claude-code.sh` with
  `CLAUDE_CODE_USE_BEDROCK=1` + model env vars. Standard scenarios
  use this AMI directly for their kali instance.
- **Polaris is structurally different.** Its kali is a docker
  container (`a14-kali`) inside a 17-container compose stack baked
  into the polaris-vm Ubuntu AMI. The container is built from
  `scenario-dev/polaris/containers/boreas-kali/Dockerfile`, which
  installs `kali-linux-top10`, `nodejs`, `npm`, etc. — but **does
  NOT install `@anthropic-ai/claude-code`** and does NOT write the
  `/etc/profile.d/claude-bedrock.sh` env file.
- The runtime workaround is the `polaris_kali_bedrock_shard` step in
  the engine's `PolarisRangeBootstrapPlan`. It writes the env file
  inside the running container at provision-time and adds an
  `/etc/hosts` override for the bedrock VPCE private IP (the polaris
  compose `dns` container intercepts DNS and isn't VPC-aware, so the
  in-container browser would otherwise resolve `bedrock-runtime` to
  the public IP). Claude itself is already pre-installed because the
  baked AMI's docker image has it from a prior bake.
- **Real architectural debt:**
  - Two install paths exist for claude (packer for AMI, runtime shard
    for polaris docker). Both must be maintained in sync.
  - The polaris docker `dns` container should forward AWS-suffix
    queries to the VPC resolver (169.254.169.253), eliminating the
    need for the `/etc/hosts` shim.
  - Or: bake `claude-code` directly into the `boreas-kali` Dockerfile
    (mirroring `packer/scripts/kali/claude-code.sh`), and remove the
    runtime shard step entirely. The shard step exists only because
    the baked container is missing the install — fix the bake and
    the shard becomes unnecessary.

## Terminal copy/paste was never wired (UX bug)

- Mission Control's in-browser terminal uses xterm.js. xterm.js
  *renders* the selection (highlight visible) but does **not** push
  selected text to the system clipboard, nor accept paste — those are
  the embedding application's responsibility. The shifter wrapper
  (`shifter/shifter_platform/static/js/terminal.js`) had no
  copy/paste wiring at all. Mouse highlight worked visually; nothing
  ever reached the OS clipboard.
- **Fix:** added `terminal.attachCustomKeyEventHandler` in
  `createTerminalInstances()`:
  - `Ctrl+Shift+C` → `navigator.clipboard.writeText(terminal.getSelection())`
  - `Ctrl+Shift+V` → `navigator.clipboard.readText()` → `sendInput()`
  Falls through silently on permission denial. Consistent with native
  Linux terminal-emulator conventions.
- Test suite was NOT updated — `terminal.test.js` mock for `Terminal`
  doesn't include `attachCustomKeyEventHandler`. Jest will fail until
  the mock is patched. CI deploy on `aws-dev` doesn't run jest, so
  this didn't block the release. Action item: add mock method + test
  for the key handler.

## CTFd auth model for cohort events

- Two parallel auth systems are in play and they don't share state:
  1. **CTFd accounts** (board / flag submission) — pre-created via
     `scripts/ctfd-workshop/create_users.py` with `--default-password`.
     Username = email. Cohort uses one shared password
     (`vancity` for this event). Skips CTFd's registration flow
     entirely.
  2. **Mission Control magic links** (range access) — created via
     `ctf.services.participant.invite_participant` and emailed via
     `send_invitations` (or `resend_invite` per-participant). Token
     auto-rotates on each `resend_invite`.
- **CTFd has no first-login acknowledgement gate** built in. The
  `tos_url` config only shows a link on the *registration* page;
  participants pre-created via API never see it. A "Before You Begin"
  callout on the index page is visibility-only, not enforcement.
  Verbal acknowledgement during the briefing is the actual mechanism.
- The two systems mean: a participant can have CTFd creds without
  Mission Control creds (or vice versa). Track both in the status
  doc. For the May 2026 event, the workflow was: create both, send
  the magic link, use CTFd password as fallback if magic link fails.

## CTFd API gotchas

Caught during live operations.

- **Pagination is silent and capped at 100.** `?per_page=500` returns
  the first 100 only. Drove a misleading "no progress" report when in
  fact 57 more submissions existed beyond page 1. Always paginate
  with `meta.pagination.next` until exhausted.
- **`/api/v1/configs/...` requires `Content-Type: application/json`
  header**, not just `Authorization: Token`. Without it the endpoint
  302-redirects to `/login` even with a valid admin token. Other
  endpoints (`/users`, `/challenges`, `/pages`, `/flags`) tolerate
  missing Content-Type on GET; configs do not.
- **Flag entries need explicit `data` field** when patching — the
  PATCH body must include `id`, `type`, `content`, `data`,
  `challenge_id`, `challenge`. A partial PATCH with only `type` and
  `content` returned `success: true` but didn't always persist the
  type change cleanly.
- **Flag type `regex`** uses `re.match` (anchored at start, not end).
  `(?i)Kursk Heavy Industries` matches "Kursk Heavy Industries Inc"
  too. Acceptable for our case but worth knowing.

## IMDS + VPCE plumbing for in-container AWS SDK

- Default IMDS hop limit on a fresh EC2 is 1 — sufficient for
  processes on the host but **not** for processes inside a docker
  container reaching IMDS through the docker bridge (one extra hop).
- Without hop=2, the kali container has no AWS creds at runtime.
  AWS SDK calls fail. claude can't reach Bedrock.
- Fix in `shifter/engine/provisioner/main.py`: call
  `ec2.modify_instance_metadata_options(HttpPutResponseHopLimit=2)`
  before running `PolarisRangeBootstrapPlan`. Idempotent; warn on
  failure rather than fail the whole provision.
- For the bedrock VPCE: the polaris compose `dns` container is the
  default resolver inside `a14-kali` (via docker bridge DNS). It
  isn't VPC-aware and forwards `bedrock-runtime.us-east-2.amazonaws.com`
  to upstream resolvers, which return the public Bedrock IP. From
  inside the VPC, hitting the public IP instead of the VPCE private
  IP usually fails (depending on egress rules) — and the smoke test
  treated it as a hard failure.
- Fix is the `/etc/hosts` override the shard step drops into the
  container. Better fix is to teach the `dns` container to forward
  AWS-suffix queries to the VPC resolver (169.254.169.253) so DNS
  answers the VPCE private IP automatically. Tracked under
  "Architectural inconsistency" above.

## Mid-event range swap pattern (proven, reusable)

The pattern below worked twice in the May 2026 event (Ranjeet → spare1's
range; Chintan as new participant → spare2's range). Capture for reuse.

1. Resolve participant by id; resolve their current `engine.Range`
   and `cms.RangeInstance` (filter `user_id=...` exclude `destroyed`).
2. If swapping out an existing range, soft-destroy it: set
   `engine.Range.status = DESTROYED`, set `destroyed_at`. Set
   `cms.RangeInstance.status = "destroyed"`. (EC2 lingers — terminate
   manually post-event.)
3. Reassign the source range's `user_id` on both `engine.Range`
   and `cms.RangeInstance` to the target participant's `user_id`.
4. Update `participant.range_instance_id` = new RangeInstance.id;
   `participant.range_status = "ready"`.
5. Clear the source participant's pointers
   (`range_instance_id = None`, `range_status = ""`).
6. Optionally call `ctf.services.resend_invite(target_participant_id)`
   to email a fresh magic-link.

Total wall time per swap: <30 seconds via SSM exec to the portal
container.

## Pre-flight checklist for next event

Distilled from this run. Run all of these in order before sending
magic links to a cohort:

1. **Bedrock model invoke from operator laptop** — for every model id
   used by the engine and by baked AMIs. If any returns
   `AccessDeniedException`, fix before proceeding.
2. **Provision N test ranges concurrently** (3–5 minimum). Watch all
   of them hit READY in the engine. Confirm `participant.range_status`
   gets set, not just `engine.Range.status`.
3. **For each test range**: SSM into `a14-kali` and run
   `claude -p "ok"`. Should return inside 30s.
4. **CTFd flag verification sweep**: for every challenge in CTFd,
   `GET /api/v1/challenges/{id}/flags` and assert non-empty. Run
   after every `sync_polaris_ctfd.py` invocation, including re-syncs.
5. **Content artefact verification sweep**: for every challenge that
   embeds the canonical `FLAG{...}` in scenario content (PDFs, HTML,
   files inside the range), `grep` for the exact flag string. Fail
   loudly on any miss. The "Follow the Money" PDF placeholder
   regression would have been caught here.
6. **Trigger the splice flip on a test range** end-to-end. SSH into
   A15, run the modbus runaway, confirm `a14-kali` attaches to
   `splice-link` automatically, confirm the flag is on the post-failure
   HMI page.
7. **Submit one flag end-to-end via CTFd UI** (don't just hit the API)
   — confirms the participant-facing `/api/v1/challenges/attempt`
   path works.
8. **Magic-link round-trip**: send to operator's own email, click,
   land on `/participant/range/`, verify the range card renders.
9. **In-browser terminal**: open one, type something, select output,
   `Ctrl+Shift+C`, paste outside the terminal. Confirms clipboard
   wiring is alive.

## Things that fell through despite preparation

- The 3.97.0 cycle bumped Sonnet 4.5 → 4.6 in source but the change
  shipped to ranges via redeploy and shard-step-rewrite, not via
  rebake. Future bakes ship with whichever model id was current at
  bake time; runtime-shard substitution masks AMI staleness. Make the
  AMI bake-version vs runtime-config relationship explicit.
- Multiple `sync_polaris_ctfd.py` re-runs over the day silently lost
  the flag rows on every challenge (root cause TBD). The page sync
  worked reliably; the challenge-flag sync did not. The script needs
  a verify-after-sync pass.
- Per the BSides Ottawa lessons (`lessons-1.md` / `-2.md` / `-3.md`),
  the Guacamole undersizing was already known. The fix was committed
  to TF but the apply window default deferred it. **Bug filed against
  one's own past lessons file is still a bug.** Either set
  `apply_immediately = true` in the rds module or schedule a
  pre-event maintenance window to flush queued RDS changes.

## UX is the bottleneck (operator's read on the cohort)

Two things made the experience painful that have nothing to do with
the campaign content itself.

### Onboarding: nothing tells participants where to go first

- **Neither the briefing deck nor the CTFd site makes the first
  click obvious.** The briefing finishes; the participant lands on
  the CTFd orientation page; they read it; they don't know what to
  do next. The deck never says "now do X" with a literal click path,
  and the CTFd page leads with mission narrative before action.
- The "First Moves" list on the CTFd index page exists but is buried
  below the hero text. Participants who scroll past it head straight
  for the desktop / file manager looking for "the thing to do" and
  miss it entirely.
- **Reflex fixes for next event:**
  - Briefing deck closing slide (or replacement of "Range Access")
    should walk through the *literal* clicks: magic link → orientation
    → ENTER RANGE → CTFd Start Here. Project this on the screen during
    kickoff. No verbal-only handoff.
  - CTFd orientation page should lead with a single big call-to-action
    ("Click here to begin → /challenges") above all content. Mission
    narrative below the fold, not above it.
  - Send a one-page printed cheat sheet to each seat with the URL +
    cred + first-step command. Removes the "where do I start" tax.

### Guacamole unreliability is a painful UX break

- Already documented above as the t3.small RDS that didn't get
  resized in time (apply_immediately = false). Capturing here from
  the **UX angle** because the failure mode is what hurts:
  - Participant clicks ENTER RANGE → password challenge appears
    (instead of the connected Kali desktop) → confused → retries →
    confused again → maybe gets in on retry 3 → loses momentum.
  - Worse on the first click of the day when they don't yet know
    "this is normal, just retry." First impressions of the platform
    are *flaky and confusing*.
  - Compounds the onboarding problem above: a participant who *can't
    even reliably log in* spends their first 10 minutes fighting the
    plumbing instead of reading the briefing.
- **Two things have to land before next event:**
  1. The Guac DB resize must actually be applied (not queued behind
     a maintenance window). Either set `apply_immediately = true`
     in the rds module, or schedule a pre-event reboot to flush.
  2. The first-attempt success rate for Guacamole load must be very
     high — measure this in the post-event review. If it's not,
     investigate guacd/guacamole-client connection-establishment
     code path, not just DB sizing. The DB is only one possible
     bottleneck.

## A9 SSH credentials are not discoverable in the range (P0 DESIGN BUG)

- After the splice flip, a14-kali is on `splice-link` and the A9
  splice-relay host is reachable at `172.20.50.5:22`. Participants
  must SSH into A9 to reach the bunker controllers — A9 is the only
  host with a route to 172.20.50.10/11/12/50.
- The SSH credentials are `root:splice2025`. **That password is not
  in any in-range artifact** — `grep -r splice2025` across
  `scenario-dev/polaris/{build,content-packages}/` returns zero
  hits outside `a9/Dockerfile` (build-time only, not in the running
  container) and the operator walkthroughs (not exposed to
  participants).
- **Live-event evidence:** at least one of the three top scorers
  (with no prior red-team CTF experience) explicitly reported being
  blocked here in post-event feedback — they got the SCADA blackout,
  triggered the splice, found A9 on port 22 via nmap, and could not
  authenticate. They got no bunker flags as a result. Two of three
  bunker-eligible operators stalled here.
- **Fix options:**
  1. Embed the credentials in a discoverable in-range artifact —
     e.g., a forensic note in the splice-watcher service file on
     a14-kali ("recovered relay creds: root / splice2025"), or in
     a maintainer log on A9 itself reachable via guest banner /
     pre-auth.
  2. Replace password auth with an SSH key pre-staged on a14-kali
     (e.g., `/home/kali/.ssh/splice_relay_key` deployed by the
     splice-watcher step). Participants discover the key file once
     attached to splice-link.
  3. Both. The SSH key is more robust; the documented credential
     is what an OT pentester would expect to find on the relay.
- **P0 priority** for the next event. This single missing artifact
  cost two top scorers the entire bunker chain (1300 pts). The
  bunker challenges themselves are well-designed but unreachable
  without this fix.
- **RESOLVED 2026-05-26 via #707.** Option (b) shipped: A9 is now
  key-only (`PasswordAuthentication no`), and the range bootstrap
  (provisioner for EC2 ranges, `tests/setup.sh` for the dev compose
  range) generates a per-range Ed25519 keypair and stages the
  private half at `/home/kali/.ssh/splice_relay` on a14-kali (mode
  0600). `~/.ssh/config` aliases `splice-relay` to that IdentityFile
  so the participant verb is still `ssh root@splice-relay`. The
  scenario_smoketest harness gained a challenge-31 adapter that
  proves the evidence file, the SSH auth, and the Modbus device-id
  chain end-to-end from a14-kali.

(Add as the event continues — fill in further confusions, blockers,
unexpected issues, and any operator/facilitator notes worth carrying
forward to the next cohort.)
