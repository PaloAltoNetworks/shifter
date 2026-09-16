"""Closed sharing membership and authority evidence contracts (PLAT-202 M20).

Owning services project these dependency-light DTOs downward into Engine.  A
projection intentionally keeps collection membership, live subject authority,
publisher authority, and spending eligibility as independent facts and
revision namespaces.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from shared.model_access.core_models import (
    ClosedModel,
    Digest,
    Identifier,
    NonNegativeInt,
    OwnedReference,
    PositiveInt,
)


class AuthorityState(StrEnum):
    """Closed fail-safe state shared by all projected authority facts."""

    ALLOWED = "allowed"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


class EligibilityBasis(StrEnum):
    """Approved basis for funded access through a group selector."""

    MANAGED_MEMBERSHIP = "managed_membership"
    APPROVED_SPENDING = "approved_spending"


class PublisherAuthorityScope(StrEnum):
    """Closed scope proven by an owning publisher-authority adapter."""

    SELECTOR = "selector"
    DEPLOYMENT = "deployment"


def _reference_key(reference: OwnedReference) -> tuple[str, str]:
    """Return the stable sort and uniqueness key for a qualified reference."""
    return reference.owner, reference.reference


def _require_unique(keys: tuple[object, ...], message: str) -> None:
    """Reject duplicate canonical evidence keys."""
    if len(keys) != len(set(keys)):
        raise ValueError(message)


class SubjectAuthorizationEvidence(ClosedModel):
    """Live authority for one complete owner-qualified member reference."""

    subject_ref: OwnedReference
    authority_ref: OwnedReference
    authority_revision: PositiveInt
    state: AuthorityState


class SelectorAuthorityEvidence(ClosedModel):
    """One authoritative owner fact contributing to a selector or bounded union."""

    authority_ref: OwnedReference
    authority_revision: PositiveInt
    state: AuthorityState


class PublisherAuthorityEvidence(ClosedModel):
    """Server-derived authority for one publisher over the complete selector."""

    publisher_ref: OwnedReference
    authority_ref: OwnedReference
    authority_revision: PositiveInt
    selector_digest: Digest
    scope: PublisherAuthorityScope
    state: AuthorityState


class SpendingEligibilityEvidence(ClosedModel):
    """Independent approval allowing a group selector to activate funded facets."""

    authority_ref: OwnedReference
    eligibility_revision: PositiveInt
    state: AuthorityState
    basis: EligibilityBasis


class AuthorityInvalidation(ClosedModel):
    """Bounded command emitted by an owning service in its mutation transaction."""

    deployment_id: UUID | None
    authority_refs: Annotated[tuple[OwnedReference, ...], Field(min_length=1, max_length=64)]
    state: AuthorityState
    reason: Identifier

    @field_validator("authority_refs")
    @classmethod
    def _normalize_authority_refs(cls, values: tuple[OwnedReference, ...]) -> tuple[OwnedReference, ...]:
        normalized = tuple(sorted(values, key=_reference_key))
        if len(normalized) != len({_reference_key(item) for item in normalized}):
            raise ValueError("authority_refs must be unique")
        return normalized


class ResolvedSubjectAuthority(ClosedModel):
    """Owner resolver's stable authority source for one resolved subject."""

    subject_ref: OwnedReference
    authority_ref: OwnedReference


class ModelAccessRangeView(ClosedModel):
    """Canonical Engine range identity exposed to authorized owner resolvers."""

    range_ref: OwnedReference
    authority_ref: OwnedReference
    range_uuid: UUID
    owner_user_id: PositiveInt
    workspace_id: PositiveInt
    request_uuid: UUID | None = None


class ModelAccessRangePage(ClosedModel):
    """One bounded keyset page from an automatic Engine range assessment."""

    items: Annotated[tuple[ModelAccessRangeView, ...], Field(max_length=1000)]
    assessment_count: NonNegativeInt
    continuation: UUID | None = None

    @model_validator(mode="after")
    def _validate_page(self) -> ModelAccessRangePage:
        range_uuids = tuple(item.range_uuid for item in self.items)
        if range_uuids != tuple(sorted(range_uuids)) or len(range_uuids) != len(set(range_uuids)):
            raise ValueError("range page items must be unique and sorted")
        if self.assessment_count < len(self.items):
            raise ValueError("assessment_count cannot be smaller than the current page")
        if self.continuation is not None and (not self.items or self.continuation != self.items[-1].range_uuid):
            raise ValueError("continuation must identify the last item in a non-empty page")
        return self


class ModelAccessRangeInstanceView(ClosedModel):
    """CMS correlation from a range-instance PK to a canonical Engine range."""

    range_instance_id: PositiveInt
    range_view: ModelAccessRangeView


class PublisherAuthorityRequirement(ClosedModel):
    """Authority source and scope a publisher must satisfy for one selector atom."""

    selector_digest: Digest
    authority_ref: OwnedReference
    scope: PublisherAuthorityScope


class ResolvedSpendingEligibility(ClosedModel):
    """Owner resolver's explicit source and basis for funded eligibility."""

    authority_ref: OwnedReference
    basis: EligibilityBasis


class SelectorResolution(ClosedModel):
    """Revision-free owner result consumed by the downward Engine projector."""

    contract_version: Literal["model-access-selector-resolution/v1"]
    selector_digest: Digest
    assessment_count: NonNegativeInt
    member_refs: tuple[OwnedReference, ...]
    selector_authority_refs: Annotated[tuple[OwnedReference, ...], Field(min_length=1)]
    subject_authorities: tuple[ResolvedSubjectAuthority, ...]
    publisher_requirements: Annotated[tuple[PublisherAuthorityRequirement, ...], Field(min_length=1, max_length=1000)]
    spending_eligibilities: Annotated[tuple[ResolvedSpendingEligibility, ...], Field(max_length=1000)] = ()

    @field_validator("member_refs", "selector_authority_refs")
    @classmethod
    def _sort_refs(cls, values: tuple[OwnedReference, ...]) -> tuple[OwnedReference, ...]:
        return tuple(sorted(values, key=_reference_key))

    @field_validator("subject_authorities")
    @classmethod
    def _sort_subjects(cls, values: tuple[ResolvedSubjectAuthority, ...]) -> tuple[ResolvedSubjectAuthority, ...]:
        return tuple(sorted(values, key=lambda item: _reference_key(item.subject_ref)))

    @field_validator("publisher_requirements")
    @classmethod
    def _sort_publishers(
        cls, values: tuple[PublisherAuthorityRequirement, ...]
    ) -> tuple[PublisherAuthorityRequirement, ...]:
        return tuple(
            sorted(
                values,
                key=lambda item: (item.selector_digest, _reference_key(item.authority_ref), item.scope.value),
            )
        )

    @field_validator("spending_eligibilities")
    @classmethod
    def _sort_spending(cls, values: tuple[ResolvedSpendingEligibility, ...]) -> tuple[ResolvedSpendingEligibility, ...]:
        return tuple(sorted(values, key=lambda item: (_reference_key(item.authority_ref), item.basis.value)))

    @model_validator(mode="after")
    def _validate_resolution(self) -> SelectorResolution:
        member_keys = tuple(_reference_key(item) for item in self.member_refs)
        if len(member_keys) != len(set(member_keys)):
            raise ValueError("member_refs must contain unique owner-qualified references")
        if self.assessment_count != len(member_keys):
            raise ValueError("assessment_count must equal the complete resolved member count")
        selector_keys = tuple(_reference_key(item) for item in self.selector_authority_refs)
        if len(selector_keys) != len(set(selector_keys)):
            raise ValueError("selector_authority_refs must be unique")
        subject_keys = tuple(_reference_key(item.subject_ref) for item in self.subject_authorities)
        if len(subject_keys) != len(set(subject_keys)) or set(subject_keys) != set(member_keys):
            raise ValueError("every member_ref requires exactly one resolved subject authority")
        publisher_keys = tuple(
            (item.selector_digest, _reference_key(item.authority_ref), item.scope.value)
            for item in self.publisher_requirements
        )
        if len(publisher_keys) != len(set(publisher_keys)):
            raise ValueError("publisher requirements must be unique")
        spending_keys = tuple(
            (_reference_key(item.authority_ref), item.basis.value) for item in self.spending_eligibilities
        )
        if len(spending_keys) != len(set(spending_keys)):
            raise ValueError("spending eligibility sources must be unique")
        return self


class SharingAuthorityEvidence(ClosedModel):
    """Bounded authoritative projection for one binding selector.

    ``member_refs`` is inclusion only.  Every included member carries a
    separate subject-authorization fact so a snapshot can freeze inclusion
    without freezing authorization.  Publisher and spending evidence remain
    separate because neither collection membership nor self-service group
    membership grants either authority.
    """

    contract_version: Literal["model-access-sharing-authority/v1"]
    deployment_id: UUID
    sharing_binding_id: Identifier
    selector_digest: Digest
    membership_revision: PositiveInt
    assessment_count: NonNegativeInt
    selector_authorities: Annotated[tuple[SelectorAuthorityEvidence, ...], Field(min_length=1)]
    state: AuthorityState
    member_refs: tuple[OwnedReference, ...]
    subject_authorizations: tuple[SubjectAuthorizationEvidence, ...]
    publisher_authorities: Annotated[tuple[PublisherAuthorityEvidence, ...], Field(min_length=1, max_length=1000)]
    spending_eligibilities: Annotated[tuple[SpendingEligibilityEvidence, ...], Field(max_length=1000)] = ()
    observed_at: datetime
    freshness_deadline: datetime

    @field_validator("member_refs")
    @classmethod
    def _sort_member_refs(cls, values: tuple[OwnedReference, ...]) -> tuple[OwnedReference, ...]:
        return tuple(sorted(values, key=_reference_key))

    @field_validator("selector_authorities")
    @classmethod
    def _sort_selector_authorities(
        cls, values: tuple[SelectorAuthorityEvidence, ...]
    ) -> tuple[SelectorAuthorityEvidence, ...]:
        return tuple(sorted(values, key=lambda item: _reference_key(item.authority_ref)))

    @field_validator("subject_authorizations")
    @classmethod
    def _sort_subject_authorizations(
        cls, values: tuple[SubjectAuthorizationEvidence, ...]
    ) -> tuple[SubjectAuthorizationEvidence, ...]:
        return tuple(sorted(values, key=lambda item: _reference_key(item.subject_ref)))

    @field_validator("publisher_authorities")
    @classmethod
    def _sort_publisher_authorities(
        cls, values: tuple[PublisherAuthorityEvidence, ...]
    ) -> tuple[PublisherAuthorityEvidence, ...]:
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    _reference_key(item.publisher_ref),
                    item.selector_digest,
                    _reference_key(item.authority_ref),
                    item.scope.value,
                ),
            )
        )

    @field_validator("spending_eligibilities")
    @classmethod
    def _sort_spending_eligibilities(
        cls, values: tuple[SpendingEligibilityEvidence, ...]
    ) -> tuple[SpendingEligibilityEvidence, ...]:
        return tuple(sorted(values, key=lambda item: (_reference_key(item.authority_ref), item.basis.value)))

    @model_validator(mode="after")
    def _validate_projection(self) -> SharingAuthorityEvidence:
        member_keys = tuple(_reference_key(item) for item in self.member_refs)
        _require_unique(member_keys, "member_refs must contain unique owner-qualified references")
        if self.assessment_count != len(member_keys):
            raise ValueError("assessment_count must equal the complete projected member count")

        selector_keys = tuple(_reference_key(item.authority_ref) for item in self.selector_authorities)
        _require_unique(selector_keys, "selector authority references must be unique")

        subject_keys = tuple(_reference_key(item.subject_ref) for item in self.subject_authorizations)
        _require_unique(subject_keys, "subject authorization references must be unique")
        if set(subject_keys) != set(member_keys):
            raise ValueError("every member_ref requires exactly one subject authorization")

        publisher_keys = tuple(
            (
                _reference_key(item.publisher_ref),
                item.selector_digest,
                _reference_key(item.authority_ref),
                item.scope.value,
            )
            for item in self.publisher_authorities
        )
        _require_unique(publisher_keys, "publisher authority references and selector digests must be unique")

        eligibility_keys = tuple(
            (_reference_key(item.authority_ref), item.basis.value) for item in self.spending_eligibilities
        )
        _require_unique(eligibility_keys, "spending eligibility references and bases must be unique")

        if self.observed_at.tzinfo is None or self.freshness_deadline.tzinfo is None:
            raise ValueError("authority evidence times must include timezones")
        if self.freshness_deadline <= self.observed_at:
            raise ValueError("freshness_deadline must be after observed_at")
        return self

    def subject_authorization_for(
        self, subject: OwnedReference | dict[str, str]
    ) -> SubjectAuthorizationEvidence | None:
        """Return the exact owner-qualified subject evidence, never a string-only match."""
        subject_ref = subject if isinstance(subject, OwnedReference) else OwnedReference.model_validate(subject)
        return next((item for item in self.subject_authorizations if item.subject_ref == subject_ref), None)

    def publisher_authority_for(self, publisher: OwnedReference | dict[str, str]) -> PublisherAuthorityEvidence | None:
        """Return authority for an exact server-derived publisher reference."""
        publisher_ref = publisher if isinstance(publisher, OwnedReference) else OwnedReference.model_validate(publisher)
        return next((item for item in self.publisher_authorities if item.publisher_ref == publisher_ref), None)

    def has_funded_eligibility(self) -> bool:
        """Whether an independently approved funded-access basis is currently allowed."""
        return any(item.state is AuthorityState.ALLOWED for item in self.spending_eligibilities)
