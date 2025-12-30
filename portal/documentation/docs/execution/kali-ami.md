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

## Building the AMI

AMI is built with Packer. See [`packer/README.md`](/packer/README.md).

```bash
cd packer
packer init .
packer build kali.pkr.hcl
```

Or trigger via GitHub Actions: **Actions > Packer AMI Build > Run workflow**

## Provisioning Flow

1. Portal triggers provisioner with range config
2. Provisioner reads `KALI_AMI_ID` from env
3. EC2 launched from pre-baked AMI
4. User data runs on boot:
   - Sets hostname
   - Configures SSH keys

## Config

| Env Var | Value |
|---------|-------|
| `KALI_AMI_ID` | Set in terraform.tfvars per environment |

## Marketplace Subscription

Base image requires AWS Marketplace subscription (free):
[AWS Marketplace - Kali Linux](https://aws.amazon.com/marketplace/pp/prodview-fznsw3f7mq7to)
