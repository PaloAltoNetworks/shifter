"""Range provisioning: create_range plus its hydration/dispatch helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import IntegrityError, transaction

from cms.exceptions import CMSError
from cms.models import ACTIVE_RANGE_UNIQUE_CONSTRAINT, AgentConfig, RangeInstance

# Re-exported for existing importers (cms.services._aces_range_create, tests); the
# gate lives in its own module so _range_create stays within its size budget.
from cms.services._range_backend_admission import (
    _assert_live_fire_backend_admitted,
    _openvpn_backend_admitted,
)

# Re-exported for existing importers (cms.services._aces_range_create): the
# argument-shape and scenario admission validators live in their own module.
from cms.services._range_create_validation import (
    _assert_scenario_launchable,
    _check_scenario_agent_requirements,
    _load_scenario_template_or_raise,
    _validate_create_range_agents_by_os,
    _validate_create_range_scenario,
    _validate_create_range_user,
)
from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
)
from shared.enums import ResourceStatus
from shared.schemas import RangeRef
from shared.schemas.persistence import wrap_persisted_spec

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.contrib.auth.models import User

    from cms.models import Request
    from cms.services._range_lease import RangeLease
    from shared.enums import RangeSource
    from shared.range_instantiation_policy import BackendAdmission
    from shared.schemas import RequestSpec
    from shared.schemas.range import RangeContext, RangeSpec

logger = logging.getLogger(__name__)

# Authored, user-facing message for the single-active-range invariant. Shared by
# the friendly service pre-check (``_assert_no_active_range``) and the database
# constraint translation (``_reserve_active_range_slot``) so both admission
# rejections read identically and neither leaks driver/SQL detail (#307).
_ACTIVE_RANGE_MESSAGE = "You already have an active range. Please destroy it before creating a new one."


def _engine_create_range_call(
    request_spec: RequestSpec,
    backend_admission: BackendAdmission | None = None,
    remote_access_capability: dict[str, object] | None = None,
) -> RangeRef:
    """Late-bound call to ``cms.services.engine_create_range`` so test patches apply.

    ``backend_admission`` is the trusted #1348 admission result carried beside the
    RequestSpec (never inside it); the Engine persists the backend/purpose binding
    from it at create (#1666).
    """
    from cms import services as _cs

    if remote_access_capability is None:
        return _cs.engine_create_range(request_spec, backend_admission=backend_admission)
    return _cs.engine_create_range(
        request_spec,
        backend_admission=backend_admission,
        remote_access_capability=remote_access_capability,
    )


def _audit_log_call(**kwargs: Any) -> None:  # NOSONAR
    """Late-bound call to ``cms.services.audit_log`` so test patches apply."""
    from cms import services as _cs

    _cs.audit_log(_cs.AuditEvent(**kwargs))


def _get_active_range_call(user: User, range_source: RangeSource | None = None) -> Any:  # NOSONAR
    """Look up active range through the package to honor test patches."""
    from cms import services as _cs

    return _cs.get_active_range(user, range_source)


def _get_agent_call(user: User, agent_id: int) -> AgentConfig:
    """Look up agent through the package to honor test patches."""
    from cms import services as _cs

    return _cs.get_agent(user, agent_id)


def _assert_no_active_range(user: User, range_source: RangeSource | None = None) -> None:
    """Raise CMSError if the user already has an active range for the given source.

    This is the friendly, fast pre-check for the common sequential case; it is a
    read-before-create and therefore races under concurrency. The authoritative
    backstop is the partial unique constraint enforced in
    :func:`_reserve_active_range_slot` (#307).
    """
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
    """Return True iff ``exc`` violates the active-range unique constraint.

    Detection is backend-aware. PostgreSQL (production) names the violated
    constraint via ``exc.__cause__.diag.constraint_name`` -- the authoritative
    signal. SQLite (the fast test lane) reports the violated *columns* rather
    than the index name, so we fall back to matching the ``(user_id,
    range_source)`` column pair, which is unique to this constraint on
    ``RangeInstance``. Either way, only *this* constraint counts as an
    active-range conflict, so unrelated integrity errors still propagate (#307
    preflight: do not catch every ``IntegrityError`` as a duplicate range).
    """
    cause = exc.__cause__
    diag = getattr(cause, "diag", None)
    if getattr(diag, "constraint_name", None) == ACTIVE_RANGE_UNIQUE_CONSTRAINT:
        return True
    message = str(exc)
    if ACTIVE_RANGE_UNIQUE_CONSTRAINT in message:
        return True
    return "user_id" in message and "range_source" in message


def _reserve_active_range_slot(
    user: User,
    range_source: RangeSource,
    persist_instance: Callable[[Request], RangeInstance],
) -> tuple[UUID, Request, RangeInstance]:
    """Atomically reserve the single active-range slot for ``(user, range_source)``.

    One transaction creates the CMS ``Request``, persists the ``RangeInstance``
    (built by ``persist_instance``), and sets it PROVISIONING. The partial
    unique constraint on ``(user_id, range_source)`` for active rows is the
    race-proof backstop: a losing concurrent caller's INSERT raises
    ``IntegrityError``, the whole transaction rolls back (so no orphan
    ``Request`` is left behind), and the *named* violation is translated into the
    authored active-range ``CMSError``. Unrelated integrity errors propagate.

    Cloud/engine dispatch MUST happen outside this call — never hold the
    transaction open across an Engine/ACES/broker call (#307 preflight).
    """
    try:
        with transaction.atomic():
            request_id, cms_request = _create_cms_request(user)
            range_instance = persist_instance(cms_request)
            _set_range_instance_status(range_instance, ResourceStatus.PROVISIONING)
    except IntegrityError as exc:
        if _is_active_range_conflict(exc):
            logger.warning(
                "create_range: active-range constraint collision for user_id=%s range_source=%s",
                user.id,
                range_source.value,
            )
            raise CMSError(_ACTIVE_RANGE_MESSAGE) from exc
        raise
    return request_id, cms_request, range_instance


def _lookup_agents_by_os(user: User, agents_by_os: dict[str, int]) -> dict[str, AgentConfig]:
    """Resolve each agent ID to an AgentConfig owned by the user."""
    return {os_type: _get_agent_call(user, aid) for os_type, aid in agents_by_os.items()}


def _create_cms_request(user: User) -> tuple[UUID, Request]:
    """Create the CMS Request row and return (request_id, cms_request)."""
    from uuid import uuid4

    from cms.models import Request
    from shared.enums import RequestType

    request_id = uuid4()
    cms_request = Request.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    logger.info(
        "create_range: created CMS Request id=%s for user_id=%s",
        request_id,
        user.id,
    )
    return request_id, cms_request


def _dispatch_engine_range(
    request_id: UUID,
    user: User,
    range_spec: RangeSpec,
    backend_admission: BackendAdmission | None = None,
    remote_access_capability: dict[str, object] | None = None,
) -> None:
    """Dispatch range provisioning to engine for an already-owned CMS request.

    ``backend_admission`` (the trusted #1348 result) is carried beside the
    RequestSpec so the Engine persists the #1666 ownership binding at create.
    """
    from shared.schemas import RequestSpec

    request_spec = RequestSpec(
        request_id=request_id,
        user_id=user.id,
        items=[range_spec],
    )
    _engine_create_range_call(request_spec, backend_admission, remote_access_capability)


def _build_remote_access_capability(
    range_spec: RangeSpec,
    teardown_at: datetime | None,
    *,
    backend_admitted: bool = True,
    required: bool,
) -> dict[str, object] | None:
    """Mint OpenVPN authority when the product and scenario support it."""
    capability = None
    if teardown_at is not None and not backend_admitted:
        if required:
            raise CMSError("OpenVPN access is unavailable on the selected range backend")
    elif teardown_at is not None:
        target_uuid = _remote_access_target_uuid(range_spec)
        if target_uuid is None:
            if required:
                raise CMSError("OpenVPN access requires exactly one identified Kali attacker target")
        else:
            from shared.remote_access import build_openvpn_capability

            capability = build_openvpn_capability(target_uuid, teardown_at)
    return capability


def _remote_access_target_uuid(range_spec: RangeSpec) -> str | None:
    """Return the sole participant-visible Kali attacker UUID, when unambiguous."""
    participant_targets = {binding.target_ref for binding in range_spec.participant_access}
    kali_targets = [
        instance for instance in range_spec.all_instances if instance.role == "attacker" and instance.os_type == "kali"
    ]
    targets = (
        [instance for instance in kali_targets if str(instance.uuid) in participant_targets]
        if participant_targets
        else kali_targets
    )
    if len(targets) != 1:
        return None
    return targets[0].uuid


def _persist_range_instance_record(
    cms_request: Request,
    scenario: str,
    user: User,
    agents: dict[str, AgentConfig],
    range_spec: RangeSpec,
    lease: RangeLease,
    range_source: RangeSource,
) -> RangeInstance:
    """Persist the RangeInstance row tying the CMS Request to the hydrated spec."""
    # Store first agent for backward compatibility (field is nullable).
    first_agent = next(iter(agents.values()), None)
    return RangeInstance.objects.create(
        request=cms_request,
        scenario_id=scenario,
        user_id=user.id,
        agent=first_agent,
        range_source=range_source.value,
        range_spec=wrap_persisted_spec("range_spec", range_spec),
        expires_at=lease.expires_at,
        maximum_expires_at=lease.maximum_expires_at,
    )


def _set_range_instance_status(range_instance: RangeInstance, status: ResourceStatus) -> None:
    """Persist CMS status for a range instance using the existing public vocabulary."""
    range_instance.status = status.value
    range_instance.save(update_fields=["status"])


def _audit_range_provision(
    request_id: UUID,
    scenario: str,
    user: User,
    agents: dict[str, AgentConfig],
    ngfw_enabled: bool,
) -> None:
    """Write the audit-log entry for a successful create_range request."""
    _audit_log_call(
        entity_type=AuditEntityType.RANGE,
        # Range ID not yet assigned at this point.
        entity_id=0,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.USER,
        actor_id=user.id,
        new_state={
            "request_id": str(request_id),
            "scenario": scenario,
            "agents": {os_type: a.name for os_type, a in agents.items()},
            "ngfw_enabled": ngfw_enabled,
        },
        request_id=str(request_id),
    )


def _build_range_context_for_create(
    request_id: UUID,
    scenario: str,
    user: User,
    range_spec: RangeSpec,
    agents: dict[str, AgentConfig],
) -> RangeContext:
    """Build the RangeContext projection returned by create_range."""
    from shared.schemas import InstanceContext, RangeContext

    instance_contexts = [
        InstanceContext(
            uuid=spec.uuid,
            name=spec.name or "",
            role=spec.role,
            os_type=spec.os_type,
            join_domain=spec.join_domain,
        )
        for spec in range_spec.all_instances
    ]
    agent_names = ", ".join(a.name for a in agents.values())
    return RangeContext(
        request_id=request_id,
        # Legacy field, use request_id for new ranges.
        range_id=None,
        scenario_id=scenario,
        user_id=user.id,
        status=ResourceStatus.PROVISIONING,
        instances=instance_contexts,
        agent_name=agent_names,
    )


def create_range(
    user: User,
    scenario: str,
    agents_by_os: dict[str, int],
    ngfw_enabled: bool = False,
    range_source: RangeSource | None = None,
    remote_access_teardown_at: datetime | None = None,
) -> RangeContext:
    """Validate, hydrate, and trigger range provisioning.

    CMS validates scenario and agent requirements, hydrates the scenario
    template with agent details, calls Engine, and stores RangeInstance.

    Args:
        user: User requesting the range
        scenario: Scenario ID (basic, ad_attack_lab)
        agents_by_os: Mapping of OS type to agent ID, e.g. {"windows": 123, "linux": 456}
        ngfw_enabled: Whether to deploy VM-Series NGFW inline
        range_source: Server-derived provenance label (RangeSource enum). Defaults to
            MISSION_CONTROL. Must be set by the product entry point (e.g. the CTF bridge
            passes RangeSource.CTF). Never user-supplied from a request body.
        remote_access_teardown_at: Trusted CTF event cleanup deadline used to
            build the CTF lease. Never accepted from an HTTP request body;
            Mission Control derives its lease entirely inside CMS.

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
    from cms.scenarios.hydrator import hydrate_scenario
    from shared.enums import RangeSource

    if range_source is None:
        range_source = RangeSource.MISSION_CONTROL

    _validate_create_range_user(user)
    _validate_create_range_scenario(user, scenario)
    _validate_create_range_agents_by_os(user, agents_by_os)

    from cms.services._range_lease import build_range_lease

    lease = build_range_lease(
        range_source,
        enforced_deadline=remote_access_teardown_at,
    )

    logger.debug(
        "create_range called for user_id=%s, scenario=%s, agents_by_os=%s, ngfw_enabled=%s, range_source=%s",
        user.id,
        scenario,
        agents_by_os,
        ngfw_enabled,
        range_source.value,
    )

    try:
        backend_admission = _assert_live_fire_backend_admitted()
        _assert_no_active_range(user, range_source)

        _assert_scenario_launchable(scenario)
        scenario_template = _load_scenario_template_or_raise(scenario)
        requirements = scenario_template.get_agent_requirements()
        _check_scenario_agent_requirements(scenario, requirements, agents_by_os)

        agents = _lookup_agents_by_os(user, agents_by_os)
        range_spec = hydrate_scenario(scenario, user.id, agents)
        remote_access_capability = _build_remote_access_capability(
            range_spec,
            lease.maximum_expires_at,
            backend_admitted=_openvpn_backend_admitted(backend_admission),
            required=range_source is RangeSource.CTF,
        )

        def _persist(cms_request: Request) -> RangeInstance:
            """Build the RangeInstance for the reservation from the hydrated spec."""
            return _persist_range_instance_record(
                cms_request,
                scenario,
                user,
                agents,
                range_spec,
                lease,
                range_source,
            )

        request_id, _cms_request, range_instance = _reserve_active_range_slot(user, range_source, _persist)
        try:
            _dispatch_engine_range(
                request_id,
                user,
                range_spec,
                backend_admission,
                remote_access_capability,
            )
        except Exception:
            _set_range_instance_status(range_instance, ResourceStatus.FAILED)
            raise
        _audit_range_provision(request_id, scenario, user, agents, ngfw_enabled)

        logger.debug(
            "create_range completed: request_id=%s, scenario=%s, user_id=%s, range_source=%s",
            request_id,
            scenario,
            user.id,
            range_source.value,
        )
        return _build_range_context_for_create(request_id, scenario, user, range_spec, agents)

    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception("Error in create_range for user_id=%s", user.id)
        raise
