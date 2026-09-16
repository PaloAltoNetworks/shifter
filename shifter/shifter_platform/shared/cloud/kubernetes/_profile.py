"""The injected profile that carries provider-variable Kubernetes task wiring.

The neutral Kubernetes task runner (#1824) owns only generic Job mechanics. Every
provider-specific choice — the runner label value, the runtime service account
(Workload Identity vs IRSA), image pull/backoff/TTL settings, and the provisioner
hardening posture — is resolved by the provider adapter and passed in as this
single frozen profile. The neutral core reads no Django settings and imports no
provider module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# An optional string field in the positional tuple type aliases below.
OptionalStr = str | None

# A writable mount: (volume name, mount path, emptyDir medium or None, size limit or None).
WritableMount = tuple[str, str, OptionalStr, OptionalStr]

# A node scheduling toleration: (key, operator, value or None, effect).
Toleration = tuple[str, str, OptionalStr, str]

# Provisioner runtime identity and writable surface (issue #950/#1103). These are
# image-specific and cloud-neutral: the same provisioner image runs on GKE and
# EKS, so both the GCP and AWS adapters share one hardening contract here rather
# than each duplicating the uid/gid/mount layout.
_PROVISIONER_RUN_AS_UID = 1000
_PROVISIONER_RUN_AS_GID = 1000
# Memory-backed workspace volume size cap. Terraform staging trees are tiny, but a
# runaway plan log or provider download could otherwise consume node memory
# unbounded; 256Mi is generous for the staged terraform/ tree plus plan output.
_PROVISIONER_WORKSPACE_SIZE_LIMIT = "256Mi"
# Writable mount points the provisioner image needs at runtime. /app and the rest
# of the root filesystem are read-only (issue #1103); these explicit emptyDir
# volumes are the only paths the runtime user can write to. workspace is
# memory-backed so terraform.tfvars.json (which can carry secrets) never persists
# on disk.
_PROVISIONER_WRITABLE_MOUNTS: tuple[WritableMount, ...] = (
    ("provisioner-workspace", "/var/run/provisioner/workspace", "Memory", _PROVISIONER_WORKSPACE_SIZE_LIMIT),
    ("tmp", "/tmp", None, None),  # noqa: S108 # nosec B108 — Kubernetes mount path, not a tempfile API call
    ("tf-plugin-cache", "/home/appuser/.terraform.d/plugin-cache", None, None),
    ("pulumi-home", "/home/appuser/.pulumi", None, None),
)


@dataclass(frozen=True)
class ProvisionerHardeningProfile:
    """Hardening applied to a single named task container.

    The restricted security-context *flags* (drop-ALL capabilities, read-only
    root filesystem, non-root, no privilege escalation, seccomp RuntimeDefault,
    ``automountServiceAccountToken=False``) are the generic restricted posture
    rendered by the neutral core. This profile carries the provider/image-variable
    inputs: which container to harden, the runtime uid/gid, and the explicit
    writable-mount layout that container's image needs.
    """

    container_name: str
    run_as_uid: int
    run_as_gid: int
    writable_mounts: tuple[WritableMount, ...]


@dataclass(frozen=True)
class KubernetesTaskProfile:
    """Provider-injected wiring for one Kubernetes task-runner instance."""

    runner_label_value: str
    service_account_name: str
    image_pull_policy: str
    backoff_limit: int
    ttl_seconds_after_finished: int
    hardening: ProvisionerHardeningProfile | None = None
    # Provider-injected node placement for launched task Jobs. Empty by default so
    # the neutral core and non-GCP adapters are unchanged; the GCP adapter pins
    # provisioner Jobs onto the exclusive provisioner node pool (#1711) so their
    # pod IPs come from the provisioner pod range that the range VPC's management
    # ingress is scoped to.
    node_selector: Mapping[str, str] | None = None
    tolerations: tuple[Toleration, ...] = field(default_factory=tuple)
    # Explicit runtime grants for private task images and bounded workers.
    # Empty defaults preserve existing provider profiles; the preparation
    # adapter supplies these from its validated, separately installed grant.
    image_pull_secrets: tuple[str, ...] = field(default_factory=tuple)
    resource_requests: Mapping[str, str] | None = None
    resource_limits: Mapping[str, str] | None = None
    active_deadline_seconds: int | None = None

    def hardening_for(self, container_name: str) -> ProvisionerHardeningProfile | None:
        """Return the hardening profile when it applies to ``container_name``."""
        if self.hardening is not None and container_name == self.hardening.container_name:
            return self.hardening
        return None


def standard_provisioner_hardening(container_name: str) -> ProvisionerHardeningProfile:
    """Return the cloud-neutral provisioner hardening contract for the shared image.

    The provisioner image, its non-root uid/gid, and its writable-mount layout are
    identical on every cloud, so both the GKE and EKS adapters build their
    ``KubernetesTaskProfile`` hardening from this single source of truth rather
    than each duplicating the uid/gid/mount layout.
    """
    return ProvisionerHardeningProfile(
        container_name=container_name,
        run_as_uid=_PROVISIONER_RUN_AS_UID,
        run_as_gid=_PROVISIONER_RUN_AS_GID,
        writable_mounts=_PROVISIONER_WRITABLE_MOUNTS,
    )
