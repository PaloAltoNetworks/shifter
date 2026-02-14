# Data Model: Experiment Manager

**Feature**: Experiment Manager
**Date**: 2026-02-08

## Entity Relationship Overview

```
User (auth.User)
 ├── 1:N ScriptAsset        (user-owned script files in S3)
 └── 1:N Experiment          (user-owned experiment configs)
          ├── N:1 ScenarioTemplate  (reference, by scenario_id string)
          ├── N:1 AgentConfig       (optional, FK to cms.AgentConfig)
          ├── 1:N ExperimentScript  (0..1 per instance name)
          │        └── N:1 ScriptAsset  (optional FK, for python type)
          ├── 1:N ExperimentRun     (one per run)
          │        └── 1:N RunArtifact  (outputs per instance per run)
          └── 0:1 ExperimentArtifact (final bundle zip)
```

## Entities

### ScriptAsset

Extends the existing `FileAsset` abstract model (same pattern as `AgentConfig`).

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | AutoField (PK) | | Primary key |
| name | CharField(255) | required | User-provided display name |
| user | FK → User | CASCADE | Owner |
| s3_key | CharField(500) | required | S3 object key |
| original_filename | CharField(255) | required | Original upload filename |
| file_size_bytes | PositiveBigIntegerField | required | File size |
| sha256_hash | CharField(64) | blank | Content hash |
| created_at | DateTimeField | auto_now_add | Upload timestamp |
| deleted_at | DateTimeField | null, blank | Soft delete timestamp |

**Validation rules**:
- File extension must be `.py`
- File size must be <= 1MB
- User must be staff
- Filename sanitized (no path traversal)

**S3 key pattern**: `scripts/{user_id}/{unique_id}_{filename}`

**Manager**: `active_for_user(user)` returns non-deleted scripts for user.

---

### Experiment

Top-level experiment configuration container.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | AutoField (PK) | | Primary key |
| uuid | UUIDField | unique, indexed, default=uuid4 | Cross-service correlation |
| user | FK → User | CASCADE | Owner (staff only) |
| name | CharField(255) | required | Display name |
| description | TextField | blank | Optional description |
| scenario_id | CharField(100) | required | Scenario template ID (e.g., "basic", "ad_attack_lab") |
| agent | FK → cms.AgentConfig | SET_NULL, null, blank | XDR agent for victim instances |
| status | CharField(20) | indexed, default="draft" | Lifecycle state |
| total_runs | PositiveIntegerField | default=1 | Number of runs (1-10) |
| max_parallel_runs | PositiveIntegerField | default=1 | Parallelism limit (1-5) |
| created_at | DateTimeField | auto_now_add | Creation timestamp |
| updated_at | DateTimeField | auto_now | Last modified |
| started_at | DateTimeField | null, blank | When experiment started |
| completed_at | DateTimeField | null, blank | When experiment finished |
| error_message | TextField | blank | Error details if failed |

**Status transitions**:
```
draft → queued → running → completed
                         → cancelled
                         → failed
```

**Validation rules**:
- `total_runs`: 1-10
- `max_parallel_runs`: 1-5, must be <= total_runs
- `scenario_id` must reference a valid, enabled scenario template
- `agent` required if scenario `requires_agent()` returns True
- User must be staff

---

### ExperimentScript

Binds a script (or Claude Code prompt) to a specific instance in the experiment.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | AutoField (PK) | | Primary key |
| experiment | FK → Experiment | CASCADE | Parent experiment |
| instance_name | CharField(100) | required | Instance name from scenario template (e.g., "Attacker", "Workstation") |
| script_type | CharField(20) | required | "python" or "claude_code" |
| script | FK → ScriptAsset | SET_NULL, null, blank | Python script (for script_type=python) |
| claude_prompt | TextField | blank | Claude Code prompt text (for script_type=claude_code) |
| execution_order | PositiveIntegerField | default=0 | Lower = earlier. Non-attacker instances get 0, attacker gets 100. |

**Constraints**:
- UNIQUE(experiment, instance_name)
- `script_type=claude_code` only allowed when instance role is "attacker"
- If `script_type=python`, `script` FK is required
- If `script_type=claude_code`, `claude_prompt` is required
- `instance_name` must match an instance in the experiment's scenario template

**Validation rules**:
- Template variables in `claude_prompt` must reference valid instance names from scenario
- Supported variable patterns: `{{InstanceName.ip}}`, `{{InstanceName.hostname}}`, `{{scenario.name}}`

---

### ExperimentRun

A single execution of the experiment's scenario.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | AutoField (PK) | | Primary key |
| uuid | UUIDField | unique, indexed, default=uuid4 | Correlation key |
| experiment | FK → Experiment | CASCADE | Parent experiment |
| run_number | PositiveIntegerField | required | 1-based run index |
| request_id | UUIDField | null, blank, indexed | Links to CMS/Engine Request (set on provisioning start) |
| status | CharField(20) | indexed, default="pending" | Lifecycle state |
| started_at | DateTimeField | null, blank | When run started |
| completed_at | DateTimeField | null, blank | When run finished |
| error_message | TextField | blank | Error details if failed |
| metadata | JSONField | null, blank | Runtime data: instance IPs, timing, etc. |

**Status transitions**:
```
pending → provisioning → executing_victims → executing_attacker → collecting → completed
                      → failed (at any point)
```

**Constraints**:
- UNIQUE(experiment, run_number)

---

### RunArtifact

Collected output from a specific instance within a run.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | AutoField (PK) | | Primary key |
| run | FK → ExperimentRun | CASCADE | Parent run |
| instance_name | CharField(100) | required | Instance that produced this artifact |
| artifact_type | CharField(30) | required | "script_output", "claude_transcript" |
| s3_key | CharField(500) | required | S3 object key |
| file_size_bytes | PositiveBigIntegerField | default=0 | Artifact file size |
| created_at | DateTimeField | auto_now_add | Collection timestamp |

**S3 key pattern**: `experiments/{experiment_id}/runs/{run_number}/{instance_name}/{artifact_type}.tar.gz`

---

### ExperimentArtifact

Bundled zip of all run artifacts for a completed experiment.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | AutoField (PK) | | Primary key |
| experiment | OneToOneField → Experiment | CASCADE | Parent experiment |
| s3_key | CharField(500) | required | S3 object key |
| file_size_bytes | PositiveBigIntegerField | default=0 | Bundle size |
| created_at | DateTimeField | auto_now_add | Bundle creation timestamp |

**S3 key pattern**: `experiments/{experiment_id}/bundle.zip`

**Bundle structure**:
```
experiment_{name}_{id}/
├── metadata.json          # Experiment config, timing, results summary
├── run_01/
│   ├── metadata.json      # Run config, instance IPs, timing
│   ├── Attacker/
│   │   └── claude_transcript.jsonl
│   └── Workstation/
│       └── script_output.tar.gz
├── run_02/
│   └── ...
└── run_N/
    └── ...
```

## State Machine: Experiment

```
     ┌─────────┐
     │  draft   │  User creates and configures
     └────┬─────┘
          │ start()
     ┌────▼─────┐
     │  queued   │  Validated, runs created
     └────┬─────┘
          │ first batch provisions
     ┌────▼─────┐
     │ running   │  Runs executing in batches
     └──┬──┬──┬─┘
        │  │  │
        │  │  └──────────────┐
        │  │           ┌─────▼─────┐
        │  │           │ cancelled  │  User cancelled
        │  │           └───────────┘
        │  │
        │  └─────────────────┐
        │              ┌─────▼─────┐
        │              │  failed    │  Unrecoverable error
        │              └───────────┘
        │
   ┌────▼──────┐
   │ completed  │  All runs finished
   └───────────┘
```

## State Machine: ExperimentRun

```
     ┌──────────┐
     │  pending  │  Waiting for batch slot
     └────┬─────┘
          │ range provisioning started
     ┌────▼──────────┐
     │ provisioning   │  Range being created
     └────┬──────────┘
          │ range READY
     ┌────▼──────────────┐
     │ executing_victims  │  Non-attacker scripts running
     └────┬──────────────┘
          │ all victim scripts done
     ┌────▼───────────────┐
     │ executing_attacker  │  Attacker script running
     └────┬───────────────┘
          │ attacker script done
     ┌────▼──────────┐
     │  collecting    │  Uploading artifacts to S3
     └────┬──────────┘
          │ artifacts uploaded, range destroyed
     ┌────▼──────────┐
     │  completed     │  Done
     └──────────────┘

     Any state → failed (on error)
```

## Indexes

| Table | Column(s) | Type | Rationale |
|-------|-----------|------|-----------|
| experiment | user_id | FK index | List experiments for user |
| experiment | status | B-tree | Filter by status |
| experiment | uuid | Unique | Cross-service lookup |
| experiment_run | experiment_id | FK index | List runs for experiment |
| experiment_run | status | B-tree | Batch scheduling queries |
| experiment_run | request_id | B-tree | Event handler lookup |
| experiment_run | uuid | Unique | Cross-service lookup |
| run_artifact | run_id | FK index | List artifacts for run |
| experiment_script | experiment_id, instance_name | Unique composite | One script per instance |
| script_asset | user_id | FK index | List scripts for user |
