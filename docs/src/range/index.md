# Range Infrastructure

Stable VPC with ephemeral per-user subnets for XDR/XSIAM demo environments.

## Architecture

```mermaid
graph TB
    subgraph "Range VPC (10.1.0.0/16)"
        IGW[Internet Gateway]
        RT[Public Route Table]

        subgraph "User A Subnet (10.1.1.0/24)"
            ControlA[Control Box]
            KaliA[Kali Box]
            VictimA[Victim Box]
            ControlA -->|MCP| KaliA
            ControlA -->|MCP| VictimA
            KaliA -->|attacks| VictimA
            KaliA -.-x|no egress| ControlA
        end

        subgraph "User B Subnet (10.1.2.0/24)"
            ControlB[Control Box]
            KaliB[Kali Box]
            VictimB[Victim Box]
            ControlB -->|MCP| KaliB
            ControlB -->|MCP| VictimB
            KaliB -->|attacks| VictimB
        end
    end

    UserA((User A)) -->|HTTPS| ControlA
    UserB((User B)) -->|HTTPS| ControlB
    VictimA -->|XDR Agent| XDR[XDR/XSIAM]
    VictimB -->|XDR Agent| XDR
    IGW <--> Internet((Internet))
```

## Per-User Subnet

Each user gets one subnet with three instances:

| Instance | Purpose |
|----------|---------|
| Control Box | Kasm desktop, Cursor/Cline, MCP connections to Kali and Victim |
| Kali Box | Attack tools, MCP-controlled from Control |
| Victim Box | Target with XDR agent, MCP-configured from Control |

## Security Groups

Current implementation (Phase 1 - no Control Box yet):

| SG | Ingress | Egress |
|----|---------|--------|
| Kali | SSH from VPC CIDR, ALL from Victim SG | ALL (0.0.0.0/0) |
| Victim | SSH from VPC CIDR, ALL from Kali SG | ALL (0.0.0.0/0) |

**Traffic Matrix:**

| Source → Dest | Allowed | Purpose |
|---------------|---------|---------|
| Kali → Victim | ✅ All ports/protocols | Attacks, exploits, scans |
| Victim → Kali | ✅ All ports/protocols | Reverse shells, callbacks, C2 |
| VPC → Kali | ✅ SSH (22) | MCP/Chat UI access |
| VPC → Victim | ✅ SSH (22) | MCP configuration |
| Kali → Internet | ✅ All | apt updates, tool downloads |
| Victim → Internet | ✅ All | XDR agent callbacks, updates |

Both instances have unrestricted egress for operational flexibility. Victim-Kali traffic is fully bidirectional to support all attack scenarios including reverse shells.

**Future (Phase 2 - with Control Box):**

| SG | Ingress | Egress |
|----|---------|--------|
| Control | HTTPS from internet | SSH to Kali SG, Victim SG |
| Kali | SSH from Control SG, ALL from Victim SG | ALL to Victim SG only |
| Victim | ALL from Kali SG, SSH from Control SG | HTTPS (agent callbacks) |

In Phase 2, Kali egress will be restricted to Victim only (no internet access from Kali).

## CIDR

| VPC | CIDR |
|-----|------|
| Portal | `10.0.0.0/16` |
| Range | `10.1.0.0/16` |

255 usable `/24` subnets. AWS default 200 subnets/VPC (adjustable to 500).

## Components

### Stable

| Resource | Purpose |
|----------|---------|
| VPC | Network boundary |
| Internet Gateway | Internet access |
| Route Table | 0.0.0.0/0 → IGW |

### Ephemeral (per-user)

| Resource | Purpose |
|----------|---------|
| Subnet | `/24` per user |
| Control/Kali/Victim EC2 | User instances |
| 3x Security Groups | Traffic isolation |

## AMI Prerequisites

### Kali Linux

The Kali box uses a **pre-baked AMI** with pentesting tools already installed:

| Account | AMI | Name |
|---------|-----|------|
| Prod (322748898657) | `ami-01ca670fc1154a1d6` | `shifter-kali-20251212` |
| Dev (878848911818) | `ami-0a9c4fc63c42afb51` | `shifter-kali-20251212` |

**Included:**
- AWS SSM Agent (for management without SSH keys)
- `kali-linux-headless` metapackage (nmap, metasploit, hydra, etc.)
- `hexstrike-ai` (AI-powered MCP pentesting)
- 40GB root volume

**To re-bake the AMI** (e.g., to update packages):

1. Subscribe to [AWS Marketplace - Kali Linux](https://aws.amazon.com/marketplace/pp/prodview-fznsw3f7mq7to) (free)
2. Launch from the marketplace AMI with a 40GB root volume
3. Install SSM agent and packages:
   ```bash
   wget -q https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_amd64/amazon-ssm-agent.deb
   sudo dpkg -i amazon-ssm-agent.deb
   sudo systemctl enable amazon-ssm-agent
   sudo apt update
   sudo apt install -y kali-linux-headless hexstrike-ai
   ```
4. Harden for AMI:
   ```bash
   sudo shred -u /etc/ssh/*_key /etc/ssh/*_key.pub
   rm -f ~/.ssh/authorized_keys
   sudo truncate -s 0 /etc/machine-id
   sudo apt clean
   ```
5. Create AMI: `aws ec2 create-image --instance-id <id> --name "shifter-kali-$(date +%Y%m%d)" --no-reboot`

### Victim

Uses a standard Amazon Linux 2023 AMI (no subscription required).

## Terraform

Stable module: `modules/range/vpc/` (VPC, IGW, route table)

Environment: `environments/prod/range/`

Future: `modules/range/user-subnet/` for ephemeral per-user resources.

## Deployment

`range.yml` workflow:

- PR → `terraform plan`
- Merge to main → `terraform apply`
- Manual dispatch → plan/apply/destroy

State: `s3://shifter-infra-xxx/prod/range/terraform.tfstate`

Variables: `TF_VARS_PROD_RANGE` GitHub secret.
