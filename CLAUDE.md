# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Shifter** is a fork of APTL (Advanced Purple Team Lab) adapted for PANW SecOps Domain Consultants. While APTL is a local Docker-based purple team lab with Wazuh SIEM, Shifter is a cloud-hosted XDR/XSIAM demo and attack testing environment deployed to AWS.

### Target Users

PANW SecOps Domain Consultants who need to:
- Run demos in XDR or XSIAM for customers
- Test different attack scenarios against XDR-protected victims
- Cannot install tools locally on their work Windows laptops

### Key Difference from APTL

| Aspect | APTL | Shifter |
|--------|------|---------|
| Deployment | Local Docker | AWS CloudFormation |
| SIEM | Wazuh (self-hosted) | XDR/XSIAM (DC's tenant) |
| Workstation | User's laptop | Windows EC2 via RDP |
| Target Users | Security researchers | PANW Domain Consultants |
| Setup | `./start-lab.sh` | AWS Console (zero install) |

---

## Shifter Architecture

### High-Level Design

```
DC's Windows Laptop (browser + RDP client only)
         │
         │ RDP (3389)
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  AWS VPC: 10.0.0.0/16                                           │
│  Subnet: 10.0.1.0/24                                            │
│                                                                 │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐    │
│  │   Windows     │    │     Kali      │    │    Victim     │    │
│  │  Workstation  │    │   (headless)  │    │    (Linux)    │    │
│  │  t3.xlarge    │    │   t3.medium   │    │   t3.medium   │    │
│  │               │    │               │    │               │    │
│  │  • Cursor IDE │───▶│  • Kali tools │───▶│  • XDR agent  │    │
│  │  • mcp-kali   │SSH │  • SSH server │    │  • Vuln apps  │    │
│  │  • mcp-victim │───▶│               │    │  • SSH server │    │
│  │  • Node.js    │SSH │               │    │               │    │
│  └───────┬───────┘    └───────────────┘    └───────┬───────┘    │
│          │                                         │            │
│          │ Elastic IP (stable RDP)                 │ XDR Agent  │
│          ▼                                         ▼            │
└──────────────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
                                            DC's XSIAM Tenant
                                            (alerts, detections)
```

### Why This Architecture

1. **Windows Workstation + Headless Kali** (vs Kali with GUI):
   - Cheaper: ~$0.25/hr vs ~$0.57/hr (no GPU instance needed)
   - Familiar: DCs know Windows RDP (vs NICE DCV on Linux)
   - Same pattern as APTL: Cursor + MCPs controlling remote boxes via SSH
   - Realistic: Operator controlling attack infrastructure remotely

2. **CloudFormation** (vs Terraform):
   - Zero install: DCs deploy from AWS Console (browser only)
   - No tooling on locked-down laptops required
   - One-click stack deletion for cleanup

3. **Reuses APTL MCP Architecture**:
   - Same `aptl-mcp-common` library
   - Config-driven MCP servers (just change JSON target)
   - Minimal new code required

---

## Components

### 1. Windows Workstation (t3.xlarge)

**Purpose**: DC's cloud desktop with AI-assisted attack control

**Specifications**:
- Instance: t3.xlarge (4 vCPU, 16GB RAM)
- OS: Windows Server 2022
- Access: RDP on port 3389 (restricted to DC's IP)

**Installed Software** (via user_data PowerShell):
- Cursor IDE (AI coding assistant)
- Node.js 20.x LTS
- Git
- MCP servers (mcp-kali, mcp-victim)
- OpenSSH client

**MCP Configuration** (`C:\Users\Administrator\.cursor\mcp.json`):
```json
{
    "mcpServers": {
    "kali": {
      "command": "node",
      "args": ["C:\\Shifter\\mcp\\mcp-kali\\build\\index.js"]
    },
    "victim": {
            "command": "node",
      "args": ["C:\\Shifter\\mcp\\mcp-victim\\build\\index.js"]
        }
    }
}
```

### 2. Kali Attack Box (t3.medium)

**Purpose**: Headless Kali Linux for attack execution

**Specifications**:
- Instance: t3.medium (2 vCPU, 4GB RAM)
- OS: Kali Linux (AWS Marketplace AMI)
- Access: SSH only (from Windows Workstation)

**Installed Software** (via user_data bash):
- kali-linux-headless metapackage
- Common attack tools (nmap, metasploit, hydra, sqlmap, etc.)
- SSH server configured for key-only auth

**MCP Tools Available**:
- `kali_info` - Get Kali instance information
- `kali_run_command` - Execute single command
- `kali_interactive_session` - Persistent SSH session
- `kali_background_session` - Long-running processes (msfconsole, etc.)
- Session management tools (list, close, get output)

### 3. Victim Linux (t3.medium)

**Purpose**: Target system with XDR/XSIAM agent for demo scenarios

**Specifications**:
- Instance: t3.medium (2 vCPU, 4GB RAM)
- OS: Amazon Linux 2023
- Access: SSH only (from Windows Workstation or Kali)

**Installed Software** (via user_data bash):
- XDR/XSIAM agent (downloaded from DC-provided URL)
- Apache + PHP (vulnerable web services)
- SSH server
- Basic network tools

**MCP Tools Available**:
- `victim_info` - Get victim instance information
- `victim_run_command` - Execute single command
- `victim_interactive_session` - Persistent SSH session
- Session management tools

### 4. Networking

**VPC Configuration**:
- VPC CIDR: 10.0.0.0/16
- Public Subnet: 10.0.1.0/24
- Internet Gateway for outbound access

**Security Group (shared by all instances)**:

| Direction | Port | Protocol | Source | Purpose |
|-----------|------|----------|--------|---------|
| Inbound | 3389 | TCP | DC's IP | RDP to Windows |
| Inbound | 22 | TCP | DC's IP | SSH backup |
| Inbound | ALL | ALL | Self (SG) | Inter-instance traffic |
| Outbound | ALL | ALL | 0.0.0.0/0 | Internet access |

The self-referencing rule enables unrestricted Kali ↔ Victim traffic for attack scenarios (any port, any protocol).

### 5. Auto-Shutdown (Cost Control)

**Lambda + EventBridge**:
- EventBridge rule triggers Lambda at configured time (default: 7pm UTC)
- Lambda stops all three EC2 instances
- DC can restart from AWS Console next day
- Prevents overnight/weekend charges

---

## CloudFormation Parameters

```yaml
Parameters:
  YourIPCIDR:
    Type: String
    Description: "Your IP in CIDR format (e.g., 203.0.113.50/32)"
    
  KeyPairName:
    Type: AWS::EC2::KeyPair::KeyName
    Description: "Existing EC2 key pair for SSH access"
    
  AdminPassword:
    Type: String
    NoEcho: true
    Description: "Password for Windows Administrator account"
    
  XDRAgentURL:
    Type: String
    Description: "URL to download XDR/XSIAM agent (S3 presigned or public)"
    Default: ""
    
  ShutdownTimeUTC:
    Type: String
    Default: "19:00"
    Description: "Daily auto-shutdown time in UTC (HH:MM)"
```

---

## User Experience

### Deployment (One-Time)

1. DC logs into AWS Console
2. CloudFormation → Create Stack → Upload template (or from S3 URL)
3. Fill in parameters:
   - Their public IP (for RDP/SSH access)
   - Key pair name (create one if needed)
   - Windows admin password
   - XDR agent download URL (from their XSIAM tenant)
4. Create stack → Wait ~15 minutes
5. Get outputs: Windows IP, Kali internal IP, Victim internal IP

### Daily Usage

1. Start instances from EC2 Console (if stopped by auto-shutdown)
2. RDP to Windows Workstation
3. Open Cursor IDE
4. Use AI to configure attack scenarios:
   > "Set up a PHP command injection vulnerability on the victim"
5. Use AI to run attacks from Kali:
   > "From Kali, scan the victim and exploit the web vulnerability"
6. Show XDR/XSIAM console to customer (detections)
7. Instances auto-stop at 7pm UTC

### Cleanup

1. CloudFormation → Delete Stack
2. All resources removed (VPC, instances, security groups, etc.)

---

## File Structure (Planned)

```
shifter/
├── CLAUDE.md                          # This file
├── README.md                          # Updated for Shifter
├── cloudformation/
│   ├── shifter-stack.yaml             # Main CloudFormation template
│   └── shifter-stack-params.json      # Example parameters
├── scripts/
│   ├── windows-user-data.ps1          # Windows provisioning
│   ├── kali-user-data.sh              # Kali provisioning
│   └── victim-user-data.sh            # Victim provisioning
├── mcp/
│   ├── aptl-mcp-common/               # (existing) Shared MCP library
│   ├── mcp-kali/                      # (new) Kali MCP for Shifter
│   │   ├── src/index.ts
│   │   ├── aws-lab-config.json        # Points to Kali EC2
│   │   └── package.json
│   └── mcp-victim/                    # (new) Victim MCP for Shifter
│       ├── src/index.ts
│       ├── aws-lab-config.json        # Points to Victim EC2
│       └── package.json
├── lambda/
│   └── auto-shutdown/
│       ├── index.py                   # Lambda function
│       └── requirements.txt
├── docs/
│   └── shifter-setup-guide.md         # Step-by-step with screenshots
└── archive/                           # Old APTL Docker content (reference)
```

---

## Implementation Plan

### Phase 1: Repository Cleanup

**Goal**: Remove all APTL Docker/Wazuh code that won't be used, leaving only what Shifter needs.

#### Files/Directories to DELETE

| Path | Reason |
|------|--------|
| `docker-compose.yml` | Docker lab definition - not used |
| `start-lab.sh` | Docker startup script - not used |
| `generate-indexer-certs.yml` | Wazuh certificate generation - not used |
| `aptl.json` | Docker lab configuration - not used |
| `mkdocs.yml` | APTL documentation site config - not used |
| `CHANGELOG.md` | APTL changelog - start fresh |
| `config/` | **Entire directory** - Wazuh configuration |
| `config/certs.yml` | Wazuh cert config |
| `config/wazuh_cluster/` | Wazuh manager config |
| `config/wazuh_dashboard/` | Wazuh dashboard config |
| `config/wazuh_indexer/` | Wazuh indexer config |
| `containers/` | **Entire directory** - Docker container definitions |
| `containers/gaming-api/` | Game API container |
| `containers/kali/` | Docker Kali (will use AWS AMI instead) |
| `containers/minecraft-server/` | Minecraft container |
| `containers/minetest-client/` | Minetest client container |
| `containers/minetest-server/` | Minetest server container |
| `containers/reverse/` | Reverse engineering container |
| `containers/victim/` | Docker victim (will use AWS AMI instead) |
| `docs/` | **Entire directory** - APTL-specific docs |
| `docs/architecture/` | Docker architecture docs |
| `docs/components/` | Docker component docs |
| `docs/containers/` | Container docs |
| `docs/deployment.md` | Docker deployment |
| `docs/getting-started/` | Docker getting started |
| `docs/index.md` | APTL doc index |
| `docs/troubleshooting/` | Docker troubleshooting |
| `assets/` | **Entire directory** - APTL screenshots/docs |
| `assets/docs/` | APTL PDF docs |
| `assets/images/` | APTL screenshots |
| `archive/` | **Entire directory** - old roadmap docs |
| `scripts/generate-ssh-keys.sh` | Docker-specific key generation |
| `vms/` | **Entire directory** - Proxmox Terraform (not AWS) |
| `vms/windows/` | Proxmox Windows VM |
| `mcp/mcp-wazuh/` | Wazuh API MCP - replaced by XSIAM |
| `mcp/mcp-minetest-client/` | Game-specific MCP - not needed |
| `mcp/mcp-minetest-server/` | Game-specific MCP - not needed |
| `mcp/mcp-reverse/` | Container-specific MCP - not needed |
| `mcp/mcp-windows-re/` | Hardcoded IP config - needs rewrite |
| `mcp/build-all-mcps.sh` | References removed MCPs |
| `mcp/package-lock.json` | Root lock file - MCPs have their own |

#### Files/Directories to KEEP

| Path | Reason |
|------|--------|
| `CLAUDE.md` | This file - project guidance |
| `LICENSE` | MIT license - required |
| `README.md` | Will rewrite for Shifter |
| `mcp/aptl-mcp-common/` | **Core MCP library** - directly reused |
| `mcp/mcp-red/` | **Example MCP server** - reference implementation |
| `ctf_scenarios/` | **Attack scenarios** - deployable on victim |
| `infra/windows_re/` | **Reference only** - Terraform patterns for CloudFormation |

#### Cleanup Commands

```bash
# Run from repo root

# Delete Docker/Wazuh files
rm -f docker-compose.yml
rm -f start-lab.sh
rm -f generate-indexer-certs.yml
rm -f aptl.json
rm -f mkdocs.yml
rm -f CHANGELOG.md

# Delete Docker-specific directories
rm -rf config/
rm -rf containers/
rm -rf docs/
rm -rf assets/
rm -rf archive/
rm -rf vms/

# Delete scripts directory (only has Docker-specific script)
rm -rf scripts/

# Delete unused MCP servers (keep mcp-red as example)
rm -rf mcp/mcp-wazuh/
rm -rf mcp/mcp-minetest-client/
rm -rf mcp/mcp-minetest-server/
rm -rf mcp/mcp-reverse/
rm -rf mcp/mcp-windows-re/
rm -f mcp/build-all-mcps.sh
rm -f mcp/package-lock.json
```

#### Post-Cleanup Structure

```
shifter/
├── CLAUDE.md                    # Project guidance (this file)
├── LICENSE                      # MIT license
├── README.md                    # To be rewritten
├── ctf_scenarios/               # Attack scenarios for victim
│   ├── basic/
│   ├── intermediate/
│   ├── hard/
│   ├── README.md
│   ├── scenarios.json
│   └── SCHEMA.md
├── infra/                       # Reference patterns
│   └── windows_re/              # Terraform → CloudFormation reference
│       ├── main.tf
│       ├── outputs.tf
│       ├── README.md
│       ├── terraform.tfvars.example
│       ├── user_data.ps1
│       └── variables.tf
└── mcp/
    ├── aptl-mcp-common/         # Core MCP library
    │   ├── src/
    │   ├── tests/
    │   ├── package.json
    │   ├── package-lock.json
    │   ├── tsconfig.json
    │   └── vitest.config.ts
    └── mcp-red/                 # Example MCP server implementation
        ├── src/index.ts
        ├── docker-lab-config.json
        ├── package.json
        └── tsconfig.json
```

#### Verification After Cleanup

```bash
# Verify structure
find . -type f -name "*.yml" | grep -v node_modules  # Should only show ctf_scenarios files
find . -type f -name "docker*"                        # Should return nothing
find . -type d -name "wazuh*"                         # Should return nothing
ls mcp/                                               # Should show aptl-mcp-common/ and mcp-red/

# Verify MCP common still builds
cd mcp/aptl-mcp-common && npm install && npm run build && npm test

# Verify mcp-red still builds
cd mcp/mcp-red && npm install && npm run build
```

---

### Phase 2: Build Shifter Infrastructure

**Goal**: Create AWS CloudFormation stack and new MCP servers

1. **CloudFormation Template** (`cloudformation/shifter-stack.yaml`)
   - VPC, subnet, internet gateway, route table
   - Security group with self-referencing rule
   - Three EC2 instances (Windows, Kali, Victim)
   - Elastic IP for Windows
   - IAM role for instances
   - Lambda + EventBridge for auto-shutdown

2. **User Data Scripts** (`scripts/`)
   - `windows-user-data.ps1`: RDP, Cursor, Node.js, Git, MCP setup
   - `kali-user-data.sh`: SSH, kali-linux-headless, tools
   - `victim-user-data.sh`: SSH, Apache, PHP, XDR agent install

3. **MCP Servers** (`mcp/`)
   - `mcp-kali/`: New MCP with config pointing to Kali private IP
   - `mcp-victim/`: New MCP with config pointing to Victim private IP
   - Both reuse `aptl-mcp-common` (no changes to common needed)

4. **Documentation**
   - Rewrite `README.md` for Shifter
   - Create `docs/setup-guide.md` with screenshots

### Phase 3: Enhanced Scenarios (Future)

- Pre-configured vulnerable applications (DVWA, Juice Shop)
- Windows victim option (for EDR demos)
- CTF scenario deployment scripts adapted for AWS
- Multiple victim instances option

### Phase 4: Full Purple Team (Future)

- XSIAM API MCP (query alerts, search XQL)
- Complete attack → detection → investigation loop
- DC provides XSIAM API credentials
- AI can verify detections after attacks

---

## Development Commands

### Building MCP Common Library

```bash
cd mcp/aptl-mcp-common && npm install && npm run build
```

### Testing MCP Common

```bash
cd mcp/aptl-mcp-common && npm test
```

### Building New MCP Servers (After Phase 2)

```bash
# Build Kali MCP
cd mcp/mcp-kali && npm install && npm run build

# Build Victim MCP  
cd mcp/mcp-victim && npm install && npm run build

# Test with MCP Inspector
cd mcp/mcp-kali
npx @modelcontextprotocol/inspector build/index.js
```

### CloudFormation Deployment (After Phase 2)

```bash
# Validate template
aws cloudformation validate-template --template-body file://cloudformation/shifter-stack.yaml

# Create stack
aws cloudformation create-stack \
  --stack-name shifter-test \
  --template-body file://cloudformation/shifter-stack.yaml \
  --parameters file://cloudformation/shifter-stack-params.json \
  --capabilities CAPABILITY_IAM

# Delete stack
aws cloudformation delete-stack --stack-name shifter-test
```

---

## Reference Code (infra/windows_re/)

The `infra/windows_re/` directory contains Terraform patterns useful as reference for building CloudFormation:

| Terraform File | CloudFormation Equivalent |
|----------------|---------------------------|
| `main.tf` (VPC, SG, EC2) | `AWS::EC2::VPC`, `AWS::EC2::SecurityGroup`, `AWS::EC2::Instance` |
| `user_data.ps1` | Will adapt for Windows workstation provisioning |
| `variables.tf` | CloudFormation Parameters |
| `outputs.tf` | CloudFormation Outputs |

This directory will be removed after CloudFormation is built, or kept as reference.

---

## Security Considerations

1. **IP Whitelisting**: RDP/SSH only from DC's IP
2. **Key-Only SSH**: Password auth disabled on all Linux instances
3. **No Public Access**: Kali and Victim have no inbound from internet
4. **Auto-Shutdown**: Reduces attack surface when not in use
5. **Stack Deletion**: Clean removal of all resources

---

## Cost Estimate

| Resource | Type | Hourly | 8hr/day |
|----------|------|--------|---------|
| Windows Workstation | t3.xlarge | $0.1664 | $1.33 |
| Kali | t3.medium | $0.0416 | $0.33 |
| Victim | t3.medium | $0.0416 | $0.33 |
| **Total** | | **$0.2496** | **$2.00** |

With auto-shutdown, a DC using the lab 8 hours/day costs ~$2/day or ~$40/month.

---

## Git Workflow

### Branch Strategy

- `main` - Stable Shifter releases
- `develop` - Integration branch
- `feature/*` - New features

### Commit Protocol

**NEVER make commits without explicit user permission:**
1. ALWAYS ask before creating commits
2. Show user what will be committed first
3. Let user review changes before committing
4. Only commit when user explicitly requests it
5. NEVER include Claude attribution or co-authored-by tags

---

## What NOT To Do

Per project rules:
- Do NOT add features not explicitly requested
- Do NOT create documentation for unbuilt features
- Do NOT assume requirements - ask for clarification
- Do NOT add "helpful" extras beyond the request
- Keep responses focused and concise
- Write for technical audience (no marketing language)
