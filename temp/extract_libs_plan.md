# Provisioner Type Safety Assessment

## Status

**Previous Plan (Subnet Flow Issues):** COMPLETE - All 18 issues fixed and merged.

This plan assesses type safety improvements for the provisioner codebase.

---

## Key Finding: Shared Module Already Has Pydantic Models

**Location:** `shifter/shifter_platform/shared/schemas/`

The shared module already contains well-designed Pydantic models that mirror provisioner concepts:

| Shared Model | Provisioner Equivalent | Status |
|--------------|------------------------|--------|
| `RangeSpec` | `RangeConfig` dataclass | Duplicate |
| `SubnetSpec` | `SubnetConfig` dataclass | Duplicate |
| `InstanceSpec` | `InstanceConfig` dataclass | Duplicate |
| `NGFWAppSpec` | untyped dict | Missing type |
| `DCConfig` | `dc_config: dict` | Missing type |
| `AgentDetails` | `agent: dict` | Missing type |

**Current Problem:** Provisioner reads JSON from DB and converts to local dataclasses in `config.py`, duplicating the Pydantic models.

---

## Recommended Approach: Extract Shared Library

Instead of creating new TypedDict definitions, extract the existing Pydantic models to a location importable by the provisioner.

---

## Phase 1: Create Shared Types Package (HIGH Priority)

### 1.1 Extract Core Types to Shared Package

**New location:** `shifter/shared/` (top-level, importable by all components)

Extract these models from `shifter_platform/shared/schemas/`:
- `SpecBase` (base.py)
- `RangeSpec`, `InstanceSpec`, `AgentDetails`, `DCConfig` (range.py)
- `SubnetSpec` (subnet.py)
- `NGFWAppSpec` (app.py)

**Structure:**
```
shifter/shared/
├── __init__.py
├── schemas/
│   ├── __init__.py
│   ├── base.py      # SpecBase
│   ├── range.py     # RangeSpec, InstanceSpec, AgentDetails, DCConfig
│   ├── subnet.py    # SubnetSpec
│   └── ngfw.py      # NGFWAppSpec (extracted subset)
└── enums.py         # Role, OSType enums
```

### 1.2 Update shifter_platform to Import from Shared

Update `shifter_platform/shared/schemas/` to re-export from `shifter/shared/`:
```python
# shifter_platform/shared/schemas/range.py
from shifter.shared.schemas.range import RangeSpec, InstanceSpec, DCConfig, AgentDetails
```

This maintains backward compatibility while enabling provisioner access.

---

## Phase 2: Update Provisioner to Use Shared Types (HIGH Priority)

### 2.1 Replace config.py Dataclasses with Pydantic

**File:** `shifter/engine/provisioner/config.py`

Replace local dataclasses with imports from shared:

```python
# Before (duplicate definitions)
@dataclass
class InstanceConfig:
    uuid: str
    role: str
    os_type: str
    ...

# After (import from shared)
from shifter.shared.schemas.range import InstanceSpec
from shifter.shared.schemas.subnet import SubnetSpec

# Use Pydantic models directly
def build_range_config(range_data: dict) -> RangeSpec:
    """Parse and validate range config from database."""
    return RangeSpec.model_validate(range_data["range_config"])
```

### 2.2 Add Pydantic Validation at DB Boundary

**File:** `shifter/engine/provisioner/main.py`

Validate JSON immediately after loading from database:

```python
def get_range_data_by_request_id(request_id: str) -> RangeSpec:
    """Load and validate range config from database."""
    with get_db_connection() as conn:
        row = conn.execute(...).fetchone()

    # Validate with Pydantic (catches schema errors at boundary)
    return RangeSpec.model_validate(row["range_config"])
```

---

## Phase 3: Add Provisioner-Specific Types (MEDIUM Priority)

Some types are provisioner-specific (not in shared). Add these as TypedDicts:

### 3.1 Pulumi Output Types

**File:** `shifter/engine/provisioner/types.py` (new)

```python
from typing import TypedDict, NotRequired

class SubnetOutput(TypedDict):
    """Pulumi output for a provisioned subnet."""
    uuid: str
    subnet_id: str
    subnet_cidr: str
    security_group_id: str
    route_table_id: str
    gwlb_endpoint_id: str | None

class InstanceOutput(TypedDict):
    """Pulumi output for a provisioned instance."""
    uuid: str
    role: str
    os: str
    subnet_name: str
    instance_id: str
    private_ip: str
    ssh_key_secret_arn: str

class PulumiStackOutputs(TypedDict):
    """Complete Pulumi stack outputs."""
    subnets: dict[str, SubnetOutput]
    instances: list[InstanceOutput]
    dcConfigParamName: NotRequired[str]
```

### 3.2 DB Query Return Types

```python
class NGFWInstanceState(TypedDict):
    """State stored in database for NGFW instance."""
    ec2_instance_id: str | None
    management_ip: str | None
    ssh_key_secret_arn: str | None

class InstanceState(TypedDict):
    """State stored in database for range instance."""
    aws_instance_id: str
    private_ip: str
    ssh_key_secret_arn: str
    subnet_name: str
```

---

## Phase 4: Fix Function Signatures (LOW Priority)

### 4.1 Fix env: dict Parameters

Use `dict[str, str]` for subprocess environment:

**Locations:**
- `main.py:1008` - `_run_provision()`
- `main.py:1115` - `_run_destroy()`
- `main.py:1280` - `_run_ngfw_provision()`

### 4.2 Replace Magic String Keys

Create constants for Pulumi config keys to prevent typos:

```python
class PulumiConfigKey:
    RANGE_ID = "rangeId"
    ENVIRONMENT = "environment"
    RANGE_VPC_ID = "rangeVpcId"
```

---

## Implementation Order

1. **Phase 1** - Create `shifter/shared/` package with extracted Pydantic models
2. **Phase 2** - Update provisioner to import from shared, remove duplicate dataclasses
3. **Phase 3** - Add provisioner-specific TypedDicts for Pulumi outputs
4. **Phase 4** - Fix loose function signatures (env: dict, etc.)

---

## Verification

1. **Static Analysis:**
   - Run `mypy shifter/shared/` - verify Pydantic models pass
   - Run `mypy shifter/engine/provisioner/` - verify imports work

2. **Unit Tests:**
   - Test Pydantic validation catches missing fields
   - Test shared models can be imported from both locations
   - Verify existing provisioner tests pass

3. **Integration:**
   - Run provisioner in dev environment
   - Create/destroy a range to verify end-to-end

---

## Files Modified

| File | Changes |
|------|---------|
| `shifter/shared/` (new package) | Extracted Pydantic models |
| `shifter_platform/shared/schemas/*.py` | Re-export from shared |
| `engine/provisioner/config.py` | Import from shared, remove duplicates |
| `engine/provisioner/main.py` | Use Pydantic models at boundaries |
| `engine/provisioner/types.py` (new) | Provisioner-specific TypedDicts |

---

## Decision: Pydantic for Shared, TypedDict for Local

**Shared models:** Use Pydantic (already built, provides validation)
- `RangeSpec`, `SubnetSpec`, `InstanceSpec`, `NGFWAppSpec`, `DCConfig`
- Validated at DB boundary when loading JSON

**Provisioner-local types:** Use TypedDict (zero overhead, Pulumi-specific)
- `PulumiStackOutputs`, `SubnetOutput`, `InstanceOutput`
- No runtime validation needed - these are our own outputs

This hybrid approach:
- Eliminates duplicate definitions
- Validates external data (DB) with Pydantic
- Keeps internal data (Pulumi outputs) lightweight with TypedDict
