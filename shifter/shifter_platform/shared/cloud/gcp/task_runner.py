"""GKE-native GCP adapter over the provider-neutral Kubernetes task runner.

The generic Kubernetes Job mechanics (manifest build, create-or-observe
lifecycle, sensitive-env Secret projection, interrupt, status) live in
``shared.cloud.kubernetes`` (#1824). This module is the thin GCP adapter: it
builds a ``KubernetesTaskProfile`` from Django settings plus the GCP-specific
identity/label/hardening choices and composes ``KubernetesTaskRunner``.

It remains the public face of the adapter so callers keep using
``from shared.cloud.gcp.task_runner import GCPTaskRunner`` exactly as before, and
the AWS/GCP cloud-adapter seam (ADR-005-R1) still pairs
``cloud/aws/task_runner.py`` with ``cloud/gcp/task_runner.py``. The Workload
Identity KSA (``ENGINE_TASK_SERVICE_ACCOUNT_NAME``) and the
``shifter.dev/task-runner: gcp`` label are GCP wiring injected here, never generic
Kubernetes defaults.
"""

from __future__ import annotations

from django.conf import settings

from shared.cloud import PROVISIONER_CONTAINER_NAME
from shared.cloud.kubernetes import KubernetesTaskProfile, KubernetesTaskRunner, standard_provisioner_hardening

# GCP task-runner provider tag stamped on Job/Secret metadata.
_SHIFTER_TASK_RUNNER_GCP = "gcp"

# Exclusive provisioner node-pool placement (#1711). Provisioner Jobs SSH-drive
# range hosts and probe the OpenVPN gateway; pinning them to the tainted
# provisioner pool gives their pods alias IPs from the provisioner pod range,
# which is the only source the range VPC's management ingress admits. The node
# label matches the pool's ``node-restriction.kubernetes.io/shifter-pool`` label
# and the toleration matches its ``dedicated=provisioner:NoSchedule`` taint (both
# in platform/terraform/gcp/modules/portal/gke/main.tf). The selector keys on the
# NodeRestriction-protected prefix (not the generic ``role`` label) so a
# compromised kubelet cannot self-label its node to attract provisioner Jobs
# (#1711 codex security finding).
_PROVISIONER_NODE_SELECTOR = {"node-restriction.kubernetes.io/shifter-pool": "provisioner"}
_PROVISIONER_TOLERATIONS = (("dedicated", "Equal", "provisioner", "NoSchedule"),)


def _build_gcp_task_profile() -> KubernetesTaskProfile:
    """Resolve the GCP Kubernetes task profile from Django settings at call time.

    Reading here (rather than at construction) preserves the historical timing:
    ``ENGINE_TASK_*`` values are owned by the runtime env/Helm renderers and read
    when a task is launched. The provisioner hardening posture (uid/gid/writable
    mounts) is the shared cloud-neutral contract; only the runner label and the
    Workload Identity KSA are GCP wiring.
    """
    return KubernetesTaskProfile(
        runner_label_value=_SHIFTER_TASK_RUNNER_GCP,
        service_account_name=str(getattr(settings, "ENGINE_TASK_SERVICE_ACCOUNT_NAME", "") or ""),
        image_pull_policy=getattr(settings, "ENGINE_TASK_IMAGE_PULL_POLICY", "IfNotPresent"),
        backoff_limit=getattr(settings, "ENGINE_TASK_BACKOFF_LIMIT", 0),
        ttl_seconds_after_finished=getattr(settings, "ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED", 3600),
        hardening=standard_provisioner_hardening(PROVISIONER_CONTAINER_NAME),
        node_selector=_PROVISIONER_NODE_SELECTOR,
        tolerations=_PROVISIONER_TOLERATIONS,
    )


class GCPTaskRunner(KubernetesTaskRunner):
    """GCP adapter: the neutral Kubernetes runner wired with the GCP task profile.

    For GCP the ECS-shaped TaskRunner interface is reinterpreted by the neutral
    core: ``cluster`` is the Kubernetes namespace, ``task_definition`` the image,
    and ``command`` the container args (image ENTRYPOINT preserved).
    """

    def __init__(self) -> None:
        super().__init__(_build_gcp_task_profile)


__all__ = ("PROVISIONER_CONTAINER_NAME", "GCPTaskRunner")
