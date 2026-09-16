"""Shifter's configuration-bound RAES realization contract.

The public RAES ``RealizerConfigurationModel`` is the independent apply-time
evidence surface for the backend. It declares the account features and resource
families this Shifter configuration genuinely realizes, while the backend
manifest remains the authoring capability surface. The common validate/apply
path consults this contract before dispatch so a manifest over-claim cannot
become an accepted plan.
"""

from __future__ import annotations

from raes_contracts.realization_envelope import (
    BackendRealizationEnvelopeModel,
    RealizationConcern,
    RealizerConfigurationModel,
    realization_envelope_digest,
    realizer_configuration_digest,
)

# A coupled, finite release matrix. Actual guest readback must match the
# selected row; an image alias never supplies operating-system evidence.
# The namespaced Alpine version denotes a major.minor release family; guest
# patch versions are normalized to that family by the independent OS probe.
OPERATING_SYSTEMS = [
    {"family": "linux", "distribution": "ubuntu", "versions": ["22.04", "24.04"]},
    {"family": "linux", "distribution": "debian", "versions": ["12", "13"]},
    {"family": "linux", "distribution": "x-shifter:alpine", "versions": ["3.19"]},
    {"family": "linux", "distribution": "x-shifter:kali", "versions": ["rolling"]},
    {"family": "windows", "distribution": "windows-server", "versions": ["2019", "2022", "2025"]},
]

_CONFIGURATION = {
    "mode": "shifter-provider-native",
    "architecture": "x86_64",
    "image_policy": "raes-image-registry",
    "network_policy": "isolated-range-cell",
    "supported_node_types": ["switch", "compute"],
    "supported_os_families": ["linux", "windows"],
    "operating_systems": OPERATING_SYSTEMS,
    "supported_content_types": ["directory", "file"],
    "supported_account_features": ["auth_method", "disabled", "groups", "home", "shell", "spn"],
    "supported_domain_profiles": ["active_directory"],
    "supports_acls": True,
    "memory_mib": {"minimum": 512, "maximum": None},
    "vcpus": {"minimum": 1, "maximum": None},
}


def create_shifter_realizer_configuration() -> RealizerConfigurationModel:
    """Return Shifter's validated, digest-bound realizer configuration."""
    # The public digest helper validates the complete model, then excludes its
    # self-digest. Supply a valid placeholder during that first validation.
    configuration = RealizerConfigurationModel(configuration_digest="sha256:" + "0" * 64, **_CONFIGURATION)
    digest = realizer_configuration_digest(configuration)
    return configuration.model_copy(update={"configuration_digest": digest})


SHIFTER_REALIZER_CONFIGURATION = create_shifter_realizer_configuration()
REALIZED_ACCOUNT_FEATURES = frozenset(SHIFTER_REALIZER_CONFIGURATION.supported_account_features)


def create_shifter_realization_envelope(
    *, scenario_name: str, compute_node_name: str
) -> BackendRealizationEnvelopeModel:
    """Build the constructive carrier for one runtime-selected scenario.

    Scenario and node identities come from the already loaded portable pack.
    They make the envelope constructive without fixing network, image, OS,
    sizing, or any provider materialization choice.  Those terms remain under
    the runtime's open semantics and are realized by the selected adapter.
    """
    guest = {"operating-system", "content-placement", "account-placement", "feature-binding"}
    concerns = []
    for concern in RealizationConcern:
        strength = "guest-observed" if concern.value in guest else "driver-reported"
        mechanism = "shifter-native-realization"
        if concern.value == "compute-substrate":
            strength, mechanism = "daemon-observed", "virtual-machine"
        concerns.append(
            {
                "concern": concern.value,
                "disposition": "realized",
                "observation_strength": strength,
                "mechanism": mechanism,
            }
        )
    envelope_id = "shifter-runtime-realization-v1"
    payload = {
        "id": envelope_id,
        "expression": {
            "id": envelope_id,
            "scope": "scenario",
            "domains": {
                "scenario-name": {"kind": "exact", "value": scenario_name},
                "node-type": {"kind": "exact", "value": "compute"},
            },
            "bindings": [
                {"path": "name", "scope": "scenario", "posture": "exact", "domain": "scenario-name"},
                {
                    "path": f"nodes.{compute_node_name}.type",
                    "scope": "node",
                    "posture": "exact",
                    "domain": "node-type",
                },
            ],
        },
        "configuration": SHIFTER_REALIZER_CONFIGURATION,
        "concerns": concerns,
    }
    return BackendRealizationEnvelopeModel(**payload, digest=realization_envelope_digest(payload))


__all__ = [
    "REALIZED_ACCOUNT_FEATURES",
    "SHIFTER_REALIZER_CONFIGURATION",
    "create_shifter_realization_envelope",
    "create_shifter_realizer_configuration",
]
