"""Select authored preparation intent from an accessible, registered private pack."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError as ModelValidationError

from cms.scenarios.realizability import _trusted_scenario_path
from cms.scenarios.registry import check_scenario_access
from engine.services import request_artifact_preparation
from shared.exceptions import ValidationError
from shared.raes.preparation_contract import (
    PreparationPackage,
    load_preparation_input_bindings,
    load_preparation_requirement,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.services import PreparationView
    from shared.audit import RequestAudit


def prepare_registered_artifact(
    user: User,
    scenario_id: str,
    requirement_address: str,
    adapter_id: UUID,
    specification_id: str,
    *,
    audit: RequestAudit | None = None,
) -> PreparationView:
    """Resolve private bytes server-side; HTTP input cannot invent build permission.

    Catalog access and package conformance are independent of artifact supply.
    The existing trusted staging context checks immutable bytes and contains
    private object packs until public RAES has extracted the exact requirement.
    """
    from cms.models import RaesPackageSource

    if not (user and user.is_active and user.has_perm("engine.prepare_artifacts")):
        raise ValidationError("Artifact preparation access is not permitted")
    try:
        detail = check_scenario_access(scenario_id, user)
    except ValueError as exc:
        raise ValidationError("The preparation package is unavailable") from exc
    source = RaesPackageSource.objects.filter(scenario_id=scenario_id).first()
    if source is None or not detail.get("launchable") or not source.package_digest:
        raise ValidationError("The preparation package is not trusted for use")
    with _trusted_scenario_path(source) as (scenario_path, _):
        if scenario_path is None:
            raise ValidationError("The preparation package integrity check failed")
        try:
            requirement = load_preparation_requirement(scenario_path, requirement_address)
            package = PreparationPackage(
                scenario_id=source.scenario_id,
                package_digest=source.package_digest,
                lock_digest=source.lock_digest,
                requirement_address=requirement_address,
                requirement=requirement,
                specification_id=specification_id,
                input_bindings=load_preparation_input_bindings(scenario_path, requirement),
            )
        except (ValueError, ModelValidationError) as exc:
            raise ValidationError("The authored preparation requirement is unavailable") from exc
    return request_artifact_preparation(user, adapter_id, package.model_dump(mode="json"), audit=audit)
