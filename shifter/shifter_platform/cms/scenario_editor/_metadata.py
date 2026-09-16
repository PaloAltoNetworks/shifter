"""ScenarioMetadata service operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.models import ScenarioMetadata
from cms.scenarios.realizability import get_scenario_realizability
from cms.scenarios.registry import get_catalog_entry
from shared.audit import AuditAction
from shared.log_sanitize import safe_log_value
from shared.raes.realizability import RealizabilityOutcome

from ._common import ScenarioEditorError, audit_scenario_change, validate_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

#: Cap on gaps quoted in a refusal so the message stays readable and bounded.
_MAX_REPORTED_GAPS = 3


def _verify_scenario_exists(scenario_id: str, *, user_id: int) -> None:
    """Confirm the RAES source exists before metadata changes."""
    if get_catalog_entry(scenario_id) is None:
        logger.error(
            "update_metadata: scenario not found, scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
            user_id,
        )
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found")


#: Outcomes that permit publication. ``INDETERMINATE`` is deliberately absent:
#: an assessment that could not be completed is not permission to publish.
_PUBLISHABLE_OUTCOMES = frozenset({RealizabilityOutcome.REALIZABLE, RealizabilityOutcome.NOT_APPLICABLE})

#: Reported when no assessment could be produced at all. Deliberately reuses the
#: INDETERMINATE wording: from the author's side, an entry that cannot be
#: assessed and one whose assessment was inconclusive are the same refusal.
_UNASSESSED_OUTCOME = RealizabilityOutcome.INDETERMINATE


def _assert_publishable(scenario_id: str, *, enabled: bool | None) -> None:
    """Refuse to enable an RAES entry the backend cannot realize (ADR-034-R3).

    This is the authoritative gate. The editor's badge is advisory -- a caller
    can ignore it, drive the API directly, or race a registry change -- so
    realizability is recomputed here, at the boundary that actually flips the
    desired state, and never trusted from the request.

    Only publication is gated: disabling, staff-only toggles, and saving a
    non-realizable pack for staff review all remain allowed.

    A missing assessment (``None``) is a refusal, not a pass. Existence
    verification and assessment are separate lookups, so an entry that vanishes
    or resolves inconsistently between them must fail closed -- "no assessment"
    is not "nothing to assess", and only an explicit ``NOT_APPLICABLE`` result
    means realizability genuinely does not apply.
    """
    if enabled is not True:
        return

    assessment = get_scenario_realizability(scenario_id)
    if assessment is not None and assessment["outcome"] in _PUBLISHABLE_OUTCOMES:
        return

    outcome = assessment["outcome"] if assessment else _UNASSESSED_OUTCOME
    gaps = assessment["gaps"] if assessment else []
    logger.warning(
        "publication refused: scenario_id=%s outcome=%s gap_codes=%s",
        safe_log_value(scenario_id),
        outcome,
        sorted({gap["code"] for gap in gaps}),
    )
    raise ScenarioEditorError(_refusal_message(outcome, gaps))


def _refusal_message(outcome: str, gaps: list[dict[str, str]]) -> str:
    """Explain the refusal using the same bounded gaps the editor renders."""
    detail = "; ".join(f"{gap['address']}: {gap['message']}" for gap in gaps[:_MAX_REPORTED_GAPS])
    if outcome == RealizabilityOutcome.INDETERMINATE:
        lead = "Cannot confirm this scenario is realizable by the selected backend, so it cannot be enabled"
    else:
        lead = "The selected backend cannot realize this scenario, so it cannot be enabled"
    return f"{lead}. {detail}" if detail else f"{lead}."


def update_metadata(
    user: User,
    scenario_id: str,
    *,
    enabled: bool | None = None,
    staff_only: bool | None = None,
) -> ScenarioMetadata:
    """Update availability metadata for a RAES package source."""
    validate_user(user, "update_metadata")
    logger.debug(
        "update_metadata called for user_id=%s, scenario_id=%s",
        user.id,
        safe_log_value(scenario_id),
    )

    try:
        _verify_scenario_exists(scenario_id, user_id=user.id)
        _assert_publishable(scenario_id, enabled=enabled)

        metadata, created = ScenarioMetadata.objects.get_or_create(
            scenario_id=scenario_id,
            defaults={
                "enabled": enabled if enabled is not None else True,
                "staff_only": staff_only if staff_only is not None else False,
                "updated_by": user,
            },
        )

        if not created:
            update_fields = ["updated_by", "updated_at"]
            if enabled is not None:
                metadata.enabled = enabled
                update_fields.append("enabled")
            if staff_only is not None:
                metadata.staff_only = staff_only
                update_fields.append("staff_only")
            metadata.updated_by = user
            metadata.save(update_fields=update_fields)
    except (TypeError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in update_metadata for user_id=%s, scenario_id=%s",
            user.id,
            safe_log_value(scenario_id),
        )
        raise

    audit_scenario_change(
        action=AuditAction.UPDATE,
        actor_id=user.id,
        state={"scenario_id": scenario_id, "enabled": metadata.enabled, "staff_only": metadata.staff_only},
    )
    logger.info(
        "Scenario metadata updated: scenario_id=%s, enabled=%s, staff_only=%s by user_id=%s",
        safe_log_value(scenario_id),
        metadata.enabled,
        metadata.staff_only,
        user.id,
    )
    return metadata
