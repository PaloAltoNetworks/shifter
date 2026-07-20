# Cortex XDR Broker VM Integration Design

## Overview

This document outlines the design for adding Cortex XDR Broker VM instances to Shifter ranges. The Broker VM acts as a bridge between range instances and the Cortex XDR/XSIAM cloud, enabling agent proxy functionality for isolated environments.

### Purpose

The Broker VM enables:
- **Agent Proxy**: XDR agents in the range connect to the Broker VM instead of directly to the internet
- **Closed Network Support**: Ranges can operate with restricted egress while still reporting to XDR/XSIAM
- **Syslog Collection**: Optional applet for collecting syslog from range instances (requires XDR Pro per TB license)

### Use Case

Domain Consultants running demos in environments where direct XDR cloud connectivity is restricted or where centralized agent communication is preferred.

---

## Cortex XDR Broker VM Requirements

### Hardware Requirements

| Use Case | CPU Cores | RAM | Disk |
|----------|-----------|-----|------|
| Agent Proxy Only | 2 | 8 GB | 100 GB |
| Standard | 4 | 8 GB | 512 GB |
| Content Caching | 8 | 8 GB | 512 GB |

**Recommendation for Shifter**: 4 cores / 8 GB RAM / 100 GB disk (t3.xlarge or m5.large)

### Network Requirements

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 8888 | TCP | Inbound | Agent proxy (XDR agents connect here) |
| 443 | TCP | Outbound | XDR cloud connectivity |
| 53 | UDP/TCP | Outbound | DNS resolution |
| 22 | TCP | Inbound | SSH (Portal terminal access) |
| 443 | TCP | Inbound | Broker VM Web UI (for registration) |

### Registration Process

1. Broker VM boots and reaches ready state
2. User generates registration token from Cortex XDR Console:
   `Settings > Configurations > Data Broker > Broker VMs > Generate Token`
3. User accesses Broker VM Web UI at `https://<broker-ip>`
4. User enters registration token
5. Broker VM registers with tenant (takes ~30 seconds)
6. User can then activate applets (Agent Proxy, Syslog Collector, etc.)

**Key Point**: Registration is a manual step requiring user interaction with the XDR console. This cannot be automated without XDR API access.

---

## AMI Creation (One-Time Setup)

The Broker VM is distributed as a VMDK that must be converted to an AMI. This is a one-time manual process per AWS region.

### Prerequisites

1. Download Broker VM VMDK from Cortex XDR Console:
   `Settings > Configurations > Data Broker > Broker VMs > Download VMDK`
2. AWS IAM user with VM Import/Export permissions:
   - `s3:GetBucketLocation`, `s3:GetObject`, `s3:PutObject`
   - `ec2:ImportImage`, `ec2:ImportSnapshot`, `ec2:DescribeImportImageTasks`
   - `ec2:CreateImage`, `ec2:DescribeImages`

### Import Process

```bash
# 1. Upload VMDK to S3
aws s3 cp broker-vm-15.0.x.vmdk s3://shifter-broker-vm-import/

# 2. Create containers.json
cat > containers.json << 'EOF'
{
  "Description": "Cortex XDR Broker VM 15.x",
  "Format": "vmdk",
  "UserBucket": {
    "S3Bucket": "shifter-broker-vm-import",
    "S3Key": "broker-vm-15.0.x.vmdk"
  }
}
EOF

# 3. Import image
aws ec2 import-image \
  --description "Cortex XDR Broker VM 15.x" \
  --disk-containers "file://containers.json"

# 4. Track progress
aws ec2 describe-import-image-tasks --import-task-ids import-ami-xxxxx

# 5. Note the AMI ID when complete
```

### AMI Management

- Store AMI ID in SSM Parameter: `/shifter/{env}/ami/broker-vm`
- Update when new Broker VM versions are released
- Consider automating with a Lambda triggered by S3 upload

---

## Engine Integration

### Instance Catalog Addition

Add new entry to `shifter-engine/catalog/instances.py`:

```python
def _get_broker_instance_type() -> str:
    """Get default instance type for Broker VM from environment."""
    return os.environ.get("BROKER_INSTANCE_TYPE") or "t3.xlarge"

INSTANCE_CATALOG["broker-vm"] = InstanceType(
    name="broker-vm",
    role="broker",
    _instance_type_getter=_get_broker_instance_type,
    user_data_template="broker.sh.j2",  # Minimal - just waits for boot
    description="Cortex XDR Broker VM",
    ami_lookup=None,  # AMI ID from SSM parameter, not dynamic lookup
    requires_agent=False,
    ssh_user="broker",  # Broker VM uses 'broker' user
)
```

### New Role: `broker`

The Broker VM introduces a new role alongside `attacker`, `victim`, and `dc`:

| Role | Purpose | Setup Plan | Agents |
|------|---------|------------|--------|
| `attacker` | Kali attack box | KaliSetupPlan | None |
| `victim` | XDR-protected target | Bootstrap + XDR | Required |
| `dc` | Active Directory DC | Prebaked AMI | Optional |
| `broker` | XDR Broker VM | None (prebaked) | None |

### User Data Template

Create `shifter-engine/templates/broker.sh.j2`:

```bash
#!/bin/bash
# Broker VM user data - minimal, just log that SSM will handle setup
echo "Shifter Broker VM initializing..."
echo "Registration must be completed via Web UI at https://$(hostname -I | awk '{print $1}')"
```

**Note**: Broker VM is a hardened appliance. User data has limited effect. The VM boots to its own shell/web interface.

### No SSM Setup Plan Required

Unlike victims and DCs, the Broker VM:
- Is a hardened appliance (not a general-purpose OS)
- Does not support arbitrary command execution via SSM
- Requires manual registration via its Web UI
- Has no XDR agent to install (it IS the broker)

The engine should:
1. Create the EC2 instance
2. Wait for instance to reach running state
3. Export the private IP for user reference
4. User completes registration manually

---

## Security Group Design

### New Security Group: `broker`

Add to `terraform/modules/range/vpc/main.tf`:

```hcl
resource "aws_security_group" "broker" {
  count = var.enable_broker_security_group ? 1 : 0

  name        = "${var.name_prefix}-broker"
  description = "Security group for Cortex XDR Broker VM instances"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-broker-sg"
  })
}
```

### Ingress Rules

```hcl
# Agent proxy from VPC (XDR agents connect here)
resource "aws_security_group_rule" "broker_agent_proxy" {
  type              = "ingress"
  from_port         = 8888
  to_port           = 8888
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.broker[0].id
  description       = "Agent proxy from VPC"
}

# HTTPS Web UI from Portal (for registration)
resource "aws_security_group_rule" "broker_https_from_portal" {
  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.broker[0].id
  description       = "HTTPS Web UI from Portal VPC"
}

# SSH from Portal (terminal access)
resource "aws_security_group_rule" "broker_ssh_from_portal" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.broker[0].id
  description       = "SSH from Portal VPC"
}
```

### Egress Rules

```hcl
# HTTPS to internet (XDR cloud)
resource "aws_security_group_rule" "broker_https_egress" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.broker[0].id
  description       = "HTTPS to XDR cloud"
}

# DNS
resource "aws_security_group_rule" "broker_dns_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.broker[0].id
  description       = "DNS"
}
```

### Victim → Broker Communication

Add rule to allow victims to reach broker:

```hcl
resource "aws_security_group_rule" "victim_to_broker" {
  count = var.enable_broker_security_group ? 1 : 0

  type                     = "egress"
  from_port                = 8888
  to_port                  = 8888
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.broker[0].id
  security_group_id        = aws_security_group.victim.id
  description              = "Agent proxy to Broker VM"
}
```

---

## Scenario Configuration

### New Scenario: `broker_proxy`

Add to `portal/mission_control/views.py`:

```python
def _get_scenario_instance_config(scenario, agent_os):
    scenarios = {
        "basic": [...],
        "ad_attack_lab": [...],
        "broker_proxy": [
            {"role": "attacker", "os_type": "kali"},
            {"role": "broker", "os_type": "broker"},
            {"role": "victim", "os_type": agent_os},
        ],
    }
    return scenarios.get(scenario, scenarios["basic"])
```

### Instance Config Schema Extension

```python
{
    "role": "broker",
    "os_type": "broker",
    "instance_type": "t3.xlarge",  # Optional, defaults from env var
}
```

---

## Provisioning Workflow

### Sequence

```
Portal: launch_range(scenario="broker_proxy")
    ↓
Engine: Creates NetworkComponent (subnet)
    ↓
Engine: Creates broker InstanceComponent
    - No AMI lookup (uses SSM parameter)
    - No setup plan (prebaked)
    ↓
Engine: Creates victim InstanceComponent(s)
    - Runs XDR agent install
    - Agent configured to use broker IP:8888 (future enhancement)
    ↓
Engine: Creates attacker InstanceComponent
    ↓
Pulumi outputs:
    {
      "instances": [
        {"role": "broker", "private_ip": "10.1.5.10", ...},
        {"role": "victim", "private_ip": "10.1.5.11", ...},
        {"role": "attacker", "private_ip": "10.1.5.12", ...}
      ]
    }
    ↓
Portal: Displays broker IP to user
    ↓
User: Accesses https://<broker-ip> and registers with XDR token
    ↓
User: Activates Agent Proxy applet on broker
    ↓
User: Configures victim XDR agents to use broker (manual or via policy)
```

### Portal UI Changes

Add to range details display:
- Broker VM IP address
- Link to Broker VM Web UI (`https://<broker-ip>`)
- Registration status indicator (future: poll broker status)

---

## Range Stack Changes

### `range_stack.py` Updates

```python
# Separate instances by role for dependency ordering
dc_configs = [inst for inst in config.instances if inst.role == "dc"]
broker_configs = [inst for inst in config.instances if inst.role == "broker"]
other_configs = [inst for inst in config.instances if inst.role not in ("dc", "broker")]

# Create broker instances (no setup needed)
for inst_config in broker_configs:
    broker_instance = InstanceComponent(
        f"{name}-broker-{broker_count}",
        # ... params ...
    )
    broker_count += 1
    self.instances.append(broker_instance)
    # No run_setup() - broker is self-contained
```

---

## Network Firewall Considerations

### Egress Filtering

The Range VPC uses AWS Network Firewall for domain-based egress filtering. The Broker VM requires outbound access to:

- `*.paloaltonetworks.com` - XDR cloud services
- `*.amazonaws.com` - AWS metadata/SSM (optional)

Add to `terraform/modules/range/vpc/firewall.tf`:

```hcl
# Add to allowed domains list
locals {
  broker_allowed_domains = [
    ".paloaltonetworks.com",
    ".xdr.paloaltonetworks.com",
  ]
}
```

**Note**: Verify exact FQDNs from Palo Alto Networks documentation for specific regions.

---

## Configuration Requirements

### Environment Variables (ECS Task Definition)

| Variable | Description | Default |
|----------|-------------|---------|
| `BROKER_INSTANCE_TYPE` | EC2 instance type for Broker VM | `t3.xlarge` |
| `BROKER_AMI_ID` | Broker VM AMI ID (or SSM parameter path) | Required |

### SSM Parameters

| Parameter | Description |
|-----------|-------------|
| `/shifter/{env}/ami/broker-vm` | Broker VM AMI ID |

### Terraform Variables

| Variable | Description |
|----------|-------------|
| `enable_broker_security_group` | Enable broker SG creation |
| `broker_allowed_domains` | ANFW domain allowlist for broker |

---

## Issues and Anti-Patterns Identified

### 1. Manual Registration Required

**Issue**: Broker VM registration requires manual user interaction with both the XDR console (generate token) and Broker VM Web UI (enter token).

**Impact**: Cannot fully automate range provisioning with broker. User must complete registration after range is ready.

**Mitigation**:
- Clear UI guidance in Portal
- Provide Broker VM Web UI link
- Consider future XDR API integration if available

### 2. AMI Management Overhead

**Issue**: Broker VM is distributed as VMDK, requiring manual conversion to AMI. Updates require re-importing.

**Impact**: Operational overhead for keeping broker AMIs current.

**Mitigation**:
- Document AMI creation process
- Consider Lambda automation for S3 → AMI pipeline
- Store AMI versions in SSM Parameters

### 3. Agent Proxy Configuration on Victims

**Issue**: XDR agents on victims need to be configured to use the Broker VM as their proxy. This typically requires:
- XDR policy configuration in the console, or
- Passing proxy settings during agent installation

**Impact**: Current XDR agent install plans don't support proxy configuration.

**Mitigation**:
- Phase 1: User configures proxy via XDR policy after range is up
- Phase 2: Extend XDRAgentInstallPlan to accept proxy settings

### 4. Hardened Appliance Limitations

**Issue**: Broker VM is a hardened appliance. Cannot install additional software, run arbitrary commands, or customize extensively.

**Impact**:
- SSM agent may not be available/functional
- Limited observability from Shifter
- No automated health checks

**Mitigation**:
- Accept as limitation of appliance model
- Rely on XDR console for broker health monitoring
- Document that broker is "fire and forget" from Shifter perspective

### 5. Instance Type Sizing

**Issue**: Broker VM has specific hardware requirements (4 cores, 8GB RAM). t3.xlarge (4 vCPU, 16GB) works but may be oversized.

**Consideration**: m5.large (2 vCPU, 8GB) might suffice for agent proxy only use case.

**Recommendation**: Default to t3.xlarge for safety, allow override via environment variable.

---

## Open Questions

1. **XDR API Access**: Does PANW provide an API for generating registration tokens or checking broker status? This would enable automation.

2. **Disk Size**: The engine currently doesn't set root volume size. Broker VM needs 100-512GB. Need to verify default AMI disk size after import.

3. **Multiple Brokers**: Should a range support multiple Broker VMs for HA? Initial implementation: single broker per range.

4. **Syslog Collection**: Should Shifter support configuring the Syslog Collector applet? This requires XDR Pro per TB license.

5. **Broker VM Updates**: How to handle Broker VM version updates for existing ranges? Likely: destroy and re-provision range.

---

## Implementation Phases

### Phase 1: Basic Integration (MVP)

- Add `broker` role to instance catalog
- Create broker security group in Terraform
- Add AMI SSM parameter
- Extend RangeStack to handle broker instances
- Add `broker_proxy` scenario
- Portal displays broker IP after provisioning
- User manually registers and configures

### Phase 2: Enhanced UX

- Portal links to Broker VM Web UI
- Registration instructions in Portal
- Broker status polling (if API available)
- Agent proxy configuration in XDR install plans

### Phase 3: Automation (If XDR API Available)

- Automated token generation
- Automated broker registration
- Automated agent proxy activation
- Health monitoring integration

---

## References

- [Set up Broker VM on AWS](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR/Cortex-XDR-3.x-Documentation/Set-up-Broker-VM-on-Amazon-Web-Services)
- [What is the Broker VM?](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR/Cortex-XDR-3.x-Documentation/What-is-the-Broker-VM)
- [Configure the Broker VM](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR/Cortex-XDR-Pro-Administrator-Guide/Configure-the-Broker-VM)
- [Create a Broker VM AMI](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR/Cortex-XDR-Pro-Administrator-Guide/Create-a-Broker-VM-Amazon-Machine-Image-AMI)
- [Broker VM Applets](https://docs-cortex.paloaltonetworks.com/r/Cortex-XDR/Cortex-XDR-3.x-Documentation/Broker-VM-data-collector-applets)
