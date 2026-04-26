# Code Flow Trace: Instance Name from Template to Terminal UI

**Generated**: 2026-01-25
**Branch**: dev
**Entry**: Template YAML → Terminal UI `instance.name`
**Validation**: Manual trace

---

## Summary: Where the Name Breaks

**PRIMARY BUG**: `InstanceSpec.from_template()` in [range.py:121](shifter/cyberscript/schemas/range.py#L121) **overwrites** the template name with a generated `f"{role}-{os_type}"` string.

**SECONDARY ISSUE**: EC2 hostname is hardcoded in [instance.py:225-252](shifter/engine/provisioner/components/instance.py#L225-L252), completely ignoring `display_name`.

---

## Call Sequence

### 1. Template YAML → `InstanceConfig`

**File**: [cms/scenarios/templates/basic.yaml](shifter/shifter_platform/cms/scenarios/templates/basic.yaml)

```yaml
instances:
  - name: Attacker      # ✅ Name defined here
    role: attacker
    os_type: kali

  - name: Workstation   # ✅ Name defined here
    role: victim
    os_type: from_agent
```

**Flow**: YAML is loaded by `load_scenario()` and parsed into `ScenarioTemplate` with `InstanceConfig` objects.

**Result**: `InstanceConfig.name = "Attacker"` ✅

---

### 2. `load_scenario()` → `ScenarioTemplate`

**File**: [cms/scenarios/loader.py:23-47](shifter/shifter_platform/cms/scenarios/loader.py#L23-L47)

```python
def load_scenario(scenario_id: str) -> ScenarioTemplate:
    with open(template_path) as f:
        data = yaml.safe_load(f)
    return ScenarioTemplate(**data)  # ✅ Name preserved
```

**Result**: `ScenarioTemplate.instances[0].name = "Attacker"` ✅

---

### 3. `hydrate_scenario()` → `InstanceSpec.from_template()`

**File**: [cms/scenarios/hydrator.py:61-69](shifter/shifter_platform/cms/scenarios/hydrator.py#L61-L69)

```python
for instance in template.instances:
    hydrated = InstanceSpec.from_template(instance.model_dump(), agents)
    instances_by_name[instance.name] = hydrated  # Key uses template name
```

**Note**: `instance.model_dump()` includes `{"name": "Attacker", "role": "attacker", ...}`

**Result**: Calls `from_template()` with correct name in `data` dict ✅

---

### 4. 🔴 **BUG**: `InstanceSpec.from_template()` Overwrites Name

**File**: [cyberscript/schemas/range.py:81-128](shifter/cyberscript/schemas/range.py#L81-L128)

```python
@classmethod
def from_template(cls, data: dict[str, Any], agents: dict[str, Any] | None = None) -> InstanceSpec:
    name, role, template_os_type = _extract_required_fields(data)
    # ^^^ name = "Attacker" extracted correctly at line 107

    ...

    return cls(
        name=f"{role}-{os_type}",  # 🔴 BUG: Line 121 - Template name OVERWRITTEN!
        uuid=str(uuid_module.uuid4()),
        role=cast(...),
        ...
    )
```

**Input**: `data["name"] = "Attacker"`
**Output**: `InstanceSpec.name = "attacker-kali"` ❌

**The template name is extracted but then discarded!**

---

### 5. `RangeSpec` → `range_config` in DB

**File**: [cms/scenarios/hydrator.py:106-112](shifter/shifter_platform/cms/scenarios/hydrator.py#L106-L112)

The `RangeSpec` is serialized to JSON and stored in `mission_control_range.range_config`.

**Result**: `range_config.subnets[0].instances[0].name = "attacker-kali"` ❌

---

### 6. Provisioner `_build_instance_config()`

**File**: [engine/provisioner/config.py:395-462](shifter/engine/provisioner/config.py#L395-L462)

```python
def _build_instance_config(inst: dict[str, Any], ...) -> InstanceConfig:
    instance_name = inst.get("name") or f"{display_role}-{os_type}"
    # ^^^ Gets "attacker-kali" from range_config (already wrong)

    return InstanceConfig(
        ...
        name=instance_name,  # Passes wrong name
    )
```

**Result**: `InstanceConfig.name = "attacker-kali"` ❌

---

### 7. `InstanceComponent` - display_name vs hostname

**File**: [engine/provisioner/components/instance.py:160-252](shifter/engine/provisioner/components/instance.py#L160-L252)

```python
# Line 164: display_name is set (but with wrong value from step 6)
self.display_name = display_name or f"{role}-{os_type}"

# Lines 225-252: Hostname is COMPLETELY SEPARATE and hardcoded!
if role == "attacker":
    self.hostname = f"shifter-kali-{range_id}"  # Ignores display_name!
elif role == "victim":
    self.hostname = f"shifter-target-{range_id}-{index}"  # Ignores display_name!
elif role == "dc":
    self.hostname = f"shifter-dc-{range_id}"  # Ignores display_name!
```

**Result**:
- `display_name = "attacker-kali"` (wrong, should be "Attacker")
- `hostname = "shifter-kali-123"` (hardcoded, never uses template name)

---

### 8. Terminal UI Display

**File**: [templates/mission_control/terminal.html:56](shifter/shifter_platform/templates/mission_control/terminal.html#L56)

```html
<span class="pane-title">{{ instance.name|default:instance.role }}</span>
```

**Source**: `RangeContext.instances[].name` from step 5

**Result**: Displays "attacker-kali" instead of "Attacker" ❌

---

## Data Flow Diagram

```
Template YAML
    │
    │ name: "Attacker"  ✅
    ▼
load_scenario()
    │
    │ InstanceConfig.name = "Attacker"  ✅
    ▼
hydrate_scenario()
    │
    │ instance.model_dump()["name"] = "Attacker"  ✅
    ▼
InstanceSpec.from_template()        ◄──── 🔴 BUG HERE
    │
    │ Line 121: name=f"{role}-{os_type}"  ❌
    │ Result: name = "attacker-kali"
    ▼
RangeSpec → range_config (DB)
    │
    │ name = "attacker-kali"  ❌
    ▼
Provisioner config.py
    │
    │ display_name = "attacker-kali"  ❌
    ▼
InstanceComponent
    │
    ├─► display_name = "attacker-kali"  ❌
    │
    └─► hostname = "shifter-kali-{range_id}"  (hardcoded, separate issue)
    ▼
Terminal UI
    │
    │ Displays: "attacker-kali"  ❌
    │ Expected: "Attacker"
    ▼
EC2 Instance
    │
    │ Hostname: "shifter-kali-123"  (hardcoded)
    │ Expected: "Attacker" or similar
```

---

## Files Touched

| File | Line(s) | Issue |
|------|---------|-------|
| [cyberscript/schemas/range.py](shifter/cyberscript/schemas/range.py) | 121 | **PRIMARY BUG**: Overwrites template name |
| [engine/provisioner/components/instance.py](shifter/engine/provisioner/components/instance.py) | 225-252 | Hostname hardcoded, ignores display_name |

---

## Fix Required

### Primary Fix - Use Template Name

In [cyberscript/schemas/range.py:121](shifter/cyberscript/schemas/range.py#L121):

**Current** (broken):
```python
return cls(
    name=f"{role}-{os_type}",  # Overwrites template name
    ...
)
```

**Fixed**:
```python
return cls(
    name=name,  # Use the template name from _extract_required_fields()
    ...
)
```

### Secondary Fix - Use Name for Hostname (if desired)

In [engine/provisioner/components/instance.py](shifter/engine/provisioner/components/instance.py), the hostname generation could optionally use `display_name`:

```python
# Current (hardcoded):
self.hostname = f"shifter-kali-{range_id}"

# Potential fix (uses display_name):
safe_name = re.sub(r'[^a-zA-Z0-9-]', '', display_name.lower())[:15]
self.hostname = f"shifter-{safe_name}-{range_id}"
```

Note: Hostname has length and character restrictions, so the template name would need sanitization.
