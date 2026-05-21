"""Per-challenge adapters: the executable coverage map.

An adapter executes one challenge's canonical participant path against a real
staged range and returns the value that path yields. Each adapter declares the
runner container it executes from and the *kind* of value it produces:

* ``flag``   - the path yields the literal ``FLAG{...}`` configured in CTFd;
  the harness compares it for equality against the board's static flag.
* ``answer`` - the path yields a submit-answer string distinct from the CTFd
  static flag (e.g. a concatenated device-model identifier). The adapter
  records ``expected_answer`` and the harness compares against that.

The coverage universe is derived from the board, not from this registry: a
challenge with no adapter is reported ``uncovered`` (a failure), never skipped.

Adapter logic is factored from the existing per-asset smoketests under
``scenario-dev/polaris/tests/smoketests/``; this registry does not duplicate
challenge metadata that already lives in ``ctfd-challenges.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Produced:
    """A value produced by walking a challenge's hint path."""

    value: str | None
    kind: str  # "flag" | "answer"
    note: str = ""


@dataclass
class AdapterContext:
    """Range connection context handed to every adapter."""

    runner: object  # a runner.Runner (or test double) exposing .exec()
    hosts: dict[str, str] = field(default_factory=dict)
    dns: str = "172.20.0.2"

    def host(self, key: str) -> str:
        """Return the configured hostname for an asset key (e.g. ``a0``)."""
        return self.hosts[key]


@dataclass(frozen=True)
class Adapter:
    """An executable check for one challenge."""

    challenge_id: int
    runner: str
    value_kind: str
    solve: Callable[[AdapterContext], Produced]
    expected_answer: str | None = None


ADAPTERS: dict[int, Adapter] = {}


def register(
    challenge_id: int,
    *,
    runner: str,
    value_kind: str = "flag",
    expected_answer: str | None = None,
) -> Callable[[Callable[[AdapterContext], Produced]], Callable]:
    """Decorator: register an adapter callable for ``challenge_id``."""

    def decorator(fn: Callable[[AdapterContext], Produced]):
        if challenge_id in ADAPTERS:
            raise ValueError(f"duplicate adapter for challenge {challenge_id}")
        ADAPTERS[challenge_id] = Adapter(
            challenge_id=challenge_id,
            runner=runner,
            value_kind=value_kind,
            solve=fn,
            expected_answer=expected_answer,
        )
        return fn

    return decorator


# Importing a mission module runs its @register decorators as a side effect.
from . import mission1_osint  # noqa: E402,F401
