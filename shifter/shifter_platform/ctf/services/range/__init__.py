"""CTF Range service.

Provides integration with Shifter's range infrastructure for CTF events. This
package facade re-exports the public service surface; implementation is split by
responsibility across private submodules:

- :mod:`ctf.services.range.provision` -- single-participant provisioning + retry
- :mod:`ctf.services.range.batch` -- event-level throttled provisioning
- :mod:`ctf.services.range.tasks` -- spin-up task enqueue + progress projection
- :mod:`ctf.services.range.lifecycle` -- stop/start/restart/destroy + cleanup
- :mod:`ctf.services.range.status` -- range status reads
- :mod:`ctf.services.range.recovery` -- destroyed-range recovery (rebuild/reassign-spare)
- :mod:`ctf.services.range.spares` -- event spare-range pool (provision/summary/cleanup)
"""

from __future__ import annotations

from ctf.services.range.batch import provision_event_ranges_throttled
from ctf.services.range.lifecycle import (
    cleanup_event_ranges,
    destroy_participant_range,
    restart_participant_range,
    start_participant_range,
    stop_participant_range,
)
from ctf.services.range.provision import (
    provision_participant_range,
    provision_participant_range_with_retry,
)
from ctf.services.range.recovery import get_recovery_status, recover_participant_range
from ctf.services.range.spares import (
    cleanup_event_spares,
    get_event_spare_summary,
    provision_event_spares,
)
from ctf.services.range.status import get_range_status, update_participant_range_status
from ctf.services.range.tasks import get_provision_progress, request_event_provisioning

__all__ = [
    "cleanup_event_ranges",
    "cleanup_event_spares",
    "destroy_participant_range",
    "get_event_spare_summary",
    "get_provision_progress",
    "get_range_status",
    "get_recovery_status",
    "provision_event_ranges_throttled",
    "provision_event_spares",
    "provision_participant_range",
    "provision_participant_range_with_retry",
    "recover_participant_range",
    "request_event_provisioning",
    "restart_participant_range",
    "start_participant_range",
    "stop_participant_range",
    "update_participant_range_status",
]
