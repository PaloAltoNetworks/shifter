"""CMS service interface.

Content and asset management for Shifter platform.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.assets.services import create_agent as assets_create_agent
from cms.assets.services import delete_agent as assets_delete_agent
from mission_control.models import AgentConfig

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


# =============================================================================
# Agents
# =============================================================================


def create_agent(user: User, **kwargs: Any) -> Any:
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
            - sha256: SHA256 hash of the agent file
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
        raise TypeError("user cannot be None")

    if not hasattr(user, "id"):
        logger.error("create_agent called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")

    if user.id is None:
        logger.error("create_agent called with unsaved user (id=None)")
        raise ValueError("user must be saved (have an ID)")

    logger.debug("create_agent called for user_id=%s", user.id)

    try:
        agent = assets_create_agent(user=user, **kwargs)

        # Validate response from assets service
        if agent is None:
            logger.error("create_agent: assets service returned None for user_id=%s", user.id)
            raise TypeError("Assets service returned None instead of AgentConfig")

        if not isinstance(agent, AgentConfig):
            logger.error(
                "create_agent: assets service returned invalid type %s for user_id=%s",
                type(agent).__name__,
                user.id,
            )
            raise TypeError(f"Assets service returned {type(agent).__name__}, expected AgentConfig")

        logger.debug("create_agent returning agent_id=%s for user_id=%s", agent.id, user.id)
        return agent

    except TypeError:
        # Re-raise TypeErrors (our validation errors)
        raise
    except Exception:
        logger.exception("Error in create_agent for user_id=%s", user.id)
        raise


def delete_agent(user: User, agent_id: int) -> None:
    """Soft delete agent.

    Verifies ownership via get_agent, then delegates to cms.assets.services.delete_agent().

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
        raise TypeError("user cannot be None")

    if not hasattr(user, "id"):
        logger.error("delete_agent called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")

    if user.id is None:
        logger.error("delete_agent called with unsaved user (id=None)")
        raise ValueError("user must be saved (have an ID)")

    # Input validation - agent_id
    if agent_id is None:
        logger.error("delete_agent called with None agent_id for user_id=%s", user.id)
        raise TypeError("agent_id cannot be None")

    if not isinstance(agent_id, int):
        logger.error("delete_agent called with invalid agent_id type: %s", type(agent_id).__name__)
        raise TypeError(f"agent_id must be an int, got {type(agent_id).__name__}")

    if agent_id < 0:
        logger.error("delete_agent called with negative agent_id=%s for user_id=%s", agent_id, user.id)
        raise ValueError("agent_id must be non-negative")

    logger.debug("delete_agent called for user_id=%s, agent_id=%s", user.id, agent_id)

    try:
        # Get agent (also verifies ownership and not deleted)
        agent = get_agent(user, agent_id)

        # Delete via assets service
        assets_delete_agent(agent)

        logger.debug("delete_agent completed for agent_id=%s, user_id=%s", agent_id, user.id)

    except Exception:
        logger.exception("Error in delete_agent for user_id=%s, agent_id=%s", user.id, agent_id)
        raise


def list_agents(user: User) -> list[Any]:
    """Get user's agents.

    Args:
        user: User whose agents to retrieve

    Returns:
        List of AgentConfig instances belonging to the user

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
    """
    # Input validation
    if user is None:
        logger.error("list_agents called with None user")
        raise TypeError("user cannot be None")

    if not hasattr(user, "id"):
        logger.error("list_agents called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")

    if user.id is None:
        logger.error("list_agents called with unsaved user (id=None)")
        raise ValueError("user must be saved (have an ID)")

    logger.debug("list_agents called for user_id=%s", user.id)

    try:
        result = AgentConfig.active_for_user(user)

        # Validate response from model
        if result is None:
            logger.error("list_agents: model returned None for user_id=%s", user.id)
            raise TypeError("Model returned None instead of iterable")

        # Convert to list (handles QuerySet, tuple, generator)
        agents = list(result)

        # Validate list contents
        for item in agents:
            if not isinstance(item, AgentConfig):
                logger.error(
                    "list_agents: model returned invalid item type %s for user_id=%s",
                    type(item).__name__,
                    user.id,
                )
                raise TypeError(f"Model returned list containing {type(item).__name__}, expected AgentConfig")

        logger.debug("list_agents returning %d agents for user_id=%s", len(agents), user.id)
        return agents

    except TypeError:
        # Re-raise TypeErrors (our validation errors)
        raise
    except Exception:
        logger.exception("Error in list_agents for user_id=%s", user.id)
        raise


def get_agent(user: User, agent_id: int) -> Any:
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
        raise TypeError("user cannot be None")

    if not hasattr(user, "id"):
        logger.error("get_agent called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")

    if user.id is None:
        logger.error("get_agent called with unsaved user (id=None)")
        raise ValueError("user must be saved (have an ID)")

    # Input validation - agent_id
    if agent_id is None:
        logger.error("get_agent called with None agent_id for user_id=%s", user.id)
        raise TypeError("agent_id cannot be None")

    if not isinstance(agent_id, int):
        logger.error("get_agent called with invalid agent_id type: %s", type(agent_id).__name__)
        raise TypeError(f"agent_id must be an int, got {type(agent_id).__name__}")

    if agent_id < 0:
        logger.error("get_agent called with negative agent_id=%s for user_id=%s", agent_id, user.id)
        raise ValueError("agent_id must be non-negative")

    logger.debug("get_agent called for user_id=%s, agent_id=%s", user.id, agent_id)

    try:
        agent = AgentConfig.objects.get(id=agent_id)

        # Validate response from model
        if agent is None:
            logger.error("get_agent: model returned None for agent_id=%s", agent_id)
            raise TypeError("Model returned None instead of AgentConfig")

        if not isinstance(agent, AgentConfig):
            logger.error(
                "get_agent: model returned invalid type %s for agent_id=%s",
                type(agent).__name__,
                agent_id,
            )
            raise TypeError(f"Model returned {type(agent).__name__}, expected AgentConfig")

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
            logger.error("get_agent: agent_id=%s is deleted", agent_id)
            raise CMSError(f"Agent {agent_id} not found")

        logger.debug("get_agent returning agent_id=%s for user_id=%s", agent_id, user.id)
        return agent

    except AgentConfig.DoesNotExist:
        logger.error("get_agent: agent_id=%s not found", agent_id)
        raise CMSError(f"Agent {agent_id} not found") from None
    except (TypeError, CMSError):
        # Re-raise TypeErrors and CMSErrors
        raise
    except Exception:
        logger.exception("Error in get_agent for user_id=%s, agent_id=%s", user.id, agent_id)
        raise


# =============================================================================
# Credentials
# =============================================================================


def create_credential(user: User, credential_type: str, **kwargs: Any) -> Any:
    """Create credential (SCM or deployment profile).

    Args:
        user: User who will own the credential
        credential_type: Type of credential ('scm' or 'deployment_profile')
        **kwargs: Type-specific fields:
            For 'scm':
                - name: Display name for the credential
                - scm_folder_name: SCM folder name
                - scm_pin_id: SCM PIN ID
                - scm_pin_value: SCM PIN value (encrypted)
                - sls_region: SLS region
            For 'deployment_profile':
                - name: Display name for the credential
                - authcode: Deployment authcode (encrypted)

    Returns:
        Credential: The newly created credential record

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved) or credential_type is invalid
    """
    from cms.models import Credential

    # Input validation - user
    if user is None:
        logger.error("create_credential called with None user")
        raise TypeError("user cannot be None")

    if not hasattr(user, "id"):
        logger.error("create_credential called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")

    if user.id is None:
        logger.error("create_credential called with unsaved user (id=None)")
        raise ValueError("user must be saved (have an ID)")

    # Input validation - credential_type
    valid_types = [c[0] for c in Credential.Type.choices]
    if credential_type is None:
        logger.error("create_credential called with None credential_type for user_id=%s", user.id)
        raise ValueError("credential_type cannot be None")

    if credential_type not in valid_types:
        logger.error(
            "create_credential called with invalid credential_type '%s' for user_id=%s",
            credential_type,
            user.id,
        )
        raise ValueError(f"credential_type must be one of {valid_types}, got '{credential_type}'")

    logger.debug("create_credential called for user_id=%s, credential_type=%s", user.id, credential_type)

    try:
        # Create credential with provided fields
        credential = Credential(
            user=user,
            credential_type=credential_type,
            **kwargs,
        )
        credential.save()

        logger.debug(
            "create_credential created credential_id=%s, credential_type=%s for user_id=%s",
            credential.id,
            credential_type,
            user.id,
        )
        return credential

    except Exception:
        logger.exception("Error in create_credential for user_id=%s, credential_type=%s", user.id, credential_type)
        raise


def delete_credential(user: User, credential_id: int) -> None:
    """Soft delete credential.

    Verifies ownership via get_credential, then performs soft delete.

    Args:
        user: User requesting deletion
        credential_id: ID of the credential to delete

    Returns:
        None

    Raises:
        TypeError: If user is None, invalid type, or credential_id is invalid type
        ValueError: If user has no ID (unsaved) or credential_id is invalid
        CMSError: If credential not found or not owned by user
    """
    from django.utils import timezone

    # Input validation - user
    if user is None:
        logger.error("delete_credential called with None user")
        raise TypeError("user cannot be None")

    if not hasattr(user, "id"):
        logger.error("delete_credential called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")

    if user.id is None:
        logger.error("delete_credential called with unsaved user (id=None)")
        raise ValueError("user must be saved (have an ID)")

    # Input validation - credential_id
    if credential_id is None:
        logger.error("delete_credential called with None credential_id for user_id=%s", user.id)
        raise TypeError("credential_id cannot be None")

    if not isinstance(credential_id, int):
        logger.error("delete_credential called with invalid credential_id type: %s", type(credential_id).__name__)
        raise TypeError(f"credential_id must be an int, got {type(credential_id).__name__}")

    if credential_id < 0:
        logger.error("delete_credential called with negative credential_id=%s for user_id=%s", credential_id, user.id)
        raise ValueError("credential_id must be non-negative")

    logger.debug("delete_credential called for user_id=%s, credential_id=%s", user.id, credential_id)

    try:
        # Get credential (also verifies ownership and not deleted)
        credential = get_credential(user, credential_id)

        # Soft delete
        credential.deleted_at = timezone.now()
        credential.save()

        logger.debug("delete_credential completed for credential_id=%s, user_id=%s", credential_id, user.id)

    except Exception:
        logger.exception("Error in delete_credential for user_id=%s, credential_id=%s", user.id, credential_id)
        raise


def list_credentials(user: User) -> list[Any]:
    """Get user's credentials (includes type).

    Args:
        user: User whose credentials to retrieve

    Returns:
        List of Credential instances belonging to the user

    Raises:
        TypeError: If user is None or invalid type
        ValueError: If user has no ID (unsaved)
    """
    from cms.models import Credential

    # Input validation
    if user is None:
        logger.error("list_credentials called with None user")
        raise TypeError("user cannot be None")

    if not hasattr(user, "id"):
        logger.error("list_credentials called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")

    if user.id is None:
        logger.error("list_credentials called with unsaved user (id=None)")
        raise ValueError("user must be saved (have an ID)")

    logger.debug("list_credentials called for user_id=%s", user.id)

    try:
        result = Credential.active_for_user(user)

        # Validate response from model
        if result is None:
            logger.error("list_credentials: model returned None for user_id=%s", user.id)
            raise TypeError("Model returned None instead of iterable")

        # Convert to list (handles QuerySet, tuple, generator)
        credentials = list(result)

        # Validate list contents
        for item in credentials:
            if not isinstance(item, Credential):
                logger.error(
                    "list_credentials: model returned invalid item type %s for user_id=%s",
                    type(item).__name__,
                    user.id,
                )
                raise TypeError(f"Model returned list containing {type(item).__name__}, expected Credential")

        logger.debug("list_credentials returning %d credentials for user_id=%s", len(credentials), user.id)
        return credentials

    except TypeError:
        # Re-raise TypeErrors (our validation errors)
        raise
    except Exception:
        logger.exception("Error in list_credentials for user_id=%s", user.id)
        raise


def get_credential(user: User, credential_id: int) -> Any:
    """Get single credential by ID.

    Args:
        user: User requesting the credential
        credential_id: ID of the credential to retrieve

    Returns:
        Credential instance if found and owned by user

    Raises:
        TypeError: If user is None, invalid type, or credential_id is invalid type
        ValueError: If user has no ID (unsaved) or credential_id is invalid
        CMSError: If credential not found, not owned by user, or deleted
    """
    from cms.exceptions import CMSError
    from cms.models import Credential

    # Input validation - user
    if user is None:
        logger.error("get_credential called with None user")
        raise TypeError("user cannot be None")

    if not hasattr(user, "id"):
        logger.error("get_credential called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")

    if user.id is None:
        logger.error("get_credential called with unsaved user (id=None)")
        raise ValueError("user must be saved (have an ID)")

    # Input validation - credential_id
    if credential_id is None:
        logger.error("get_credential called with None credential_id for user_id=%s", user.id)
        raise TypeError("credential_id cannot be None")

    if not isinstance(credential_id, int):
        logger.error("get_credential called with invalid credential_id type: %s", type(credential_id).__name__)
        raise TypeError(f"credential_id must be an int, got {type(credential_id).__name__}")

    if credential_id < 0:
        logger.error("get_credential called with negative credential_id=%s for user_id=%s", credential_id, user.id)
        raise ValueError("credential_id must be non-negative")

    logger.debug("get_credential called for user_id=%s, credential_id=%s", user.id, credential_id)

    try:
        credential = Credential.objects.get(id=credential_id)

        # Validate response from model
        if credential is None:
            logger.error("get_credential: model returned None for credential_id=%s", credential_id)
            raise TypeError("Model returned None instead of Credential")

        if not isinstance(credential, Credential):
            logger.error(
                "get_credential: model returned invalid type %s for credential_id=%s",
                type(credential).__name__,
                credential_id,
            )
            raise TypeError(f"Model returned {type(credential).__name__}, expected Credential")

        # Check ownership
        if credential.user.id != user.id:
            logger.error(
                "get_credential: access denied - credential_id=%s owned by user_id=%s, requested by user_id=%s",
                credential_id,
                credential.user.id,
                user.id,
            )
            raise CMSError(f"Credential {credential_id} not found")

        # Check soft deletion
        if credential.deleted_at is not None:
            logger.error("get_credential: credential_id=%s is deleted", credential_id)
            raise CMSError(f"Credential {credential_id} not found")

        logger.debug("get_credential returning credential_id=%s for user_id=%s", credential_id, user.id)
        return credential

    except Credential.DoesNotExist:
        logger.error("get_credential: credential_id=%s not found", credential_id)
        raise CMSError(f"Credential {credential_id} not found") from None
    except (TypeError, CMSError):
        # Re-raise TypeErrors and CMSErrors
        raise
    except Exception:
        logger.exception("Error in get_credential for user_id=%s, credential_id=%s", user.id, credential_id)
        raise


# =============================================================================
# Ranges
# =============================================================================


def create_range(user: User, scenario: str, agent_id: int, **kwargs: Any) -> Any:
    """Compose scenario, trigger provisioning."""
    raise NotImplementedError


def destroy_range(user: User, range_id: int) -> None:
    """Tear down range."""
    raise NotImplementedError


def list_ranges(user: User) -> list[Any]:
    """Get user's ranges."""
    raise NotImplementedError


def get_range(user: User, range_id: int) -> Any:
    """Get single range."""
    raise NotImplementedError


def cancel_range(user: User, range_id: int) -> None:
    """Cancel provisioning range."""
    raise NotImplementedError


def pause_range(user: User, range_id: int) -> None:
    """Pause range."""
    raise NotImplementedError


def resume_range(user: User, range_id: int) -> None:
    """Resume range."""
    raise NotImplementedError


# =============================================================================
# Uploads
# =============================================================================


def initiate_upload(user: User, name: str, filename: str, file_size: int) -> dict[str, Any]:
    """Validate, generate presigned URL."""
    raise NotImplementedError


def complete_upload(user: User, upload_token: str, sha256: str) -> Any:
    """Verify and finalize upload."""
    raise NotImplementedError


def cancel_upload(user: User, upload_token: str) -> None:
    """Clean up failed upload."""
    raise NotImplementedError


# =============================================================================
# User Quota
# =============================================================================


def get_storage_used(user: User) -> int:
    """Check storage quota."""
    raise NotImplementedError


# =============================================================================
# Scenarios
# =============================================================================


def list_scenarios(user: User) -> list[Any]:
    """Get available scenarios."""
    raise NotImplementedError
