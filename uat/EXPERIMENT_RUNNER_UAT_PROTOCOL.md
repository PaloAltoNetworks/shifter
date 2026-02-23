# UAT Protocol: Experiment Runner

**Version:** 1.0
**Target Environment:** Dev
**Created:** 2026-02-22
**Owner:** SecOps Team

## Table of Contents

- [1. Prerequisites & Environment Setup](#1-prerequisites--environment-setup)
- [2. Test Scope Overview](#2-test-scope-overview)
- [3. Test Data Preparation](#3-test-data-preparation)
- [4. Test Cases](#4-test-cases)
  - [TC-1: Script Upload Flow](#tc-1-script-upload-flow)
  - [TC-2: Script Management](#tc-2-script-management)
  - [TC-3: Experiment Creation](#tc-3-experiment-creation)
  - [TC-4: Experiment Lifecycle (Start / Monitor / Complete)](#tc-4-experiment-lifecycle-start--monitor--complete)
  - [TC-5: Parallel Run Scheduling](#tc-5-parallel-run-scheduling)
  - [TC-6: Failure Recovery](#tc-6-failure-recovery)
  - [TC-7: Cancel Running Experiment](#tc-7-cancel-running-experiment)
  - [TC-8: Artifact Collection & Download](#tc-8-artifact-collection--download)
  - [TC-9: Template Variables in Prompts](#tc-9-template-variables-in-prompts)
  - [TC-10: Permission Boundaries](#tc-10-permission-boundaries)
  - [TC-11: Validation & Edge Cases](#tc-11-validation--edge-cases)
  - [TC-12: Multi-Instance Execution Order](#tc-12-multi-instance-execution-order)
  - [TC-13: Infrastructure Failure Injection](#tc-13-infrastructure-failure-injection)
- [5. Test Execution Log](#5-test-execution-log)
- [6. Known Limitations](#6-known-limitations)
- [7. Troubleshooting Guide](#7-troubleshooting-guide)

---

## 1. Prerequisites & Environment Setup

### 1.1 Environment Details

- **Dev Portal URL:** `http://localhost:8000` (via SSM tunnel)
- **Experiment Runner URL:** `http://localhost:8000/mission-control/experiments/`
- **Script Manager URL:** `http://localhost:8000/mission-control/experiments/scripts/`
- **WebSocket URL:** `ws://localhost:8000/ws/experiment-status/<experiment_id>/`

### 1.2 Tunnel Setup

```bash
# Start SSM tunnel to dev portal (via shifter-ops MCP)
start_portal_test_tunnel(env="dev", local_port=8000)
```

### 1.3 Required User Accounts

| User Type | Username | Purpose |
|-----------|----------|---------|
| Staff User A | dev_login staff account | Create/manage experiments |
| Staff User B | second staff account | Test permission isolation |

### 1.4 Required Infrastructure

- Scenario `basic` must exist in scenario registry
- At least one active agent uploaded (Windows or Linux)
- SQS experiments queue configured (`SQS_EXPERIMENTS_URL`)
- ECS cluster running (`PULUMI_ECS_CLUSTER_ARN`)

### 1.5 Pre-Test Checklist

- [ ] Verify dev portal tunnel is open
- [ ] Confirm dev_login authentication works
- [ ] Verify database access via shifter-ops MCP
- [ ] Confirm `basic` scenario loads (query DB or check scenario list)
- [ ] Verify no stale UAT experiments exist
- [ ] Check CloudWatch logs accessible

### 1.6 Database Access

Use the shifter-ops MCP for database queries:

```sql
-- Verify experiments table exists and is accessible
SELECT COUNT(*) FROM cms_experiment;

-- Verify scripts table exists
SELECT COUNT(*) FROM cms_scriptasset;

-- Check available scenarios
SELECT scenario_id, name FROM cms_scenario WHERE deleted_at IS NULL;
```

---

## 2. Test Scope Overview

### 2.1 Features Covered

**Script Management:**
- Upload Python scripts (presigned S3 URL flow)
- List user's scripts
- Soft-delete scripts

**Experiment CRUD:**
- Create experiment with script assignments (Claude Code or Python)
- View experiment list with run counts
- View experiment detail with runs and artifacts

**Experiment Lifecycle:**
- Start experiment (DRAFT -> QUEUED -> RUNNING)
- Monitor run progress via WebSocket
- Cancel running experiment
- Experiment completion (COMPLETED / FAILED)

**Orchestration:**
- Run scheduling with max_parallel_runs enforcement
- Range provisioning per run
- Victim-then-attacker execution order
- Artifact collection

**Error Handling:**
- Run failure recovery (next run starts)
- Validation errors surfaced in UI
- State transition enforcement

**Permission Boundaries:**
- Staff-only access to all experiment endpoints
- User isolation (can only see own experiments)

### 2.2 Out of Scope

- ECS task internal execution (container-level testing)
- SSM command execution on range instances
- S3 artifact content verification (binary-level)
- XDR agent interaction within ranges
- Performance / load testing

### 2.3 Test Environment Specifications

- **Platform:** Django 5.x on AWS us-east-2
- **Database:** PostgreSQL (via RDS)
- **Queue:** SQS (experiments queue)
- **Compute:** ECS Fargate (experiment-executor tasks)
- **Storage:** S3 (scripts and artifacts)
- **Real-time:** Django Channels via WebSocket

---

## 3. Test Data Preparation

### 3.1 Python Test Script

File: `uat_test_script.py`
```python
#!/usr/bin/env python3
"""UAT test script - writes a marker file and prints output."""
import datetime
import os

output_dir = "/tmp"
marker = os.path.join(output_dir, "uat_marker.txt")

with open(marker, "w") as f:
    f.write(f"UAT test executed at {datetime.datetime.now().isoformat()}\n")

print("UAT test script executed successfully")
print(f"Marker file written to {marker}")
```

### 3.2 Claude Code Test Prompt

```
Create a file called /tmp/uat_test.txt with the content "Experiment runner UAT successful" and then print the contents of the file.
```

### 3.3 Template Variable Test Prompt

```
Connect to the victim at {Workstation.private_ip} and verify the hostname matches {Workstation.hostname}. Report findings.
```

### 3.4 Invalid Test Data

| Test Data | Purpose |
|-----------|---------|
| File `test.txt` (not .py) | Rejected by upload validation |
| File > 1MB | Rejected by size validation |
| Empty experiment name | Rejected by form validation |
| `max_parallel_runs` > `total_runs` | Rejected by schema validation |
| Script referencing non-existent instance | Rejected by create validation |

---

## 4. Test Cases

### TC-1: Script Upload Flow

#### TC-1.1: Upload Valid Python Script

**Objective:** Verify users can upload a Python script via the presigned URL flow.

**Prerequisites:**
- Logged in as staff user
- At `/mission-control/experiments/scripts/`

**Steps:**
1. Navigate to `/mission-control/experiments/scripts/`
2. Click "Upload Script" button
3. Fill form:
   - Name: `uat_test_script`
   - Select file: `uat_test_script.py` (< 1MB, .py extension)
4. Click "Upload"
5. Wait for upload progress/completion
6. Verify script appears in scripts list

**Expected Result:**
- Presigned URL generated for S3 upload
- Upload completes successfully
- Script appears in scripts list with name, filename, size
- Database verification:
  ```sql
  SELECT id, name, original_filename, file_size_bytes, deleted_at
  FROM cms_scriptasset WHERE name = 'uat_test_script';
  -- Should return: row with deleted_at = NULL
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

**Notes:**
_[Any deviations, defects, or observations]_

---

#### TC-1.2: Reject Non-Python File Upload

**Objective:** Verify .py extension enforcement.

**Prerequisites:**
- Logged in as staff user
- At scripts upload page

**Steps:**
1. Navigate to `/mission-control/experiments/scripts/upload/`
2. Attempt to upload a `.txt` file
3. Verify rejection

**Expected Result:**
- Error message: "Only .py files are allowed"
- No script created in database

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-1.3: Reject Oversized File Upload

**Objective:** Verify 1MB size limit enforcement.

**Prerequisites:**
- Logged in as staff user
- File > 1MB available

**Steps:**
1. Attempt to upload a Python file larger than 1MB
2. Verify rejection

**Expected Result:**
- Error message: "File size exceeds maximum"
- No script created in database

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-2: Script Management

#### TC-2.1: List Scripts

**Objective:** Verify script list shows only user's active scripts.

**Prerequisites:**
- At least one script uploaded (from TC-1.1)
- Logged in as staff user

**Steps:**
1. Navigate to `/mission-control/experiments/scripts/`
2. Verify uploaded script appears
3. Verify list shows name, filename, size, upload date

**Expected Result:**
- Script list displays correctly
- Only current user's non-deleted scripts shown

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-2.2: Delete Script (Soft Delete)

**Objective:** Verify scripts are soft-deleted.

**Prerequisites:**
- Script `uat_test_script` exists
- Logged in as staff user

**Steps:**
1. Navigate to `/mission-control/experiments/scripts/`
2. Click delete on `uat_test_script`
3. Confirm deletion
4. Verify script removed from list

**Expected Result:**
- Script no longer visible in list
- Database verification (soft-delete):
  ```sql
  SELECT id, name, deleted_at FROM cms_scriptasset WHERE name = 'uat_test_script';
  -- Should return: row with deleted_at NOT NULL
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-3: Experiment Creation

#### TC-3.1: Create Minimal Experiment (Claude Code)

**Objective:** Verify experiment creation with a Claude Code prompt.

**Prerequisites:**
- Logged in as staff user
- Scenario `basic` exists

**Steps:**
1. Navigate to `/mission-control/experiments/create/`
2. Fill form:
   - Name: `UAT Minimal Claude`
   - Description: `Minimal experiment with Claude Code prompt`
   - Scenario: Select `basic`
   - Total runs: `1`
   - Max parallel runs: `1`
3. Add script assignment:
   - Instance: `Workstation` (or first available instance)
   - Type: `Claude Code`
   - Prompt: `Create a file called /tmp/uat_test.txt with content "UAT successful"`
   - Execution order: `10`
4. Click "Create Experiment"

**Expected Result:**
- Redirect to experiment detail page
- Experiment in DRAFT status
- Shows 0/1 runs (not started)
- Script assignment visible
- "Start Experiment" button enabled
- Database verification:
  ```sql
  SELECT id, name, status, total_runs, max_parallel_runs
  FROM cms_experiment WHERE name = 'UAT Minimal Claude';
  -- Should return: status=draft, total_runs=1, max_parallel_runs=1

  SELECT es.instance_name, es.script_type, es.execution_order
  FROM cms_experimentscript es
  JOIN cms_experiment e ON es.experiment_id = e.id
  WHERE e.name = 'UAT Minimal Claude';
  -- Should return: 1 row with script_type=claude_code
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-3.2: Create Experiment with Python Script

**Objective:** Verify experiment creation with an uploaded Python script.

**Prerequisites:**
- Logged in as staff user
- Python script uploaded (re-upload if TC-2.2 deleted it)

**Steps:**
1. Navigate to `/mission-control/experiments/create/`
2. Fill form:
   - Name: `UAT Python Script`
   - Scenario: `basic`
   - Total runs: `1`
   - Max parallel runs: `1`
3. Add script assignment:
   - Instance: `Workstation`
   - Type: `Python`
   - Script: Select uploaded script
   - Execution order: `10`
4. Click "Create Experiment"

**Expected Result:**
- Experiment created in DRAFT status
- Script assignment shows Python type with linked script
- Database verification:
  ```sql
  SELECT es.instance_name, es.script_type, es.script_id, s.name as script_name
  FROM cms_experimentscript es
  JOIN cms_experiment e ON es.experiment_id = e.id
  LEFT JOIN cms_scriptasset s ON es.script_id = s.id
  WHERE e.name = 'UAT Python Script';
  -- Should return: script_type=python, script_id NOT NULL
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-3.3: Create Multi-Run Experiment

**Objective:** Verify experiment creation with multiple runs and parallel config.

**Prerequisites:**
- Logged in as staff user

**Steps:**
1. Navigate to `/mission-control/experiments/create/`
2. Fill form:
   - Name: `UAT Multi-Run`
   - Scenario: `basic`
   - Total runs: `3`
   - Max parallel runs: `2`
3. Add script assignment (Claude Code prompt)
4. Click "Create Experiment"

**Expected Result:**
- Experiment created with total_runs=3, max_parallel_runs=2
- Database verification:
  ```sql
  SELECT total_runs, max_parallel_runs FROM cms_experiment WHERE name = 'UAT Multi-Run';
  -- Should return: 3, 2
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-3.4: Validate Form Input Errors

**Objective:** Verify form validation catches invalid inputs.

**Prerequisites:**
- Logged in as staff user
- At `/mission-control/experiments/create/`

**Test Cases:**

| Sub-Test | Invalid Input | Expected Error |
|----------|---------------|----------------|
| TC-3.4.1 | Empty name | Validation error |
| TC-3.4.2 | Invalid scenario_id | "Invalid scenario" |
| TC-3.4.3 | max_parallel_runs (3) > total_runs (1) | "max_parallel_runs cannot exceed total_runs" |
| TC-3.4.4 | total_runs > 10 | Rejected by field constraint |
| TC-3.4.5 | max_parallel_runs > 5 | Rejected by field constraint |
| TC-3.4.6 | Script referencing non-existent instance | "Instance not found in scenario" |

**Steps:**
For each sub-test:
1. Fill form with invalid input
2. Submit form
3. Verify error message appears
4. Verify experiment is NOT created

**Expected Result:**
- All validation errors displayed with clear messages
- No experiments created in database for invalid inputs

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-4: Experiment Lifecycle (Start / Monitor / Complete)

#### TC-4.1: Start Experiment

**Objective:** Verify experiment transitions from DRAFT to QUEUED and runs are created.

**Prerequisites:**
- Experiment `UAT Minimal Claude` created in DRAFT status (from TC-3.1)
- Logged in as staff user

**Steps:**
1. Navigate to experiment detail page
2. Click "Start Experiment"
3. Confirm dialog (if any)
4. Observe status change in UI

**Expected Result:**
- Experiment status changes: DRAFT -> QUEUED
- Run records created in database
- SQS event `experiment.start` published
- Database verification:
  ```sql
  SELECT status FROM cms_experiment WHERE name = 'UAT Minimal Claude';
  -- Should return: queued (or running if orchestrator processes quickly)

  SELECT run_number, status FROM cms_experimentrun
  WHERE experiment_id = (SELECT id FROM cms_experiment WHERE name = 'UAT Minimal Claude')
  ORDER BY run_number;
  -- Should return: 1 row, status=pending (or provisioning)
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-4.2: Monitor Experiment Progress

**Objective:** Verify real-time status updates via WebSocket.

**Prerequisites:**
- Experiment started (from TC-4.1)
- On experiment detail page

**Steps:**
1. Stay on experiment detail page after starting
2. Observe WebSocket status updates:
   - Experiment: QUEUED -> RUNNING
   - Run 1: PENDING -> PROVISIONING -> EXECUTING_VICTIMS -> (EXECUTING_ATTACKER ->) COLLECTING -> COMPLETED
3. Wait for completion (~10-15 minutes)

**Expected Result:**
- UI updates in real-time without page refresh
- Run status progresses through expected states
- Experiment status reaches COMPLETED when all runs finish

**Monitor via CloudWatch:**
```
fields @timestamp, @message
| filter @message like /experiment|orchestrat|schedule_runs|handle_range/
| sort @timestamp desc
| limit 50
```

Look for:
- `schedule_runs: scheduled 1 runs`
- `handle_range_provisioned called for run X`
- `_dispatch_commands: started ECS task`
- `handle_artifacts_collected: run X completed`

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-4.3: Verify Experiment Completion

**Objective:** Verify experiment reaches terminal state correctly.

**Prerequisites:**
- Experiment has finished running

**Steps:**
1. Verify experiment detail page shows COMPLETED status
2. Verify all runs show COMPLETED
3. Check timestamps

**Expected Result:**
- Experiment status = COMPLETED
- All runs status = COMPLETED
- started_at and completed_at timestamps set
- Database verification:
  ```sql
  SELECT status, started_at, completed_at FROM cms_experiment WHERE name = 'UAT Minimal Claude';
  -- Should return: completed, both timestamps NOT NULL

  SELECT run_number, status, started_at, completed_at FROM cms_experimentrun
  WHERE experiment_id = (SELECT id FROM cms_experiment WHERE name = 'UAT Minimal Claude');
  -- All runs should be completed with timestamps
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-5: Parallel Run Scheduling

#### TC-5.1: Verify Max Parallel Enforcement

**Objective:** Verify max_parallel_runs limits concurrent runs.

**Prerequisites:**
- Experiment `UAT Multi-Run` created (total_runs=3, max_parallel_runs=2)
- Logged in as staff user

**Steps:**
1. Start experiment `UAT Multi-Run`
2. Immediately check run statuses in database
3. Verify only 2 runs are in non-PENDING state
4. Wait for first run to complete
5. Verify 3rd run starts

**Expected Result:**
- Initially: 2 runs in PROVISIONING, 1 run in PENDING
- After first completion: 3rd run transitions to PROVISIONING
- Never more than 2 active runs simultaneously
- Database verification (during execution):
  ```sql
  SELECT run_number, status FROM cms_experimentrun
  WHERE experiment_id = (SELECT id FROM cms_experiment WHERE name = 'UAT Multi-Run')
  AND status NOT IN ('completed', 'failed', 'pending')
  ORDER BY run_number;
  -- Should never return more than 2 rows
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-6: Failure Recovery

#### TC-6.1: Failed Run Does Not Block Others

**Objective:** Verify failed runs don't prevent subsequent runs from executing.

**Prerequisites:**
- Create experiment with total_runs=3, max_parallel_runs=1
- Logged in as staff user

**Steps:**
1. Create experiment `UAT Failure Test` (3 runs, 1 parallel)
2. Start experiment
3. Wait for Run 1 to reach an active state
4. Manually fail Run 1 via Django admin or DB:
   ```sql
   UPDATE cms_experimentrun SET status = 'failed', error_message = 'Simulated failure for UAT'
   WHERE experiment_id = (SELECT id FROM cms_experiment WHERE name = 'UAT Failure Test')
   AND run_number = 1;
   ```
5. Observe Run 2 starts

**Expected Result:**
- Run 1 marked FAILED with error message
- Run 2 starts automatically
- Run 3 starts after Run 2
- Experiment completes with mixed results
- Database verification:
  ```sql
  SELECT run_number, status, error_message FROM cms_experimentrun
  WHERE experiment_id = (SELECT id FROM cms_experiment WHERE name = 'UAT Failure Test')
  ORDER BY run_number;
  -- Run 1: failed, Run 2+3: completed or running
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

**Notes:**
Design note: If all runs fail, experiment status = FAILED. If mixed (some fail, some complete), experiment status = COMPLETED. This differs from the original UAT plan which stated mixed = FAILED.

---

### TC-7: Cancel Running Experiment

#### TC-7.1: Cancel Experiment Mid-Execution

**Objective:** Verify experiments can be cancelled gracefully.

**Prerequisites:**
- Create and start a multi-run experiment
- Logged in as staff user

**Steps:**
1. Create experiment `UAT Cancel Test` (3 runs, 1 parallel)
2. Start experiment
3. Wait for first run to reach EXECUTING_VICTIMS or later
4. Click "Cancel Experiment"
5. Confirm cancellation

**Expected Result:**
- Experiment status changes to CANCELLED
- No new runs start after cancellation
- In-progress runs may continue to completion (graceful)
- Pending runs remain PENDING
- Database verification:
  ```sql
  SELECT status FROM cms_experiment WHERE name = 'UAT Cancel Test';
  -- Should return: cancelled

  SELECT run_number, status FROM cms_experimentrun
  WHERE experiment_id = (SELECT id FROM cms_experiment WHERE name = 'UAT Cancel Test')
  ORDER BY run_number;
  -- No pending runs should have started after cancellation
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-7.2: Cannot Cancel DRAFT Experiment

**Objective:** Verify DRAFT experiments cannot be cancelled.

**Prerequisites:**
- Experiment in DRAFT status
- Logged in as staff user

**Steps:**
1. Navigate to a DRAFT experiment's detail page
2. Verify "Cancel" button is disabled or hidden
3. If visible, attempt to cancel and verify error

**Expected Result:**
- Cancel not available for DRAFT experiments
- Error: "Cannot cancel experiment in draft state"

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-8: Artifact Collection & Download

#### TC-8.1: View Run Artifacts

**Objective:** Verify artifacts appear after run completion.

**Prerequisites:**
- A completed experiment with at least 1 completed run

**Steps:**
1. Navigate to completed experiment detail page
2. Expand run details
3. Verify artifacts listed

**Expected Result:**
- Artifacts visible per run
- Shows instance name, artifact type, file size
- Download links available

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-8.2: Download Individual Artifact

**Objective:** Verify individual artifact download via presigned URL.

**Prerequisites:**
- Completed experiment with artifacts

**Steps:**
1. Navigate to experiment detail page
2. Click download link on an individual artifact
3. Verify file downloads

**Expected Result:**
- Presigned S3 URL generated
- File downloads successfully
- Content is readable (Python output or Claude transcript)

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-8.3: Download All Artifacts (ZIP Bundle)

**Objective:** Verify ZIP bundle download of all artifacts.

**Prerequisites:**
- Completed experiment with artifacts

**Steps:**
1. Navigate to experiment detail page
2. Click "Download All Artifacts" button
3. Verify ZIP file downloads

**Expected Result:**
- ZIP file downloads with organized structure:
  ```
  experiment_<id>_artifacts.zip
  ├── run_1/
  │   └── <instance_name>/
  │       └── output.log
  └── experiment_metadata.json
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-9: Template Variables in Prompts

#### TC-9.1: Create Experiment with Template Variables

**Objective:** Verify template variable substitution in Claude prompts.

**Prerequisites:**
- Scenario with named instances (e.g., `basic` with `Workstation`)
- Logged in as staff user

**Steps:**
1. Create experiment with Claude prompt containing template variables:
   ```
   Verify the system at {Workstation.private_ip} is responding. Report the hostname.
   ```
2. Verify experiment creation succeeds (template validated)

**Expected Result:**
- Template variables accepted during creation
- Variables reference valid instance names and properties

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-9.2: Reject Invalid Template Variables

**Objective:** Verify invalid template variables are rejected at creation.

**Test Cases:**

| Sub-Test | Template | Expected Error |
|----------|----------|----------------|
| TC-9.2.1 | `{NonExistentInstance.private_ip}` | Unknown instance error |
| TC-9.2.2 | `{Workstation.invalid_property}` | Unknown property error |

**Steps:**
For each sub-test:
1. Attempt to create experiment with invalid template
2. Verify error message

**Expected Result:**
- Invalid templates rejected with clear error messages

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-10: Permission Boundaries

#### TC-10.1: Staff-Only Access

**Objective:** Verify all experiment endpoints require staff status.

**Prerequisites:**
- Non-staff user account available

**Steps:**
1. Log in as non-staff user (or log out entirely)
2. Attempt to access:
   - `/mission-control/experiments/` (experiment list)
   - `/mission-control/experiments/scripts/` (script list)
   - `/mission-control/experiments/create/` (create form)
3. Verify redirect to login or 403 Forbidden

**Expected Result:**
- All endpoints redirect non-staff users to login
- No experiment data exposed

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-10.2: User Isolation

**Objective:** Verify users cannot see or manage other users' experiments.

**Prerequisites:**
- Experiment created by Staff User A
- Logged in as Staff User B

**Steps:**
1. Create experiment as Staff User A
2. Log in as Staff User B
3. Navigate to experiment list
4. Verify User A's experiment is NOT visible
5. Attempt direct URL access to User A's experiment
6. Verify 404 or permission denied

**Expected Result:**
- User B cannot see User A's experiments in list
- Direct URL access returns redirect or 404
- Cannot start/cancel other user's experiments

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-11: Validation & Edge Cases

#### TC-11.1: Start Non-DRAFT Experiment

**Objective:** Verify cannot start an already-started experiment.

**Steps:**
1. Start a DRAFT experiment (transitions to QUEUED)
2. Attempt to start the same experiment again

**Expected Result:**
- Error: "Experiment must be in draft state to start"

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-11.2: Deleted Script Not Assignable

**Objective:** Verify soft-deleted scripts cannot be assigned to new experiments.

**Steps:**
1. Upload a Python script
2. Soft-delete the script
3. Attempt to create experiment referencing the deleted script

**Expected Result:**
- Script not available in script selector dropdown
- If referenced directly, error: "Script not found"

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-11.3: Experiment List Shows Run Counts

**Objective:** Verify experiment list annotations are correct.

**Steps:**
1. Navigate to experiment list
2. Verify each experiment shows completed/total run counts

**Expected Result:**
- List shows "X/Y runs completed" for each experiment
- Counts match database
- Database verification:
  ```sql
  SELECT e.id, e.name, e.total_runs,
    COUNT(r.id) FILTER (WHERE r.status = 'completed') as completed_runs,
    COUNT(r.id) as total_run_records
  FROM cms_experiment e
  LEFT JOIN cms_experimentrun r ON e.id = r.experiment_id
  GROUP BY e.id, e.name, e.total_runs
  ORDER BY e.created_at DESC;
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

### TC-12: Multi-Instance Execution Order

#### TC-12.1: Victim Scripts Execute Before Attacker Scripts

**Objective:** Verify execution_order < 100 (victim) runs before execution_order >= 100 (attacker) across multiple instances.

**Prerequisites:**
- Scenario with multiple instances (e.g., `ad_attack_lab` with Workstation, Server, Attacker)
- Logged in as staff user

**Steps:**
1. Create experiment with scenario that has 3+ instances
2. Add script assignments:
   - `Workstation` (victim, execution_order=10): Claude prompt
   - `Server` (victim, execution_order=20): Python script
   - `Attacker` (attacker, execution_order=100): Claude prompt
3. Start experiment
4. Observe run status transitions in UI and CloudWatch logs

**Expected Result:**
- Run transitions: PROVISIONING -> EXECUTING_VICTIMS -> EXECUTING_ATTACKER -> COLLECTING
- During EXECUTING_VICTIMS: Workstation and Server execute in parallel
- EXECUTING_ATTACKER only begins after ALL victim scripts complete
- All artifacts collected from all 3 instances
- Database verification:
  ```sql
  SELECT es.instance_name, es.script_type, es.execution_order,
    CASE WHEN es.execution_order < 100 THEN 'victim' ELSE 'attacker' END as role
  FROM cms_experimentscript es
  JOIN cms_experiment e ON es.experiment_id = e.id
  WHERE e.name = 'UAT Multi-Instance'
  ORDER BY es.execution_order;
  -- Should return: 3 rows with 2 victims (order < 100) and 1 attacker (order >= 100)
  ```

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

**Notes:**
Execution order is determined by the `_build_execution_plan()` method in the orchestrator. Scripts with `execution_order < 100` are classified as victim scripts; `>= 100` are attacker scripts. If no attacker scripts exist, the run skips the EXECUTING_ATTACKER phase.

---

### TC-13: Infrastructure Failure Injection

#### TC-13.1: Range Provisioning Failure

**Objective:** Verify run handles range provisioning failure gracefully.

**Prerequisites:**
- Running experiment with multiple runs
- Database access to simulate failure

**Steps:**
1. Create experiment `UAT Infra Failure` (3 runs, 1 parallel)
2. Start experiment
3. Wait for Run 1 to reach PROVISIONING
4. Simulate range failure by updating the run's range instance status to FAILED in DB, or by triggering `handle_run_failed` event via SQS
5. Observe next run starts

**Expected Result:**
- Run 1 transitions to FAILED with error message
- Error message explains provisioning failure
- Run 2 starts automatically (respecting max_parallel_runs)
- Experiment continues processing remaining runs
- CloudWatch logs show failure and scheduling of next run

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

---

#### TC-13.2: ECS Task Dispatch Failure

**Objective:** Verify graceful handling when ECS task cannot be dispatched.

**Prerequisites:**
- Running experiment

**Steps:**
1. Start experiment
2. Wait for run to reach PROVISIONING -> EXECUTING_VICTIMS transition
3. If possible, temporarily misconfigure ECS task definition ARN or kill ECS task after dispatch
4. Observe error handling

**Expected Result:**
- Run marks FAILED with descriptive error
- Error logged to CloudWatch with task details
- Remaining runs continue as normal

**Actual Result:**
_[To be filled during execution]_

**Status:** ☐ Pass ☐ Fail ☐ Blocked

**Notes:**
This test requires infrastructure access. If not feasible in dev, verify behavior through code review of `_dispatch_commands()` idempotency check and error handling. The orchestrator checks `dispatch_task_arn` in run metadata to prevent duplicate dispatches.

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

### Severity Classification

| Severity | Description | Example |
|----------|-------------|---------|
| Critical | Feature non-functional, no workaround | Experiment start fails, runs never execute |
| Major | Feature partially broken, workaround exists | Artifacts don't download but exist in S3 |
| Minor | Cosmetic or non-blocking issue | Run count display off by one, UI alignment |

### Sign-Off

| Role | Name | Date | Decision |
|------|------|------|----------|
| QA | _[Name]_ | _[Date]_ | ☐ Pass ☐ Conditional Pass ☐ Fail |
| Dev | _[Name]_ | _[Date]_ | ☐ Acknowledged |
| PM | _[Name]_ | _[Date]_ | ☐ Ready for Production ☐ Not Ready |

---

## 6. Known Limitations

### Design Limitations

1. **Mixed Results = COMPLETED**
   - If some runs complete and some fail, experiment status is COMPLETED (not FAILED)
   - Only when ALL runs fail does experiment status = FAILED
   - This is intentional: partial results still have value for experimenters

2. **Graceful Cancellation**
   - Cancelling an experiment does NOT abort in-progress runs
   - Active runs complete their current phase, but no new runs start
   - This prevents data loss from abrupt termination

3. **No Experiment Editing After Creation**
   - Experiments cannot be modified after creation (immutable config)
   - To change settings, create a new experiment
   - Scripts, runs, and assignments are fixed at creation time

4. **Script Upload Two-Phase Flow**
   - Upload uses presigned URL (client -> S3 directly)
   - Requires token verification step after upload completes
   - Token expires after 10 minutes

### Technical Constraints

1. **SQS Event Ordering**
   - SQS is best-effort ordered; events may arrive out of order
   - Orchestrator handles this via state checks and idempotency guards

2. **ECS Task Dispatch**
   - Requires configured `PULUMI_ECS_CLUSTER_ARN` and task definition
   - If ECS is not configured, runs fail with "ECS not configured" error

3. **Range Provisioning Dependency**
   - Experiment runs require actual range infrastructure
   - Provisioning time is ~5-10 minutes per range
   - Network or AWS capacity issues will fail runs

4. **WebSocket InMemoryChannelLayer (Dev)**
   - Dev environment may use InMemoryChannelLayer (no Redis)
   - WebSocket updates may not work across processes in this mode
   - Production uses Redis-backed channel layer

### Browser Compatibility

- Tested on: Chrome, Firefox, Edge (latest versions)
- WebSocket support required for real-time updates
- JavaScript required for dynamic form behavior

---

## 7. Troubleshooting Guide

### Experiment Stuck in QUEUED

**Symptoms:** Experiment status = QUEUED but no runs start.

**Check:**
1. SQS queue receiving events? Check via AWS Console -> SQS
2. Experiments worker running? Check ECS tasks for SQS consumer
3. CloudWatch logs show `experiment.start` event processed?

**Resolution:**
- Verify `SQS_QUEUE_CONFIG.experiments.url` is configured in settings
- Check for errors in SQS worker logs
- Republish start event via Django shell if needed
- Restart experiments worker ECS task

---

### Run Stuck in PROVISIONING

**Symptoms:** Run status = PROVISIONING for > 15 minutes.

**Check:**
1. RangeInstance actually provisioning? Check `cms_rangeinstance` status
2. Bridge published `range_provisioned` event? Check CloudWatch for `notify_experiment_on_range_ready`
3. SQS experiments queue received event? Check AWS SQS console

**Resolution:**
- Verify `notify_experiment_on_range_ready` logs in CloudWatch
- Check SQS_EXPERIMENTS_URL is configured
- Manually publish `experiment.run.range_provisioned` event if bridge failed
- Check AWS capacity for range provisioning (EC2 limits, VPC limits)

---

### Scripts Not Executing

**Symptoms:** Run reaches EXECUTING_VICTIMS but no ECS task appears.

**Check:**
1. ECS task started? Check AWS ECS console -> Tasks tab
2. Task logs show SSM commands? Check CloudWatch -> ECS task logs
3. SSM permissions correct? Check IAM role for ECS task

**Resolution:**
- Verify `EXPERIMENT_TASK_DEFINITION_ARN` is configured
- Check ECS task execution role has SSM permissions
- Verify target instances have SSM agent running and are reachable
- Check `_dispatch_commands` logs for errors

---

### Artifacts Not Collected

**Symptoms:** Run completes execution phases but no artifacts appear.

**Check:**
1. Collection ECS task started?
2. S3 permissions correct? Check ECS task role
3. Output files exist on instances? (`/tmp/output_*.log`)

**Resolution:**
- Verify ECS task role has `s3:PutObject` permission on artifacts bucket
- Check S3 bucket policy allows uploads from ECS tasks
- SSH to instance, verify output files exist at expected paths
- Check `_collect_artifacts` logs for S3 upload errors

---

### WebSocket Updates Not Appearing

**Symptoms:** UI does not show real-time status changes.

**Check:**
1. WebSocket connection open? Check browser dev tools -> Network -> WS tab
2. Channel layer configured? Check `CHANNEL_LAYERS` in settings
3. Redis running? (production) or InMemoryChannelLayer? (dev)

**Resolution:**
- Refresh page to re-establish WebSocket connection
- In dev, InMemoryChannelLayer only works within same process
- For cross-process updates, configure Redis channel layer
- Check `consumers.py` for connection/disconnect errors in logs

---

## Appendix A: Database Schema Reference

### cms_experiment Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key (auto) |
| uuid | UUID | Unique identifier |
| user_id | ForeignKey | Owner (staff user) |
| name | CharField(255) | Display name |
| description | TextField | User-facing description |
| scenario_id | CharField(100) | Scenario template ID |
| agent_id | ForeignKey | Optional agent config |
| status | CharField(20) | draft/queued/running/completed/cancelled/failed |
| total_runs | PositiveInteger | 1-10 |
| max_parallel_runs | PositiveInteger | 1-5 |
| created_at | DateTimeField | Creation timestamp |
| started_at | DateTimeField | When first started (nullable) |
| completed_at | DateTimeField | When reached terminal state (nullable) |
| error_message | TextField | Error details (if failed) |

### cms_experimentrun Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key (auto) |
| uuid | UUID | Unique identifier |
| experiment_id | ForeignKey | Parent experiment |
| run_number | PositiveInteger | 1-based run index |
| request_id | UUID | Links to CMS Request (nullable) |
| status | CharField(20) | pending/provisioning/executing_victims/executing_attacker/collecting/completed/failed |
| started_at | DateTimeField | When provisioning started (nullable) |
| completed_at | DateTimeField | When reached terminal state (nullable) |
| error_message | TextField | Error details (if failed) |
| metadata | JSONField | Runtime data: IPs, task ARNs, etc. (nullable) |

### cms_experimentscript Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key (auto) |
| experiment_id | ForeignKey | Parent experiment |
| instance_name | CharField(100) | Instance from scenario template |
| script_type | CharField(20) | python / claude_code |
| script_id | ForeignKey | ScriptAsset (nullable, for Python type) |
| claude_prompt | TextField | Claude prompt text (for Claude type) |
| execution_order | PositiveInteger | Lower = earlier; < 100 = victim, >= 100 = attacker |

### cms_scriptasset Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key (auto) |
| user_id | ForeignKey | Owner |
| name | CharField(255) | User-provided name |
| s3_key | CharField(500) | S3 object key |
| original_filename | CharField(255) | Original upload filename |
| file_size_bytes | BigInteger | File size |
| deleted_at | DateTimeField | Soft delete timestamp (nullable) |

---

## Appendix B: Quick Command Reference

### Database Queries (via shifter-ops MCP)

```sql
-- List all experiments
SELECT id, name, status, total_runs, created_at FROM cms_experiment ORDER BY created_at DESC;

-- List runs for an experiment
SELECT run_number, status, started_at, completed_at FROM cms_experimentrun
WHERE experiment_id = <id> ORDER BY run_number;

-- List script assignments
SELECT instance_name, script_type, execution_order FROM cms_experimentscript
WHERE experiment_id = <id> ORDER BY execution_order;

-- Check active runs (never exceed max_parallel)
SELECT run_number, status FROM cms_experimentrun
WHERE experiment_id = <id> AND status NOT IN ('completed', 'failed', 'pending');

-- Cleanup UAT data
DELETE FROM cms_experiment WHERE name LIKE 'UAT%';
DELETE FROM cms_scriptasset WHERE name LIKE 'uat_%';
```

### CloudWatch Log Queries (via shifter-ops MCP)

```
-- Experiment orchestration events
fields @timestamp, @message
| filter @message like /experiment|orchestrat|schedule_runs/
| sort @timestamp desc
| limit 50

-- Error-level messages
fields @timestamp, @message
| filter @message like /ERROR/ AND @message like /experiment/
| sort @timestamp desc
| limit 20
```

### Common URLs

- Experiment List: `/mission-control/experiments/`
- Create Experiment: `/mission-control/experiments/create/`
- Experiment Detail: `/mission-control/experiments/<id>/`
- Start Experiment: `/mission-control/experiments/<id>/start/` (POST)
- Cancel Experiment: `/mission-control/experiments/<id>/cancel/` (POST)
- Script List: `/mission-control/experiments/scripts/`
- Script Upload: `/mission-control/experiments/scripts/upload/`
- Download Artifacts: `/mission-control/experiments/<id>/download/`

---

**End of UAT Protocol**
