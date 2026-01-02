# Feature: Guacamole RDP Gateway for Range Instances

## Summary

Integrate Apache Guacamole as a shared RDP gateway to provide browser-based remote desktop access to appropriate range instances (Windows hosts and Kali).

## Motivation

Users currently access range instances via SSH terminal only. Windows hosts (DC, victims) and Kali benefit from graphical access. Guacamole provides a browser-native solution without requiring users to install RDP clients or manage VPN connections.

## Requirements

### Infrastructure

- [ ] Deploy Guacamole server in Portal VPC (ECS Fargate or EC2)
- [ ] Configure Guacamole to reach Range VPC instances via VPC peering
- [ ] Integrate Guacamole authentication with Cognito (OIDC or SAML)
- [ ] Secure Guacamole admin interface (or disable it entirely)
- [ ] Add ALB route for Guacamole (`/guacamole/` or subdomain)

### CMS: Instance RDP Flag

Add `rdp_enabled` flag to instance catalog and scenario schema.

**`shifter/engine/provisioner/catalog/instances.py`**

```python
@dataclass
class InstanceType:
    name: str
    role: str
    user_data_template: str
    description: str
    _instance_type_getter: callable
    ami_lookup: Optional[dict] = None
    requires_agent: bool = False
    ssh_user: str = "ubuntu"
    rdp_enabled: bool = False  # NEW: Whether RDP access is available
    rdp_port: int = 3389       # NEW: RDP port (3389 for Windows, 3389 for xrdp on Linux)
```

**Default RDP-enabled instances:**

| Instance Type | RDP Enabled | Notes |
|---------------|-------------|-------|
| `kali-2024` | ✅ | Via xrdp (requires user_data changes) |
| `windows-server-2022-victim` | ✅ | Native RDP |
| `windows-server-2022-dc` | ✅ | Native RDP |
| `ubuntu-*-victim` | ❌ | SSH only |
| `amazon-linux-*-victim` | ❌ | SSH only |

**`shifter/shifter_platform/cms/scenarios/schema.py`**

```python
class InstanceConfig(BaseModel):
    role: str
    os_type: str
    agent_slot: str | None = None
    domain_controller: bool = False
    join_domain: bool = False
    dc_config: DCConfig | None = None
    rdp_enabled: bool | None = None  # NEW: Override catalog default (None = use catalog default)
```

### Engine: Propagate RDP Metadata

- [ ] Engine stores RDP-enabled flag per instance in Range model or separate table
- [ ] Expose instance RDP status via `/api/range/status/` response

### Portal UX

**Dashboard / Range Detail**

When range is ready, show instance cards with access buttons:

```
┌─────────────────────────────────────────────────────┐
│ kali                                    🟢 Running  │
│ 10.1.42.10                                          │
│ ┌─────────┐  ┌─────────┐                            │
│ │   SSH   │  │   RDP   │                            │
│ └─────────┘  └─────────┘                            │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ dc                                      🟢 Running  │
│ 10.1.42.11                                          │
│ ┌─────────┐  ┌─────────┐                            │
│ │   SSH   │  │   RDP   │                            │
│ └─────────┘  └─────────┘                            │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ victim-1                                🟢 Running  │
│ 10.1.42.12                                          │
│ ┌─────────┐                                         │
│ │   SSH   │  (RDP not available for this instance)  │
│ └─────────┘                                         │
└─────────────────────────────────────────────────────┘
```

- SSH button → existing terminal view (possibly with instance selector)
- RDP button → opens Guacamole connection in new tab

**Implementation options:**

1. **Direct Guacamole link**: `/guacamole/#/client/{connection_id}`
2. **Portal proxy route**: `/mission-control/rdp/{instance_id}/` that generates Guacamole auth token and redirects

### Guacamole Connection Management

**Option A: Static connections (simpler)**
- Pre-create Guacamole connections for each instance during provisioning
- Store connection ID in RangeInstance or Range model
- Delete connections on range destroy

**Option B: Dynamic connections via API**
- Use Guacamole REST API to create connections on-demand
- Generate one-time auth tokens for users
- More complex but avoids stale connections

### Security Considerations

- [ ] Guacamole connections must be scoped to user's own range instances only
- [ ] Connection credentials managed via SSM Parameter Store or Secrets Manager
- [ ] Audit logging for RDP sessions
- [ ] Session timeout aligned with range TTL

### Kali xrdp Setup

Kali user_data template needs xrdp installation:

```bash
# Install xrdp for Guacamole access
apt-get install -y xrdp
systemctl enable xrdp
systemctl start xrdp

# Configure xrdp to use existing session
echo "kali:changeme" | chpasswd  # Or use EC2 key-based auth
```

Alternatively, use Kali's built-in VNC and configure Guacamole for VNC instead of RDP.

## Out of Scope (for this issue)

- VNC support (future enhancement)
- File transfer via Guacamole
- Session recording
- Multi-monitor support

## Related

- DC security group already allows RDP from Range VPC (`dc_rdp_from_range` in `platform/terraform/modules/range/vpc/main.tf`)
- Terminal view implementation in `mission_control/views.py`

## Tasks

1. [ ] Add `rdp_enabled` to `InstanceType` dataclass
2. [ ] Update instance catalog with RDP flags
3. [ ] Add optional `rdp_enabled` to `InstanceConfig` schema
4. [ ] Design Guacamole deployment (ECS vs EC2)
5. [ ] Implement Guacamole Terraform module
6. [ ] Add Kali xrdp provisioning to user_data template
7. [ ] Extend Range API to return instance RDP metadata
8. [ ] Update dashboard UI with instance access buttons
9. [ ] Implement Guacamole connection management (create/delete)
10. [ ] Add Cognito integration for Guacamole auth
11. [ ] Update security groups if needed
12. [ ] Documentation
