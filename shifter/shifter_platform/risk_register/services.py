"""Risk-register domain public service facade.

This module is the risk domain's public boundary: composition code (``config``)
and other layers consume risk-register capabilities through it rather than
reaching into models or private modules (ADR-001).

The platform audit vocabulary, port, and emission policy moved to
``shared.audit`` in #1523; this module now exposes the concrete audit
persistence adapter for the startup binding seam, the risk-register access
policy, and bounded read summaries. Emitters record audit events via
``shared.audit``, never through here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from risk_register.access import principal_has_risk_register_access
from risk_register.audit_adapter import audit_log_writer

if TYPE_CHECKING:
    from rest_framework.request import Request

logger = logging.getLogger(__name__)

__all__ = [
    "audit_log_writer",
    "dashboard_risk_summary",
    "principal_has_risk_register_access",
]


def dashboard_risk_summary(request: Request) -> dict[str, object]:
    """Return a bounded risk-register load summary for the SPA dashboard.

    Cross-domain composition (``config.api_dashboard``) needs the risk load
    without importing risk-register models directly. Access is gated by the
    advisory access policy; every field fails closed so a degraded dependency
    never breaks the dashboard. Returns bounded primitives only.
    """
    if not principal_has_risk_register_access(request):
        return {"accessible": False, "open_count": None}
    try:
        from risk_register.models import Risk, Status

        open_count = Risk.objects.filter(status=Status.OPEN).count()
    except Exception:
        logger.exception("dashboard summary: risk-register count failed")
        return {"accessible": True, "open_count": None}
    return {"accessible": True, "open_count": open_count}
