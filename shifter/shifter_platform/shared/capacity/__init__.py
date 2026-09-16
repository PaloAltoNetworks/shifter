"""Capacity-aware provisioning contract (PLAT-201).

Public surface for the Django-free capacity-admission policy. Engine services,
cloud capacity-inventory adapters, and product wiring import from here rather
than reaching into the module directly, matching the ``shared.raes`` package
convention.
"""

from __future__ import annotations

from shared.capacity.contract import (
    CapacityAssessmentResult,
    CapacityInventoryPort,
    CapacityMetricSpec,
    CapacityOutcome,
    CapacityReasonCode,
    EnforcementMode,
    MeasurementSource,
    MetricObservation,
    MetricVerdict,
    ObservationResult,
    PartitionRef,
    ProviderMetricRef,
    evaluate_metric,
    worst_outcome,
)
from shared.capacity.demand import CapacityDemand, ImageCount, build_demand

__all__ = [
    "CapacityAssessmentResult",
    "CapacityDemand",
    "CapacityInventoryPort",
    "CapacityMetricSpec",
    "CapacityOutcome",
    "CapacityReasonCode",
    "EnforcementMode",
    "ImageCount",
    "MeasurementSource",
    "MetricObservation",
    "MetricVerdict",
    "ObservationResult",
    "PartitionRef",
    "ProviderMetricRef",
    "build_demand",
    "evaluate_metric",
    "worst_outcome",
]
