# Scenario Templates

Complete schema reference for CyberScript scenario YAML templates. Validated by `ScenarioTemplate` in `cms/scenarios/schema.py`.

## Top-Level Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| **`id`** | string | yes | -- | Unique scenario identifier. Must match the filename stem. |
| **`name`** | string | yes | -- | Human-readable display name shown in the UI. |
| **`description`** | string | yes | -- | User-facing description of the scenario. |
| **`enabled`** | bool | no | `true` | Whether the scenario is visible in the scenario catalog. |
| **`ngfw`** | bool | no | `false` | Whether the scenario requires NGFW provisioning. |
| **`instances`** | list | yes | -- | Instance configurations. Must contain at least one entry. |
| **`subnets`** | list | no | `[]` | Subnet configurations. If empty, the hydrator creates a single `default` subnet at runtime. |

## Validation Rules

- `instances` must be non-empty. An empty list raises a validation error.
- Every instance name referenced in a `subnets[].instances` list must match an entry in `instances[].name`. Unknown references raise a validation error.
- `id` must be unique across all YAML templates and DB scenarios.

## Minimal Valid Template

```yaml
id: minimal
name: Minimal Range
description: Simplest possible scenario.
instances:
  - name: Attacker
    role: attacker
    os_type: kali
```

This produces a single Kali instance in a `default` subnet with no NGFW.

## Field Details

### `id`

The canonical identifier for the scenario. Used in:

- Filename: `cms/scenarios/templates/{id}.yaml`
- Hydration: `hydrate_scenario(scenario_id="{id}", ...)`
- UI: scenario selection, URL routing
- Metadata: `ScenarioMetadata.scenario_id`

Convention: lowercase, underscores for word separation (e.g., `ad_attack_lab`, `ad_attack_lab_ngfw`).

### `ngfw`

When `true`, the Engine provisions a Palo Alto Networks NGFW appliance alongside the range instances. Subnet `connected_to` declarations become firewall rules routed through the NGFW. See [Networking](networking.md).

### `instances`

List of `InstanceConfig` objects. See [Instances](instances.md) for the full field reference.

### `subnets`

List of `SubnetConfig` objects. See [Networking](networking.md) for the full field reference.

## Schema Source

```
cms/scenarios/schema.py :: ScenarioTemplate
```
