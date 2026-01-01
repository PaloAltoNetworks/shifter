"""CMS asset management services.

This module handles agent (asset) management:
- get_storage_used: Calculate total storage used by a user's agents
- create_agent: Create a new agent record
- delete_agent: Soft delete an agent and remove from S3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Sum
from django.utils import timezone

from cms.models import AgentConfig, OperatingSystem
from management.models import ActivityLog
from mission_control.services.s3 import S3Error
from mission_control.services.s3 import delete_agent as s3_delete

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class AssetError(Exception):
    """Error raised when an asset operation fails."""


def get_storage_used(user: User) -> int:
    """Get total bytes used by a user's active agents.

    Args:
        user: The user to check storage for

    Returns:
        int: Total bytes used by active agents (0 if none)
    """
    result = AgentConfig.active_for_user(user).aggregate(total=Sum("file_size_bytes"))
    return result["total"] or 0


def create_agent(
    user: User,
    name: str,
    s3_key: str,
    filename: str,
    os_slug: str,
    file_size: int,
    sha256: str,
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
        sha256: SHA256 hash of the agent file
        upload_method: Optional upload method for logging (e.g., 'presigned')

    Returns:
        AgentConfig: The newly created agent record

    Raises:
        AssetError: If the operating system is not found
    """
    # Look up OS
    os_obj = OperatingSystem.objects.filter(slug=os_slug).first()
    if not os_obj:
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
    ActivityLog.log(
        "agent_uploaded",
        user=user,
        **log_metadata,
    )

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
    # Delete from S3 first - fail fast before touching DB
    try:
        s3_delete(agent.s3_key)
    except S3Error as e:
        raise AssetError(f"Failed to delete agent from storage: {e}") from e

    # Soft delete the database record
    agent.deleted_at = timezone.now()
    agent.save(update_fields=["deleted_at"])

    # Log activity
    ActivityLog.log(
        "agent_deleted",
        user=agent.user,
        agent_id=agent.id,
        agent_name=agent.name,
    )
