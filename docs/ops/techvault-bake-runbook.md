# TechVault Golden AMI Bake Runbook

Region: `us-east-2` (all resources)
Scenario: [`cms/scenarios/templates/techvault.yaml`](../../shifter/shifter_platform/cms/scenarios/templates/techvault.yaml)
User docs: `documentation/docs/scenarios/techvault.md`
Precedent: this mirrors the POLARIS bake pattern. See
[`docs/architecture/polaris-scenario-bake-preflight-618.md`](../architecture/polaris-scenario-bake-preflight-618.md).

This is the operator procedure for producing the **TechVault golden AMI**: one
Ubuntu host running the APTL `techvault-operational` Docker Compose stack (~31
containers) plus the VS Code + Claude Code + MCP seat, baked so a range launch
only boots it, never rebuilds or reprovisions it.

## Why pre-bake

The stack is ~14 locally built images plus ~23 pulled images and takes tens of
minutes to build and converge. Baking it once means range launch is a boot plus
the containers' own `restart: unless-stopped` auto-start (seconds to minutes),
with per-range work limited to injecting SSH/RDP creds and the Bedrock shard.
**Do not run `aptl lab start` at range launch; that re-runs provisioning
(cert-gen, seeding, ACES realization). Range launch = boot plus auto-start only.**

## Prerequisites

- AWS creds for the target account (`us-east-2`).
- The pinned wheel version. Bake is tied to a version. Current: **`aptl-labs==4.1.2`**.
- Base image: Canonical Ubuntu 24.04 (`/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id`).
- For the **runtime agent** (not the bake): AWS Bedrock model access must be
  granted in the account for the `us.anthropic.claude-*` inference profiles the
  seat uses. Invoking without the grant fails with an AWS Marketplace
  subscribe error. This is an account admin action, done once.

## Isolated bake environment

Build in a **standalone VPC** (no peering to the portal/engine VPCs) so the bake
cannot touch a live deployment:

- VPC `10.99.0.0/16`, one public subnet, IGW plus default route, SG with no
  inbound plus egress-all.
- IAM role plus instance profile with `AmazonSSMManagedInstanceCore` (drive the
  host over SSM RunCommand: no SSH keys, no inbound).
- Tag everything `Project=techvault-bake` for clean teardown.

Launch the bake host: Ubuntu 24.04, **r5.2xlarge**, ~**100 GB** gp3 root,
the SSM instance profile, IMDSv2 required.

## Bake procedure

Run everything through SSM against the bake host.

### 1. Toolchain

```bash
curl -fsSL https://get.docker.com | sh && systemctl enable --now docker
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs
npm install -g @anthropic-ai/claude-code
apt-get install -y pipx jq
```

### 2. Stand up the full stack (as the `ubuntu` user, uid 1000)

> **Gotcha (root versus uid 1000):** aptl writes the Wazuh TLS certs `0400` owned
> by the running user. The `wazuh-indexer` / `wazuh-dashboard` containers run as
> **uid 1000**. Run the lab as **`ubuntu` (uid 1000)** so those certs are
> readable. Running the whole thing as root leaves the indexer unhealthy
> (`Unable to read .../root-ca.pem`).

```bash
sudo -u ubuntu env HOME=/home/ubuntu pipx install "aptl-labs==4.1.2"
sudo -u ubuntu env HOME=/home/ubuntu bash -c '
  cd /home/ubuntu && ~/.local/bin/aptl lab init techvault && cd techvault
  # Gotcha: the default aptl.json disables enterprise/soc/mail/fileshare/dns.
  # Enable all container groups for the full stack. (--scenario alone does NOT.)
  jq ".containers = {wazuh:true,victim:true,kali:true,reverse:true,enterprise:true,soc:true,mail:true,fileshare:true,dns:true}" aptl.json > t && mv t aptl.json
  ~/.local/bin/aptl lab start
  [ -f .mcp.json.example ] && cp -n .mcp.json.example .mcp.json
'
```

Expect **31 running `aptl-*` containers** (`aptl lab status`). Note:
`techvault-operational` is the public startup contract and deliberately
**excludes** the `mail` and `reverse` containers even with those groups enabled.
31 containers is the full operational stack.

### 3. Seat: VS Code over RDP (the Shifter access pattern)

```bash
apt-get install -y --no-install-recommends xfce4 xfce4-terminal xfce4-goodies dbus-x11 xorgxrdp xrdp
# VS Code Desktop from the Microsoft apt repo (real VS Code, not code-server)
wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list
apt-get update && apt-get install -y code
echo "xfce4-session" > /home/ubuntu/.xsession && chown ubuntu:ubuntu /home/ubuntu/.xsession
adduser xrdp ssl-cert
systemctl enable xrdp
# Auto-open the lab in VS Code on RDP login (optional UX):
#   /home/ubuntu/.config/autostart/code.desktop -> Exec=code --no-sandbox /home/ubuntu/techvault
```

Access is **Guacamole RDP** into this XFCE desktop (`os_type: kali` in the
template selects the RDP path). The seat user stays `ubuntu`; the range bootstrap
records `ssh_username=ubuntu` and sets the per-range RDP password.

### 4. Quiesce and image (leave the stack RUNNING)

Do **not** `aptl lab stop`. Kill any transient test processes, then create the
image with the stack running so the containers auto-start on the next boot:

```bash
aws ec2 create-image --instance-id <bake-host> --name "techvault-golden-4.1.2-ide-<date>" \
  --description "TechVault techvault-operational + VS Code seat, aptl-labs 4.1.2" \
  --tag-specifications 'ResourceType=image,Tags=[{Key=Project,Value=techvault-bake},{Key=aptl_version,Value=4.1.2}]'
```

`create-image` (default, no `--no-reboot`) stops the instance for a consistent
snapshot; on boot docker restarts the `unless-stopped`/`always` containers.

### 5. Golden verify (non-negotiable)

Launch a **fresh instance from the new AMI**, let docker auto-start the stack, and
confirm before trusting it:

- `aptl lab status` shows all containers running/healthy (Wazuh indexer, TheHive,
  Cassandra, ES take a couple minutes).
- Purple-team loop: SQLi from Kali produces Wazuh `web_attack` alerts.
- MCP smoke: `aptl-red` `kali_info` / `kali_run_command` over JSON-RPC.

Use APTL's own protocol: `docs/components/mcp-smoke-test-protocol.md` in the aptl
repo (manual-fallback plus agent-MCP sections).

### 6. Register the AMI

Set the per-environment SSM parameter (this is how the provisioner resolves it;
see `shifter/engine/provisioner/provisioner_ami.py`). It is **additive**; it
does not touch the base `/shifter/ami/{kali,ubuntu,windows,dc}` params:

```bash
aws ssm put-parameter --name /shifter/ami/techvault --type String \
  --value <ami-id> --description "TechVault golden AMI (aptl-labs 4.1.2)"
```

The repo references the AMI by **key** (`ami_key: techvault` in the scenario
template), never by id; nothing else to commit.

## Sizing notes

The full stack idles at ~9 GB / 62 GB RAM and ~4% CPU on `r5.2xlarge`; an nmap
sweep from Kali stays under load 0.3. The size is comfortable with headroom for
participant work plus Claude Code (which is remote compute via Bedrock).

## Automated pipeline

The reproducible path is the `workflow_dispatch` workflow
`.github/workflows/techvault-scenario-bake.yml` ("TechVault Scenario Bake"),
which automates the manual steps above: it stands up the stack, installs the
VS Code seat, images the running stack, golden-verifies, and updates
`/shifter/ami/techvault`. It follows the `workflow_dispatch`-only bake boundary
from `docs/architecture/polaris-scenario-bake-preflight-618.md` (never wired to
push, pull_request, or schedule).

The workflow is self-contained: it drives the bake inline over SSM RunCommand
and has no separate `scripts/` bake range. The operator supplies the isolated
bake subnet, security group, and SSM instance profile (plus the pinned
`aptl_version`) as inputs. Run this workflow for a normal rebake; the manual
steps above are the reference for what it does and for debugging.
