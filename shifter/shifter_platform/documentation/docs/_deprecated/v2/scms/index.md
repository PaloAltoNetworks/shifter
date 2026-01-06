# SCMS (Scenario Content Management)

SCMS is a goal-state concept. No separate SCMS app exists today.

## Current State

Range configuration is fixed: 1 Kali attacker + 1 Ubuntu victim. The only user-configurable content is the XDR agent installer.

Related models live in `mission_control`:

### OperatingSystem

Reference table for OS types. Used to map agent file extensions to OS.

| Field | Purpose |
|-------|---------|
| `slug` | Identifier (e.g., `linux`, `windows`) |
| `name` | Display name |
| `extensions` | JSON list of file extensions (e.g., `[".deb", ".sh"]`) |

### AgentConfig

User-uploaded XDR/XSIAM agent installers.

| Field | Purpose |
|-------|---------|
| `user` | Owner |
| `os` | FK to OperatingSystem |
| `name` | User-friendly name |
| `s3_key` | S3 object key for installer file |
| `sha256_hash` | File integrity (optional) |

## Range Instance Config

The `Range.instance_config` JSON field exists for future multi-instance scenarios. Currently unused - provisioner defaults to:

```json
[
  {"role": "attacker", "os": "kali", "instance_type": "t3.small"},
  {"role": "victim", "os": "ubuntu", "instance_type": "t3.micro"}
]
```

## What SCMS Would Add

Per goal-state architecture (`notes/arch/goal-state.md`):
- Scenario authoring and versioning
- Publishing workflow (draft → published → deprecated)
- Tooling catalogs (instance types, OS images, appliances)
- Multiple victim configurations per scenario

None of this exists today.
