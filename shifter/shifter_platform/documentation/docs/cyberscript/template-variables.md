# Template Variables

Double-brace syntax for referencing provisioned instance properties in experiment prompts. Resolved at runtime after instances are provisioned.

Source: `cyberscript/template_vars.py`

## Syntax

```
{{InstanceName.property}}
```

Instance names must match a `name` from the scenario template's `instances` list.

## Allowed Properties

| Property | Description | Example Value |
|----------|-------------|---------------|
| **`ip`** | Private IP address of the instance | `10.1.1.5` |
| **`name`** | Display name of the instance | `Workstation` |
| **`instance_id`** | Cloud instance identifier | `i-0abc123def456` (AWS), GDC VM name (GCP) |

Source: `ALLOWED_PROPERTIES` in `cyberscript/template_vars.py`

## Example

```
Attack the workstation at {{Workstation.ip}} using credentials from {{DC.ip}}
```

After resolution (when instances are provisioned):

```
Attack the workstation at 10.1.2.15 using credentials from 10.1.1.5
```

## Validation

`validate_template()` checks two things:

1. **Instance name exists** -- Every `InstanceName` must be in the scenario's instance names set. Unknown instances produce an error.
2. **Property is allowed** -- Every `property` must be one of `ip`, `name`, `instance_id`. Unknown properties produce an error.

Validation errors are returned as a list of strings. An empty list means the template is valid.

## Resolution

`resolve_template()` replaces variables with actual values from provisioned instance data:

```python
instance_data = {
    "Workstation": {"ip": "10.1.2.15", "name": "Workstation", "instance_id": "i-abc123"},
    "DC": {"ip": "10.1.1.5", "name": "DC", "instance_id": "i-def456"},
}
resolved = resolve_template(template_string, instance_data)
```

Resolution happens after provisioning, when IP addresses and instance IDs are known. If a variable cannot be resolved (instance or property missing), a `ValueError` is raised.

## Regex Pattern

```python
r"\{\{(\w+)\.(\w+)\}\}"
```

Captures two groups: instance name (`\w+`) and property (`\w+`). Instance names with spaces are not supported in template variable references -- use `\w+` compatible names (letters, digits, underscores) when referencing instances in templates.

## Pydantic Integration

The `TemplateString` annotated type provides automatic validation in Pydantic models. When a model field uses `TemplateString`, variables are validated against `instance_names` from the Pydantic validation context.

```python
from cyberscript.template_vars import TemplateString

class ExperimentPrompt(BaseModel):
    instructions: TemplateString
```

Validation context must include `instance_names`:

```python
prompt = ExperimentPrompt.model_validate(
    {"instructions": "SSH to {{Attacker.ip}}"},
    context={"instance_names": {"Attacker", "Workstation"}},
)
```
