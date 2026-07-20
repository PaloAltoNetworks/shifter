"""Cross-domain template context processors (composition root).

These compose authorization flags across domains for template rendering, so they
live at the ``config`` composition root and consume public domain service
facades rather than reaching into a domain's models or policy modules (ADR-001,
#1523). Moved here from ``shared`` so the contracts layer no longer imports the
risk-register domain.
"""

from __future__ import annotations

import logging

from django.http import HttpRequest

from risk_register.services import principal_has_risk_register_access
from shared.auth import can_edit_cms_authoring

logger = logging.getLogger(__name__)


def user_permissions(request: HttpRequest) -> dict[str, bool]:
    """Inject authorization flags into every template context."""
    if not request.user.is_authenticated:
        return {
            "can_access_threat_research": False,
            "can_access_risk_register": False,
        }

    can_access_risk_register = principal_has_risk_register_access(request)
    allowed = can_edit_cms_authoring(request.user)
    logger.debug(
        "user_permissions: user=%s can_access_threat_research=%s can_access_risk_register=%s",
        request.user.pk,
        allowed,
        can_access_risk_register,
    )
    return {
        "can_access_threat_research": allowed,
        "can_access_risk_register": can_access_risk_register,
    }
