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
2. Manifest written to `kali-manifest.json`
3. Update `terraform/environments/*/terraform.tfvars` with new AMI ID

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

## Build Time

Expect ~15-20 minutes for a full Kali build (kali-linux-headless is large).

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
