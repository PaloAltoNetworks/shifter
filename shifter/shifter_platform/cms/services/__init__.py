"""CMS service interface.

Content and asset management for Shifter platform. The implementation is
split across private submodules (``_common``, ``_agents``, ``_credentials``,
``_range_queries``, ``_range_create``, ``_range_destroy``, ``_range_pause``,
``_range_resume``, ``_uploads``, ``_scenarios``, ``_ngfws``, ``_queries``)
and re-exported here so callers continue to use
``from cms.services import X``.

The re-exports also rebind names that tests historically patch at
``cms.services.<name>`` (``assets_create_agent``, ``assets_delete_agent``,
``audit_log``, the ``engine_*`` aliases, ``RangeInstance``) so existing
``unittest.mock.patch`` targets still work.

The cross-layer re-exports (``cms.experiments.*``, ``cms.signals.*``) are
preserved on the facade so the layer-imports gate
(``scripts/check_layer_imports/layer_imports.yaml``) continues to allow
only ``cms.services`` from mission_control / ctf rather than reaching into
``cms.experiments`` / ``cms.signals`` directly.
"""

from __future__ import annotations

# --- Names tests patch via ``patch("cms.services.X")`` -----------------------
# Rebound here so the patch target resolves at the package level, which means
# submodules that look these up at call time through ``cms.services`` honour
# the mock for free.
from cms.assets.services import AgentUploadSpec
from cms.assets.services import create_agent as assets_create_agent
from cms.assets.services import delete_agent as assets_delete_agent
from cms.exceptions import CMSError
from cms.experiments.exceptions import ScriptUploadError as ScriptUploadError
from cms.experiments.services import complete_script_upload as complete_script_upload
from cms.experiments.services import delete_script as delete_script
from cms.experiments.services import initiate_script_upload as initiate_script_upload
from cms.experiments.services import list_scripts as list_scripts
from cms.models import AgentConfig, RangeInstance
from cms.signals import range_status_changed as range_status_changed
from engine.services import cancel_range_by_request as engine_cancel_range_by_request
from engine.services import create_range as engine_create_range
from engine.services import destroy_range_by_request as engine_destroy_range_by_request
from engine.services import get_instance_ips_by_uuid as engine_get_instance_ips_by_uuid
from engine.services import pause_range as engine_pause_range
from engine.services import resume_range as engine_resume_range
from risk_register.services import AuditEvent, audit_log

# --- Public service functions ------------------------------------------------
from ._agents import (
    create_agent,
    delete_agent,
    get_agent,
    get_allowed_extensions,
    list_agents,
)
from ._credentials import (
    create_credential,
    delete_credential,
    get_credential,
    list_credentials,
)
from ._ngfws import (
    create_ngfw,
    destroy_ngfw,
    get_ngfw,
    list_ngfws,
)
from ._queries import (
    find_range_instance_id_by_request,
    get_range_spec_by_id,
    get_range_status_by_id,
    get_range_target_instances,
)
from ._range_create import create_range
from ._range_destroy import (
    cancel_range,
    cancel_range_by_request_id,
    destroy_range,
    destroy_range_by_request_id,
)
from ._range_pause import pause_range, pause_range_by_request_id
from ._range_queries import (
    get_active_range,
    get_range,
    get_range_by_request_id,
    list_ranges,
)
from ._range_resume import resume_range, resume_range_by_request_id
from ._scenarios import (
    get_scenario,
    list_scenarios,
    validate_scenario_requirements,
)
from ._uploads import (
    cancel_upload,
    complete_upload,
    get_storage_used,
    initiate_upload,
)

# Cross-layer re-exports preserved on cms.services so the layer-imports gate
# (scripts/check_layer_imports/layer_imports.yaml) can continue to allow only
# `cms.services` from mission_control / ctf rather than reaching into
# cms.experiments / cms.signals directly.
__all__ = (
    "AgentConfig",
    "AgentUploadSpec",
    "AuditEvent",
    "CMSError",
    "RangeInstance",
    "ScriptUploadError",
    "assets_create_agent",
    "assets_delete_agent",
    "audit_log",
    "cancel_range",
    "cancel_range_by_request_id",
    "cancel_upload",
    "complete_script_upload",
    "complete_upload",
    "create_agent",
    "create_credential",
    "create_ngfw",
    "create_range",
    "delete_agent",
    "delete_credential",
    "delete_script",
    "destroy_ngfw",
    "destroy_range",
    "destroy_range_by_request_id",
    "engine_cancel_range_by_request",
    "engine_create_range",
    "engine_destroy_range_by_request",
    "engine_get_instance_ips_by_uuid",
    "engine_pause_range",
    "engine_resume_range",
    "find_range_instance_id_by_request",
    "get_active_range",
    "get_agent",
    "get_allowed_extensions",
    "get_credential",
    "get_ngfw",
    "get_range",
    "get_range_by_request_id",
    "get_range_spec_by_id",
    "get_range_status_by_id",
    "get_range_target_instances",
    "get_scenario",
    "get_storage_used",
    "initiate_script_upload",
    "initiate_upload",
    "list_agents",
    "list_credentials",
    "list_ngfws",
    "list_ranges",
    "list_scenarios",
    "list_scripts",
    "pause_range",
    "pause_range_by_request_id",
    "range_status_changed",
    "resume_range",
    "resume_range_by_request_id",
    "validate_scenario_requirements",
)
