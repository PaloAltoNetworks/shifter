"""GDC mixed-asset scenario Pod lifecycle for shared L2 subnets.

Split across private submodules by responsibility and re-exported here so
callers keep using ``from gdc_scenario_pods import X`` /
``gdc_scenario_pods.<name>`` exactly as before the split:

- ``_kube``: Kubernetes client construction and Pod apply/wait helpers
  (``_import_kubernetes_modules``, ``_build_kube_api_client``, ``_apply_pod``,
  ``_extract_network_status_ip``, ``_wait_for_pod_ready``,
  ``_wait_for_pod_deleted``, ``_is_pod_ready``).
- ``_manifest``: Pod naming, labeling, and manifest construction
  (``_sanitize_name``, ``_assignment_key``, ``_is_scenario_pod``,
  ``_pod_name``, ``_pod_labels``, ``_build_networks_annotation``,
  ``_build_pod_manifest``, ``_first_non_empty_str``,
  ``_build_subnet_pod_context``, ``_get_runtime_metadata``).
- ``_ops``: power operations and range-asset apply/destroy orchestration
  (``_resolve_power_target``, ``_create_scenario_pod_asset``,
  ``_delete_scenario_pod_asset``, ``run_power_operation``,
  ``apply_range_assets``, ``destroy_range_assets``).

Six collaborator names below (``_build_kube_api_client``,
``_import_kubernetes_modules``, ``_wait_for_pod_ready``,
``_wait_for_pod_deleted``, ``load_gdc_network_access_config``,
``load_gdc_scenario_pod_config``) are re-exported here - not just imported by
the submodule that defines/uses them - because the test suite patches them at
``gdc_scenario_pods.<name>``. Submodule functions call back into this package
at call time (``import gdc_scenario_pods as _pkg; _pkg.<name>``) so those
patches take effect, mirroring the ``range_ops`` and ``terraform_base``
splits.
"""

from __future__ import annotations

from config import load_gdc_network_access_config, load_gdc_scenario_pod_config

from ._kube import (
    _apply_pod,
    _build_kube_api_client,
    _extract_network_status_ip,
    _import_kubernetes_modules,
    _is_pod_ready,
    _wait_for_pod_deleted,
    _wait_for_pod_ready,
)
from ._manifest import (
    _assignment_key,
    _build_networks_annotation,
    _build_pod_manifest,
    _build_subnet_pod_context,
    _first_non_empty_str,
    _get_runtime_metadata,
    _is_scenario_pod,
    _pod_labels,
    _pod_name,
    _sanitize_name,
)
from ._ops import (
    _create_scenario_pod_asset,
    _delete_scenario_pod_asset,
    _resolve_power_target,
    apply_range_assets,
    destroy_range_assets,
    run_power_operation,
)

__all__ = [
    "_apply_pod",
    "_assignment_key",
    "_build_kube_api_client",
    "_build_networks_annotation",
    "_build_pod_manifest",
    "_build_subnet_pod_context",
    "_create_scenario_pod_asset",
    "_delete_scenario_pod_asset",
    "_extract_network_status_ip",
    "_first_non_empty_str",
    "_get_runtime_metadata",
    "_import_kubernetes_modules",
    "_is_pod_ready",
    "_is_scenario_pod",
    "_pod_labels",
    "_pod_name",
    "_resolve_power_target",
    "_sanitize_name",
    "_wait_for_pod_deleted",
    "_wait_for_pod_ready",
    "apply_range_assets",
    "destroy_range_assets",
    "load_gdc_network_access_config",
    "load_gdc_scenario_pod_config",
    "run_power_operation",
]
