"""CTF-owned event, team, and cohort model-access selector authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.db.models import Model, QuerySet
from pydantic import ValidationError

from ctf.enums import EventCapability, SpareRangeStatus
from ctf.exceptions import CTFError
from ctf.models import CTFCohort, CTFEvent, CTFParticipant, CTFSpareRange, CTFTeam
from shared.model_access import (
    OwnedReference,
    PublisherAuthorityRequirement,
    PublisherAuthorityScope,
    ResolvedSubjectAuthority,
    SelectorKind,
    SelectorResolution,
    SharingSelector,
    compute_digest,
)


class ModelAccessSelectorError(CTFError):
    """Opaque CTF selector denial with no entity-enumeration detail."""

    default_code = "CTF_MODEL_ACCESS_SELECTOR_DENIED"

    def __init__(self) -> None:
        super().__init__("Model-access selector denied")


@dataclass(frozen=True, slots=True)
class _SelectedSubject:
    """A CTF-owned draw and its optional realized range correlation."""

    range_instance_id: int | None
    draw_ref: OwnedReference
    authority_ref: OwnedReference


def _locked_pages[ModelT: Model](queryset: QuerySet[ModelT]) -> tuple[ModelT, ...]:
    """Materialize a locked owner query through bounded keyset pages."""
    rows: list[ModelT] = []
    continuation: int | None = None
    while True:
        page_query = queryset
        if continuation is not None:
            page_query = page_query.filter(pk__gt=continuation)
        page = tuple(page_query.order_by("pk")[:1000])
        rows.extend(page)
        if len(page) < 1000:
            return tuple(rows)
        continuation = page[-1].pk


def _chunks(values: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    """Split identifiers into bounded owner-boundary requests."""
    return tuple(values[index : index + 1000] for index in range(0, len(values), 1000))


def _uuid_ids(values: tuple[str, ...]) -> tuple[UUID, ...]:
    """Parse canonical UUID selector identifiers without enumeration detail."""
    try:
        resolved = tuple(UUID(value) for value in values)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ModelAccessSelectorError() from exc
    if any(str(value) != supplied for value, supplied in zip(resolved, values, strict=True)):
        raise ModelAccessSelectorError()
    return resolved


def _require_event_authority(actor: object, events: tuple[CTFEvent, ...]) -> None:
    """Require range-management authority over every selected event."""
    from ctf.services.authorization import resolve_event_authority

    user = cast(AbstractBaseUser | AnonymousUser | None, actor)
    if any(resolve_event_authority(user, event, capability=EventCapability.RANGES) is None for event in events):
        raise ModelAccessSelectorError()


def _events_for_ids(ids: tuple[UUID, ...]) -> tuple[CTFEvent, ...]:
    """Lock and return the exact requested event set."""
    events = tuple(CTFEvent.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if len(events) != len(ids):
        raise ModelAccessSelectorError()
    return events


def _selector_rows(
    selector: SharingSelector,
) -> tuple[tuple[CTFEvent, ...], tuple[OwnedReference, ...], dict[str, object]]:
    """Resolve an event, team, or cohort selector to locked owner rows."""
    ids = _uuid_ids(selector.ids)
    if selector.kind is SelectorKind.CTF_EVENT:
        events = _events_for_ids(ids)
        refs = tuple(OwnedReference(owner="ctf", reference=f"event:{event.pk}") for event in events)
        return events, refs, {"event_id__in": ids}

    if selector.kind is SelectorKind.CTF_TEAM:
        teams = tuple(CTFTeam.objects.select_for_update().select_related("event").filter(pk__in=ids).order_by("pk"))
        if len(teams) != len(ids):
            raise ModelAccessSelectorError()
        events = _events_for_ids(tuple(sorted({team.event_id for team in teams})))
        refs = tuple(OwnedReference(owner="ctf", reference=f"team:{team.pk}") for team in teams)
        return events, refs, {"team_id__in": ids}

    cohorts = tuple(CTFCohort.objects.select_for_update().select_related("event").filter(pk__in=ids).order_by("pk"))
    if len(cohorts) != len(ids):
        raise ModelAccessSelectorError()
    events = _events_for_ids(tuple(sorted({cohort.event_id for cohort in cohorts})))
    refs = tuple(OwnedReference(owner="ctf", reference=f"cohort:{cohort.pk}") for cohort in cohorts)
    return events, refs, {"cohort_id__in": ids}


def _subjects_for_filter(filters: dict[str, object], *, include_spares: bool) -> tuple[_SelectedSubject, ...]:
    """Resolve eligible participant and optional spare subjects completely."""
    from ctf.services.participant import eligible_participant_q

    participants = _locked_pages(CTFParticipant.objects.select_for_update().filter(eligible_participant_q(), **filters))
    selected = [
        _SelectedSubject(
            range_instance_id=participant.range_instance_id,
            draw_ref=OwnedReference(owner="ctf", reference=f"draw:{participant.pk}"),
            authority_ref=OwnedReference(owner="ctf", reference=f"participant:{participant.pk}"),
        )
        for participant in participants
    ]
    if include_spares:
        spares = _locked_pages(
            CTFSpareRange.objects.select_for_update().filter(
                **filters,
                status__in=(SpareRangeStatus.PROVISIONING.value, SpareRangeStatus.READY.value),
            )
        )
        selected.extend(
            _SelectedSubject(
                range_instance_id=spare.range_instance_id,
                draw_ref=OwnedReference(owner="ctf", reference=f"draw:{spare.pk}"),
                authority_ref=OwnedReference(owner="ctf", reference=f"spare:{spare.pk}"),
            )
            for spare in spares
        )
    realized = [item.range_instance_id for item in selected if item.range_instance_id is not None]
    if len(realized) != len(set(realized)):
        raise ModelAccessSelectorError()
    return tuple(selected)


def _materialize_resolution(
    selector: SharingSelector,
    selector_refs: tuple[OwnedReference, ...],
    selected: tuple[_SelectedSubject, ...],
) -> SelectorResolution:
    """Correlate selected CTF draws and build canonical authority evidence."""
    from ctf.bridges import cms_resolve_model_access_range_instances

    realized_ids = tuple(sorted(item.range_instance_id for item in selected if item.range_instance_id is not None))
    realized_views = tuple(
        view for page in _chunks(realized_ids) for view in cms_resolve_model_access_range_instances(page)
    )
    by_instance = dict(zip(realized_ids, realized_views, strict=True))
    if len(by_instance) != len(realized_ids):
        raise ModelAccessSelectorError()

    member_refs = []
    subject_authorities = []
    for item in selected:
        member_ref = (
            by_instance[item.range_instance_id].range_ref if item.range_instance_id is not None else item.draw_ref
        )
        member_refs.append(member_ref)
        subject_authorities.append(ResolvedSubjectAuthority(subject_ref=member_ref, authority_ref=item.authority_ref))

    digest = compute_digest(selector)
    try:
        return SelectorResolution(
            contract_version="model-access-selector-resolution/v1",
            selector_digest=digest,
            assessment_count=len(member_refs),
            member_refs=tuple(member_refs),
            selector_authority_refs=selector_refs,
            subject_authorities=tuple(subject_authorities),
            publisher_requirements=tuple(
                PublisherAuthorityRequirement(
                    selector_digest=digest,
                    authority_ref=reference,
                    scope=PublisherAuthorityScope.SELECTOR,
                )
                for reference in selector_refs
            ),
        )
    except ValidationError as exc:
        raise ModelAccessSelectorError() from exc


def participant_model_admission_subject(participant: CTFParticipant) -> OwnedReference:
    """Return a participant's authoritative model-access membership subject (PLAT-202).

    Before any range is realized the draw reference is authoritative; once a range
    exists the published sharing membership uses that range's canonical reference
    (see :func:`_materialize_resolution`), so a replacement launch must resolve the
    realized range reference rather than the draw — otherwise a binding published
    against the range would not match and its restriction would be bypassed.

    This must be evaluated **before** any teardown of the range being replaced:
    ``resolve_model_access_range_instances`` excludes a ``DESTROYING`` instance, so
    resolving after teardown would silently fall back to the draw and drop a
    range-scoped restriction. Fail closed (raise) when a realized range cannot be
    resolved rather than substituting the draw identity; the recovery flow captures
    this subject before it blocks the old range. A stale published projection is
    denied downstream by the Engine effective-policy compiler (stale membership →
    indeterminate), so admission is never silently widened.
    """
    if participant.range_instance_id is None:
        return OwnedReference(owner="ctf", reference=f"draw:{participant.pk}")

    from ctf.bridges import cms_resolve_model_access_range_instances

    views = tuple(cms_resolve_model_access_range_instances((participant.range_instance_id,)))
    if len(views) != 1:
        raise ModelAccessSelectorError()
    return views[0].range_ref


def classify_model_access_selected_ranges(range_uuids: tuple[UUID, ...]) -> tuple[UUID, ...]:
    """Return the exact subset backed by CTF participants or spare ranges.

    Classification is authority-neutral but row-locked.  It prevents a range
    that is CTF-owned from falling through to ordinary personal-range policy
    when the actor lacks authority over its event.
    """
    from ctf.bridges import cms_find_model_access_selected_ranges

    normalized = tuple(sorted(range_uuids))
    if not normalized or len(normalized) > 1000 or len(normalized) != len(set(normalized)):
        raise ModelAccessSelectorError()
    with transaction.atomic():
        selected_views = tuple(cms_find_model_access_selected_ranges(normalized))
        instance_ids = tuple(item.range_instance_id for item in selected_views)
        participant_instance_ids = set(
            CTFParticipant.all_objects.select_for_update()
            .filter(range_instance_id__in=instance_ids)
            .values_list("range_instance_id", flat=True)
        )
        spare_instance_ids = set(
            CTFSpareRange.all_objects.select_for_update()
            .filter(range_instance_id__in=instance_ids)
            .values_list("range_instance_id", flat=True)
        )
        ctf_instance_ids = participant_instance_ids | spare_instance_ids
        return tuple(
            sorted(item.range_view.range_uuid for item in selected_views if item.range_instance_id in ctf_instance_ids)
        )


def _resolve_selected_ranges(actor: object, selector: SharingSelector) -> SelectorResolution:
    """Resolve explicit selected ranges through their exact CTF owners."""
    from ctf.bridges import cms_resolve_model_access_selected_ranges
    from ctf.services.participant import eligible_participant_q

    range_uuids = _uuid_ids(selector.ids)
    selected_views = tuple(cms_resolve_model_access_selected_ranges(range_uuids))
    if len(selected_views) != len(range_uuids):
        raise ModelAccessSelectorError()
    instance_ids = tuple(item.range_instance_id for item in selected_views)
    participants = tuple(
        CTFParticipant.objects.select_for_update()
        .select_related("event")
        .filter(eligible_participant_q(), range_instance_id__in=instance_ids)
        .order_by("range_instance_id")
    )
    spares = tuple(
        CTFSpareRange.objects.select_for_update()
        .select_related("event")
        .filter(
            range_instance_id__in=instance_ids,
            status__in=(SpareRangeStatus.PROVISIONING.value, SpareRangeStatus.READY.value),
        )
        .order_by("range_instance_id")
    )
    source_by_instance = {
        participant.range_instance_id: (
            participant.event,
            OwnedReference(owner="ctf", reference=f"participant:{participant.pk}"),
        )
        for participant in participants
    }
    for spare in spares:
        if spare.range_instance_id in source_by_instance:
            raise ModelAccessSelectorError()
        source_by_instance[spare.range_instance_id] = (
            spare.event,
            OwnedReference(owner="ctf", reference=f"spare:{spare.pk}"),
        )
    if set(source_by_instance) != set(instance_ids):
        raise ModelAccessSelectorError()
    events = tuple(
        sorted(
            {event.pk: event for event, _authority in source_by_instance.values()}.values(),
            key=lambda item: item.pk,
        )
    )
    _require_event_authority(actor, events)

    event_refs = tuple(OwnedReference(owner="ctf", reference=f"event:{event.pk}") for event in events)
    source_refs = tuple(source_by_instance[item.range_instance_id][1] for item in selected_views)
    range_refs = tuple(item.range_view.authority_ref for item in selected_views)
    selector_refs = tuple(
        {(item.owner, item.reference): item for item in event_refs + source_refs + range_refs}.values()
    )
    digest = compute_digest(selector)
    return SelectorResolution(
        contract_version="model-access-selector-resolution/v1",
        selector_digest=digest,
        assessment_count=len(selected_views),
        member_refs=tuple(item.range_view.range_ref for item in selected_views),
        selector_authority_refs=selector_refs,
        subject_authorities=tuple(
            ResolvedSubjectAuthority(
                subject_ref=item.range_view.range_ref,
                authority_ref=source_by_instance[item.range_instance_id][1],
            )
            for item in selected_views
        ),
        publisher_requirements=tuple(
            PublisherAuthorityRequirement(
                selector_digest=digest,
                authority_ref=reference,
                scope=PublisherAuthorityScope.SELECTOR,
            )
            for reference in event_refs
        ),
    )


def resolve_model_access_selector(
    actor: object,
    selector: SharingSelector | dict[str, object],
) -> SelectorResolution:
    """Resolve a complete CTF atomic selector under owner-domain row locks."""
    try:
        parsed = selector if isinstance(selector, SharingSelector) else SharingSelector.model_validate(selector)
    except ValidationError as exc:
        raise ModelAccessSelectorError() from exc
    if parsed.kind not in {
        SelectorKind.SELECTED_RANGES,
        SelectorKind.CTF_EVENT,
        SelectorKind.CTF_TEAM,
        SelectorKind.CTF_COHORT,
    }:
        raise ModelAccessSelectorError()

    with transaction.atomic():
        if parsed.kind is SelectorKind.SELECTED_RANGES:
            return _resolve_selected_ranges(actor, parsed)
        events, selector_refs, filters = _selector_rows(parsed)
        _require_event_authority(actor, events)
        selected = _subjects_for_filter(filters, include_spares=parsed.include_spares)
        return _materialize_resolution(parsed, selector_refs, selected)
