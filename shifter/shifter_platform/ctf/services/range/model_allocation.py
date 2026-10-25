"""Strict event demand projection for the enforcing model allocation path."""

from uuid import UUID

from django.conf import settings
from django.db import transaction
from pydantic import ValidationError

from ctf.models import CTFEvent, CTFSpareRange
from shared.model_access import ContractError, EventModelDemand, OwnedReference
from shared.model_access.reservation import ModelLaunchScope, SystemPreparationAuthority


def project_event_model_scope(
    event: CTFEvent,
    draw_key: UUID,
    subject: OwnedReference,
    *,
    spare_id: UUID | None = None,
) -> ModelLaunchScope | None:
    """Keep the actual event, stable draw, window and complete typed demand.

    Unlike the advisory compute declaration, malformed model demand cannot be
    dropped. The owning event mutex fences concurrent demand/window mutations.
    """
    from ctf.bridges import cms_project_model_launch_authority

    with transaction.atomic():
        current = CTFEvent.objects.select_for_update().get(pk=event.pk)
        default_demands: tuple[EventModelDemand, ...] = ()
        if not current.model_demand:
            if not getattr(settings, "MODEL_ACCESS_ENABLED", False):
                return None
            from ctf.bridges import cms_project_scenario_model_demands

            default_demands = cms_project_scenario_model_demands(
                current.scenario_id, expected_concurrency=current.max_participants or 1
            )
            if not default_demands:
                return None
        catalog = getattr(settings, "MODEL_ACCESS_CATALOG", None)
        if catalog is None:
            raise ContractError("allocation.policy_unavailable")
        try:
            demands = tuple(EventModelDemand.model_validate(item) for item in current.model_demand) or default_demands
            from ctf.services.event.model_sources import project_event_model_sources

            sponsorship = project_event_model_sources(current)
            system = _system_preparation(current, spare_id) if spare_id is not None else None
            # Selector membership changes as participant ranges materialize, but
            # the launch's event demand/window authority is generation-stable.
            refs: tuple[OwnedReference, ...] = (OwnedReference(owner="ctf", reference=f"event-launch:{current.pk}"),)
            if system is not None:
                refs += (system.authority_ref,)
            revisions = cms_project_model_launch_authority(
                deployment_id=catalog.deployment_id,
                authority_refs=refs,
            )
            return ModelLaunchScope(
                kind="event",
                scope_id=current.pk,
                draw_key=draw_key,
                subject_ref=subject,
                window_start=current.get_spinup_time(),
                window_end=current.get_cleanup_time(),
                demands=demands,
                authority_revisions=revisions,
                system_preparation=system,
                source_sponsorship=sponsorship,
            )
        except ContractError:
            raise
        except (ValidationError, TypeError, ValueError):
            raise ContractError("allocation.event_demand_invalid") from None


def _system_preparation(event: CTFEvent, spare_id: UUID) -> SystemPreparationAuthority:
    """Prove the real unconsumed spare/owner under CTF's locks, not a caller flag."""
    spare = (
        CTFSpareRange.objects.select_for_update(of=("self", "owner_user"))
        .select_related("owner_user")
        .filter(
            pk=spare_id,
            event=event,
            status="provisioning",
            consumed_by__isnull=True,
            owner_user__is_active=False,
            owner_user__profile__deleted_at__isnull=True,
        )
        .first()
    )
    if spare is None or spare.owner_user is None or spare.owner_user.has_usable_password():
        raise ContractError("allocation.system_owner_unavailable")
    return SystemPreparationAuthority(
        owner_ref=OwnedReference(owner="management", reference=f"user:{spare.owner_user_id}"),
        spare_id=spare.pk,
    )
