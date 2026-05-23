"""Credential service entrypoints (create / delete / list / get)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from cms.exceptions import CMSError
from risk_register.models import AuditLog

from ._common import _validate_caller_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.schemas.credentials import CredentialContext, CredentialRef

logger = logging.getLogger(__name__)


def _audit_log_call(**kwargs: Any) -> None:  # NOSONAR
    """Late-bound call to ``cms.services.audit_log`` so test patches apply."""
    from cms import services as _cs

    _cs.audit_log(**kwargs)


def create_credential(user: User, credential_type_slug: str, **kwargs: Any) -> CredentialRef:
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

    _validate_caller_user(user, "create_credential")

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
        try:
            cred_type = CredentialType.objects.get(slug=credential_type_slug)
        except CredentialType.DoesNotExist:
            logger.error(
                "create_credential: credential type '%s' not found for user_id=%s",
                credential_type_slug,
                user.id,
            )
            raise CMSError(f"Credential type '{credential_type_slug}' not found") from None

        name = kwargs.pop("name", None)
        if not name:
            raise ValueError("name is required")

        expires_at = kwargs.pop("expires_at", None)

        if credential_type_slug == "scm" and not kwargs.get("scm_folder_name"):
            kwargs["scm_folder_name"] = ""

        data = kwargs

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

        _audit_log_call(
            entity_type=AuditLog.EntityType.CREDENTIAL,
            entity_id=credential.id,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={
                "credential_type": credential_type_slug,
                "name": name,
            },
        )

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

    _validate_caller_user(user, "delete_credential")

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
        try:
            credential = Credential.objects.get(
                id=credential_id,
                user=user,
            )
        except Credential.DoesNotExist:
            logger.error(
                "delete_credential: credential_id=%s not found for user_id=%s",
                credential_id,
                user.id,
            )
            raise CMSError(f"Credential {credential_id} not found") from None

        previous_state = {
            "credential_type": credential.credential_type.slug,
            "name": credential.name,
        }

        credential.deleted_at = timezone.now()
        credential.save(update_fields=["deleted_at"])

        _audit_log_call(
            entity_type=AuditLog.EntityType.CREDENTIAL,
            entity_id=credential_id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state=previous_state,
        )

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

    _validate_caller_user(user, "list_credentials")

    logger.debug("list_credentials called for user_id=%s", user.id)

    try:
        credentials = (
            Credential.objects.filter(
                user=user,
            )
            .select_related("credential_type")
            .order_by("-created_at")
        )

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

    _validate_caller_user(user, "get_credential")

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
