"""CTF-range schemas for CyberScript.

Additive to the demo-range schemas. Demo (AWS) paths remain unchanged
per ADR-005 provider-seam continuity; CTF ranges deploy to GDC.

Public surface:

- CTFRangeSpec — top-level aggregate (range_type='ctf')
- ZoneSpec, NetworkSpec (+ GDCNetworkBinding, NetworkRouteSpec)
- AssetSpec (+ AssetNetworkAttachment, DCConfigExt)
- ForestSpec, DomainSpec, ForestTrustSpec
- ServiceSpec (+ ServiceEndpointSpec, WeakWAFConfig)
- FlagSpec, MitreTTP
- DataSeedSpec (Synthea / DICOM / HL7 / BenignNoise)
- DetectionStackSpec
- ParticipantAccessSpec
- SafetyEnvelopeSpec (+ RegisterRange)
- ScenarioOverlaySpec (+ operation discriminator and sub-types)
"""

from __future__ import annotations

from .access import ParticipantAccessSpec
from .asset import (
    AssetNetworkAttachment,
    AssetOSType,
    AssetRole,
    AssetSpec,
    AssetType,
    DCConfigExt,
)
from .ctf_range import CYBERSCRIPT_VERSION_V1, CTFRangeSpec
from .data import (
    BenignNoiseSeed,
    DataSeedSpec,
    DicomSeed,
    HL7FeedSeed,
    SyntheaSeed,
)
from .detection import DetectionStackSpec
from .flag import FlagSpec, MitreTTP
from .forest import DomainSpec, ForestSpec, ForestTrustSpec
from .network import GDCNetworkBinding, NetworkRouteSpec, NetworkSpec
from .overlay import (
    ADUserInjection,
    AnyOverlayOperation,
    CTFdConfigOperation,
    CTFdPageRef,
    ConfigPatchOperation,
    ImageSwapOperation,
    InjectVulnOperation,
    NetworkPolicyPatchOperation,
    OperationKind,
    OverlayOperationBase,
    PlantFlagOperation,
    PlantFlagPolicy,
    SafetyReview,
    ScenarioOverlayMetadata,
    ScenarioOverlaySpec,
    ScheduleEventOperation,
    ScheduledAction,
    SidecarAddOperation,
    TagOperation,
)
from .safety import RegisterRange, SafetyEnvelopeSpec
from .service import (
    ProtoLiteral,
    ServiceEndpointSpec,
    ServiceSpec,
    ServiceType,
    WeakWAFConfig,
)
from .zone import ZoneKind, ZoneSpec

__all__ = [
    "ADUserInjection",
    "AnyOverlayOperation",
    "AssetNetworkAttachment",
    "AssetOSType",
    "AssetRole",
    "AssetSpec",
    "AssetType",
    "BenignNoiseSeed",
    "CTFRangeSpec",
    "CTFdConfigOperation",
    "CTFdPageRef",
    "CYBERSCRIPT_VERSION_V1",
    "ConfigPatchOperation",
    "DCConfigExt",
    "DataSeedSpec",
    "DetectionStackSpec",
    "DicomSeed",
    "DomainSpec",
    "FlagSpec",
    "ForestSpec",
    "ForestTrustSpec",
    "GDCNetworkBinding",
    "HL7FeedSeed",
    "ImageSwapOperation",
    "InjectVulnOperation",
    "MitreTTP",
    "NetworkPolicyPatchOperation",
    "NetworkRouteSpec",
    "NetworkSpec",
    "OperationKind",
    "OverlayOperationBase",
    "ParticipantAccessSpec",
    "PlantFlagOperation",
    "PlantFlagPolicy",
    "ProtoLiteral",
    "RegisterRange",
    "SafetyEnvelopeSpec",
    "SafetyReview",
    "ScenarioOverlayMetadata",
    "ScenarioOverlaySpec",
    "ScheduleEventOperation",
    "ScheduledAction",
    "ServiceEndpointSpec",
    "ServiceSpec",
    "ServiceType",
    "SidecarAddOperation",
    "SyntheaSeed",
    "TagOperation",
    "WeakWAFConfig",
    "ZoneKind",
    "ZoneSpec",
]
