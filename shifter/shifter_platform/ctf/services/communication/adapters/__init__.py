"""Channel adapter seam for the scoped-communication delivery engine (#2098).

Re-exports the command/result contract and closed registry from :mod:`.contract`
and performs the explicit, closed registration of the in-app adapter at import.
"""

from __future__ import annotations

from .contract import (
    ChannelAdapter,
    DeliveryCommand,
    DeliveryOutcome,
    OutcomeClass,
    get_adapter,
    register_adapter,
    registered_channels,
)
from .inapp import InAppAdapter

# Closed, explicit registration (not a dynamic plugin hook / AppConfig.ready).
register_adapter(InAppAdapter())

__all__ = [
    "ChannelAdapter",
    "DeliveryCommand",
    "DeliveryOutcome",
    "InAppAdapter",
    "OutcomeClass",
    "get_adapter",
    "register_adapter",
    "registered_channels",
]
