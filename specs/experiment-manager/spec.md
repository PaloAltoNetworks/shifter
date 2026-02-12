# Feature Specification: Experiment Manager

**Feature Branch**: `claude/experiment-manager-app-Bv5qo`
**Created**: 2026-02-08
**Status**: Draft
**Input**: User description: "Experiment Manager app for the Shifter Django platform"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Upload Script Assets (Priority: P1)

A staff user uploads Python scripts that will be used in experiments. Scripts are file assets stored in S3, following the same upload pattern as XDR agent uploads. Each script is associated with the user and can be reused across multiple experiments.

**Why this priority**: Scripts are the fundamental input to experiments. Without the ability to upload and manage scripts, no experiment can be configured. This is the foundational building block.

**Independent Test**: A staff user can navigate to a script management page, upload a `.py` file, see it listed, and delete it. No experiment infrastructure required.

**Acceptance Scenarios**:

1. **Given** a staff user on the script upload page, **When** they select a Python file and submit, **Then** the file is uploaded to S3 and appears in their script list with name, filename, and upload date.
2. **Given** a staff user with uploaded scripts, **When** they view the script list, **Then** they see all their active (non-deleted) scripts.
3. **Given** a staff user viewing a script, **When** they click delete, **Then** the script is soft-deleted from the list and removed from S3.
4. **Given** a non-staff user, **When** they attempt to access the scripts page, **Then** they are denied access.

---

### User Story 2 - Create and Configure an Experiment (Priority: P1)

A staff user creates an experiment by selecting a scenario, setting the number of runs and parallelism, and assigning scripts to specific instances in the scenario. For the attacker instance, the user can alternatively provide a Claude Code prompt instead of a script.

**Why this priority**: Experiment configuration is the core user workflow. Without it, there's nothing to run. Co-equal with script upload since both are needed for a minimum viable experiment.

**Independent Test**: A staff user can create an experiment in draft state with full configuration. Verifiable by inspecting the saved experiment and its script assignments without running anything.

**Acceptance Scenarios**:

1. **Given** a staff user on the experiment creation page, **When** they select a scenario, **Then** the form displays all instances from that scenario template (by name and role) with script assignment controls for each.
2. **Given** a staff user configuring an experiment, **When** they set total runs to 7 and max parallel to 3, **Then** the experiment saves with those values.
3. **Given** a staff user configuring an experiment, **When** they assign a Python script to "Workstation" and a Claude Code prompt to "Attacker", **Then** both assignments are saved correctly with the experiment.
4. **Given** a staff user configuring an experiment, **When** they attempt to assign a Claude Code prompt to a non-attacker instance, **Then** the system prevents it (only Python scripts allowed for non-attacker instances).
5. **Given** a staff user configuring an experiment, **When** they leave an instance with no script assigned, **Then** the experiment saves successfully (scripts are optional per instance).
6. **Given** a staff user, **When** they provide a Claude Code prompt containing template variables like `{{Workstation.ip}}`, **Then** the system accepts the prompt and stores it with variables unresolved (they resolve at execution time).

---

### User Story 3 - Run an Experiment (Priority: P1)

A staff user starts a configured experiment. The system provisions ranges, executes scripts on each instance in the correct order, collects outputs, and tears down ranges. Runs execute in batches up to the parallelism limit.

**Why this priority**: This is the core value of the entire feature — automated, repeated attack runs with telemetry collection. Without execution, the feature delivers no value.

**Independent Test**: A staff user starts an experiment and can observe runs transitioning through states (pending, provisioning, executing, collecting, completed). Each run provisions its own range, runs scripts, collects artifacts, and destroys the range.

**Acceptance Scenarios**:

1. **Given** an experiment in draft state with valid configuration, **When** the user clicks "Start Experiment", **Then** the experiment transitions to running, N run records are created, and the first batch (up to max_parallel) begins provisioning ranges.
2. **Given** a run whose range has reached READY status, **When** the system begins script execution, **Then** all non-attacker instance scripts execute first (in parallel with each other), and only after all complete does the attacker script execute.
3. **Given** a run with a Claude Code prompt on the attacker, **When** the attacker phase executes, **Then** the system runs `claude -p "<prompt>" --dangerously-skip-permissions --output-format stream-json` on the Kali box, with template variables resolved to actual instance IPs/hostnames from the provisioned range.
4. **Given** a run where all scripts have completed, **When** the collection phase begins, **Then** stdout/stderr from each script and the full Claude Code stream-json transcript are uploaded to S3 as run artifacts.
5. **Given** a run that has completed artifact collection, **When** collection finishes, **Then** the range is destroyed and the next pending run (if any) begins provisioning.
6. **Given** a run where a script fails or times out, **When** the failure is detected, **Then** the run is marked as failed with an error message, the range is still destroyed, and remaining runs continue.
7. **Given** an experiment with 10 runs and max_parallel=5, **When** started, **Then** exactly 5 runs provision simultaneously, and as each completes, a new pending run starts until all 10 have run.

---

### User Story 4 - Monitor Experiment Progress (Priority: P2)

A staff user views real-time progress of a running experiment, seeing which runs are in which state, and receiving updates as runs progress through their lifecycle.

**Why this priority**: Users need visibility into long-running experiments. Without progress monitoring, they have no way to know what's happening. Important but secondary to the core execution flow.

**Independent Test**: A staff user views an experiment detail page and sees a run status grid that updates in real time as runs transition through states.

**Acceptance Scenarios**:

1. **Given** a running experiment, **When** the user views the experiment detail page, **Then** they see a grid/table of all runs with current status, start time, and elapsed time for each.
2. **Given** a running experiment, **When** a run transitions to a new state, **Then** the UI updates without requiring a page refresh.
3. **Given** a completed experiment, **When** the user views the detail page, **Then** they see a summary showing total runs, successes, failures, and total elapsed time.

---

### User Story 5 - Download Experiment Artifacts (Priority: P2)

A staff user downloads the output artifacts from completed experiment runs, either individually per run or as a full experiment bundle.

**Why this priority**: Artifacts are the entire point of running experiments — without downloadable results, the experiments produce no usable output. Important but secondary to core execution since artifacts must exist before they can be downloaded.

**Independent Test**: After an experiment completes, a user clicks download links and receives the correct files.

**Acceptance Scenarios**:

1. **Given** a completed run with artifacts, **When** the user clicks a download link for a specific run artifact, **Then** the browser downloads the file via a presigned S3 URL.
2. **Given** a completed experiment, **When** the user clicks "Download All", **Then** the browser downloads a zip archive containing all run artifacts organized by run number and instance name, plus a metadata file summarizing the experiment configuration and results.
3. **Given** a run artifact from a Claude Code execution, **When** downloaded, **Then** the JSONL file contains the complete stream-json output including all tool calls, reasoning steps, and results.
4. **Given** an experiment with some failed runs, **When** the user downloads artifacts, **Then** failed runs include whatever partial output was captured before failure, plus error information.

---

### User Story 6 - Manage Experiments (Priority: P3)

A staff user views their list of experiments, cancels running experiments, and deletes completed experiments.

**Why this priority**: Lifecycle management is important for housekeeping but not critical for the core experiment workflow. Users can work with experiments effectively without cancel/delete initially.

**Independent Test**: A staff user can view their experiment list, see status of each, and cancel a running experiment.

**Acceptance Scenarios**:

1. **Given** a staff user on the experiments list page, **When** they view the list, **Then** they see all their experiments with name, scenario, status, run count, and creation date.
2. **Given** a running experiment, **When** the user clicks "Cancel", **Then** no new runs start, currently executing runs complete their current phase and then their ranges are destroyed, and the experiment is marked as cancelled.
3. **Given** experiments in various states, **When** the user views the list, **Then** experiments are sorted by most recent first with clear status indicators.

---

### Edge Cases

- What happens when a range fails to provision during an experiment run? The run is marked as failed, the failure is logged, and the next pending run starts. The experiment continues.
- What happens when SSM connectivity is lost mid-script? The script execution times out, the run is marked as failed with a timeout error, and the range is destroyed.
- What happens when Claude Code crashes or hangs on the attacker? There is a configurable timeout (default: 30 minutes). If exceeded, the process is killed, whatever output exists is collected, and the run is marked as failed.
- What happens when all runs in an experiment fail? The experiment is marked as completed (not failed — it ran to completion, but all runs individually failed). The status of each run is visible.
- What happens when the user starts an experiment but the scenario requires an XDR agent and none is configured? Validation at experiment start prevents this — the user must select an agent if the scenario requires one.
- What happens if S3 artifact upload fails during collection? The run is marked as failed with collection error. Partial artifacts that were uploaded remain accessible.
- What happens when template variables in a Claude prompt reference an instance name that doesn't exist in the scenario? Validation at experiment creation prevents this — template variables are checked against the scenario's instance names.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST restrict all experiment functionality to staff users only.
- **FR-002**: System MUST allow staff users to upload Python script files as reusable assets, stored in S3 following the existing file asset pattern (presigned URL, HMAC token verification).
- **FR-003**: System MUST allow staff users to create experiments by selecting a scenario template, configuring total runs (1-10), and max parallel runs (1-5).
- **FR-004**: System MUST allow staff users to assign 0 or 1 script per instance (by instance name from the scenario template) in an experiment.
- **FR-005**: System MUST support two script types for attacker instances: Python script (file upload) or Claude Code prompt (text with template variables).
- **FR-006**: System MUST support only Python script type for non-attacker instances.
- **FR-007**: System MUST resolve template variables in Claude Code prompts at execution time. Supported variables: `{{InstanceName.ip}}` and `{{InstanceName.hostname}}` for each instance in the scenario, and `{{scenario.name}}`.
- **FR-008**: System MUST provision a dedicated range per experiment run using the existing range provisioning flow.
- **FR-009**: System MUST execute scripts in order: all non-attacker instance scripts first (in parallel), then attacker script after all non-attacker scripts complete.
- **FR-010**: System MUST run Claude Code prompts on the attacker box via SSM with `--dangerously-skip-permissions --output-format stream-json`, capturing all output to a file.
- **FR-011**: System MUST collect all script outputs (stdout, stderr) and Claude Code transcripts from each instance after execution and upload them to S3 as run artifacts.
- **FR-012**: System MUST destroy each run's range after artifact collection completes (or after failure).
- **FR-013**: System MUST respect the max_parallel_runs limit, queuing excess runs and starting them as earlier runs complete.
- **FR-014**: System MUST provide real-time progress updates for running experiments via WebSocket.
- **FR-015**: System MUST provide download links for individual run artifacts and a complete experiment artifact bundle.
- **FR-016**: System MUST include experiment and run metadata (configuration, timing, instance details, status) in the artifact bundle.
- **FR-017**: System MUST allow cancellation of running experiments, stopping new runs from starting while allowing in-progress runs to complete their current phase.
- **FR-018**: System MUST validate experiment configuration at start time: scenario exists, required agents are selected, template variables reference valid instance names, and run/parallelism limits are within bounds.
- **FR-019**: System MUST appear as a new entry in the Mission Control sidebar, visible only to staff users.

### Key Entities

- **ScriptAsset**: A user-owned Python script file stored in S3. Attributes: name, S3 key, filename, file size, hash, owner. Follows the existing FileAsset soft-delete pattern. Reusable across experiments.
- **Experiment**: A configured set of repeated runs of a scenario. Attributes: name, description, scenario reference, agent reference, total runs, max parallel runs, status, owner. Contains script assignments and runs.
- **ExperimentScript**: A script assignment binding a script (or Claude Code prompt) to a specific instance name within an experiment. Attributes: target instance name, script type, script reference or Claude prompt text, execution order. One per instance per experiment.
- **ExperimentRun**: A single execution of the experiment's scenario. Attributes: run number, status, request ID (links to range provisioning), timing data, error information, metadata. Contains artifacts.
- **RunArtifact**: A collected output file from a specific instance within a run. Attributes: instance name, artifact type, S3 key, file size. Types include script output and Claude Code transcript.
- **ExperimentArtifact**: The bundled zip of all run artifacts for an experiment, plus metadata. One per completed experiment.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Staff users can create, configure, and start an experiment within 5 minutes.
- **SC-002**: An experiment with 10 runs and max parallel 5 completes all runs without manual intervention.
- **SC-003**: All script outputs and Claude Code transcripts are captured and downloadable for every completed run.
- **SC-004**: Failed runs do not block the remainder of the experiment — subsequent runs continue automatically.
- **SC-005**: Users can monitor experiment progress in real time without refreshing the page.
- **SC-006**: Downloaded artifact bundles contain complete metadata sufficient to reproduce the experiment configuration.
- **SC-007**: Experiment functionality is invisible to non-staff users — no sidebar entry, no accessible URLs.

## Assumptions

- Claude Code is already installed and configured for Bedrock on all range AMIs (Kali, Ubuntu, Windows). No changes to AMI configuration required.
- Bedrock IAM permissions are already granted to all range instances. No IAM changes required.
- The existing CMS `create_range()` and `destroy_range()` functions work correctly and will be used as-is for experiment runs.
- The existing SNS/SQS event system will be extended with a new handler for experiment-aware range status processing.
- SSM connectivity to range instances is reliable enough for script execution and artifact collection.
- Script execution timeout defaults to 30 minutes and Claude Code execution timeout defaults to 30 minutes. These are system defaults, not user-configurable initially.
- The experiment orchestrator runs as a management command or within the existing SQS worker process, not as a separate service.
- Template variable resolution uses the instance name from the scenario template (e.g., "Attacker", "Workstation") mapped to provisioned instance IPs at execution time.
- The max parallel runs limit (5) and max total runs limit (10) are system-wide constants initially, not per-user configurable.
