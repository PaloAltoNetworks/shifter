"""Mission Control view package.

The implementation is split across private submodules (``_pages``,
``_ngfw``, ``_credentials``, ``_guacamole_bootstrap``) and the
view callables are re-exported here so existing
``from mission_control.views import X`` and ``from mission_control import views;
views.X`` call sites (URL configuration) continue to work.
"""

from __future__ import annotations

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

__all__ = (
    "agents",
    "credential_add",
    "credential_detail",
    "credentials_list",
    "dashboard",
    "delete_agent",
    "help_page",
    "ngfw_deprovision",
    "ngfw_detail",
    "ngfw_list",
    "ngfw_wizard",
    "settings",
    "terminal",
    "walkthrough",
)
