"""Shifter CMS - Content management services.

Scenarios, agents, credentials, and range orchestration.
"""


def __getattr__(name: str):
    """Lazy import for CMS public API.

    Defers imports until first access to avoid circular import issues
    during Django app initialization.
    """
    if name == "CMSError":
        from .exceptions import CMSError

        return CMSError

    if name in __all__:
        from . import services

        return getattr(services, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CMSError",
    "cancel_range",
    "cancel_upload",
    "complete_upload",
    "create_agent",
    "create_credential",
    "create_range",
    "delete_agent",
    "delete_credential",
    "destroy_range",
    "get_active_range",
    "get_agent",
    "get_allowed_extensions",
    "get_credential",
    "get_range",
    "get_scenario",
    "get_storage_used",
    "initiate_upload",
    "list_agents",
    "list_credentials",
    "list_ranges",
    "list_scenarios",
    "pause_range",
    "resume_range",
    "validate_scenario_requirements",
]
