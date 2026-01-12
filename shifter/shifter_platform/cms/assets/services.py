"""CMS asset management services.

This module handles agent (asset) management:
- get_storage_used: Calculate total storage used by a user's agents
- create_agent: Create a new agent record
- delete_agent: Soft delete an agent and remove from S3
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db.models import Sum
from django.utils import timezone

from cms.assets.s3 import S3Error
from cms.assets.s3 import delete_agent as s3_delete
from cms.models import AgentConfig, OperatingSystem

# TODO: Layer violation - CMS should not import from management. See GH issue #469
from management.services import log_activity
from shared.exceptions import AssetError

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def get_storage_used(user: User) -> int:
    """Get total bytes used by a user's active agents.

    Args:
        user: The user to check storage for

    Returns:
        int: Total bytes used by active agents (0 if none)
    """
    result = AgentConfig.active_for_user(user).aggregate(total=Sum("file_size_bytes"))
    total = result["total"] or 0
    logger.debug("get_storage_used: user_id=%s total=%d bytes", user.id, total)
    return total


def create_agent(
    user: User,
    name: str,
    s3_key: str,
    filename: str,
    os_slug: str,
    file_size: int,
    sha256: str = "",
    upload_method: str | None = None,
) -> AgentConfig:
    """Create a new agent record.

    Args:
        user: The user who owns the agent
        name: Display name for the agent
        s3_key: S3 key where the agent file is stored
        filename: Original filename of the agent
        os_slug: Operating system slug (e.g., 'windows', 'linux-debian')
        file_size: Size of the agent file in bytes
        sha256: SHA256 hash of the agent file (optional, for future server-side compute)
        upload_method: Optional upload method for logging (e.g., 'presigned')

    Returns:
        AgentConfig: The newly created agent record

    Raises:
        AssetError: If the operating system is not found
    """
    logger.debug(
        "create_agent: user_id=%s name=%s os_slug=%s file_size=%d",
        user.id,
        name,
        os_slug,
        file_size,
    )

    # Look up OS
    os_obj = OperatingSystem.objects.filter(slug=os_slug).first()
    if not os_obj:
        logger.error("create_agent: OS not found os_slug=%s", os_slug)
        raise AssetError(f"Operating system '{os_slug}' not found")

    # Create database record
    agent = AgentConfig.objects.create(
        user=user,
        os=os_obj,
        name=name,
        s3_key=s3_key,
        original_filename=filename,
        file_size_bytes=file_size,
        sha256_hash=sha256,
    )

    # Build activity log metadata
    log_metadata = {
        "agent_id": agent.id,
        "agent_name": name,
        "filename": filename,
        "os": os_slug,
        "file_size": file_size,
    }
    if upload_method:
        log_metadata["upload_method"] = upload_method

    # Log activity
    log_activity(
        "agent_uploaded",
        user=user,
        **log_metadata,
    )

    logger.info("create_agent: success agent_id=%s user_id=%s", agent.id, user.id)
    return agent


def delete_agent(agent: AgentConfig) -> None:
    """Delete an agent (soft delete after removing from S3).

    Deletes the agent file from S3 first, then soft-deletes the database
    record. If S3 delete fails, the database record is not modified.

    Args:
        agent: The agent to delete

    Raises:
        AssetError: If S3 delete fails
    """
    logger.debug("delete_agent: agent_id=%s s3_key=%s", agent.id, agent.s3_key)

    # Delete from S3 first - fail fast before touching DB
    try:
        s3_delete(agent.s3_key)
    except S3Error as e:
        logger.error("delete_agent: S3 delete failed agent_id=%s error=%s", agent.id, e)
        raise AssetError(f"Failed to delete agent from storage: {e}") from e

    # Soft delete the database record
    agent.deleted_at = timezone.now()
    agent.save(update_fields=["deleted_at"])

    # Log activity
    log_activity(
        "agent_deleted",
        user=agent.user,
        agent_id=agent.id,
        agent_name=agent.name,
    )

    logger.info("delete_agent: success agent_id=%s", agent.id)
