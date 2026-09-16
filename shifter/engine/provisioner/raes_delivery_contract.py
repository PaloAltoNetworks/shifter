"""Fail-closed validation and ordering for RAES delivery resources."""

from __future__ import annotations

import re
from typing import Any

from shared.raes.content_delivery import ContentDeliveryError, DeliveryBinding

from raes_gcp_composition import RaesGceCompositionError
from raes_plan import RaesPlan, RaesPlanContent, RaesPlanFeature

SUPPORTED_DELIVERY_CONTENT_TYPES = frozenset({"file", "directory"})
SAFE_SERVICE_IDENTITY = re.compile(r"^[A-Za-z0-9._+-]+$")


class FeatureDependencyCycleError(RuntimeError):
    """Raised when feature ordering cannot be resolved."""


def source_backed_content(raes_plan: RaesPlan) -> list[RaesPlanContent]:
    """Return every content item whose bytes are delivered, not baked in."""
    return [item for item in raes_plan.content if item.source_name]


def source_backed_features(raes_plan: RaesPlan) -> list[RaesPlanFeature]:
    """Return delivered artifact/configuration features (services are separate)."""
    return [
        item for item in raes_plan.features if item.source_name and item.feature_type in {"artifact", "configuration"}
    ]


def ordered_features(raes_plan: RaesPlan) -> list[RaesPlanFeature]:
    """Return features in stable dependency order, failing closed on a cycle."""
    features = list(raes_plan.features)
    feature_addresses = {feature.address for feature in features}
    remaining = {
        feature.address: {dependency for dependency in feature.ordering_dependencies if dependency in feature_addresses}
        for feature in features
    }
    ordered: list[RaesPlanFeature] = []
    completed: set[str] = set()
    while len(ordered) < len(features):
        ready = [
            feature
            for feature in features
            if feature.address not in completed and remaining[feature.address].issubset(completed)
        ]
        if not ready:
            raise FeatureDependencyCycleError("RAES feature realization dependencies contain a cycle")
        ordered.extend(ready)
        completed.update(feature.address for feature in ready)
    return ordered


def validated_binding(raw: dict[str, Any]) -> DeliveryBinding:
    """Parse and validate one persisted delivery binding."""
    binding = DeliveryBinding.from_transport(raw)
    suffix = f"/{binding.sha256[:2]}/{binding.sha256}"
    if not binding.storage_key.endswith(suffix):
        raise ContentDeliveryError("delivery binding storage_key is not content-addressed")
    return binding


def _validate_feature(feature: RaesPlanFeature) -> None:
    """Reject features without a safe provisioner realization contract."""
    if feature.feature_type not in {"service", "artifact", "configuration"}:
        raise RaesGceCompositionError("feature type has no provisioner realization")
    if feature.has_environment:
        raise RaesGceCompositionError("feature environment has no safe realization contract")
    if not feature.source_name:
        raise RaesGceCompositionError("feature source identity is missing")
    if feature.feature_type in {"artifact", "configuration"} and not feature.destination:
        raise RaesGceCompositionError("delivered feature destination is missing")
    unsafe_service_identity = feature.feature_type == "service" and (
        not SAFE_SERVICE_IDENTITY.fullmatch(feature.source_name)
        or (feature.source_version is not None and not SAFE_SERVICE_IDENTITY.fullmatch(feature.source_version))
    )
    if unsafe_service_identity:
        raise RaesGceCompositionError("service feature identity is invalid")


def _validated_bindings(delivery_bindings: list[dict[str, Any]] | None) -> list[DeliveryBinding]:
    """Validate every raw binding and translate contract failures."""
    validated: list[DeliveryBinding] = []
    for raw_binding in delivery_bindings or []:
        try:
            validated.append(validated_binding(raw_binding))
        except ContentDeliveryError:
            raise RaesGceCompositionError("a delivery binding failed contract validation") from None
    return validated


def _validate_source_content(source_content: list[RaesPlanContent]) -> None:
    """Reject source-backed content without a delivery materializer."""
    for item in source_content:
        if item.content_type not in SUPPORTED_DELIVERY_CONTENT_TYPES:
            raise RaesGceCompositionError(f"source-backed content {item.content_type!r} has no delivery materializer")


def _assert_identity_sets_match(
    source_content: list[RaesPlanContent],
    source_features: list[RaesPlanFeature],
    validated: list[DeliveryBinding],
    binding_count: int,
) -> None:
    """Require a one-to-one match between deliverables and binding identities."""
    bound_identities = {
        (binding.resource_type or "content-placement", binding.resource_address or binding.content_address or "")
        for binding in validated
    }
    source_identities = {
        *(("content-placement", item.address) for item in source_content),
        *(("feature-binding", item.address) for item in source_features),
    }
    if len(bound_identities) != binding_count:
        raise RaesGceCompositionError("RAES delivery bindings carry a duplicate resource identity")
    if source_identities - bound_identities:
        raise RaesGceCompositionError("a source-backed resource is missing its delivery binding")
    if bound_identities - source_identities:
        raise RaesGceCompositionError("a delivery binding does not match any deliverable resource")


def assert_content_delivery_bindings_complete(
    raes_plan: RaesPlan,
    delivery_bindings: list[dict[str, Any]] | None,
) -> None:
    """Fail closed unless every deliverable resource has exactly one binding."""
    source_content = source_backed_content(raes_plan)
    source_features = source_backed_features(raes_plan)
    for feature in raes_plan.features:
        _validate_feature(feature)
    _validate_source_content(source_content)
    validated = _validated_bindings(delivery_bindings)
    _assert_identity_sets_match(source_content, source_features, validated, len(delivery_bindings or []))
