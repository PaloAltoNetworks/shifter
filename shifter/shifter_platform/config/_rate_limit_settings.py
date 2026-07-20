"""Launch-endpoint rate-limiting settings (issue #322).

Split into ``config/_rate_limit_settings.py`` (star-imported by
``config.settings``) to keep that module under the Sonar S104 500-line cap.
Enforcement lives in ``mission_control.api.rate_limit``; the shared
``launch_rate_limit`` cache is configured in ``config/_cache_settings.py``.

Backpressure on the two expensive Mission Control launch mutations
(``LaunchRangeView``, ``NGFWCreateView``) to prevent cascade failures under
load. Two independent fixed-window budgets per operation: a per-actor budget
(abuse cap) and a fleet budget (system-wide cap, the actual cascade guard).
Budget exhaustion returns 429 + Retry-After; a limiter-backend outage fails
closed with a bounded 503.

Disabled by default under test runs so the process-global fleet counter cannot
accumulate across unrelated launch tests; enabled by default everywhere else.
When enabled, every budget max/window MUST be a positive integer — a
non-positive value is a configuration error, not a silent disable (use the
master flag to disable). Defaults are conservative starting points for
interactive use and are tunable via the ``RANGE_``/``NGFW_LAUNCH_*`` env vars.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from config._runtime_env import IS_TEST_RUN

__all__ = ["LAUNCH_RATE_LIMITS", "LAUNCH_RATE_LIMIT_ENABLED"]


def _int(name: str, default: int) -> int:
    """Read a positive-integer knob, failing loud on a non-integer value."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _bool(name: str, default: bool) -> bool:
    """Read a boolean knob (reads the name indirectly, like the other knobs)."""
    return os.environ.get(name, str(default)).lower() == "true"


LAUNCH_RATE_LIMIT_ENABLED = _bool("LAUNCH_RATE_LIMIT_ENABLED", not IS_TEST_RUN)

LAUNCH_RATE_LIMITS = {
    "range": {
        "actor": {"max": _int("RANGE_LAUNCH_ACTOR_MAX", 5), "window": _int("RANGE_LAUNCH_ACTOR_WINDOW_SECONDS", 60)},
        "fleet": {"max": _int("RANGE_LAUNCH_FLEET_MAX", 20), "window": _int("RANGE_LAUNCH_FLEET_WINDOW_SECONDS", 60)},
    },
    "ngfw": {
        "actor": {"max": _int("NGFW_LAUNCH_ACTOR_MAX", 5), "window": _int("NGFW_LAUNCH_ACTOR_WINDOW_SECONDS", 60)},
        "fleet": {"max": _int("NGFW_LAUNCH_FLEET_MAX", 20), "window": _int("NGFW_LAUNCH_FLEET_WINDOW_SECONDS", 60)},
    },
}

if LAUNCH_RATE_LIMIT_ENABLED:
    for _op, _budgets in LAUNCH_RATE_LIMITS.items():
        for _kind, _cfg in _budgets.items():
            if _cfg["max"] <= 0 or _cfg["window"] <= 0:
                raise ImproperlyConfigured(
                    f"LAUNCH_RATE_LIMITS[{_op!r}][{_kind!r}] max and window must be positive integers"
                )
