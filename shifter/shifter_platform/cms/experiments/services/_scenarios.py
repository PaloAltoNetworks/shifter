"""Scenario helper service entrypoints."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.experiments import services as _pkg
from cms.experiments.exceptions import ExperimentError, ExperimentValidationError
from shared.log_sanitize import safe_log_value

from ._common import _validate_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def get_scenario_instances(scenario_id: str, user: User | None = None) -> list[dict[str, str]]:
    """Get instance list for a scenario template.

    Args:
        scenario_id: Scenario template ID.
        user: Optional requesting user. If provided, access is checked.

    Returns:
        List of dicts with instance name and role.

    Raises:
        ExperimentValidationError: If scenario not found or access denied.
    """
    logger.debug("get_scenario_instances called for scenario_id=%s", safe_log_value(scenario_id))
    if user is not None:
        _validate_user(user, "get_scenario_instances")
    try:
        try:
            if user is not None:
                _pkg.check_scenario_access(scenario_id, user)
            scenario = _pkg.load_scenario_template(scenario_id)
        except ValueError as e:
            raise ExperimentValidationError(f"Invalid scenario: {e}") from e

        return [{"name": inst.name, "role": inst.role, "os_type": inst.os_type} for inst in scenario.instances]
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        # Inline CR/LF/tab stripping at the call site so CodeQL's
        # ``py/log-injection`` taint tracker recognises sanitisation. The
        # shared ``safe_log_value`` helper performs the same scrubbing, but
        # CodeQL doesn't pattern-match it as a sanitiser.
        clean_scenario_id = str(scenario_id).replace("\r", " ").replace("\n", " ").replace("\t", " ")[:200]
        logger.exception("Error in get_scenario_instances for scenario_id=%s", clean_scenario_id)
        raise
