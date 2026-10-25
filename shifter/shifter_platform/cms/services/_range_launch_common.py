"""Common admission and persistence invariants for RAES range launches."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import IntegrityError, transaction

from cms.exceptions import CMSError, WorkspaceLaunchQuotaExceeded
from cms.models import ACTIVE_RANGE_UNIQUE_CONSTRAINT, RangeInstance
from cms.services._range_workspace import (
    reauthorize_launch_workspace_locked,
    resolve_effective_egress_mode_locked,
)
from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED
from shared.enums import ResourceStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.contrib.auth.models import User

    from cms.models import Request
    from shared.enums import RangeSource
    from shared.model_access import OwnedReference
    from shared.model_access.reservation import ModelLaunchScope

logger = logging.getLogger(__name__)

_ACTIVE_RANGE_MESSAGE = "You already have an active range. Please destroy it before creating a new one."
# One non-enumerating message for an enforcing per-workspace concurrent-range cap.
_LAUNCH_QUOTA_MESSAGE = "This workspace has reached its concurrent range limit."


@dataclass(frozen=True, slots=True)
class LaunchOptions:
    """Optional inputs retained at the public range-launch seam."""

    ngfw_enabled: bool = False
    remote_access_teardown_at: datetime | None = None
    workspace_uuid: str | UUID | None = None
    # PLAT-202: the canonical sharing-membership subject (a CTF draw reference)
    # so required-model admission resolves the sharing overlap against the real
    # launch subject rather than the launcher identity.
    model_admission_subject: OwnedReference | None = None
    model_launch_scope: ModelLaunchScope | None = None
    model_sources: dict | None = None
    # CTF ranges belong to a participant, while private scenario visibility is
    # authorized by the event owner who selected the tenant pack.
    content_authorizer: User | None = None
    ctf_policy_workspace_id: int | None = None


def _audit_log_call(**kwargs: Any) -> None:  # NOSONAR
    """Late-bind the public audit seam so established test patches apply."""
    from cms import services as cms_services

    cms_services.audit_log(cms_services.AuditEvent(**kwargs))


def _validate_create_range_user(user: User) -> None:
    """Validate the launcher's public argument shape."""
    if user is None:
        logger.error("create_range called with None user")
        raise TypeError(USER_CANNOT_BE_NONE)
    if not hasattr(user, "id"):
        logger.error("create_range called with invalid user type: %s", type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")
    if user.id is None:
        logger.error("create_range called with unsaved user (id=None)")
        raise ValueError(USER_MUST_BE_SAVED)


def _validate_create_range_scenario(user: User, scenario: str) -> None:
    """Validate the registered scenario identifier argument."""
    if scenario is None:
        logger.error("create_range called with None scenario for user_id=%s", user.id)
        raise ValueError("scenario cannot be None")
    if not isinstance(scenario, str) or not scenario:
        logger.error("create_range called with invalid scenario '%s' for user_id=%s", scenario, user.id)
        raise ValueError("scenario must be a non-empty string")


def _assert_scenario_launchable(scenario: str) -> None:
    """Reject a registered RAES source that has not passed launch admission."""
    from cms.scenarios.registry import get_catalog_entry

    entry = get_catalog_entry(scenario)
    if entry is not None and not entry.get("launchable", True):
        logger.warning("create_range: scenario '%s' is not launchable", scenario)
        raise CMSError(f"Scenario '{scenario}' is not available for launch")


def _get_active_range_call(user: User, range_source: RangeSource | None = None) -> Any:  # NOSONAR
    """Late-bind active-range lookup so established test patches apply."""
    from cms import services as cms_services

    return cms_services.get_active_range(user, range_source)


def _assert_no_active_range(user: User, range_source: RangeSource | None = None) -> None:
    """Fail fast when the user already occupies the source's active slot."""
    existing = _get_active_range_call(user, range_source)
    if existing:
        logger.warning(
            "create_range: user_id=%s already has active %s range request_id=%s",
            user.id,
            range_source,
            existing.range_id,
        )
        raise CMSError(_ACTIVE_RANGE_MESSAGE)


def _is_active_range_conflict(exc: IntegrityError) -> bool:
    """Return whether an integrity error is the active-range constraint."""
    cause = exc.__cause__
    diag = getattr(cause, "diag", None)
    if getattr(diag, "constraint_name", None) == ACTIVE_RANGE_UNIQUE_CONSTRAINT:
        return True
    message = str(exc)
    if ACTIVE_RANGE_UNIQUE_CONSTRAINT in message:
        return True
    return "user_id" in message and "range_source" in message


def _create_cms_request(user: User, workspace_id: int, request_id: UUID) -> Request:
    """Create the CMS request row for a pre-minted correlation identifier."""
    from cms.models import Request
    from shared.enums import RequestType

    request = Request.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
        workspace_id=workspace_id,
    )
    logger.info("create_range: created CMS Request id=%s for user_id=%s", request_id, user.id)
    return request


def _set_range_instance_status(range_instance: RangeInstance, status: ResourceStatus) -> None:
    """Persist the public status vocabulary on a CMS range instance."""
    range_instance.status = status.value
    range_instance.save(update_fields=["status"])


def _reserve_active_range_slot(
    user: User,
    range_source: RangeSource,
    persist_instance: Callable[[Request], RangeInstance],
    workspace_id: int,
    request_id: UUID | None = None,
    *,
    policy_workspace_id: int | None = None,
    policy_actor: User | None = None,
) -> tuple[UUID, Request, RangeInstance, str]:
    """Atomically reauthorize scope, admit the workspace quota, and reserve the slot."""
    from uuid import uuid4

    from workspaces.services import (
        WorkspaceQuotaAuditContext,
        WorkspaceQuotaRejected,
        record_workspace_quota_rejection,
        reserve_workspace_concurrent_range,
    )

    correlation_id = request_id or uuid4()
    quota_audit = WorkspaceQuotaAuditContext(actor_type="user", actor_id=getattr(user, "id", None))
    try:
        with transaction.atomic():
            if policy_workspace_id is not None and policy_actor is not None and policy_workspace_id < workspace_id:
                from cms.services._range_workspace import reauthorize_ctf_policy_workspace_locked

                reauthorize_ctf_policy_workspace_locked(policy_actor, policy_workspace_id)
            reauthorize_launch_workspace_locked(user, workspace_id)
            if policy_workspace_id is not None and policy_actor is not None and policy_workspace_id >= workspace_id:
                from cms.services._range_workspace import reauthorize_ctf_policy_workspace_locked

                reauthorize_ctf_policy_workspace_locked(policy_actor, policy_workspace_id)
            # Concurrent-range quota is evaluated under the same workspace mutex and
            # the open reservation is committed with the CMS reservation, so an
            # active-range collision or any persistence failure rolls both back
            # together (ADR-046-R10). The pre-minted request UUID is the key.
            reserve_workspace_concurrent_range(workspace_id, correlation_id, quota_audit)
            egress_mode = resolve_effective_egress_mode_locked(policy_workspace_id or workspace_id)
            cms_request = _create_cms_request(user, workspace_id, correlation_id)
            range_instance = persist_instance(cms_request)
            _set_range_instance_status(range_instance, ResourceStatus.PROVISIONING)
    except WorkspaceQuotaRejected as rejected:
        # Hard cap: the transaction rolled back with no range persisted. Record the
        # rejection evidence on the committed path, then map to a launch conflict.
        record_workspace_quota_rejection(
            rejected.workspace_id, rejected.verdict, quota_audit, correlation_key=str(correlation_id)
        )
        logger.info(
            "create_range: workspace concurrent-range quota exhausted user_id=%s workspace_id=%s",
            user.id,
            workspace_id,
        )
        raise WorkspaceLaunchQuotaExceeded(_LAUNCH_QUOTA_MESSAGE) from None
    except IntegrityError as exc:
        if _is_active_range_conflict(exc):
            logger.warning(
                "create_range: active-range constraint collision for user_id=%s range_source=%s",
                user.id,
                range_source.value,
            )
            raise CMSError(_ACTIVE_RANGE_MESSAGE) from exc
        raise
    return correlation_id, cms_request, range_instance, egress_mode
