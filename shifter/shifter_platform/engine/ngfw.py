"""NGFW service functions.

Service layer for UserNGFW lifecycle management.

TODO: This module imports from cms.models (UserNGFW). This violates the
Engine boundary - Engine should not depend on CMS. UserNGFW should either:
1. Move back to Engine (if it's truly infrastructure), or
2. These NGFW functions should move to CMS (if NGFW is content/asset)
See GitHub issue #437 for tracking.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db.models import QuerySet
from django.utils import timezone

from shared.constants import USER_CANNOT_BE_NONE

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import UserNGFW

logger = logging.getLogger(__name__)


def list_ngfws(user: User) -> QuerySet[UserNGFW]:
    """List all active NGFWs for user.

    Args:
        user: User to list NGFWs for

    Returns:
        QuerySet of UserNGFW objects owned by user

    Raises:
        TypeError: If user is None
    """
    from cms.models import UserNGFW

    # Input validation
    if user is None:
        logger.error("list_ngfws called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    logger.debug("list_ngfws called for user_id=%s", user.id)

    return UserNGFW.active_for_user(user)


def get_ngfw(user: User, ngfw_id: int) -> UserNGFW:
    """Get a specific NGFW by ID.

    Args:
        user: User requesting the NGFW (must own it)
        ngfw_id: ID of the NGFW to retrieve

    Returns:
        UserNGFW instance

    Raises:
        TypeError: If user or ngfw_id is None or wrong type
        ValueError: If ngfw_id is negative
        UserNGFW.DoesNotExist: If NGFW not found or deleted
        PermissionError: If user doesn't own the NGFW
    """
    from cms.models import UserNGFW

    # Input validation - user
    if user is None:
        logger.error("get_ngfw called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    # Input validation - ngfw_id
    if ngfw_id is None:
        logger.error("get_ngfw called with None ngfw_id")
        raise TypeError("ngfw_id cannot be None")

    if not isinstance(ngfw_id, int):
        logger.error("get_ngfw called with invalid ngfw_id type: %s", type(ngfw_id).__name__)
        raise TypeError(f"ngfw_id must be an int, got {type(ngfw_id).__name__}")

    if ngfw_id < 0:
        logger.error("get_ngfw called with negative ngfw_id=%s", ngfw_id)
        raise ValueError("ngfw_id must be non-negative")

    logger.debug("get_ngfw called for user_id=%s, ngfw_id=%s", user.id, ngfw_id)

    try:
        # First check if NGFW exists (including deleted)
        ngfw = UserNGFW.objects.get(id=ngfw_id)

        # Check if soft-deleted
        if ngfw.deleted_at is not None:
            logger.error("get_ngfw: ngfw_id=%s is deleted", ngfw_id)
            raise UserNGFW.DoesNotExist("NGFW not found")

        # Check ownership
        if ngfw.user_id != user.id:
            logger.error(
                "get_ngfw: user_id=%s does not own ngfw_id=%s (owned by %s)",
                user.id,
                ngfw_id,
                ngfw.user_id,
            )
            raise PermissionError("User does not own this NGFW")

        logger.debug("get_ngfw returning ngfw_id=%s for user_id=%s", ngfw_id, user.id)
        return ngfw

    except UserNGFW.DoesNotExist:
        logger.error("get_ngfw: ngfw_id=%s not found", ngfw_id)
        raise


def provision_ngfw(user: User, name: str) -> UserNGFW:
    """Create a new NGFW and start provisioning.

    Args:
        user: User provisioning the NGFW
        name: Name for the new NGFW

    Returns:
        Created UserNGFW instance with PROVISIONING status

    Raises:
        TypeError: If user or name is None
        ValueError: If name is empty or whitespace
    """
    from cms.models import UserNGFW

    # Input validation - user
    if user is None:
        logger.error("provision_ngfw called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    # Input validation - name
    if name is None:
        logger.error("provision_ngfw called with None name")
        raise TypeError("name cannot be None")

    name = name.strip()
    if not name:
        logger.error("provision_ngfw called with empty name")
        raise ValueError("name cannot be empty")

    logger.debug("provision_ngfw called for user_id=%s, name=%s", user.id, name)

    # Create NGFW with PROVISIONING status
    ngfw = UserNGFW.objects.create(
        user=user,
        name=name,
        status=UserNGFW.Status.PROVISIONING,
    )

    logger.debug("provision_ngfw created ngfw_id=%s for user_id=%s", ngfw.id, user.id)

    # TODO: Trigger actual provisioning via ECS task (Issue #414)

    return ngfw


def start_ngfw(user: User, ngfw_id: int) -> UserNGFW:
    """Start an NGFW (EC2 instance).

    Only valid for NGFWs in READY or STOPPED status.

    Args:
        user: User starting the NGFW (must own it)
        ngfw_id: ID of the NGFW to start

    Returns:
        Updated UserNGFW instance with ACTIVE status

    Raises:
        TypeError: If user or ngfw_id is None or wrong type
        ValueError: If ngfw_id is negative or NGFW cannot be started
        UserNGFW.DoesNotExist: If NGFW not found
        PermissionError: If user doesn't own the NGFW
    """
    from cms.models import UserNGFW

    # Input validation - user
    if user is None:
        logger.error("start_ngfw called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    # Input validation - ngfw_id
    if ngfw_id is None:
        logger.error("start_ngfw called with None ngfw_id")
        raise TypeError("ngfw_id cannot be None")

    if not isinstance(ngfw_id, int):
        logger.error("start_ngfw called with invalid ngfw_id type: %s", type(ngfw_id).__name__)
        raise TypeError(f"ngfw_id must be an int, got {type(ngfw_id).__name__}")

    if ngfw_id < 0:
        logger.error("start_ngfw called with negative ngfw_id=%s", ngfw_id)
        raise ValueError("ngfw_id must be non-negative")

    logger.debug("start_ngfw called for user_id=%s, ngfw_id=%s", user.id, ngfw_id)

    try:
        # Get and validate NGFW
        ngfw = get_ngfw(user, ngfw_id)

        # Validate state - can only start from READY or STOPPED
        if ngfw.status not in (UserNGFW.Status.READY, UserNGFW.Status.STOPPED):
            logger.error(
                "start_ngfw: Cannot start NGFW ngfw_id=%s in status=%s",
                ngfw_id,
                ngfw.status,
            )
            raise ValueError(f"Cannot start NGFW in '{ngfw.status}' status")

        # Update status to ACTIVE (simplified - real impl would use STARTING intermediate state)
        ngfw.status = UserNGFW.Status.ACTIVE
        ngfw.last_started_at = timezone.now()
        ngfw.save(update_fields=["status", "last_started_at"])

        logger.debug("start_ngfw: started ngfw_id=%s, new status=%s", ngfw_id, ngfw.status)

        # TODO: Trigger actual EC2 start via engine service (Issue #414)

        return ngfw

    except UserNGFW.DoesNotExist:
        raise
    except PermissionError:
        raise
    except ValueError:
        raise
    except Exception:
        logger.exception("Error in start_ngfw for ngfw_id=%s", ngfw_id)
        raise


def stop_ngfw(user: User, ngfw_id: int) -> UserNGFW:
    """Stop an NGFW (EC2 instance).

    Only valid for NGFWs in ACTIVE status.

    Args:
        user: User stopping the NGFW (must own it)
        ngfw_id: ID of the NGFW to stop

    Returns:
        Updated UserNGFW instance with STOPPED status

    Raises:
        TypeError: If user or ngfw_id is None or wrong type
        ValueError: If ngfw_id is negative or NGFW cannot be stopped
        UserNGFW.DoesNotExist: If NGFW not found
        PermissionError: If user doesn't own the NGFW
    """
    from cms.models import UserNGFW

    # Input validation - user
    if user is None:
        logger.error("stop_ngfw called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    # Input validation - ngfw_id
    if ngfw_id is None:
        logger.error("stop_ngfw called with None ngfw_id")
        raise TypeError("ngfw_id cannot be None")

    if not isinstance(ngfw_id, int):
        logger.error("stop_ngfw called with invalid ngfw_id type: %s", type(ngfw_id).__name__)
        raise TypeError(f"ngfw_id must be an int, got {type(ngfw_id).__name__}")

    if ngfw_id < 0:
        logger.error("stop_ngfw called with negative ngfw_id=%s", ngfw_id)
        raise ValueError("ngfw_id must be non-negative")

    logger.debug("stop_ngfw called for user_id=%s, ngfw_id=%s", user.id, ngfw_id)

    try:
        # Get and validate NGFW
        ngfw = get_ngfw(user, ngfw_id)

        # Validate state - can only stop from ACTIVE
        if ngfw.status != UserNGFW.Status.ACTIVE:
            logger.error(
                "stop_ngfw: Cannot stop NGFW ngfw_id=%s in status=%s",
                ngfw_id,
                ngfw.status,
            )
            raise ValueError(f"Cannot stop NGFW in '{ngfw.status}' status")

        # Update status to STOPPED (simplified - real impl would use STOPPING intermediate state)
        ngfw.status = UserNGFW.Status.STOPPED
        ngfw.last_stopped_at = timezone.now()
        ngfw.save(update_fields=["status", "last_stopped_at"])

        logger.debug("stop_ngfw: stopped ngfw_id=%s, new status=%s", ngfw_id, ngfw.status)

        # TODO: Trigger actual EC2 stop via engine service (Issue #414)

        return ngfw

    except UserNGFW.DoesNotExist:
        raise
    except PermissionError:
        raise
    except ValueError:
        raise
    except Exception:
        logger.exception("Error in stop_ngfw for ngfw_id=%s", ngfw_id)
        raise


def deprovision_ngfw(user: User, ngfw_id: int, confirm_name: str) -> UserNGFW:
    """Deprovision an NGFW.

    Requires name confirmation for safety.

    Args:
        user: User deprovisioning the NGFW (must own it)
        ngfw_id: ID of the NGFW to deprovision
        confirm_name: Must match NGFW name exactly

    Returns:
        Updated UserNGFW instance with DEPROVISIONING status

    Raises:
        TypeError: If user, ngfw_id, or confirm_name is None or wrong type
        ValueError: If ngfw_id is negative, confirm_name is empty, or name doesn't match
        UserNGFW.DoesNotExist: If NGFW not found
        PermissionError: If user doesn't own the NGFW
    """
    from cms.models import UserNGFW

    # Input validation - user
    if user is None:
        logger.error("deprovision_ngfw called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)

    # Input validation - ngfw_id
    if ngfw_id is None:
        logger.error("deprovision_ngfw called with None ngfw_id")
        raise TypeError("ngfw_id cannot be None")

    if not isinstance(ngfw_id, int):
        logger.error("deprovision_ngfw called with invalid ngfw_id type: %s", type(ngfw_id).__name__)
        raise TypeError(f"ngfw_id must be an int, got {type(ngfw_id).__name__}")

    if ngfw_id < 0:
        logger.error("deprovision_ngfw called with negative ngfw_id=%s", ngfw_id)
        raise ValueError("ngfw_id must be non-negative")

    # Input validation - confirm_name
    if confirm_name is None:
        logger.error("deprovision_ngfw called with None confirm_name")
        raise TypeError("confirm_name cannot be None")

    if not confirm_name.strip():
        logger.error("deprovision_ngfw called with empty confirm_name")
        raise ValueError("confirm_name cannot be empty")

    logger.debug("deprovision_ngfw called for user_id=%s, ngfw_id=%s", user.id, ngfw_id)

    try:
        # Get and validate NGFW
        ngfw = get_ngfw(user, ngfw_id)

        # Validate name confirmation
        if confirm_name != ngfw.name:
            logger.error(
                "deprovision_ngfw: confirm_name '%s' does not match ngfw name '%s' for ngfw_id=%s",
                confirm_name,
                ngfw.name,
                ngfw_id,
            )
            raise ValueError("Name confirmation does not match")

        # Update status to DEPROVISIONING
        ngfw.status = UserNGFW.Status.DEPROVISIONING
        ngfw.save(update_fields=["status"])

        logger.debug("deprovision_ngfw: started deprovisioning ngfw_id=%s", ngfw_id)

        # TODO: Trigger actual deprovisioning via ECS task (Issue #414)

        return ngfw

    except UserNGFW.DoesNotExist:
        raise
    except PermissionError:
        raise
    except ValueError:
        raise
    except Exception:
        logger.exception("Error in deprovision_ngfw for ngfw_id=%s", ngfw_id)
        raise
