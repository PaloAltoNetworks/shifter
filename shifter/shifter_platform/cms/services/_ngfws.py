"""NGFW service entrypoints (list / get / create / destroy) and helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from cms.exceptions import CMSError
from risk_register.models import AuditLog
from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED
from shared.enums import ResourceStatus
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import App, Credential, Instance, Request
    from shared.schemas.app import NGFWAppContext, NGFWAppRef

logger = logging.getLogger(__name__)


def _audit_log_call(**kwargs: Any) -> None:  # NOSONAR
    """Late-bound call to ``cms.services.audit_log`` so test patches apply."""
    from cms import services as _cs

    _cs.audit_log(**kwargs)


def _app_to_ngfw_context(app: App) -> NGFWAppContext:
    """Convert App model to NGFWAppContext projection.

    Internal helper - do not call from outside cms.services.
    AWS infrastructure details are owned by Engine, not exposed here.

    Args:
        app: App model with instance relationship loaded.
    """
    from shared.schemas.app import NGFWAppContext

    assert app.instance is not None, "App must have an instance"
    return NGFWAppContext(
        app_id=app.id,
        instance_id=app.instance.id,
        name=app.name,
        status=app.status,
        created_at=app.created_at,
        serial_number=app.data.get("serial_number"),
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


def _validate_ngfw_name(name: str) -> str:
    """Strip and require a non-empty NGFW display name."""
    if not name or not name.strip():
        raise ValueError("name is required")
    return name.strip()


def _resolve_ngfw_deployment_profile(
    user: User, deployment_profile_id: int, credential_model: type[Credential]
) -> Credential:
    """Load and type-check the deployment-profile credential for `create_ngfw`."""
    if not deployment_profile_id:
        raise ValueError("deployment_profile_id is required")
    try:
        deployment_profile = credential_model.objects.select_related("credential_type").get(
            id=deployment_profile_id,
            user=user,
        )
    except credential_model.DoesNotExist:
        raise CMSError("Deployment profile not found") from None
    if deployment_profile.credential_type.slug != "deployment_profile":
        raise CMSError("deployment_profile_id must reference a deployment profile credential")
    return cast("Credential", deployment_profile)


def _resolve_ngfw_registration(
    user: User,
    registration_method: str,
    scm_credential_id: int | None,
    otp_value: str | None,
    otp_folder: str | None,
    credential_model: type[Credential],
) -> Credential | None:
    """Validate registration-method-specific inputs; return the SCM credential or None."""
    if registration_method not in ("pin", "otp"):
        raise ValueError("registration_method must be 'pin' or 'otp'")
    if registration_method == "otp":
        if not otp_value or not otp_folder:
            raise ValueError("otp_value and otp_folder are required for OTP registration")
        return None
    # pin
    if not scm_credential_id:
        raise ValueError("scm_credential_id is required for PIN registration")
    try:
        scm_credential = credential_model.objects.select_related("credential_type").get(
            id=scm_credential_id,
            user=user,
        )
    except credential_model.DoesNotExist:
        raise CMSError("SCM credential not found") from None
    if scm_credential.credential_type.slug != "scm":
        raise CMSError("scm_credential_id must reference an SCM credential")
    return cast("Credential", scm_credential)


def _validate_app_id(app_id: UUID | str) -> UUID:
    """Validate app_id for NGFW operations.

    Internal helper - raises TypeError or ValueError on invalid input.

    Args:
        app_id: UUID or string representation of UUID.

    Returns:
        Validated UUID.
    """
    if app_id is None:
        raise TypeError("app_id cannot be None")
    if isinstance(app_id, str):
        try:
            return UUID(app_id)
        except ValueError:
            raise ValueError(f"app_id must be a valid UUID, got '{app_id}'") from None
    if isinstance(app_id, UUID):
        return app_id
    raise TypeError(f"app_id must be a UUID or string, got {type(app_id).__name__}")


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
    from cms.models import App

    _validate_ngfw_user(user)
    logger.debug("list_ngfws called for user_id=%s", user.id)

    apps = (
        App.objects.filter(
            instance__request__user=user,
            app_type__slug="panw-ngfw",
        )
        .select_related("instance")
        .order_by("-created_at")
    )

    return [_app_to_ngfw_context(app) for app in apps]


def get_ngfw(user: User, app_id: UUID | str) -> NGFWAppContext:
    """Get single NGFW by App UUID as NGFWAppContext projection.

    Args:
        user: User requesting the NGFW
        app_id: UUID of the App to retrieve

    Returns:
        NGFWAppContext projection

    Raises:
        TypeError: If user is None, invalid type, or app_id is invalid type
        ValueError: If user has no ID (unsaved) or app_id is invalid
        CMSError: If NGFW not found or not owned by user
    """
    from cms.models import App

    _validate_ngfw_user(user)
    validated_app_id = _validate_app_id(app_id)
    logger.debug("get_ngfw called for user_id=%s, app_id=%s", user.id, validated_app_id)

    try:
        app = App.objects.select_related("instance", "instance__request").get(
            id=validated_app_id,
            instance__request__user=user,
            app_type__slug="panw-ngfw",
        )
    except App.DoesNotExist:
        logger.error("get_ngfw: App id=%s not found for user_id=%s", app_id, user.id)
        raise CMSError("NGFW not found") from None
    return _app_to_ngfw_context(app)


def _reject_existing_active_ngfw(user: User) -> None:
    """Refuse provisioning when the user already has an active NGFW."""
    from cms.models import App

    existing_ngfw = (
        App.objects.filter(
            instance__request__user=user,
            app_type__slug="panw-ngfw",
        )
        .exclude(status=ResourceStatus.DESTROYING.value)
        .first()
    )
    if existing_ngfw:
        logger.warning(
            "create_ngfw: user_id=%s already has active NGFW app_id=%s",
            user.id,
            existing_ngfw.id,
        )
        raise CMSError("You already have an active NGFW. Please destroy it before creating a new one.")


def _provision_ngfw_request_records(user: User, name: str) -> tuple[UUID, Request, Instance, App]:
    """Create the Request / Instance / App rows that own an NGFW provisioning."""
    from uuid import uuid4

    from cms.models import App, AppType, Instance, InstanceType, Request
    from shared.enums import RequestType

    request_id = uuid4()
    request = Request.objects.create(
        request_id=request_id,
        request_type=RequestType.NGFW.value,
        user=user,
    )
    logger.info("create_ngfw: created Request id=%s for user_id=%s", request_id, user.id)

    instance_type = InstanceType.objects.get(slug="panw-ngfw")
    app_type = AppType.objects.get(slug="panw-ngfw")

    instance = Instance.objects.create(
        request=request,
        name=name,
        instance_type=instance_type,
        status=ResourceStatus.PROVISIONING.value,
    )
    logger.info("create_ngfw: created Instance id=%s for user_id=%s", instance.id, user.id)

    app = App.objects.create(
        name=name,
        app_type=app_type,
        instance=instance,
        status=ResourceStatus.PROVISIONING.value,
    )
    logger.info("create_ngfw: created App id=%s for instance_id=%s", app.id, instance.id)

    return request_id, request, instance, app


def _hydrate_and_dispatch_ngfw(
    request_id: UUID,
    user: User,
    request: Request,
    instance: Instance,
    app: App,
    name: str,
    deployment_profile: Credential,
    registration_method: str,
    scm_credential: Credential | None,
    otp_value: str | None,
    otp_folder: str | None,
) -> None:
    """Hydrate the NGFW spec, persist for audit, dispatch the engine, and write the audit-log row."""
    from cms.scenarios.hydrator import hydrate_ngfw
    from engine.services import create_ngfw as engine_create_ngfw
    from shared.schemas import RequestSpec

    ngfw_instance_spec = hydrate_ngfw(
        instance=instance,
        app=app,
        request=request,
        deployment_profile=deployment_profile,
        registration_method=registration_method,  # type: ignore[arg-type]
        scm_credential=scm_credential,
        otp_value=otp_value,
        otp_folder=otp_folder,
    )
    request_spec = RequestSpec(
        request_id=request_id,
        user_id=user.id,
        items=[ngfw_instance_spec],
    )

    instance.data = ngfw_instance_spec.model_dump(mode="json")
    instance.save(update_fields=["data"])

    engine_create_ngfw(request_spec)

    _audit_log_call(
        entity_type=AuditLog.EntityType.NGFW,
        entity_id=0,
        action=AuditLog.Action.PROVISION,
        actor_type=AuditLog.ActorType.USER,
        actor_id=user.id,
        new_state={
            "app_uuid": str(app.id),
            "name": name,
            "registration_method": registration_method,
            "request_id": str(request_id),
        },
        request_id=str(request_id),
    )


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

    Validates credentials, creates the Request/Instance/App rows, hydrates
    the NGFW spec, and dispatches engine provisioning.

    Raises:
        TypeError: If user is None or parameter types are invalid.
        ValueError: If required fields are missing or have invalid values.
        CMSError: If credential validation fails or the user already has an
            active NGFW.
    """
    from cms.models import Credential
    from shared.schemas.app import NGFWAppRef

    _validate_ngfw_user(user)
    _reject_existing_active_ngfw(user)

    name = _validate_ngfw_name(name)
    deployment_profile = _resolve_ngfw_deployment_profile(user, deployment_profile_id, Credential)
    scm_credential = _resolve_ngfw_registration(
        user,
        registration_method,
        scm_credential_id,
        otp_value,
        otp_folder,
        Credential,
    )

    logger.debug(
        "create_ngfw called for user_id=%s, name=%s, method=%s",
        user.id,
        safe_log_value(name),
        safe_log_value(registration_method),
    )

    request_id, request, instance, app = _provision_ngfw_request_records(user, name)
    _hydrate_and_dispatch_ngfw(
        request_id,
        user,
        request,
        instance,
        app,
        name,
        deployment_profile,
        registration_method,
        scm_credential,
        otp_value,
        otp_folder,
    )

    return NGFWAppRef(
        app_id=app.id,
        instance_id=instance.id,
        is_deleted=False,
    )


def destroy_ngfw(user: User, app_id: UUID | str, confirm_name: str) -> NGFWAppRef:
    """Deprovision an NGFW.

    Requires name confirmation to prevent accidental deprovisioning.

    Args:
        user: User requesting deprovisioning
        app_id: UUID of the App to deprovision
        confirm_name: Must match NGFW name exactly

    Returns:
        NGFWAppRef indicating deprovisioning started

    Raises:
        TypeError: If user is None or parameter types are invalid
        ValueError: If confirm_name doesn't match or parameters invalid
        CMSError: If NGFW not found or not owned by user
    """
    from django.utils import timezone

    import engine.services as engine_services
    from cms.models import App
    from shared.schemas.app import NGFWAppRef

    _validate_ngfw_user(user)
    validated_app_id = _validate_app_id(app_id)
    logger.debug("destroy_ngfw called for user_id=%s, app_id=%s", user.id, safe_log_value(validated_app_id))

    try:
        app = App.objects.select_related("instance", "instance__request").get(
            id=validated_app_id,
            instance__request__user=user,
            app_type__slug="panw-ngfw",
        )
    except App.DoesNotExist:
        logger.error("destroy_ngfw: App id=%s not found for user_id=%s", safe_log_value(app_id), user.id)
        raise CMSError("NGFW not found") from None

    if confirm_name != app.name:
        logger.error(
            "destroy_ngfw: name mismatch for App id=%s (expected=%s, got=%s)",
            safe_log_value(app_id),
            safe_log_value(app.name),
            safe_log_value(confirm_name),
        )
        raise ValueError("Name confirmation does not match")

    instance = app.instance
    assert instance is not None, "App must have an instance"
    request_id = instance.request.request_id

    try:
        engine_services.destroy_ngfw(request_id)
    except engine_services.EngineError as e:
        raise CMSError(str(e)) from e

    now = timezone.now()
    app.status = ResourceStatus.DESTROYING.value
    app.deleted_at = now
    app.save(update_fields=["status", "deleted_at"])

    instance.status = ResourceStatus.DESTROYING.value
    instance.deleted_at = now
    instance.save(update_fields=["status", "deleted_at"])

    _audit_log_call(
        entity_type=AuditLog.EntityType.NGFW,
        entity_id=0,
        action=AuditLog.Action.DEPROVISION,
        actor_type=AuditLog.ActorType.USER,
        actor_id=user.id,
        previous_state={
            "app_uuid": str(app.id),
            "name": app.name,
            "status": ResourceStatus.DESTROYING.value,
        },
        request_id=str(request_id),
    )

    logger.info(
        "destroy_ngfw: started deprovisioning App id=%s, request_id=%s",
        safe_log_value(app_id),
        request_id,
    )

    return NGFWAppRef(
        app_id=app.id,
        instance_id=instance.id,
        is_deleted=True,
    )
