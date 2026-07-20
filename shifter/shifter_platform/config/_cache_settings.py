"""Django cache configuration (``CACHES``).

Split into ``config/_cache_settings.py`` (star-imported by ``config.settings``)
to keep that module under the Sonar S104 500-line cap.

- ``default``: process-local ``LocMemCache``. This preserves the pre-existing
  implicit default (Django's global default is also ``LocMemCache``), so global
  cache behaviour — including the CTF invite limiter that uses the default cache
  — is unchanged by #322. Defining ``CACHES`` here replaces Django's implicit
  default, so ``default`` must be declared explicitly.
- ``launch_rate_limit``: the shared launch-admission cache (#322). Redis-backed
  in production for cross-worker correctness, or ``LocMemCache`` under tests /
  single-process dev. Built from the shared Redis posture — see
  ``config._redis.build_launch_rate_limit_cache``.
"""

from __future__ import annotations

import os

from config._redis import build_launch_rate_limit_cache

__all__ = ["CACHES"]

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "launch_rate_limit": build_launch_rate_limit_cache(os.environ),
}
