"""Experiment manager business logic.

All business logic lives in the private submodules of this package
(``_common``, ``_scripts``, ``_experiments``, ``_artifacts``,
``_scenarios``) and is re-exported here so existing callers can keep
using ``from cms.experiments.services import X`` and existing
``unittest.mock.patch("cms.experiments.services.X")`` targets keep
working.

The patchable names exposed here (``transaction``, ``audit_log``,
``ScriptAsset``, ``Experiment``, ``ExperimentRun``, ``ExperimentScript``,
``ExperimentArtifact``, ``RunArtifact``, ``verify_upload_token``,
``verify_s3_object``, ``read_script_header``, ``delete_s3_object``,
``generate_script_upload_url``, ``generate_upload_token``,
``generate_presigned_download_url``, ``_check_result_type``) are looked
up by the submodules through this package at call time, so a test that
does ``patch("cms.experiments.services.X")`` takes effect inside the
service implementations exactly as before the split.

Views call services, services call models/S3.
"""

from __future__ import annotations

# --- Patchable dependency names ----------------------------------------------
# These are imported at package load so tests can target them via
# ``patch("cms.experiments.services.<name>")``. Submodules look them up
# through this package (``cms.experiments.services``) at call time so the
# patches apply across module boundaries.
from django.db import transaction

from cms.experiments.events import publish_experiment_event
from cms.experiments.models import (
    Experiment,
    ExperimentArtifact,
    ExperimentRun,
    ExperimentScript,
    RunArtifact,
    ScriptAsset,
)
from cms.experiments.s3 import (
    delete_s3_object,
    generate_presigned_download_url,
    generate_script_upload_url,
    generate_upload_token,
    read_script_header,
    verify_s3_object,
    verify_upload_token,
)
from cms.scenarios.registry import check_scenario_access, load_scenario_template
from risk_register.services import audit_log

# --- Shared helpers (also patchable) -----------------------------------------
from ._common import _check_result_type, _validate_user

# --- Public service functions ------------------------------------------------
from ._artifacts import get_artifact_download_url, get_bundle_download_url
from ._experiments import (
    cancel_experiment,
    create_experiment,
    get_experiment,
    list_experiments,
    start_experiment,
)
from ._scenarios import get_scenario_instances
from ._scripts import (
    complete_script_upload,
    delete_script,
    initiate_script_upload,
    list_scripts,
)

__all__ = [
    # Patchable dependencies (kept on __all__ so re-import is intentional)
    "Experiment",
    "ExperimentArtifact",
    "ExperimentRun",
    "ExperimentScript",
    "RunArtifact",
    "ScriptAsset",
    "_check_result_type",
    "_validate_user",
    "audit_log",
    "check_scenario_access",
    "delete_s3_object",
    "generate_presigned_download_url",
    "generate_script_upload_url",
    "generate_upload_token",
    "load_scenario_template",
    "publish_experiment_event",
    "read_script_header",
    "transaction",
    "verify_s3_object",
    "verify_upload_token",
    # Public service functions
    "cancel_experiment",
    "complete_script_upload",
    "create_experiment",
    "delete_script",
    "get_artifact_download_url",
    "get_bundle_download_url",
    "get_experiment",
    "get_scenario_instances",
    "initiate_script_upload",
    "list_experiments",
    "list_scripts",
]
