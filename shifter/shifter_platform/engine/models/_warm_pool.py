"""Warm-range allocation ledger (#28).

The warm pool maintains system-owned, quarantined range generations that an
initial launch can atomically claim. This ledger is the **claim authority**: a
row plus database constraints, never an in-memory queue or a provider tag,
decides which launch owns which generation (preflight #28).

The ledger references an existing Engine ``Request``/``Range`` generation; it does
**not** replace Engine or CMS range state and does **not** add a public lifecycle
enum. Its :class:`WarmRangeGeneration.State` is *private* allocation state and is
deliberately distinct from ``Range.Status`` / ``ResourceStatus``: a warm
generation whose infrastructure is realized is ``READY`` for the pool but must
never be surfaced as a publicly ``READY`` range, because it is quarantined and
inaccessible until activation hands it to a claimant.

The atomic claim is a database transaction *above* the provider adapter:
``select_for_update(skip_locked=True)`` over ready, unclaimed, exact-fingerprint
generations, a conditional ``READY -> CLAIMED`` transition, generation fencing on
``operation_id``, and a partial-unique guarantee that one generation is claimed by
at most one launch. The claim commits before any activation is queued and never
calls a provider while holding a lock.
"""

from __future__ import annotations

import uuid

from django.db import models

from ._range import Range


class WarmRangeGeneration(models.Model):
    """One system-owned, pre-provisioned range generation in the warm pool."""

    class State(models.TextChoices):
        """Private warm-allocation state (never a public range status).

        - ``PROVISIONING``: warm provision dispatched; infrastructure not yet ready.
        - ``READY``: realized, quarantined, unclaimed; eligible for atomic claim.
        - ``CLAIMED``: claimed by a launch; activation queued or in progress.
        - ``UNHEALTHY``: quarantined pending retirement (failed health / suspect).
        - ``RETIRING``: canonical destroy dispatched; capacity still held.
        - ``TERMINAL``: destroy confirmed (provider absence observed); capacity released.
        """

        PROVISIONING = "provisioning", "Provisioning"
        READY = "ready", "Ready (unclaimed)"
        CLAIMED = "claimed", "Claimed (activating)"
        ACTIVATED = "activated", "Activated (consumed; owned by claimant)"
        UNHEALTHY = "unhealthy", "Unhealthy (quarantined)"
        RETIRING = "retiring", "Retiring"
        TERMINAL = "terminal", "Terminal"

    #: The non-terminal, unclaimed states that count against the pool ceiling.
    NONTERMINAL_UNCLAIMED_STATES = (State.PROVISIONING, State.READY)

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Unique identifier for cross-service correlation",
    )
    #: Operator-declared bucket identity (installation warm_pool policy). Scopes
    #: reconciliation and metrics labels; not itself compatibility proof.
    bucket_id = models.CharField(max_length=40, help_text="Warm-pool bucket id from the deployment policy")
    #: The canonical compatibility digest (shared.warm_pool.compatibility). A launch
    #: claims a generation only when its digest equals the launch's digest.
    compatibility_digest = models.CharField(
        max_length=80, db_index=True, help_text="Canonical sha256: compatibility digest (claim match key)"
    )
    #: The exact effective-policy fingerprint the generation was minted under, so a
    #: later config change cannot reinterpret an existing generation (preflight #28).
    effective_policy_fingerprint = models.CharField(
        max_length=80, help_text="sha256: fingerprint of the effective policy at provision time"
    )
    #: The admitted range backend for this generation (aws/gce/gdc).
    backend = models.CharField(max_length=8, help_text="Admitted range backend bound at warm provision")
    #: The range source the bucket serves (e.g. mission-control). Part of the
    #: compatibility class and carried into the activation projection so the ledger
    #: is self-sufficient for activation without a CMS round-trip.
    range_source = models.CharField(max_length=32, help_text="Range source this generation's bucket serves")
    #: The declared capacity partition the generation draws from.
    capacity_partition = models.CharField(max_length=40, help_text="Declared capacity partition (ADR-047 catalog)")
    #: The pool-scoped capacity scope key (``event_ref``-shaped) these draws use.
    #: Reuses the Engine capacity ledger without fabricating a CTF event (#28).
    capacity_scope_ref = models.UUIDField(help_text="Pool capacity scope (Engine capacity ledger event_ref)")
    #: The idempotent capacity draw key for this generation. Held while resources
    #: exist (including after claim); released only after provider absence is observed.
    capacity_draw_key = models.UUIDField(unique=True, help_text="Idempotent capacity draw key for this generation")

    #: The request_id (UUID) correlating this warm generation to its system-owned
    #: CMS Request / Engine Request / RangeInstance. A scalar, not an FK: the ledger
    #: row is created at reservation time (so a warm-prepare provision suppresses
    #: participant access), before the Engine Request exists, and both sides
    #: correlate on this id (the same pattern CMS/Engine range projections use).
    request_id = models.UUIDField(db_index=True, help_text="System-owned request_id this generation is realized under")
    #: The realized Range, once provisioning creates it (null while PROVISIONING).
    range = models.ForeignKey(
        Range,
        on_delete=models.SET_NULL,
        related_name="warm_generation",
        null=True,
        blank=True,
        help_text="Realized system-owned Range (null until provisioned)",
    )
    #: Generation fence: the current operation generation for this row. A stale
    #: provider result carrying a different operation_id is rejected (ADR-043).
    operation_id = models.UUIDField(
        null=True, blank=True, editable=False, help_text="Current operation generation fence"
    )

    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.PROVISIONING,
        db_index=True,
    )
    #: The launch Request UUID that claimed this generation. Partial-unique when
    #: set: a generation is claimed by at most one launch.
    claimed_by_request_id = models.UUIDField(
        null=True, blank=True, help_text="Launch request UUID that atomically claimed this generation"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True, help_text="When the generation became READY (unclaimed)")
    claimed_at = models.DateTimeField(null=True, blank=True, help_text="When the generation was claimed")
    idle_deadline = models.DateTimeField(
        null=True, blank=True, db_index=True, help_text="Warm-idle expiry; a READY generation past this is retired"
    )
    retired_at = models.DateTimeField(null=True, blank=True, help_text="When destroy was confirmed (provider absence)")

    class Meta:
        """Indexes and constraints backing the atomic claim and reconciler sweeps."""

        indexes = [
            # The claim query: ready generations in an authorized bucket carrying the
            # exact compatibility digest, bound by backend/range_source.
            models.Index(fields=["bucket_id", "state", "compatibility_digest"], name="warmgen_claim_idx"),
            # Reconciler scans: by bucket + state, and idle-expiry sweeps.
            models.Index(fields=["state", "idle_deadline"], name="warmgen_reconcile_idx"),
        ]
        constraints = [
            # One generation is claimed by at most one launch. The partial unique
            # index is the database half of the atomic-claim guarantee; the
            # conditional READY->CLAIMED transition under select_for_update is the
            # other half.
            models.UniqueConstraint(
                fields=["claimed_by_request_id"],
                condition=models.Q(claimed_by_request_id__isnull=False),
                name="warmgen_one_claim_per_request",
            ),
            # A claimed generation must record who claimed it and when; an
            # unclaimed generation must not. Keeps the ledger internally honest so
            # a half-written claim cannot masquerade as either state.
            models.CheckConstraint(
                condition=(
                    models.Q(state="claimed", claimed_by_request_id__isnull=False, claimed_at__isnull=False)
                    | (~models.Q(state="claimed") & models.Q(claimed_by_request_id__isnull=True))
                    # Any post-claim state (a consumed activation, an unhealthy
                    # failed activation, or a retiring/terminal teardown) retains its
                    # claim provenance if it was claimed before the transition; allow
                    # claimed_by to persist once set by permitting it on those states.
                    # Pre-claim active states (provisioning/ready) still require a
                    # null claimed_by via the clause above.
                    | models.Q(state__in=["activated", "unhealthy", "retiring", "terminal"])
                ),
                name="warmgen_claim_consistency",
            ),
        ]

    def __str__(self) -> str:
        return f"WarmRangeGeneration({self.bucket_id}/{self.state} {self.uuid})"
