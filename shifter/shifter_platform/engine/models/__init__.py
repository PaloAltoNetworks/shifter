"""Engine models.

Infrastructure lifecycle models for Shifter platform.

- Request: Provisioning request container (1:1 with RequestSpec)
- Instantiation: Abstract base for materialized specs
- Range: User's cyber range instance with provisioned infrastructure
- NGFW: User's Next-Generation Firewall with AWS resources
- SubnetAllocation: CIDR reservation to prevent race conditions during provisioning

Split into a package (#561) so no module exceeds 500 lines. Django app_label,
table names, and every field/Meta/method are unchanged - this is a pure module
reorganization with zero migration drift. The implementation is spread across
private submodules by domain:

- ``_request``: Request, Instantiation (abstract base), Instance, App.
- ``_range``: Range (depends on ``_request.Request``).
- ``_subnet``: Subnet, SubnetAllocation (depends on ``_range.Range`` and
  ``_request.Instantiation``).
- ``_outbox``: OutboxStatus, RangeEventOutbox.
- ``_launch``: ProvisionerLaunchStatus, InterruptState, ProvisionerLaunchIntent.
- ``_raes``: RaesImageMapping, RaesContentDeliveryBinding, RaesParticipantAccessBinding,
  RaesArtifactSatisfactionBinding.

All models are re-exported here so Django's app registry discovers them via
``engine.models`` and callers keep using ``from engine.models import X``
exactly as before the split.
"""

from ._capacity import CapacityDeclaration
from ._capacity_assessment import CapacityAssessment, CapacityDraw, CapacityReservation
from ._cleanup_verification import CleanupVerificationOutcome, RangeCleanupVerification
from ._launch import InterruptState, ProvisionerLaunchIntent, ProvisionerLaunchStatus
from ._operation_io import (
    OperationInput,
    OperationResultDisposition,
    OperationResultInbox,
    OperationResultKind,
)
from ._outbox import OutboxStatus, RangeEventOutbox
from ._preparation import (
    PreparationAdapter,
    PreparationAttempt,
    PreparationGrant,
    PreparationOperation,
    PreparationScopeLock,
    PreparedArtifactAdmission,
)
from ._raes import (
    RaesArtifactSatisfactionBinding,
    RaesContentDeliveryBinding,
    RaesImageMapping,
    RaesParticipantAccessBinding,
)
from ._range import Range
from ._receipt import ReceiptVerifierRegistration
from ._request import App, Instance, Instantiation, Request
from ._retry_binding import PublicOperationRetryBinding, RetryBindingStatus
from ._sharing import (
    AllocationGroup,
    MembershipProjection,
    SharingAuthorityFence,
    SharingBindingRecord,
    SharingBindingRevision,
    SharingPoolRecord,
    SharingPoolRevision,
)
from ._subnet import Subnet, SubnetAllocation
from ._warm_pool import WarmRangeGeneration

__all__ = [
    "AllocationGroup",
    "App",
    "CapacityAssessment",
    "CapacityDeclaration",
    "CapacityDraw",
    "CapacityReservation",
    "CleanupVerificationOutcome",
    "Instance",
    "Instantiation",
    "InterruptState",
    "MembershipProjection",
    "OperationInput",
    "OperationResultDisposition",
    "OperationResultInbox",
    "OperationResultKind",
    "OutboxStatus",
    "PreparationAdapter",
    "PreparationAttempt",
    "PreparationGrant",
    "PreparationOperation",
    "PreparationScopeLock",
    "PreparedArtifactAdmission",
    "ProvisionerLaunchIntent",
    "ProvisionerLaunchStatus",
    "PublicOperationRetryBinding",
    "RaesArtifactSatisfactionBinding",
    "RaesContentDeliveryBinding",
    "RaesImageMapping",
    "RaesParticipantAccessBinding",
    "Range",
    "RangeCleanupVerification",
    "RangeEventOutbox",
    "ReceiptVerifierRegistration",
    "Request",
    "RetryBindingStatus",
    "SharingAuthorityFence",
    "SharingBindingRecord",
    "SharingBindingRevision",
    "SharingPoolRecord",
    "SharingPoolRevision",
    "Subnet",
    "SubnetAllocation",
    "WarmRangeGeneration",
]
