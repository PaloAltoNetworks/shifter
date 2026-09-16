"""Run an existing setup plan's readback without its installation steps."""

from dataclasses import dataclass
from typing import Any

from .base import SetupPlan, SetupStep


@dataclass(frozen=True)
class VerificationOnlyPlan:
    """Provide VerificationOnlyPlan."""

    source: SetupPlan

    @property
    def steps(self) -> list[SetupStep]:
        return []

    @property
    def verify_step(self) -> SetupStep:
        step = self.source.verify_step
        if step is None or not step.is_verification:
            raise ValueError("setup plan has no independent verification step")
        return step

    def get_context(self, instance: object) -> dict[str, Any]:
        return self.source.get_context(instance)
