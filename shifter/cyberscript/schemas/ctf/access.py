"""Participant access plane declaration for CTF ranges.

Each participant gets a Kali pod (and optionally a Windows workstation VM)
wired to the range via Shifter's Guacamole/xterm.js stack.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class ParticipantAccessSpec(BaseModel):
    """Per-participant access plane.

    Attributes:
        kali_image: container image for the per-participant Kali pod.
        kali_networks: NetworkSpec.name list the Kali pod attaches to.
        include_windows_workstation: whether to also provision a Win WS.
        windows_image_key: Packer image key when workstation is included.
        guacamole_enabled: whether to wire Guacamole.
        terminal_type: in-browser terminal mechanism.
    """

    kali_image: str = "aurora-kali:latest"
    kali_networks: list[str]
    include_windows_workstation: bool = False
    windows_image_key: str | None = None
    guacamole_enabled: bool = True
    terminal_type: Literal["xterm.js", "guacamole_ssh", "guacamole_rdp"] = "xterm.js"

    @field_validator("kali_networks")
    @classmethod
    def at_least_one_network(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("kali_networks must list at least one network")
        return v
