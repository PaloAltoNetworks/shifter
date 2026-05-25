"""Common helpers shared by the experiment service submodules.

Kept private to the package. The patchable names that tests target via
``patch("cms.experiments.services.<name>")`` live on the package
``__init__`` and are looked up there at call time so the mocks apply
across submodule boundaries.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shared.auth import validate_cms_authoring_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def _validate_user(user: User, func_name: str) -> None:
    """Delegate to the shared CMS authoring user validator (see shared.auth)."""
    validate_cms_authoring_user(user, func_name)


def _check_result_type(result: object, expected_type: type, func_name: str) -> None:
    """Validate ORM return type — defensive check matching cms/services.py pattern."""
    if not isinstance(result, expected_type):
        logger.error(
            "%s: expected %s, got %s",
            func_name,
            expected_type.__name__,
            type(result).__name__,
        )
        raise TypeError(f"{func_name}: expected {expected_type.__name__}, got {type(result).__name__}")
