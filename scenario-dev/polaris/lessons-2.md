# Lessons from BSides Ottawa 2026 — Polaris live event

Captured from the operational run of 2026-04-15 (110 participants, ~4h event window, AWS dev account + Account B overflow). Organized by where the lesson hit us, not by polish.

---

## Bedrock / model access

### Model onboarding is a console-only gate, not IAM

`bedrock:InvokeModel` with correct resource ARN is **not sufficient** for newer Anthropic models. Some models additionally require a one-time Anthropic use-case form submission in the Bedrock console (per account, per region). The failure mode is indistinguishable from a permissions gap — the same `ResourceNotFoundException` with "Model use case details have not been submitted" message, except it cannot be fixed via IAM changes.

**Action for next event:** before provisioning, from a **real range's instance-profile role** (not an admin), invoke every model ID you plan to use. Fix any failures in the console before distributing participant links. Test with exactly the model ID the shard script will set — `us.anthropic.claude-sonnet-4-6` failing doesn't tell you anything about `global.anthropic.claude-sonnet-4-6`.

### TPM quota math: shard count matters more than raw quota

Default per-model CRIS TPM in a fresh account (≈5–6M TPM) looks like headroom on paper, but two-way sharding (55 users per bucket at ~110K TPM/user burndown) lands you right at the quota. You need at least four quota buckets per model to have real margin:

- **US CRIS** and **Global CRIS** are separate quotas for the same model — easiest 2x for zero complexity.
- **Per-region on-demand** quotas are smaller and require enabling the model per region.
- **Cross-account** doubles everything again — cheap insurance.

**Rule of thumb:** aim for a per-shard steady-state load below 50% of its quota. For 100+ users, that means 8 buckets (2 accounts × 2 models × US/Global CRIS).

### Account B as live backup, not cold standby

A "cold" backup account that takes hours to switch to is useless mid-event. Wire it in from the start with live traffic (static IAM user keys, stored in Account A Secrets Manager, injected into the Kali env via `docker-compose.override.yml` or profile.d file). Then a failing shard is a table edit + ~10 min of re-apply, not a 2-hour recovery.

### IMDSv2 hop limit default = 1 silently breaks containers

EC2's default `HttpPutResponseHopLimit=1` combined with Docker bridge networking kills IMDSv2 token PUTs from inside containers. Claude Code (and any AWS SDK relying on instance profile) then has no credentials and returns nothing — no clean error, just empty output. **Bake `HttpPutResponseHopLimit=3` into the Terraform launch template** for any instance that runs containers needing instance-profile auth.

---

## Provisioning

### Range.status DB flag lags actual readiness by 10–20 minutes

The provisioner publishes "Completed" to SNS → SQS → portal worker → DB update. The queue processing can lag 10–20+ minutes behind the actual container-up state. A provisioning orchestrator that polls `Range.status` and aborts on timeout will get false negatives.

**Better signal:** check EC2 instances via `aws ec2 describe-instances` (tagged `shifter:range_id`) + directly check docker container count on the host. A range with both `kali` and `dc01` running for 15+ min and `a14-kali` at 22/22 containers is ready, regardless of what the DB says.

### Pipeline triggers; don't serialize

Per-batch serial ("trigger, wait 22 min, trigger next") works but wastes the overlap window. Trigger next batch as soon as the **previous batch's EC2 instances are launched** (pending/running), not after they're fully provisioned. Cut our 110-range rollout from ~4 h projected → ~33 min actual. See `orchestrate_provisioning.py --wave-ec2-gate`.

### Watch the verification signal

Our initial orchestrator's batch-failure threshold tripped because Range.status still showed "provisioning" at the timeout. Ranges were fine. The remediation rule: **if the retry pass finds zero unprovisioned participants, the "failures" were false positives**. We ended up with a `--sleep-only` mode that just sleeps between batches and skips status polling entirely.

### ECS Fargate provisioner concurrency

~30 concurrent provisioner tasks ran without issue; EC2 RunInstances never throttled; the per-range DC Windows bootstrap was the longest step (~15 min). The provisioning path does not bottleneck at 100+ ranges.

---

## Session + environment delivery

### `/etc/profile.d/*` is **login-shell only**

The fundamental surprise: the SSH flow into `a14-kali` is a login shell (sources `/etc/profile.d/*`), but **xrdp → xfce4-terminal is a non-login interactive bash** (sources `/etc/bash.bashrc`, does NOT source profile.d). Env config pushed only to `/etc/profile.d/` breaks RDP users silently. Belt-and-braces: also source from `/etc/bash.bashrc` and write plain `KEY=value` to `/etc/environment` (PAM-applied for any session).

### Modifying env of a running shell is borderline impossible

Linux doesn't let you rewrite `/proc/$pid/environ` of a running process. If the participant's shell captured old env at spawn time and is in the middle of an interactive `claude` session, your options are:
- `tmux respawn-pane -k -t <pane>` — kills current process, respawns a fresh login shell, keeps tmux + SSH alive (**cleanest**)
- `tmux kill-server` — nukes the whole server; forces reconnect (**collateral observed**: in our setup, killing tmux in two specific containers somehow caused a brief, unexplained outage for other users; don't use unless you know why)
- `tmux send-keys "source /etc/profile.d/..."` — works if pane has a bash prompt, fails if pane is running a Node.js process like claude (send-keys goes into claude's stdin)

**Default to `respawn-pane -k`.**

### Wrapper binary replacement has a nasty edge case

Attempting to replace `/usr/local/bin/claude` (which was a symlink to a 13 MB Node.js entry point) with a bash wrapper using `cat > /usr/local/bin/claude` followed the symlink and overwrote the target cli.js, bricking that range's Claude Code install. Recovery: `npm install -g @anthropic-ai/claude-code@<version>`.

**Rule:** when replacing a path that may be a symlink, always `rm -f <path>` first, then create the new file. Never `cat >` or `>>` against an unknown path type.

### Scenario DNS container and Bedrock endpoints

The scenario's in-range DNS service returned **public** IPs for `bedrock-runtime.us-east-2.amazonaws.com`. A private subnet can't route to those. Fix: `/etc/hosts` override in `a14-kali` mapping the hostname to the Bedrock VPC endpoint's private IP (e.g. `10.1.0.42`). Better long-term: configure the scenario `dns` container to forward unknown queries to `169.254.169.253` (Amazon-provided DNS).

**Discovery trap:** VPC endpoints create one ENI per subnet. If your ranges span multiple subnets but the Bedrock VPCE only has one ENI, you rely on cross-subnet routing. Works for small events; worth baking endpoint-per-subnet for larger ones.

---

## Diagnostics and recovery patterns

### SSM agent hang ≠ instance down

User 17's SSM agent went unresponsive (commands queuing, no drains, last ping 11 min old) while the EC2 instance itself reported `ok/ok`. Side effect: the portal's terminal UI couldn't reach the range either.

**Fix:** `aws ec2 reboot-instances`. With `docker --restart unless-stopped`, all 22 scenario containers came back in 3 min, no re-provisioning needed. Container filesystem changes (the Bedrock shard config) survived the reboot because containers were restarted, not re-created.

**Rule:** if SSM is stuck but EC2 is healthy, reboot before spending more time diagnosing.

### Container restart ≠ container recreate

Our `docker-compose.yml` was set up with `--restart unless-stopped`. On host reboot, containers restart but are **not re-created from image**, so container filesystem state (written config, installed env hooks) is preserved. If docker-compose ever ran with `--force-recreate` on boot, all that state would be lost and would need re-applying.

### Health-check must exercise the actual failure mode

My range-health-check script verified config FILES existed (`/etc/profile.d/claude-bedrock.sh` present, env vars declared) and returned 108/112 "healthy". But the actual failure was the `claude` binary invoking Bedrock and receiving "model not available" — which the file-inspection check couldn't catch. **Any health check must actually drive the failure path end-to-end.** In this case: `claude -p "reply ok"` and check the response.

### Cross-account S3 friction

Range instance role had no S3 write perms in Account A's buckets. When I needed to shuttle files (e.g. restoring a cli.js from a clean range to the broken one), I had to use presigned URLs from my local admin credentials. For future events, either grant a narrow "staging bucket" write permission on the range role or stash a utility container image on S3-public-readable ahead of time.

---

## User-facing flow

### Magic link distribution: clickable grid beats email copy-paste

Users copy-pasting magic-link URLs out of printouts/emails produced "invalid token" reports en masse. Platform was fine — the tokens in the DB matched what was sent. The fix was a simple static HTML page on the CTFd box with a click-grid of `001`–`110` buttons, each linking to that participant's magic URL. One click, no retype.

**For next event:** make the briefing deck's last slide a range-link grid from day one. No paper. No typing.

### Pre-event block via ALB fixed-response

Keeping the magic links distributed early but gated until event start: add an ALB listener rule with a `path-pattern: /ctf/register*` condition and a `fixed-response` action returning 503 with a "opens at X" message. Takes seconds to add via CLI, same to remove. Clean, zero app-layer code.

### Token TTL ceiling is `min(event_end, now + MAGIC_LINK_EXPIRY_HOURS)`

Generated tokens have an expiry baked in at save time. Extending `event_end` after the fact doesn't extend already-issued tokens — you'd need `resend_invite` to mint fresh ones. Plan `event_end` generously upfront.

---

## Cost + monitoring

### Billing data lag makes real-time budgets weak

AWS Cost Explorer and Budgets update on an 8–12 hour lag. A $500 budget alert for a live event is a post-mortem tool, not a circuit breaker. For real-time kill-switches, use **Bedrock CloudWatch metrics** (`InputTokenCount`, `OutputTokenCount`, `Invocations` — published ~5 min cadence) and compute running cost locally from known per-token pricing.

### Account-level spend baseline

BSides Ottawa event day (110 ranges × ~4h active + provisioning overhead) ran around **$80 / day on Account A** for compute/infra (EC2/VPC/NGFW/ECS/RDS/ElastiCache) plus **$170–220 on Account B** for Bedrock token cost over 6 hours. Rough rule: $250–$350 / day for an event this size once all the pieces are accounted for. Useful for future quoting.

---

## Operational discipline

### Scope every change

The user repeatedly had to tell me "only touch user 44, nothing shared". Under time pressure my instinct was to push broad fixes. The successful moves were all surgical: one kali container restart, one tmux respawn-pane, per-participant config re-write. **Default to smallest blast radius. Prefer `respawn-pane` to `kill-server`, per-instance SSM to fleet-wide.**

### Idempotent install scripts + markers

Every mutation script written for this event used marker-guarded file edits (`# BEDROCK_BASHRC_HOOK` etc.) and re-ran safely. This made re-fire-when-broken a non-event. Worth the 10 lines of guard logic every time.

### Cache static lookups locally

Building a participant→range→instance map once at the start (dumped to `/tmp/pmap.json`, `/tmp/rmap.json`) cut per-user remediation from 20 seconds (SSM round-trip + Django shell) to 1 second (local dict lookup + one SSM). When a user pings mid-event saying "I'm broken", that latency matters.

---

## Things to bake in before the next event

1. **AMI build:** set IMDSv2 hop limit to 3 in the launch template; install the Bedrock `/etc/hosts` override at build; bake the profile.d + bash.bashrc + /etc/environment hooks so fresh ranges don't need post-provision remediation.
2. **Scenario DNS:** forward unknown queries to `169.254.169.253` so AWS endpoints resolve privately.
3. **Model onboarding preflight:** a script that assumes the range instance role and invokes every model your shard table references. Block go/no-go on it.
4. **Shard table in code, not in a scratchpad:** current `SHARD_TABLE` in `apply_kali_bedrock_shard.py` should move to the provisioner's bootstrap plan so every new range is born with the right config.
5. **Event-end + token TTL:** set `MAGIC_LINK_EXPIRY_HOURS` high (48+) and set `event_end` conservatively; makes links robust to schedule slips.
6. **Orchestrator:** default to `--wave-ec2-gate` with `--final-wait` rather than sleep-only; makes timing predictable and minimizes wall clock.
7. **Briefing deck:** auto-inject the range-link grid as the final slide at provisioning time; don't hand-paste tokens.
8. **Health check runs real invokes:** `claude -p "reply ok"` across all ranges as the green/red signal, not config file inspection.
