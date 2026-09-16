"""Explicitly run contract conformance for an immutable registered pack."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import transaction

from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.auth import validate_cms_authoring_user
from shared.exceptions import ValidationError
from shared.raes.pack_conformance import validate_pack_contract

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import RaesPackageSource


def validate_registered_pack_conformance(*, user: User, scenario_id: str, expected_package_digest: str) -> str:
    """Verify current private bytes, compile through the actual backend, then CAS.

    Callers supply identity and request validation; they cannot supply a result
    or a trusted report. The same check is usable after tenant setup for object
    packs. It creates no range, availability record, adapter or worker authority.
    """
    from cms.models import RaesPackageSource
    from cms.scenarios.realizability import _trusted_scenario_path
    from cms.scenarios.registry import check_scenario_access

    validate_cms_authoring_user(user, "validate_pack_conformance")
    try:
        check_scenario_access(scenario_id, user)
    except ValueError as exc:
        raise ValidationError("The pack is unavailable for conformance validation") from exc
    source = RaesPackageSource.objects.filter(scenario_id=scenario_id).first()
    if source is None or not expected_package_digest or source.package_digest != expected_package_digest:
        raise ValidationError("The pack identity changed before conformance validation")
    identity = _identity(source)
    report = "urn:shifter:pack-conformance:" + str(uuid4())
    try:
        with _trusted_scenario_path(source) as (scenario_path, _):
            if scenario_path is None:
                raise ValueError("pack integrity verification failed")
            validate_pack_contract(scenario_path, report)
    except Exception as exc:
        # Private parser diagnostics and storage references never leave this gate.
        raise ValidationError("The registered pack failed contract conformance") from exc
    with transaction.atomic():
        current = RaesPackageSource.objects.select_for_update().get(pk=source.pk)
        if _identity(current) != identity:
            raise ValidationError("The pack identity changed during conformance validation")
        current.conformance_status = "passed"
        current.conformance_report_ref = report
        current.save(update_fields=["conformance_status", "conformance_report_ref", "updated_at"])
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.SCENARIO,
                entity_id=0,
                action=AuditAction.UPDATE,
                actor_type=AuditActorType.USER,
                actor_id=user.id,
                new_state={
                    "scenario_id": scenario_id,
                    "package_digest": expected_package_digest,
                    "conformance_status": "passed",
                    "conformance_report_ref": report,
                },
            ),
            strict=True,
        )
    return "passed"


def _identity(source: RaesPackageSource) -> tuple[str, ...]:
    """Handle identity."""
    return tuple(
        getattr(source, key)
        for key in (
            "source_kind",
            "contract_kind",
            "contract_profile",
            "package_ref",
            "package_version",
            "package_digest",
            "lock_ref",
            "lock_digest",
        )
    )
