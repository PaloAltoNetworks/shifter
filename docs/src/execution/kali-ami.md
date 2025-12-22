# Kali AMI

Pre-baked Kali Linux with pentesting tools and Claude Code.

## What's In It

- Kali Linux 2025.3.0
- SSM agent
- kali-linux-headless metapackage
- Claude Code (configured for Bedrock)

## Why Pre-Bake

The marketplace Kali AMI is minimal. Pre-baking adds:
- SSM agent (not in Kali repos by default)
- Pentesting tools via kali-linux-headless
- Claude Code for agentic pentesting workflows

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
