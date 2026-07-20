"""Agent service entrypoints (create / delete / list / get).

These functions thin-wrap ``cms.assets.services`` with the canonical CMS
input validation and audit/error envelope. The delegated assets helpers
are looked up through the ``cms.services`` package at call time so tests
that patch ``cms.services.assets_create_agent`` / ``assets_delete_agent``
keep working after the package split.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.exceptions import CMSError
from cms.models import AgentConfig

from ._common import (
    _agent_projection_dict,
    _validate_caller_user,
    _validate_listing_user,
    _validate_nonneg_int_id,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def _assets_create_agent_call(**kwargs: Any) -> AgentConfig:
    """Late-bound call to ``cms.services.assets_create_agent`` so test patches apply."""
    from cms import services as _cs

    return _cs.assets_create_agent(**kwargs)


def _assets_delete_agent_call(agent: AgentConfig) -> None:
    """Late-bound call to ``cms.services.assets_delete_agent`` so test patches apply."""
    from cms import services as _cs

    _cs.assets_delete_agent(agent)


def create_agent(user: User, **kwargs: Any) -> AgentConfig:
    """Create agent record.

    Delegates to cms.assets.services.create_agent() after validating user.

    Args:
        user: User who will own the agent
        **kwargs: Arguments passed to assets service:
            - name: Display name for the agent
            - s3_key: S3 key where the agent file is stored
            - filename: Original filename of the agent
            - os_slug: Operating system slug (e.g., 'windows', 'linux-debian')
            - file_size: Size of the agent file in bytes
            - sha256: SHA256 hash (optional, for future server-side compute)
            - upload_method: Optional upload method for logging

    Returns:
        AgentConfig: The newly created agent record

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
        AssetError: If the operating system is not found
    """
    _validate_caller_user(user, "create_agent")

    logger.debug("create_agent called for user_id=%s", user.id)

    try:
        from cms.assets.services import AgentUploadSpec

        agent = _assets_create_agent_call(user=user, spec=AgentUploadSpec(**kwargs))

        if agent is None:
            logger.error(
                "create_agent: assets service returned None for user_id=%s",
                user.id,
            )
            msg = "Assets service returned None instead of AgentConfig"
            raise TypeError(msg)

        if not isinstance(agent, AgentConfig):
            logger.error(
                "create_agent: assets service returned invalid type %s for user_id=%s",
                type(agent).__name__,
                user.id,
            )
            msg = f"Assets service returned {type(agent).__name__}, expected AgentConfig"
            raise TypeError(msg)

        logger.debug(
            "create_agent returning agent_id=%s for user_id=%s",
            agent.id,
            user.id,
        )
        return agent

    except TypeError:
        raise
    except Exception:
        logger.exception("Error in create_agent for user_id=%s", user.id)
        raise


def delete_agent(user: User, agent_id: int) -> None:
    """Soft delete agent.

    Verifies ownership via get_agent, then delegates to
    cms.assets.services.delete_agent().

    Args:
        user: User requesting deletion
        agent_id: ID of the agent to delete

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or agent_id is invalid type
        ValueError: If user has no ID (unsaved) or agent_id is invalid
        CMSError: If agent not found or not owned by user
        AssetError: If S3 delete fails
    """
    _validate_caller_user(user, "delete_agent")

    if agent_id is None:
        logger.error(
            "delete_agent called with None agent_id for user_id=%s",
            user.id,
        )
        raise TypeError("agent_id cannot be None")

    if not isinstance(agent_id, int):
        logger.error(
            "delete_agent called with invalid agent_id type: %s",
            type(agent_id).__name__,
        )
        msg = f"agent_id must be an int, got {type(agent_id).__name__}"
        raise TypeError(msg)

    if agent_id < 0:
        logger.error(
            "delete_agent called with negative agent_id=%s for user_id=%s",
            agent_id,
            user.id,
        )
        raise ValueError("agent_id must be non-negative")

    logger.debug(
        "delete_agent called for user_id=%s, agent_id=%s",
        user.id,
        agent_id,
    )

    try:
        # Look up through the package so tests can patch
        # ``cms.services.get_agent`` to short-circuit the lookup.
        from cms import services as _cs

        agent = _cs.get_agent(user, agent_id)
        _assets_delete_agent_call(agent)

        logger.debug(
            "delete_agent completed for agent_id=%s, user_id=%s",
            agent_id,
            user.id,
        )

    except Exception:
        logger.exception(
            "Error in delete_agent for user_id=%s, agent_id=%s",
            user.id,
            agent_id,
        )
        raise


def list_agents(user: User) -> list[dict[str, Any]]:
    """Get user's agents as projection dicts.

    Args:
        user: User whose agents to retrieve

    Returns:
        List of agent dicts with keys: id, name, os_name, os_slug, file_size_mb,
        original_filename, created_at, agent_type, agent_type_display

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
    """
    _validate_listing_user(user, "list_agents")

    logger.debug("list_agents called for user_id=%s", user.id)

    try:
        result = AgentConfig.active_for_user(user).select_related("os")
        if result is None:
            logger.error("list_agents: model returned None for user_id=%s", user.id)
            raise TypeError("Model returned None instead of iterable")

        agents = [_agent_projection_dict(agent) for agent in result]

        logger.debug(
            "list_agents returning %d agents for user_id=%s",
            len(agents),
            user.id,
        )
        return agents

    except TypeError:
        raise
    except Exception:
        logger.exception("Error in list_agents for user_id=%s", user.id)
        raise


def get_agent(user: User, agent_id: int) -> AgentConfig:
    """Get single agent by ID.

    Args:
        user: User requesting the agent
        agent_id: ID of the agent to retrieve

    Returns:
        AgentConfig instance if found and owned by user

    Raises:
        TypeError: If user is None, invalid type, or agent_id is invalid type
        ValueError: If user has no ID (unsaved) or agent_id is invalid
        CMSError: If agent not found, not owned by user, or deleted
    """
    _validate_caller_user(user, "get_agent")
    _validate_nonneg_int_id(agent_id, "agent_id", "get_agent", user.id)

    logger.debug(
        "get_agent called for user_id=%s, agent_id=%s",
        user.id,
        agent_id,
    )

    try:
        agent = AgentConfig.objects.get(id=agent_id)

        if agent is None:
            logger.error(
                "get_agent: model returned None for agent_id=%s",
                agent_id,
            )
            msg = "Model returned None instead of AgentConfig"
            raise TypeError(msg)

        if not isinstance(agent, AgentConfig):
            logger.error(
                "get_agent: model returned invalid type %s for agent_id=%s",
                type(agent).__name__,
                agent_id,
            )
            msg = f"Model returned {type(agent).__name__}, expected AgentConfig"
            raise TypeError(msg)

        if agent.user.id != user.id:
            logger.error(
                "get_agent: access denied - agent_id=%s owned by user_id=%s, requested by user_id=%s",
                agent_id,
                agent.user.id,
                user.id,
            )
            raise CMSError(f"Agent {agent_id} not found")

        if agent.deleted_at is not None:
            logger.error(
                "get_agent: agent_id=%s is deleted",
                agent_id,
            )
            raise CMSError(f"Agent {agent_id} not found")

        logger.debug(
            "get_agent returning agent_id=%s for user_id=%s",
            agent_id,
            user.id,
        )
        return agent

    except AgentConfig.DoesNotExist:
        logger.error("get_agent: agent_id=%s not found", agent_id)
        raise CMSError(f"Agent {agent_id} not found") from None
    except (TypeError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in get_agent for user_id=%s, agent_id=%s",
            user.id,
            agent_id,
        )
        raise


def get_allowed_extensions() -> list[str]:
    """Get list of allowed file extensions for agent uploads.

    Returns:
        List of allowed extensions (e.g., ['.msi', '.deb', '.rpm'])
    """
    from cms.assets.validation import get_allowed_extensions as _impl

    return _impl()
