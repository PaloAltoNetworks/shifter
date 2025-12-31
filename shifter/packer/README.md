# Packer AMI Builds

Reproducible AMI builds for Shifter range instances.

## Prerequisites

- [Packer](https://www.packer.io/downloads) 1.9+
- AWS credentials with EC2/AMI permissions
- AWS Marketplace subscription for Kali Linux (free)

## Available AMIs

| AMI | Template | Description |
|-----|----------|-------------|
| Kali | `kali.pkr.hcl` | Kali Linux with pentesting tools, sshpass, Claude Code |
| Ubuntu | `ubuntu.pkr.hcl` | Ubuntu 22.04 victim with Apache, MySQL, Docker, Claude Code |
| Windows | `windows.pkr.hcl` | Windows Server 2022 with XAMPP, IIS, OpenSSH, Claude Code |

## Quick Start

```bash
# Initialize Packer plugins
packer init .

# Validate template (requires var-file - no defaults)
packer validate -var-file=dev.pkrvars.hcl .

# Build AMI
AWS_PROFILE=panw-shifter-dev-workstation packer build -var-file=dev.pkrvars.hcl .
```

## Build Output

After a successful build:
1. AMI ID is printed to console
2. Manifest written to `{ami_type}-manifest.json` (e.g., `kali-manifest.json`, `ubuntu-manifest.json`)
3. SSM Parameter `/shifter/ami/{ami_type}` updated by GitHub Actions

## Kali AMI Contents

**Base:**
- Kali Linux Rolling
- SSM Agent
- curl, wget, git, jq, htop, tmux, vim

**Security Tools:**
- `kali-linux-headless` metapackage (195+ tools)
- sshpass (non-interactive SSH)

**Development:**
- Python 3, pip, venv
- Node.js, npm
- build-essential

**Claude Code:**
- `@anthropic-ai/claude-code`
- Pre-configured for AWS Bedrock

## Ubuntu AMI Contents

**Base:**
- Ubuntu 22.04 LTS
- SSM Agent

**Services (running on boot):**
- Apache 2.4 with mod_php
- MySQL 8.0
- Docker
- OpenSSH Server
- vsftpd (FTP)

**Services (installed, not running):**
- Samba

**Development:**
- build-essential (gcc, g++, make)
- Python 3, pip, venv
- Node.js 20.x, npm
- Git, curl, nano, netcat

**Claude Code:**
- `@anthropic-ai/claude-code`
- Pre-configured for AWS Bedrock

## Windows AMI Contents

**Base:**
- Windows Server 2022 Datacenter
- SSM Agent
- WinRM enabled for remote management

**Services:**
- XAMPP (Apache 2.4, MySQL, PHP)
- IIS with management tools
- FTP Server
- OpenSSH Server

**Development:**
- Python 3.12
- Node.js 20.x, npm
- Git

**Claude Code:**
- `@anthropic-ai/claude-code`
- Installed to system PATH (`C:\Program Files\nodejs`)
- Pre-configured for AWS Bedrock

**Disabled Services:**
- Print Spooler, Remote Registry, Edge Update, Themes
- Windows Defender (via GPO registry keys for XDR compatibility)

## Build Time

- **Kali:** ~15-20 minutes (kali-linux-headless is large)
- **Ubuntu:** ~5-10 minutes
- **Windows:** ~20-30 minutes (includes sysprep)

## Customization

### Variables

All variables are required (no defaults). Use a var-file:

| File | Use |
|------|-----|
| `dev.pkrvars.hcl` | Dev environment builds |
| `prod.pkrvars.hcl` | Production builds (create as needed) |

Override specific variables with `-var`:

```bash
packer build -var-file=dev.pkrvars.hcl -var="instance_type=t3.xlarge" .
```

### Adding Packages

Edit `scripts/kali/tools.sh` to add packages:

```bash
apt-get install -y my-package
```

## Troubleshooting

### Marketplace subscription error

```
Error: You are not authorized to perform this operation
```

Subscribe to Kali Linux on AWS Marketplace (free):
https://aws.amazon.com/marketplace/pp/prodview-fznsw3f7mq7to

### SSH connection timeout

Ensure:
- Security group allows SSH from your IP
- Instance has public IP (default VPC) or you're using a bastion

### Build fails partway through

Check the EC2 console - Packer may leave a running instance. Terminate it manually if needed.

### Windows WinRM connection timeout

Ensure:
- Security group allows WinRM (port 5985) from your IP
- Instance has public IP
- User data script ran successfully (check EC2 console logs)

### Windows sysprep fails

If sysprep fails:
- Check EC2Launch logs at `C:\ProgramData\Amazon\EC2Launch\log\`
- Ensure all services are installed before sysprep runs
- Verify EC2Launch v2 is present at `C:\Program Files\Amazon\EC2Launch\`
