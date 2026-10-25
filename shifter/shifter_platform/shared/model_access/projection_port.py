"""Owner-side membership refresh composition; Engine never calls this port."""

from collections.abc import Callable
from uuid import UUID

from shared.model_access.catalog import ContractError

_refresher: Callable[[UUID], None] | None = None


def bind_projection_refresher(refresher: Callable[[UUID], None]) -> None:
    """Bind the composition-root adapter once at application startup."""
    global _refresher
    if _refresher is not None and _refresher is not refresher:
        raise ContractError("allocation.projection_adapter_conflict")
    _refresher = refresher


def refresh_launch_projections(deployment_id: UUID) -> None:
    """Owners refresh stale projections before sending allocation inputs downward."""
    if _refresher is None:
        raise ContractError("allocation.projection_adapter_missing")
    try:
        _refresher(deployment_id)
    except Exception:
        raise ContractError("allocation.authority_unavailable") from None
