"""AWS (EKS) task-runner adapter.

Paired with the GCP adapter across the ADR-005-R1 cloud seam. Like
``GCPTaskRunner``, ``AWSKubernetesTaskRunner`` composes the provider-neutral
``KubernetesTaskRunner`` (``shared.cloud.kubernetes``) with an AWS
``KubernetesTaskProfile``: the ``shifter.dev/task-runner: aws`` label and the
IRSA-annotated ``ENGINE_TASK_SERVICE_ACCOUNT_NAME`` are the AWS wiring; the
provisioner hardening posture is the shared cloud-neutral contract. This is what
``get_task_runner()`` returns for AWS (#1826): the Shifter management plane runs
on EKS and dispatches the provisioner as a Kubernetes Job, matching the GCP
substrate. AWS range/target delivery remains ECS/VM behind the ADR-039 range
adapter, a separate transport from this provisioner-dispatch runner.
"""

from __future__ import annotations

from django.conf import settings

from shared.cloud import PROVISIONER_CONTAINER_NAME
from shared.cloud.kubernetes import KubernetesTaskProfile, KubernetesTaskRunner, standard_provisioner_hardening

# AWS task-runner provider tag stamped on Job/Secret metadata. Distinct from the
# GCP "gcp" value so the fail-closed provisioner admission policy binds the AWS
# runner to its own AWS-derived contract, never the GCP one.
_SHIFTER_TASK_RUNNER_AWS = "aws"


def _build_aws_task_profile() -> KubernetesTaskProfile:
    """Resolve the AWS (EKS) Kubernetes task profile from Django settings at call time.

    Mirrors ``_build_gcp_task_profile``: the ``ENGINE_TASK_*`` values are owned by
    the runtime env / Helm renderers and read when a task is launched. The
    service account is IRSA-annotated on the cluster side (not GCP Workload
    Identity); the provisioner hardening posture is the shared cloud-neutral
    contract.
    """
    return KubernetesTaskProfile(
        runner_label_value=_SHIFTER_TASK_RUNNER_AWS,
        service_account_name=str(getattr(settings, "ENGINE_TASK_SERVICE_ACCOUNT_NAME", "") or ""),
        image_pull_policy=getattr(settings, "ENGINE_TASK_IMAGE_PULL_POLICY", "IfNotPresent"),
        backoff_limit=getattr(settings, "ENGINE_TASK_BACKOFF_LIMIT", 0),
        ttl_seconds_after_finished=getattr(settings, "ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED", 3600),
        hardening=standard_provisioner_hardening(PROVISIONER_CONTAINER_NAME),
    )


class AWSKubernetesTaskRunner(KubernetesTaskRunner):
    """AWS adapter: the neutral Kubernetes runner wired with the AWS task profile.

    For AWS the ECS-shaped TaskRunner interface is reinterpreted by the neutral
    core exactly as for GCP: ``cluster`` is the Kubernetes namespace,
    ``task_definition`` the image, and ``command`` the container args.
    """

    def __init__(self) -> None:
        super().__init__(_build_aws_task_profile)


__all__ = ("AWSKubernetesTaskRunner",)
