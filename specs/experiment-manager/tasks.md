# Tasks: Experiment Manager

**Input**: Design documents from `specs/experiment-manager/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: TDD workflow per `.claude/skills/tdd-plan/SKILL.md` is MANDATORY. Each implementation task is preceded by its test.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

All paths are relative to repository root. Django app at `shifter/shifter_platform/experiments/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the Django app skeleton, register it, wire up routing and sidebar.

- [ ] T001 Create experiments app directory structure per plan.md: `shifter/shifter_platform/experiments/` with `__init__.py`, `apps.py`, `admin.py`, `models.py`, `services.py`, `handlers.py`, `orchestrator.py`, `template_vars.py`, `s3.py`, `urls.py`, `views.py`
- [ ] T002 Create `ExperimentsConfig` in `shifter/shifter_platform/experiments/apps.py` with `name = "experiments"` and `default_auto_field`
- [ ] T003 Register `experiments` in `INSTALLED_APPS` in `shifter/shifter_platform/config/settings.py` (after `cms`)
- [ ] T004 Add SQS queue config for experiments in `shifter/shifter_platform/config/settings.py` under `SQS_QUEUE_CONFIG`
- [ ] T005 [P] Add URL routing: `path("mission-control/experiments/", include("experiments.urls"))` in `shifter/shifter_platform/config/urls.py`
- [ ] T006 [P] Create empty `shifter/shifter_platform/experiments/urls.py` with `app_name = "experiments"`
- [ ] T007 [P] Add staff-only Experiments entry to sidebar in `shifter/shifter_platform/templates/partials/icon_sidebar.html` (between Risk Register and Docs, wrapped in `{% if user.is_staff %}`)
- [ ] T008 [P] Create `shifter/shifter_platform/experiments/templates/experiments/` directory with empty placeholder templates
- [ ] T009 [P] Create `shifter/shifter_platform/experiments/tests/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: All models, migrations, and admin registration. These MUST be complete before any user story implementation.

**CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T010 Write tests for ScriptAsset model in `shifter/shifter_platform/experiments/tests/test_models.py` — test creation, soft delete, `active_for_user` manager, `.py` validation
- [ ] T011 [P] Write tests for Experiment model in `shifter/shifter_platform/experiments/tests/test_models.py` — test creation, status transitions, validation (total_runs 1-10, max_parallel 1-5), uuid generation
- [ ] T012 [P] Write tests for ExperimentScript model in `shifter/shifter_platform/experiments/tests/test_models.py` — test unique constraint (experiment, instance_name), script_type validation, claude_code only for attacker
- [ ] T013 [P] Write tests for ExperimentRun model in `shifter/shifter_platform/experiments/tests/test_models.py` — test creation, status transitions, unique constraint (experiment, run_number), metadata JSONField
- [ ] T014 [P] Write tests for RunArtifact and ExperimentArtifact models in `shifter/shifter_platform/experiments/tests/test_models.py` — test creation, FK relationships
- [ ] T015 Implement ScriptAsset model in `shifter/shifter_platform/experiments/models.py` — extends `cms.models.FileAsset`, FK to User, `active_for_user()` manager
- [ ] T016 Implement Experiment model in `shifter/shifter_platform/experiments/models.py` — all fields per data-model.md, Status choices, FK to User and cms.AgentConfig
- [ ] T017 Implement ExperimentScript model in `shifter/shifter_platform/experiments/models.py` — FK to Experiment and ScriptAsset, script_type choices, unique_together (experiment, instance_name)
- [ ] T018 Implement ExperimentRun model in `shifter/shifter_platform/experiments/models.py` — FK to Experiment, Status choices, unique_together (experiment, run_number), metadata JSONField
- [ ] T019 [P] Implement RunArtifact model in `shifter/shifter_platform/experiments/models.py` — FK to ExperimentRun, artifact_type choices
- [ ] T020 [P] Implement ExperimentArtifact model in `shifter/shifter_platform/experiments/models.py` — OneToOneField to Experiment
- [ ] T021 Create and run migrations: `python manage.py makemigrations experiments && python manage.py migrate`
- [ ] T022 Register all models in Django admin in `shifter/shifter_platform/experiments/admin.py` — list_display, list_filter, search_fields, raw_id_fields for user FKs, readonly_fields for auto-set fields
- [ ] T023 Run model tests to verify: `python manage.py test experiments.tests.test_models`

**Checkpoint**: All models exist, migrations run, admin registered. Foundation ready for user story implementation.

---

## Phase 3: User Story 1 — Upload Script Assets (Priority: P1)

**Goal**: Staff users can upload, list, and delete Python script files as reusable assets stored in S3.

**Independent Test**: Navigate to script management page, upload a `.py` file, see it listed, delete it.

### Tests for User Story 1

- [ ] T024 [P] [US1] Write tests for S3 script operations in `shifter/shifter_platform/experiments/tests/test_s3.py` — test `generate_presigned_upload_url()`, `generate_presigned_download_url()`, `delete_script_from_s3()`, filename sanitization
- [ ] T025 [P] [US1] Write tests for script services in `shifter/shifter_platform/experiments/tests/test_services.py` — test `create_script()`, `delete_script()`, `list_scripts()`, `initiate_script_upload()`, `complete_script_upload()`, staff validation, file size validation
- [ ] T026 [P] [US1] Write tests for script views in `shifter/shifter_platform/experiments/tests/test_views.py` — test `script_list`, `script_upload`, `script_delete` with staff/non-staff users, GET/POST methods

### Implementation for User Story 1

- [ ] T027 [US1] Implement S3 operations for scripts in `shifter/shifter_platform/experiments/s3.py` — `generate_presigned_upload_url()`, `generate_presigned_download_url()`, `delete_script_from_s3()`, `verify_s3_object_exists()` (following `cms/assets/s3.py` patterns)
- [ ] T028 [US1] Implement script upload token functions in `shifter/shifter_platform/experiments/s3.py` — `generate_upload_token()`, `verify_upload_token()` using HMAC (following `cms/assets/upload_token.py` pattern)
- [ ] T029 [US1] Implement script services in `shifter/shifter_platform/experiments/services.py` — `create_script()`, `delete_script()`, `list_scripts()`, `initiate_script_upload()`, `complete_script_upload()` with staff-only validation
- [ ] T030 [US1] Implement script URL routes in `shifter/shifter_platform/experiments/urls.py` — `scripts/`, `scripts/upload/`, `scripts/<id>/delete/`
- [ ] T031 [US1] Implement script views in `shifter/shifter_platform/experiments/views.py` — `script_list`, `script_upload`, `script_delete` with `@staff_member_required`
- [ ] T032 [US1] Create script list template in `shifter/shifter_platform/experiments/templates/experiments/script_list.html` — table of scripts with name, filename, size, date, delete button
- [ ] T033 [US1] Create script upload template in `shifter/shifter_platform/experiments/templates/experiments/script_upload.html` — form with name field, file picker (.py only), submit
- [ ] T034 [US1] Run US1 tests: `python manage.py test experiments.tests.test_s3 experiments.tests.test_services experiments.tests.test_views`

**Checkpoint**: Staff users can upload, list, and delete Python scripts. Independently testable — no experiment infrastructure needed.

---

## Phase 4: User Story 2 — Create and Configure an Experiment (Priority: P1)

**Goal**: Staff users can create experiments with scenario selection, run/parallelism config, and per-instance script assignments.

**Independent Test**: Create an experiment in draft state, verify all configuration saved correctly.

**Depends on**: US1 (scripts must exist to assign them)

### Tests for User Story 2

- [ ] T035 [P] [US2] Write tests for template variable validation in `shifter/shifter_platform/experiments/tests/test_template_vars.py` — test `parse_template_variables()`, `validate_template_variables()` against scenario instance names, supported variable patterns
- [ ] T036 [P] [US2] Write tests for experiment creation services in `shifter/shifter_platform/experiments/tests/test_services.py` — test `create_experiment()`, validation (runs 1-10, parallel 1-5, scenario exists, agent required check, claude_code only for attacker)
- [ ] T037 [P] [US2] Write tests for experiment views in `shifter/shifter_platform/experiments/tests/test_views.py` — test `experiment_create` GET (form loads with scenario list), POST (creates experiment + scripts), `scenario_instances` AJAX endpoint

### Implementation for User Story 2

- [ ] T038 [US2] Implement template variable parsing and validation in `shifter/shifter_platform/experiments/template_vars.py` — `parse_template_variables()`, `validate_template_variables()`, `resolve_template_variables()`
- [ ] T039 [US2] Implement experiment creation service in `shifter/shifter_platform/experiments/services.py` — `create_experiment()` with full validation (scenario, agent, scripts_config with per-instance assignments, template variable validation for claude_code prompts)
- [ ] T040 [US2] Implement `get_experiment()` and `list_experiments()` in `shifter/shifter_platform/experiments/services.py`
- [ ] T041 [US2] Add experiment URL routes in `shifter/shifter_platform/experiments/urls.py` — `create/`, `<id>/`, `api/scenario/<scenario_id>/instances/`
- [ ] T042 [US2] Implement `experiment_create` view in `shifter/shifter_platform/experiments/views.py` — GET renders form with scenario list, POST creates experiment with script assignments
- [ ] T043 [US2] Implement `scenario_instances` JSON endpoint in `shifter/shifter_platform/experiments/views.py` — returns instance names and roles for a scenario template (used by create form JS)
- [ ] T044 [US2] Create experiment create template in `shifter/shifter_platform/experiments/templates/experiments/experiment_create.html` — scenario dropdown, run count/parallelism inputs, dynamic per-instance script assignment section
- [ ] T045 [US2] Run US2 tests: `python manage.py test experiments.tests.test_template_vars experiments.tests.test_services experiments.tests.test_views`

**Checkpoint**: Staff users can create fully configured experiments in draft state. Scripts can be assigned per instance. Claude prompts validated.

---

## Phase 5: User Story 3 — Run an Experiment (Priority: P1)

**Goal**: Staff users start experiments which provision ranges, execute scripts in order, collect artifacts, and tear down.

**Independent Test**: Start an experiment, observe runs transitioning through states, verify artifacts in S3.

**Depends on**: US1 (scripts), US2 (experiment config)

### Tests for User Story 3

- [ ] T046 [P] [US3] Write tests for experiment start service in `shifter/shifter_platform/experiments/tests/test_services.py` — test `start_experiment()` validation, run creation, batch scheduling, status transitions
- [ ] T047 [P] [US3] Write tests for SQS event handler in `shifter/shifter_platform/experiments/tests/test_handlers.py` — test `process_event()` for range.status.updated (READY, FAILED, DESTROYED), run state machine transitions, batch scheduling on completion
- [ ] T048 [P] [US3] Write tests for ExperimentOrchestrator in `shifter/shifter_platform/experiments/tests/test_orchestrator.py` — test script upload steps, execution ordering (victims then attacker), artifact collection steps, Claude Code command generation, template variable resolution at execution time
- [ ] T049 [P] [US3] Write tests for experiment start view in `shifter/shifter_platform/experiments/tests/test_views.py` — test `experiment_start` POST, validation errors, redirect

### Implementation for User Story 3

- [ ] T050 [US3] Implement `start_experiment()` in `shifter/shifter_platform/experiments/services.py` — validate config, create ExperimentRun records, transition to queued→running, trigger first batch via CMS `create_range()`
- [ ] T051 [US3] Implement batch scheduling logic in `shifter/shifter_platform/experiments/services.py` — `_provision_next_batch()` checks pending runs, respects max_parallel, calls CMS `create_range()` for each, stores request_id on ExperimentRun
- [ ] T052 [US3] Implement SQS event handler in `shifter/shifter_platform/experiments/handlers.py` — `process_event()` dispatches range events, looks up ExperimentRun by request_id, advances state machine
- [ ] T053 [US3] Implement ExperimentOrchestrator in `shifter/shifter_platform/experiments/orchestrator.py` — compose SetupSteps for: upload scripts, execute victim scripts (parallel), execute attacker script, collect artifacts; uses SSMExecutor pattern
- [ ] T054 [US3] Implement Claude Code command generation in `shifter/shifter_platform/experiments/orchestrator.py` — builds `claude -p "<resolved_prompt>" --dangerously-skip-permissions --output-format stream-json > /tmp/experiment/{run_id}/claude_output.jsonl 2>&1` command with resolved template variables
- [ ] T055 [US3] Implement artifact collection in `shifter/shifter_platform/experiments/orchestrator.py` — SSM commands to tar outputs on each instance, upload to S3 using key pattern from data-model.md, create RunArtifact records
- [ ] T056 [US3] Implement run completion and teardown in `shifter/shifter_platform/experiments/services.py` — `_complete_run()` triggers CMS `destroy_range()`, `_check_experiment_completion()` marks experiment completed when all runs done
- [ ] T057 [US3] Implement ECS task trigger in `shifter/shifter_platform/experiments/services.py` — `_start_experiment_executor()` calls `ecs:RunTask` with run_id parameter (reusing provisioner task definition pattern from `engine/ecs.py`)
- [ ] T058 [US3] Add `<id>/start/` URL route in `shifter/shifter_platform/experiments/urls.py`
- [ ] T059 [US3] Implement `experiment_start` view in `shifter/shifter_platform/experiments/views.py` — POST only, calls `start_experiment()`, redirects to detail page
- [ ] T060 [US3] Run US3 tests: `python manage.py test experiments.tests.test_services experiments.tests.test_handlers experiments.tests.test_orchestrator experiments.tests.test_views`

**Checkpoint**: Experiments can be started and run to completion. Ranges provisioned, scripts executed in order, artifacts collected, ranges destroyed, batches scheduled.

---

## Phase 6: User Story 4 — Monitor Experiment Progress (Priority: P2)

**Goal**: Staff users see real-time progress of running experiments via WebSocket updates.

**Independent Test**: View experiment detail page, see run status grid updating in real time.

**Depends on**: US3 (runs must exist and transition)

### Tests for User Story 4

- [ ] T061 [P] [US4] Write tests for experiment detail view in `shifter/shifter_platform/experiments/tests/test_views.py` — test `experiment_detail` renders runs grid, status badges, timing info
- [ ] T062 [P] [US4] Write tests for WebSocket broadcasting in `shifter/shifter_platform/experiments/tests/test_handlers.py` — test that handler broadcasts run status changes to experiment channel group

### Implementation for User Story 4

- [ ] T063 [US4] Implement `experiment_detail` view in `shifter/shifter_platform/experiments/views.py` — loads experiment with runs, renders detail template with run status grid
- [ ] T064 [US4] Create experiment detail template in `shifter/shifter_platform/experiments/templates/experiments/experiment_detail.html` — experiment metadata, run status grid/table, start/cancel buttons, summary stats
- [ ] T065 [US4] Add WebSocket broadcasting to SQS handler in `shifter/shifter_platform/experiments/handlers.py` — on run status change, broadcast to `experiment_{experiment_id}` channel group using `channel_layer.group_send()`
- [ ] T066 [US4] Add WebSocket consumer for experiments — `ExperimentConsumer` that handles `experiment.run_status` and `experiment.status` message types, authenticates staff user, validates experiment ownership
- [ ] T067 [US4] Add WebSocket JavaScript to experiment detail template — connect to `ws://host/ws/experiments/<id>/`, update run status grid on message, show completion summary
- [ ] T068 [US4] Run US4 tests: `python manage.py test experiments.tests.test_views experiments.tests.test_handlers`

**Checkpoint**: Experiment detail page shows live run progress. Status updates flow: handler → channel group → WebSocket → browser.

---

## Phase 7: User Story 5 — Download Experiment Artifacts (Priority: P2)

**Goal**: Staff users download individual run artifacts or full experiment bundles via presigned S3 URLs.

**Independent Test**: After experiment completes, click download link and receive correct file.

**Depends on**: US3 (artifacts must exist in S3)

### Tests for User Story 5

- [ ] T069 [P] [US5] Write tests for artifact download services in `shifter/shifter_platform/experiments/tests/test_services.py` — test `get_artifact_download_url()`, `get_experiment_bundle_url()`, ownership validation
- [ ] T070 [P] [US5] Write tests for download views in `shifter/shifter_platform/experiments/tests/test_views.py` — test `artifact_download`, `experiment_download` redirect to presigned URLs, ownership checks

### Implementation for User Story 5

- [ ] T071 [US5] Implement `get_artifact_download_url()` in `shifter/shifter_platform/experiments/services.py` — validates ownership, generates presigned GET URL via `experiments/s3.py`
- [ ] T072 [US5] Implement `get_experiment_bundle_url()` in `shifter/shifter_platform/experiments/services.py` — validates ownership, generates presigned GET URL for bundle zip
- [ ] T073 [US5] Implement experiment bundle creation in `shifter/shifter_platform/experiments/services.py` — `_create_experiment_bundle()` downloads all run artifacts from S3, creates zip with metadata.json, uploads bundle to S3, creates ExperimentArtifact record
- [ ] T074 [US5] Add download URL routes in `shifter/shifter_platform/experiments/urls.py` — `<id>/download/`, `<id>/runs/<run_number>/artifacts/<artifact_id>/download/`
- [ ] T075 [US5] Implement `artifact_download` and `experiment_download` views in `shifter/shifter_platform/experiments/views.py` — generate presigned URLs, redirect browser to download
- [ ] T076 [US5] Add download links to experiment detail template in `shifter/shifter_platform/experiments/templates/experiments/experiment_detail.html` — per-run artifact links, "Download All" button for completed experiments
- [ ] T077 [US5] Run US5 tests: `python manage.py test experiments.tests.test_services experiments.tests.test_views`

**Checkpoint**: Artifacts downloadable individually and as bundles. Presigned URLs work. Metadata included in bundles.

---

## Phase 8: User Story 6 — Manage Experiments (Priority: P3)

**Goal**: Staff users view experiment list, cancel running experiments.

**Independent Test**: View experiment list, cancel a running experiment, verify it stops gracefully.

**Depends on**: US2 (experiments must exist), US3 (cancel requires running experiment)

### Tests for User Story 6

- [ ] T078 [P] [US6] Write tests for cancel service in `shifter/shifter_platform/experiments/tests/test_services.py` — test `cancel_experiment()` stops new runs, in-progress runs complete, status transitions
- [ ] T079 [P] [US6] Write tests for list and cancel views in `shifter/shifter_platform/experiments/tests/test_views.py` — test `experiment_list` shows all user experiments sorted, `experiment_cancel` POST works

### Implementation for User Story 6

- [ ] T080 [US6] Implement `cancel_experiment()` in `shifter/shifter_platform/experiments/services.py` — marks experiment as cancelled, stops scheduling new runs, allows in-progress runs to complete current phase then destroy ranges
- [ ] T081 [US6] Implement `experiment_list` view in `shifter/shifter_platform/experiments/views.py` — lists user's experiments with status, scenario, run counts, sorted by most recent
- [ ] T082 [US6] Add cancel URL route in `shifter/shifter_platform/experiments/urls.py` — `<id>/cancel/`
- [ ] T083 [US6] Implement `experiment_cancel` view in `shifter/shifter_platform/experiments/views.py` — POST only, calls `cancel_experiment()`, redirects to detail page
- [ ] T084 [US6] Create experiment list template in `shifter/shifter_platform/experiments/templates/experiments/experiment_list.html` — table with name, scenario, status badges, run count, dates, link to detail, "New Experiment" button
- [ ] T085 [US6] Run US6 tests: `python manage.py test experiments.tests.test_services experiments.tests.test_views`

**Checkpoint**: Experiment list page works. Cancellation is graceful. All basic lifecycle management in place.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Activity logging, error handling, final integration testing.

- [ ] T086 Add activity logging to all experiment services in `shifter/shifter_platform/experiments/services.py` — log create, start, cancel, complete events via `management.services.log_activity()`
- [ ] T087 Add error handling and logging throughout `shifter/shifter_platform/experiments/services.py` and `shifter/shifter_platform/experiments/handlers.py` — follow CMS service error handling pattern (re-raise known errors, catch-all with logging)
- [ ] T088 Verify all views return correct `active_nav = "experiments"` context for sidebar highlighting
- [ ] T089 Run full test suite: `python manage.py test experiments`
- [ ] T090 Run quickstart.md validation checklist

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2. No user story dependencies.
- **US2 (Phase 4)**: Depends on Phase 2. Soft dependency on US1 (needs scripts to assign, but can create experiments without scripts).
- **US3 (Phase 5)**: Depends on US1 + US2 (needs scripts and experiment config to run).
- **US4 (Phase 6)**: Depends on US3 (needs running experiment to monitor).
- **US5 (Phase 7)**: Depends on US3 (needs artifacts from completed runs).
- **US6 (Phase 8)**: Depends on US2 (needs experiments to list) and US3 (needs running experiment to cancel).
- **Polish (Phase 9)**: Depends on all user stories being complete.

### User Story Dependencies

```
Phase 1: Setup
    ↓
Phase 2: Foundational (models, migrations, admin)
    ↓
Phase 3: US1 - Script Upload ←─── required by US2, US3
    ↓
Phase 4: US2 - Create Experiment ←─── required by US3, US6
    ↓
Phase 5: US3 - Run Experiment ←─── required by US4, US5, US6
    ↓ (can be parallel after US3)
Phase 6: US4 - Monitor Progress  ┐
Phase 7: US5 - Download Artifacts ├── can run in parallel
Phase 8: US6 - Manage Experiments ┘
    ↓
Phase 9: Polish
```

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Models before services
- Services before views
- Views before templates
- Story complete before moving to next priority

### Parallel Opportunities

**Within Phase 2 (Foundational)**:
- T010-T014 (all model tests) can run in parallel
- T019-T020 (RunArtifact, ExperimentArtifact) can run in parallel

**Within US1 (Phase 3)**:
- T024-T026 (all US1 tests) can run in parallel

**Within US2 (Phase 4)**:
- T035-T037 (all US2 tests) can run in parallel

**Within US3 (Phase 5)**:
- T046-T049 (all US3 tests) can run in parallel

**After US3 is complete**:
- US4, US5, US6 (Phases 6-8) can proceed in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all tests for US1 together:
Task: T024 "Write tests for S3 script operations"
Task: T025 "Write tests for script services"
Task: T026 "Write tests for script views"

# After tests pass (verify they fail), launch implementation:
Task: T027 "Implement S3 operations for scripts"
Task: T028 "Implement script upload token functions"
# Then sequentially:
Task: T029 "Implement script services" (depends on T027, T028)
Task: T030-T033 "Views, URLs, templates"
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (models, migrations, admin)
3. Complete Phase 3: US1 — Script Upload
4. Complete Phase 4: US2 — Create Experiment
5. **STOP and VALIDATE**: Staff user can upload scripts and create configured experiments in draft state
6. Deploy/demo if ready (experiments exist in draft, can inspect via admin)

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 (Script Upload) → Test independently → Scripts work
3. US2 (Create Experiment) → Test independently → Experiments configurable
4. US3 (Run Experiment) → Test independently → **Core value delivered**
5. US4 (Monitor) → Real-time progress → User experience improved
6. US5 (Download) → Artifacts downloadable → **Full value delivered**
7. US6 (Manage) → List + cancel → Lifecycle management
8. Polish → Logging, error handling, final validation

### Critical Path

The critical path is: Setup → Foundation → US1 → US2 → US3 → US5 (download). This delivers the complete experiment workflow from creation through artifact download.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- TDD: Write tests first, verify they fail, then implement
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All views use `@staff_member_required` decorator (same as Risk Register)
- All services follow CMS validation pattern (validate user, validate params, try/catch)
- S3 operations follow `cms/assets/s3.py` patterns
- Event handler follows `cms/handlers.py` patterns
