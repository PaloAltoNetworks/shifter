"""Mission Control view package.

The implementation is split across private submodules (``_pages``,
``_uploads``, ``_guacamole``, ``_ranges``, ``_ngfw``, ``_credentials``,
``_files``) and re-exported here so existing
``from mission_control.views import X`` and ``from mission_control import views;
views.X`` call sites continue to work.

The re-exports also rebind a handful of names that tests historically
patch at ``mission_control.views.<name>`` (``render``, ``logger``,
``audit_log_from_request``, the ``cms_*`` aliases, ``get_active_range``,
``get_allowed_extensions``). Submodules call through the late-binding
helpers in ``_common`` so those patches still hit the same objects the
submodule code sees.
"""

from __future__ import annotations

import logging

from django.shortcuts import render

from cms.services import (
    create_credential as cms_create_credential,
)
from cms.services import (
    create_ngfw as cms_create_ngfw,
)
from cms.services import (
    create_range as cms_create_range,
)
from cms.services import (
    delete_agent as cms_delete_agent,
)
from cms.services import (
    delete_credential as cms_delete_credential,
)
from cms.services import (
    destroy_ngfw as cms_destroy_ngfw,
)
from cms.services import (
    get_active_range,
    get_allowed_extensions,
)
from cms.services import (
    get_agent as cms_get_agent,
)
from cms.services import (
    get_credential as cms_get_credential,
)
from cms.services import (
    get_ngfw as cms_get_ngfw,
)
from cms.services import (
    list_agents as cms_list_agents,
)
from cms.services import (
    list_credentials as cms_list_credentials,
)
from cms.services import (
    list_ngfws as cms_list_ngfws,
)
from cms.services import (
    list_scenarios as cms_list_scenarios,
)
from risk_register.models import AuditLog
from risk_register.services import audit_log_from_request

from ._credentials import (
    api_credential_create,
    api_credential_delete,
    credential_add,
    credential_detail,
    credentials_list,
)
from ._files import (
    api_list_scripts,
    file_delete,
    file_upload,
    files,
)
from ._guacamole import (
    api_ngfw_ssh_url,
    guacamole_rdp_url,
    guacamole_ssh_url,
)
from ._guacamole_bootstrap import (
    guacamole_bootstrap_open,
    guacamole_bootstrap_status,
)
from ._ngfw import (
    api_ngfw_create,
    api_ngfw_destroy,
    api_ngfw_list,
    ngfw_deprovision,
    ngfw_detail,
    ngfw_list,
    ngfw_wizard,
)
from ._pages import (
    agents,
    dashboard,
    delete_agent,
    help_page,
    settings,
    terminal,
    walkthrough,
)
from ._ranges import (
    cancel_range,
    destroy_range,
    get_range,
    launch_range,
    list_scenarios,
    pause_range,
    resume_range,
)
from ._ranges import (
    list_agents as list_agents_api,
)
from ._uploads import (
    cancel_upload,
    complete_upload,
    initiate_upload,
)

# ``list_agents`` exists as both the JSON API view (``_ranges.list_agents``)
# and the imported ``cms.services.list_agents`` rebind above. The JSON view
# is the public ``mission_control.views.list_agents`` per the urlconf; the
# rebound CMS helper is exposed as ``cms_list_agents`` for the patch contract.
list_agents = list_agents_api

# Shared logger. All submodules use ``_common._logger()`` which late-binds
# through this module attribute so ``patch.object(views, "logger")`` works
# regardless of which submodule the actual emit happens from.
logger = logging.getLogger(__name__)

__all__ = (
    "AuditLog",
    "agents",
    "api_credential_create",
    "api_credential_delete",
    "api_list_scripts",
    "api_ngfw_create",
    "api_ngfw_destroy",
    "api_ngfw_list",
    "api_ngfw_ssh_url",
    "audit_log_from_request",
    "cancel_range",
    "cancel_upload",
    "cms_create_credential",
    "cms_create_ngfw",
    "cms_create_range",
    "cms_delete_agent",
    "cms_delete_credential",
    "cms_destroy_ngfw",
    "cms_get_agent",
    "cms_get_credential",
    "cms_get_ngfw",
    "cms_list_agents",
    "cms_list_credentials",
    "cms_list_ngfws",
    "cms_list_scenarios",
    "complete_upload",
    "credential_add",
    "credential_detail",
    "credentials_list",
    "dashboard",
    "delete_agent",
    "destroy_range",
    "file_delete",
    "file_upload",
    "files",
    "get_active_range",
    "get_allowed_extensions",
    "get_range",
    "guacamole_bootstrap_open",
    "guacamole_bootstrap_status",
    "guacamole_rdp_url",
    "guacamole_ssh_url",
    "help_page",
    "initiate_upload",
    "launch_range",
    "list_agents",
    "list_scenarios",
    "logger",
    "ngfw_deprovision",
    "ngfw_detail",
    "ngfw_list",
    "ngfw_wizard",
    "pause_range",
    "render",
    "resume_range",
    "settings",
    "terminal",
    "walkthrough",
)
