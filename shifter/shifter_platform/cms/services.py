"""CMS service interface.

Content and asset management for Shifter platform.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from cms.assets.services import create_agent as assets_create_agent
from cms.assets.services import delete_agent as assets_delete_agent
from cms.assets.validation import get_allowed_extensions as _get_allowed_extensions
from cms.exceptions import CMSError
from cms.models import AgentConfig, RangeInstance
from engine import cancel_range as engine_cancel_range
from engine import create_range as engine_create_range
from engine import destroy_range as engine_destroy_range
from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED
from shared.enums import ACTIVE_STATUSES, TERMINAL_STATUSES, ResourceStatus

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import NGFW
    from shared.schemas.app import LinkedRangeContext, NGFWAppContext, NGFWAppRef
    from shared.schemas.credentials import CredentialContext, CredentialRef
    from shared.schemas.range import RangeContext

logger = logging.getLogger(__name__)


# =============================================================================
# Agents
# =============================================================================


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
    # Input validation - user
    if user is None:
        logger.error("create_agent called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "create_agent called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("create_agent called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    logger.debug("create_agent called for user_id=%s", user.id)

    try:
        agent = assets_create_agent(user=user, **kwargs)

        # Validate response from assets service
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
            msg = (
                f"Assets service returned {type(agent).__name__}, expected AgentConfig"
            )
            raise TypeError(msg)

        logger.debug(
            "create_agent returning agent_id=%s for user_id=%s",
            agent.id,
            user.id,
        )
        return agent

    except TypeError:
        # Re-raise TypeErrors (our validation errors)
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
    # Input validation - user
    if user is None:
        logger.error("delete_agent called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "delete_agent called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("delete_agent called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - agent_id
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
        # Get agent (also verifies ownership and not deleted)
        agent = get_agent(user, agent_id)

        # Delete via assets service
        assets_delete_agent(agent)

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
        List of agent dicts with keys: id, name, os_name, os_slug, file_size_mb

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
    """
    # Input validation
    if user is None:
        logger.error("list_agents called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "list_agents called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("list_agents called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    logger.debug("list_agents called for user_id=%s", user.id)

    try:
        result = AgentConfig.active_for_user(user).select_related("os")

        # Validate response from model
        if result is None:
            logger.error(
                "list_agents: model returned None for user_id=%s",
                user.id,
            )
            raise TypeError("Model returned None instead of iterable")

        # Convert to projection dicts with validation
        agents = []
        for agent in result:
            # Validate agent has required attributes
            has_id = hasattr(agent, "id")
            has_name = hasattr(agent, "name")
            has_os = hasattr(agent, "os")
            if not (has_id and has_name and has_os):
                logger.error(
                    "list_agents: invalid agent object in result for user_id=%s",
                    user.id,
                )
                raise TypeError("Model returned invalid agent object")

            agent_dict = {
                "id": agent.id,
                "name": agent.name,
                "os_name": agent.os.name,
                "os_slug": agent.os.slug,
                "file_size_mb": agent.file_size_mb,
                "original_filename": agent.original_filename,
                "created_at": agent.created_at,
            }

            # Validate dict values are non-empty and correct types
            if not isinstance(agent_dict["id"], int):
                logger.error(
                    "list_agents: agent.id is not int for user_id=%s",
                    user.id,
                )
                raise TypeError("agent.id must be int")
            if not isinstance(agent_dict["name"], str) or not agent_dict["name"]:
                logger.error(
                    "list_agents: agent.name is not non-empty str for user_id=%s",
                    user.id,
                )
                raise TypeError("agent.name must be non-empty str")
            if not isinstance(agent_dict["os_name"], str) or not agent_dict["os_name"]:
                logger.error(
                    "list_agents: agent.os.name is not non-empty str for user_id=%s",
                    user.id,
                )
                raise TypeError("agent.os.name must be non-empty str")
            if not isinstance(agent_dict["os_slug"], str) or not agent_dict["os_slug"]:
                logger.error(
                    "list_agents: agent.os.slug is not non-empty str for user_id=%s",
                    user.id,
                )
                raise TypeError("agent.os.slug must be non-empty str")
            if not isinstance(agent_dict["file_size_mb"], (int, float)):
                logger.error(
                    "list_agents: agent.file_size_mb is not number for user_id=%s",
                    user.id,
                )
                raise TypeError("agent.file_size_mb must be number")
            if (
                not isinstance(agent_dict["original_filename"], str)
                or not agent_dict["original_filename"]
            ):
                logger.error(
                    "list_agents: agent.original_filename is not non-empty str for user_id=%s",
                    user.id,
                )
                msg = "agent.original_filename must be non-empty str"
                raise TypeError(msg)
            if agent_dict["created_at"] is None:
                logger.error(
                    "list_agents: agent.created_at is None for user_id=%s",
                    user.id,
                )
                raise TypeError("agent.created_at must not be None")

            agents.append(agent_dict)

        logger.debug(
            "list_agents returning %d agents for user_id=%s",
            len(agents),
            user.id,
        )
        return agents

    except TypeError:
        # Re-raise TypeErrors (our validation errors)
        raise
    except Exception:
        logger.exception(
            "Error in list_agents for user_id=%s",
            user.id,
        )
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
    from cms.exceptions import CMSError

    # Input validation - user
    if user is None:
        logger.error("get_agent called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "get_agent called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("get_agent called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - agent_id
    if agent_id is None:
        logger.error(
            "get_agent called with None agent_id for user_id=%s",
            user.id,
        )
        raise TypeError("agent_id cannot be None")

    if not isinstance(agent_id, int):
        logger.error(
            "get_agent called with invalid agent_id type: %s",
            type(agent_id).__name__,
        )
        msg = f"agent_id must be an int, got {type(agent_id).__name__}"
        raise TypeError(msg)

    if agent_id < 0:
        logger.error(
            "get_agent called with negative agent_id=%s for user_id=%s",
            agent_id,
            user.id,
        )
        raise ValueError("agent_id must be non-negative")

    logger.debug(
        "get_agent called for user_id=%s, agent_id=%s",
        user.id,
        agent_id,
    )

    try:
        agent = AgentConfig.objects.get(id=agent_id)

        # Validate response from model
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

        # Check ownership
        if agent.user.id != user.id:
            logger.error(
                "get_agent: access denied - agent_id=%s owned by user_id=%s, requested by user_id=%s",
                agent_id,
                agent.user.id,
                user.id,
            )
            raise CMSError(f"Agent {agent_id} not found")

        # Check soft deletion
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
        # Re-raise TypeErrors and CMSErrors
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
    return _get_allowed_extensions()


# =============================================================================
# Credentials
# =============================================================================


def create_credential(
    user: User, credential_type_slug: str, **kwargs: Any
) -> CredentialRef:
    """Create credential (SCM or deployment profile).

    Args:
        user: User who will own the credential
        credential_type_slug: Type slug ('scm' or 'deployment_profile')
        **kwargs: Type-specific fields:
            For 'scm':
                - name: Display name for the credential
                - scm_folder_name: SCM folder name
                - scm_pin_id: SCM PIN ID
                - scm_pin_value: SCM PIN value (stored in data JSON)
                - sls_region: SLS region
            For 'deployment_profile':
                - name: Display name for the credential
                - authcode: Deployment authcode (stored in data JSON)

    Returns:
        CredentialRef: Minimal reference to the created credential

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved) or credential_type_slug is invalid
        CMSError: If credential type not found
    """
    from cms.models import Credential, CredentialType
    from shared.schemas import CredentialRef

    # Input validation - user
    if user is None:
        logger.error("create_credential called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "create_credential called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("create_credential called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - credential_type_slug
    if credential_type_slug is None:
        logger.error(
            "create_credential called with None credential_type_slug for user_id=%s",
            user.id,
        )
        raise ValueError("credential_type_slug cannot be None")

    logger.debug(
        "create_credential called for user_id=%s, credential_type_slug=%s",
        user.id,
        credential_type_slug,
    )

    try:
        # Get credential type from catalog
        try:
            cred_type = CredentialType.objects.get(slug=credential_type_slug)
        except CredentialType.DoesNotExist:
            logger.error(
                "create_credential: credential type '%s' not found for user_id=%s",
                credential_type_slug,
                user.id,
            )
            raise CMSError(
                f"Credential type '{credential_type_slug}' not found"
            ) from None

        # Extract name and type-specific data
        name = kwargs.pop("name", None)
        if not name:
            raise ValueError("name is required")

        expires_at = kwargs.pop("expires_at", None)

        # Apply defaults for SCM credentials
        if credential_type_slug == "scm" and not kwargs.get("scm_folder_name"):
            kwargs["scm_folder_name"] = "All Firewalls"

        # Remaining kwargs go into the data JSON field
        data = kwargs

        # Create credential
        credential = Credential(
            user=user,
            name=name,
            credential_type=cred_type,
            data=data,
            expires_at=expires_at,
        )
        credential.full_clean()
        credential.save()

        logger.debug(
            "create_credential created credential_id=%s, credential_type=%s for user_id=%s",
            credential.id,
            credential_type_slug,
            user.id,
        )

        # Return minimal CredentialRef (no secrets exposed)
        return CredentialRef(
            credential_id=credential.id,
            user_id=user.id,
            is_deleted=False,
        )

    except (CMSError, ValueError):
        raise
    except Exception:
        logger.exception(
            "Error in create_credential for user_id=%s, credential_type_slug=%s",
            user.id,
            credential_type_slug,
        )
        raise


def delete_credential(user: User, credential_id: int) -> CredentialRef:
    """Soft delete credential.

    Verifies ownership, then performs soft delete.

    Args:
        user: User requesting deletion
        credential_id: ID of the credential to delete

    Returns:
        CredentialRef: Reference to the deleted credential

    Raises:
        TypeError: If user is None, invalid type, or credential_id is
            invalid type
        ValueError: If user has no ID (unsaved) or credential_id is
            invalid
        CMSError: If credential not found or not owned by user
    """
    from cms.models import Credential
    from shared.schemas import CredentialRef

    # Input validation - user
    if user is None:
        logger.error("delete_credential called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "delete_credential called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("delete_credential called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - credential_id
    if credential_id is None:
        logger.error(
            "delete_credential called with None credential_id for user_id=%s",
            user.id,
        )
        raise TypeError("credential_id cannot be None")

    if not isinstance(credential_id, int):
        logger.error(
            "delete_credential called with invalid credential_id type: %s",
            type(credential_id).__name__,
        )
        msg = f"credential_id must be an int, got {type(credential_id).__name__}"
        raise TypeError(msg)

    if credential_id < 0:
        logger.error(
            "delete_credential called with negative credential_id=%s for user_id=%s",
            credential_id,
            user.id,
        )
        raise ValueError("credential_id must be non-negative")

    logger.debug(
        "delete_credential called for user_id=%s, credential_id=%s",
        user.id,
        credential_id,
    )

    try:
        # Get credential directly (verify ownership and not deleted)
        try:
            credential = Credential.objects.get(
                id=credential_id,
                user=user,
                deleted_at__isnull=True,
            )
        except Credential.DoesNotExist:
            logger.error(
                "delete_credential: credential_id=%s not found for user_id=%s",
                credential_id,
                user.id,
            )
            raise CMSError(f"Credential {credential_id} not found") from None

        # Soft delete
        credential.deleted_at = timezone.now()
        credential.save(update_fields=["deleted_at"])

        logger.debug(
            "delete_credential completed for credential_id=%s, user_id=%s",
            credential_id,
            user.id,
        )

        return CredentialRef(
            credential_id=credential_id,
            user_id=user.id,
            is_deleted=True,
        )

    except CMSError:
        raise
    except Exception:
        logger.exception(
            "Error in delete_credential for user_id=%s, credential_id=%s",
            user.id,
            credential_id,
        )
        raise


def list_credentials(user: User) -> list[CredentialContext]:
    """Get user's credentials as CredentialContext projections.

    Returns type-specific context objects (SCMCredentialContext or
    DeploymentProfileContext) that exclude sensitive data like secrets.

    Args:
        user: User whose credentials to retrieve

    Returns:
        List of CredentialContext instances (discriminated union)

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
    """
    from cms.models import Credential
    from shared.schemas import (
        DeploymentProfileContext,
        SCMCredentialContext,
    )

    # Input validation
    if user is None:
        logger.error("list_credentials called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "list_credentials called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("list_credentials called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    logger.debug("list_credentials called for user_id=%s", user.id)

    try:
        credentials = (
            Credential.objects.filter(
                user=user,
                deleted_at__isnull=True,
            )
            .select_related("credential_type")
            .order_by("-created_at")
        )

        # Convert to CredentialContext projections
        contexts: list[CredentialContext] = []
        for cred in credentials:
            type_slug = cred.credential_type.slug

            ctx: SCMCredentialContext | DeploymentProfileContext
            if type_slug == "scm":
                ctx = SCMCredentialContext(
                    credential_id=cred.id,
                    name=cred.name,
                    user_id=cred.user_id,
                    created_at=cred.created_at,
                    expires_at=cred.expires_at,
                    is_deleted=cred.is_deleted,
                    scm_folder_name=cred.data.get("scm_folder_name", ""),
                    scm_pin_id=cred.data.get("scm_pin_id", ""),
                    sls_region=cred.data.get("sls_region", ""),
                )
            elif type_slug == "deployment_profile":
                # Mask authcode for display
                authcode = cred.data.get("authcode", "")
                authcode_masked = f"{authcode[:5]}***" if len(authcode) >= 5 else "***"
                ctx = DeploymentProfileContext(
                    credential_id=cred.id,
                    name=cred.name,
                    user_id=cred.user_id,
                    created_at=cred.created_at,
                    expires_at=cred.expires_at,
                    is_deleted=cred.is_deleted,
                    authcode_masked=authcode_masked,
                )
            else:
                logger.warning(
                    "list_credentials: unknown credential type '%s' for credential_id=%s",
                    type_slug,
                    cred.id,
                )
                continue

            contexts.append(ctx)

        logger.debug(
            "list_credentials returning %d credentials for user_id=%s",
            len(contexts),
            user.id,
        )
        return contexts

    except Exception:
        logger.exception(
            "Error in list_credentials for user_id=%s",
            user.id,
        )
        raise


def get_credential(user: User, credential_id: int) -> CredentialContext:
    """Get single credential by ID as CredentialContext projection.

    Returns type-specific context (SCMCredentialContext or
    DeploymentProfileContext) that excludes sensitive data.

    Args:
        user: User requesting the credential
        credential_id: ID of the credential to retrieve

    Returns:
        CredentialContext: Type-specific context projection

    Raises:
        TypeError: If user is None, invalid type, or credential_id is
            invalid type
        ValueError: If user has no ID (unsaved) or credential_id is
            invalid
        CMSError: If credential not found, not owned by user, or
            deleted
    """
    from cms.models import Credential
    from shared.schemas import DeploymentProfileContext, SCMCredentialContext

    # Input validation - user
    if user is None:
        logger.error("get_credential called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "get_credential called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("get_credential called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - credential_id
    if credential_id is None:
        logger.error(
            "get_credential called with None credential_id for user_id=%s",
            user.id,
        )
        raise TypeError("credential_id cannot be None")

    if not isinstance(credential_id, int):
        logger.error(
            "get_credential called with invalid credential_id type: %s",
            type(credential_id).__name__,
        )
        msg = f"credential_id must be an int, got {type(credential_id).__name__}"
        raise TypeError(msg)

    if credential_id < 0:
        logger.error(
            "get_credential called with negative credential_id=%s for user_id=%s",
            credential_id,
            user.id,
        )
        raise ValueError("credential_id must be non-negative")

    logger.debug(
        "get_credential called for user_id=%s, credential_id=%s",
        user.id,
        credential_id,
    )

    try:
        cred = Credential.objects.select_related("credential_type").get(
            id=credential_id,
            user=user,
            deleted_at__isnull=True,
        )
    except Credential.DoesNotExist:
        logger.error(
            "get_credential: credential_id=%s not found for user_id=%s",
            credential_id,
            user.id,
        )
        raise CMSError(f"Credential {credential_id} not found") from None

    try:
        type_slug = cred.credential_type.slug

        ctx: SCMCredentialContext | DeploymentProfileContext
        if type_slug == "scm":
            ctx = SCMCredentialContext(
                credential_id=cred.id,
                name=cred.name,
                user_id=cred.user_id,
                created_at=cred.created_at,
                expires_at=cred.expires_at,
                is_deleted=cred.is_deleted,
                scm_folder_name=cred.data.get("scm_folder_name", ""),
                scm_pin_id=cred.data.get("scm_pin_id", ""),
                sls_region=cred.data.get("sls_region", ""),
            )
        elif type_slug == "deployment_profile":
            # Mask authcode for display
            authcode = cred.data.get("authcode", "")
            authcode_masked = f"{authcode[:5]}***" if len(authcode) >= 5 else "***"
            ctx = DeploymentProfileContext(
                credential_id=cred.id,
                name=cred.name,
                user_id=cred.user_id,
                created_at=cred.created_at,
                expires_at=cred.expires_at,
                is_deleted=cred.is_deleted,
                authcode_masked=authcode_masked,
            )
        else:
            logger.error(
                "get_credential: unknown credential type '%s' for credential_id=%s",
                type_slug,
                credential_id,
            )
            raise CMSError(f"Unknown credential type: {type_slug}")

        logger.debug(
            "get_credential returning credential_id=%s for user_id=%s",
            credential_id,
            user.id,
        )
        return ctx

    except CMSError:
        raise
    except Exception:
        logger.exception(
            "Error in get_credential for user_id=%s, credential_id=%s",
            user.id,
            credential_id,
        )
        raise


# =============================================================================
# Ranges
# =============================================================================


def list_ranges(user: User) -> list[RangeInstance]:
    """Get user's range instances.

    Args:
        user: User whose range instances to retrieve

    Returns:
        List of RangeInstance instances belonging to the user

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
    """
    # Input validation
    if user is None:
        logger.error("list_ranges called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "list_ranges called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("list_ranges called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    logger.debug("list_ranges called for user_id=%s", user.id)

    try:
        result = RangeInstance.objects.filter(user_id=user.id)

        # Validate response from model
        if result is None:
            logger.error(
                "list_ranges: model returned None for user_id=%s",
                user.id,
            )
            raise TypeError("Model returned None instead of iterable")

        # Convert to list (handles QuerySet, tuple, generator)
        ranges = list(result)

        # Validate list contents
        for item in ranges:
            if not isinstance(item, RangeInstance):
                logger.error(
                    "list_ranges: model returned invalid item type %s for user_id=%s",
                    type(item).__name__,
                    user.id,
                )
                msg = f"Model returned list containing {type(item).__name__}, expected RangeInstance"
                raise TypeError(msg)

        logger.debug(
            "list_ranges returning %d ranges for user_id=%s",
            len(ranges),
            user.id,
        )
        return ranges

    except TypeError:
        # Re-raise TypeErrors (our validation errors)
        raise
    except Exception:
        logger.exception("Error in list_ranges for user_id=%s", user.id)
        raise


def get_range(user: User, range_id: int) -> RangeInstance:
    """Get single range instance by range ID.

    Args:
        user: User requesting the range instance
        range_id: ID of the range to retrieve

    Returns:
        RangeInstance if found and owned by user

    Raises:
        TypeError: If user is None, invalid type, or range_id is invalid type
        ValueError: If user has no ID (unsaved) or range_id is invalid
        CMSError: If range not found or not owned by user
    """
    from cms.exceptions import CMSError

    # Input validation - user
    if user is None:
        logger.error("get_range called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "get_range called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("get_range called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - range_id
    if range_id is None:
        logger.error(
            "get_range called with None range_id for user_id=%s",
            user.id,
        )
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error(
            "get_range called with invalid range_id type: %s",
            type(range_id).__name__,
        )
        msg = f"range_id must be an int, got {type(range_id).__name__}"
        raise TypeError(msg)

    if range_id < 0:
        logger.error(
            "get_range called with negative range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        raise ValueError("range_id must be non-negative")

    logger.debug(
        "get_range called for user_id=%s, range_id=%s",
        user.id,
        range_id,
    )

    try:
        range_obj = RangeInstance.objects.get(range_id=range_id)

        # Validate response from model
        if range_obj is None:
            logger.error(
                "get_range: model returned None for range_id=%s",
                range_id,
            )
            msg = "Model returned None instead of RangeInstance"
            raise TypeError(msg)

        if not isinstance(range_obj, RangeInstance):
            logger.error(
                "get_range: model returned invalid type %s for range_id=%s",
                type(range_obj).__name__,
                range_id,
            )
            msg = f"Model returned {type(range_obj).__name__}, expected RangeInstance"
            raise TypeError(msg)

        # Check ownership
        if range_obj.user_id != user.id:
            logger.error(
                "get_range: access denied - range_id=%s owned by user_id=%s, requested by user_id=%s",
                range_id,
                range_obj.user_id,
                user.id,
            )
            raise CMSError(f"Range {range_id} not found")

        logger.debug(
            "get_range returning range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        return range_obj

    except RangeInstance.DoesNotExist:
        logger.error("get_range: range_id=%s not found", range_id)
        raise CMSError(f"Range {range_id} not found") from None
    except (TypeError, CMSError):
        # Re-raise TypeErrors and CMSErrors
        raise
    except Exception:
        logger.exception(
            "Error in get_range for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise


def get_active_range(user: User) -> RangeContext | None:
    """Get user's active (non-deleted) range as a RangeContext projection.

    Returns the most recently created range that:
    - Belongs to the user
    - Is not soft-deleted (deleted_at is None)

    Note: Terminal statuses (DESTROYED, FAILED) automatically set deleted_at
    via RangeInstance.save(), so filtering by deleted_at is sufficient.

    Used by Mission Control to check if user has an active range.
    Returns a RangeContext rather than raw model to:
    - Provide only the essential identifiers (range_id, user_id, status)
    - Validate data before returning to caller
    - Hide implementation details from presentation layer

    Args:
        user: User whose active range to retrieve

    Returns:
        RangeContext if user has an active range, None otherwise

    Raises:
        TypeError: If user is None or invalid type
        ValidationError: If RangeContext creation fails validation
        Exception: Database errors are logged and propagated
    """
    from shared.schemas import RangeContext

    # Input validation
    if user is None:
        logger.error("get_active_range called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "get_active_range called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    logger.debug("get_active_range called for user_id=%s", user.id)

    try:
        # Query for active ranges (non-deleted)
        # Exclude DESTROYING status - user can create new range while old one tears down
        from shared.enums import ResourceStatus

        instance = (
            RangeInstance.active.filter(user_id=user.id)
            .exclude(status=ResourceStatus.DESTROYING.value)
            .order_by("-created_at")
            .first()
        )
    except TypeError:
        # Re-raise TypeErrors (shouldn't happen but be defensive)
        raise
    except Exception:
        logger.exception("Error in get_active_range for user_id=%s", user.id)
        raise

    if instance:
        logger.debug(
            "get_active_range found range_id=%s status=%s for user_id=%s",
            instance.range_id,
            instance.status,
            user.id,
        )
        from shared.enums import ResourceStatus
        from shared.schemas import InstanceContext

        # Get instance data from stored range_spec
        instance_contexts = []
        if instance.range_spec and "instances" in instance.range_spec:
            instance_contexts = [
                InstanceContext(
                    uuid=spec.get("uuid"),
                    role=spec["role"],
                    os_type=spec["os_type"],
                    join_domain=spec.get("join_domain", False),
                )
                for spec in instance.range_spec["instances"]
            ]

        # Get agent_name from FK if exists
        agent_name = instance.agent.name if instance.agent else None

        return RangeContext(
            range_id=instance.range_id,
            scenario_id=instance.scenario_id,
            user_id=instance.user_id,
            status=ResourceStatus(instance.status),
            instances=instance_contexts,
            agent_name=agent_name,
        )
    else:
        logger.debug(
            "get_active_range found no active range for user_id=%s",
            user.id,
        )
        return None


def create_range(
    user: User, scenario: str, agent_id: int, ngfw_enabled: bool = False
) -> RangeContext:
    """Validate, hydrate, and trigger range provisioning.

    CMS validates scenario and agent requirements, hydrates the scenario
    template with agent details, calls Engine, and stores RangeInstance.

    Args:
        user: User requesting the range
        scenario: Scenario ID (basic, ad_attack_lab)
        agent_id: ID of the agent to use for victim instances
        ngfw_enabled: Whether to deploy VM-Series NGFW inline

    Returns:
        RangeContext: Template-safe projection of the created range

    Raises:
        TypeError: If user is None, invalid type, or parameters are
            invalid
        ValueError: If user has no ID (unsaved) or parameters are
            invalid
        CMSError: If scenario not found, agent not found, or
            requirements not met
    """
    from cms.exceptions import CMSError
    from cms.models import RangeInstance
    from cms.scenarios.hydrator import hydrate_scenario

    # Input validation - user
    if user is None:
        logger.error("create_range called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "create_range called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("create_range called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - scenario
    if scenario is None:
        logger.error(
            "create_range called with None scenario for user_id=%s",
            user.id,
        )
        raise ValueError("scenario cannot be None")

    if not isinstance(scenario, str) or not scenario:
        logger.error(
            "create_range called with invalid scenario '%s' for user_id=%s",
            scenario,
            user.id,
        )
        raise ValueError("scenario must be a non-empty string")

    # Input validation - agent_id
    if agent_id is None:
        logger.error(
            "create_range called with None agent_id for user_id=%s",
            user.id,
        )
        raise TypeError("agent_id cannot be None")

    if not isinstance(agent_id, int):
        logger.error(
            "create_range called with invalid agent_id type: %s",
            type(agent_id).__name__,
        )
        msg = f"agent_id must be an int, got {type(agent_id).__name__}"
        raise TypeError(msg)

    if agent_id < 0:
        logger.error(
            "create_range called with negative agent_id=%s for user_id=%s",
            agent_id,
            user.id,
        )
        raise ValueError("agent_id must be non-negative")

    logger.debug(
        "create_range called for user_id=%s, scenario=%s, agent_id=%s, ngfw_enabled=%s",
        user.id,
        scenario,
        agent_id,
        ngfw_enabled,
    )

    try:
        # 0. Check user doesn't already have an active range
        existing = get_active_range(user)
        if existing:
            logger.warning(
                "create_range: user_id=%s already has active range_id=%s",
                user.id,
                existing.range_id,
            )
            msg = "You already have an active range. Please destroy it before creating a new one."
            raise CMSError(msg)

        # 1. Validate scenario exists
        try:
            get_scenario(scenario)
        except CMSError:
            logger.error(
                "create_range: scenario '%s' not found for user_id=%s",
                scenario,
                user.id,
            )
            raise

        # 2. Get agent (validates ownership and not deleted)
        agent = get_agent(user, agent_id)

        # 3. Validate agent meets scenario requirements
        validate_scenario_requirements(scenario, agent)

        # 4. Hydrate scenario with agent details
        range_request = hydrate_scenario(scenario, user.id, agent)

        # 5. Call engine to create range
        range_id = engine_create_range(range_request)

        # 6. Store RangeInstance record with hydrated spec
        RangeInstance.objects.create(
            range_id=range_id,
            scenario_id=scenario,
            user_id=user.id,
            agent=agent,
            range_spec=range_request.model_dump(mode="json"),
        )

        logger.debug(
            "create_range completed: range_id=%s, scenario=%s, user_id=%s",
            range_id,
            scenario,
            user.id,
        )

        # 7. Return RangeContext projection with instances
        # Engine always sets PROVISIONING status on creation
        from shared.enums import ResourceStatus
        from shared.schemas import InstanceContext, RangeContext

        instance_contexts = [
            InstanceContext(
                uuid=spec.uuid,
                role=spec.role,
                os_type=spec.os_type,
                join_domain=spec.join_domain,
            )
            for spec in range_request.instances
        ]

        return RangeContext(
            range_id=range_id,
            scenario_id=scenario,
            user_id=user.id,
            status=ResourceStatus.PROVISIONING,
            instances=instance_contexts,
            agent_name=agent.name,
        )

    except (TypeError, ValueError, CMSError):
        # Re-raise known errors
        raise
    except Exception:
        logger.exception("Error in create_range for user_id=%s", user.id)
        raise


def destroy_range(user: User, range_id: int) -> None:
    """Tear down range.

    Fetches RangeInstance, verifies ownership, updates CMS status to DESTROYING,
    then delegates to engine.services.destroy_range with RangeContext.

    Args:
        user: User requesting destruction
        range_id: ID of the range to destroy

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or range_id is invalid type
        ValueError: If user has no ID (unsaved) or range_id is invalid
        CMSError: If range not found or not owned by user
        EngineError: If engine fails to destroy range
    """
    from shared.schemas import RangeContext

    # Input validation - user
    if user is None:
        logger.error("destroy_range called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "destroy_range called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("destroy_range called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - range_id
    if range_id is None:
        logger.error(
            "destroy_range called with None range_id for user_id=%s",
            user.id,
        )
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error(
            "destroy_range called with invalid range_id type: %s",
            type(range_id).__name__,
        )
        msg = f"range_id must be an int, got {type(range_id).__name__}"
        raise TypeError(msg)

    if range_id < 0:
        logger.error(
            "destroy_range called with negative range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        raise ValueError("range_id must be non-negative")

    logger.debug(
        "destroy_range called for user_id=%s, range_id=%s",
        user.id,
        range_id,
    )

    # Fetch range instance directly and verify ownership
    try:
        instance = RangeInstance.objects.get(range_id=range_id)
    except RangeInstance.DoesNotExist:
        logger.warning(
            "destroy_range: range not found for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise CMSError(f"Range {range_id} not found") from None

    # Verify ownership
    if instance.user_id != user.id:
        logger.error(
            "destroy_range: access denied - range_id=%s owned by user_id=%s, requested by user_id=%s",
            range_id,
            instance.user_id,
            user.id,
        )
        raise CMSError(f"Range {range_id} not found")

    try:
        # Update CMS status to DESTROYING and soft delete immediately
        # This allows user to create a new range without waiting for teardown
        instance.status = ResourceStatus.DESTROYING.value
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["status", "deleted_at"])

        range_ctx = RangeContext(
            range_id=instance.range_id,
            scenario_id=instance.scenario_id,
            user_id=instance.user_id,
            status=ResourceStatus(instance.status),
            instances=[],
            agent_name=instance.agent.name if instance.agent else None,
        )
        engine_destroy_range(range_ctx)

        logger.debug(
            "destroy_range completed for range_id=%s, user_id=%s",
            range_id,
            user.id,
        )

    except (TypeError, ValueError, CMSError):
        # Re-raise known errors
        raise
    except Exception:
        logger.exception(
            "Error in destroy_range for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise


def cancel_range(user: User, range_id: int) -> None:
    """Cancel provisioning range.

    Verifies ownership via get_range, then delegates to
    engine.orchestration.cancel().

    Args:
        user: User requesting cancellation
        range_id: ID of the range to cancel

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or range_id is invalid type
        ValueError: If user has no ID (unsaved) or range_id is invalid
        CMSError: If range not found or not owned by user
        OrchestrationError: If range not in cancellable status
    """
    from shared.schemas import RangeContext

    # Input validation - user
    if user is None:
        logger.error("cancel_range called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "cancel_range called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("cancel_range called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - range_id
    if range_id is None:
        logger.error(
            "cancel_range called with None range_id for user_id=%s",
            user.id,
        )
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error(
            "cancel_range called with invalid range_id type: %s",
            type(range_id).__name__,
        )
        msg = f"range_id must be an int, got {type(range_id).__name__}"
        raise TypeError(msg)

    if range_id < 0:
        logger.error(
            "cancel_range called with negative range_id=%s for user_id=%s",
            range_id,
            user.id,
        )
        raise ValueError("range_id must be non-negative")

    logger.debug(
        "cancel_range called for user_id=%s, range_id=%s",
        user.id,
        range_id,
    )

    instance = None

    try:
        # Get range instance (verifies ownership and captures current
        # status)
        instance = get_range(user, range_id)
        if instance is None:
            logger.warning(
                "cancel_range: range not found for user_id=%s, range_id=%s",
                user.id,
                range_id,
            )
            raise CMSError("Range not found")
    except (TypeError, ValueError, CMSError):
        logger.error(
            "cancel_range: user and range mismatch for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise

    try:
        # Update CMS status to DESTROYED (CMS is authoritative)
        # save() triggers invariant: terminal status auto-sets deleted_at
        instance.status = ResourceStatus.DESTROYED.value
        instance.save(update_fields=["status"])
        if instance.status != ResourceStatus.DESTROYED.value:
            raise CMSError("Range status not updated to DESTROYED")

        range_ctx = RangeContext(
            range_id=instance.range_id,
            scenario_id=instance.scenario_id,
            user_id=instance.user_id,
            status=ResourceStatus(instance.status),
            instances=[],
            agent_name=instance.agent.name if instance.agent else None,
        )
        engine_cancel_range(range_ctx)
    except (TypeError, ValueError, CMSError):
        # Re-raise known errors
        raise
    except Exception:
        logger.exception(
            "Error in cancel_range for user_id=%s, range_id=%s",
            user.id,
            range_id,
        )
        raise


def pause_range(user: User, range_id: int) -> None:
    """Pause range.

    Note: Deferred feature - not implemented in current scope.
    """
    raise NotImplementedError("pause_range is not yet implemented")


def resume_range(user: User, range_id: int) -> None:
    """Resume range.

    Note: Deferred feature - not implemented in current scope.
    """
    raise NotImplementedError("resume_range is not yet implemented")


# =============================================================================
# Uploads
# =============================================================================


def initiate_upload(
    user: User, name: str, filename: str, file_size: int
) -> dict[str, Any]:
    """Validate and generate presigned URL for direct S3 upload.

    Validates user quota, file extension, and generates all components needed
    for the client to upload directly to S3.

    Args:
        user: User initiating the upload
        name: Display name for the agent
        filename: Original filename (used for extension validation)
        file_size: Expected file size in bytes

    Returns:
        Dict containing:
            - presigned_url: URL for PUT request to S3
            - s3_key: S3 key where file will be uploaded
            - upload_token: Signed token for completion verification
            - expected_os: Operating system slug from file extension

    Raises:
        TypeError: If user is None, invalid type, or file_size is
            invalid type
        ValueError: If user is unsaved, name/filename is empty, or
            file_size is invalid
        CMSError: If quota exceeded, invalid extension, or S3 error
    """
    from django.conf import settings

    from cms.assets.s3 import S3Error, generate_presigned_upload_url
    from cms.assets.services import get_storage_used
    from cms.assets.upload_token import generate_upload_token
    from cms.assets.validation import ValidationError, validate_file_extension
    from cms.exceptions import CMSError

    # Input validation - user
    if user is None:
        logger.error("initiate_upload called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "initiate_upload called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("initiate_upload called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - name
    if name is None:
        logger.error(
            "initiate_upload called with None name for user_id=%s",
            user.id,
        )
        raise ValueError("name cannot be None")

    name = name.strip()
    if not name:
        logger.error(
            "initiate_upload called with empty name for user_id=%s",
            user.id,
        )
        raise ValueError("name cannot be empty")

    # Input validation - filename
    if filename is None:
        logger.error(
            "initiate_upload called with None filename for user_id=%s",
            user.id,
        )
        raise ValueError("filename cannot be None")

    filename = filename.strip()
    if not filename:
        logger.error(
            "initiate_upload called with empty filename for user_id=%s",
            user.id,
        )
        raise ValueError("filename cannot be empty")

    # Input validation - file_size
    if file_size is None:
        logger.error(
            "initiate_upload called with None file_size for user_id=%s",
            user.id,
        )
        raise TypeError("file_size cannot be None")

    if not isinstance(file_size, int):
        logger.error(
            "initiate_upload called with invalid file_size type: %s",
            type(file_size).__name__,
        )
        msg = f"file_size must be an int, got {type(file_size).__name__}"
        raise TypeError(msg)

    if file_size <= 0:
        logger.error(
            "initiate_upload called with invalid file_size=%s for user_id=%s",
            file_size,
            user.id,
        )
        raise ValueError("file_size must be positive")

    logger.debug(
        "initiate_upload called for user_id=%s, filename=%s, file_size=%s",
        user.id,
        filename,
        file_size,
    )

    try:
        # Check storage quota
        current_usage = get_storage_used(user)
        quota_bytes = settings.AGENT_USER_STORAGE_QUOTA_MB * 1024 * 1024
        if current_usage + file_size > quota_bytes:
            available_mb = (quota_bytes - current_usage) / 1024 / 1024
            logger.error(
                "initiate_upload: quota exceeded for user_id=%s - current=%s, requested=%s, quota=%s",
                user.id,
                current_usage,
                file_size,
                quota_bytes,
            )
            msg = (
                f"Storage quota exceeded. You have {available_mb:.1f} MB "
                f"available of {settings.AGENT_USER_STORAGE_QUOTA_MB} "
                f"MB total."
            )
            raise CMSError(msg)

        # Validate file extension
        try:
            file_format = validate_file_extension(filename)
        except ValidationError as e:
            logger.error(
                "initiate_upload: validation error for user_id=%s - %s",
                user.id,
                str(e),
            )
            raise CMSError(str(e)) from e

        # Generate presigned URL
        try:
            presigned_url, s3_key = generate_presigned_upload_url(
                user_id=user.id,
                filename=filename,
            )
        except S3Error as e:
            logger.error(
                "initiate_upload: S3 error for user_id=%s - %s",
                user.id,
                str(e),
            )
            raise CMSError("Failed to initiate upload") from e

        # Generate upload token
        upload_token = generate_upload_token(
            user_id=user.id,
            s3_key=s3_key,
            name=name,
            filename=filename,
            os_slug=file_format.os_slug,
            file_size=file_size,
        )

        logger.debug(
            "initiate_upload completed for user_id=%s, filename=%s, s3_key=%s",
            user.id,
            filename,
            s3_key,
        )

        return {
            "presigned_url": presigned_url,
            "s3_key": s3_key,
            "upload_token": upload_token,
            "expected_os": file_format.os_slug,
        }

    except (TypeError, ValueError, CMSError):
        # Re-raise known errors
        raise
    except Exception:
        logger.exception("Error in initiate_upload for user_id=%s", user.id)
        raise


def complete_upload(user: User, upload_token: str) -> AgentConfig:
    """Verify and finalize upload after file has been uploaded to S3.

    Verifies the upload token, checks the S3 object exists with correct size,
    tags it as completed, and creates the agent record.

    Args:
        user: User who initiated the upload
        upload_token: Signed token from initiate_upload

    Returns:
        AgentConfig: The newly created agent record

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user is unsaved or upload_token is empty
        CMSError: If token is invalid/expired, S3 verification fails,
            or size mismatch
    """
    from cms.assets.s3 import S3Error, tag_s3_object, verify_s3_object_exists
    from cms.assets.services import create_agent
    from cms.assets.upload_token import verify_upload_token
    from cms.exceptions import CMSError

    # Input validation - user
    if user is None:
        logger.error("complete_upload called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "complete_upload called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("complete_upload called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - upload_token
    if upload_token is None:
        logger.error(
            "complete_upload called with None upload_token for user_id=%s",
            user.id,
        )
        raise ValueError("upload_token cannot be None")

    upload_token = upload_token.strip()
    if not upload_token:
        logger.error(
            "complete_upload called with empty upload_token for user_id=%s",
            user.id,
        )
        raise ValueError("upload_token cannot be empty")

    logger.debug("complete_upload called for user_id=%s", user.id)

    try:
        # Verify upload token
        try:
            payload = verify_upload_token(upload_token, user.id)
        except ValueError as e:
            logger.error(
                "complete_upload: token verification failed for user_id=%s - %s",
                user.id,
                str(e),
            )
            raise CMSError("Invalid upload token") from e

        s3_key = payload["s3_key"]
        expected_size = payload["file_size"]

        # Verify S3 object exists
        try:
            actual_size, _etag = verify_s3_object_exists(s3_key)
        except S3Error as e:
            logger.error(
                "complete_upload: S3 verification failed for user_id=%s - %s",
                user.id,
                str(e),
            )
            raise CMSError("Upload not found in storage") from e

        # Verify size matches
        if actual_size != expected_size:
            logger.error(
                "complete_upload: size mismatch for user_id=%s - expected=%s, actual=%s",
                user.id,
                expected_size,
                actual_size,
            )
            msg = f"File size mismatch: expected {expected_size}, got {actual_size}"
            raise CMSError(msg)

        # Tag S3 object as completed
        tag_s3_object(s3_key, {"status": "completed"})

        # Create agent record
        agent = create_agent(
            user=user,
            name=payload["name"],
            s3_key=s3_key,
            filename=payload["filename"],
            os_slug=payload["os_slug"],
            file_size=expected_size,
            upload_method="presigned",
        )

        logger.debug(
            "complete_upload completed for user_id=%s, agent_id=%s",
            user.id,
            agent.id,
        )

        return agent

    except (TypeError, ValueError, CMSError):
        # Re-raise known errors
        raise
    except Exception:
        logger.exception("Error in complete_upload for user_id=%s", user.id)
        raise


def cancel_upload(user: User, upload_token: str) -> None:
    """Cancel an upload and clean up the S3 object.

    Verifies the upload token and attempts to delete the S3 object.
    S3 delete failures are logged but don't cause the operation to fail
    (best effort cleanup).

    Args:
        user: User who initiated the upload
        upload_token: Signed token from initiate_upload

    Returns:
        None

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user is unsaved or upload_token is empty
        CMSError: If token is invalid/expired
    """
    from cms.assets.s3 import S3Error, delete_agent
    from cms.assets.upload_token import verify_upload_token
    from cms.exceptions import CMSError

    # Input validation - user
    if user is None:
        logger.error("cancel_upload called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "cancel_upload called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("cancel_upload called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    # Input validation - upload_token
    if upload_token is None:
        logger.error(
            "cancel_upload called with None upload_token for user_id=%s",
            user.id,
        )
        raise ValueError("upload_token cannot be None")

    upload_token = upload_token.strip()
    if not upload_token:
        logger.error(
            "cancel_upload called with empty upload_token for user_id=%s",
            user.id,
        )
        raise ValueError("upload_token cannot be empty")

    logger.debug("cancel_upload called for user_id=%s", user.id)

    try:
        # Verify upload token
        try:
            payload = verify_upload_token(upload_token, user.id)
        except ValueError as e:
            logger.error(
                "cancel_upload: token verification failed for user_id=%s - %s",
                user.id,
                str(e),
            )
            raise CMSError("Invalid upload token") from e

        s3_key = payload["s3_key"]

        # Attempt to delete S3 object (best effort)
        try:
            delete_agent(s3_key)
        except S3Error as e:
            # Log but don't fail - the object may not exist yet
            logger.warning(
                "cancel_upload: S3 delete failed for user_id=%s, s3_key=%s - %s",
                user.id,
                s3_key,
                str(e),
            )

        logger.debug(
            "cancel_upload completed for user_id=%s, s3_key=%s",
            user.id,
            s3_key,
        )

    except (TypeError, ValueError, CMSError):
        # Re-raise known errors
        raise
    except Exception:
        logger.exception("Error in cancel_upload for user_id=%s", user.id)
        raise


# =============================================================================
# User Quota
# =============================================================================


def get_storage_used(user: User) -> int:
    """Get total bytes used by a user's active agents.

    Args:
        user: The user to check storage for

    Returns:
        int: Total bytes used by active agents (0 if none)

    Raises:
        TypeError: If user is None or not a User instance
        ValueError: If user is not saved (no ID)
    """
    from cms.assets.services import get_storage_used as assets_get_storage_used

    # Input validation - user
    if user is None:
        logger.error("get_storage_used called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "get_storage_used called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("get_storage_used called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    logger.debug("get_storage_used called for user_id=%s", user.id)

    try:
        result = assets_get_storage_used(user)

        logger.debug(
            "get_storage_used returning %d bytes for user_id=%s",
            result,
            user.id,
        )
        return result

    except Exception:
        logger.exception(
            "Error in get_storage_used for user_id=%s",
            user.id,
        )
        raise


# =============================================================================
# Scenarios
# =============================================================================


def list_scenarios(user: User) -> list[dict[str, Any]]:
    """Get available scenarios with metadata.

    Args:
        user: User requesting scenarios

    Returns:
        List of scenario dictionaries with id, name, description,
        requirements, and instances fields.

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user is unsaved
    """
    from cms.scenarios.loader import get_all_scenarios

    # Input validation - user
    if user is None:
        logger.error("list_scenarios called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    if not hasattr(user, "id"):
        logger.error(
            "list_scenarios called with invalid user type: %s",
            type(user).__name__,
        )
        msg = f"user must be a User instance, got {type(user).__name__}"
        raise TypeError(msg)

    if user.id is None:
        logger.error("list_scenarios called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)

    logger.debug("list_scenarios called for user_id=%s", user.id)

    try:
        scenarios = get_all_scenarios()

        # Convert to list of dicts (deep copy to prevent mutation)
        result = [scenario.model_dump() for scenario in scenarios]

        logger.debug(
            "list_scenarios returning %d scenarios for user_id=%s",
            len(result),
            user.id,
        )
        return result

    except Exception:
        logger.exception(
            "Error in list_scenarios for user_id=%s",
            user.id,
        )
        raise


def get_scenario(scenario_id: str) -> dict[str, Any]:
    """Get a single scenario template by ID.

    Args:
        scenario_id: Unique scenario identifier

    Returns:
        Scenario dictionary with id, name, description, requirements, instances

    Raises:
        CMSError: If scenario not found
    """
    from cms.exceptions import CMSError
    from cms.scenarios.loader import load_scenario

    logger.debug("get_scenario called for scenario_id=%s", scenario_id)

    try:
        scenario = load_scenario(scenario_id)
        return scenario.model_dump()

    except ValueError as e:
        logger.error("get_scenario: scenario '%s' not found", scenario_id)
        raise CMSError(f"Scenario '{scenario_id}' not found") from e
    except Exception:
        logger.exception(
            "Error in get_scenario for scenario_id=%s",
            scenario_id,
        )
        raise


def validate_scenario_requirements(scenario_id: str, agent: AgentConfig | None) -> None:
    """Validate that an agent meets scenario requirements.

    Args:
        scenario_id: Scenario to validate against
        agent: AgentConfig instance (or None)

    Returns:
        None if validation passes

    Raises:
        CMSError: If validation fails (agent missing, wrong OS, etc.)
    """
    from cms.exceptions import CMSError
    from cms.scenarios.loader import load_scenario

    logger.debug(
        "validate_scenario_requirements called for scenario_id=%s",
        scenario_id,
    )

    try:
        scenario = load_scenario(scenario_id)
    except ValueError as e:
        logger.error(
            "validate_scenario_requirements: scenario '%s' not found",
            scenario_id,
        )
        raise CMSError(f"Scenario '{scenario_id}' not found") from e

    requirements = scenario.requirements

    # Check if agent is required
    if requirements.required and agent is None:
        logger.error(
            "validate_scenario_requirements: scenario '%s' requires an agent",
            scenario_id,
        )
        raise CMSError(f"Scenario '{scenario_id}' requires an agent")

    # Check OS requirement if specified
    if requirements.os is not None and agent is not None:
        # Get agent's OS slug
        agent_os = agent.os.slug if hasattr(agent.os, "slug") else str(agent.os)

        # Check if agent OS matches requirement (windows matches
        # windows, etc.)
        # For windows requirement, check if agent_os starts with
        # 'windows'
        if requirements.os == "windows":
            if not agent_os.startswith("windows"):
                logger.error(
                    "validate_scenario_requirements: scenario '%s' requires windows, but agent has %s",
                    scenario_id,
                    agent_os,
                )
                msg = f"Scenario '{scenario_id}' requires a Windows agent, but agent has OS '{agent_os}'"
                raise CMSError(msg)
        elif requirements.os == "linux" and not agent_os.startswith("linux"):
            logger.error(
                "validate_scenario_requirements: scenario '%s' requires linux, but agent has %s",
                scenario_id,
                agent_os,
            )
            msg = f"Scenario '{scenario_id}' requires a Linux agent, but agent has OS '{agent_os}'"
            raise CMSError(msg)

    logger.debug(
        "validate_scenario_requirements: validation passed for scenario_id=%s",
        scenario_id,
    )


# =============================================================================
# NGFWs
# =============================================================================


def _ngfw_to_context(ngfw: NGFW) -> NGFWAppContext:
    """Convert NGFW model to NGFWAppContext projection.

    Internal helper - do not call from outside cms.services.
    AWS infrastructure details are owned by Engine, not exposed here.
    """
    from shared.schemas.app import NGFWAppContext

    return NGFWAppContext(
        app_id=ngfw.id,
        name=ngfw.name,
        app_type="ngfw",
        created_at=ngfw.created_at,
    )


def _validate_ngfw_user(user: User) -> None:
    """Validate user for NGFW operations.

    Internal helper - raises TypeError or ValueError on invalid input.
    """
    if user is None:
        logger.error("NGFW operation called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)
    if not hasattr(user, "id") or user.id is None:
        logger.error("NGFW operation called with unsaved user")
        raise ValueError(USER_MUST_BE_SAVED)


def _validate_ngfw_id(ngfw_id: int) -> None:
    """Validate ngfw_id for NGFW operations.

    Internal helper - raises TypeError or ValueError on invalid input.
    """
    if ngfw_id is None:
        raise TypeError("ngfw_id cannot be None")
    if not isinstance(ngfw_id, int):
        raise TypeError(f"ngfw_id must be an int, got {type(ngfw_id).__name__}")
    if ngfw_id <= 0:
        raise ValueError("ngfw_id must be a positive integer")


def list_ngfws(user: User) -> list[NGFWAppContext]:
    """Get user's NGFWs as NGFWAppContext projections.

    Args:
        user: User whose NGFWs to retrieve

    Returns:
        List of NGFWAppContext instances ordered by created_at desc

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
    """
    from cms.models import NGFW

    _validate_ngfw_user(user)
    logger.debug("list_ngfws called for user_id=%s", user.id)

    ngfws = NGFW.objects.filter(user=user, deleted_at__isnull=True).order_by(
        "-created_at"
    )
    return [_ngfw_to_context(n) for n in ngfws]


def get_ngfw(user: User, ngfw_id: int) -> NGFWAppContext:
    """Get single NGFW by ID as NGFWAppContext projection.

    Args:
        user: User requesting the NGFW
        ngfw_id: ID of the NGFW to retrieve

    Returns:
        NGFWAppContext projection

    Raises:
        TypeError: If user is None, invalid type, or ngfw_id is invalid type
        ValueError: If user has no ID (unsaved) or ngfw_id is invalid
        CMSError: If NGFW not found or not owned by user
    """
    from cms.models import NGFW

    _validate_ngfw_user(user)
    _validate_ngfw_id(ngfw_id)
    logger.debug("get_ngfw called for user_id=%s, ngfw_id=%s", user.id, ngfw_id)

    try:
        ngfw = NGFW.objects.get(id=ngfw_id, user=user, deleted_at__isnull=True)
    except NGFW.DoesNotExist:
        logger.error("get_ngfw: NGFW id=%s not found for user_id=%s", ngfw_id, user.id)
        raise CMSError("NGFW not found") from None
    return _ngfw_to_context(ngfw)


def get_ngfw_linked_ranges(user: User, ngfw_id: int) -> list[LinkedRangeContext]:
    """Get ranges linked to an NGFW.

    Used by deprovision confirmation to show affected ranges.

    Args:
        user: User requesting the data
        ngfw_id: ID of the NGFW

    Returns:
        List of LinkedRangeContext for active ranges using this NGFW

    Raises:
        TypeError: If user is None, invalid type, or ngfw_id is invalid type
        ValueError: If user has no ID (unsaved) or ngfw_id is invalid
        CMSError: If NGFW not found or not owned by user
    """
    from engine.models import Range
    from shared.schemas.app import LinkedRangeContext

    _validate_ngfw_user(user)
    _validate_ngfw_id(ngfw_id)
    logger.debug(
        "get_ngfw_linked_ranges called for user_id=%s, ngfw_id=%s", user.id, ngfw_id
    )

    # Verify NGFW exists and user owns it (raises CMSError if not)
    get_ngfw(user, ngfw_id)

    # Find active ranges linked to this NGFW
    # Active means: pending, provisioning, ready, paused, or resuming (not destroyed/failed)
    active_statuses = [
        ResourceStatus.PENDING.value,
        ResourceStatus.PROVISIONING.value,
        ResourceStatus.READY.value,
        ResourceStatus.PAUSED.value,
        ResourceStatus.RESUMING.value,
    ]
    ranges = Range.objects.filter(
        ngfw_id=ngfw_id,
        status__in=active_statuses,
    ).order_by("-created_at")

    return [
        LinkedRangeContext(
            range_id=r.id,
            status=r.status,
            created_at=r.created_at,
        )
        for r in ranges
    ]


def create_ngfw(
    user: User,
    name: str,
    deployment_profile_id: int,
    registration_method: str,
    scm_credential_id: int | None = None,
    otp_value: str | None = None,
    otp_folder: str | None = None,
) -> NGFWAppRef:
    """Create a new NGFW.

    Validates credentials, creates NGFW record, and triggers provisioning.

    Args:
        user: User requesting provisioning
        name: Display name for the NGFW
        deployment_profile_id: ID of deployment profile credential
        registration_method: Either "pin" or "otp"
        scm_credential_id: Required if registration_method is "pin"
        otp_value: Required if registration_method is "otp"
        otp_folder: Required if registration_method is "otp"

    Returns:
        NGFWAppRef with ngfw_id for status polling

    Raises:
        TypeError: If user is None or parameter types are invalid
        ValueError: If required fields missing or invalid values
        CMSError: If credential validation fails
    """
    from cms.models import NGFW, Credential
    from shared.schemas.app import NGFWAppRef

    _validate_ngfw_user(user)

    # Validate name
    if not name or not name.strip():
        raise ValueError("name is required")
    name = name.strip()

    # Validate deployment_profile_id
    if not deployment_profile_id:
        raise ValueError("deployment_profile_id is required")
    try:
        deployment_profile = Credential.objects.select_related("credential_type").get(
            id=deployment_profile_id,
            user=user,
            deleted_at__isnull=True,
        )
        if deployment_profile.credential_type.slug != "deployment_profile":
            raise CMSError(
                "deployment_profile_id must reference a deployment profile credential"
            )
    except Credential.DoesNotExist:
        raise CMSError("Deployment profile not found") from None

    # Validate registration_method
    if registration_method not in ("pin", "otp"):
        raise ValueError("registration_method must be 'pin' or 'otp'")

    # Validate registration-specific fields
    scm_credential = None  # Initialize outside if-block
    if registration_method == "pin":
        if not scm_credential_id:
            raise ValueError("scm_credential_id is required for PIN registration")
        # Validate SCM credential exists and is owned by user
        try:
            scm_credential = Credential.objects.select_related("credential_type").get(
                id=scm_credential_id,
                user=user,
                deleted_at__isnull=True,
            )
            if scm_credential.credential_type.slug != "scm":
                raise CMSError("scm_credential_id must reference an SCM credential")
        except Credential.DoesNotExist:
            raise CMSError("SCM credential not found") from None
    else:  # otp
        if not otp_value or not otp_folder:
            raise ValueError(
                "otp_value and otp_folder are required for OTP registration"
            )

    logger.debug(
        "create_ngfw called for user_id=%s, name=%s, method=%s",
        user.id,
        name,
        registration_method,
    )

    from uuid import uuid4

    from cms.models import Request
    from cms.scenarios.hydrator import hydrate_ngfw
    from engine import create_ngfw as engine_create_ngfw
    from shared.schemas import RequestSpec

    # Create Request record first
    request_id = uuid4()
    request = Request.objects.create(
        request_id=request_id,
        user=user,
    )

    logger.info("create_ngfw: created Request id=%s for user_id=%s", request_id, user.id)

    # Create NGFW record with PROVISIONING status, linked to request
    ngfw = NGFW.objects.create(
        user=user,
        name=name,
        status=ACTIVE_STATUSES[NGFWStatus.PROVISIONING.value],
        request=request,
    )

    logger.info("create_ngfw: created NGFW id=%s for user_id=%s", ngfw.id, user.id)

    # Hydrate NGFW with credential data
    ngfw_instance_spec = hydrate_ngfw(
        ngfw=ngfw,
        deployment_profile=deployment_profile,
        registration_method=registration_method,  # type: ignore[arg-type]
        scm_credential=scm_credential,
        otp_value=otp_value,
        otp_folder=otp_folder,
    )

    # Wrap in RequestSpec
    request_spec = RequestSpec(
        request_id=request_id,
        user_id=user.id,
        items=[ngfw_instance_spec],
    )

    # Store the hydrated spec for audit/debugging (like RangeInstance.range_spec)
    ngfw.ngfw_spec = ngfw_instance_spec.model_dump(mode="json")
    ngfw.save(update_fields=["ngfw_spec"])

    engine_create_ngfw(request_spec)

    return NGFWAppRef(
        ngfw_id=ngfw.id,
        user_id=user.id,
        is_deleted=False,
    )


def destroy_ngfw(user: User, ngfw_id: int, confirm_name: str) -> NGFWAppRef:
    """Deprovision an NGFW.

    Requires name confirmation to prevent accidental deprovisioning.

    Args:
        user: User requesting deprovisioning
        ngfw_id: ID of the NGFW to deprovision
        confirm_name: Must match NGFW name exactly

    Returns:
        NGFWAppRef indicating deprovisioning started

    Raises:
        TypeError: If user is None or parameter types are invalid
        ValueError: If confirm_name doesn't match or parameters invalid
        CMSError: If NGFW not found or not owned by user
    """
    from cms.models import NGFW
    from shared.schemas.app import NGFWAppRef

    _validate_ngfw_user(user)
    _validate_ngfw_id(ngfw_id)
    logger.debug("deprovision_ngfw called for user_id=%s, ngfw_id=%s", user.id, ngfw_id)

    try:
        ngfw = NGFW.objects.get(id=ngfw_id, user=user, deleted_at__isnull=True)
    except NGFW.DoesNotExist:
        logger.error(
            "deprovision_ngfw: NGFW id=%s not found for user_id=%s", ngfw_id, user.id
        )
        raise CMSError("NGFW not found") from None

    # Validate name confirmation
    if confirm_name != ngfw.name:
        logger.error(
            "deprovision_ngfw: name mismatch for NGFW id=%s (expected=%s, got=%s)",
            ngfw_id,
            ngfw.name,
            confirm_name,
        )
        raise ValueError("Name confirmation does not match")

    # Update status to deprovisioning
    ngfw.status = TERMINAL_STATUSES[]
    ngfw.save(update_fields=["status"])

    # Call engine to tear down infrastructure
    if ngfw.request:
        from engine import services as engine_services

        engine_services.destroy_ngfw(ngfw.request.request_id)

    logger.info("deprovision_ngfw: started deprovisioning NGFW id=%s", ngfw_id)

    return NGFWAppRef(
        ngfw_id=ngfw.id,
        user_id=user.id,
        is_deleted=False,
    )
