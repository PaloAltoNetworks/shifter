"""CTF extension points for external Django apps (CTF-1401).

Extensibility follows Django's app architecture — no standalone plugin
lifecycle. A separate app registers its extensions from ``AppConfig.ready``:

    from ctf.extensions import register_flag_validator, register_scoring_strategy

    class MyPluginConfig(AppConfig):
        name = "my_ctf_plugin"

        def ready(self):
            register_flag_validator("blockchain", verify_blockchain_flag)
            register_scoring_strategy("golf", GolfScoringStrategy())

- **Flag validators** take ``(flag_obj, submitted_flag)`` and return a bool;
  the registered ``flag_type`` becomes usable on ``CTFFlag`` rows and wins
  over the built-in dispatch (static/regex/programmable/http).
- **Scoring strategies** implement the ``ScoringStrategy`` protocol from
  :mod:`ctf.services.scoring._strategy`; the registered mode becomes a valid
  ``CTFEvent.scoring_mode`` value.

Registrations are process-wide and idempotent by key (last write wins).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ctf.models import CTFChallenge, CTFFlag

logger = logging.getLogger(__name__)


class ScoringStrategyLike(Protocol):
    """Structural contract for scoring strategies (see ctf.services.scoring._strategy)."""

    def points_for_solve(self, challenge: CTFChallenge, total_hint_penalty: int) -> int:
        """Points to award for a correct solve."""
        ...


FlagValidator = Callable[["CTFFlag", str], bool]

_flag_validators: dict[str, FlagValidator] = {}
_scoring_strategies: dict[str, ScoringStrategyLike] = {}


def register_flag_validator(flag_type: str, validator: FlagValidator) -> None:
    """Register (or replace) the validator for a custom flag type."""
    if not callable(validator):
        raise TypeError("validator must be callable")
    _flag_validators[flag_type] = validator
    logger.info("Registered CTF flag validator for type %r", flag_type)


def get_flag_validator(flag_type: str) -> FlagValidator | None:
    """Return the registered validator for a flag type, if any."""
    return _flag_validators.get(flag_type)


def register_scoring_strategy(mode: str, strategy: ScoringStrategyLike) -> None:
    """Register (or replace) the scoring strategy for a custom mode."""
    if not hasattr(strategy, "points_for_solve"):
        raise TypeError("strategy must implement points_for_solve")
    _scoring_strategies[mode] = strategy
    logger.info("Registered CTF scoring strategy for mode %r", mode)


def get_registered_scoring_strategy(mode: str) -> ScoringStrategyLike | None:
    """Return the registered strategy for a mode, if any."""
    return _scoring_strategies.get(mode)


def registered_scoring_modes() -> frozenset[str]:
    """Modes contributed by extensions (used by event-config validation)."""
    return frozenset(_scoring_strategies)


def registered_flag_types() -> frozenset[str]:
    """Flag types contributed by extensions (used by model choice validation)."""
    return frozenset(_flag_validators)
