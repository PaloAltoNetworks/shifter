# UAT Plan: Scenario Editor

**Version:** 1.0
**Target Environment:** Dev
**Created:** 2026-02-21
**Owner:** SecOps Team

## Table of Contents

- [1. Prerequisites & Environment Setup](#1-prerequisites--environment-setup)
- [2. Test Scope Overview](#2-test-scope-overview)
- [3. Test Data Preparation](#3-test-data-preparation)
- [4. Test Cases](#4-test-cases)
  - [TC-1: Scenario Creation (Form-Based)](#tc-1-scenario-creation-form-based)
  - [TC-2: Scenario Creation (YAML-Based)](#tc-2-scenario-creation-yaml-based)
  - [TC-3: Schema Validation (Cyberscript Validation)](#tc-3-schema-validation-cyberscript-validation)
  - [TC-4: CRUD Operations](#tc-4-crud-operations)
  - [TC-5: Metadata Management](#tc-5-metadata-management)
  - [TC-6: Range Integration (End-to-End)](#tc-6-range-integration-end-to-end)
- [5. Test Execution Log](#5-test-execution-log)
- [6. Known Limitations](#6-known-limitations)

---

## 1. Prerequisites & Environment Setup

### 1.1 Environment Details

- **Dev Environment URL:** `https://dev.shifter.example.com` (replace with actual URL)
- **Scenario Editor URL:** `https://dev.shifter.example.com/scenario_editor/`
- **API Base URL:** `https://dev.shifter.example.com/api/`

### 1.2 Required User Accounts

| User Type | Username | Purpose |
|-----------|----------|---------|
| Staff User | `staff_user@example.com` | Create/edit scenarios, test staff-only features |
| Non-Staff User | `regular_user@example.com` | Test visibility filtering, range launching |

### 1.3 Browser/Tools Requirements

- Modern web browser (Chrome, Firefox, Edge)
- Browser developer tools (for API testing)
- Database access (for validation queries)
- curl or similar HTTP client (for API testing)

### 1.4 Pre-Test Checklist

- [ ] Verify dev environment is accessible
- [ ] Confirm staff user account has staff privileges
- [ ] Confirm non-staff user account lacks staff privileges
- [ ] Verify database access credentials
- [ ] Clear browser cache and cookies
- [ ] List existing default YAML scenarios for reference

### 1.5 Database Connection

Connect to dev database to run validation queries:

```bash
# SSH tunnel to dev environment
ssh -L 5432:localhost:5432 dev.shifter.example.com

# Connect to PostgreSQL
psql -h localhost -U shifter -d shifter_dev
```

---

## 2. Test Scope Overview

### 2.1 Features Covered

**Scenario Management:**
- Create scenarios via form builder
- Create scenarios via YAML editor
- Edit custom scenarios (form and YAML)
- Clone scenarios (default and custom)
- Soft-delete custom scenarios
- Export scenarios as YAML

**Validation:**
- Pydantic schema validation (ScenarioTemplate)
- Slug format validation (scenario_id)
- Real-time YAML validation endpoint
- Instance reference validation in subnets
- Domain controller configuration validation

**Metadata Management:**
- Toggle scenario enabled/disabled state
- Toggle scenario staff-only access
- Metadata overlay on default YAML scenarios

**Integration:**
- Scenario listing via `/api/scenarios/`
- Range launch with custom scenarios via `/api/range/launch/`
- Scenario_id tracking in RangeInstance model
- Visibility filtering (enabled, staff_only)

### 2.2 Out of Scope

- Default YAML scenario editing (read-only by design)
- Range provisioning details (infrastructure layer)
- XDR agent installation workflow
- Actual attack execution within ranges

### 2.3 Test Environment Specifications

- **Platform:** Django 5.x on AWS us-east-2
- **Database:** PostgreSQL with soft-delete pattern
- **Authentication:** Django session-based auth

---

## 3. Test Data Preparation

### 3.1 Valid Scenarios

#### Basic Single-Subnet Scenario

```yaml
id: uat-basic-test
name: UAT Basic Test Scenario
description: Simple scenario with attacker and victim on one subnet for UAT testing.
ngfw: false

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false

  - name: Victim
    role: victim
    os_type: from_agent
    xdr_agent: true

subnets:
  - name: core
    instances: [Attacker, Victim]
```

#### Multi-Subnet Scenario

```yaml
id: uat-multi-subnet
name: UAT Multi-Subnet Test
description: Scenario with multiple subnets and cross-subnet connectivity for UAT testing.
ngfw: false

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false

  - name: WebServer
    role: victim
    os_type: ubuntu
    xdr_agent: true

  - name: Workstation
    role: victim
    os_type: windows
    xdr_agent: true

subnets:
  - name: dmz
    instances: [WebServer]
    connected_to: [internal]

  - name: internal
    instances: [Workstation]

  - name: attacker_net
    instances: [Attacker]
    connected_to: [dmz]
```

#### Domain Controller Scenario

```yaml
id: uat-domain-test
name: UAT Domain Controller Test
description: Active Directory scenario with domain controller and joined workstation for UAT testing.
ngfw: false

instances:
  - name: Attacker
    role: attacker
    os_type: kali
    xdr_agent: false

  - name: DomainController
    role: dc
    os_type: windows
    xdr_agent: true
    domain_controller: true
    dc_config:
      domain_name: uat.local
      netbios_name: UAT

  - name: Workstation
    role: victim
    os_type: windows
    xdr_agent: true
    join_domain: true

subnets:
  - name: ad_network
    instances: [DomainController, Workstation]

  - name: attacker_net
    instances: [Attacker]
    connected_to: [ad_network]
```

### 3.2 Invalid Scenarios (For Validation Testing)

#### Missing Required Fields

```yaml
# Missing 'id' field
name: Invalid Scenario
description: Missing ID field
instances:
  - name: Attacker
    role: attacker
    os_type: kali
```

#### Empty Instances Array

```yaml
id: invalid-empty
name: Invalid Empty Instances
description: Empty instances array
instances: []
```

#### Invalid Subnet Reference

```yaml
id: invalid-subnet-ref
name: Invalid Subnet Reference
description: Subnet references non-existent instance
instances:
  - name: Attacker
    role: attacker
    os_type: kali

subnets:
  - name: core
    instances: [Attacker, NonExistentInstance]
```

#### Invalid Enum Values

```yaml
id: invalid-enums
name: Invalid Enum Values
description: Invalid role and os_type values
instances:
  - name: Attacker
    role: hacker  # Invalid: should be 'attacker', 'victim', or 'dc'
    os_type: debian  # Invalid: should be 'kali', 'windows', 'ubuntu', or 'from_agent'
```

#### Missing DC Config

```yaml
id: invalid-dc-config
name: Invalid DC Config
description: Domain controller without dc_config
instances:
  - name: DomainController
    role: dc
    os_type: windows
    domain_controller: true
    # Missing dc_config
```

---

## 4. Test Cases

### TC-1: Scenario Creation (Form-Based)

#### TC-1.1: Create Basic Scenario with Single Instance

**Objective:** Verify form-based creation of a minimal valid scenario.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/`

**Steps:**
1. Navigate to `/scenario_editor/`
2. Click "Create Scenario (Form)" button
3. Fill in form:
   - Scenario ID: `uat-form-basic`
   - Name: `UAT Form Basic`
   - Description: `Basic scenario created via form`
   - NGFW: Unchecked
   - Add one instance:
     - Name: `Attacker`
     - Role: `attacker`
     - OS Type: `kali`
     - XDR Agent: Unchecked
   - Add one subnet:
     - Name: `core`
     - Instances: `["Attacker"]`
4. Click "Save"

**Expected Result:**
- Redirect to scenario detail page at `/scenario_editor/uat-form-basic/`
- Success message: "Scenario 'UAT Form Basic' created successfully."
- Scenario appears in scenario list
- Database verification:
  ```sql
  SELECT scenario_id, name, deleted_at FROM cms_scenario WHERE scenario_id = 'uat-form-basic';
  -- Should return: uat-form-basic | UAT Form Basic | NULL
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

**Notes:**
_[Any deviations, defects, or observations]_

---

#### TC-1.2: Create Scenario with Multiple Instances and Subnets

**Objective:** Verify form handles complex scenarios with multiple instances and subnets.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/`

**Steps:**
1. Navigate to `/scenario_editor/`
2. Click "Create Scenario (Form)" button
3. Fill in form:
   - Scenario ID: `uat-form-complex`
   - Name: `UAT Form Complex`
   - Description: `Complex scenario with multiple instances and subnets`
   - NGFW: Unchecked
   - Add three instances:
     - Instance 1: `Attacker`, `attacker`, `kali`, XDR: false
     - Instance 2: `WebServer`, `victim`, `ubuntu`, XDR: true
     - Instance 3: `Workstation`, `victim`, `windows`, XDR: true
   - Add two subnets:
     - Subnet 1: `dmz`, Instances: `["WebServer"]`, Connected To: `[]`
     - Subnet 2: `internal`, Instances: `["Workstation"]`, Connected To: `[]`
4. Click "Save"

**Expected Result:**
- Scenario created successfully
- All instances and subnets saved in definition JSON
- Database verification:
  ```sql
  SELECT scenario_id, definition::jsonb->'instances' FROM cms_scenario WHERE scenario_id = 'uat-form-complex';
  -- Should return 3 instances in JSON array
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-1.3: Create Scenario with Domain Controller

**Objective:** Verify form handles domain controller configuration.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/`

**Steps:**
1. Navigate to `/scenario_editor/`
2. Click "Create Scenario (Form)" button
3. Fill in form:
   - Scenario ID: `uat-form-dc`
   - Name: `UAT Form DC`
   - Description: `Domain controller scenario via form`
   - Add DC instance:
     - Name: `DomainController`
     - Role: `dc`
     - OS Type: `windows`
     - XDR Agent: Checked
     - Domain Controller: Checked
     - DC Config:
       - Domain Name: `uat.local`
       - NetBIOS Name: `UAT`
   - Add workstation instance:
     - Name: `Workstation`
     - Role: `victim`
     - OS Type: `windows`
     - XDR Agent: Checked
     - Join Domain: Checked
4. Click "Save"

**Expected Result:**
- DC scenario created with nested dc_config
- Database verification:
  ```sql
  SELECT scenario_id, definition::jsonb->'instances'->0->'dc_config'
  FROM cms_scenario WHERE scenario_id = 'uat-form-dc';
  -- Should return: {"domain_name": "uat.local", "netbios_name": "UAT"}
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-1.4: Validate Form Input Errors

**Objective:** Verify form validation catches invalid inputs.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/form/`

**Test Cases:**

| Sub-Test | Invalid Input | Expected Error Message |
|----------|---------------|------------------------|
| TC-1.4.1 | Empty scenario_id | "Scenario ID is required" |
| TC-1.4.2 | scenario_id = `My Scenario!` (invalid chars) | "Scenario ID must contain only lowercase letters, numbers, hyphens, and underscores" |
| TC-1.4.3 | Empty name | "Name is required" |
| TC-1.4.4 | Empty description | "Description is required" |
| TC-1.4.5 | Empty instances array | "At least one instance is required" |

**Steps:**
For each sub-test:
1. Fill in form with the invalid input
2. Submit form
3. Verify error message appears
4. Verify scenario is NOT created

**Expected Result:**
- All validation errors displayed correctly
- No scenarios created in database

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-1.5: Verify Slug Format Validation

**Objective:** Verify scenario_id follows slug format rules.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/form/`

**Test Cases:**

| Sub-Test | scenario_id Value | Expected Result |
|----------|-------------------|-----------------|
| TC-1.5.1 | `valid-slug-123` | ✓ Accepted |
| TC-1.5.2 | `another_valid_slug` | ✓ Accepted |
| TC-1.5.3 | `CamelCase` | ✗ Rejected (uppercase) |
| TC-1.5.4 | `has spaces` | ✗ Rejected (spaces) |
| TC-1.5.5 | `special@chars!` | ✗ Rejected (special chars) |
| TC-1.5.6 | `-starts-with-dash` | ✗ Rejected (starts with dash) |
| TC-1.5.7 | `ends-with-dash-` | ✗ Rejected (ends with dash) |

**Steps:**
For each sub-test:
1. Attempt to create scenario with given scenario_id
2. Verify acceptance or rejection matches expected result

**Expected Result:**
- Only valid slug formats accepted
- Clear error messages for invalid formats

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-2: Scenario Creation (YAML-Based)

#### TC-2.1: Create Scenario from YAML Template

**Objective:** Verify YAML-based creation with valid YAML.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/`

**Steps:**
1. Navigate to `/scenario_editor/`
2. Click "Create Scenario (YAML)" button
3. Replace template YAML with valid test data (use "Basic Single-Subnet Scenario" from section 3.1)
4. Click "Save"

**Expected Result:**
- Scenario created successfully
- Redirect to detail page
- Success message displayed
- Database verification:
  ```sql
  SELECT scenario_id, name FROM cms_scenario WHERE scenario_id = 'uat-basic-test';
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-2.2: Validate YAML Syntax Errors

**Objective:** Verify YAML parser catches syntax errors.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/yaml/`

**Test Cases:**

| Sub-Test | Invalid YAML | Expected Error |
|----------|--------------|----------------|
| TC-2.2.1 | Missing colon after key | YAML parse error |
| TC-2.2.2 | Incorrect indentation | YAML parse error |
| TC-2.2.3 | Unmatched brackets | YAML parse error |
| TC-2.2.4 | Invalid list syntax | YAML parse error |

**Steps:**
For each sub-test:
1. Enter invalid YAML
2. Click "Validate" button
3. Verify error message appears

**Expected Result:**
- All syntax errors caught
- Clear error messages with line numbers if possible

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-2.3: Test Real-Time YAML Validation Endpoint

**Objective:** Verify `/scenario_editor/validate-yaml/` endpoint works correctly.

**Prerequisites:**
- Logged in as staff user
- Browser dev tools open

**Steps:**
1. Navigate to `/scenario_editor/create/yaml/`
2. Open browser Network tab
3. Enter valid YAML
4. Click "Validate" button
5. Observe POST request to `/scenario_editor/validate-yaml/`
6. Verify response

**Expected Result:**
- POST request to `/scenario_editor/validate-yaml/`
- Response 200 OK with JSON:
  ```json
  {
    "valid": true,
    "errors": [],
    "definition": { ... }
  }
  ```

**Using curl:**
```bash
curl -X POST https://dev.shifter.example.com/scenario_editor/validate-yaml/ \
  -H "Content-Type: application/json" \
  -H "Cookie: sessionid=<your-session-id>" \
  -d '{"yaml_content": "id: test\nname: Test\ndescription: Test\ninstances:\n  - name: Attacker\n    role: attacker\n    os_type: kali\n"}'
```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-2.4: Import Valid YAML Scenario

**Objective:** Verify YAML import with all field types (instances, subnets, dc_config).

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/yaml/`

**Steps:**
1. Navigate to `/scenario_editor/create/yaml/`
2. Paste "Domain Controller Scenario" from section 3.1
3. Click "Validate" to verify structure
4. Click "Save"

**Expected Result:**
- Complex scenario created with all nested structures
- Database verification:
  ```sql
  SELECT
    scenario_id,
    definition::jsonb->'instances' as instances,
    definition::jsonb->'subnets' as subnets
  FROM cms_scenario
  WHERE scenario_id = 'uat-domain-test';
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-3: Schema Validation (Cyberscript Validation)

#### TC-3.1: Missing Required Fields

**Objective:** Verify Pydantic validation catches missing required fields.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/yaml/`

**Test Cases:**

| Sub-Test | Missing Field | Expected Error |
|----------|---------------|----------------|
| TC-3.1.1 | `id` | "YAML must include an 'id' field" |
| TC-3.1.2 | `name` | "YAML must include a 'name' field" |
| TC-3.1.3 | `description` | "YAML must include a 'description' field" |
| TC-3.1.4 | `instances` | Validation error mentioning missing instances |

**Steps:**
For each sub-test:
1. Enter YAML with missing field
2. Click "Validate" or attempt to save
3. Verify appropriate error message

**Expected Result:**
- All required fields validated
- Clear error messages indicating which field is missing

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-3.2: Empty Instances Array

**Objective:** Verify validation rejects scenarios with empty instances.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/yaml/`

**Steps:**
1. Enter YAML from section 3.2 ("Empty Instances Array")
2. Click "Validate"

**Expected Result:**
- Validation error: "instances must not be empty"

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-3.3: Invalid Subnet Instance References

**Objective:** Verify validation catches subnet references to non-existent instances.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/yaml/`

**Steps:**
1. Enter YAML from section 3.2 ("Invalid Subnet Reference")
2. Click "Validate"

**Expected Result:**
- Validation error: "Subnet 'core' references unknown instance 'NonExistentInstance'"

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-3.4: Invalid Enum Values

**Objective:** Verify validation rejects invalid enum values for role and os_type.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/yaml/`

**Valid Enum Values:**
- **role:** `attacker`, `victim`, `dc`
- **os_type:** `kali`, `windows`, `ubuntu`, `from_agent`

**Steps:**
1. Enter YAML with invalid role: `hacker`
2. Click "Validate"
3. Verify error
4. Enter YAML with invalid os_type: `debian`
5. Click "Validate"
6. Verify error

**Expected Result:**
- Clear validation errors indicating invalid enum values
- Error messages list valid options

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-3.5: Nested Validation (DC Config Structure)

**Objective:** Verify nested dc_config structure validation.

**Prerequisites:**
- Logged in as staff user
- At `/scenario_editor/create/yaml/`

**Test Cases:**

| Sub-Test | Invalid DC Config | Expected Error |
|----------|-------------------|----------------|
| TC-3.5.1 | domain_controller=true but no dc_config | Validation error |
| TC-3.5.2 | dc_config missing domain_name | Field required error |
| TC-3.5.3 | dc_config missing netbios_name | Field required error |

**Steps:**
For each sub-test:
1. Enter YAML with invalid dc_config
2. Attempt to validate/save
3. Verify error message

**Expected Result:**
- Nested validation catches all dc_config errors
- Clear messages about required nested fields

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-4: CRUD Operations

#### TC-4.1: Edit Custom Scenario (Form)

**Objective:** Verify editing custom scenarios via form.

**Prerequisites:**
- Custom scenario `uat-form-basic` created (from TC-1.1)
- Logged in as staff user

**Steps:**
1. Navigate to `/scenario_editor/uat-form-basic/`
2. Click "Edit (Form)" button
3. Update fields:
   - Name: `UAT Form Basic (Updated)`
   - Description: `Updated description`
4. Click "Save"

**Expected Result:**
- Success message: "Scenario updated successfully."
- Changes reflected in detail view
- Database verification:
  ```sql
  SELECT name, description, updated_at FROM cms_scenario WHERE scenario_id = 'uat-form-basic';
  -- Should show updated values and recent timestamp
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-4.2: Edit Custom Scenario (YAML)

**Objective:** Verify editing custom scenarios via YAML editor.

**Prerequisites:**
- Custom scenario `uat-basic-test` created (from TC-2.1)
- Logged in as staff user

**Steps:**
1. Navigate to `/scenario_editor/uat-basic-test/`
2. Click "Edit (YAML)" button
3. Modify YAML:
   - Change name to `UAT Basic Test (YAML Updated)`
   - Add another instance
4. Click "Validate" to verify changes
5. Click "Save"

**Expected Result:**
- Scenario updated with new definition
- Success message displayed
- New instance appears in detail view

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-4.3: Clone Scenario with New ID

**Objective:** Verify cloning creates independent copy.

**Prerequisites:**
- Scenario `uat-basic-test` exists
- Logged in as staff user

**Steps:**
1. Navigate to `/scenario_editor/uat-basic-test/`
2. Click "Clone" button
3. Enter new scenario ID: `uat-cloned-scenario`
4. Enter new name: `UAT Cloned Scenario`
5. Click "Clone"

**Expected Result:**
- New scenario created with new ID
- Original scenario unchanged
- Database verification:
  ```sql
  SELECT scenario_id, name FROM cms_scenario WHERE scenario_id IN ('uat-basic-test', 'uat-cloned-scenario');
  -- Should return both rows
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-4.4: Soft Delete Custom Scenario

**Objective:** Verify soft-delete pattern (deleted_at timestamp).

**Prerequisites:**
- Custom scenario `uat-cloned-scenario` exists
- Logged in as staff user

**Steps:**
1. Navigate to `/scenario_editor/uat-cloned-scenario/`
2. Click "Delete" button
3. Confirm deletion

**Expected Result:**
- Success message: "Scenario deleted successfully."
- Scenario removed from scenario list
- Database verification (soft-delete):
  ```sql
  SELECT scenario_id, deleted_at FROM cms_scenario WHERE scenario_id = 'uat-cloned-scenario';
  -- Should return row with deleted_at timestamp NOT NULL
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-4.5: Verify Default Scenarios Cannot Be Edited/Deleted

**Objective:** Verify default YAML scenarios are read-only.

**Prerequisites:**
- Default scenario exists (e.g., `basic`, `ad_attack_lab`)
- Logged in as staff user

**Steps:**
1. List all scenarios at `/scenario_editor/`
2. Identify a default scenario (is_default = true)
3. Navigate to detail page
4. Verify no "Edit (Form)" or "Edit (YAML)" buttons shown
5. Verify "Delete" button not present or disabled
6. Attempt to access edit URL directly: `/scenario_editor/<default-id>/edit/form/`

**Expected Result:**
- Edit/delete buttons hidden or disabled for default scenarios
- Direct URL access returns 403 Forbidden
- Error message: "Default scenarios cannot be edited. Clone it to create an editable copy."

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-4.6: Export Scenario as YAML File

**Objective:** Verify YAML export functionality.

**Prerequisites:**
- Scenario `uat-domain-test` exists
- Logged in as staff user

**Steps:**
1. Navigate to `/scenario_editor/uat-domain-test/`
2. Click "Export YAML" button
3. Verify file download

**Expected Result:**
- File downloaded: `uat-domain-test.yaml`
- File content matches scenario structure
- File contains valid YAML
- Response headers:
  - `Content-Type: text/yaml`
  - `Content-Disposition: attachment; filename="uat-domain-test.yaml"`

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-5: Metadata Management

#### TC-5.1: Toggle Scenario Enabled/Disabled

**Objective:** Verify enabled flag controls scenario visibility.

**Prerequisites:**
- Custom scenario `uat-form-basic` exists and is enabled
- Logged in as staff user

**Steps:**
1. Navigate to `/scenario_editor/`
2. Locate `uat-form-basic` in list
3. Verify current state: Enabled
4. Click "Disable" button
5. Refresh page
6. Verify state changed to: Disabled
7. Click "Enable" button
8. Verify state changed back to: Enabled

**Expected Result:**
- Toggle button updates metadata
- Database verification:
  ```sql
  SELECT scenario_id, enabled FROM cms_scenariometadata WHERE scenario_id = 'uat-form-basic';
  -- Should toggle between true and false
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-5.2: Toggle Scenario Staff-Only Access

**Objective:** Verify staff_only flag restricts access.

**Prerequisites:**
- Custom scenario `uat-form-basic` exists
- Logged in as staff user

**Steps:**
1. Navigate to `/scenario_editor/`
2. Locate `uat-form-basic` in list
3. Verify current state: All Users
4. Click "Make Staff Only" button
5. Refresh page
6. Verify state changed to: Staff Only
7. Click "Make Public" button
8. Verify state changed back to: All Users

**Expected Result:**
- Toggle button updates metadata
- Database verification:
  ```sql
  SELECT scenario_id, staff_only FROM cms_scenariometadata WHERE scenario_id = 'uat-form-basic';
  -- Should toggle between true and false
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-5.3: Verify Disabled Scenarios Hidden from Non-Staff API

**Objective:** Verify disabled scenarios don't appear in non-staff scenario listings.

**Prerequisites:**
- Scenario `uat-form-basic` exists and is disabled
- Non-staff user account available

**Steps:**
1. Log in as staff user
2. Disable scenario `uat-form-basic` at `/scenario_editor/`
3. Log out
4. Log in as non-staff user
5. Navigate to `/api/scenarios/` (or use curl)
6. Verify `uat-form-basic` NOT in list

**API Test:**
```bash
# As non-staff user
curl -H "Authorization: Bearer <non-staff-token>" \
  https://dev.shifter.example.com/api/scenarios/
```

**Expected Result:**
- Disabled scenario not visible to non-staff users
- Staff users still see it in scenario editor

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-5.4: Verify Staff-Only Scenarios Hidden from Non-Staff API

**Objective:** Verify staff_only scenarios restricted to staff users.

**Prerequisites:**
- Scenario `uat-form-basic` exists and is enabled but staff-only
- Non-staff user account available

**Steps:**
1. Log in as staff user
2. Enable scenario `uat-form-basic`
3. Set to "Staff Only"
4. Log out
5. Log in as non-staff user
6. Navigate to `/api/scenarios/`
7. Verify `uat-form-basic` NOT in list
8. Log back in as staff user
9. Verify scenario IS visible

**Expected Result:**
- Staff-only scenario hidden from non-staff users
- Staff-only scenario visible to staff users

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-5.5: Verify Metadata Overlay on Default YAML Scenarios

**Objective:** Verify metadata can be applied to default YAML scenarios.

**Prerequisites:**
- Default scenario exists (e.g., `basic`)
- No existing metadata for this scenario
- Logged in as staff user

**Steps:**
1. Navigate to `/scenario_editor/`
2. Locate default scenario (e.g., `basic`)
3. Click "Disable" button
4. Verify scenario marked as disabled

**Expected Result:**
- Metadata row created in cms_scenariometadata
- Default YAML scenario unchanged (still in templates/ directory)
- Database verification:
  ```sql
  SELECT scenario_id, enabled FROM cms_scenariometadata WHERE scenario_id = 'basic';
  -- Should create new row: basic | false
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-6: Range Integration (End-to-End)

#### TC-6.1: List Scenarios via API as Staff User

**Objective:** Verify staff users see all enabled scenarios (default and custom).

**Prerequisites:**
- Multiple scenarios exist (both default and custom)
- Some scenarios enabled, some disabled
- Logged in as staff user

**Steps:**
1. Call `/api/scenarios/` as staff user

**API Test:**
```bash
curl -H "Authorization: Bearer <staff-token>" \
  https://dev.shifter.example.com/api/scenarios/
```

**Expected Result:**
- Response includes all enabled scenarios (staff_only ignored for staff)
- Response includes both default YAML and custom DB scenarios
- Disabled scenarios excluded
- Response format:
  ```json
  {
    "scenarios": [
      {
        "id": "uat-form-basic",
        "name": "UAT Form Basic",
        "description": "...",
        "is_default": false,
        "enabled": true,
        "staff_only": false
      },
      ...
    ]
  }
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-6.2: List Scenarios via API as Non-Staff User

**Objective:** Verify non-staff users only see enabled, non-staff-only scenarios.

**Prerequisites:**
- Multiple scenarios with varying metadata
- Logged in as non-staff user

**Steps:**
1. Call `/api/scenarios/` as non-staff user

**API Test:**
```bash
curl -H "Authorization: Bearer <non-staff-token>" \
  https://dev.shifter.example.com/api/scenarios/
```

**Expected Result:**
- Response excludes disabled scenarios
- Response excludes staff-only scenarios
- Only public, enabled scenarios returned

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-6.3: Launch Range with Enabled Custom Scenario

**Objective:** Verify custom scenarios can be used for range provisioning.

**Prerequisites:**
- Custom scenario `uat-form-basic` exists and is enabled
- Logged in as staff or non-staff user
- Range launch API endpoint available

**Steps:**
1. Call `/api/range/launch/` with scenario_id: `uat-form-basic`

**API Test:**
```bash
curl -X POST https://dev.shifter.example.com/api/range/launch/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "uat-form-basic",
    "agent_distribution_id": "<agent-dist-id>",
    "name": "UAT Test Range"
  }'
```

**Expected Result:**
- Range creation initiated (201 Created or 202 Accepted)
- Response includes range_id
- Database verification:
  ```sql
  SELECT range_id, scenario_id, status FROM cms_rangeinstance WHERE scenario_id = 'uat-form-basic' ORDER BY created_at DESC LIMIT 1;
  -- Should return new range with scenario_id
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-6.4: Verify Disabled Scenario Not Available for Launch

**Objective:** Verify disabled scenarios rejected at range launch.

**Prerequisites:**
- Scenario `uat-form-basic` exists and is disabled
- Logged in as non-staff user

**Steps:**
1. Disable scenario `uat-form-basic`
2. Attempt to launch range with disabled scenario

**API Test:**
```bash
curl -X POST https://dev.shifter.example.com/api/range/launch/ \
  -H "Authorization: Bearer <non-staff-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "uat-form-basic",
    "agent_distribution_id": "<agent-dist-id>",
    "name": "UAT Test Range"
  }'
```

**Expected Result:**
- API returns 400 Bad Request or 404 Not Found
- Error message: "Scenario not found" or "Scenario not available"
- No range created

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-6.5: Launch Range and Verify Scenario ID Recorded in RangeInstance

**Objective:** Verify scenario_id tracked in range instance for auditing.

**Prerequisites:**
- Scenario `uat-form-basic` exists and is enabled
- Logged in as staff user

**Steps:**
1. Launch range with `uat-form-basic` (API or UI)
2. Note returned range_id
3. Query database for range instance

**Expected Result:**
- Database verification:
  ```sql
  SELECT range_id, scenario_id, name, status, created_at
  FROM cms_rangeinstance
  WHERE range_id = '<range-id>';
  -- Should show: scenario_id = 'uat-form-basic'
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-6.6: Verify Range Spec Hydration from Scenario Template

**Objective:** Verify range infrastructure matches scenario definition.

**Prerequisites:**
- Scenario `uat-multi-subnet` exists (from section 3.1)
- Range launched with this scenario

**Steps:**
1. Launch range with `uat-multi-subnet`
2. Wait for range to provision (or check initial spec)
3. Verify range spec matches scenario:
   - 3 instances (Attacker, WebServer, Workstation)
   - 3 subnets (dmz, internal, attacker_net)
   - Correct subnet connectivity

**Database/API Verification:**
```sql
-- Check range spec stored
SELECT range_id, spec FROM cms_rangeinstance WHERE scenario_id = 'uat-multi-subnet' ORDER BY created_at DESC LIMIT 1;
```

**Expected Result:**
- Range spec matches scenario definition
- Instance names, roles, os_types correct
- Subnet configuration matches
- XDR agent flags correctly applied

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

## 5. Test Execution Log

### Execution Summary

| Date | Executed By | Environment | Pass | Fail | Blocked | Total |
|------|-------------|-------------|------|------|---------|-------|
| _[Date]_ | _[Name]_ | Dev | 0 | 0 | 0 | 0 |

### Defects Found

| Defect ID | Test Case | Severity | Description | Status |
|-----------|-----------|----------|-------------|--------|
| - | - | - | - | - |

### Notes and Observations

_[Add any general observations, performance notes, or recommendations here]_

---

## 6. Known Limitations

### Design Limitations

1. **Default YAML Scenarios Read-Only**
   - Default scenarios in `cms/scenarios/templates/` cannot be edited via editor
   - Workaround: Clone the scenario first, then edit the clone

2. **Soft-Delete Pattern**
   - Deleted scenarios remain in database with deleted_at timestamp
   - Scenario IDs of deleted scenarios cannot be immediately reused
   - Workaround: Choose unique IDs or wait for hard delete (manual cleanup)

3. **Scenario ID Format Restrictions**
   - Must be valid slug: lowercase, numbers, hyphens, underscores only
   - Cannot start or end with hyphen or underscore
   - Immutable after creation (cannot be changed via edit)

4. **Metadata Defaults**
   - If no metadata row exists: enabled=true, staff_only=false
   - Metadata must be explicitly created to change these defaults
   - Default YAML scenarios inherit these defaults until metadata created

### Technical Constraints

1. **Pydantic Validation Strictness**
   - All instance names must be unique within a scenario
   - Subnet instance references validated only at save time (not real-time)
   - DC instances must have dc_config when domain_controller=true

2. **Range Launch Dependencies**
   - Scenario must have enabled=true
   - Non-staff users cannot launch staff_only scenarios
   - Agent distribution must be available and valid

### Browser Compatibility

- Tested on: Chrome, Firefox, Edge (latest versions)
- YAML editor may require JavaScript enabled
- Form validation requires JavaScript for client-side checks

---

## Appendix A: Database Schema Reference

### cms_scenario Table

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| scenario_id | SlugField | Unique identifier (e.g., 'my-scenario') |
| name | CharField | Display name |
| description | TextField | User-facing description |
| definition | JSONField | Instances, subnets, ngfw flag |
| created_by | ForeignKey | Staff user who created |
| updated_by | ForeignKey | Staff user who last updated |
| created_at | DateTimeField | Creation timestamp |
| updated_at | DateTimeField | Last modification timestamp |
| deleted_at | DateTimeField | Soft delete timestamp (NULL = active) |

### cms_scenariometadata Table

| Column | Type | Description |
|--------|------|-------------|
| scenario_id | CharField | Matches YAML or DB scenario id (unique) |
| enabled | BooleanField | Whether scenario is available (default true) |
| staff_only | BooleanField | Whether restricted to staff (default false) |
| updated_by | ForeignKey | Staff user who last changed metadata |
| updated_at | DateTimeField | Last modification timestamp |

---

## Appendix B: Quick Command Reference

### Database Queries

```sql
-- List all active scenarios
SELECT scenario_id, name, deleted_at FROM cms_scenario WHERE deleted_at IS NULL;

-- List all scenario metadata
SELECT scenario_id, enabled, staff_only FROM cms_scenariometadata;

-- Find ranges launched with a specific scenario
SELECT range_id, name, status, created_at
FROM cms_rangeinstance
WHERE scenario_id = 'uat-form-basic'
ORDER BY created_at DESC;

-- Check soft-deleted scenarios
SELECT scenario_id, name, deleted_at FROM cms_scenario WHERE deleted_at IS NOT NULL;
```

### API Endpoints

```bash
# List scenarios (staff user)
curl -H "Authorization: Bearer <staff-token>" \
  https://dev.shifter.example.com/api/scenarios/

# List scenarios (non-staff user)
curl -H "Authorization: Bearer <non-staff-token>" \
  https://dev.shifter.example.com/api/scenarios/

# Validate YAML
curl -X POST https://dev.shifter.example.com/scenario_editor/validate-yaml/ \
  -H "Content-Type: application/json" \
  -H "Cookie: sessionid=<session>" \
  -d '{"yaml_content": "..."}'

# Launch range
curl -X POST https://dev.shifter.example.com/api/range/launch/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"scenario_id": "uat-form-basic", "agent_distribution_id": "<id>", "name": "Test Range"}'
```

### Common URLs

- Scenario Editor Home: `https://dev.shifter.example.com/scenario_editor/`
- Create Form: `https://dev.shifter.example.com/scenario_editor/create/form/`
- Create YAML: `https://dev.shifter.example.com/scenario_editor/create/yaml/`
- Detail View: `https://dev.shifter.example.com/scenario_editor/<scenario-id>/`
- Edit Form: `https://dev.shifter.example.com/scenario_editor/<scenario-id>/edit/form/`
- Edit YAML: `https://dev.shifter.example.com/scenario_editor/<scenario-id>/edit/yaml/`

---

**End of UAT Plan**
