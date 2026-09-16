"""Engine-owned model-access sharing records (PLAT-202, M19, #2139).

Engine PostgreSQL is the sole live authority for named collections, sharing
pools and bindings. The mounted installation catalog is validated inventory, not
a parallel evaluator: a definition only affects a range after it passes the
authorized, revision-fenced publication transaction in ``engine.services``.

Revision namespaces are kept explicit and never conflated:

* a stable ``(deployment_id, sharing_binding_id)`` / ``(deployment_id,
  sharing_pool_id)`` names the logical object;
* an immutable **definition revision** (``SharingBindingRevision``) names one
  published form of a binding and is the optimistic compare-and-set fence for
  publish / withdraw / drain;
* a **routing revision** on ``SharingPoolRecord`` names the allocation-affinity
  choice while the stable pool and financial-account IDs survive it;
* a **membership revision** plus a synchronously advanced **fence revision** on
  ``MembershipProjection`` name the authoritative selector result and the point
  before which grants must be reassessed.

Published revisions retain their original references. Nothing here cascade-deletes
a pool or projection that a future allocation, settlement or liability may still
reference; withdrawal tombstones a binding rather than removing it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from django.db import models
from django.utils import timezone

_ACTIVE = "active"
_TOMBSTONED = "tombstoned"
_BINDING_STATES = ((_ACTIVE, "active"), (_TOMBSTONED, "tombstoned"))
_AUTHORITY_STATES = (("allowed", "allowed"), ("revoked", "revoked"), ("unknown", "unknown"))
_DEPLOYMENT_HELP = "Owning deployment; every lookup is deployment-scoped"


class SharingPoolRecord(models.Model):
    """Stable Engine-owned sharing pool: routing/affinity revisions vary, IDs do not.

    The financial-account references (provider/capacity/spend/rate/concurrency)
    are the pool's stable identity and must survive routing revisions; a routing
    change bumps ``routing_revision`` and may re-key allocation groups, but never
    rewrites an account reference (that would silently move money).
    """

    deployment_id = models.UUIDField(db_index=True, help_text=_DEPLOYMENT_HELP)
    sharing_pool_id = models.CharField(max_length=128, help_text="Stable logical pool identity within the deployment")
    routing_revision = models.PositiveIntegerField(help_text="Current allocation-affinity/routing revision of the pool")
    provider_pool_ref = models.CharField(
        max_length=256, blank=True, default="", help_text="Shared provider pool reference, if any"
    )
    capacity_account_ref = models.CharField(
        max_length=256, blank=True, default="", help_text="Shared capacity account reference, if any"
    )
    spend_account_refs = models.JSONField(
        default=list, blank=True, help_text="Distinct shared spend account references"
    )
    rate_account_refs = models.JSONField(default=list, blank=True, help_text="Distinct shared rate account references")
    concurrency_account_refs = models.JSONField(
        default=list, blank=True, help_text="Distinct shared concurrency account references"
    )
    alias_affinities = models.JSONField(
        default=list, blank=True, help_text="Per-alias assignment affinity for the current routing revision"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_sharing_pool"
        ordering = ["deployment_id", "sharing_pool_id"]
        constraints = [
            models.UniqueConstraint(fields=["deployment_id", "sharing_pool_id"], name="engine_sharing_pool_identity"),
        ]

    def __str__(self) -> str:
        return f"{self.sharing_pool_id}@r{self.routing_revision} ({self.deployment_id})"


class SharingPoolRevision(models.Model):
    """One immutable routing revision of a pool: the routing choice a binding pins.

    A pool's financial-account identity is stable and lives on
    :class:`SharingPoolRecord`; its routing content (per-alias affinity, provider
    pool) is versioned here so a later routing change on the pool cannot silently
    change the routing of a binding that was published against an earlier revision.
    """

    pool = models.ForeignKey(
        SharingPoolRecord,
        on_delete=models.PROTECT,
        related_name="routing_revisions",
        help_text="Pool this immutable routing revision belongs to",
    )
    routing_revision = models.PositiveIntegerField(help_text="Monotonic per-pool routing/affinity revision")
    provider_pool_ref = models.CharField(
        max_length=256, blank=True, default="", help_text="Provider pool reference for this routing revision"
    )
    alias_affinities = models.JSONField(
        default=list, blank=True, help_text="Per-alias assignment affinity for this routing revision"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_sharing_pool_revision"
        ordering = ["pool", "-routing_revision"]
        constraints = [
            models.UniqueConstraint(fields=["pool", "routing_revision"], name="engine_sharing_pool_revision_identity"),
        ]

    def __str__(self) -> str:
        return f"{self.pool.sharing_pool_id}#r{self.routing_revision}"


class SharingBindingRecord(models.Model):
    """Stable Engine-owned binding identity pointing at its latest published revision."""

    deployment_id = models.UUIDField(db_index=True, help_text=_DEPLOYMENT_HELP)
    sharing_binding_id = models.CharField(
        max_length=128, help_text="Stable logical binding identity within the deployment"
    )
    pool = models.ForeignKey(
        SharingPoolRecord,
        on_delete=models.PROTECT,
        related_name="bindings",
        help_text="Pool this binding shares from; PROTECT keeps referenced pools from being deleted",
    )
    current_definition_revision = models.PositiveIntegerField(help_text="Latest published definition revision")
    state = models.CharField(max_length=16, choices=_BINDING_STATES, default=_ACTIVE, help_text="active | tombstoned")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_sharing_binding"
        ordering = ["deployment_id", "sharing_binding_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["deployment_id", "sharing_binding_id"], name="engine_sharing_binding_identity"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sharing_binding_id}@r{self.current_definition_revision} {self.state}"


class SharingBindingRevision(models.Model):
    """One immutable published form of a binding: the compare-and-set fence unit.

    Append-only. Withdrawal writes a terminal ``tombstoned`` revision rather than
    editing or deleting an earlier one, so a later retry, settlement or
    reconciliation reads the definition that was actually published.
    """

    binding = models.ForeignKey(
        SharingBindingRecord,
        on_delete=models.CASCADE,
        related_name="revisions",
        help_text="Binding this immutable revision belongs to",
    )
    definition_revision = models.PositiveIntegerField(help_text="Monotonic per-binding definition revision")
    definition_digest = models.CharField(
        max_length=71, help_text="sha256:<64hex> over the canonical published definition"
    )
    definition = models.JSONField(
        help_text="Canonical SharingBinding payload as published (references only, no secrets)"
    )
    catalog_digest = models.CharField(
        max_length=71,
        help_text="Catalog digest pinned at publication; resolution refuses a replacement catalog",
    )
    resolved_profile = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="ModelProfile resolved and frozen at publication, so resolution never re-reads a mutated catalog",
    )
    frozen_members = models.JSONField(
        default=list,
        blank=True,
        help_text="Resolved snapshot membership frozen at publication (empty for dynamic bindings)",
    )
    pool_routing_revision = models.PositiveIntegerField(
        help_text="Immutable pool routing revision this binding was validated against and resolves through",
    )
    selector_digest = models.CharField(
        max_length=71,
        help_text="Digest of the canonical selector; binds membership evidence to the exact published selector",
    )
    membership_mode = models.CharField(max_length=16, help_text="snapshot | dynamic")
    priority = models.PositiveIntegerField(
        help_text="Operator-controlled precedence for non-combinable choices (0-1000)"
    )
    effective_from = models.DateTimeField(help_text="Start of the binding's effective interval")
    effective_until = models.DateTimeField(help_text="End of the binding's effective interval")
    observed_membership_revision = models.PositiveIntegerField(help_text="Membership revision observed at publication")
    observed_assessment_count = models.PositiveIntegerField(
        default=0,
        help_text="Complete automatic population assessed for the published membership revision",
    )
    observed_authority_revisions = models.JSONField(
        default=list,
        help_text="Complete selector-authority fence revisions observed at publication",
    )
    publisher_authority_revisions = models.JSONField(
        default=list,
        help_text="Complete publisher-authority fence revisions checked at publication",
    )
    publisher_owner = models.CharField(max_length=128, help_text="Server-derived publisher owner namespace")
    publisher_reference = models.CharField(
        max_length=256, help_text="Server-derived publisher reference (never trusted from the payload)"
    )
    empty_snapshot_ack = models.BooleanField(
        default=False, help_text="Operator acknowledged an empty resolved snapshot"
    )
    state = models.CharField(max_length=16, choices=_BINDING_STATES, default=_ACTIVE, help_text="active | tombstoned")
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_sharing_binding_revision"
        ordering = ["binding", "-definition_revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["binding", "definition_revision"], name="engine_sharing_binding_revision_identity"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.binding.sharing_binding_id}#{self.definition_revision} {self.state}"


class MembershipProjection(models.Model):
    """Engine-owned authoritative membership projection for one binding's selector.

    Upstream CTF/CMS/identity/workspace owners publish membership through the
    permitted downward bridge (#2140) into this record; Engine never calls those
    domains back. The ``fence_revision`` is advanced synchronously on a binding
    withdrawal or revision change, before any asynchronous grant reassessment, so
    a request can detect a bulk invalidation without a usable stale-grant window.
    """

    deployment_id = models.UUIDField(db_index=True, help_text=_DEPLOYMENT_HELP)
    sharing_binding_id = models.CharField(max_length=128, help_text="Binding whose selector this projection resolves")
    selector_digest = models.CharField(
        max_length=71,
        default="",
        help_text="Digest of the selector this evidence resolves; a new selector version gets a distinct row",
    )
    membership_revision = models.PositiveIntegerField(
        help_text="Authoritative membership revision from the owning service"
    )
    assessment_count = models.PositiveIntegerField(
        default=0,
        help_text="Complete automatic population assessed to produce this projection",
    )
    fence_revision = models.PositiveIntegerField(default=1, help_text="Synchronous binding-local invalidation fence")
    state = models.CharField(
        max_length=16,
        choices=_AUTHORITY_STATES,
        default="unknown",
        help_text="allowed | revoked | unknown",
    )
    member_refs = models.JSONField(
        default=list,
        blank=True,
        help_text="Bounded canonical complete owner-qualified member references",
    )
    selector_authorities = models.JSONField(
        default=list,
        help_text="Complete owner-qualified selector authority references and observed revisions",
    )
    evidence_digest = models.CharField(
        max_length=71,
        default="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        help_text="Digest of the complete canonical authority evidence for replay conflict detection",
    )
    subject_authorizations = models.JSONField(default=list, blank=True)
    publisher_authorities = models.JSONField(default=list, blank=True)
    spending_eligibilities = models.JSONField(default=list, blank=True)
    observed_at = models.DateTimeField(help_text="When the projection was observed from the owning service")
    freshness_deadline = models.DateTimeField(help_text="Instant after which the projection is stale and denies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_sharing_membership_projection"
        ordering = ["deployment_id", "sharing_binding_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["deployment_id", "sharing_binding_id", "selector_digest"],
                name="engine_sharing_membership_projection_identity",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=("allowed", "revoked", "unknown")),
                name="engine_sharing_membership_projection_state",
            ),
            models.CheckConstraint(
                condition=models.Q(membership_revision__gt=0),
                name="engine_sharing_membership_projection_revision",
            ),
            models.CheckConstraint(
                condition=models.Q(fence_revision__gt=0),
                name="engine_sharing_membership_projection_fence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sharing_binding_id} {self.state}@m{self.membership_revision}/f{self.fence_revision}"

    def is_fresh(self, now: datetime | None = None) -> bool:
        """Whether the projection is authoritative right now: allowed and unexpired."""
        moment = now or timezone.now()
        return self.state == "allowed" and self.observed_at <= moment <= self.freshness_deadline


class SharingAuthorityFence(models.Model):
    """Shared synchronously checked revision for one authoritative owner fact.

    Owner services advance this small row inside their mutation transaction.
    Projection refresh and admission compare the complete owner-qualified key,
    revision, and closed state; fan-out reassessment can therefore remain
    bounded without leaving stale authority usable.
    """

    deployment_id = models.UUIDField(db_index=True, help_text=_DEPLOYMENT_HELP)
    authority_owner = models.CharField(max_length=128)
    authority_reference = models.CharField(max_length=256)
    authority_revision = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=_AUTHORITY_STATES, default="unknown")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_sharing_authority_fence"
        ordering = ["deployment_id", "authority_owner", "authority_reference"]
        constraints = [
            models.UniqueConstraint(
                fields=["deployment_id", "authority_owner", "authority_reference"],
                name="engine_sharing_authority_fence_identity",
            ),
            models.CheckConstraint(
                condition=models.Q(authority_revision__gt=0),
                name="engine_sharing_authority_fence_revision",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=("allowed", "revoked", "unknown")),
                name="engine_sharing_authority_fence_state",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.authority_owner}:{self.authority_reference} "
            f"{self.state}@{self.authority_revision} ({self.deployment_id})"
        )


class AllocationGroup(models.Model):
    """Stable allocation-group identity keyed by routing revision, affinity and owner.

    ``per_range`` assignment uses the existing draw UUID and needs no row here.
    ``per_user`` keys on the canonical owner; ``per_pool`` keys on the pool
    routing revision alone. The stable UUID substitutes for the draw UUID in
    ADR-060's rendezvous so retries and later members reuse the pinned assignment;
    allocation *execution* itself belongs to #2120.
    """

    deployment_id = models.UUIDField(db_index=True, help_text=_DEPLOYMENT_HELP)
    sharing_pool_id = models.CharField(max_length=128, help_text="Pool the allocation group belongs to")
    routing_revision = models.PositiveIntegerField(help_text="Pool routing revision this group is pinned to")
    affinity = models.CharField(max_length=16, help_text="per_user | per_pool")
    owner_ref = models.CharField(
        max_length=256, blank=True, default="", help_text="Canonical owner for per_user; empty for per_pool"
    )
    allocation_group_id = models.UUIDField(default=uuid4, editable=False, help_text="Stable allocation-group identity")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_sharing_allocation_group"
        ordering = ["deployment_id", "sharing_pool_id", "routing_revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["deployment_id", "sharing_pool_id", "routing_revision", "affinity", "owner_ref"],
                name="engine_sharing_allocation_group_identity",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sharing_pool_id}@r{self.routing_revision}/{self.affinity}/{self.owner_ref or '-'}"
