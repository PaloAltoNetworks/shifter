# POLARIS Lessons — Ottawa BSides prep, splice gating + egress hotfix

Session-specific lessons pulled from the run-up to BSides Ottawa (flag 19
splice gating + range-VPC egress fix). Written down so the next event
doesn't re-learn them.

## Provisioning architecture — what actually deploys

- The `polaris-vm` "AMI" is a real baked AMI — not stock Ubuntu + user_data.
  `scripts/polaris-aws-range/` is the **bake pipeline**: it stands up a
  temporary range, runs `user_data.sh.tpl` (fetches build tarball from S3,
  `docker compose build && up -d`), verifies end-to-end, then
  `aws ec2 create-image`s the running host and writes the AMI ID to SSM
  `/shifter/ami/polaris-vm`.
- Participant ranges launch from that baked AMI via the real range
  provisioner. Their per-range user_data (`kali.sh.tpl`) is minimal —
  just hostname + SSH key. The compose stack is already running on the
  AMI. Per-range customization happens in SSM bootstrap.
- There are **two content paths** that both feed a deployed range:
  1. The S3 build tarball (operator-uploaded; baked into the AMI).
     Changes require a new tarball upload AND a new AMI bake.
  2. The provisioner container image (auto-rebuilt by
     `.github/workflows/deploy.yml` on push to main). Changes
     auto-deploy to *new* ranges on next `terraform apply`.
- Prefer path (2) for post-bake fixes. Path (1) has no CI/CD and
  requires manual operator action.

## Docker compose constraints

- `docker-compose.override.yml` can **add** network memberships but
  cannot **remove** them. To strip a pre-wired network from a baked
  compose file, run `docker network disconnect` explicitly after
  `docker compose up -d --force-recreate`.
- Compose prefixes network names with the project name. Project name
  defaults to the containing directory. `splice-link` in the compose
  file becomes `build_splice-link` on the host. `docker network
  disconnect splice-link a14-kali` fails with "no such network" — you
  need the prefixed name, or discover it dynamically:
  `docker network ls --format '{{.Name}}' | grep -E '(^|_)splice-link$'`.

## Jinja renderer pitfalls in provisioner plans

- `SetupOrchestrator._render_script` scans the entire plan script
  string with `\{\{\s*(\w+)\s*\}\}` and raises `SetupError` for any
  match whose name isn't in the plan's context dict.
- Go template tokens with a **leading dot** (`{{.Name}}`,
  `{{json .NetworkSettings.Networks}}`, `{{range .Containers}}`) pass
  through untouched — the dot breaks the `\w+` match.
- Bare word-only tokens **do** match. Landmines include `{{end}}`,
  `{{range}}`, `{{word}}`. These will fail at render time, not at
  deploy time.
- The scan doesn't skip bash comments inside the Python string. A
  `# note about {{end}}` in a heredoc **will** collide with the
  renderer. Avoid the braces in comments too.
- Safe pattern for container introspection: `docker inspect <name>
  --format '{{json .NetworkSettings.Networks}}'` + `grep -q` for the
  network name. No `{{range}}...{{end}}` required.

## Testing strategy — minimal harness beats full stack

- Building the 17-container polaris stack on a laptop is impractical
  (Kali image is huge, some images may not build on Apple Silicon).
  Don't try.
- A 3-container harness proves the logic end-to-end in under a minute:
  - tiny Flask-ish HTTP server that returns the same JSON shape as
    `A5 /api/status` (with a `/trigger` endpoint to flip
    `runaway_complete=true`)
  - alpine stand-in for a14-kali
  - alpine + `nc` stand-in for a9-splice
  - the real Docker networks at test CIDRs (172.30.x for isolation
    from production 172.20.x)
- Simulate the baked state explicitly: compose-wire A14 to splice-link
  up front, then run the hotfix logic, then assert the gate closes
  before the trigger and opens after it. Without this, you test the
  watcher in isolation and miss the "pre-wire is still there" case.

## Network Firewall as the real choke point

- Range VPC has an AWS Network Firewall with STRICT_ORDER stateful
  rules: GCP/Cortex IP allowlist + DNS-to-8.8.8.8 + NTP + drop-all at
  priority 100. Docker Hub, apt, arbitrary participant targets are all
  blocked by the drop-all.
- SGs and NACLs on range boxes are **fully permissive** (egress
  `0.0.0.0/0`, NACL default). The firewall is the sole egress choke
  point. When egress breaks, check the firewall first; the SG/NACL
  check is a formality.
- Cheapest live override: new stateful rule group with
  `pass ip any any -> any any` added to the policy at a priority
  below drop-all. Doesn't modify any existing artifact; revert is
  "remove the reference and delete the rule group".
- This diverges from
  `platform/terraform/modules/range/vpc/firewall.tf`. Next
  `terraform apply` ignores unknown rule groups but won't manage them
  either. Plan a TF commit to persist.

## Hotfix architecture when CI/CD time is gone

- The bootstrap plan is per-range SSM RunCommand. If you can't wait
  for a CI/CD cycle, write a script that does the same thing the
  bootstrap would do, targeting already-deployed instances.
- Targeting: discover instances by `image-id = $(aws ssm get-parameter
  /shifter/ami/polaris-vm)` + `instance-state-name = running`,
  optionally scoped to the range VPC.
- Rate safety: SSM SendCommand caps InstanceIds at 50 per call. Batch
  accordingly. Use `MaxConcurrency` inside the batch (≈10) so SSM
  paces execution and a single range's NAT doesn't see a flood.
- Keep the hotfix script byte-identical to the bootstrap heredoc
  (embed the same watcher, same systemd unit). Drift between the two
  creates bugs that only surface on mixed fleets (some new-provisioned,
  some hotfixed).
- Snapshot state before mutating shared infra (firewall policy,
  security groups, route tables). `aws ... describe-* > /tmp/...json`
  is a 2-line audit trail.

## Process discipline

- When corrected ("I don't think you understand"), go back to primary
  sources. Explore/Plan agent summaries compress and can drop details.
  Reading the actual `ranges.tf`, `user_data.sh.tpl`, and `kali.sh.tpl`
  in this session corrected a wrong mental model of the AMI lifecycle.
- Propose-then-apply for live changes. Explicitly list the change, the
  blast radius, and the revert command. Wait for "ok" before executing.
  Applies to AWS Console/CLI mutations, not just code edits.
- Don't dual-own artifacts. First version of the splice watcher lived
  both in `scenario-dev/polaris/build/` (tarball source) and in the
  bootstrap plan heredoc. Two sources of truth invites drift; pick one.
  For post-bake logic, the bootstrap plan (auto-deployed) is the right
  owner.

## Scenario-specific: flag 19 splice gate

- A5's Flask HMI already exposes state at `/api/status` — no new
  endpoint needed to detect flag 19. Poll via
  `docker exec a5-scada python3 -c 'import urllib.request; ...'`
  so the watcher doesn't need a route into the scada network from the
  host. (The `container_name:` in `build/docker-compose.yml` is
  `a5-scada`, not `a5-scada-generator` as an earlier draft claimed —
  that wrong default was the source of the silent watcher failure at
  BSides Ottawa where operators had to manually `docker network connect`
  per participant.)
- The watcher must be long-running (systemd `Type=simple`,
  `Restart=on-failure`). A one-shot doesn't work — runaway state can
  flip after participants finish the exploit chain.
- The gate should be **idempotent** on both sides: disconnect is
  no-op if not connected; connect checks `is_connected` before
  re-attaching. Flag 19 can be re-earned after a container restart;
  the watcher must handle that without spamming `connect` errors.

## Scenario-specific: egress needs

- Kali participants need more than GCP/Cortex. Hotfix rule is
  `pass ip any any -> any any` (wide open). For a quieter future
  version, the right shape is probably: keep drop-all, explicitly
  allow the domains/IPs Kali tooling actually needs (Kali mirrors,
  PyPI, GitHub, Docker Hub, common resolver IPs).
- Don't rely on the firewall's domain allowlist for Kali — TLS SNI
  filtering has performance and compatibility issues with modern
  clients that use ECH or reuse connections. IP allowlist + DNS
  allowlist is more predictable.
