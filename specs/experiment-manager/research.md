# Research: Experiment Manager

**Feature**: Experiment Manager
**Date**: 2026-02-08

## R-001: Remote Command Execution on Range Instances

**Decision**: Use SSM via a new ECS task (ExperimentExecutor), not direct portal-to-instance SSM.

**Rationale**: The portal EC2 instance does NOT have `ssm:SendCommand` IAM permissions. Only the Pulumi provisioner ECS task role has SSM permissions (`ssm:SendCommand`, `ssm:GetCommandInvocation`, `ssm:DescribeInstanceInformation`). Granting the portal direct SSM access would break the existing security model that separates presentation from infrastructure concerns. The established pattern is: portal triggers ECS task, ECS task has infrastructure permissions.

**Alternatives considered**:
- **Grant portal SSM permissions**: Rejected — violates domain separation (Constitution IV), increases portal attack surface.
- **SSH from portal**: Portal has SSH access via asyncssh + Secrets Manager keys, but SSH is designed for interactive terminal sessions, not orchestrated command execution. SSM is more reliable for automated scripts (handles reboots, timeouts, no SSH key rotation concerns).
- **Lambda proxy**: Adds operational complexity without clear benefit over ECS pattern already in use.

**Implementation**: Create a new ECS task definition (`experiment-executor`) that reuses the existing SSMExecutor class but is parameterized for experiment operations (run script, collect artifacts) rather than provisioning operations. The Django app triggers this task via `ecs:RunTask` (same pattern as `start_range_provisioning()`).

## R-002: Orchestration Pattern

**Decision**: Event-driven state machine using existing SNS/SQS infrastructure, with a new `experiments` SQS queue and handler.

**Rationale**: The existing SNS/SQS fan-out pattern (provisioner → SNS → SQS queues → handlers) is proven and scales well. The experiments app needs to:
1. React to range status events (READY, FAILED, DESTROYED)
2. Drive its own state machine (run phases, batch scheduling)
3. Broadcast progress to WebSocket clients

This maps directly to the existing pattern: subscribe a new `experiments` SQS queue to the SNS topic, add a handler that processes both range events and experiment-specific events.

**Alternatives considered**:
- **Celery**: Not used anywhere in the codebase. Adding it introduces a new dependency and operational concern. Rejected per Constitution VI (Simplicity).
- **Django management command polling loop**: Would work but doesn't integrate with the existing event system. The orchestrator would need to poll the database for state changes rather than being event-driven.
- **Synchronous in-request execution**: Impossible — runs take 10+ minutes each.

**Implementation**:
- New SQS queue subscribed to existing SNS topic
- New handler in `experiments/handlers.py` that processes `range.status.updated` events
- Handler checks if the range belongs to an experiment run, and if so, advances the run state machine
- For experiment-internal events (batch scheduling, artifact collection), the handler can publish to SNS or call services directly since it runs in the worker process

## R-003: Script Execution Architecture

**Decision**: Reuse existing SSMExecutor and SetupStep pattern from the provisioner, packaged as an ExperimentOrchestrator.

**Rationale**: The provisioner already has a battle-tested `SetupOrchestrator` that executes `SetupStep` sequences via SSM. The experiment execution is structurally identical:
1. Upload script to instance (SSM command)
2. Execute script (SSM command with timeout)
3. Collect output (SSM command to tar and read)

The `SetupStep` dataclass already supports: name, script, timeout, verification, stdin_input.

**Implementation**:
- `ExperimentOrchestrator` composes `SetupStep` objects for each phase
- Phase 1: Upload + execute non-attacker scripts (parallel across instances)
- Phase 2: Upload + execute attacker script
- Phase 3: Collect artifacts from all instances
- Each phase uses SSMExecutor to send commands
- All execution runs in the experiment-executor ECS task

## R-004: S3 Artifact Storage

**Decision**: Extend existing S3 patterns for both script uploads and artifact downloads.

**Rationale**: The codebase has a robust S3 pattern (presigned URLs, HMAC tokens, FileAsset model). Script uploads follow the same flow as agent uploads. Artifact downloads need presigned GET URLs (the inverse of the existing presigned PUT pattern).

**S3 key patterns**:
- Scripts: `scripts/{user_id}/{unique_id}_{filename}`
- Run artifacts: `experiments/{experiment_id}/runs/{run_number}/{instance_name}/{artifact_type}.tar.gz`
- Experiment bundle: `experiments/{experiment_id}/bundle.zip`

**Implementation**:
- `ScriptAsset` extends `FileAsset` (same as `AgentConfig`)
- Upload flow identical to agent uploads: presigned URL → browser upload → complete with HMAC token
- Validation: `.py` extension, 1MB size limit, text content check
- Artifact collection: ECS task uploads run outputs to S3 during collection phase
- Download: New `generate_presigned_download_url(s3_key)` function returning time-limited GET URL

## R-005: Template Variable Resolution

**Decision**: Simple string template substitution using scenario instance names mapped to provisioned instance data at execution time.

**Rationale**: Users write prompts at experiment creation time when ranges don't exist yet. They can't know IPs. But they know instance names from the scenario template (e.g., "Attacker", "Workstation", "Domain Controller"). At execution time, provisioned instance details are available in `Range.provisioned_instances` (JSON array with role, private_ip, hostname per instance).

**Supported variables**:
- `{{InstanceName.ip}}` → private IP of the named instance
- `{{InstanceName.hostname}}` → hostname of the named instance
- `{{scenario.name}}` → scenario template name

**Implementation**:
- At experiment creation: parse prompt for `{{...}}` patterns, validate instance names exist in scenario template
- At execution time: build context dict from `Range.provisioned_instances`, do `str.replace()` for each variable
- Instance name matching: normalize spaces/underscores (e.g., "Domain Controller" and "Domain_Controller" both match)

## R-006: Real-Time Progress Updates

**Decision**: Extend existing WebSocket channel group pattern with experiment-specific groups.

**Rationale**: Mission Control already uses Django Channels with Redis for real-time range status updates. The pattern is: handler receives SQS event → broadcasts to channel group → WebSocket consumer pushes to browser. Experiments need the same pattern.

**Implementation**:
- New channel group: `experiment_{experiment_id}`
- New WebSocket consumer: `ExperimentConsumer` in mission_control (or experiments app)
- Events broadcast: run status changes, phase transitions, completion
- UI connects on experiment detail page, disconnects on navigation away

## R-007: ECS Task for Experiment Execution

**Decision**: New ECS task definition (`experiment-executor`) separate from the Pulumi provisioner but sharing the same container image and IAM permissions for SSM.

**Rationale**: The experiment executor needs SSM permissions (to run scripts on instances) and S3 permissions (to upload artifacts), but does NOT need Pulumi/infrastructure provisioning permissions. However, for simplicity in the initial implementation, reusing the provisioner task definition with different command arguments is acceptable. The provisioner already has all needed permissions.

**Implementation**:
- Extend the provisioner CLI with new commands: `experiment execute --run-id <uuid>`
- The provisioner process receives the run ID, loads run configuration from DB, executes scripts via SSM, collects artifacts to S3
- Portal triggers via existing `ecs:RunTask` pattern
- Alternatively: new Terraform module for a dedicated experiment-executor task (cleaner separation, more initial work)

**Decision for initial implementation**: Reuse provisioner task definition with new CLI command. Separate task definition is a future optimization.
