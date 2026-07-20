"""Safety envelope for OT / medical-device assets in CTF ranges.

Every AssetSpec with role=="ot" must declare a SafetyEnvelopeSpec. The
envelope is enforced by the emulator runtime: any write outside `writable`
is rejected, keeping scenario flags from being able to cause simulated
harm.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class RegisterRange(BaseModel):
    """A contiguous range of registers / objects on an OT protocol."""

    proto: Literal["modbus_tcp", "bacnet", "s7comm", "opcua", "mqtt"]
    addr_start: int
    addr_end: int

    @field_validator("addr_end")
    @classmethod
    def end_after_start(cls, v: int, info) -> int:
        addr_start = info.data.get("addr_start")
        if addr_start is not None and v < addr_start:
            raise ValueError("addr_end must be >= addr_start")
        return v


class SafetyEnvelopeSpec(BaseModel):
    """Declares readable, writable, and flag-rewarded-write register ranges.

    The emulator enforces this at the protocol layer. Anything outside
    `writable` raises on write, regardless of whether a scenario overlay
    attempts to reach it. Scenario overlays that alter an envelope must
    set `override_safety_envelope=True` on their InjectVulnOperation
    and carry a reviewed `safety_review:` block.
    """

    readable: list[RegisterRange] = []
    writable: list[RegisterRange] = []
    flag_rewarded_writes: list[RegisterRange] = []
    rationale: str
