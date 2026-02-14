# API Contracts: Experiment Manager

**Feature**: Experiment Manager
**Date**: 2026-02-08

## Overview

The Experiment Manager uses Django server-rendered views (same pattern as Risk Register and Mission Control), not a REST API. User interactions are standard form submissions and page navigations. Real-time updates use WebSocket.

## URL Routes

**Namespace**: `experiments`
**URL prefix**: `/mission-control/experiments/`

### Page Routes

| Method | URL | View | Description |
|--------|-----|------|-------------|
| GET | `/mission-control/experiments/` | `experiment_list` | List all experiments for user |
| GET | `/mission-control/experiments/create/` | `experiment_create` | Create experiment form |
| POST | `/mission-control/experiments/create/` | `experiment_create` | Submit new experiment |
| GET | `/mission-control/experiments/<id>/` | `experiment_detail` | Experiment detail + run status |
| POST | `/mission-control/experiments/<id>/start/` | `experiment_start` | Start experiment execution |
| POST | `/mission-control/experiments/<id>/cancel/` | `experiment_cancel` | Cancel running experiment |

### Script Management Routes

| Method | URL | View | Description |
|--------|-----|------|-------------|
| GET | `/mission-control/experiments/scripts/` | `script_list` | List user's scripts |
| GET | `/mission-control/experiments/scripts/upload/` | `script_upload` | Upload script form |
| POST | `/mission-control/experiments/scripts/upload/` | `script_upload` | Submit script upload |
| POST | `/mission-control/experiments/scripts/<id>/delete/` | `script_delete` | Soft-delete script |

### Download Routes

| Method | URL | View | Description |
|--------|-----|------|-------------|
| GET | `/mission-control/experiments/<id>/download/` | `experiment_download` | Download experiment bundle |
| GET | `/mission-control/experiments/<id>/runs/<run_number>/artifacts/<artifact_id>/download/` | `artifact_download` | Download single artifact |

### AJAX/API Routes (for dynamic form behavior)

| Method | URL | View | Description |
|--------|-----|------|-------------|
| GET | `/mission-control/experiments/api/scenario/<scenario_id>/instances/` | `scenario_instances` | Get instance list for scenario (JSON) |

## Access Control

All routes require:
1. Authenticated user (`@login_required`)
2. Staff status (`@staff_member_required`)
3. Object ownership (user can only see/modify their own experiments)

## WebSocket Contract

### Connection

**URL**: `ws://<host>/ws/experiments/<experiment_id>/`

**Authentication**: Same session-based auth as existing WebSocket consumers.

**Authorization**: Staff user who owns the experiment.

### Server → Client Messages

#### Run Status Update
```json
{
    "type": "run.status",
    "run_number": 3,
    "run_uuid": "uuid-string",
    "status": "executing_victims",
    "started_at": "2026-02-08T12:00:00Z",
    "metadata": {}
}
```

#### Experiment Status Update
```json
{
    "type": "experiment.status",
    "experiment_uuid": "uuid-string",
    "status": "completed",
    "completed_at": "2026-02-08T14:30:00Z",
    "summary": {
        "total_runs": 10,
        "completed": 8,
        "failed": 2
    }
}
```

#### Artifact Ready
```json
{
    "type": "artifact.ready",
    "run_number": 3,
    "instance_name": "Attacker",
    "artifact_type": "claude_transcript",
    "artifact_id": 42
}
```

## Service Interface Contract

Following Constitution IV (Domain-Driven Design), the experiments app exposes functionality via `experiments.services`.

### experiments.services

```python
# Script management
def create_script(user, name, s3_key, filename, file_size, sha256) -> ScriptAsset
def delete_script(user, script_id) -> None
def list_scripts(user) -> QuerySet[ScriptAsset]

# Experiment lifecycle
def create_experiment(user, name, description, scenario_id, agent_id, total_runs, max_parallel_runs, scripts_config) -> Experiment
def start_experiment(user, experiment_id) -> Experiment
def cancel_experiment(user, experiment_id) -> Experiment
def get_experiment(user, experiment_id) -> Experiment
def list_experiments(user) -> QuerySet[Experiment]

# Artifact downloads
def get_artifact_download_url(user, artifact_id) -> str  # presigned S3 URL
def get_experiment_bundle_url(user, experiment_id) -> str  # presigned S3 URL

# Upload flow (same pattern as CMS agent uploads)
def initiate_script_upload(user, name, filename, file_size) -> dict  # {presigned_url, upload_token}
def complete_script_upload(user, upload_token) -> ScriptAsset
```

### experiments.handlers

```python
# SQS event handler (registered in settings.SQS_QUEUE_CONFIG)
def process_event(message: str | dict) -> None
```

Handles:
- `range.status.updated` — advances run state machine when range reaches READY or FAILED
- `range.destroyed` — marks range teardown complete for a run

## Template Variable Contract

Variables available in Claude Code prompts, resolved at execution time:

| Variable | Resolves To | Example |
|----------|-------------|---------|
| `{{InstanceName.ip}}` | Private IP of named instance | `{{Workstation.ip}}` → `10.1.5.101` |
| `{{InstanceName.hostname}}` | Hostname of named instance | `{{Attacker.hostname}}` → `kali-abc123` |
| `{{scenario.name}}` | Scenario template display name | `Basic Range` |

Instance name matching is case-sensitive and must match the scenario template exactly.
