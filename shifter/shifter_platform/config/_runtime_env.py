"""Shared runtime environment toggles for Django settings modules.

Centralizes ``IS_TEST_RUN``, ``AUTH_PROVIDER``, and ``ENVIRONMENT`` resolution
so ``config.settings`` and ``config._oidc_settings`` do not duplicate logic (#948).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "AUTH_PROVIDER",
    "IS_TEST_RUN",
    "require_environment",
    "required_runtime_env",
    "runtime_allows_dev_defaults",
]

IS_TEST_RUN = os.environ.get("TESTING") == "1" or Path(sys.argv[0]).name == "pytest"
AUTH_PROVIDER = os.environ.get("AUTH_PROVIDER", "oidc").strip().lower()


_TOOLING_INVOKERS = frozenset({"pytest", "mypy", "dmypy"})


def runtime_allows_dev_defaults(env: Mapping[str, str] | None = None) -> bool:
    """Return True when settings may use explicit non-production defaults."""
    source = env if env is not None else os.environ
    invoker = Path(sys.argv[0]).name
    if source.get("TESTING") == "1" or invoker in _TOOLING_INVOKERS:
        return True
    if source.get("ENVIRONMENT", "").strip().lower() == "build":
        return True
    return source.get("DJANGO_DEBUG", "").strip().lower() == "true"


def required_runtime_env(name: str, *, dev_default: str | None = None, env: Mapping[str, str] | None = None) -> str:
    """Return a required environment value or an explicit dev/test/build default."""
    from django.core.exceptions import ImproperlyConfigured

    source = env if env is not None else os.environ
    raw = source.get(name, "").strip()
    if raw:
        return raw
    if dev_default is not None and runtime_allows_dev_defaults(source):
        return dev_default
    raise ImproperlyConfigured(f"{name} environment variable is required")


def require_environment(env: Mapping[str, str] | None = None) -> str:
    """Return ``ENVIRONMENT`` or fail closed when unset/blank (#948).

    Refuses the silent ``production`` default that made AWS dev deployments
    indistinguishable from prod and hid the dev-login posture from operators.
    """
    from django.core.exceptions import ImproperlyConfigured

    source = env if env is not None else os.environ
    raw = source.get("ENVIRONMENT", "").strip()
    if not raw:
        invoker = Path(sys.argv[0]).name
        if source.get("TESTING") == "1" or invoker in _TOOLING_INVOKERS:
            return "test"
        raise ImproperlyConfigured(
            "ENVIRONMENT is required; refusing silent production default (#948). "
            "Set ENVIRONMENT explicitly for every deploy (e.g. development, production, test, build)."
        )
    return raw
