"""Flag definitions for CTF ranges."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

from ..base import SpecBase


class MitreTTP(BaseModel):
    """MITRE ATT&CK tactic/technique/sub-technique reference.

    Enterprise v15+ by default; ICS TAs may also be used for OT flags.
    """

    tactic: str
    technique: str
    sub_technique: str | None = None

    @field_validator("tactic")
    @classmethod
    def tactic_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("tactic must be non-empty")
        return v.strip()


class FlagSpec(SpecBase):
    """A single flag / challenge declaration.

    Attributes:
        id: stable challenge id (e.g. "admission-01"); unique across the
            scenario registry.
        display_name: human-readable title shown in CTFd.
        points: base point value; CTFd dynamic scoring may adjust.
        difficulty: player-facing difficulty tier.
        zone: ZoneSpec.name this flag is filed under.
        asset: AssetSpec.name of the primary-target asset.
        service: optional ServiceSpec.name.
        source: static or programmatic validation path.
        mitre: MITRE ATT&CK mapping.
        prerequisite_flag_ids: other flag ids that must be solved first.
        unlock_day: day-index gate; None => available from Day 1.
        mission: human mission grouping (Admission, Charted, etc.).
        hints: CTFd hint bodies; operator may toggle paid/free at event time.
    """

    id: str
    display_name: str
    points: int
    difficulty: Literal["easy", "medium", "hard", "expert"]
    zone: str
    asset: str
    service: str | None = None
    source: Literal["static", "programmatic"] = "static"
    mitre: list[MitreTTP] = []
    prerequisite_flag_ids: list[str] = []
    unlock_day: int | None = None
    mission: str | None = None
    hints: list[str] = []

    @field_validator("id")
    @classmethod
    def id_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("flag id must be non-empty")
        return v.strip()

    @field_validator("points")
    @classmethod
    def points_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("points must be positive")
        return v

    @field_validator("unlock_day")
    @classmethod
    def unlock_day_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("unlock_day must be >= 1 (or None for always-on)")
        return v
