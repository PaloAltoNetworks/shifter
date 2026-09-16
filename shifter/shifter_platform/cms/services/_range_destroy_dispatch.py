"""Late-bound engine calls used by range destroy and cancellation flows."""

from uuid import UUID


def engine_destroy_range_by_request(request_id: UUID) -> bool:
    """Resolve the public facade at call time so boundary patches remain effective."""
    from cms import services

    return services.engine_destroy_range_by_request(request_id)


def engine_cancel_range_by_request(request_id: UUID) -> bool:
    """Resolve the public facade at call time so boundary patches remain effective."""
    from cms import services

    return services.engine_cancel_range_by_request(request_id)
