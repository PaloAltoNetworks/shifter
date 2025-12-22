# Victim AMI

Pre-baked Ubuntu victim with vulnerable services and Claude Code.

## What's In It

- Ubuntu 22.04
- Claude Code (configured for Bedrock)
- Vulnerable services: Apache, MySQL, Docker, PHP, Samba, FTP

## Why Pre-Bake

XDR/XSIAM needs real services to detect attacks against. Pre-baking ensures consistent victim environments across all ranges. Claude Code enables agentic attack and defense workflows from both Kali and victim.

## Provisioning Flow

1. Portal triggers provisioner with range config
2. Provisioner reads `VICTIM_AMI_ID` from env
3. EC2 launched from pre-baked AMI
4. User data runs on boot:
   - Sets hostname
   - Configures SSH keys
   - Downloads XDR agent from S3 (presigned URL)
   - Installs XDR agent

## XDR Agent Installation

The XDR agent is NOT in the AMI. Users upload their agent installer to S3 via the portal. At boot, user data downloads and installs it. This allows each range to connect to the user's own XSIAM tenant.

## Config

| Env Var | Value |
|---------|-------|
| `VICTIM_AMI_ID` | Set in terraform.tfvars per environment |
