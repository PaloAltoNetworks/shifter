"""Context processors for the shared app."""

from __future__ import annotations

import logging

from django.http import HttpRequest

from shared.auth import can_edit_cms_authoring

logger = logging.getLogger(__name__)


def user_permissions(request: HttpRequest) -> dict[str, bool]:
    """Inject ``can_access_threat_research`` into every template context."""
    if not request.user.is_authenticated:
        return {"can_access_threat_research": False}

    allowed = can_edit_cms_authoring(request.user)
    logger.debug(
        "user_permissions: user=%s can_access_threat_research=%s",
        request.user.pk,
        allowed,
    )
    return {"can_access_threat_research": allowed}
