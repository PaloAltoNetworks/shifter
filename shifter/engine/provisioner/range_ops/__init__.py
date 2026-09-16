"""Range pause/resume operations.

Handles pausing and resuming all provisioned assets in a range.

Split across private submodules by responsibility and re-exported here so
callers keep using ``from range_ops import X`` / ``range_ops.<name>`` exactly
as before the split:

- ``_ngfw``: NGFW pause/resume/status helpers used during range lifecycle
  transitions (shared-NGFW pause eligibility, EC2 stop/start, status
  propagation).
- ``_pause_resume``: range-wide pause/resume orchestration - classifying
  instances, running per-instance operations in parallel, and updating
  range/instance status in the database.

Several collaborator names below (``AWSExecutor``, ``OpsOrchestrator``,
``NGFWStartPlan``, ``get_db_connection``, ``get_range_data_by_request_id``,
``update_range_status``, ``time``) are re-exported
here - not just imported by the submodule that uses them - because the test
suite patches them at ``range_ops.<name>``. Submodule functions call back
into this package at call time (``import range_ops as _pkg; _pkg.<name>``)
so those patches take effect, mirroring the ``components.network`` split.
"""

from __future__ import annotations

import time

from executors.aws_executor import AWSExecutor
from orchestrators.ops_orchestrator import OpsOrchestrator
from plans.ngfw_start import NGFWStartPlan
from provisioner_db import get_db_connection, get_range_data_by_request_id, update_range_status

from ._ngfw import (
    NGFW_START_MAX_RETRIES,
    NGFW_START_RETRY_DELAYS,
    _publish_ngfw_status,
    _run_ngfw_start_with_retry,
    _update_ngfw_status,
    _wait_for_ngfw_pause_to_complete,
    ensure_ngfw_running,
    get_range_ngfw_info,
    pause_ngfw_for_range,
    should_pause_ngfw,
)
from ._pause_resume import (
    _build_aws_lifecycle_entry,
    _build_range_lifecycle_entry,
    _execute_instance_operation,
    _update_instance_statuses,
    get_range_instance_ids,
    run_range_pause,
    run_range_resume,
)

__all__ = [
    "NGFW_START_MAX_RETRIES",
    "NGFW_START_RETRY_DELAYS",
    "AWSExecutor",
    "NGFWStartPlan",
    "OpsOrchestrator",
    "_build_aws_lifecycle_entry",
    "_build_range_lifecycle_entry",
    "_execute_instance_operation",
    "_publish_ngfw_status",
    "_run_ngfw_start_with_retry",
    "_update_instance_statuses",
    "_update_ngfw_status",
    "_wait_for_ngfw_pause_to_complete",
    "ensure_ngfw_running",
    "get_db_connection",
    "get_range_data_by_request_id",
    "get_range_instance_ids",
    "get_range_ngfw_info",
    "pause_ngfw_for_range",
    "run_range_pause",
    "run_range_resume",
    "should_pause_ngfw",
    "time",
    "update_range_status",
]
