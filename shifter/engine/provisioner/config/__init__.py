"""Configuration module for Shifter Engine.

This module handles configuration dataclasses, database access,
and utility functions for the provisioner.

Split across private submodules by cloud/responsibility domain and
re-exported here so callers keep using ``from config import X`` /
``config.<name>`` exactly as before the split:

- ``_env``: shared env-var parsing helpers (leaf).
- ``_crypto``: field decryption, presigned URLs, cloud-provider resolution (leaf).
- ``_gcp_backend``: GCP range-backend selection, gce vs gdc (leaf; depends on ``_crypto``).
- ``_ngfw``: provider-neutral NGFW attachment resolution.
- ``_gdc``: GDC (Google Distributed Cloud) VM Runtime / scenario-Pod configuration.
- ``_range``: range/instance dataclasses, range-network contract, DB loading.
- ``_gce``: GCE (Compute Engine) live-fire range-cell backend configuration.
- ``_aws_polaris``: per-range AWS Polaris agent Bedrock role configuration.

Dependency direction is one-way (leaves first, no cycles):
``_env``, ``_crypto`` -> ``_gcp_backend``, ``_ngfw`` -> ``_gdc`` -> ``_range`` -> ``_gce``;
``_aws_polaris`` depends only on ``_env``.
"""

from ._aws_polaris import (
    AWSPolarisAgentConfig,
    load_aws_polaris_agent_config,
)
from ._content_delivery import (
    AcesContentDeliveryConfig,
    load_aces_content_delivery_config,
)
from ._crypto import (
    FieldDecryptError,
    decrypt_field,
    generate_presigned_url,
    resolve_cloud_provider,
)
from ._gce import (
    GCERangeCellConfig,
    GCERangeImageProfile,
    load_gce_range_cell_config,
)
from ._gcp_backend import (
    get_gcp_range_backend,
    is_gce_range_cell_backend,
)
from ._gdc import (
    GDCNetworkAccessConfig,
    GDCPaloAltoVMSeriesConfig,
    GDCScenarioPodConfig,
    GDCScenarioPodProfile,
    GDCVMRuntimeConfig,
    GDCVMRuntimeProfile,
    load_gdc_network_access_config,
    load_gdc_palo_alto_vmseries_config,
    load_gdc_scenario_pod_config,
    load_gdc_vmruntime_config,
)
from ._ngfw import (
    NGFWAttachmentConfig,
    has_ngfw_attachment_state,
    resolve_ngfw_attachment_config,
)
from ._range import (
    InstanceConfig,
    RangeConfig,
    RangeNetworkConfig,
    SubnetConfig,
    get_range_availability_zone,
    get_range_from_db,
    load_range_network_config,
)

__all__ = [
    "AWSPolarisAgentConfig",
    "AcesContentDeliveryConfig",
    "FieldDecryptError",
    "GCERangeCellConfig",
    "GCERangeImageProfile",
    "GDCNetworkAccessConfig",
    "GDCPaloAltoVMSeriesConfig",
    "GDCScenarioPodConfig",
    "GDCScenarioPodProfile",
    "GDCVMRuntimeConfig",
    "GDCVMRuntimeProfile",
    "InstanceConfig",
    "NGFWAttachmentConfig",
    "RangeConfig",
    "RangeNetworkConfig",
    "SubnetConfig",
    "decrypt_field",
    "generate_presigned_url",
    "get_gcp_range_backend",
    "get_range_availability_zone",
    "get_range_from_db",
    "has_ngfw_attachment_state",
    "is_gce_range_cell_backend",
    "load_aces_content_delivery_config",
    "load_aws_polaris_agent_config",
    "load_gce_range_cell_config",
    "load_gdc_network_access_config",
    "load_gdc_palo_alto_vmseries_config",
    "load_gdc_scenario_pod_config",
    "load_gdc_vmruntime_config",
    "load_range_network_config",
    "resolve_cloud_provider",
    "resolve_ngfw_attachment_config",
]
