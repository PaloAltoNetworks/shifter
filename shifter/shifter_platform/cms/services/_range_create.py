"""Range provisioning: create_range plus its hydration/dispatch helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from cms.exceptions import CMSError
from cms.models import AgentConfig, RangeInstance
from risk_register.models import AuditLog
from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED
from shared.enums import ResourceStatus

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import Request
    from cms.scenarios.schema import ScenarioTemplate
    from shared.schemas.range import RangeContext, RangeSpec

logger = logging.getLogger(__name__)


def _engine_create_range_call(request_spec: Any) -> Any:
    """Late-bound call to ``cms.services.engine_create_range`` so test patches apply."""
    from cms import services as _cs

    return _cs.engine_create_range(request_spec)


def _audit_log_call(**kwargs: Any) -> None:
    """Late-bound call to ``cms.services.audit_log`` so test patches apply."""
    from cms import services as _cs

    _cs.audit_log(**kwargs)


def _get_active_range_call(user: User) -> Any:
    """Look up active range through the package to honor test patches."""
    from cms import services as _cs

    return _cs.get_active_range(user)


def _get_agent_call(user: User, agent_id: int) -> AgentConfig:
    """Look up agent through the package to honor test patches."""
    from cms import services as _cs

    return _cs.get_agent(user, agent_id)


def _validate_create_range_user(user: User) -> None:
    """Validate the ``user`` argument shape for create_range."""
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


def _validate_create_range_scenario(user: User, scenario: str) -> None:
    """Validate the ``scenario`` argument shape for create_range."""
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


def _validate_create_range_agents_by_os(user: User, agents_by_os: dict[str, int]) -> None:
    """Validate the ``agents_by_os`` argument shape for create_range."""
    if agents_by_os is None:
        logger.error(
            "create_range called with None agents_by_os for user_id=%s",
            user.id,
        )
        raise TypeError("agents_by_os cannot be None")
    if not isinstance(agents_by_os, dict):
        logger.error(
            "create_range called with invalid agents_by_os type: %s",
            type(agents_by_os).__name__,
        )
        msg = f"agents_by_os must be a dict, got {type(agents_by_os).__name__}"
        raise TypeError(msg)


def _assert_no_active_range(user: User) -> None:
    """Raise CMSError if the user already has an active range."""
    existing = _get_active_range_call(user)
    if existing:
        logger.warning(
            "create_range: user_id=%s already has active range request_id=%s",
            user.id,
            existing.range_id,
        )
        msg = "You already have an active range. Please destroy it before creating a new one."
        raise CMSError(msg)


def _load_scenario_template_or_raise(scenario: str) -> ScenarioTemplate:
    """Return the scenario template or raise CMSError if not found."""
    from cms.scenarios.registry import load_scenario_template as load_scenario

    try:
        return load_scenario(scenario)
    except ValueError as e:
        logger.error("create_range: scenario '%s' not found", scenario)
        raise CMSError(str(e)) from e


def _check_scenario_agent_requirements(
    scenario: str, requirements: dict[str, bool], agents_by_os: dict[str, int]
) -> None:
    """Raise CMSError when scenario requirements are not met by agents_by_os."""
    if requirements["requires_windows"] and "windows" not in agents_by_os:
        raise CMSError(f"Scenario '{scenario}' requires a Windows agent")
    if requirements["requires_linux"] and "linux" not in agents_by_os:
        raise CMSError(f"Scenario '{scenario}' requires a Linux agent")
    if requirements["has_from_agent"] and not agents_by_os:
        raise CMSError(f"Scenario '{scenario}' requires at least one agent")


def _lookup_agents_by_os(user: User, agents_by_os: dict[str, int]) -> dict[str, AgentConfig]:
    """Resolve each agent ID to an AgentConfig owned by the user."""
    return {os_type: _get_agent_call(user, aid) for os_type, aid in agents_by_os.items()}


def _create_cms_request_and_dispatch_engine(user: User, range_spec: RangeSpec) -> tuple[UUID, Request]:
    """Create the CMS Request row, dispatch the engine, return (request_id, cms_request)."""
    from uuid import uuid4

    from cms.models import Request
    from shared.enums import RequestType
    from shared.schemas import RequestSpec

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
    request_spec = RequestSpec(
        request_id=request_id,
        user_id=user.id,
        items=[range_spec],
    )
    _engine_create_range_call(request_spec)
    return request_id, cms_request


def _persist_range_instance_record(
    cms_request: Request,
    scenario: str,
    user: User,
    agents: dict[str, AgentConfig],
    range_spec: RangeSpec,
) -> None:
    """Persist the RangeInstance row tying the CMS Request to the hydrated spec."""
    # Store first agent for backward compatibility (field is nullable).
    first_agent = next(iter(agents.values()), None)
    RangeInstance.objects.create(
        request=cms_request,
        scenario_id=scenario,
        user_id=user.id,
        agent=first_agent,
        range_spec=range_spec.model_dump(mode="json"),
    )


def _audit_range_provision(
    request_id: UUID,
    scenario: str,
    user: User,
    agents: dict[str, AgentConfig],
    ngfw_enabled: bool,
) -> None:
    """Write the audit-log entry for a successful create_range request."""
    _audit_log_call(
        entity_type=AuditLog.EntityType.RANGE,
        # Range ID not yet assigned at this point.
        entity_id=0,
        action=AuditLog.Action.PROVISION,
        actor_type=AuditLog.ActorType.USER,
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
) -> RangeContext:
    """Validate, hydrate, and trigger range provisioning.

    CMS validates scenario and agent requirements, hydrates the scenario
    template with agent details, calls Engine, and stores RangeInstance.

    Args:
        user: User requesting the range
        scenario: Scenario ID (basic, ad_attack_lab)
        agents_by_os: Mapping of OS type to agent ID, e.g. {"windows": 123, "linux": 456}
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
    from cms.scenarios.hydrator import hydrate_scenario

    _validate_create_range_user(user)
    _validate_create_range_scenario(user, scenario)
    _validate_create_range_agents_by_os(user, agents_by_os)

    logger.debug(
        "create_range called for user_id=%s, scenario=%s, agents_by_os=%s, ngfw_enabled=%s",
        user.id,
        scenario,
        agents_by_os,
        ngfw_enabled,
    )

    try:
        _assert_no_active_range(user)

        scenario_template = _load_scenario_template_or_raise(scenario)
        requirements = scenario_template.get_agent_requirements()
        _check_scenario_agent_requirements(scenario, requirements, agents_by_os)

        agents = _lookup_agents_by_os(user, agents_by_os)
        range_spec = hydrate_scenario(scenario, user.id, agents)

        request_id, cms_request = _create_cms_request_and_dispatch_engine(user, range_spec)
        _persist_range_instance_record(cms_request, scenario, user, agents, range_spec)
        _audit_range_provision(request_id, scenario, user, agents, ngfw_enabled)

        logger.debug(
            "create_range completed: request_id=%s, scenario=%s, user_id=%s",
            request_id,
            scenario,
            user.id,
        )
        return _build_range_context_for_create(request_id, scenario, user, range_spec, agents)

    except (TypeError, ValueError, CMSError):
        raise
    except Exception:
        logger.exception("Error in create_range for user_id=%s", user.id)
        raise
