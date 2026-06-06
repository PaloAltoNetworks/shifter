"""CMS asset management services.

This module handles agent (asset) management:
- get_storage_used: Calculate total storage used by a user's agents
- create_agent: Create a new agent record
- delete_agent: Soft delete an agent and remove from S3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Sum
from django.utils import timezone

from cms.assets.s3 import S3Error
from cms.assets.s3 import delete_agent as s3_delete
from cms.models import AgentConfig, AgentType, OperatingSystem
from risk_register.models import AuditLog
from risk_register.services import AuditEvent, audit_log
from shared.exceptions import AssetError
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentUploadSpec:
    """Agent file/metadata inputs for :func:`create_agent` (all but the owner).

    Groups the agent record's file and classification fields so create_agent
    takes a single cohesive object instead of a long positional parameter list.
    """

    name: str
    s3_key: str
    filename: str
    os_slug: str
    file_size: int
    sha256: str = ""
    upload_method: str | None = None
    agent_type: str = AgentType.XDR


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


def create_agent(user: User, spec: AgentUploadSpec) -> AgentConfig:
    """Create a new agent record.

    Args:
        user: The user who owns the agent
        spec: Agent file/metadata inputs (see :class:`AgentUploadSpec`)

    Returns:
        AgentConfig: The newly created agent record

    Raises:
        AssetError: If the operating system is not found or agent_type is invalid
    """
    name = spec.name
    s3_key = spec.s3_key
    filename = spec.filename
    os_slug = spec.os_slug
    file_size = spec.file_size
    sha256 = spec.sha256
    upload_method = spec.upload_method
    agent_type = spec.agent_type

    # Inline CR/LF stripping at the call site so CodeQL's ``py/log-injection``
    # taint tracker recognises the sanitization (routing through a helper
    # function loses the connection).
    safe_name = name.replace("\r", " ").replace("\n", " ").replace("\t", " ")[:200]
    safe_os_slug = os_slug.replace("\r", " ").replace("\n", " ").replace("\t", " ")[:200]
    safe_agent_type = agent_type.replace("\r", " ").replace("\n", " ").replace("\t", " ")[:200]
    logger.debug(
        "create_agent: user_id=%s name=%s os_slug=%s file_size=%d agent_type=%s",
        user.id,
        safe_name,
        safe_os_slug,
        file_size,
        safe_agent_type,
    )

    # Validate agent_type
    valid_types = {choice[0] for choice in AgentType.choices}
    if agent_type not in valid_types:
        logger.error("create_agent: Invalid agent_type=%s", safe_log_value(agent_type))
        raise AssetError(f"Invalid agent type '{agent_type}'")

    # Look up OS
    os_obj = OperatingSystem.objects.filter(slug=os_slug).first()
    if not os_obj:
        logger.error("create_agent: OS not found os_slug=%s", safe_log_value(os_slug))
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
        agent_type=agent_type,
    )

    # Audit log agent creation
    new_state = {
        "name": name,
        "os": os_slug,
        "filename": filename,
        "file_size": file_size,
        "agent_type": agent_type,
    }
    if upload_method:
        new_state["upload_method"] = upload_method

    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.AGENT,
            entity_id=agent.id,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state=new_state,
        )
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
    logger.debug("delete_agent: agent_id=%s s3_key=%s", agent.id, safe_log_value(agent.s3_key))

    # Delete from S3 first - fail fast before touching DB
    try:
        s3_delete(agent.s3_key)
    except S3Error as e:
        logger.error("delete_agent: S3 delete failed agent_id=%s error=%s", agent.id, e)
        raise AssetError(f"Failed to delete agent from storage: {e}") from e

    # Capture state before deletion
    previous_state = {
        "name": agent.name,
        "os": agent.os.slug,
    }

    # Soft delete the database record
    agent.deleted_at = timezone.now()
    agent.save(update_fields=["deleted_at"])

    # Audit log agent deletion
    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.AGENT,
            entity_id=agent.id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=agent.user.id,
            previous_state=previous_state,
        )
    )

    logger.info("delete_agent: success agent_id=%s", agent.id)
