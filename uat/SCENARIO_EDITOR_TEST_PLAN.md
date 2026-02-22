# Scenario Editor - Executable Test Plan

## Features to Test

From code analysis (services.py, views.py, registry.py):

**Core Operations:**
1. create_scenario() - Create custom scenario with Pydantic validation
2. update_scenario() - Update custom scenario (not defaults)
3. delete_scenario() - Soft delete (sets deleted_at timestamp)
4. clone_scenario() - Clone any scenario to new custom scenario
5. export_scenario_yaml() - Export as YAML string
6. validate_yaml() - Parse and validate YAML against schema
7. validate_definition() - Validate dict against ScenarioTemplate

**Metadata Operations:**
8. update_metadata() - Toggle enabled/staff_only flags

**Registry Operations:**
9. list_all_scenarios() - Unified list from YAML + DB with filtering
10. get_scenario_detail() - Get single scenario (DB first, then YAML)
11. load_scenario_template() - Load for range hydration
12. is_default_scenario() - Check if YAML default

**Web Views (11 endpoints):**
- scenario_list - List all
- scenario_create_form - Create via form
- scenario_yaml_create - Create via YAML
- validate_yaml_view - API validation endpoint
- scenario_detail_view - View detail
- scenario_edit_form - Edit via form
- scenario_yaml_editor - Edit via YAML
- scenario_delete_view - Delete
- scenario_clone_view - Clone
- scenario_toggle_enabled - Toggle enabled
- scenario_toggle_staff_only - Toggle staff_only
- scenario_export_view - Export YAML download

---

## How I Will Test

### 1. Database State Verification

Query dev database to check:
- Current scenarios in cms_scenario table
- Metadata in cms_scenariometadata table
- Soft delete status (deleted_at)
- Definition structure (JSON)

### 2. Create Test Scenarios

Execute SQL to create test scenarios directly:
- Minimal scenario (1 instance, 1 subnet)
- Complex scenario (multiple instances, subnets, DC config)
- Invalid scenarios (for validation testing)

### 3. Verify Pydantic Validation

Test schema validation catches:
- Missing required fields (id, name, description, instances)
- Empty instances array
- Invalid subnet references
- Invalid enum values (role, os_type)
- Missing dc_config when domain_controller=true
- Empty subnet instances array

### 4. Verify Metadata System

Test metadata overlay:
- Default behavior (enabled=true, staff_only=false)
- Metadata on custom scenarios
- Metadata on YAML defaults
- Filtering for non-staff users

### 5. Verify Registry

Test unified registry:
- Lists both YAML defaults and DB customs
- Applies metadata overlays correctly
- Handles deleted scenarios (excluded from lists)
- DB scenarios take precedence over YAML with same ID

### 6. Verify CRUD Constraints

Test business rules:
- Cannot edit default YAML scenarios
- Cannot delete default YAML scenarios
- Scenario ID must be unique (among active scenarios)
- Soft delete allows/prevents ID reuse
- Scenario ID format validation (slug)

### 7. Check Integration

Test scenario usage:
- Range launch can find custom scenarios
- Range spec hydration works
- scenario_id tracked in RangeInstance

### 8. Check Logs for Errors

Query CloudWatch logs for:
- Validation errors
- 500 errors
- Failed scenario operations

---

## Test Execution

### TEST 1: Check Current Database State

**Query:**
```sql
SELECT scenario_id, name, deleted_at, created_at
FROM cms_scenario
ORDER BY created_at DESC
LIMIT 10;
```

**Success:** Returns list of scenarios (or empty if none)

---

### TEST 2: Check Default YAML Scenarios

**Query:**
```sql
SELECT scenario_id, enabled, staff_only
FROM cms_scenariometadata
WHERE scenario_id IN ('basic', 'ad_attack_lab', 'xdr_demo');
```

**Success:** Shows metadata overlays on defaults (if any exist)

---

### TEST 3: Check Scenario Definition Structure

**Query:**
```sql
SELECT
    scenario_id,
    definition->'instances' as instances,
    definition->'subnets' as subnets,
    definition->'ngfw' as ngfw
FROM cms_scenario
WHERE deleted_at IS NULL
LIMIT 1;
```

**Success:** JSON structure matches expected format

---

### TEST 4: Create Test Scenario

**Execute:**
```sql
INSERT INTO cms_scenario (
    id, scenario_id, name, description, definition,
    created_by_id, updated_by_id, created_at, updated_at
) VALUES (
    gen_random_uuid(),
    'uat-test-scenario',
    'UAT Test Scenario',
    'Test scenario for UAT verification',
    '{"ngfw": false, "instances": [{"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": false}], "subnets": [{"name": "core", "instances": ["Attacker"], "connected_to": []}]}'::jsonb,
    (SELECT id FROM auth_user WHERE is_staff = true LIMIT 1),
    (SELECT id FROM auth_user WHERE is_staff = true LIMIT 1),
    NOW(),
    NOW()
);
```

**Verify:**
```sql
SELECT scenario_id, name FROM cms_scenario WHERE scenario_id = 'uat-test-scenario';
```

**Success:** Scenario created and queryable

---

### TEST 5: Check Pydantic Validation on Save

The Scenario model validates on save. Try creating invalid scenario:

**Execute:**
```sql
INSERT INTO cms_scenario (
    id, scenario_id, name, description, definition,
    created_by_id, updated_by_id, created_at, updated_at
) VALUES (
    gen_random_uuid(),
    'uat-invalid',
    'UAT Invalid',
    'Test invalid definition',
    '{"ngfw": false, "instances": [], "subnets": []}'::jsonb,
    (SELECT id FROM auth_user WHERE is_staff = true LIMIT 1),
    (SELECT id FROM auth_user WHERE is_staff = true LIMIT 1),
    NOW(),
    NOW()
);
```

**Expected:** Should fail due to empty instances array
**Note:** Model validation happens in app layer, not DB layer. Need to test via Python.

---

### TEST 6: Test Soft Delete

**Execute:**
```sql
UPDATE cms_scenario
SET deleted_at = NOW()
WHERE scenario_id = 'uat-test-scenario';
```

**Verify:**
```sql
SELECT scenario_id, deleted_at FROM cms_scenario WHERE scenario_id = 'uat-test-scenario';
```

**Success:** deleted_at timestamp set

---

### TEST 7: Verify Soft Delete Filters

**Query:**
```sql
SELECT scenario_id FROM cms_scenario WHERE deleted_at IS NULL;
```

**Success:** uat-test-scenario NOT in results

---

### TEST 8: Test Metadata Creation

**Execute:**
```sql
INSERT INTO cms_scenariometadata (scenario_id, enabled, staff_only, updated_by_id, updated_at)
VALUES (
    'uat-test-scenario',
    false,
    true,
    (SELECT id FROM auth_user WHERE is_staff = true LIMIT 1),
    NOW()
);
```

**Verify:**
```sql
SELECT scenario_id, enabled, staff_only FROM cms_scenariometadata WHERE scenario_id = 'uat-test-scenario';
```

**Success:** Metadata row created

---

### TEST 9: Test Metadata on Default Scenarios

**Execute:**
```sql
INSERT INTO cms_scenariometadata (scenario_id, enabled, staff_only, updated_by_id, updated_at)
VALUES (
    'basic',
    false,
    false,
    (SELECT id FROM auth_user WHERE is_staff = true LIMIT 1),
    NOW()
)
ON CONFLICT (scenario_id) DO UPDATE
SET enabled = false, updated_at = NOW();
```

**Verify:**
```sql
SELECT scenario_id, enabled FROM cms_scenariometadata WHERE scenario_id = 'basic';
```

**Success:** Metadata overlay on default YAML scenario

---

### TEST 10: Check Unique Constraint

**Execute:**
```sql
INSERT INTO cms_scenario (
    id, scenario_id, name, description, definition,
    created_by_id, updated_by_id, created_at, updated_at
) VALUES (
    gen_random_uuid(),
    'uat-test-scenario',
    'Duplicate',
    'Should fail',
    '{"ngfw": false, "instances": [{"name": "A", "role": "attacker", "os_type": "kali"}], "subnets": []}'::jsonb,
    (SELECT id FROM auth_user WHERE is_staff = true LIMIT 1),
    (SELECT id FROM auth_user WHERE is_staff = true LIMIT 1),
    NOW(),
    NOW()
);
```

**Expected:** Fails due to unique constraint on scenario_id (where deleted_at IS NULL)

---

### TEST 11: Check Range Integration

**Query:**
```sql
SELECT
    r.range_id,
    r.scenario_id,
    r.status,
    r.created_at
FROM cms_rangeinstance r
WHERE r.scenario_id IS NOT NULL
ORDER BY r.created_at DESC
LIMIT 10;
```

**Success:** Shows ranges launched with scenario_id tracked

---

### TEST 12: Check for Recent Errors in Logs

**CloudWatch Query:**
Component: `portal`
Filter: `ERROR` or `scenario` or `ScenarioEditorError`

**Success:** No unexpected errors in recent logs

---

### TEST 13: Verify Scenario ID Format Validation

**Test Cases:**
- `valid-scenario-id` ✓
- `valid_scenario_id` ✓
- `valid123` ✓
- `Invalid-ID` ✗ (uppercase)
- `invalid id` ✗ (space)
- `-invalid` ✗ (starts with hyphen)
- `invalid-` ✗ (ends with hyphen)

**Implementation:** Regex pattern: `^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$`

---

### TEST 14: Verify Definition Structure

Required in definition JSON:
```json
{
  "ngfw": boolean,
  "instances": [
    {
      "name": string,
      "role": "attacker"|"victim"|"dc",
      "os_type": "kali"|"windows"|"ubuntu"|"from_agent",
      "xdr_agent": boolean,
      "domain_controller": boolean,
      "join_domain": boolean,
      "dc_config": {
        "domain_name": string,
        "netbios_name": string
      }
    }
  ],
  "subnets": [
    {
      "name": string,
      "instances": [string],
      "connected_to": [string]
    }
  ]
}
```

---

## Success Criteria

**Database Layer:**
- [  ] Scenarios can be created in cms_scenario
- [  ] Soft delete sets deleted_at timestamp
- [  ] Unique constraint enforced on active scenarios
- [  ] Metadata can be applied to any scenario_id
- [  ] Definition JSON structure is valid

**Validation Layer:**
- [  ] Empty instances array rejected
- [  ] Invalid subnet references caught
- [  ] Invalid enum values caught
- [  ] Missing dc_config caught
- [  ] Scenario ID format validated

**Registry Layer:**
- [  ] Lists both YAML defaults and DB customs
- [  ] Applies metadata overlays correctly
- [  ] Filters soft-deleted scenarios
- [  ] Handles enabled/staff_only filtering

**Integration:**
- [  ] Range launch can use custom scenarios
- [  ] scenario_id tracked in RangeInstance
- [  ] No errors in recent logs

**Business Rules:**
- [  ] Cannot edit default YAML scenarios
- [  ] Cannot delete default YAML scenarios
- [  ] Scenario IDs must be unique
- [  ] Slug format enforced

---

## Cleanup

After testing:
```sql
-- Delete test scenarios
DELETE FROM cms_scenario WHERE scenario_id LIKE 'uat-%';

-- Delete test metadata
DELETE FROM cms_scenariometadata WHERE scenario_id LIKE 'uat-%';

-- Reset any modified default metadata
DELETE FROM cms_scenariometadata WHERE scenario_id = 'basic';
```
