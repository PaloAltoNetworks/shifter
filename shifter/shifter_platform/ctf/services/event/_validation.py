"""Event create/update input validators.

Split from ``_crud`` for the python:S104 file-size budget. Both helpers surface a
controlled ``CTFValidationError`` (400) on the JSON API path, which bypasses form
validation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ctf.exceptions import CTFValidationError

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def validate_scoring_mode(event_data: dict[str, Any]) -> None:
    """Reject an unknown ``scoring_mode`` with a controlled 400.

    The model field constrains choices, but the JSON API path bypasses form
    validation, so validate here to surface a `CTFValidationError` (400) rather
    than persisting an invalid value that would later fall back to standard.
    """
    from ctf.enums import ScoringMode
    from ctf.extensions import registered_scoring_modes

    if "scoring_mode" not in event_data:
        return
    if event_data["scoring_mode"] in registered_scoring_modes():
        return
    try:
        ScoringMode(event_data["scoring_mode"])
    except ValueError:
        raise CTFValidationError(
            "Invalid scoring mode",
            code="CTF_INVALID_SCORING_MODE",
            details={
                "scoring_mode": event_data["scoring_mode"],
                "valid_modes": [m.value for m in ScoringMode],
            },
        ) from None


def validate_content_scenario_access(user: User, scenario_id: str) -> None:
    """Authorize configured content through the existing CTF launch catalog."""
    from django.conf import settings

    if settings.CTF_CONTENT_REFERENCES.get(scenario_id) is None:
        return

    from ctf.bridges import cms_list_scenarios

    if scenario_id not in {available_id for available_id, _name in cms_list_scenarios(user)}:
        raise CTFValidationError(
            "Scenario is not available for CTF event creation.",
            code="CTF_SCENARIO_NOT_AVAILABLE",
        )
