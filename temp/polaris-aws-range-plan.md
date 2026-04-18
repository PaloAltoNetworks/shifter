# POLARIS → AWS: build reference range, AMI from it

## Context

Produce one AWS AMI per POLARIS asset in `panw-shifter-dev-workstation` us-east-2, plus a cyberscript scenario and supporting provisioner plans that consume them. Event in under 48 hours. GCP work is parallel in another worktree and out of scope here. All work lands on `polaris-ctf` branch.

### Approach: build a working golden reference range in AWS, then image each instance

Instead of writing Packer templates that try to reproduce the docker-compose golden range from scratch, **stand up the real range in a real AWS VPC with real subnets and real networking, run it successfully end-to-end, then `aws ec2 create-image` on each instance.** 17 running instances → 17 AMIs.

Each instance is a plain Ubuntu 24.04 EC2 running Docker + the asset's existing Dockerfile image. `docker run --network host` inherits the instance's primary + secondary ENIs, so multi-homed assets (A14, A15, A16, A9, DNS) get real multi-homing via cloud networking, not simulation.

**Why this beats Packer for the 48-hour window**:
- No Dockerfile-to-setup.sh translation. Zero translation risk.
- Interactive debug on live instances when something breaks.
- Real networking verified before the AMI exists.
- The golden range audit issues (sleep 8 in A7, runtime init in A1/A4/A6/A15/A16, /tmp/a6-content volatility) **don't apply** because each instance runs the asset as a Docker container, exactly as compose does. Same behaviour, no divergence risk.
- `create-image` on a stopped instance is a single API call — no build pipeline.

**Pin private IPs to compose CIDRs**: every POLARIS range uses `172.20.0.0/16` internally, matching docker-compose. Every instance's `private_ip_address` is pinned to its compose IP. This means the `dns` asset's zone files (which hardcode 172.20.x.y records) work **unchanged** — no runtime zone templating, no DNS inject plan needed. All future cyberscript-provisioned ranges reuse the same CIDRs inside their own VPC (no conflict between ranges).

## Phase 1 — Terraform for the golden reference range

New TF module at `scripts/polaris-aws-range/` (one-shot, not part of the main `platform/terraform/` tree — keeps the main pipeline clean and lets us destroy this when we're done):

- `main.tf`:
  - VPC `polaris-golden` 172.20.0.0/16
  - Subnets: shared 172.20.0.0/24, corporate 172.20.10.0/24, lab 172.20.30.0/24, scada 172.20.40.0/24, bunker-ot 172.20.50.0/24, splice-link 172.20.60.0/24
  - Internet gateway + NAT on corporate (for apt/docker install); strip before image
  - Security groups per the compose topology (see next section)
  - 17 `aws_instance` resources, Ubuntu 24.04 base (use the existing `${prefix}-ubuntu-*` AMI)
  - Primary ENI pinned to compose IP: A0 172.20.0.10, DNS 172.20.0.2, A14 172.20.0.140, A1 172.20.10.20, A3 172.20.10.30, A4 172.20.10.40, A15 172.20.10.50, A16 172.20.10.60, A5 172.20.40.10, A6 172.20.30.10, A7 172.20.30.20, A8 172.20.30.30, A9 172.20.50.5, A10 172.20.50.10, A11 172.20.50.11, A12 172.20.50.12, A13 172.20.50.50
  - Secondary ENIs for multi-homed instances:
    - A14: +corporate 172.20.10.140 +splice-link 172.20.60.140
    - A15: +scada 172.20.40.20
    - A16: +lab 172.20.30.60
    - A9: +splice-link 172.20.60.5
    - DNS: +corporate 172.20.10.2 +lab 172.20.30.2
  - VPC DHCP option set pointing at 172.20.0.2 (the DNS instance's shared-subnet IP)
  - Key pair + SSH access from operator IP (open 22 from a parameter CIDR)
- `sg.tf` — security groups enforcing compose reachability, notably:
  - A14 → shared, corporate (direct); splice-link → A9 only
  - A15 → scada → A5
  - A16 → lab → A6, A7, A8 (and A16 NEVER → A9)
  - A9 → bunker-ot → A10–A13
  - Every subnet → DNS on 53/udp+tcp
- `user_data.tf` — renders per-asset user-data shell script from a template, injects asset name + S3 bucket for the build tarball
- `variables.tf` — bucket name, operator CIDR, ubuntu AMI ID
- `outputs.tf` — instance IDs, private IPs, AMI ID placeholders

TF backend: local state for the golden range — this is a one-shot artifact, not a permanent resource. Commit the `.tfstate` to the repo under `scripts/polaris-aws-range/` is NOT needed (gitignored per existing `.gitignore` TF rules); operator runs `terraform apply` with local state.

## Phase 2 — Build tarball uploaded to S3

Single tarball containing the entire `scenario-dev/polaris/build/` tree:
- `tar czf polaris-build-v1.tar.gz scenario-dev/polaris/build/`
- `aws s3 cp polaris-build-v1.tar.gz s3://<bucket>/polaris/build-v1.tar.gz` — bucket = use an existing panw-shifter-dev-workstation bucket the Packer OIDC role already has write access to, or create `shifter-polaris-artifacts` if none exists
- Instance profile on EC2 instances gets read access to this object via IAM role

Tarball includes `_shared/gpg-chain/` and `_shared/research-analyst-key/` — byte-stable, single upload, every instance pulls the same bytes. Flag 30 chain protected.

## Phase 3 — Per-instance user-data

Common user-data template (Jinja2-rendered from TF), parameterised by asset name:

```bash
#!/bin/bash
set -euo pipefail
exec > >(tee /var/log/polaris-bootstrap.log) 2>&1

# Install Docker
apt-get update
apt-get install -y docker.io awscli

# Pull build tarball
cd /opt
aws s3 cp s3://<bucket>/polaris/build-v1.tar.gz .
tar xzf build-v1.tar.gz
cd scenario-dev/polaris/build

# Build the asset's docker image
ASSET="{{ asset }}"
docker build -f "${ASSET}/Dockerfile" -t "polaris-${ASSET}" .

# systemd unit runs the container with host networking
cat > /etc/systemd/system/polaris-asset.service <<EOF
[Unit]
Description=POLARIS asset ${ASSET}
After=docker.service
Requires=docker.service

[Service]
Restart=always
ExecStartPre=-/usr/bin/docker rm -f polaris-${ASSET}
ExecStart=/usr/bin/docker run --rm --name polaris-${ASSET} --network host polaris-${ASSET}
ExecStop=/usr/bin/docker stop polaris-${ASSET}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now polaris-asset.service
```

Three assets need special handling in user-data:
- **A14 (Kali)**: its Dockerfile is Kali-based with xrdp. `--network host` still works. No special handling; same template.
- **DNS**: Dockerfile builds BIND with baked zone files; those files already reference the exact compose IPs we're pinning. Just runs.
- **A8 postgres**: container initializes on first `docker run` against empty volume. Fine — the volume lives inside the container filesystem under host networking, so postgres initializes the `docker-entrypoint-initdb.d/01-init.sql` GPG row on first run. Baking is captured when we AMI the instance.

## Phase 4 — Bring up the range, verify in place

1. `terraform apply` — creates VPC, subnets, SGs, 17 instances, secondary ENIs, DHCP option set
2. Wait for all user-data to finish (watch `/var/log/polaris-bootstrap.log` via SSM RunCommand or SSH)
3. Verify each instance:
   - `systemctl status polaris-asset.service` green
   - Asset-specific smoke: gitea `/api/v1/version`, postgres `SELECT 1`, samba `smbclient -L`, BIND `dig @172.20.0.2`, flask servers respond on expected ports
4. From A14 Kali (SSH in via operator IP), run all four walkthroughs:
   - `00-range-access.md` — just connectivity checks (skip the docker-exec steps; we're on a real EC2 now, SSH is the model)
   - `flags-07-19-front-office.md` — A0/A1/A3/A4/A15/A5 chain
   - `flags-20-30-lab.md` — A16/A6/A7/A8/A9 chain
   - `flags-31-36-bunker.md` — A9 → A10-A13 chain
5. Capture 38/38 flags end-to-end. Any break → debug live on the affected instance → fix → re-verify.

## Phase 5 — Clean + AMI each instance

For each of the 17 instances:
1. SSH in, cleanup script:
   - `truncate -s 0 /var/log/*.log /var/log/*/*.log 2>/dev/null || true`
   - `rm -f /root/.bash_history /home/ubuntu/.bash_history`
   - `docker stop polaris-<asset> && docker rm polaris-<asset>` (so AMI captures a clean host, container restarts from image on next boot)
   - `cloud-init clean --logs`
   - `sudo shutdown -h now`
2. `aws ec2 create-image --instance-id <id> --name polaris-<asset>-v1-<timestamp> --no-reboot` (we already stopped, so no-reboot is fine)
3. Tag the AMI: `Project=polaris`, `Asset=<asset>`, `Version=v1`, `ManagedBy=manual-golden-range`
4. Wait for AMI `available` state
5. Write SSM param `/shifter/ami/polaris-<asset>` = new AMI ID in `panw-shifter-dev-workstation` us-east-2

Script this as `scripts/polaris-aws-range/snapshot.sh`: loops over all 17 instance IDs, runs cleanup via SSM RunCommand, shuts down, creates AMI, writes SSM, reports.

## Phase 6 — Cyberscript scenario + provisioner plans

### Scenario template

`shifter/shifter_platform/cms/scenarios/templates/polaris_northstorm.yaml`:
- All 17 instances with `ami_key: polaris-<asset>`
- A14: `role: attacker`, `os_type: kali`, other 16: `role: victim`, `os_type: ubuntu`
- Subnets: shared, corporate, scada, lab, bunker-ot, splice-link — matches golden range
- `connected_to` mirrors the reachability graph (A14 ↔ shared/corporate/splice-link, etc.)
- Scenario ID `polaris_northstorm`, enabled, no NGFW (for now)

### Schema additions

Both the cyberscript and CMS schema need a single additive field:
- `shifter/cyberscript/schemas/range.py:InstanceSpec` — add `additional_subnets: list[str] = []`
- `shifter/shifter_platform/cms/scenarios/schema.py:InstanceConfig` — add `additional_subnets: list[str] = []`
- `InstanceSpec.from_template()` passes it through
- Default `[]` preserves all existing scenarios

### Provisioner plans

One new provisioner plan:
- `shifter/engine/provisioner/plans/polaris_ctfd_inject.py` — writes `/etc/environment` with `CTFD_URL` and `CTFD_TOKEN` values on A14 via SSM RunCommand. Values come from CMS-side range creation payload (operator enters at event time). Invoked in the setup orchestrator only for instances tagged `role=attacker` in the `polaris_northstorm` scenario.

Every other POLARIS instance reuses the existing `linux_bootstrap.py` plan (hostname + SSH key) unchanged. No DNS zone inject plan needed because IPs are pinned to match baked zones.

### TF range module extension for multi-NIC

`shifter/engine/provisioner/terraform/modules/range/`:
- `variables.tf` — add `additional_subnets = list(string)` to the instance object schema (optional, default `[]`)
- `main.tf` — add `aws_network_interface.secondary` for each (instance, additional_subnet) pair, then `aws_network_interface_attachment.secondary` to bind. Security groups inherited from the target subnet.
- `main.py` in the provisioner (`build_tf_vars`) — pass `additional_subnets` through to TF vars

POLARIS instance specs in the YAML will fill this out — A14 gets `additional_subnets: [corporate, splice-link]`, etc. For non-POLARIS scenarios the field stays empty and nothing changes.

### DHCP option set per range

The range TF module already creates a VPC per range. Add an `aws_vpc_dhcp_options` resource pointing `domain_name_servers = [172.20.0.2]` (the DNS instance's pinned IP), associate to the range VPC. Only active when the scenario has a DNS instance — gate behind a new optional `has_dns` field on the range spec, or detect by checking if any instance has `ami_key: polaris-dns`. Second option is cleaner — no schema change.

## Phase 7 — Verification

1. **Golden range AMI bake integrity**: launch a single instance from each new AMI in a scratch VPC. Confirm the docker container starts automatically, service responds, content is present. 17 smoke boots.
2. **Provisioner dry-run**: hydrate `polaris_northstorm.yaml` through the CMS, call `range_ops` to provision a test range in dev, confirm all 17 instances come up with correct primary + secondary ENIs, DNS resolves, pinned IPs match.
3. **Full flag run in the provisioner-provisioned range**: SSH into A14 from the provisioned range, run the walkthroughs. 38/38 flags captured, proving the scenario + plans work end-to-end.

## Work items / files

**New files (to create):**
- `scripts/polaris-aws-range/main.tf` + `sg.tf` + `variables.tf` + `outputs.tf` + `user_data.sh.tpl`
- `scripts/polaris-aws-range/README.md` — operator runbook
- `scripts/polaris-aws-range/snapshot.sh` — cleanup + `create-image` + SSM registration script
- `shifter/shifter_platform/cms/scenarios/templates/polaris_northstorm.yaml`
- `shifter/engine/provisioner/plans/polaris_ctfd_inject.py`
- `shifter/engine/provisioner/tests/test_polaris_ctfd_inject_plan.py`

**Files to modify:**
- `shifter/cyberscript/schemas/range.py` — add `additional_subnets` to `InstanceSpec`
- `shifter/shifter_platform/cms/scenarios/schema.py` — add `additional_subnets` to `InstanceConfig`
- `shifter/engine/provisioner/terraform/modules/range/variables.tf` — add `additional_subnets` to instance object
- `shifter/engine/provisioner/terraform/modules/range/main.tf` — add secondary ENI resources + DHCP option set
- `shifter/engine/provisioner/main.py` — pass `additional_subnets` through `build_tf_vars`
- `shifter/engine/provisioner/orchestrators/setup_orchestrator.py` — invoke `polaris_ctfd_inject` plan for the Kali role when scenario is `polaris_northstorm`
- `CHANGELOG.md` — new version entry

**No changes to:**
- `scenario-dev/polaris/build/` — the Dockerfiles and entrypoints are consumed by user-data unchanged. **The audit fixes I flagged earlier are not needed** — each instance runs the asset as a Docker container with the same runtime semantics as compose. No bake-time rewrite required.
- `shifter/packer/` — no Packer templates created or modified
- `.github/workflows/packer.yml` — untouched

## Risks and mitigations

1. **AWS API access story** — the plan assumes I can run `terraform` + `aws` CLI against `panw-shifter-dev-workstation` us-east-2. Need to confirm credentials are set up (no SSO per project context). Mitigation: verify `aws sts get-caller-identity` works in the execution environment before starting Phase 1.
2. **S3 bucket for build tarball** — need a bucket the Packer OIDC role can write to and EC2 instance profile can read from. If one doesn't exist, create `shifter-polaris-artifacts` as Phase 1 prerequisite.
3. **Internet egress on bake instances** — bake-time apt/docker installs need outbound internet. Mitigation: NAT gateway on corporate subnet during bake. After AMI creation, instances launched by cyberscript don't need it.
4. **`--network host` collision** — multiple containers on the same EC2 instance would port-conflict, but each asset gets its own EC2 instance so this is moot. Only risk if a single Dockerfile exposes conflicting daemons, which none do.
5. **DNS zone hardcoded IPs survive because of pinning** — the whole story depends on cyberscript pinning `private_ip_address` to compose IPs. If cyberscript can't pin IPs, DNS falls back to a zone inject plan (deferred complexity). Mitigation: verify `aws_instance.private_ip_address` works in the range TF module path.
6. **A7 gitea first-boot flakiness** — known to be slow. On Docker the `sleep 8` still runs at container start. In the hybrid model this survives unchanged. If it flakes on cloud, fix lives in the container, not the AMI.
7. **Time to AMI** — `create-image` takes 5-15 min per instance × 17. Serial = ~3 hours. Parallelize by running all `create-image` calls simultaneously — AWS handles concurrency.
8. **Flag 17 needs A2 Windows DC** — out of scope here. The existing GCP A2 runbook still applies.

## Sequencing

1. Phase 1 TF scaffolding: 2-3 h
2. Phase 2 tarball + S3: 30 min
3. Phase 3 user-data template: 30 min
4. Phase 4 `terraform apply` + verify: 2-4 h (the long pole — live debugging if things break)
5. Phase 5 snapshot: 1 h (most of it is `create-image` wait time)
6. Phase 6 scenario YAML + plan + TF extension: 2-3 h (parallelisable with 4-5 if AMIs aren't ready yet)
7. Phase 7 verification: 1-2 h

Total: 9-14 hours of work across 48 hours. Plenty of slack.

## Out of scope (explicitly)

- GCP images / GDC VM Runtime / qcow2 (other agent's work in `shifter-k8s`)
- Packer templates for POLARIS (replaced by the build-then-AMI approach)
- Walkthrough rewrites for `docker exec` → SSH (post-deploy, not image-side)
- NGFW integration for POLARIS (scenario has `ngfw: false`)
