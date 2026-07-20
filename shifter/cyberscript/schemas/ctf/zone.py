"""Zone (floor / department grouping) for CTF ranges.

Zones are the player-facing grouping: "I'm on the clinical floor" /
"this is the BMS zone". Each asset lives in exactly one zone; each zone
contains one or more networks.

The ZoneKind literal is the HITRUST/HICP ABC model plus medical-device,
HIE, and telehealth extensions (see scenario-dev/hospital/design/
architecture.md §4).
"""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from ..base import SpecBase

ZoneKind = Literal[
    "admin",
    "business",
    "clinical",
    "iomt",
    "hie",
    "telehealth",
    "dmz",
    "wifi_guest",
    "wifi_corp",
    "ot_biomed",
    "ot_bms",
    "research",
    "vendor",
    "mgmt",
    "soc",
    "range_ops",
]


class ZoneSpec(SpecBase):
    """A logical zone within the range.

    Attributes:
        name: unique zone identifier (e.g. "floor-1-clinical").
        kind: zone category drawn from ZoneKind.
        floor: optional physical floor marker — documentation only.
        description: human-readable note.
        networks: names of NetworkSpecs that belong to this zone.
    """

    name: str
    kind: ZoneKind
    floor: int | None = None
    description: str | None = None
    networks: list[str] = []

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("zone name must be non-empty")
        return v.strip()
