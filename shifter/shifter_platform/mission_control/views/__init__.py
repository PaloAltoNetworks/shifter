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

from django.shortcuts import render

from cms.services import (
    create_credential as cms_create_credential,
)
from cms.services import (
    create_ngfw as cms_create_ngfw,
)
from cms.services import (
    create_range_dispatch as cms_create_range,
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
from cms.services import extend_mission_control_range as cms_extend_mission_control_range
from cms.services import (
    get_active_range,
    get_allowed_extensions,
    get_mission_control_openvpn_profile,
    get_mission_control_range_lease,
    has_mission_control_openvpn_profile,
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
from shared.audit import audit_log_from_request

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

# The Mission Control JSON views live in ``mission_control.api.views`` (served
# under ``/api/v1/mission-control/``). The legacy ``_api_view`` re-export layer
# that mirrored them here for the retired ``/mission-control/api/*`` mount was
# removed in #1328; import the DRF views directly from ``mission_control.api``.

# Shared logger. All submodules use ``_common._logger()`` which late-binds
# through this module attribute so ``patch.object(views, "logger")`` works
# regardless of which submodule the actual emit happens from.
logger = logging.getLogger(__name__)

__all__ = (
    "agents",
    "audit_log_from_request",
    "cms_create_credential",
    "cms_create_ngfw",
    "cms_create_range",
    "cms_delete_agent",
    "cms_delete_credential",
    "cms_destroy_ngfw",
    "cms_extend_mission_control_range",
    "cms_get_agent",
    "cms_get_credential",
    "cms_get_ngfw",
    "cms_list_agents",
    "cms_list_credentials",
    "cms_list_launchable_scenarios",
    "cms_list_ngfws",
    "cms_list_scenarios",
    "credential_add",
    "credential_detail",
    "credentials_list",
    "dashboard",
    "delete_agent",
    "get_active_range",
    "get_allowed_extensions",
    "get_mission_control_openvpn_profile",
    "get_mission_control_range_lease",
    "has_mission_control_openvpn_profile",
    "help_page",
    "logger",
    "ngfw_deprovision",
    "ngfw_detail",
    "ngfw_list",
    "ngfw_wizard",
    "render",
    "settings",
    "terminal",
    "walkthrough",
)
