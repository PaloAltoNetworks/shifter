"""Declarative data-seeding operations for CTF ranges.

Seeds are executed by the seed-orchestrator after provisioning. They
populate the hospital with benign-but-realistic data so the environment
feels alive: Synthea patient load, DICOM study generation, HL7 message
feeds, and scheduled benign noise.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, field_validator


class SyntheaSeed(BaseModel):
    """Generate a Synthea synthetic patient population and load into an EHR-family service.

    Attributes:
        population_size: number of patients to synthesize.
        state: Synthea US-state setting (regional demographic bias).
        formats: export formats.
        into_service: target ServiceSpec.name (EHR / LIMS / PACS).
    """

    seed_type: Literal["synthea"] = "synthea"
    population_size: int = 500
    state: str = "Massachusetts"
    formats: list[Literal["fhir_r4", "ccda", "csv"]] = ["fhir_r4"]
    into_service: str

    @field_validator("population_size")
    @classmethod
    def pop_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("population_size must be positive")
        return v


class DicomSeed(BaseModel):
    """Generate or pull DICOM studies into a PACS service."""

    seed_type: Literal["dicom"] = "dicom"
    source: Literal["synthea_dicom", "public_sample", "generated"] = "synthea_dicom"
    study_count: int
    into_service: str

    @field_validator("study_count")
    @classmethod
    def study_count_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("study_count must be positive")
        return v


class HL7FeedSeed(BaseModel):
    """Start a recurring HL7 message feed through an integration engine."""

    seed_type: Literal["hl7_feed"] = "hl7_feed"
    event_types: list[Literal["ADT_A01", "ADT_A03", "ADT_A08", "ORU_R01", "ORM_O01", "SIU_S12"]]
    messages_per_hour: int
    into_service: str

    @field_validator("messages_per_hour")
    @classmethod
    def rate_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("messages_per_hour must be positive")
        return v


class BenignNoiseSeed(BaseModel):
    """Start a background benign-activity generator (mail, helpdesk tickets, etc.)."""

    seed_type: Literal["benign_noise"] = "benign_noise"
    noise_type: Literal[
        "mail_traffic",
        "helpdesk_tickets",
        "appointment_creation",
        "badge_events",
        "hvac_setpoint_drift",
        "rtsp_motion",
        "shift_change",
        "billing_events",
    ]
    rate_hint: Literal["low", "medium", "high"] = "medium"


DataSeedSpec = Annotated[
    SyntheaSeed | DicomSeed | HL7FeedSeed | BenignNoiseSeed,
    Discriminator("seed_type"),
]
