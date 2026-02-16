# Implementation Plan: Experiment Manager

**Branch**: `claude/experiment-manager-app-Bv5qo` | **Date**: 2026-02-08 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/experiment-manager/spec.md`

## Summary

New Django app (`experiments`) enabling staff users to run repeated attack scenarios with per-instance script configuration, collect all telemetry (including Claude Code stream-json transcripts), and download structured artifact bundles. The app integrates with existing CMS range provisioning, SNS/SQS events, SSM command execution (via ECS task), and S3 storage. Experiment runs execute in parallel batches (max 5) with automatic scheduling.

## Technical Context

**Language/Version**: Python 3.11+ (Django 5.x)
**Primary Dependencies**: Django, Django Channels (WebSocket), boto3 (S3/SSM/ECS/SNS), Pydantic (validation)
**Storage**: PostgreSQL (models), Redis (channels), S3 (scripts and artifacts)
**Testing**: Django test framework (`manage.py test`)
**Target Platform**: Linux server (EC2 portal instance)
**Project Type**: Django app within existing monorepo
**Performance Goals**: N/A — experiments are long-running batch operations, not latency-sensitive
**Constraints**: Max 10 runs per experiment, max 5 parallel, 1MB script size limit
**Scale/Scope**: Staff-only (small user base), 6 new views, 6 new models, 1 new SQS handler

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Speed to Value | PASS | Self-service experiment creation, real-time WebSocket progress, turnkey execution |
| II. Safety & Isolation | PASS | Each run uses its own isolated range. Scripts execute inside range VPC. No new network exposure. |
| III. Human Oversight | PASS | User explicitly creates and starts experiments. All execution logged via ActivityLog. `--dangerously-skip-permissions` runs within isolated range only. |
| IV. Domain-Driven Design | PASS | New `experiments` app with service layer. Uses CMS services for range provisioning (not direct engine calls). |
| V. Infrastructure as Code | PASS | New SQS queue and SNS subscription via Terraform. ECS task definition in Terraform. |
| VI. Simplicity & Pragmatism | PASS | Follows existing patterns (FileAsset, service layer, SQS handler, ECS task). No new frameworks. |

### Post-Design Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Speed to Value | PASS | Same assessment. WebSocket progress keeps users informed during long runs. |
| II. Safety & Isolation | PASS | Same assessment. ECS executor model keeps SSM permissions out of portal. |
| III. Human Oversight | PASS | Same assessment. Every experiment action logged. Staff-only access. |
| IV. Domain-Driven Design | PASS | experiments.services exposes all functionality. Views have no business logic. Cross-domain via CMS service interface. |
| V. Infrastructure as Code | PASS | Terraform additions: SQS queue, SNS subscription, IAM for SQS. Minimal. |
| VI. Simplicity & Pragmatism | PASS | Reuses SSMExecutor, S3 patterns, FileAsset, SQS handler. No new dependencies. ExperimentOrchestrator mirrors SetupOrchestrator pattern. |

No constitution violations. No complexity tracking needed.

## Project Structure

### Documentation (this feature)

```text
specs/experiment-manager/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: Technical research
├── data-model.md        # Phase 1: Entity definitions and state machines
├── quickstart.md        # Phase 1: Development setup guide
├── contracts/
│   └── api-contracts.md # Phase 1: URL routes, WebSocket, service interfaces
└── checklists/
    └── requirements.md  # Specification quality checklist
```

### Source Code (repository root)

```text
shifter/shifter_platform/experiments/
├── __init__.py
├── admin.py                 # Django admin for all experiment models
├── apps.py                  # ExperimentsConfig
├── handlers.py              # SQS event handler (range events → run state machine)
├── models.py                # ScriptAsset, Experiment, ExperimentScript,
│                            #   ExperimentRun, RunArtifact, ExperimentArtifact
├── services.py              # Business logic: create, start, cancel, download
├── orchestrator.py          # ExperimentOrchestrator: script execution + artifact collection
├── template_vars.py         # Claude prompt template variable resolution
├── s3.py                    # S3 operations: script upload, artifact upload/download
├── urls.py                  # URL routing under experiments namespace
├── views.py                 # Staff-only views: list, create, detail, download
├── migrations/
│   └── 0001_initial.py
├── templates/
│   └── experiments/
│       ├── experiment_list.html
│       ├── experiment_create.html
│       ├── experiment_detail.html
│       ├── script_list.html
│       └── script_upload.html
└── tests/
    ├── __init__.py
    ├── test_models.py
    ├── test_services.py
    ├── test_handlers.py
    ├── test_orchestrator.py
    ├── test_template_vars.py
    └── test_views.py

# Sidebar modification (existing file)
shifter/shifter_platform/templates/partials/icon_sidebar.html

# Settings modification (existing file)
shifter/shifter_platform/config/settings.py

# URL routing modification (existing file)
shifter/shifter_platform/config/urls.py

# Infrastructure (new)
platform/terraform/modules/experiments/
├── sqs.tf                   # SQS queue + SNS subscription
└── iam.tf                   # SQS read permissions for portal/worker
```

**Structure Decision**: Standard Django app structure within the existing monorepo. Follows the pattern established by `risk_register` (staff-only app with views, services, models) and `cms` (file assets, S3 operations, SQS handlers). The orchestrator module follows the provisioner's `SetupOrchestrator` pattern. Infrastructure additions are minimal Terraform (SQS queue + subscription).

## Key Design Decisions

### D-001: ECS Task for Script Execution

Script execution on range instances happens via a new ECS task (reusing the provisioner task definition with a new CLI command), NOT from the Django portal directly. The portal lacks SSM permissions by design (Constitution II: Safety & Isolation). See [research.md R-001](research.md#r-001-remote-command-execution-on-range-instances).

### D-002: Event-Driven Orchestration

The experiment lifecycle is driven by SNS/SQS events. When a range reaches READY, the experiments handler picks up the event, advances the run state machine, and triggers script execution via ECS. No polling loops. See [research.md R-002](research.md#r-002-orchestration-pattern).

### D-003: Template Variables from Scenario Instance Names

Users reference instances by name from the scenario template (e.g., `{{Workstation.ip}}`), not by runtime values they can't know at configuration time. Variables resolve at execution time from `Range.provisioned_instances`. See [research.md R-005](research.md#r-005-template-variable-resolution).

### D-004: Range-Per-Run Isolation

Each experiment run provisions its own dedicated range. No range reuse between runs. Simpler than implementing range reset, and provides clean isolation. More expensive in time and compute, but experiments are batch operations where users don't need immediate results.

## Artifacts

| Artifact | Path | Description |
|----------|------|-------------|
| Specification | [spec.md](spec.md) | Feature requirements and user stories |
| Research | [research.md](research.md) | Technical decisions with rationale |
| Data Model | [data-model.md](data-model.md) | Entity definitions, state machines, indexes |
| API Contracts | [contracts/api-contracts.md](contracts/api-contracts.md) | URL routes, WebSocket, service interfaces |
| Quickstart | [quickstart.md](quickstart.md) | Development setup guide |
| Requirements Checklist | [checklists/requirements.md](checklists/requirements.md) | Spec quality validation |
