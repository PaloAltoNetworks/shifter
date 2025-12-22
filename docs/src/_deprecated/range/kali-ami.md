# Kali AMI

Pre-baked Kali Linux AMI with SSM agent and pentesting tools.

## Why Pre-Bake?

The official Kali Linux AMI from AWS Marketplace is a minimal base image. Pre-baking allows us to:

1. Install SSM agent for remote access (not included by default)
2. Install `kali-linux-headless` metapackage with core pentesting tools
3. Apply hardening for secure AMI distribution

## Base Image

**Official Kali Linux** from AWS Marketplace by Offensive Security.

Subscribe (free) before the AMI is available in your account:
[AWS Marketplace - Kali Linux](https://aws.amazon.com/marketplace/pp/prodview-fznsw3f7mq7to)

Query the latest AMI after subscribing:

```bash
aws ec2 describe-images --region us-east-2 \
  --owners 679593333241 \
  --filters "Name=name,Values=kali-last-snapshot-amd64-*" \
  --query 'Images | sort_by(@, &CreationDate) | [-1].[ImageId,Name,CreationDate]' \
  --output table
```

## Pre-Bake Process

### 1. Launch Base AMI

Launch an instance from the marketplace Kali AMI with:
- SSH key pair (for initial access)
- IAM instance profile with SSM permissions
- Public IP for SSH access

### 2. Install SSM Agent

SSM agent is not in Kali repos. Download directly from AWS:

```bash
wget https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_amd64/amazon-ssm-agent.deb
sudo dpkg -i amazon-ssm-agent.deb
sudo systemctl enable amazon-ssm-agent
sudo systemctl start amazon-ssm-agent
```

### 3. Install Pentesting Tools

The base image is minimal. Install the tools we need:

```bash
sudo apt update
sudo apt install -y kali-linux-headless  # Core pentesting tools
sudo apt install -y hexstrike-ai          # AI-powered MCP pentesting
```

### 4. Hardening (Required)

Run these commands **after all installs are complete**, right before creating the AMI:

```bash
# Remove SSH host keys (regenerated on each new instance boot)
sudo shred -u /etc/ssh/*_key /etc/ssh/*_key.pub

# Clear authorized_keys (your SSH key shouldn't persist to new instances)
rm -f ~/.ssh/authorized_keys

# Reset machine ID (generates unique ID on boot)
sudo truncate -s 0 /etc/machine-id

# Clean apt cache (reduces AMI size)
sudo apt clean
```

### 5. Create AMI

From your local machine (not the instance):

```bash
aws ec2 create-image \
  --instance-id i-xxxxx \
  --name "shifter-kali-$(date +%Y%m%d)" \
  --description "Pre-baked Kali with SSM agent" \
  --no-reboot \
  --region us-east-2 \
  --query 'ImageId' \
  --output text
```

The `--no-reboot` flag creates the AMI without stopping the instance. For production AMIs, omit this flag to ensure filesystem consistency.

Wait for AMI to become available:

```bash
aws ec2 describe-images --image-ids ami-xxxxx \
  --query 'Images[0].State' --output text
```

### 6. Update Lambda Configuration

Update the `KALI_AMI_ID` environment variable in the create_kali Lambda:

**Option A: Terraform tfvars**
```hcl
# terraform/environments/prod/terraform.tfvars
kali_ami_id = "ami-xxxxx"
```

**Option B: Direct Lambda update** (for testing)
```bash
aws lambda update-function-configuration \
  --function-name shifter-create-kali \
  --environment "Variables={KALI_AMI_ID=ami-xxxxx,...}" \
  --region us-east-2
```

### 7. Test

Launch a new range and verify:
- Instance boots and SSM agent registers
- Tools are available (whatever was installed in step 3)

## Naming Convention

`shifter-kali-YYYYMMDD` - date of AMI creation.

Example: `shifter-kali-20251212`

## Maintenance

Re-bake when:
- Major Kali rolling release updates
- New tools needed across all ranges
- Security patches required

Frequency: Monthly or as needed.
