# UAT Test Plan - Dev Branch Features

**Test Date**: 2026-02-21
**Environment**: dev.shifter.keplerops.com
**Tester**: Automated UAT via Claude Code
**Test Scope**: Features on dev branch not yet merged to main

---

## Feature 1: NGFW CLI Access via Guacamole

### Acceptance Criteria
- Users can navigate to Mission Control → NGFWs
- Users can see a list of their provisioned NGFWs
- Each NGFW detail page shows management IP and status
- "Open CLI" button generates Guacamole SSH URL
- Clicking button opens web-based SSH terminal to NGFW
- Terminal connects using stored SSH private key
- Users authenticate to PAN-OS CLI successfully

### Test Cases

#### TC1.1: View NGFW List
**Prerequisites**: User owns at least one active NGFW
**Steps**:
1. Log in as bedwards@paloaltonetworks.com
2. Navigate to /mc/ngfw/
**Expected**: Page loads with table showing user's NGFWs (name, status, management IP)
**Data Validation**: Query engine_instance for role='ngfw', user ownership

#### TC1.2: View NGFW Detail Page
**Prerequisites**: NGFW ID from TC1.1
**Steps**:
1. Click NGFW from list
2. Navigate to /mc/ngfw/{id}/
**Expected**:
- Page loads with NGFW details
- Management IP displayed: 10.1.5.116
- Status badge shows "active"
- "Open CLI" button visible and enabled

#### TC1.3: Generate Guacamole SSH URL
**Prerequisites**: Active NGFW with management_ip in state JSON
**Steps**:
1. POST to /mc/api/ngfw/{id}/ssh-url/
2. Verify authenticated session
**Expected**:
- HTTP 200 JSON response
- Response contains: `{"url": "https://guacamole.../#/client/{conn_id}?token={jwt}"}`
- Token is valid JWT signed with GUACAMOLE_SECRET_KEY
- Connection parameters include hostname, username, private key

#### TC1.4: SSH Key Retrieval
**Prerequisites**: NGFW UUID from engine_instance.uuid
**Steps**:
1. Check Secrets Manager for key: `shifter/dev/ngfw/{uuid}/ssh-key`
**Expected**:
- Secret exists
- Contains valid PEM-formatted RSA private key
- Key can decrypt NGFW admin user

#### TC1.5: Guacamole Connection
**Prerequisites**: Valid Guacamole URL from TC1.3
**Steps**:
1. Open URL in browser (or verify via logs)
2. Check guacd logs for connection attempt
**Expected**:
- guacd creates SSH connection to management_ip
- Authentication succeeds using private key
- PAN-OS CLI prompt appears
- No "Permission denied" or "Connection refused" errors

#### TC1.6: End-to-End Smoke Test
**Prerequisites**: Access to running NGFW
**Steps**:
1. Full workflow: List → Detail → Generate URL → Connect
2. Execute `show system info` in terminal
**Expected**:
- Command executes successfully
- Returns NGFW hostname, version, serial number
- Connection remains stable (no disconnects)

---

## Feature 2: Experiment Runner & Scenario Editor

### Acceptance Criteria
- Users can view available scenarios from YAML definitions
- Users can create experiments linked to scenarios
- Users can upload attack/victim scripts (PS1, Python, Bash)
- Users can assign scripts to experiment with target instance roles
- Scripts support template variables: {{InstanceName.property}}
- Template variable validation prevents invalid references
- Experiments can be queued for execution
- Orchestrator provisions ranges, runs scripts in order (victims → attackers)
- Scripts produce artifacts (logs, screenshots, files)
- Experiment runs track status: pending → provisioning → running → completed/failed

### Test Cases

#### TC2.1: View Scenarios List
**Prerequisites**: Scenarios defined in cms/scenarios/definitions/*.yaml
**Steps**:
1. Navigate to /experiments/create/ (GET)
2. Inspect scenarios dropdown
**Expected**:
- Dropdown populated with scenario choices
- Each shows: id, name, description
- At least 1 scenario available (e.g., "xdr_defense")
**Data Validation**:
```python
from cms.scenarios.loader import list_scenario_ids, load_scenario
scenario_ids = list_scenario_ids()
assert len(scenario_ids) > 0
```

#### TC2.2: Load Scenario Structure
**Prerequisites**: Scenario ID from TC2.1
**Steps**:
1. Load scenario via `load_scenario(scenario_id)`
2. Inspect scenario.instances
**Expected**:
- Instances list contains role names: ["DC", "Workstation", "Kali"]
- Each instance has: role, os_family, subnet
- Validation: Instance roles are unique within scenario

#### TC2.3: Upload Attack Script
**Prerequisites**: User account, test script file
**Test Script**: Create `/tmp/test_attack.ps1`:
```powershell
# Test attack script
Write-Host "Attacking target: {{Workstation.ip}}"
Invoke-WebRequest -Uri "http://{{Workstation.ip}}:8080/malicious" -Method POST
Write-Host "Attack complete"
```
**Steps**:
1. Navigate to /experiments/scripts/upload/
2. Fill form:
   - name: "Test Attack Script"
   - filename: "test_attack.ps1"
   - file_size: {actual size}
   - agent_type: "xdr"
3. POST to initiate upload
4. Upload file to presigned S3 URL
5. POST with upload_token to complete
**Expected**:
- Initiate: Returns presigned_url, s3_key, upload_token
- S3 upload: HTTP 200
- Complete: Redirect to /experiments/scripts/, success message
**Data Validation**:
```sql
SELECT id, name, s3_key, original_filename, agent_type
FROM experiments_scriptasset
WHERE name = 'Test Attack Script';
```
- Record exists
- s3_key format: `experiments/scripts/{uuid}/{filename}`
- agent_type = 'xdr'

#### TC2.4: Upload Victim Script
**Test Script**: Create `/tmp/test_victim.ps1`:
```powershell
# Test victim script
Write-Host "Victim preparing on {{DC.ip}}"
Start-Service -Name "VulnerableService"
```
**Steps**: Same as TC2.3 but with victim script
**Expected**: Script uploaded, stored with agent_type='xdr'

#### TC2.5: Template Variable Validation - Valid
**Prerequisites**: Scenario with instances: ["DC", "Workstation"]
**Steps**:
1. Create experiment via POST /experiments/create/
2. Submit form with:
   - scenario_id: {valid scenario}
   - Script 1: attacker script with `{{Workstation.ip}}`
   - Script 2: victim script with `{{DC.ip}}`
**Expected**:
- Form validation passes
- Experiment created successfully
- Scripts linked to experiment with target roles

#### TC2.6: Template Variable Validation - Invalid Instance
**Steps**:
1. Submit experiment with script containing: `{{InvalidInstance.ip}}`
**Expected**:
- Form validation FAILS
- Error message: "InvalidInstance not found in scenario {scenario_name}"
- Experiment NOT created

#### TC2.7: Template Variable Validation - Invalid Property
**Steps**:
1. Submit experiment with script containing: `{{DC.invalid_property}}`
**Expected**:
- Form validation FAILS
- Error message: "Invalid property 'invalid_property'. Allowed: ip, name, instance_id"
- Experiment NOT created

#### TC2.8: Create Experiment - Full Workflow
**Prerequisites**:
- Scenario ID: "xdr_defense"
- 2 uploaded scripts from TC2.3, TC2.4
**Steps**:
1. POST /experiments/create/ with:
   ```json
   {
     "name": "UAT Test Experiment",
     "description": "Testing experiment creation",
     "scenario_id": "xdr_defense",
     "agent_id": {agent_config_id},
     "total_runs": 3,
     "max_parallel_runs": 2,
     "scripts": [
       {
         "script_id": {victim_script_id},
         "target_role": "DC",
         "script_type": "victim",
         "execution_order": 1
       },
       {
         "script_id": {attacker_script_id},
         "target_role": "Kali",
         "script_type": "attacker",
         "execution_order": 2
       }
     ]
   }
   ```
**Expected**:
- HTTP 302 redirect to /experiments/
- Success message: "Experiment created successfully"
**Data Validation**:
```sql
SELECT e.id, e.name, e.scenario_id, e.status, e.total_runs,
       COUNT(es.id) as script_count
FROM experiments_experiment e
LEFT JOIN experiments_experimentscript es ON e.id = es.experiment_id
WHERE e.name = 'UAT Test Experiment'
GROUP BY e.id;
```
- Experiment exists with status='draft'
- script_count = 2

#### TC2.9: Queue Experiment for Execution
**Prerequisites**: Experiment from TC2.8
**Steps**:
1. POST /experiments/{id}/start/
**Expected**:
- Experiment status changes: draft → queued
- SQS message published to experiment queue
- Success message: "Experiment queued for execution"

#### TC2.10: Orchestrator - Schedule Runs
**Prerequisites**: Queued experiment
**Steps**:
1. Trigger orchestrator (via SQS or direct function call)
2. Call `orchestrator.schedule_runs()`
**Expected**:
- Creates ExperimentRun records (count = min(total_runs, max_parallel))
- Run status: pending → provisioning
- Range provisioning requests created
**Data Validation**:
```sql
SELECT id, status, range_request_id
FROM experiments_experimentrun
WHERE experiment_id = {experiment_id}
ORDER BY created_at;
```
- 2 runs created (max_parallel=2, total_runs=3)
- Each has range_request_id

#### TC2.11: Orchestrator - Handle Range Provisioned
**Prerequisites**: Run in 'provisioning' status, range provisioned
**Steps**:
1. Simulate range provisioning complete
2. Call `orchestrator.handle_range_provisioned(run_id, provisioned_instances)`
3. Provide instance data:
   ```python
   {
     "DC": {"ip": "10.1.2.5", "instance_id": "i-abc123"},
     "Workstation": {"ip": "10.1.3.10", "instance_id": "i-def456"}
   }
   ```
**Expected**:
- Run status: provisioning → running
- Scripts resolve template variables:
  - `{{DC.ip}}` → `10.1.2.5`
  - `{{Workstation.ip}}` → `10.1.3.10`
- SSM commands dispatched to victim instances first
- After victims complete, attacker scripts dispatched

#### TC2.12: Script Execution - Victim Scripts
**Prerequisites**: Run in 'running' status, victim scripts queued
**Steps**:
1. Verify SSM commands sent to victim instances
2. Check command format includes:
   - Instance ID from provisioned_instances
   - Script downloaded from S3
   - Resolved template variables in script content
**Expected**:
- Commands visible in CloudWatch Logs (portal publishes to SQS)
- Script executes on target instance
- Output captured

#### TC2.13: Script Execution - Attacker Scripts
**Prerequisites**: All victim scripts completed
**Steps**:
1. Verify orchestrator waits for victim completion
2. Verify attacker scripts dispatched only after victims
**Expected**:
- Execution order enforced: victims complete before attackers start
- Attacker scripts execute successfully

#### TC2.14: Artifact Collection
**Prerequisites**: Script execution completed
**Steps**:
1. Verify artifacts created for each script execution
2. Check experiments_runartifact table
**Expected**:
```sql
SELECT ra.script_name, ra.artifact_type, ra.s3_key, ra.status
FROM experiments_runartifact ra
WHERE ra.run_id = {run_id};
```
- Artifacts for each script (stdout, stderr)
- s3_key populated with artifact location
- status = 'available'

#### TC2.15: Run Completion
**Prerequisites**: All scripts executed, artifacts collected
**Steps**:
1. Verify run status transitions to 'completed' or 'failed'
2. Check run.completed_at timestamp set
**Expected**:
- Run marked complete
- Experiment status updates if all runs complete
- Range teardown triggered

#### TC2.16: Parallel Run Execution
**Prerequisites**: Experiment with total_runs=3, max_parallel=2
**Steps**:
1. Verify only 2 runs execute simultaneously
2. After run 1 completes, verify run 3 starts
**Expected**:
- At no time are >2 runs in 'running' status
- Third run remains 'pending' until slot available
- Orchestrator respects max_parallel limit

---

## Feature 3: CIE & XDR Collector Agent Types

### Acceptance Criteria
- agent_type field exists on cms_agentconfig with values: xdr, xdr_collector, cloud_identity_engine
- Existing agents default to 'xdr'
- Upload API validates agent_type
- UI displays agent type badges/labels
- Scripts can be tagged with agent_type
- Experiments filter agents by type

### Test Cases

#### TC3.1: Database Schema
**Steps**:
```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'cms_agentconfig' AND column_name = 'agent_type';
```
**Expected**:
- Column exists: VARCHAR type
- Default: 'xdr' (or NULL with application-level default)

#### TC3.2: Migration Applied
**Steps**:
```sql
SELECT applied FROM django_migrations
WHERE app = 'cms' AND name = '0023_add_agent_type';
```
**Expected**: Migration exists with recent applied timestamp

#### TC3.3: Existing Agents Migrated
**Steps**:
```sql
SELECT id, name, agent_type FROM cms_agentconfig WHERE deleted_at IS NULL;
```
**Expected**: All existing agents have agent_type = 'xdr'

#### TC3.4: Upload Agent - XDR Collector
**Prerequisites**: Valid user session
**Steps**:
1. POST /mc/api/upload/initiate/ with:
   ```json
   {
     "name": "UAT XDR Collector",
     "filename": "xdr_collector.msi",
     "file_size": 50000000,
     "agent_type": "xdr_collector"
   }
   ```
**Expected**:
- HTTP 200 with presigned_url
- s3_key includes agent type or uuid
- upload_token returned

#### TC3.5: Upload Agent - CIE
**Steps**: Same as TC3.4 with agent_type="cloud_identity_engine"
**Expected**: Upload initiated successfully

#### TC3.6: Upload Agent - Invalid Type
**Steps**:
1. POST with agent_type="invalid_type"
**Expected**:
- HTTP 400 Bad Request
- Error message: "Invalid agent_type. Allowed: xdr, xdr_collector, cloud_identity_engine"

#### TC3.7: Upload Agent - Missing Type
**Steps**:
1. POST without agent_type field
**Expected**:
- Defaults to 'xdr' OR
- Returns error if required

#### TC3.8: View Agents Page
**Prerequisites**: Agents with different types exist
**Steps**:
1. Navigate to /mc/agents/
2. Inspect agent list table
**Expected**:
- Column or badge showing agent type
- Different types visually distinguishable
- Filters available to show only specific type

---

## Feature 4: Miscellaneous Features

### Test Cases

#### TC4.1: Logout Button
**Prerequisites**: Authenticated user session
**Steps**:
1. Navigate to Mission Control dashboard
2. Locate user profile menu (sidebar or header)
3. Click profile icon/tile
**Expected**:
- Dropdown menu appears
- "Logout" option visible
- Clicking logout redirects to login page
- Session cleared (cannot access protected pages)

#### TC4.2: Risk Register MCP Tools
**Steps**:
1. Verify MCP tools available:
   - list_risks
   - get_risk
   - create_risk
   - update_risk
   - delete_risk
   - risk_dashboard
   - risk_matrix
   - risk_audit_log
**Expected**: All tools callable and return valid responses

#### TC4.3: Risk Register - Create Risk
**Steps**:
1. Call mcp__shifter-ops__create_risk with test data
**Expected**:
- Risk created in risks_risk table
- Returns risk ID
- Audit log entry created

#### TC4.4: Packer BrokenBank AMI
**Steps**:
1. Verify file exists: shifter/packer/brokenbk.pkr.hcl
2. Validate HCL syntax
**Expected**:
- File exists
- Valid Packer template
- Builds Windows AMI with BrokenBank app

---

## Test Execution Environment

### Constraints
- **ALLOWED_HOSTS Issue**: DJANGO_ALLOWED_HOSTS=dev.shifter.keplerops.com (excludes localhost)
- **Impact**: Cannot access UI via browser through SSM tunnel
- **Workarounds**:
  1. Use Django shell via SSM to call service functions directly
  2. Query database to validate state changes
  3. Check CloudWatch logs for request/response patterns
  4. Test API endpoints via curl from portal EC2 instance

### Test Data Setup
- User: bedwards@paloaltonetworks.com (ID=1)
- NGFW: ID=597, IP=10.1.5.116, instance=i-0d6483ffe59263ec2
- Scenarios: Load from cms/scenarios/definitions/
- Agent: Select existing xdr agent or create test agent

### Pass/Fail Criteria
- **PASS**: Feature works end-to-end as designed, data persists correctly, no errors
- **FAIL**: Validation errors, database inconsistencies, exceptions, incorrect behavior
- **BLOCKED**: Cannot test due to environment limitations (document reason)

---

## Appendix: How to Execute Tests

### Database Queries
```python
from mcp__shifter-ops import query
result = query(sql="SELECT...", env="dev")
```

### Django Shell via SSM
```bash
aws ssm send-command \
  --instance-ids i-07b3e3fa9bc074e53 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker exec $(docker ps --format {{.Names}} | grep portal) python manage.py shell"]' \
  --region us-east-2
```

### Check Logs
```python
from mcp__shifter-ops import tail_logs, filter_log_events
tail_logs(component="portal", env="dev", limit=100)
filter_log_events(component="portal", filter_pattern="experiment error", env="dev")
```

### S3 Validation
```bash
aws s3 ls s3://shifter-dev-assets/experiments/scripts/ --recursive
```
