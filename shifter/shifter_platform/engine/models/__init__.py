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
- ``_launch``: ProvisionerLaunchStatus, ProvisionerLaunchIntent.
- ``_aces``: AcesImageMapping, AcesContentDeliveryBinding.

All models are re-exported here so Django's app registry discovers them via
``engine.models`` and callers keep using ``from engine.models import X``
exactly as before the split.
"""

from ._aces import AcesContentDeliveryBinding, AcesImageMapping
from ._capacity import CapacityDeclaration
from ._launch import ProvisionerLaunchIntent, ProvisionerLaunchStatus
from ._outbox import OutboxStatus, RangeEventOutbox
from ._range import Range
from ._request import App, Instance, Instantiation, Request
from ._subnet import Subnet, SubnetAllocation

__all__ = [
    "AcesContentDeliveryBinding",
    "AcesImageMapping",
    "App",
    "CapacityDeclaration",
    "Instance",
    "Instantiation",
    "OutboxStatus",
    "ProvisionerLaunchIntent",
    "ProvisionerLaunchStatus",
    "Range",
    "RangeEventOutbox",
    "Request",
    "Subnet",
    "SubnetAllocation",
]
