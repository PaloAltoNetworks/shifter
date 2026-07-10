"""Mission Control view package.

The implementation is split across private submodules (``_pages``,
``_uploads``, ``_guacamole``, ``_ranges``, ``_ngfw``, ``_credentials``)
and re-exported here so existing
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
from collections.abc import Callable
from typing import Any

from django.http import HttpResponseBase
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
    list_launchable_scenarios as cms_list_launchable_scenarios,
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
    credential_add,
    credential_detail,
    credentials_list,
)
from ._ngfw import (
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


def _api_view(name: str) -> Callable[..., HttpResponseBase]:
    """Lazily resolve Mission Control DRF view callables.

    ``mission_control.api.views`` imports private helpers from this package, so
    eager imports here create a circular import while Django is loading URL
    modules. The wrapper preserves the legacy public names without importing
    the DRF module until request dispatch or a direct test call.
    """

    def _wrapped(request: object, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """Dispatch to the lazily imported DRF view callable."""
        from mission_control.api import views as api_views

        return getattr(api_views, name)(request, *args, **kwargs)

    return _wrapped


api_credential_create = _api_view("api_credential_create")
api_credential_delete = _api_view("api_credential_delete")
api_ngfw_create = _api_view("api_ngfw_create")
api_ngfw_destroy = _api_view("api_ngfw_destroy")
api_ngfw_list = _api_view("api_ngfw_list")
api_ngfw_ssh_url = _api_view("api_ngfw_ssh_url")
cancel_range = _api_view("cancel_range")
cancel_upload = _api_view("cancel_upload")
complete_upload = _api_view("complete_upload")
destroy_range = _api_view("destroy_range")
get_range = _api_view("get_range")
guacamole_bootstrap_open = _api_view("guacamole_bootstrap_open")
guacamole_bootstrap_status = _api_view("guacamole_bootstrap_status")
guacamole_rdp_url = _api_view("guacamole_rdp_url")
guacamole_ssh_url = _api_view("guacamole_ssh_url")
initiate_upload = _api_view("initiate_upload")
launch_range = _api_view("launch_range")
list_agents = _api_view("list_agents")
list_scenarios = _api_view("list_scenarios")
pause_range = _api_view("pause_range")
resume_range = _api_view("resume_range")

# Shared logger. All submodules use ``_common._logger()`` which late-binds
# through this module attribute so ``patch.object(views, "logger")`` works
# regardless of which submodule the actual emit happens from.
logger = logging.getLogger(__name__)

__all__ = (
    "AuditLog",
    "agents",
    "api_credential_create",
    "api_credential_delete",
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
    "cms_list_launchable_scenarios",
    "cms_list_ngfws",
    "cms_list_scenarios",
    "complete_upload",
    "credential_add",
    "credential_detail",
    "credentials_list",
    "dashboard",
    "delete_agent",
    "destroy_range",
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
