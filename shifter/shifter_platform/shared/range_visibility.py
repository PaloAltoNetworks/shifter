"""Pluggable range-instance visibility policy (#483).

Mission Control renders range instances but must not import domain apps; a
domain layer (CTF) owns the policy of which instances a given user may see.
This seam mirrors :mod:`shared.notifications`: the domain registers one
policy callable at app startup, and the presentation layer filters through
:func:`filter_visible_instances`. With no policy registered, everything is
visible.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

logger = logging.getLogger(__name__)

# Policy contract: (user, instances) -> the instances the user may see.
VisibilityPolicy = Callable[["AbstractBaseUser | AnonymousUser", list[Any]], list[Any]]

_policy: VisibilityPolicy | None = None


def register_visibility_policy(policy: VisibilityPolicy) -> None:
    """Register (or replace) the instance-visibility policy."""
    global _policy
    if not callable(policy):
        raise TypeError("policy must be callable")
    _policy = policy


def filter_visible_instances(user: AbstractBaseUser | AnonymousUser, instances: list[Any]) -> list[Any]:
    """Apply the registered policy; fail open to the unfiltered list on policy errors.

    Failing open is deliberate for the operator experience (a broken policy
    must not blank the terminal); the policy itself is responsible for
    failing CLOSED for restricted audiences.
    """
    if _policy is None:
        return instances
    try:
        return list(_policy(user, instances))
    except Exception:
        logger.exception("Range visibility policy failed; showing unfiltered instances")
        return instances
