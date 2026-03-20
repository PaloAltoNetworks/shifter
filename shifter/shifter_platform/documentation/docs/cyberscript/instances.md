# Instance Configuration

Field reference for `InstanceConfig` in `cms/scenarios/schema.py`. Each entry in a scenario's `instances` list defines one compute instance in the range.

## Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| **`name`** | string | yes | -- | Display name (e.g., `Attacker`, `Domain Controller`). Must be unique within the scenario. |
| **`role`** | string | yes | -- | One of: `attacker`, `victim`, `dc`. |
| **`os_type`** | string | yes | -- | One of: `kali`, `windows`, `ubuntu`, `from_agent`. |
| **`xdr_agent`** | bool | no | `false` | Install a Cortex XDR agent on this instance. |
| **`domain_controller`** | bool | no | `false` | This instance is a Windows domain controller. |
| **`join_domain`** | bool | no | `false` | This instance should join the Active Directory domain. |
| **`dc_config`** | object | no | `null` | Domain controller configuration. Required when `domain_controller: true`. |
| **`ami_key`** | string | no | `null` | Custom AMI key for non-standard images (e.g., `ctf-webshell`). Overrides the default AMI for the given `os_type`. |

## Roles

| Role | Purpose |
|------|---------|
| **`attacker`** | Offensive tooling host. Typically Kali Linux. |
| **`victim`** | Target host with XDR agent. The machine being defended/attacked. |
| **`dc`** | Active Directory domain controller. Always Windows. |

Roles map directly to AMI selection and provisioning behavior in the Engine.

## OS Types

| Value | Resolves To | Notes |
|-------|------------|-------|
| **`kali`** | Kali Linux AMI | Standard for attacker instances. |
| **`windows`** | Windows Server AMI | Used for DCs and Windows victims. |
| **`ubuntu`** | Ubuntu Server AMI | Linux victim/server instances. |
| **`from_agent`** | Determined at hydration | OS is inferred from the user-selected XDR agent. Windows agents resolve to `windows`; Linux agents resolve to `ubuntu`. |

### `from_agent` Resolution

When `os_type: from_agent`, the hydrator inspects the agent's OS slug at runtime:

```
agent.os.slug == "windows"  ->  os_type = "windows"
agent.os.slug == anything else  ->  os_type = "ubuntu"
```

This allows victims to match the OS of whatever agent the user uploads. Requires `xdr_agent: true`.

Source: `cyberscript/schemas/range.py :: _resolve_agent_os()`

## XDR Agent Embedding

When `xdr_agent: true`, the hydrator:

1. Looks up the agent by OS type from the agents mapping
2. Creates an `AgentDetails` object with `s3_key`, `filename`, and `sha256`
3. Embeds it in the hydrated `InstanceSpec.agent` field

The Engine uses this to download and install the agent during provisioning.

Agent lookup by OS type:

| Template `os_type` | Agent Key |
|--------------------|-----------|
| `windows` | `agents["windows"]` |
| `ubuntu`, `kali` | `agents["linux"]` |
| `from_agent` | First available agent |

Source: `cyberscript/schemas/range.py :: _resolve_os_and_agent()`

## Domain Controller Pattern

To create an Active Directory environment:

1. Define a DC instance with `role: dc`, `os_type: windows`, `domain_controller: true`
2. Provide `dc_config` with domain details
3. Set `join_domain: true` on instances that should join the domain

### `dc_config` Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| **`domain_name`** | string | yes | Fully qualified domain name (e.g., `internal.shifter`). |
| **`netbios_name`** | string | yes | NetBIOS name (e.g., `INTSHIFTER`). |

### Example

```yaml
instances:
  - name: Domain Controller
    role: dc
    os_type: windows
    domain_controller: true
    xdr_agent: true
    dc_config:
      domain_name: internal.shifter
      netbios_name: INTSHIFTER

  - name: Workstation
    role: victim
    os_type: windows
    xdr_agent: true
    join_domain: true
```

The Domain Controller is provisioned first. Once Active Directory is running, domain-joined instances are configured to join `internal.shifter`.

## Schema Source

```
cms/scenarios/schema.py :: InstanceConfig, DCConfig
cyberscript/schemas/range.py :: InstanceSpec, AgentDetails, DCConfig
```
