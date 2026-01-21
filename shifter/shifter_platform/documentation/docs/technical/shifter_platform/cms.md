# Shifter CMS

Content and asset management.

## Responsibility

- Scenario catalog (declarative templates)
- Asset management (agents, credentials)
- Range content tracking (scenario associations)
- Config hydration for Engine

CMS owns **what** gets deployed. Engine owns **how** it gets provisioned.

## Architecture

```mermaid
graph LR
    MC[Mission Control] --> CMS
    CMS --> Engine

    subgraph CMS
        Templates[Scenario Templates]
        Loader[Template Loader]
        Hydrator[Config Hydrator]
    end

    Templates --> Loader
    Loader --> Hydrator
    Hydrator -->|range_config| Engine
```

## Scenario Templates

Declarative YAML definitions in `cms/scenarios/templates/`.

### Template Schema

```yaml
id: string                    # Unique identifier
name: string                  # Display name
description: string           # User-facing description
enabled: boolean              # Available to users
ngfw: boolean                 # Requires NGFW

instances:
  - name: string              # Instance display name
    role: string              # attacker, victim, dc
    os_type: string           # kali, windows, ubuntu, from_agent
    xdr_agent: boolean        # Deploy XDR agent
    join_domain: boolean      # Join AD domain (optional)
    domain_controller: boolean # Is DC (optional)
    ai_agent: boolean         # AI-assisted (optional)
    dc_config:                # DC configuration (optional)
      domain_name: string
      netbios_name: string

subnets:
  - name: string              # Subnet name
    instances: [string]       # Instance names in subnet
    connected_to: [string]    # Connected subnets (for NGFW routing)
```

### Available Scenarios

| ID | Name | Instances | NGFW |
|----|------|-----------|------|
| `basic` | Basic Range | attacker, victim | No |
| `basic_ngfw` | Basic Range with NGFW | attacker, victim | Yes |
| `ad_attack_lab` | AD Attack Lab | attacker, dc, victim | No |
| `cortex_byot` | Cortex BYOT | attacker, dc, 2x victim, server | Yes |

## Hydrated Range Config

CMS hydrates templates with user-specific data before calling Engine.

```python
range_config = {
    "scenario_id": "basic",
    "subnet_index": 5,
    "instances": [
        {"role": "attacker", "os_type": "kali"},
        {
            "role": "victim",
            "os_type": "ubuntu",
            "agent": {
                "s3_key": "agents/123/abc.deb",
                "filename": "agent.deb",
            }
        }
    ],
}
```

## Models

### Catalog Models (System-Defined Types)

| Model | Purpose |
|-------|---------|
| `OperatingSystem` | Available OS types (Windows, Ubuntu, Kali) |
| `CredentialType` | Types of credentials (SCM, Deployment Profile) |
| `InstanceType` | VM instance type definitions |
| `AppType` | Application type definitions (NGFW) |

### Asset Models (User-Owned)

| Model | Purpose |
|-------|---------|
| `AgentConfig` | XDR/XSIAM agent installer uploaded by user |
| `Credential` | User credentials with type-specific data |

### Entity Models (Materialized in Ranges)

| Model | Purpose |
|-------|---------|
| `Instance` | VM instance definition in a range |
| `App` | Application (NGFW) definition in a range |
| `Subnet` | Network subnet definition in a range |

### Request Tracking

| Model | Purpose |
|-------|---------|
| `Request` | Provisioning request container (correlation UUID) |
| `RangeInstance` | Tracks hydrated scenario config sent to Engine |

## Internal Modules

| Module | Purpose |
|--------|---------|
| `cms/scenarios/loader.py` | Template loading and validation |
| `cms/scenarios/schema.py` | Pydantic models for templates |
| `cms/scenarios/hydrator.py` | Config hydration logic |
| `cms/assets/services.py` | Agent CRUD, storage quota |

## Service Interface

#### Agents

| Function | Purpose |
|----------|---------|
| `create_agent(user, ...)` | Create agent record |
| `delete_agent(user, agent_id)` | Soft delete agent |
| `list_agents(user)` | Get user's agents |
| `get_agent(user, agent_id)` | Get single agent |

#### Credentials

| Function | Purpose |
|----------|---------|
| `create_credential(user, type, ...)` | Create credential (scm, authcode) |
| `delete_credential(user, credential_id)` | Delete credential |
| `list_credentials(user)` | Get user's credentials (includes type) |
| `get_credential(user, credential_id)` | Get single credential |

#### Ranges

| Function | Purpose |
|----------|---------|
| `create_range(user, scenario_id, agent_id, ...)` | Hydrate template, call Engine |
| `destroy_range(user, range_id)` | Tear down range |
| `list_ranges(user)` | Get user's ranges |
| `get_range(user, range_id)` | Get single range |
| `cancel_range(user, range_id)` | Cancel provisioning range |
| `pause_range(user, range_id)` | Pause range |
| `resume_range(user, range_id)` | Resume range |

#### Uploads

| Function | Purpose |
|----------|---------|
| `initiate_upload(user, name, filename, file_size)` | Validate, generate presigned URL |
| `complete_upload(user, upload_token)` | Verify and finalize upload |
| `cancel_upload(user, upload_token)` | Clean up failed upload |

#### User Quota

| Function | Purpose |
|----------|---------|
| `get_storage_used(user)` | Check storage quota |

#### Scenarios

| Function | Purpose |
|----------|---------|
| `list_scenarios(user)` | Get available scenarios with metadata |
| `get_scenario(scenario_id)` | Get single scenario template |
| `validate_scenario_requirements(scenario_id, agent)` | Check agent meets requirements |
