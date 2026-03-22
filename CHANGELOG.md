# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.34.0] - 2026-03-22

### Changed
- **Terraform**: Rename remaining `pulumi_state_*`, `pulumi_locks_*`, `pulumi_secrets_*` variable names in `modules/engine-provisioner/variables.tf` to `engine_state_*`, `engine_locks_*`, `engine_secrets_*`
- **Terraform**: Rename remaining `pulumi_state_*`, `pulumi_locks_*`, `pulumi_secrets_*` output names in `environments/*/range/outputs.tf` to `engine_*` equivalents
- **Terraform**: Update all `data.terraform_remote_state.range.outputs.pulumi_*` references in `environments/*/portal/main.tf` to match renamed outputs
- **Terraform**: Rename Terraform resource identifiers (with `moved` blocks) in `modules/engine-state/` (`aws_s3_bucket.pulumi_state` → `engine_state`, `aws_kms_key.pulumi_secrets` → `engine_secrets`, `aws_dynamodb_table.pulumi_locks` → `engine_locks`, plus sub-resources)
- **Terraform**: Rename Terraform resource identifiers (with `moved` blocks) in `modules/engine-provisioner/` (`aws_ecs_cluster.pulumi` → `engine`, `aws_ecs_task_definition.pulumi_provisioner` → `engine_provisioner`, `aws_iam_role_policy.pulumi_state` → `engine_state`)
- **Terraform**: Update comments and descriptions referencing "Pulumi" to "engine" in `modules/engine-provisioner/iam.tf` and `variables.tf`

### Removed
- **Terraform**: Remove deprecated `pulumi-*` SSM parameters from `modules/portal/ssm/main.tf` (confirmed no application code references them; `engine-*` parameters already active)

## [3.33.0] - 2026-03-22

### Changed
- **Platform**: ECS modules (`engine/ecs.py`, `cms/experiments/ecs.py`) now propagate `CloudTaskError` instead of catching it and re-raising as `botocore.exceptions.ClientError`
- **Platform**: `engine/services.py` callers (`pause_range`, `resume_range`) catch `CloudTaskError` instead of `ClientError`
- **Platform**: Extract `_get_engine_ecs_config()` helper in `engine/ecs.py` to DRY up config reading from 3 internal functions

### Fixed
- **Terraform**: Portal `ecr_repository_url` uses `try()` fallback for foundation output rename (`engine_provisioner_ecr_url` || `pulumi_provisioner_ecr_url`) so portal plan succeeds regardless of foundation apply order

### Removed
- **Platform**: Remove `from botocore.exceptions import ClientError` from `engine/ecs.py` and `cms/experiments/ecs.py`

## [3.32.0] - 2026-03-22

### Changed
- **Platform**: Rename `PULUMI_ECS_CLUSTER_ARN`, `PULUMI_TASK_DEFINITION_ARN`, `PULUMI_ECS_SECURITY_GROUP_ID`, `PULUMI_PRIVATE_SUBNET_IDS` to `ENGINE_*` prefix across settings, application code, tests, Terraform SSM, deployment scripts, and CI/CD
- **Platform**: Rename `PULUMI_BACKEND_URL` to `STATE_BUCKET_URL` in task definition and local provisioner script
- **Platform**: Settings use fallback pattern (`ENGINE_*` || `PULUMI_*`) for zero-downtime transition
- **Terraform**: Rename module directories `modules/pulumi-provisioner/` to `modules/engine-provisioner/` and `modules/pulumi-state/` to `modules/engine-state/`
- **Terraform**: Rename module blocks `pulumi_provisioner` to `engine_provisioner`, `pulumi_state` to `engine_state`, `pulumi_provisioner_ecr` to `engine_provisioner_ecr` with `moved` blocks for state continuity
- **Terraform**: Rename variables `pulumi_provisioner_repository_name` to `engine_provisioner_repository_name`, `pulumi_container_tag` to `engine_container_tag`, and SSM module variables `pulumi_ecs_*`/`pulumi_task_*`/`pulumi_private_*` to `engine_*`
- **Terraform**: Rename outputs `pulumi_provisioner_ecr_*` to `engine_provisioner_ecr_*` and portal outputs `pulumi_ecs_*`/`pulumi_task_*`/`pulumi_private_*` to `engine_*`
- **Terraform**: Update all `module.pulumi_provisioner.*` and `module.pulumi_state.*` references to `module.engine_provisioner.*` and `module.engine_state.*` across environments
- **Terraform**: Update comments, descriptions, and tags from "Pulumi" to "Engine" in module internals (resource names unchanged for state compatibility)
- **Terraform**: Add new `engine-*` SSM parameters alongside deprecated `pulumi-*` parameters for transition

### Removed
- **Platform**: Remove `PULUMI_SECRETS_PROVIDER` env var (dead after Pulumi removal)
- **Platform**: Remove `PULUMI_BACKEND_URL`/`PULUMI_SECRETS_PROVIDER` from `_run_local_provisioner()` and `.env.example`
- **Platform**: Remove mock-pulumi PATH injection from local provisioner

## [3.31.0] - 2026-03-22

### Added
- **Provisioner**: `terraform_base.py` — shared Terraform runner helpers extracted from duplicate code in `terraform_runner.py` and `range_terraform_runner.py`
- **Provisioner**: `cloud/aws/base.py` — `BaseAWSAdapter` base class with shared `_get_client()` for all AWS adapters
- **Provisioner**: Shared executor exceptions (`ExecutorError`, `ExecutorCommandError`, `ExecutorTimeoutError`) in `executors/base.py`

### Changed
- **Provisioner**: `terraform_runner.py` and `range_terraform_runner.py` are now thin wrappers around `terraform_base.py`, eliminating ~550 lines of exact duplication
- **Provisioner**: All 5 AWS adapters (`secrets`, `db_auth`, `config_store`, `event_bus`, `storage`) inherit `BaseAWSAdapter` instead of duplicating `_get_client()`
- **Provisioner**: SSM, SSH, and NGFW executors use shared exception base classes from `executors/base.py` with backward-compatible aliases
- **Provisioner**: `main.py` SQL query construction uses `psycopg.sql` module for safe identifier composition instead of f-string formatting
- **Provisioner**: `linux_xdr_agent_install.py` bash scripts use `mktemp` for unpredictable temp file paths instead of hardcoded `/tmp` paths
- **Provisioner**: NGFW executor temp key file cleanup improved with `__del__` fallback; removed redundant `os.chmod` (mkstemp already creates with 0o600)

### Removed
- **Provisioner**: Remove `pulumi` and `pulumi_aws` from `requirements.txt` (already removed from `pyproject.toml`)

### Security
- **Provisioner**: Added `# NOSONAR` annotations for reviewed security hotspots (subprocess calls, Paramiko AutoAddPolicy, SSH StrictHostKeyChecking, test credentials)

## [3.30.0] - 2026-03-21

### Added
- **Provisioner Cloud**: `SecretsStore` protocol, `CloudSecretsError` exception, `AWSSecretsStore` adapter, and `get_secrets_store()` factory
- **Provisioner Cloud**: `object_exists()` and `delete_object()` methods on `ObjectStorage` protocol and `AWSObjectStorage` adapter

### Changed
- **Provisioner**: Migrate `events.py` from direct `boto3` SNS calls to `EventBus` cloud abstraction
- **Provisioner**: Migrate `config.py` RDS IAM auth from `boto3` to `DBAuth` cloud abstraction
- **Provisioner**: Migrate `main.py` S3/SSM/RDS/Secrets calls to `ObjectStorage`, `ConfigStore`, `DBAuth`, `SecretsStore` cloud abstractions
- **Provisioner**: Migrate `stacks/range_stack.py` Secrets Manager call to `SecretsStore` cloud abstraction
- **Provisioner**: Migrate `components/network.py` RDS IAM auth to `DBAuth` cloud abstraction
- **Provisioner**: Migrate `terraform_runner.py` S3 calls to `ObjectStorage` cloud abstraction
- **Provisioner**: Migrate `range_terraform_runner.py` S3 calls to `ObjectStorage` cloud abstraction

### Removed
- **Provisioner**: Remove `_get_sns_client()` from `events.py` (replaced by `EventBus` protocol)
- **Provisioner**: Remove direct `import boto3` from `events.py`, `config.py`, `main.py`, `stacks/range_stack.py`, `terraform_runner.py`, `range_terraform_runner.py`

## [3.29.1] - 2026-03-21

### Changed
- **Provisioner**: Remove misleading "stub" docstrings from AWS cloud adapters (`AWSObjectStorage`, `AWSConfigStore`, `AWSEventBus`, `AWSDBAuth`) — implementations are complete

## [3.29.0] - 2026-03-21

### Changed
- **Worker**: Migrate `run_worker` management command from direct `boto3` SQS calls to `shared.cloud.get_queue_consumer()` abstraction layer
- **CMS**: Migrate `cms/experiments/events.py` from direct `boto3` SQS calls to `shared.cloud.get_queue_publisher()` abstraction layer
- **Cloud**: Remove stub docstring from `AWSQueuePublisher`/`AWSQueueConsumer` now that extraction is complete

### Removed
- **Engine**: Delete deprecated `_get_ecs_client()` from `engine/ecs.py` (replaced by `shared.cloud.get_task_runner()`)
- **CMS**: Delete deprecated `_get_ecs_client()` from `cms/experiments/ecs.py` (replaced by `shared.cloud.get_task_runner()`)
- **Tests**: Delete `tests/engine/ecs/test_get_ecs_client.py` (tested removed function)

## [3.28.0] - 2026-03-21

### Changed
- **Engine**: Migrate `engine/secrets.get_ssh_key()` from direct `boto3` Secrets Manager calls to `shared.cloud` abstraction layer
- **CTF**: Migrate `ctf/bridges._get_instance_ssh_key()` from direct `boto3` Secrets Manager calls to `shared.cloud` abstraction layer
- **Cloud**: Remove stub docstring from `AWSSecretsStore` now that extraction is complete

## [3.27.3] - 2026-03-21

### Changed
- **Tests**: Consolidate test suite through parametrization and fixture extraction (39,712 → 39,050 lines, -662 net)
- **Tests**: Extract shared `mock_queryset` fixture and `INVALID_USERS`/`INVALID_RANGE_IDS` parametrize helpers to `tests/conftest.py`
- **Tests**: Extract in-memory model builders (`make_ctf_event`, `make_challenge`, `make_team`, `make_participant`, `make_scheduled_task`) to `tests/ctf/conftest.py`
- **Tests**: Create `tests/cms/conftest.py` with shared `credential_type_obj` fixture and `make_credential` builder
- **Tests**: Convert `_create_range_patches` helper to `create_range_ctx` pytest fixture in `cms/test_services_range.py`
- **Tests**: Parametrize user/range_id validation and error propagation tests across service classes in `cms/test_services_range.py`
- **Tests**: Consolidate model_dump/model_validate round-trip tests into parametrized classes in `shared/schemas/test_range.py` and `test_credentials.py`
- **Tests**: Parametrize required-field, default-value, computed-property, and status validation tests in `shared/schemas/test_range.py`
- **Tests**: Parametrize expiry property and positive-id validator tests in `shared/schemas/test_credentials.py`
- **Tests**: Parametrize boolean property, count, and status transition tests in `ctf/test_models.py`
- **Tests**: Parametrize credential property tests in `cms/test_models.py`
- **Tests**: Refactor `test_scoring.py` scoreboard setup methods to use shared `mock_queryset` fixture

### Added
- **Tests**: Add error handling, input validation, and missing config tests for `start_provisioning()` (2 → 7 tests)
- **Tests**: Add error handling, input validation, and missing config tests for `start_teardown()` (2 → 7 tests)
- **Tests**: Add error cases for `start_ngfw_provisioning()` (3 → 6 tests)
- **Tests**: Add error cases for `start_ngfw_teardown()` (4 → 7 tests)

### Removed
- **Tests**: Delete empty `mission_control/test_consumers.py` (0 tests, placeholder comment only)
- **Tests**: Remove redundant `InstanceContext` tests that duplicated `InstanceContextBase` coverage

## [3.27.2] - 2026-03-21

### Security
- **Platform**: Bump `django` 6.0 -> 6.0.3
- **Platform**: Bump `cryptography` 46.0.3 -> 46.0.5
- **Platform**: Bump `pyopenssl` 25.3.0 -> 26.0.0
- **Platform**: Bump `pyasn1` 0.6.1 -> 0.6.3
- **Platform**: Bump `ujson` 5.11.0 -> 5.12.0
- **Platform**: Bump `cbor2` 5.7.1 -> 5.8.0
- **Platform**: Bump `urllib3` 2.6.0 -> 2.6.3
- **Platform**: Bump `filelock` 3.20.0 -> 3.25.2
- **Platform**: Bump `virtualenv` 20.35.4 -> 21.2.0
- **Platform**: Add `[tool.uv] constraint-dependencies` to enforce minimum versions for transitive security deps

## [3.27.1] - 2026-03-21

### Security
- **Provisioner**: Bump `cryptography` 46.0.3 -> 46.0.5
- **Provisioner**: Bump `protobuf` 5.29.5 -> 5.29.6
- **Provisioner**: Bump `urllib3` minimum to >=2.6.3

## [3.27.0] - 2026-03-21

### Changed
- **Test suite: eliminate all DB access outside `tests/integration/`** — 63% faster (722s → 269s)
  - Converted 87 `@pytest.mark.django_db` markers and ~48 `TestCase` subclasses to mock-based tests
  - Only 22 markers remain, all in `tests/integration/` (legitimate integration tests)
  - View tests: replaced `Client`/`force_login` with `RequestFactory` + mock users
  - Model tests: in-memory construction via `Model()` or `__new__` + `__dict__`
  - Service tests: patched ORM managers (`objects.get`, `objects.filter`, `objects.create`, etc.)
  - Added missing engine migration (SubnetAllocation `reserved_at` → `created_at` rename)
  - Added missing CTF migration (index rename, field alter)
  - Changed all `OperatingSystem.objects.get(slug=...)` to `get_or_create()` for xdist resilience

## [3.26.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_models_subnet.py` (CMS) by mocking ORM
  - Added `_make_subnet()` helper to construct Subnet instances in-memory via `__dict__` assignment, bypassing Django FK descriptor validation
  - EntityBase `is_deleted` tests: built in-memory with `deleted_at` set/unset
  - Terminal status auto-`deleted_at` tests: patched `validate_data` and `django.db.models.Model.save` to exercise real `EntityBase.save()` logic without DB
  - Relationship tests: replaced cascade-delete DB test with `_meta` introspection asserting `CASCADE` on_delete and `related_name='subnets'`
  - Ordering test: asserted `Subnet._meta.ordering` instead of querying DB
  - Validation tests: called `subnet.validate_data()` directly on in-memory instances
  - Data/property tests: constructed in-memory instances and asserted properties
  - 4 class-level `@pytest.mark.django_db` markers removed, all 18 tests pass without DB access

## [3.25.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_models.py` (mission_control) by mocking ORM
  - Added `_make()` helper to construct Django model instances in-memory, bypassing FK validation and populating `_state.fields_cache`
  - OperatingSystem `get_for_extension` tests: patched `OperatingSystem.objects.all`
  - UserProfile tests: built via `_make()` with mock user in fields_cache
  - AgentConfig tests: built via `_make()` with mock user/os, `active_for_user` patched at `AgentConfig.objects.filter`
  - Range standup_duration tests: set `created_at`/`ready_at` directly on in-memory instances; annotation test mocks `Range.objects` chain
  - ActivityLog tests: `log()` patched at `ActivityLog.objects.create`, `__str__` tests use `_make()`
  - 4 class/method-level `@pytest.mark.django_db` markers removed, all 34 tests pass without DB access

## [3.24.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_auth.py` (CTF) by mocking ORM
  - Created `_MockGroupManager`/`_MockGroupQS` helpers to simulate `user.groups` with in-memory sets
  - OIDC backend tests: patched `config.oidc.Group.objects`, `config.oidc.get_user_profile`, `ctf.models.CTFEvent.objects`
  - Dashboard routing tests: call `dashboard_router` directly via `RequestFactory` with mock users
  - Access control decorator tests: patched `management.services.get_user_profile`, `ctf.models.CTFParticipant.objects`
  - Dev login tests: patched `config.dev_auth.User.objects`, `config.dev_auth.Group.objects`, `config.dev_auth.login`
  - Context processor tests: patched `management.services.get_user_profile` (bridges import locally)
  - Register view tests: patched `ctf.models.CTFParticipant.objects`, `django.contrib.auth.login`
  - Dual-role tests: patched `management.services.get_user_profile`, `django.contrib.auth.models.Group.objects`
  - 8 class-level `@pytest.mark.django_db` markers removed, all 48 tests pass without DB access

## [3.23.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_range_api.py` (mission_control) by mocking ORM
  - Replaced `Client`/`force_login` with `RequestFactory` + mock user via `AnonymousUser` for auth tests
  - View tests (get_range, launch_range, cancel_range, destroy_range, list_agents): patched CMS service functions (`get_active_range`, `cms_create_range`, `cms_get_agent`, `cms_list_agents`, `cms_list_scenarios`) at the view-module boundary
  - Subnet allocation tests: mocked `transaction.atomic` and `Range.objects` queryset chain
  - Shared fixtures (`mock_user`, `mock_agent`, `mock_linux_agent`, `other_user`) replace DB-backed `test_agent`/`windows_os`/`linux_os` fixtures
  - 6 class-level `@pytest.mark.django_db` markers removed, all 37 tests pass without DB access

## [3.22.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_scoring.py` (CTF) by mocking ORM
  - `TestCalculateScore`: mocked `CTFSubmission.objects.filter().aggregate()` chain
  - `TestGetScoreboard` / `TestGetTeamScoreboard`: mocked annotated queryset chains with mock participant/team objects
  - `TestGetParticipantRank`: mocked both `.get()` lookup and scoreboard queryset
  - `TestGetChallengeStatistics`: mocked `CTFChallenge.objects.get()` and submission queryset chains
  - `TestGetEventStatistics`: mocked `CTFEvent.objects.get()` and all related model managers
  - `TestCalculatePointsWithPenalty`: replaced real model instances with mocks binding the real method
  - 7 class-level `@pytest.mark.django_db` markers removed, all 27 tests pass without DB access

## [3.21.0] - 2026-03-21

### Changed
- Remove all `@pytest.mark.django_db` markers from `test_views.py` (mission_control) by mocking ORM
  - View tests (dashboard, settings, help): replaced `Client`/`force_login` with `RequestFactory` + mock user, patched `render` to avoid DB-hitting context processors
  - `TestGetUserStorageUsed`: mocked `AgentConfig.active_for_user` queryset instead of creating real DB records
  - `TestUploadLock`: replaced Django session with plain dict (no DB session backend needed)
  - 5 class-level `@pytest.mark.django_db` markers removed, all 14 tests pass without DB access

## [3.20.0] - 2026-03-20

### Changed
- Remove `@pytest.mark.django_db` from three CMS test files by mocking all ORM access
  - `test_services_scenarios.py`: replaced real User/AgentConfig fixtures with mocks, patched registry functions (list_all_scenarios, get_scenario_detail, load_scenario_template)
  - `test_scenario_hydrator.py`: replaced real User/AgentConfig fixtures with mocks, patched hydrator's load_scenario with canned ScenarioTemplate Pydantic objects
  - `test_services_range.py`: converted remaining 4 `create_range` test classes (Validation, EngineCall, Instance, Return) from DB to fully mocked ORM using ExitStack-based helper

## [3.19.0] - 2026-03-20

### Changed
- Test suite optimization: remove unnecessary `@pytest.mark.django_db` markers and add `--reuse-db`
  - Added `--reuse-db` to pytest addopts in pyproject.toml for faster repeated runs
  - `test_create_range.py`: removed `django_db`, added `_mock_transaction` autouse fixture
  - `test_cancel_range.py`: removed `django_db` from both classes, added `_mock_range_lookup` fixture
  - `test_services_storage.py`: converted real `User` fixture to `mock_user`, removed `django_db`
  - `test_handlers.py` (CMS): removed `django_db` from `TestProcessEvent` and `TestParseSnsMessage`
  - `test_handlers.py` (Engine): removed `django_db` from `TestProcessEvent` and `TestParseSnsMessage`
  - `test_models_agent_config.py`: removed `django_db` from `TestAgentConfigModel` (metadata-only tests)
  - `test_models_operating_system.py`: removed `django_db` from `TestOperatingSystemModel` (metadata-only tests)
  - 10 class-level markers removed across 7 test files

## [3.18.0] - 2026-03-20

### Changed
- Test suite cleanup: remove duplicate wrapper tests and unnecessary `@pytest.mark.django_db` markers
  - Removed ~51 duplicate tests from ECS wrapper test files (delegation verified in 2-4 tests each)
  - Deleted `tests/mission_control/test_engine.py` (12 tests duplicating `tests/engine/ecs/`)
  - Removed `@pytest.mark.django_db` from 8 test files that only use mocks (no ORM calls)
- CMS service test streamlining: replace real DB fixtures with mocks in mock-heavy tests
  - `test_services_range.py`: removed `django_db` from 8/12 classes (~75 tests), kept 4 `create_range` classes on DB
  - `test_services_upload.py`: removed `django_db` from all 3 classes (57 tests), removed unused DB fixtures
  - `test_services_agents.py`: removed `django_db` from all 4 classes (34 tests), removed unused DB fixtures
  - Added `mock_user` fixture with `Mock(pk=42, id=42)` to replace real `User.objects.create_user` in pure-mock tests
- Task runner abstraction delegation (PLAT-001.3, #813)
  - `engine/ecs.py`: All ECS task functions now delegate to `TaskRunner` protocol via `get_task_runner()`
  - `cms/experiments/ecs.py`: `start_experiment_task()` delegates to `TaskRunner` protocol via `get_task_runner()`
  - Added `container_name` parameter to `TaskRunner.run_task()` protocol and `AWSTaskRunner` adapter
  - `AWSTaskRunner.run_task()` now raises `CloudTaskError` when no tasks are started (was returning None)
  - `AWSTaskRunner.get_task_status()` now returns all fields callers expect (`desired_status`, `started_at`, `stopped_at`)
  - Exception bridging: `CloudTaskError` caught and re-raised as `ClientError` for backward compatibility
  - All existing function signatures, import paths, and caller contracts preserved
  - `_get_ecs_client()` kept deprecated in both modules; `import boto3` moved inside it

## [3.17.0] - 2026-03-19

### Changed
- Object storage abstraction delegation (PLAT-001.2, #812)
  - `cms/assets/s3.py`: All S3 functions now delegate to `ObjectStorage` protocol via `get_object_storage()`
  - `cms/experiments/s3.py`: All S3 functions now delegate to `ObjectStorage` protocol via `get_object_storage()`
  - `provisioner/config.py`: `generate_presigned_url()` delegates to provisioner `ObjectStorage` adapter
  - Exception bridging: `CloudStorageError` caught and re-raised as `S3Error` for backward compatibility
  - All existing function signatures, import paths, and caller contracts preserved

## [3.18.0] - 2026-03-20

### Added
- Programmable flag validation (CTF-118) — flags can use registered Python validator functions or HTTP callbacks for custom pass/fail logic
- New flag types: `programmable` (server-side validator registry) and `http` (external endpoint validation)
- Validator registry module (`ctf/validators.py`) with `register_validator` / `get_validator` API
- Built-in example validators: `always_true`, `contains_substring`
- `validator_config` JSONField on `CTFFlag` model for per-flag configuration

### Changed
- `CTFFlag.flag_type` max_length increased from 10 to 20 to accommodate new type names

## [3.17.0] - 2026-03-20

### Added
- CTF awards system (CTF-206) — organizers can grant point bonuses or deductions to participants via `CTFAward` model
- Award service (`grant_award`, `revoke_award`, `get_participant_awards`, `get_event_awards`)
- Score calculation now includes awards: `calculate_score`, `get_scoreboard`, `get_team_scoreboard`, model `total_score` properties, and admin annotations all reflect submission points + award points
- `get_event_statistics` includes `total_awards` count
- Award admin interface with inline views on participant and event admin pages

## [3.16.1] - 2026-03-20

### Changed
- Consolidated all in-app test directories (`ctf/tests/`, `cms/experiments/tests/`, `risk_register/tests/`) into centralized `tests/` directory so all 2331 tests are discovered by the default `pytest` command
- Removed `--cov` from pytest `addopts` — local runs are now fast; coverage runs only in CI
- CI workflow now includes `--cov` for `ctf`, `engine`, and `risk_register` modules and no longer ignores `tests/risk_register`

## [3.16.0] - 2026-03-19

### Added
- Cloud provider abstraction layer foundation (PLAT-001.1, #811)
  - Protocol definitions for ObjectStorage, TaskRunner, QueueConsumer, QueuePublisher, SecretsStore (platform)
  - Protocol definitions for EventBus, ConfigStore, DBAuth, ObjectStorage (provisioner)
  - Factory functions with `CLOUD_PROVIDER` setting (defaults to "aws")
  - AWS adapter implementations for all protocols
  - Provider-agnostic exception hierarchy
  - Generic setting aliases (`CLOUD_PROVIDER`, `CLOUD_REGION`, `STORAGE_BUCKET_NAME`) with backward-compatible AWS fallbacks
- Multiple flags per challenge (CTF-107) — new `CTFFlag` model supports multiple valid flags per challenge where any correct flag constitutes a solve
- Each flag independently supports static (hashed) or regex (pattern match) types and case sensitivity
- `add_flag` / `remove_flag` service functions and API endpoints for flag management
- Flag management UI on admin challenge detail page (add/remove flags with type and case sensitivity controls)
- Backward compatible — challenges with only the legacy `flag_hash` field continue to work without migration

## [3.15.4] - 2026-03-18

### Fixed
- Deploy pipeline circular dependency — Engine Deploy now skips gracefully when ECS task definition doesn't exist yet (first deploy), allowing Platform terraform to create it
- Platform workflow no longer blocked by Engine Deploy failure — tolerates non-success results so first deploy can complete
- Guacamole ECS stability check: replaced `aws ecs wait services-stable` (hard 10min timeout) with polling loop (20min); auto-detects FAILED deployments from prior runs and forces redeployment before waiting
- Migration `cms/0015_ngfw_model.py` made idempotent — checks if `ngfw_spec` column exists before adding it, preventing "column already exists" error on fresh databases; uses `PRAGMA table_info` for SQLite (tests) and `information_schema` for PostgreSQL (prod)
- Docker Compose build context corrected — set to parent directory so Dockerfile can access sibling directories (`cyberscript/`, `shifter_platform/`)

### Added
- `SKIP_MIGRATIONS` environment variable support in `entrypoint.sh` for local development

## [3.15.3] - 2026-03-16

### Added
- CTF walkthrough page with 7-step copy-pasteable prompts for Box 0 (WebShell) guided workshop — accessible to participants at `/ctf/walkthrough/`

## [3.15.2] - 2026-03-15

### Fixed
- Range destroy no longer fails with empty CIDR — allocated subnet CIDRs are now persisted to range_config during provisioning, and destroy falls back to the allocation table for ranges provisioned before this fix

## [3.15.1] - 2026-03-15

### Added
- CTF scheduler process (`run_ctf_scheduler`) added to deployment workflow and docker-compose — scheduled tasks (range provisioning, event start/end, cleanup) now execute automatically

### Removed
- `describe_stacks` tool from the ops MCP server — CloudFormation is not used in this project (Pulumi is used instead), so the tool was dead code

## [3.15.0] - 2026-03-15

### Fixed
- CTF magic link now takes participants directly to Mission Control instead of showing a login page
- Removed dead CTF login page — magic link is the only auth path for CTF participants
- Logout now works for all auth types — unified `/logout/` view routes OIDC users through Cognito logout, magic-link/dev users through Django session logout
- Dashboard session-expiry redirect no longer hardcodes `/oidc/authenticate/` — uses `/dashboard/` (the router) so all user types land correctly

### Changed
- CTF participants now only see the Kali (attacker) box in the terminal UI — victim, DC, and NGFW tabs are filtered out in the `active_range()` context processor

## [3.14.0] - 2026-03-15

### Added
- Instance names from scenario YAML templates are now set as EC2 hostnames during provisioning — instances get meaningful names (e.g., `webdev01`, `kali`, `mx-internal`) instead of AWS defaults like `ip-10-1-2-109.us-east-2.compute.internal`
- `name` field passed through Terraform variables, locals, user_data templates, and outputs for all instance types (Kali, Linux victim, Windows victim, DC)
- Hostname setting in `victim_linux.sh.tpl`, `victim_windows.ps1.tpl`, and `dc_windows.ps1.tpl` user_data templates
- EC2 Name tags now use the scenario template name when available

## [3.13.2] - 2026-03-14

### Fixed
- Subnet allocation race condition — `allocate_subnets()` call in `range_stack.py` now passes `range_id` and `request_id`, so CIDR reservations are actually written to `engine_subnetallocation` (GH #786)
- Windows SSH failure during CTF bootstrap — CTF AMIs now build on top of Shifter base AMIs (`shifter-windows`, `shifter-ubuntu`) which have OpenSSH pre-installed, instead of raw Amazon/Canonical images that required runtime installation (GH #786)

### Changed
- CTF Packer templates (`ctf-helpdesk`, `ctf-vault`, `ctf-webshell`, `ctf-mailroom`, `ctf-devbox`) rebase on Shifter base AMIs instead of raw vendor images; `base.ps1`/`base.sh` provisioner steps removed
- CTF setup scripts deduplicated — removed IIS install, WinRM config, SSH config, and firewall rules already baked into base AMIs
- Reverted `configure_ssh` bootstrap DISM fallback — OpenSSH is now guaranteed by base AMI; missing SSH should fail loudly

## [3.13.1] - 2026-03-14

### Fixed
- CTF range destroy API returns 500 due to missing `range_id` — `process_range_event()` now persists `range_id` from SNS event to `RangeInstance` (#756)

## [3.13.0] - 2026-03-14

### Fixed
- Normal Shifter users who are also CTF participants no longer lose access to platform features like Assets, Docs, Settings/Help, and Launch Range (GH #758) — UI restrictions now use `is_ctf_participant_only` which only hides features for pure CTF participants with no other platform role

### Added
- `is_ctf_participant_only()` utility in `shared/auth.py` — returns True only when a user is a CTF participant with no staff, superuser, organizer, or threat research role
- `is_ctf_participant_only` template context variable exposed via CTF context processor

## [3.12.0] - 2026-03-14

### Fixed
- Experiment creation now enforces `staff_only` and `disabled` scenario restrictions (GH #770) — previously the experiment UI and service layer loaded scenarios directly via `cms.scenarios.loader`, bypassing `ScenarioMetadata` access controls

### Changed
- Experiment create form uses `list_all_scenarios(user)` from the scenario registry instead of raw YAML loader, so non-staff users only see scenarios they're allowed to use
- `create_experiment()` service checks scenario access via `check_scenario_access()` before creating the experiment
- `get_scenario_instances()` AJAX endpoint passes the requesting user for access checking
- Experiment services use `load_scenario_template()` from the registry (checks DB first, then YAML) instead of `load_scenario()` from the raw loader

## [3.11.0] - 2026-03-14

### Changed
- CTF organizer admin views now use Mission Control layout (`mission_control/base.html`) instead of separate CTF portal — organizers see the full MC sidebar with ranges, terminal, assets, etc.
- Added "CTF Admin" nav item to Mission Control sidebar for organizers (between Risk Register and Scenario Editor)
- Dashboard router sends CTF organizers to Mission Control dashboard instead of CTF admin dashboard — fixes dual-role users losing access to MC launch panel (GH #758)
- Removed separate CTF organizer sidebar (`ctf_organizer_sidebar.html`) — organizers use the standard MC sidebar

## [3.10.0] - 2026-03-14

## Changed
- Update Claude Code model versions (Sonnet 4.5, Haiku 4.5)

## [3.9.0] - 2026-03-13

### Changed
- CTF participants now land on Mission Control dashboard instead of separate CTF UI — reuses existing range, terminal, and Guacamole views
- Magic link registration (`/ctf/register/`) redirects to Mission Control dashboard
- Dashboard router sends CTF participants to Mission Control
- Dev login redirects CTF participants to Mission Control
- MC sidebar hides Assets, Docs, Settings, and Help nav items for CTF participants (shows only Ranges and Terminal)
- MC dashboard hides Launch Range form for CTF participants (their ranges are pre-provisioned by organizers)
- Dashboard JS skips launch UI initialization in view-only mode for CTF participants

## [3.8.0] - 2026-03-13

### Changed
- CTF participants are auto-registered (Django user created, status set to `registered`) when added individually or via CSV import — eliminates the separate "registration" step
- Magic link emails can be sent to any participant at any time, regardless of status — removed registered-participant guard from `resend_invite()`
- "Send All Links" button now sends to all participants, not just uninvited ones
- Per-participant "Send Link" button always visible in participant list (was hidden after registration)
- Invitation email wording updated: "Click below to access your event" / "Access Event" (was "To register" / "Register Now")

## [3.7.1] - 2026-03-13

### Added
- `list_ranges` MCP tool — list ranges with status, user, scenario, instance count, and timestamps; supports filtering by status and username
- `get_range` MCP tool — get detailed range info including instances and subnet allocations
- `list_subnet_allocations` MCP tool — list subnet CIDR allocations with optional status/VPC filtering

## [3.7.0] - 2026-03-13

### Added
- `SubnetAllocation` model and migration (`engine_subnetallocation` table) to reserve CIDRs during concurrent provisioning, preventing TOCTOU race condition where multiple ranges pick the same subnet CIDR
- Subnet allocation table is checked alongside AWS `describe_subnets` during CIDR selection; stale reservations (>30min) are automatically reclaimed
- `confirm_subnet_allocations()` / `release_subnet_allocations()` lifecycle hooks called on provision success, destroy, and failure (Terraform path)
- `SubnetAllocationAdmin` registered in Django admin for ops visibility
- 7 new tests for allocation table integration (reserve, skip-reserved, stale-reclaim, released-reuse, confirm, release, DB-fallback)

## [3.6.0] - 2026-03-13

### Fixed
- CI deploy workflow (`_shifter-platform.yml`) now passes `EMAIL_BACKEND` and `CTF_FROM_EMAIL` env vars to containers (emails were silently going to console backend)
- EC2 IAM role missing `ses:GetSendQuota` permission required by `django-ses` backend (applied via Terraform)
- `get_scoreboard` and `get_team_scoreboard` annotation `total_score` collided with model `@property` of the same name, causing 500 on participant dashboard, admin scoreboard, and scoreboard API (renamed annotation to `computed_score`)
- Invite token expiry now uses event end time directly instead of `min(7 days, event_end)`, ensuring tokens remain valid through the entire event

### Changed
- `agentic_workshop` scenario template simplified from two-subnet to single flat subnet topology (multi-subnet isolation doesn't work without NGFW; attack path enforced by challenge design instead)

### Added
- CTF range management JavaScript (`static/js/ctf-ranges.js`) with `CTFRangeManager` class wiring Provision All, per-participant Provision, and per-participant Destroy buttons to API endpoints
- Per-participant range API endpoints: `POST /ctf/api/participants/<id>/range/provision/` and `POST /ctf/api/participants/<id>/range/destroy/`
- 20 Jest tests for `CTFRangeManager` covering all button interactions, error handling, and loading states

## [3.5.0] - 2026-03-13

### Added
- `ami_key` optional field on `InstanceConfig`, `InstanceSpec`, and `InstanceContextBase` for custom AMI support
- Provisioner resolves `ami_key` to AMI ID via SSM `/shifter/ami/<ami_key>` and passes per-instance `ami_id` to Terraform
- `get_ami_id()` now accepts arbitrary SSM parameter suffixes (custom ami_key values), not just the 4 known types
- Terraform `ami_id` per-instance override: when non-empty, bypasses the `os_type` AMI lookup
- `agentic_workshop` scenario template: 6-box single-subnet CTF range with custom AMIs for vibe hacking workshop

## [3.4.1] - 2026-03-13

### Fixed
- `resend_invite` now actually sends the invitation email (previously only refreshed the token without emailing)
- `user_data.sh` includes `localhost,127.0.0.1` in `DJANGO_ALLOWED_HOSTS` for SSM tunnel access
- `user_data.sh` stops `ctf-scheduler` container during redeployment (was missing from stop list)

## [3.4.0] - 2026-03-13

### Changed
- CTF RBAC migrated from `UserProfile.user_type` CharField to Django Groups (`CTF Organizer`, `CTF Participant`), enabling users to hold both roles simultaneously
- `get_user_role()` now checks Django group membership instead of `UserProfile.user_type`
- `_set_ctf_participant_profile` / `_clear_ctf_participant_profile` use additive/subtractive group operations instead of overwriting `user_type`
- OIDC callback and dev login add/remove Django groups instead of setting `user_type` field
- Dashboard router uses `shared.auth` helpers instead of `UserProfile` properties
- `UserProfile.is_ctf_organizer` / `is_ctf_participant` properties now delegate to group membership (deprecated, use `shared.auth` helpers)

### Added
- Data migration `0004_ctf_groups` creates `CTF Organizer` and `CTF Participant` groups and migrates existing users
- `shared.auth`: `CTF_ORGANIZER_GROUP`, `CTF_PARTICIPANT_GROUP` constants and `is_ctf_organizer()`, `is_ctf_participant()` helpers
- Dual-role test coverage (organizer who is also a participant)

## [3.3.0] - 2026-03-12

### Added
- Vibe Hacking Workshop CTF range: 5-box range with network topology for 90-minute workshop
- Packer templates for all CTF boxes: ctf-webshell, ctf-mailroom, ctf-helpdesk, ctf-devbox, ctf-vault
- Box 0 "WebShell" (Ubuntu walkthrough): Apache/PHP webshell -> sudo -> SUID privesc
- Box 1 "MailRoom" (Ubuntu): anonymous FTP -> credential pattern -> SSH -> PATH hijack privesc
- Box 2 "HelpDesk" (Windows): SMB cred leak -> RDP -> scheduled task abuse
- Box 3 "DevBox" (Ubuntu, dual-homed): command injection -> SSH key hunting -> GTFOBins sudo node
- Box 4 "Vault" (Windows, internal only): pivot target with WinRM, Backup Operators privesc, KeePass alt path
- Validation test scripts for each CTF box (setup verification)
- CTF scheduled task executor management command (`run_ctf_scheduler`) — polls for due `CTFScheduledTask` rows and dispatches SPIN_UP_RANGES, EVENT_START, EVENT_END, CLEANUP_RANGES, and SEND_REMINDER tasks with signal handling and heartbeat monitoring
- Throttled bulk range provisioning (`provision_event_ranges_throttled`) — spreads AWS resource creation across the spinup window with configurable delay clamped to [5, 120]s and graceful shutdown support
- Full Guacamole connection parameters (RDP credentials, SFTP config, SSH keys) for CTF range access via new `get_range_connection_info` bridge
- "Send All Invites" button on the CTF organizer participant list page with API endpoint
- Registration URL in CTF invitation emails (replaces raw invite token display)
- Event-driven range status sync from CMS to CTF via Django signal (`range_status_changed`) — updates `CTFParticipant.range_status` when CMS processes SNS range events
- Scenarios API endpoint (`/ctf/api/scenarios/`) for listing available CMS scenarios as JSON
- Datetime string parsing in event API POST/PUT handlers so JSON-submitted datetime strings are converted before reaching the service layer
- `range_spinup_minutes` field in event detail API GET response

### Changed
- CTF event create/edit form rewritten to use Mission Control AJAX pattern with XDR dark theme instead of Django form posts with Bootstrap
- CTF admin views and templates: replaced Bootstrap classes with XDR theme styling for visual consistency with Mission Control

### Fixed
- CTF participant registration now sets `UserProfile.user_type` and `active_ctf_event` directly, removing dependency on pre-configured Cognito custom claims for `ctf_participant_required` decorator
- CTF participant disqualification and deletion now clear `UserProfile` CTF fields
- `get_range_access_url` now passes RDP username/password, SFTP root directory, and SSH key to Guacamole instead of only hostname

### Removed
- Dead `_extract_ip_from_range_spec` helper in `ctf/services/range.py` (replaced by `get_range_connection_info` bridge)
- Django form-based event creation/edit views (replaced by AJAX pattern)

## [3.2.0] - 2026-03-12

### Added
- CTF scheduled task executor management command (`run_ctf_scheduler`) — polls for due `CTFScheduledTask` rows and dispatches SPIN_UP_RANGES, EVENT_START, EVENT_END, CLEANUP_RANGES, and SEND_REMINDER tasks with signal handling and heartbeat monitoring
- Throttled bulk range provisioning (`provision_event_ranges_throttled`) — spreads AWS resource creation across the spinup window with configurable delay clamped to [5, 120]s and graceful shutdown support
- Full Guacamole connection parameters (RDP credentials, SFTP config, SSH keys) for CTF range access via new `get_range_connection_info` bridge
- "Send All Invites" button on the CTF organizer participant list page with API endpoint
- Registration URL in CTF invitation emails (replaces raw invite token display)
- Event-driven range status sync from CMS to CTF via Django signal (`range_status_changed`) — updates `CTFParticipant.range_status` when CMS processes SNS range events

### Fixed
- CTF participant registration now sets `UserProfile.user_type` and `active_ctf_event` directly, removing dependency on pre-configured Cognito custom claims for `ctf_participant_required` decorator
- CTF participant disqualification and deletion now clear `UserProfile` CTF fields
- `get_range_access_url` now passes RDP username/password, SFTP root directory, and SSH key to Guacamole instead of only hostname

### Removed
- Dead `_extract_ip_from_range_spec` helper in `ctf/services/range.py` (replaced by `get_range_connection_info` bridge)

## [3.1.2] - 2026-03-12

### Fixed
- CTF event form: replace plain text `scenario_id` input with a dropdown populated from the CMS scenario registry
- CTF event form: add `is-invalid` CSS class to fields with errors for Bootstrap 5 error visibility
- CTF event form: validate submitted `scenario_id` exists in the scenario registry

## [3.1.1] - 2026-03-12

### Fixed
- Flag hashing bug: challenges created via admin form used bare SHA256, producing hashes that `verify_flag()` could never match; now uses `hash_flag()` from services
- Potential division by zero in scoring solve rate calculation
- Removed unreachable `return` statements in `api_participant_list` and `api_participant_detail`

### Security
- Add missing authorization decorators to 8 CTF API views: `api_challenge_list`, `api_challenge_detail`, `api_submit_flag`, `api_use_hint`, `api_submissions`, `api_range_status`, `api_range_access`, `api_scoreboard`
- Remove `invite_token` from API responses in `api_participant_list` and `api_participant_resend_invite`
- Replace SHA256 fallback with PBKDF2-SHA256 (600k iterations) for flag hashing when bcrypt is unavailable
- Add `# NOSONAR` annotations to hardcoded test/dev encryption keys in settings
- Add SNS topic KMS encryption in dev and prod Terraform environments
- Set `recovery_window_in_days = 7` for Secrets Manager in production (was 0)
- Pin Secrets Manager IAM policy ARNs to specific AWS account ID
- Add `#tfsec:ignore` justifications to required IAM wildcards and egress rules
- Add `# NOSONAR` annotation to dev auth bypass with justification

## [3.1.0] - 2026-03-12

### Added
- CTF admin team list, scoreboard, and analytics pages
- CTF help page with getting started content
- CTF API endpoints: event list/detail, challenge list/detail
- NGFW toggle in CTF event form (range_config)

### Changed
- CTF app uses bridge module (`ctf/bridges.py`) for all cross-domain integrations (CMS, management, mission_control)
- CTF scheduled tasks documented as database-only; no Celery dependency
- Email backend defaults to console for dev; configure via `EMAIL_BACKEND` env var for production
- Wire `EMAIL_BACKEND` and `CTF_FROM_EMAIL` through deployment pipeline (SSM → user_data.sh → Docker env → Django settings)

### Fixed
- Removed stale scheduler module reference from services docstring

### Removed
- Dead `mock_scheduler` fixture that patched non-existent `ctf.services.scheduler`

## [3.0.0] - 2026-03-11

### Added
- CTF (Capture The Flag) management platform — core app files: models, enums, services, admin, forms, migrations
- CTF config and routing integration: settings, URL routing, dashboard router, dev login user types, OIDC user type claims
- CTF views, URL routing, and templates: organizer admin views, participant views, API endpoints, 38 template files, email templates, sidebar partials
- UserProfile CTF fields: user_type, active_ctf_event, role properties (is_ctf_organizer, is_ctf_participant, is_standard_user)
- CTF test suite: 13 test files, 230 tests across models, auth, challenges, events, participant views, services (notification, range)
- CTF participant registration endpoint (`/ctf/register/`) to complete invite-link registration flow

### Fixed
- CTF invite emails never sent: `invite_participant()` and `bulk_import_participants()` prematurely set `invited_at`, causing `send_invitations()` to skip all participants
- CTF range provisioning: all ranges were created under the organizer's user, causing the second participant's range to fail the active-range check; now uses `participant.user`

### Security
- Add organizer ownership checks to 11 CTF views missing authorization: range list/provision APIs, notification list/create/send views and APIs, team list, scoreboard, analytics, and event detail API — non-owning organizers now get 403

## [2.3.3] - 2026-03-10

### Added
- SE Admin IAM Users Terraform module (`platform/terraform/global/se-admins/`) for managing PANW SE admin access to the dev AWS account

## [2.3.2] - 2026-02-24

### Fixed
- Logout button not working (GET request to POST-only `OIDCLogoutView`)

## [2.3.1] - 2026-02-24

### Added
- CyberScript DSL language reference documentation (`documentation/docs/cyberscript/`)
- Schema validators: unique instance names, `dc_config` required when `domain_controller: true`

### Fixed
- Threat Research RBAC sidebar visibility and auth redirect

## [2.3.0] - 2026-02-24

### Added
- Unified platform audit logging system
- Audit coverage for range pause/resume, experiments, scenario editor
- AuditLog entity types: experiment, scenario, script
- AuditLog actions: pause, resume, cancel
- Audit service tests (16 tests)

### Fixed
- audit_log() now swallows exceptions instead of re-raising (never breaks the application)
- Stale self.range_id references in SSH consumer after refactor
- Migrated agent events from deprecated ActivityLog to AuditLog

## [2.2.10] - 2026-02-23

### Added
- Threat Research RBAC group
- Threat Research access to Experiment Manager and Scenario Editor

## [2.2.9] - 2026-02-22

### Fixed
- Experiment runner integration fixes

## [2.2.8] - 2026-02-22

### Changed
- Finish experiment runner integration

## [2.2.7] - 2026-02-21

### Added
- Scenario Editor UAT plans

### Fixed
- Role enum validation for ScenarioTemplate

## [2.2.6] - 2026-02-21

### Changed
- Range pause/unpause uses Ready instead of Active status

## [2.2.5] - 2026-02-21

### Added
- MCP tools for SSM tunnel testing: start_portal_test_tunnel, stop_portal_test_tunnel
- localhost to ALLOWED_HOSTS in dev for tunnel access

## [2.2.4] - 2026-02-21

### Changed
- Enable dev_login in deployed dev environment for programmatic testing via SSM tunnel

## [2.2.3] - 2026-02-21

### Fixed
- Broken migration chain causes Django crash loop

## [2.2.2] - 2026-02-17

### Fixed
- Deploy script SSM waiter timeout - increased max attempts from 20 to 60 (15 minutes)

## [2.2.1] - 2026-02-16

### Changed
- Centralized script variable sanitization in Pydantic contexts for consistent and secure variable handling.
- Moved experiment template variable logic to shared `cyberscript` library to enable cross-layer reuse and validation.
- Hardened `ExperimentOrchestrator` with comprehensive exception handling and debug logging to ensure unexpected failures mark runs as FAILED rather than hanging.
- Standardized `ExperimentManager` services and views to match CMS defensive coding patterns, including uniform user validation and ORM result type checking.
- Refactored experiment creation flow to enforce model-level validation within atomic transactions.

## [2.2.0] - 2026-02-16

### Add
- Direct NGFW access for users

## [2.1.7] - 2026-02-16

### Added
- Cortex Broken Bank AMI

## [2.1.6] - 2026-02-16

### Added
- Add XDR Collector and Cloud Identity Engine agents to CMS
-
## [2.1.5] - 2026-02-15

### Changed
- Merged MCP-Shifter and MCP-NGFW into MCP-Ops
- MCP-Ops has range reconciliation tool to find and destroy orphaned instances
- Add better parsing for AWS to SonarQube

## [2.1.4] - 2026-02-15

### Fixed
- Shifter DB MCP no longer leaks connections to RDS

## [2.1.3] - 2026-02-15

### Fixed
- Failed ranges do not always get destroyed

## [2.1.2] - 2026-02-14

### Fixed
- Restrictive Egress rules in Network Firewall loosened to match XSIAM docs recommendations

## [2.1.1] - 2026-02-10

### Fixed
- Subnet `connected_to` semantics corrected: Terraform now creates security group rules on target subnet allowing traffic from source (was reversed)
- Range provisioning now reads NGFW data ENI ID from database instead of non-existent environment variable

### Changed
- Updated `connected_to` documentation to clarify unidirectional semantics (both subnets must list each other for bidirectional traffic)
- Updated basic_ngfw scenario template to have bidirectional subnet connectivity

## [2.1.0] - 2026-02-08

### Added
- Experiment Manager for creating and managing experiments

## [2.0.0] - 2026-02-07

### Added
- Scenario Editor for creating and editing CyberScript

## [1.1.3] - 2026-02-07

### Added
- Certipy to Kali AMI

## [1.1.2] - 2026-02-07

### Added
- Credentials details page

## [1.1.1] - 2026-02-07

### Changed
- Increased number of possible user subnets by decreasing subnet size

## [1.1.0] - 2026-02-06

### Changed
- Range pause/resume flow and UI updates

### Fixed
- Guacamole ECS service not deploying correctly

## [1.0.9] - 2026-02-02

### Fixed
- Claude errors due to using wrong small model
- Handle NGFW "starting" state correctly

## [1.0.8] - 2026-02-02

### Fixed
- Fix logic error handling non-NGFW scenarios

## [1.0.7] - 2026-02-01

### Fixed
- Refine Internet egress domains and CIDR to Palo Alto Networks published IPs instead of overbroad GCP IPs

## [1.0.6] - 2026-01-28

### Added
- MCP servers for Shifter DB, NGFW, and AWS ops
### Fixed
- NGFW destroy flow does not remove EC2 instances
- NGFW commands not piped to SSH as required
- Provisioner missing permission for deleting NGFW resources

## [1.0.5] - 2026-01-28

### Changed
- Updated SSH connection validation to handle difference between SSH being up and management plane being fully up

## [1.0.4] - 2026-01-28

### Fixed
- Hydrator no longer rejects empty folder fields for SCM creds

## [1.0.3] - 2026-01-27

### Fixed
- Some range boxes have unexpected Internet access


## [1.0.2] - 2026-01-25

### Added
- Range pause/resume flow and UI updates

## [1.0.1] - 2026-01-25

### Changed
- Migrated range and NGFW provisioning to Terraform

## [1.0.0] - 2026-01-21

### Added
- Cortex BYOT scenario (automation except for CIE and XDR collector)
- Cortex Deployment Experience scenario

### Changed
- Dashboard renamed to Ranges
- Ranges view uses multiple tiles for launch and active ranges
- NGFW flow handles prompting user to associate NGFW to SCM and XDR
- Removed legacy Terraform-based range provisioning
- Ubuntu box supports RDP/desktop access
- Users can set MFA to remember devices

### Fixed
- Django build does not include cyberscript shared library
- Extend and streamline NGFW stand up plan
- Dynamic subnet creation for ranges misses Shifter Platform creation
- Missing VPC route for kali
- VPC Internet egress not enforcing drop rule
- Kali RDP not working due to permissions on logs
- XDR not deployed on BYOT scenario DC
- Race condition in DC readiness and target attempt to join domain

## [0.10.7] - 2026-01-12

### Changed
- Extract all Cyberscript related code to shared library for reuse in Provisioner and Engine
-
## [0.10.6] - 2026-01-13

### Fixed
- Type conflict causes NGFW provisioning to fail
- CMS parses legacy and new range_spec formats for consumers

## [0.10.5] - 2026-01-12

### Fixed
- Provisioner ID mismatch causes range create status update to fail
- Range subnets have no route to s3 for agent downloads

## [1.0.4] - 2026-01-12

### Changed
- Extracted ssh key generation to shared library

## [1.0.3] - 2026-01-12

### Added
- Additional local dev support

### Fixed
- Provisioner ID mismatch causes range create status update to fail

## [1.0.0] - 2026-01-10

### Added
- NGFW create/destroy flow and UI
- NGFW's dynamically add routes for subnets in user ranges
- NGFW's dynamically pause if user has no active ranges
- CyberScript (DSL) templates and initial interpreter for all range operations (range, ngfw, dc, etc.)
- v1.0 of the Cortex BYOT scenario template
  - Two config options: Automated or Full Manual
  - Automated: NGFW, DC, 2x Workstations, Server, Attacker, domain join, XDR agent install, subnet routing
    - Remaining manual (automation coming soon): CIE, XDR Collector, Caldera
- Improved Bedrock logging and alarms
- Draft Cortex BYOT scenario template
- venv enforcer hook for Claude Code
- Guacamole RDP for Range instances
- User (not just technical) docs in Shifter

### Changed
- NGFW models and services refactored to use schemas
- Extended DSL and initial DSL interpreter implementation for NGFW flows
- Templates refactored to use CyberScript DSL
- Engine refactored to accept RequestSpec and interpret it into Engine models
- CyberScript subnets align with actual subnets in AWS
- AaC gate (service layer boundary violations at code or model level) fails will now block PRs
- AWS assets tagged to requests for cost tracking and cleanup
- Patched vulnerable urllib3, now on 2.6.3
- Update technical docs

### Fixed
- Dashboard range status updates and styling
- Better AaC checking in check_layer_imports script
- Sticky sesesions on Linux terminals: keep history, scrollback, etc when reconnecting
- tmux now used for Terminal UI sessions
- RDP copy/paste not working
- Packer does not clean up EC2 instance after build
- tmux Terminal UI sessions not allowing mouse scrolling

## [0.10.6] - 2025-01-09

### Added
- Guacamole RDP for Range instances

### Fixed
- tmux now used for Terminal UI sessions

## [0.10.5] - 2025-01-06

### Changed
- Added tmux install to Kali and Ubuntu AMIs

## [0.10.4] - 2025-01-06

### Fixed
- Hotfix for Home subnet CIDR conflict detection

## [0.10.3] - 2025-01-04

### Changed
- user_data for Shifter Platform deployment and ASG lifecycle hook

### Fixed
- Terminal timeouts, reconnects, and stability issues
- Range instance username mismatch

## [0.10.2] - 2025-01-04

### Changed
- GitHub runners replaced with auto-scaling ephemeral runners via terraform-aws-github-runner module
  - Scale from zero on workflow trigger
  - EC2 spot instances for cost savings
  - GitHub App authentication for secure runner registration
- Added runner-deploy.sh script for runner infrastructure management
- Added manual-deployment.md documentation for global terraform stacks


## [0.10.1] - 2025-01-02

### Added
- Cyber range DSL foundation (Shared Schema)
- Interactive cli app for Shifter AWS account bootstrap and infrastructure deployment
- Arch as Code foundation: Code and model level service layer boundary violation detection in CI/CD and pre-commit
- Independent processes consume range status updates
- Claude develop skill
- Centralized code coverage reporting

### Changed

- CMS services extraction edge cases and fixes
- Mission Control re-wire to use services
- Engine services extraction and implementation (excl pause/resume)
  - NGFW services deferred to upcoming patch
  - Mission Control re-wire deferred to upcoming patch
- Model migrations to respect service layer separation
- Redis replication for HA (single-node in dev, replication group in prod)
- SNS/SQS for range status updates with alarms
- Fault-tolerant fully alarmed range status consumer processes
- Unit test coverage improvements

### Fixed
- In-depth help check short circuited by Django middleware
- Remove dead code from service layer refactoring
- Frontend tests not included in pre-commit
- Remove stale Celery references
- Linting
- Some tests not called
- Pre-commit and CI/CD test, lint, quality, and sast coverage
- SonarQube coverage exclusions
- Tests for repo utility apps and Architecture as Code tests

## [0.10.0] - 2025-01-01

### Added
- CMS services extraction and implementation
- Unified Credential model

## [0.9.9] - 2025-12-31

### Added
- Management services implementation
  - cognito_sub update service
  - activity log service
  - user profile service

### Changed
- OIDC backend updated to use management services
- User profile model moved to management domain
- Activity log model moved to management domain

## [0.9.8] - 2025-12-31

### Added
- Portal NGFW Management UI (#416)
  - NGFW list view at `/mission-control/assets/ngfw/`
  - NGFW detail view with AWS resources, PAN-OS info, linked ranges
  - 5-step setup wizard (Name & Credentials → Registration → Confirm → Provisioning → Complete)
  - Deprovision confirmation view with linked ranges warning
  - API endpoints:
    - `GET /api/ngfw/list/` - List user's NGFWs
    - `POST /api/ngfw/` - Start provisioning
    - `GET /api/ngfw/<id>/status/` - Poll provisioning status
    - `POST /api/ngfw/<id>/start/` - Start NGFW
    - `POST /api/ngfw/<id>/stop/` - Stop NGFW
    - `POST /api/ngfw/<id>/deprovision/` - Deprovision NGFW
  - WebSocket consumer for real-time provisioning status updates
  - XDR manual configuration instructions with serial number display
  - 62 tests covering all views and APIs
- Test review skill (`.claude/skills/test-review/`)
  - 6 quality criteria with specific fail indicators
  - Anti-pattern catalog by severity (HIGH/MEDIUM/LOW)
  - Coverage gap detection checklist
  - Scoring formula and fix guidance

### Note
- NGFW API endpoints are stubbed pending Issue #414 (UserNGFWStack)
- UI is complete and functional with simulated provisioning flow

## [0.9.7] - 2025-12-30

### Security
- Hardened GitHub Actions OIDC IAM permissions to limit blast radius (#430)
  - Restricted `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PutRolePolicy` to specific role name patterns
  - Restricted `iam:CreateInstanceProfile` to matching instance profile patterns
  - Restricted `iam:PassRole` to same role patterns
  - Allowed patterns: `dev-portal-*`, `prod-portal-*`, `dev-range-*`, `prod-range-*`, `shifter-*`, `github-actions-shifter-*`
  - Prevents attacker from creating arbitrary roles with `AdministratorAccess` if GHA is compromised

## [0.9.6] - 2025-12-30

### Added
- S3 cost budget alerts for dev and prod environments
  - Defense-in-depth monitoring for unusual S3 costs
  - Alerts at 80% of $50/month threshold

## [0.9.3] - 2025-12-30

### Added
- Windows victim AMI Packer build (#410)
  - `windows.pkr.hcl` Packer template with WinRM communicator
  - PowerShell provisioning scripts: base, services, tools, claude-code, sysprep
  - XAMPP, IIS, FTP Server, OpenSSH Server
  - Python 3.12, Node.js 20.x, Git
  - Claude Code configured for Bedrock (system PATH at `C:\Program Files\nodejs`)
  - WinRM enabled for remote management
  - Windows Defender disabled via GPO for XDR compatibility
  - EC2Launch v2 sysprep for AMI finalization
- GitHub Actions workflow support for Windows AMI builds

### Changed
- Updated packer README with Windows AMI documentation
- Updated victim-ami.md with Packer build instructions

## [0.9.2] - 2025-12-30

### Added
- Ubuntu victim AMI Packer configuration (#409)
  - `ubuntu.pkr.hcl` template following Kali pattern
  - Provisioning scripts: base.sh, services.sh, tools.sh, claude-code.sh
  - Services: Apache 2.4 with mod_php, MySQL 8.0, Docker, OpenSSH, vsftpd, Samba
  - Development tools: build-essential, Python 3, Node.js 20.x, Git
  - Claude Code configured for AWS Bedrock
- GitHub Actions workflow support for Ubuntu AMI builds
- Ubuntu test classes in shifter/packer/tests/test_packer.py

### Changed
- SSM parameter for victim AMI renamed from `/shifter/ami/victim` to `/shifter/ami/ubuntu`
- Terraform data sources updated for new SSM parameter name

## [0.9.1] - 2025-12-30

### Changed
- Engine architecture refactor (#413)
  - Executors moved to `executors/` (ssm_executor, ssh_executor)
  - Orchestrators moved to `orchestrators/` (setup_orchestrator)
  - Plans moved to `plans/` (setup_plan.py → base.py)
  - RangeStack moved to `stacks/`
  - New: `AWSExecutor`, `OpsOrchestrator` stubs
  - New: Base protocols for executors and orchestrators

## [0.9.0] - 2025-12-30

### Added
- NGFW database models for persistent per-user NGFW support (#412)
  - `SCMCredential` model for Strata Cloud Manager PIN-based registration
  - `NGFWDeploymentProfile` model for Software NGFW Credits authcodes
  - `UserNGFW` model for persistent NGFW instances
  - `Asset` and `Credential` abstract base classes with soft delete and expiration
- Field-level encryption for sensitive credentials using `django-encrypted-model-fields`
  - `scm_pin_value` and `authcode` fields encrypted at rest
  - `FIELD_ENCRYPTION_KEY` environment variable required in production
- Range model fields for NGFW integration
  - `ngfw` FK to UserNGFW (SET_NULL on delete)
  - `gwlb_endpoint_id` for GWLB endpoint tracking
- Django admin for new models (SCMCredential, NGFWDeploymentProfile, UserNGFW)
- Database grants for provisioner_lambda user on new tables
- NGFW infrastructure foundation for persistent per-user NGFW instances (#408)
  - Dedicated /22 subnet (10.1.4.0/22) for ~500 NGFW capacity
  - Management security group (SSH/HTTPS from Portal for management)
  - Dataplane security group (all VPC traffic via GWLB)
  - IAM role with S3 bootstrap read and CloudWatch Logs access
  - CloudWatch alarm for NGFW capacity (>400 triggers SNS alert)
  - Terraform outputs for Engine/Pulumi consumption

### Removed
- `StrataConfig` model (superseded by `SCMCredential` and `NGFWDeploymentProfile`)
- Range fields: `ngfw_enabled`, `strata_config`, `ngfw_instance_id`, `ngfw_untrust_ip`, `ngfw_trust_ip`

## [0.8.9] - 2025-12-29

### Added
- Packer infrastructure for reproducible AMI builds (#273)
- sshpass in Kali AMI for non-interactive SSH (#273)
- GitHub Actions workflow for AMI builds

## [0.8.8] - 2025-12-29

### Changed
- Remove redundant SSH security group rules (#290)

## [0.8.7] - 2025-12-29

### Added
- `standup_duration` property on Range model for tracking provisioning time

## [0.8.6] - 2025-12-29

### Changed
- Remove Step Functions permissions from GitHub OIDC role (cleanup after v1 provisioner removal)

## [0.8.5] - 2025-12-29

### Fixed
- Dashboard dropdown behavior and portal test stability

## [0.8.4] - 2025-12-29

### Changed
- Extract service layer from views.py (engine, cms apps)
- Centralize Range status groupings as frozenset constants

## [0.8.3] - 2025-12-29

### Changes
- Refactor consumers.py for maintanability

## [0.8.2] - 2025-12-27

### Added
- NGFW (VM-Series) support
- Strata Cloud Manager support
- Cortex XDR sidebar submenu styling
- Asset Menu

### Changes
- GitGuardian and Snyk ignore tests

## [0.8.1] - 2025-12-27

### Changed
- Migrate all instances to Shifter Engine
- Docs updated to reflect new architecture and naming conventions

## [0.8.0] - 2025-12-27

### Added
- Domain controller AMI
- Basic AD scenario option with AD join by Windows
- Re-factor Shifter Engine scenario generation for extensibility

### Changed
- SonarQube ignores test files

## [0.7.20] - 2025-12-24

### Added
- JavaScript unit tests for DirectUploader (upload.js) with Jest (#136)
  - 79 tests covering happy paths, failure modes, edge cases, order of operations
  - Proper mocks for fetch, XMLHttpRequest, navigator.sendBeacon, window events
  - `make test-js` and `make test-js-coverage` Makefile targets
  - CI integration via `portal-js-tests` job in quality workflow

## [0.7.19] - 2025-12-24
- Add TDD planning Claude Code skill

## [0.7.18] - 2025-12-24

### Added
- Claude Code Skills for common repo/ops tasks

## [0.7.17] - 2025-12-24

### Changed
- Risk register app is accessible only by admin
- Removed History sidebar item (not yet working)
- Terminal page and link handles no active range gracefully

## [0.7.16] - 2025-12-23

### Added
- Developer documentation section (`docs/dev/`) with onboarding guides
  - Local setup, CI/CD, secrets management, Terraform patterns, engineering principles
- Commit tfvars to repository (no longer gitignored)
- Dev-box admin password auto-generated and stored in Secrets Manager

### Changed
- Removed `*.tfvars` from `.gitignore` - config values are not secrets
- Dev-box no longer requires manual password in tfvars

### Removed
- `terraform.tfvars.example` files (redundant now that tfvars are committed)
- `admin_password` variable from dev-box Terraform

## [0.7.15] - 2025-12-23

### Added
- Documentation section in Mission Control sidebar
- Renders markdown docs from `shifter/shifter_platform/documentation/docs/` with navigation tree
- Mermaid.js diagram support for architecture diagrams
- Cortex XDR dark theme styling for documentation pages

## [0.7.14] - 2025-12-22

### Fixed
- Terminal UI text overflows container

## [0.7.13] - 2025-12-22

### Fixed
- Terminal UI does not show IP address for Windows victims

## [0.7.12] - 2025-12-22

### Added
- Windows victim support in provisioner v2
- Windows victim AMI v3 with XAMPP, Claude Code, Python, Git, IIS, FTP, OpenSSH
- Terminal UI SSH support for Windows victims (Administrator username)
- Database migration granting provisioner SELECT on operatingsystem table

### Fixed
- Range destroy race condition leads to subnet collision
- Django logs not forwarded to CloudWatch
- Windows AMI sysprep: Claude Code installed to system path (`C:\Program Files\nodejs`)
- Windows Defender disabled via policy to avoid XDR conflicts

## [0.7.11] - 2025-12-21

.deb and .rpm packages confirmed fix as part of provisioner v2 in 0.7.7

### Added
- Provisioner confirms assigned subnet index is available before provisioning

### Fixed
- Kali boots slow due to redundant kali headless install
- Failed range auto-cleanup not running in dev


## [0.7.10] - 2025-12-21

### Fixed
- Provisioner fails to install .deb or .rpm agent packages properly
- Provisioner fails to rollback range if agent installation fails

## [0.7.9] - 2025-12-21

### Fixed
- Provisioner uses vars for instance types instead of hardcoded values

## [0.7.8] - 2025-12-21

### Added
- Standing dev box instance for development and testing

## [0.7.7] - 2025-12-21

### Added
- Pulumi-based provisioner for declarative multi-OS range infrastructure
  - ECS Fargate execution with Step Functions orchestration
  - S3/DynamoDB state backend, ECR container registry
  - Reusable components: NetworkComponent, InstanceComponent, RangeStack
  - Instance catalog supporting Kali, Ubuntu, Windows, Amazon Linux
- CI/CD workflow for Pulumi provisioner (`_pulumi-provisioner.yml`)
- Django model fields and service routing for v1 (Lambda) / v2 (Pulumi) provisioners
- Self-hosted GitHub Actions runner for CI/CD

### Changed
- Range instance types bumped to t3.medium (4GB min for Claude Code)
- CI Docker builds use local caching instead of GitHub Actions cache

### Fixed
- Secrets Manager resources now Pulumi-managed (proper lifecycle, no orphans)
- KMS policy, DNS egress, availability zone configuration for ECS tasks
- WebSocket terminal consumer reads from `provisioned_instances` field (v2 provisioner compatibility)

### Removed
- V1 (Lambda) provisioner

## [0.7.6] - 2025-12-19

### Added
- ALB access logs, VPC flow logs, RDS log exports, WAF logging
- XDR CloudTrail integration via CloudFormation (dev and prod)
- CloudWatch alarms for log aggregation (Firehose delivery lag, SQS DLQ)

### Changed
- Replaced Checkov skip comments with actual implementations (CKV_AWS_91, CKV2_AWS_11, CKV_AWS_129)
- Removed unused XDR IAM from Terraform (managed by CloudFormation instead)

### Fixed
- Multiple code quality, security, and code smells

## [0.7.5] - 2025-12-18

### Added
- AWS WAF protection for ALB with rate limiting and AWS managed rules

## [0.7.4] - 2025-12-18

### Added
- ElastiCache Redis module for Django Channels
- Portal autoscaling: launch template, ASG, scaling policies, CloudWatch alarms
- ALB session stickiness for WebSocket affinity
- Lambda auto-fix for range security group SSH rules from Portal VPC

### Changed
- Django Channels uses Redis when `REDIS_HOST` env var set, falls back to InMemory
- EC2 module supports single instance or ASG mode via `enable_autoscaling` flag
- Dev environment: autoscaling enabled with 2 instances
- GitHub Actions portal workflow supports ASG deployment via SSM targeting by tag
- IAM: Added `elasticache_asg` policy for ElastiCache, Auto Scaling, and Launch Template permissions


## [0.7.3] - 2025-12-17

### Fixed
- VPC peering TF drift dev/prod

### Fixed
- Network Firewall blocking XDR agent egress to Cortex cloud
  - Changed from STRICT_ORDER to DEFAULT_ACTION_ORDER for domain allowlist
  - Added Suricata rule to block direct IP connections (SNI bypass prevention)
- XDR agent not registering with tenant after installation
  - Added cortex.conf deployment before running installer script

## [0.7.2] - 2025-12-17

### Changed
- Removed redundant connection status from terminal header
- Increased terminal padding for better readability

## [0.7.1] - 2025-12-16

### Fixed
- XDR agent not installing on victim EC2 instances (#274)
  - Root cause: User data script used `aws s3 cp` but victim EC2 lacks AWS CLI
  - Changed to presigned URL + curl for agent download (no AWS CLI required)
  - Added SSM-based agent verification before marking range as ready
- CI/CD pipeline not updating Step Functions and Lambdas on code changes
  - Root cause: Missing `output_file_mode` in `archive_file` caused inconsistent zip hashes across CI runners
  - Added `output_file_mode = "0666"` to all Lambda archive_file blocks
  - Extracted Step Functions definitions to external ASL JSON files with `templatefile()`
- Dashboard polling errors when session expires during range provisioning
  - CORS errors occurred when API redirected to Cognito for re-authentication
  - Added session expiration detection and automatic redirect to login page
  - Network Firewall blocking XDR agent egress to Cortex cloud
    - Changed from STRICT_ORDER to DEFAULT_ACTION_ORDER for domain allowlist
    - Added Suricata rule to block direct IP connections (SNI bypass prevention)
  - XDR agent not registering with tenant after installation
    - Added cortex.conf deployment before running installer script

### Added
- Agent verification step in provisioning workflow
  - New `verify_agent` Lambda checks installation via SSM RunCommand
  - Step Functions retry loop with 30s intervals (5 min max)
  - Ranges fail fast with descriptive error if agent install fails
- External ASL state machine definitions for better maintainability
  - `provision_range.asl.json`, `teardown_range.asl.json`, `cleanup_stale_ranges.asl.json`

## [0.7.0] - 2025-12-16

### Added
- Claude Code on Kali and Victim AMIs for AI-assisted penetration testing
  - Configured for Amazon Bedrock (no internet required)
  - Role-specific CLAUDE.md system prompts for each instance type
  - Kali: Authorized pentester role with subnet-only scope
  - Victim: Scenario setup assistant for vulnerable configurations
- Bedrock VPC endpoints (bedrock-runtime, sts) for Range VPC
- Bedrock IAM permissions for range instance role

### Changed
- Increased Portal EC2 instance to t3.large (from t3.micro) for WebSocket stability
- Increased Kali and Victim instances to t3.small for Claude Code memory requirements

## [0.6.0] - 2025-12-16

### Added
- Browser-based Terminal UI for SSH access to range instances (#267)
  - Side-by-side Kali and Victim terminal panes with xterm.js
  - WebSocket-based SSH via Django Channels
  - Terminal sidebar menu item with active range indicator
- VPC peering between Portal and Range VPCs for SSH connectivity
- Security group rules allowing SSH from Portal to range instances

### Changed
- Switched from Gunicorn (WSGI) to Daphne (ASGI) for WebSocket support

### Fixed
- Buttons should not have underline

## [0.5.4] - 2025-12-15

### Removed
- OpenWebUI/AgentChat infrastructure (#261)
  - Deleted agentchat Terraform modules and environments
  - Removed MCP-Shifter and OpenWebUI MCP wrapper code
  - Removed agentchat GitHub Actions workflows
  - Removed ECR repositories for openwebui and mcp-shifter
  - Removed Cognito agentchat client
  - Removed openwebui_db Secrets Manager secret
  - Removed agentchat documentation
  - Removed migrations for victim_mcp_user and kali_mcp_user rename
- Entire MCP directory (`mcp/`) including aptl-mcp-common and mcp-red

### Changed
- Architecture updated: Chat UI replaced with planned browser-based terminal (Django Channels)
- `chat_base_url` now optional in provisioner module (empty string allowed)
- Updated CLAUDE.md and architecture docs to reflect new terminal-based approach

## [0.5.3] - 2025-12-15

### Added
- TARGET_MODE parameterization for MCP-Shifter (`kali` or `victim`)
  - Same binary serves both target types via environment variable
  - Dynamic column selection based on target mode
  - Tool prefixes match target type (`kali_*` or `victim_*`)
- Victim MCP database user (`victim_mcp_user`) for operational isolation
- Renamed `mcp_user` to `kali_mcp_user` for consistency
- SSM VPC Endpoints for Range VPC (ssm, ssmmessages, ec2messages)
  - Enables Systems Manager access without internet
  - Traffic stays within AWS network
- Custom OpenWebUI Docker image with Cortex theme baked in
  - ECR repository for custom OpenWebUI image
  - Dockerfile extends base image with custom CSS/assets
  - CI/CD builds and deploys themed image automatically
- Victim MCP wrapper for OpenWebUI (`mcp_wrapper_victim.py`)

### Changed
- Replaced mcp-red with mcp-shifter in CI quality workflow
- Architecture docs updated with MCP dual-container diagram
- AgentChat uses custom OpenWebUI image instead of stock ghcr.io image

## Fixed
- Missing s3 permissions to fetch XDR installer
- Fix range user_data fails to account for different installer types

## [0.5.2] - 2025-12-15

### Changed
- Reskin OpenWeb UI UX to match Cortex XDR look and feel

## [0.5.1] - 2025-12-15

### Added
- AWS Network Firewall for Range VPC egress filtering (#251)
- NAT Gateway for private subnet internet access
- Domain allowlists: Victim restricted to XDR endpoints, Kali has no external access

## [0.5.0] - 2025-12-14

### Added
- MCP-Shifter server for OpenWebUI integration (`mcp/mcp-shifter/`)
  - Cognito JWT authentication with per-user session management
  - RDS IAM authentication for range lookup
  - Secrets Manager integration for SSH key retrieval
  - Session limits (per-user and global) with structured logging
  - Idle connection cleanup timer
  - StreamableHTTPServerTransport for MCP over HTTP
- OpenWebUI MCP wrapper tool (`mcp/openwebui-mcp-wrapper/`)
- `cognito_sub` column on Range model for MCP user lookups
- Custom OIDC backend passing Cognito `sub` claim to Range model
- Security context in MCP server description (authorized pentest boundaries)
- VPC peering between Portal VPC and Range VPC for SSH connectivity
- ALB listener rules for `/chat` and `/mcp` path routing
- IAM policies for MCP server (RDS connect, Secrets Manager read)
- Security group rules for SSH from AgentChat to Kali instances
- Cognito app client for OpenWebUI OIDC authentication
- AgentChat docker-compose for local development (`agentchat/`)
- SSH keypair generation in create_kali Lambda (stored in Secrets Manager)
- `kali_ssh_key_secret_arn` field on Range model

### Changed
- AgentChat deployment workflow includes mcp-shifter container
- mark_ready Lambda sets chat_url when range becomes ready
- - AgentChat routing changed from subpath (`/chat/`) to subdomain (`chat.{domain}`)
- ACM certificate includes SAN for `chat.{domain}` subdomain
- Cognito OAuth callbacks updated for subdomain URLs
- ALB listener rules use `host_header` matching instead of `path_pattern`
- Docker layer caching added to portal and agentchat CI/CD workflows (faster builds)

## [0.4.5] - 2025-12-15
### Changed
- Reskin Portal and Risk Register to Cortex XDR look and feel

## [0.4.4] - 2025-12-14

### Changed

- Upgraded patch @modelcontextprotocol/sdk

## [0.4.3] - 2025-12-13

### Added
- Risk Register Django app
-
## [0.4.2] - 2025-12-13

### Added
- OpenWebUI + Bedrock Access Gateway (BAG) for AgentChat
- Sonnet 4.5 and DeepSeek R1 models for AgentChat
- AgentChat infrastructure
- Checkov IaC security scanning in CI and pre-commit
- Dockerfile HEALTHCHECK for portal container

### Changed
- SonarCloud coverage extended to all modules
- GitHub Actions workflows: explicit permissions, removed workflow_dispatch inputs where not needed
- Use SonarQube Cloud automatic analysis instead of CI/CD workflows

### Security
- Full review of lint (ruff, bandit, eslint) and IaC (checkov) findings
- Fixed critical issues: workflow permissions, Dockerfile healthcheck
- Created issues (#214-222) for deferred security hardening (WAF, flow logs, KMS, etc.)
- All checkov findings now have explicit skip comments with issue references

## [0.4.1] - 2025-12-12

### Removed
- LibreChat
- LiteLLM

## [0.4.0] - 2025-12-12

### Added
- Dev environment (`terraform/environments/dev/`)
- Branch-based deployments: `dev` branch → dev, `main` branch → prod
- Bootstrap script for new AWS accounts (`scripts/bootstrap-dev.sh`)

### Changed
- All workflows support environment selection via branch or manual dispatch
- Streamline GitHub Actions workflows for consistency
- Utility scripts work with dev and prod environments
- User updated immediately when range deploy fails

## [0.3.6] - 2025-12-11

### Fixed
- Remove default value from s3_bucket_arn variable (module variables should have no defaults)

## [0.3.5] - 2025-12-11

### Changed
- Make no versioning on user data s3 bucket explicit

## [0.3.4] - 2025-12-11

### Added
- AWS Bedrock as LibreChat LLM provider

### Changed
- LibreChat EC2 instance rebuilds on user_data changes

## [0.3.3] - 2025-12-11

### Changed
- RDS deletion protection enabled for prod database
- Final snapshot enabled before RDS deletion

## [0.3.2] - 2025-12-11

### Added
- Kali EC2 provisioning Lambda (create_kali) with official AWS Marketplace AMI
- Kali security group in Range VPC with bidirectional victim traffic
- kali_instance_id and kali_ip fields on Range model
- Kali cleanup in teardown Lambda
- Range VPC security documentation (security groups, traffic matrix, isolation)

### Changed
- Victim security group now allows all inbound from Kali SG (for attacks)
- Kali security group allows all inbound from Victim SG (reverse shells, C2)

## [0.3.1] - 2025-12-11

### Added
- LibreChat infrastructure (EC2, dedicated subnet, Secrets Manager, Docker Compose)
- LibreChat CI/CD workflows (infra and deploy)
- SSM tunnel script for LibreChat admin access

### Fixed
- Portal/LibreChat infra workflows now trigger on direct push to main, not just upstream cascade

## [0.3.0] - 2025-12-11

### Added
- Provisioner fields on Range model (subnet_id, subnet_cidr, subnet_index, victim_instance_id, step_function_execution_arn)
- IAM Database Authentication on RDS for Lambda provisioner
- Django migration to create provisioner_lambda PostgreSQL user with minimal permissions
- Provisioner Lambda functions (create_subnet, create_victim, create_kali, configure_librechat, cleanup)
- Step Functions state machines for provisioning and teardown with error handling and timeouts
- Victim security group in Range VPC
- Provisioner module wiring to Portal VPC with remote state references
- Portal integration with Step Functions (replaces callback-based stub)
- EC2 IAM permissions for Step Functions execution
- Range failure alarms
- Stale range cleanup
- docs/maintenance.md: RDS maintenance window reference

### Fixed
- Lambda DB queries: `agent_config_id` → `agent_id`, `os_type_id` → `os_id` (Django FK naming)
- Lambda handlers: `range_id[:8]` slice on integer (range_id is int, not UUID)
- db-connect.sh: Added autocommit for INSERT/UPDATE queries
- IAM policy: Fix `ec2:CreateSubnet` permission (unsupported `ec2:Vpc` condition key)
- Cleanup Lambda: Allow teardown from `ready` state (mark_failed=false)

### Removed
- Callback endpoint for provisioner (Lambda writes directly to DB)

## [0.2.9] - 2025-12-09

### Fixed
- AWS_REGION mismatch
- ALB health check errors
- Update docs

## [0.2.8] - 2025-12-09

### Fixed
- Range provisioner missing env var for domain
- Remove default site url for range provisioner

## [0.2.7] - 2025-12-09

### Added
- Dashboard Range launch flow with live status polling
- Range API endpoints (status, launch, cancel, destroy, callback)
- Range model status fields (pending, provisioning, ready, paused, resuming, destroying, destroyed, failed)
- Stub provisioner service with HMAC-signed callback tokens
- Client-side DashboardManager for state management
- State transition validation to prevent callback replay attacks

## [0.2.6] - 2025-12-08

### Fixed
- Upload lock clears on page navigation/error (beforeunload + 30s timeout fallback)

## [0.2.5] - 2025-12-08

### Added
- 2GB file upload via presigned S3 URLs with progress indicator
- 5GB per-user storage quota
- Upload cancel/abort support
- S3 CORS configuration for browser uploads
- S3 lifecycle rule for orphan cleanup

## [0.2.4] - 2025-12-08

### Fixed
- Logout now clears Cognito session (redirects to Cognito /logout endpoint)
- Local dev logout uses dev_logout instead of OIDC logout

## [0.2.3] - 2025-12-08

### Fixed
- Agent uploads failing: container now uses EC2 instance role via IMDSv2

### Removed
- Static IAM user credentials for portal container

## [0.2.2] - 2025-12-08

### Added
- Agent upload to S3 with magic byte validation
- File type validation (.msi, .zip, .tar.gz, .tgz, .deb, .rpm)
- Agent delete with S3 cleanup
- S3 bucket env var in deploy workflow

## [0.2.1] - 2025-12-08

### Added
- Mission Control data models (OperatingSystem, UserProfile, AgentConfig, Range, ActivityLog)
- Django admin registration for all models
- UserProfile auto-creation signal
- Model unit tests (21 tests, 100% coverage)

## [0.2.0] - 2025-12-08

### Added
- Mission Control UI shell (Dashboard, Agents, History, Settings, Help)
- Dev auth bypass for local testing
- User stories: Help, Language, Notifications

## [0.1.19] - 2025-12-08

### Changed
- Updated license to proprietary
- Block access to /admin from public internet

## [0.1.18] - 2025-12-08

### Changed
- Improved portal coming soon page design

## [0.1.17] - 2025-12-08

### Fixed
- Insecure TLS config in MCP HTTP client (removed global NODE_TLS_REJECT_UNAUTHORIZED)
- Portal deploy/infra workflow race condition (workflow_run trigger + concurrency)

### Security
- Upgraded @modelcontextprotocol/sdk to 1.24.3 (CVE-2025-66414 DNS rebinding fix)

## [0.1.16] - 2025-12-08

### Changed
- README update

## [0.1.15] - 2025-12-07

### Added
- Landing page at / to prevent redirect loop after OIDC auth

## [0.1.14] - 2025-12-07

### Fixed
- Cognito secret retrieval from Secrets Manager (issuer -> issuer_url key)

## [0.1.13] - 2025-12-07

### Added
- S3 user storage module for file uploads (agents, etc.)
- GitHub Actions IAM permissions for S3 bucket management

## [0.1.12] - 2025-12-07

### Added
- Range VPC module - stable VPC, IGW, route table
- Range environment config
- Range infrastructure workflow
- Range infrastructure documentation

## [0.1.11] - 2025-12-07

### Added
- Cognito Terraform module (user pool, client, hosted UI domain)
- Pre-signup Lambda for email domain restriction
- Auth architecture docs
- Wire Cognito into portal environment
- EC2 module accepts list of secret ARNs
- IAM permissions for Cognito and Lambda
- Django OIDC integration (mozilla-django-oidc)
- Entrypoint fetches Cognito secrets from Secrets Manager
- Deploy workflow passes COGNITO_SECRET_ARN to container

## [0.1.10] - 2025-12-07

### Fixed
- Hardcoded domain in Django ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS replaced with domain from tfvars secret

## [0.1.9] - 2025-12-07

### Fixed
- IAM permissions for SSM SendCommandToInstances
- Staticfiles directory permission error in container

## [0.1.13] - 2025-12-07

### Added
- S3 user storage module for file uploads (agents, etc.)
- GitHub Actions IAM permissions for S3 bucket management

## [0.1.8] - 2025-12-07

### Added
- Django portal Docker setup (multi-stage Dockerfile with uv)
- Container entrypoint with DB wait, migrations, gunicorn
- docker-compose.yml for local dev with Postgres
- Makefile with dev commands (up, down, build, logs, shell, migrate, init)
- GitHub Actions workflow for portal build, ECR push, SSM deploy
- Portal dev documentation
- Secrets management: IAM user for prod, Secrets Manager for DB + app secrets

### Changed
- Architecture docs updated with portal deployment pipeline
- GitHub OIDC role gets SSM permissions for deployments

## [0.1.7] - 2025-12-07

### Added
- Portal EC2 module (Docker host, SSM access, ECR/Secrets Manager IAM)
- Portal ALB module (ACM certificate, HTTPS listener, target group)
- Environment wiring with terraform_remote_state for ECR
- IAM permissions for EC2, ELB, ACM
- Security documentation
- Ethics documentation
- Disclaimer in README

### Changed
- Architecture docs updated for EC2+ALB (was ECS)
- ECR authentication via credential helper (replaces manual docker login)

### Security
- IMDSv2 enforced on EC2 (SSRF mitigation)
- ALB drops invalid HTTP headers
- ACM certificate validation with 45m timeout

## [0.1.6] - 2025-12-05

### Fixed
- Missing IAM permissions for ec2:ModifySubnetAttribute and iam:CreateServiceLinkedRole (RDS)

## [0.1.5] - 2025-12-05

### Added
- Portal VPC module (public/private subnets, NAT gateway)
- Portal RDS module (PostgreSQL, Secrets Manager credentials)
- Namespaced tfvars sync script (`TF_VARS_{ENV}_{COMPONENT}`)
- IAM permissions for VPC, RDS, Secrets Manager, KMS

## [0.1.4] - 2025-12-05

### Added
- Terraform foundation infrastructure (ECR module, global IAM, environment structure)
- GitHub Actions OIDC authentication for AWS
- CI/CD workflow for infrastructure deployment
- Version bump script

## [0.1.3] - 2025-12-05

### Added
- MkDocs with Material theme
- Documentation site (architecture, setup, API reference)
- GitHub Actions workflow for automatic GitHub Pages deployment
- Mermaid.js diagrams in architecture docs

## [0.1.2] - 2025-12-04

### Added

- Image assets for docs

### Changed
- Updated CLAUDE.md to reflect new architecture
- Removed unused files from .gitignore
- Only run mcp tests on code change

## [0.1.1] - 2025-12-04

### Added
- SonarCloud integration
- Build and test workflow
- Quality gate badge to README

### Fixed
- npm version mismatch

### Changed
- Upgraded vitest from 1.x to 4.x (required code changes to test files due to breaking changes)
## [0.1.0] - 2025-12-04

### Added
- Initial Shifter architecture for self-service cyber range platform
- Core MCP library (`mcp/aptl-mcp-common`) with SSH session management
- Reference MCP server (`mcp/mcp-red`) as template for new MCPs
- SonarCloud integration with automated code quality scanning
- Test coverage reporting via vitest with lcov output

### Changed
- Forked from APTL (Advanced Purple Team Lab) with new direction

### Removed
- All Docker/Wazuh infrastructure (replaced by XDR/XSIAM integration)
- Container definitions (kali, victim, gaming-api, minetest, minecraft, reverse)
- CTF scenarios (will be AI-generated dynamically)
- Local deployment scripts
