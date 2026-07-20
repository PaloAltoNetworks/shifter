"""Defender / SOC stack declaration for CTF ranges.

Operator-side. Not reachable by participants by default. Scenario
overlays may flip `participant_visible` for blue-team scenarios.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DetectionStackSpec(BaseModel):
    """Optional defender stack declaration.

    Each field is an enum of supported components; None disables that
    component. The default deploys a full Wazuh + Suricata + Falco stack
    as the baseline.

    Attributes:
        enabled: master toggle.
        siem: SIEM platform.
        ids: network IDS platform.
        runtime: runtime / eBPF sensor.
        threat_intel: threat-intel platform.
        case_mgmt: case management platform.
        soar: SOAR platform.
        soc_zone: ZoneSpec.name the SOC stack deploys into.
        participant_visible: if False, hidden from players (red-team scenario).
    """

    enabled: bool = True
    siem: Literal["wazuh"] | None = "wazuh"
    ids: Literal["suricata"] | None = "suricata"
    runtime: Literal["falco"] | None = "falco"
    threat_intel: Literal["misp"] | None = None
    case_mgmt: Literal["thehive_cortex"] | None = None
    soar: Literal["shuffle"] | None = None
    soc_zone: str = "soc"
    participant_visible: bool = False
