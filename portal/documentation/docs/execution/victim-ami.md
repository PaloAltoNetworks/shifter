# Victim AMI

Pre-baked victim images with vulnerable services and Claude Code.

## Ubuntu Victim

### What's In It

- Ubuntu 22.04
- Claude Code 2.x (configured for Bedrock)

**Services (running on boot):**
- Apache 2.4 with mod_php
- MySQL 8.0
- Docker
- OpenSSH Server
- vsftpd (FTP)

**Services (installed, not running):**
- Samba

**Development Tools:**
- build-essential (gcc, g++, make)
- Python 3.10
- Node.js 20.x
- Git, curl, nano, netcat

### Building with Packer

```bash
cd packer
packer init .
packer build -var-file=dev.pkrvars.hcl ubuntu.pkr.hcl
```

Or use the GitHub Actions workflow "Packer AMI Build (Dev)" and select `ubuntu`.

## Windows Victim

### What's In It

- Windows Server 2022 Datacenter
- Claude Code (configured for Bedrock, installed to system path)
- XAMPP (Apache, MySQL, PHP)
- IIS, FTP Server, OpenSSH Server
- Python, Node.js, Git

### Baking Process

Windows AMIs are built using Packer. See `packer/windows.pkr.hcl`.

**Build:**
```bash
cd packer
packer init .
packer build -var-file=dev.pkrvars.hcl windows.pkr.hcl
```

**Key considerations:**

1. **Claude Code must be in a system path** - npm global prefix set to `C:\Program Files\nodejs` before install
2. **Env vars at Machine level** - `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION=us-east-2`
3. **Disable services that slow boot or conflict with XDR:**
   - Print Spooler, Remote Registry, Edge Update, Themes
   - Windows Defender (via Group Policy registry keys)
4. **Run EC2Launch sysprep with shutdown** - `& "C:\Program Files\Amazon\EC2Launch\EC2Launch.exe" sysprep --shutdown`

**Provisioning scripts** (in order):
- `scripts/windows/base.ps1` - SSM Agent, firewall, WinRM
- `scripts/windows/services.ps1` - XAMPP, IIS, FTP, OpenSSH
- `scripts/windows/tools.ps1` - Python, Node.js, Git
- `scripts/windows/claude-code.ps1` - Claude Code for Bedrock
- `scripts/windows/sysprep.ps1` - Cleanup and sysprep (runs last)

### SSH for Terminal UI

Windows uses OpenSSH Server. User data must:
- Start sshd service
- Configure `C:\ProgramData\ssh\administrators_authorized_keys` with public key
- Set proper ACLs on the authorized_keys file

Django consumer uses `Administrator` as SSH username for Windows.

## Domain Member Mode

Windows victims can join an AD domain when a DC is present in the range.

**Behavior:**
- Reads DC config from SSM Parameter Store (retries until DC ready)
- Sets DNS to DC IP
- Joins domain with domain admin credentials
- Reboots, then installs XDR agent

Domain members use a separate user data template. Standalone Windows victims use the standard template.

## Why Pre-Bake

XDR/XSIAM needs real services to detect attacks against. Pre-baking ensures consistent victim environments across all ranges. Claude Code enables agentic attack and defense workflows from both Kali and victim.

## Provisioning Flow

1. Portal triggers provisioner with range config
2. Provisioner reads `VICTIM_AMI_ID` or `WINDOWS_AMI_ID` from env based on agent OS
3. EC2 launched from pre-baked AMI
4. User data runs on boot:
   - Sets hostname
   - Configures SSH keys
   - Downloads XDR agent from S3 (presigned URL)
   - Installs XDR agent

## XDR Agent Installation

The XDR agent is NOT in the AMI. Users upload their agent installer to S3 via the portal. At boot, user data downloads and installs it. This allows each range to connect to the user's own XSIAM tenant.

## Config

AMI IDs are managed via SSM Parameter Store:

| SSM Parameter | Description | Env Var |
|---------------|-------------|---------|
| `/shifter/ami/ubuntu` | Ubuntu victim AMI | `VICTIM_AMI_ID` |
| `/shifter/ami/windows` | Windows victim AMI | `WINDOWS_AMI_ID` |
| `/shifter/ami/kali` | Kali attack AMI | `KALI_AMI_ID` |

GitHub Actions workflows update these parameters after successful builds.
