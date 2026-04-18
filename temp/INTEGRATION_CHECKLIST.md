# Provisioner Django Integration Checklist

## Context

The standalone provisioner (`shifter/engine/provisioner/`) was copied into the Django platform
(`shifter_platform/engine/provisioner/`) during Phase 3. Files were copied but never refactored
to work as a Django app. This checklist tracks the full integration.

### What's already done
- [x] `events.py` — refactored to use Django signals
- [x] `signals.py` — created with `range_status_changed`, `range_provisioned`, `ngfw_status_changed`
- [x] `tasks.py` — Celery tasks with lazy imports
- [x] `engine/services.py` — Django ORM service layer
- [x] Plans, orchestrators, executors, catalog — copied (pure logic, no DB)
- [x] Terraform modules copied to `terraform/`
- [x] `utils/text.py` — `sanitize_hostname` + `validate_s3_path` extracted

### Django models (engine/models.py)
- `Request` — `request_id` (UUID), `user` FK, `request_type`
- `Instance(Instantiation)` — `uuid`, `role`, `os_type`, `spec`, `state` (JSON), `status`, `request` FK, `subnet` FK
- `App(Instantiation)` — `uuid`, `app_type`, `spec`, `state`, `instance` FK
- `Range` — `status`, `range_config`, `provisioned_instances`, `ngfw_instance` FK, `subnet_index`, `user` FK, `request` FK, `error_message`, timestamps. Table: `mission_control_range`
- `Subnet(Instantiation)` — `uuid`, `name`, `connected_to`, `range` FK, `spec`, `state` (JSON), `status`

---

## Phase 1: Fix Imports (mechanical — no logic changes)

All `from foo import` → `from engine.provisioner.foo import`

### main.py (13 broken imports)
- [x] `import range_terraform_runner` → `from engine.provisioner.terraform import range_runner as range_terraform_runner`
- [x] `from catalog.instances import ...` → `from engine.provisioner.catalog.instances import ...`
- [x] `from config import generate_presigned_url` → `from engine.provisioner.config import generate_presigned_url`
- [x] `from events import ...` → `from engine.provisioner.events import ...`
- [x] `from ngfw_terraform import run_ngfw_terraform` → `from engine.provisioner.terraform import ngfw_runner as ngfw_terraform`
- [x] `from executors.aws_executor import AWSExecutor` → `from engine.provisioner.executors.aws_executor import AWSExecutor`
- [x] `from executors.ssh_executor import SSHExecutor` → `from engine.provisioner.executors.ssh_executor import SSHExecutor`
- [x] `from executors.ssm_executor import SSMExecutor` → `from engine.provisioner.executors.ssm_executor import SSMExecutor`
- [x] `from orchestrators.ops_orchestrator import OpsOrchestrator` → `from engine.provisioner.orchestrators.ops_orchestrator import OpsOrchestrator`
- [x] `from orchestrators.setup_orchestrator import ...` → `from engine.provisioner.orchestrators.setup_orchestrator import ...`
- [x] `from plans.*` (7 imports) → `from engine.provisioner.plans.*`
- [x] `from components.network import allocate_subnets` → `from engine.provisioner.utils.network import allocate_subnets`
- [x] `from components.instance import sanitize_hostname` → already fixed to `from engine.provisioner.utils.text import sanitize_hostname`

### terraform/ngfw_runner.py (5 broken + 5 lazy)
- [x] `import terraform_runner` → `from engine.provisioner.terraform import base_runner as terraform_runner`
- [x] `from events import ...` → `from engine.provisioner.events import ...`
- [x] `from executors.ssh_executor import SSHExecutor` → `from engine.provisioner.executors.ssh_executor import SSHExecutor`
- [x] `from orchestrators.setup_orchestrator import ...` → `from engine.provisioner.orchestrators.setup_orchestrator import ...`
- [x] `from plans.ngfw_provision import ...` → `from engine.provisioner.plans.ngfw_provision import ...`
- [x] 5 lazy `from main import ...` → `from engine.provisioner.main import ...`

### operations/range_ops.py (8 broken)
- [x] `from events import ...` → `from engine.provisioner.events import ...`
- [x] `from executors.aws_executor import AWSExecutor` → `from engine.provisioner.executors.aws_executor import AWSExecutor`
- [x] `from main import ...` → `from engine.provisioner.main import ...`
- [x] `from orchestrators.ops_orchestrator import ...` → `from engine.provisioner.orchestrators.ops_orchestrator import ...`
- [x] `from plans.ngfw_start import ...` → `from engine.provisioner.plans.ngfw_start import ...`
- [x] `from plans.ngfw_stop import ...` → `from engine.provisioner.plans.ngfw_stop import ...`
- [x] `from plans.range_pause import ...` → `from engine.provisioner.plans.range_pause import ...`
- [x] `from plans.range_resume import ...` → `from engine.provisioner.plans.range_resume import ...`

### executors/ (3 files, 1 fix each)
- [x] `executors/aws_executor.py`: `from executors.base import CommandResult` → `from engine.provisioner.executors.base import CommandResult`
- [x] `executors/ssh_executor.py`: `from executors.base import CommandResult` → `from engine.provisioner.executors.base import CommandResult`
- [x] `executors/ssm_executor.py`: `from executors.base import CommandResult` → `from engine.provisioner.executors.base import CommandResult`

### orchestrators/ (2 files)
- [x] `orchestrators/ops_orchestrator.py`: `from orchestrators.base import StepResult` → `from engine.provisioner.orchestrators.base import StepResult`
- [x] `orchestrators/setup_orchestrator.py`: 5 broken imports (executors.base, executors.ssh_executor x2, executors.ssm_executor, plans.base) → prefix all with `engine.provisioner.`

### plans/ (6 files)
- [x] `plans/ngfw_provision.py`: `from plans.base import SetupStep` → `from engine.provisioner.plans.base import SetupStep`
- [x] `plans/ngfw_add_address.py`: same fix
- [x] `plans/ngfw_add_rule.py`: same fix
- [x] `plans/ngfw_remove_address.py`: same fix
- [x] `plans/ngfw_remove_rule.py`: same fix
- [x] `plans/ngfw_configure_subnets.py`: `from plans.base` + `from plans.ngfw_provision` → prefix both

### Other
- [x] `utils/__init__.py`: `from utils.crypto import ...` → `from engine.provisioner.utils.crypto import ...`
- [x] `config.py`: `from catalog.instances import ...` → `from engine.provisioner.catalog.instances import ...`

### Phase 1 verification
- [x] `grep -rn '^from [a-z]' engine/provisioner/ --include='*.py'` — no standalone-style imports (filter stdlib/third-party)
- [x] `grep -rn 'from components\.' engine/provisioner/ --include='*.py'` — zero results

---

## Phase 2: Strip Pulumi Dead Code from main.py

### Delete Pulumi-only functions
- [x] N/A — these 9 functions were already stripped during the Phase 3 copy. The platform copy never had them.

### Remove dead imports
- [x] `import psycopg` — removed
- [x] `from psycopg import sql` — removed
- [x] `import pulumi` — removed from config.py

### Clean up config.py Pulumi code
- [x] Deleted `load_config()` (used `pulumi.Config()`)
- [x] Deleted `get_range_from_db()` (used raw psycopg)
- [x] Deleted `get_db_connection()` from config.py (duplicate of main.py version)

### Update docstring
- [x] Updated module docstring in main.py (removed Pulumi references)
- [x] Updated "Post-Pulumi" comment to "Post-Terraform"

### Phase 2 verification
- [x] No Pulumi functions in main.py
- [x] No `import subprocess` or `import shutil` in main.py (never had them — Pulumi functions were pre-stripped)

---

## Phase 3: Create utils/network.py

Extract subnet allocation functions from standalone `components/network.py` (lines 29-428).

### Functions extracted
- [x] `_get_vpc_lock_id()` — hash VPC ID to advisory lock ID
- [x] `_publish_subnet_exhaustion_alarm()` — CloudWatch metric
- [x] `_get_existing_subnets()` — boto3 `describe_subnets` call
- [x] `allocate_subnets()` — main entry point with advisory lock
- [x] `_allocate_subnets_internal()` — find free CIDRs
- [x] `_find_free_subnet()` — legacy single-subnet allocator
- [x] `_find_free_subnet_internal()` — single-subnet logic
- [x] `_generate_slash24_candidates()`
- [x] `_generate_slash28_candidates()`

### Refactored in the extract
- [x] Replaced `_get_db_connection()` (psycopg) with `from django.db import connection` and `connection.cursor()` for advisory locks
- [x] Removed `import psycopg` from the new file
- [x] Changed `except psycopg.Error` to `except Exception`

### Phase 3 verification
- [x] `from engine.provisioner.utils.network import allocate_subnets` — importable
- [x] No `psycopg` imports in new file

---

## Phase 4: Replace Raw SQL with Django ORM — main.py

12 `get_db_connection()` call sites. Each function rewritten.

### Functions converted
- [x] `get_db_connection()` — DELETED entirely
- [x] `update_range_status(range_id, status, **kwargs)` — `Range.objects.filter(id=range_id).update(...)`
- [x] `write_provisioned_state(range_id, subnets, instances, ngfw_instance_id)` — `Subnet.objects.filter(uuid=...).update(...)`, `Instance.objects.filter(uuid=...).update(...)`, `Range.objects.filter(id=...).update(...)`
- [x] `mark_range_instances_destroyed(range_id)` — `Instance.objects.filter(request=range_obj.request).update(...)`, `Subnet.objects.filter(range_id=range_id).update(...)`
- [x] `get_user_ngfw_data(user_id)` — `Instance.objects.filter(role='ngfw', request__user_id=user_id, status__in=[...]).select_related('request').order_by('-created_at').first()`
- [x] `user_has_active_ranges(user_id, exclude_range_id)` — `Range.objects.filter(user_id=..., status__in=[...]).exclude(id=...).exists()`
- [x] `get_ngfw_data_by_request_id(request_id)` — `Instance.objects.filter(role='ngfw', request__request_id=request_id).select_related('request')` + `App.objects.filter(instance=...).first()`
- [x] `get_range_data_by_request_id(request_id)` — `Range.objects.filter(request__request_id=request_id).select_related('request')` → build dict from model fields
- [x] `update_instance_state(request_id, status, **state_updates)` — `Instance.objects.filter(role='ngfw', request__request_id=request_id)` with JSON state merge via `instance.save()`
- [x] `find_stale_routes_by_db(range_id)` — `Range.objects.filter(id__in=range_ids).exclude(status__in=[...]).values_list('id', flat=True)`
- [x] Added `_validate_provisioned_outputs()` — was missing from platform copy (pure validation, no DB)

### Removed dead imports from main.py
- [x] `import psycopg`
- [x] `from psycopg import sql`

### Phase 4 verification
- [x] `grep -n 'get_db_connection\|psycopg' engine/provisioner/main.py` — zero results
- [x] `grep -n 'cur.execute\|conn.cursor' engine/provisioner/main.py` — zero results

---

## Phase 5: Replace Raw SQL with Django ORM — operations/range_ops.py

5 raw SQL functions converted.

### Functions converted
- [x] `get_range_instance_ids(request_id)` — `Instance.objects.filter(request__request_id=request_id, status__in=[...]).values('uuid', 'state', 'role')`
- [x] `get_range_ngfw_info(request_id)` — `Range.objects.filter(request__request_id=request_id).select_related('ngfw_instance', 'ngfw_instance__request')` + `App.objects.filter(instance=ngfw)`
- [x] `should_pause_ngfw(ngfw_instance_id, exclude_range_id)` — `Range.objects.filter(ngfw_instance_id=...).exclude(...).values('status').annotate(count=Count('id'))`
- [x] `_update_ngfw_status(ngfw_instance_id, status)` — `Instance.objects.filter(id=...).update(...)` + `App.objects.filter(instance_id=...).update(...)`
- [x] `_update_instance_statuses(request_id, status)` — `Instance.objects.filter(request__request_id=request_id).update(status=status)`

### Removed dead imports from range_ops.py
- [x] Removed `get_db_connection` from imports (no longer needed)
- [x] Added `from django.utils import timezone` for timestamp updates

### Phase 5 verification
- [x] `grep -n 'get_db_connection\|psycopg\|cur.execute' engine/provisioner/operations/range_ops.py` — zero results

---

## Phase 6: Add Entry-Point Wrappers in main.py

tasks.py expects these 9 functions. Created as thin wrappers.

- [x] `run_range_provision(request_id)` → delegates to `run_range_terraform("up", request_id)`
- [x] `run_range_destroy(request_id)` → delegates to `run_range_terraform("destroy", request_id)`
- [x] `run_range_pause(request_id)` → delegates to `engine.provisioner.operations.range_ops.run_range_pause(request_id)`
- [x] `run_range_resume(request_id)` → delegates to `engine.provisioner.operations.range_ops.run_range_resume(request_id)`
- [x] `run_ngfw_provision(request_id)` → delegates to `ngfw_terraform.run_ngfw_terraform("up", request_id)`
- [x] `run_ngfw_deprovision(request_id)` → delegates to `ngfw_terraform.run_ngfw_terraform("destroy", request_id)`
- [x] `run_ngfw_start(request_id)` → delegates to `run_ngfw_operation("start", request_id)`
- [x] `run_ngfw_stop(request_id)` → delegates to `run_ngfw_operation("stop", request_id)`
- [x] `run_ngfw_complete_setup(request_id)` → delegates to `_run_complete_setup(request_id)`

### Phase 6 verification
- [x] All 9 entry points importable from `engine.provisioner.main`

---

## Phase 7: Cleanup

- [x] `psycopg[binary]` stays in `pyproject.toml` — Django's `django.db.backends.postgresql` requires it
- [x] Updated Pulumi references in comments to say Terraform
- [x] Removed standalone `__main__` CLI entrypoint from main.py

---

## Final Verification

- [x] `grep -rn '^from [a-z]' engine/provisioner/ --include='*.py'` — no standalone-style imports remaining
- [x] `grep -rn 'get_db_connection\|psycopg' engine/provisioner/ --include='*.py'` — zero results
- [x] `grep -rn 'from components\.' engine/provisioner/ --include='*.py'` — zero results
- [x] `grep -rn 'import subprocess\|import shutil' engine/provisioner/main.py` — zero results (not applicable)
- [x] `TESTING=1 python -m pytest tests/ -x -q` — 1405 passed, 5 skipped
- [x] All 9 entry points importable from `engine.provisioner.main`
