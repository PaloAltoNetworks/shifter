# Kali AMI

Pre-baked Kali Linux with pentesting tools and Claude Code.

## What's In It

- Kali Linux Rolling
- Claude Code (configured for Bedrock)
- SSM Agent

**Metapackages:**
- `kali-linux-headless` — 195 tools including:

| Category | Tools |
|----------|-------|
| Exploitation | Metasploit Framework |
| Scanning | Nmap, Nikto, dirb, gobuster, amass, dnsrecon |
| Web Testing | Burp Suite, sqlmap, commix, davtest |
| Password | John, Hashcat, Hydra, crunch, cewl |
| Wireless | Aircrack-ng, bully |
| AD/Windows | certipy-ad, enum4linux, chntpw |
| Network | Wireshark libs, arp-scan, dns2tcp |
| SSH | sshpass (non-interactive password auth) |

**Development:**
- Python 3, pip, venv
- Node.js, npm
- build-essential, git, curl, wget

## Why Pre-Bake

The marketplace Kali AMI is minimal. Pre-baking adds:
- SSM agent (not in Kali repos by default)
- Pentesting tools via kali-linux-headless
- sshpass for Claude Code automated SSH workflows
- Claude Code for agentic pentesting workflows

## AMI Management

AMI IDs are stored in SSM Parameter Store at `/shifter/ami/kali` in each AWS account. Terraform reads these values via data sources - no manual tfvars updates needed.

### Build in Dev

Build a new Kali AMI in the dev account:

```bash
./scripts/ami.sh -b kali
```

This triggers the `packer.yml` workflow which:
1. Runs Packer build using `dev.pkrvars.hcl`
2. Creates AMI in dev account (us-east-2)
3. Updates `/shifter/ami/kali` SSM parameter in dev

### Promote to Prod

After testing in dev, promote to prod:

```bash
./scripts/ami.sh -p kali
```

This triggers the `packer-promote.yml` workflow which:
1. Reads dev AMI ID from SSM
2. Shares AMI with prod account
3. Copies AMI to prod account
4. Updates `/shifter/ami/kali` SSM parameter in prod

### Manual Build

For local testing or debugging:

```bash
cd packer
packer init .
packer validate -var-file=dev.pkrvars.hcl kali.pkr.hcl
packer build -var-file=dev.pkrvars.hcl kali.pkr.hcl
```

## Provisioning Flow

1. Portal triggers provisioner with range config
2. Terraform reads AMI ID from SSM Parameter Store
3. EC2 launched from pre-baked AMI
4. User data runs on boot:
   - Sets hostname
   - Configures SSH keys

## Config

| Parameter | Location |
|-----------|----------|
| AMI ID | SSM: `/shifter/ami/kali` |
| Instance type | `terraform.tfvars` per environment |

## Marketplace Subscription

Base image requires AWS Marketplace subscription (free):
[AWS Marketplace - Kali Linux](https://aws.amazon.com/marketplace/pp/prodview-fznsw3f7mq7to)
