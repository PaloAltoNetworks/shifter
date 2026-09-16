"""Dedicated preparation profiles composed with the existing neutral Job runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from shared.cloud.kubernetes import KubernetesTaskProfile, KubernetesTaskRunner, ProvisionerHardeningProfile
from shared.cloud.kubernetes.naming import build_idempotent_job_name
from shared.preparation_grant import PreparationGrantConfiguration

CONTAINER = "artifact-preparation"


@dataclass(frozen=True)
class PreparationTask:
    """One immutable task identity; credentials are passed only at dispatch time."""

    grant: PreparationGrantConfiguration = field(repr=False)
    profile: KubernetesTaskProfile = field(repr=False)
    image: str = field(repr=False)
    operation_id: UUID
    attempt_id: UUID

    @property
    def identity(self) -> str:
        return f"preparation:{self.operation_id}:{self.attempt_id}"

    @property
    def task_ref(self) -> str:
        return f"{self.grant.namespace}/{build_idempotent_job_name(CONTAINER, self.identity)}"

    @property
    def expected_identity(self) -> dict[str, object]:
        """Interruption verifies every field before deleting the Job and its pods."""
        return {
            "task_identity": self.identity,
            "service_account_name": self.profile.service_account_name,
            "container_name": CONTAINER,
            "image": self.image,
            "command": [],
        }

    def dispatch(self, token: str) -> str | None:
        """Use create-or-observe and the runner's per-Job sensitive-env Secret."""
        return KubernetesTaskRunner(self.profile).run_task(
            task_definition=self.image,
            cluster=self.grant.namespace,
            command=[],
            container_name=CONTAINER,
            task_identity=self.identity,
            env_overrides={
                "PREPARATION_OPERATION_ID": str(self.operation_id),
                "PREPARATION_ATTEMPT_ID": str(self.attempt_id),
                "PREPARATION_ENDPOINT": self.grant.worker_endpoint,
                "PREPARATION_TOKEN": token,
            },
        )

    def interrupt(self) -> str:
        """Foreground deletion and pod absence precede cloud resource cleanup."""
        return KubernetesTaskRunner(self.profile).interrupt_task(
            self.grant.namespace, self.task_ref, self.expected_identity
        )

    def status(self) -> str:
        """Expose only task state; provider diagnostics never become operator status."""
        observed = KubernetesTaskRunner(self.profile).get_task_status(self.grant.namespace, self.task_ref)
        return observed.get("status", "UNKNOWN") if observed is not None else "UNKNOWN"


def preparation_task(
    grant: PreparationGrantConfiguration, phase: str, image: str, operation_id: UUID, attempt_id: UUID
) -> PreparationTask:
    """Bind role, executable, limits and private pulls from the separately installed grant."""
    roles = {
        "build": (grant.builder_service_account, grant.approved_worker_images),
        "verify-inputs": (grant.verifier_service_account, grant.approved_verifier_images),
        "verify-output": (grant.verifier_service_account, grant.approved_verifier_images),
        "cleanup": (grant.cleanup_service_account, [grant.cleanup_image]),
    }
    if phase not in roles or image not in roles[phase][1]:
        raise ValueError("preparation executable is not approved for this role")
    profile = KubernetesTaskProfile(
        runner_label_value=CONTAINER,
        service_account_name=roles[phase][0],
        image_pull_policy="IfNotPresent",
        backoff_limit=0,
        ttl_seconds_after_finished=3600,
        hardening=ProvisionerHardeningProfile(
            container_name=CONTAINER,
            run_as_uid=1000,
            run_as_gid=1000,
            writable_mounts=(
                ("tmp", "/tmp", "Memory", "64Mi"),  # noqa: S108  # nosec B108  # NOSONAR
            ),
        ),
        image_pull_secrets=tuple(grant.image_pull_secrets),
        resource_requests={"cpu": "100m", "memory": "256Mi"},
        resource_limits={"cpu": "1", "memory": "512Mi"},
        active_deadline_seconds=grant.max_duration_seconds,
        node_selector={"iam.gke.io/gke-metadata-server-enabled": "true"},
    )
    return PreparationTask(grant, profile, image, operation_id, attempt_id)
