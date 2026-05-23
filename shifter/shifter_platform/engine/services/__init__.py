"""Engine service interface.

Infrastructure lifecycle for Shifter platform. The implementation is split
across private submodules (``_common``, ``_range``, ``_lifecycle``,
``_terminal``, ``_ngfw``, ``_queries``) and re-exported here so callers
continue to use ``from engine.services import X``.

The re-exports also rebind a few names that tests historically patch at
``engine.services.<name>`` (``transaction``, ``get_rdp_password``,
``get_ssh_key``) so existing ``unittest.mock.patch`` targets still work.
"""

from __future__ import annotations

from django.db import transaction

from engine.secrets import SecretsError, get_rdp_password, get_ssh_key

from ._common import EngineError
from ._lifecycle import pause_range, resume_range
from ._ngfw import create_ngfw, destroy_ngfw, start_ngfw, stop_ngfw
from ._queries import get_ranges_for_ngfw, get_user_ready_range_instances
from ._range import (
    cancel_range,
    cancel_range_by_request,
    create_range,
    destroy_range,
    destroy_range_by_request,
    get_instance_ips_by_uuid,
    get_range_status,
)
from ._terminal import (
    connect_ngfw_terminal,
    connect_terminal,
    get_rdp_connection_info,
    get_ssh_connection_info,
)

__all__ = (
    "EngineError",
    "SecretsError",
    "cancel_range",
    "cancel_range_by_request",
    "connect_ngfw_terminal",
    "connect_terminal",
    "create_ngfw",
    "create_range",
    "destroy_ngfw",
    "destroy_range",
    "destroy_range_by_request",
    "get_instance_ips_by_uuid",
    "get_range_status",
    "get_ranges_for_ngfw",
    "get_rdp_connection_info",
    "get_rdp_password",
    "get_ssh_connection_info",
    "get_ssh_key",
    "get_user_ready_range_instances",
    "pause_range",
    "resume_range",
    "start_ngfw",
    "stop_ngfw",
    "transaction",
)
