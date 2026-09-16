"""Tests for the GKE-native GCP task runner."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from shared.cloud import PROVISIONER_CONTAINER_NAME
from shared.cloud.exceptions import CloudTaskError
from shared.cloud.gcp.task_runner import GCPTaskRunner
from shared.cloud.kubernetes.naming import build_idempotent_job_name


class _ApiException(Exception):
    def __init__(self, status: int):
        super().__init__(f"status={status}")
        self.status = status


def _make_fake_k8s_client() -> SimpleNamespace:
    """Build a SimpleNamespace stand-in for kubernetes.client.

    The real client classes accept keyword args and store them as attributes;
    SimpleNamespace mirrors that contract well enough for unit tests asserting
    on the produced Job spec without pulling in the kubernetes package.
    """
    return SimpleNamespace(
        V1EnvVar=lambda **kwargs: SimpleNamespace(**kwargs),
        V1EnvVarSource=lambda **kwargs: SimpleNamespace(**kwargs),
        V1SecretKeySelector=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Secret=lambda **kwargs: SimpleNamespace(**kwargs),
        V1OwnerReference=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Container=lambda **kwargs: SimpleNamespace(**kwargs),
        V1PodSpec=lambda **kwargs: SimpleNamespace(**kwargs),
        V1ObjectMeta=lambda **kwargs: SimpleNamespace(**kwargs),
        V1PodTemplateSpec=lambda **kwargs: SimpleNamespace(**kwargs),
        V1JobSpec=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Job=lambda **kwargs: SimpleNamespace(**kwargs),
        V1SecurityContext=lambda **kwargs: SimpleNamespace(**kwargs),
        V1PodSecurityContext=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Capabilities=lambda **kwargs: SimpleNamespace(**kwargs),
        V1SeccompProfile=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Volume=lambda **kwargs: SimpleNamespace(**kwargs),
        V1VolumeMount=lambda **kwargs: SimpleNamespace(**kwargs),
        V1EmptyDirVolumeSource=lambda **kwargs: SimpleNamespace(**kwargs),
        V1Toleration=lambda **kwargs: SimpleNamespace(**kwargs),
    )


def _observed_job(
    *,
    task_identity: str,
    image: str = "provisioner:latest",
    command: list[str] | None = None,
    service_account_name: str = "",
    secret_name: str | None = None,
) -> SimpleNamespace:
    """Build the deterministic fields required for create-or-observe recovery."""
    env = []
    if secret_name is not None:
        env.append(SimpleNamespace(value_from=SimpleNamespace(secret_key_ref=SimpleNamespace(name=secret_name))))
    name = build_idempotent_job_name("pulumi-provisioner", task_identity)
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            uid=f"uid-{task_identity}",
            annotations={"shifter.dev/task-identity": task_identity},
        ),
        spec=SimpleNamespace(
            template=SimpleNamespace(
                spec=SimpleNamespace(
                    service_account_name=service_account_name,
                    containers=[
                        SimpleNamespace(
                            name="pulumi-provisioner",
                            image=image,
                            args=command or ["range", "provision"],
                            env=env,
                        )
                    ],
                )
            )
        ),
    )


class TestGCPTaskRunnerRunTask:
    """Job creation behavior."""

    def test_creates_namespaced_job(self, settings) -> None:
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "shifter-provisioner"
        settings.ENGINE_TASK_IMAGE_PULL_POLICY = "Always"
        settings.ENGINE_TASK_BACKOFF_LIMIT = 1
        settings.ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED = 900

        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="pulumi-provisioner-range-provision-abc123")
        )
        core_api = MagicMock()

        client = _make_fake_k8s_client()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))

        task_id = runner.run_task(
            task_definition="us-central1-docker.pkg.dev/test/provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision", "--range-id", "42"],
            container_name="pulumi-provisioner",
            env_overrides={"CLOUD_PROVIDER": "gcp"},
        )

        assert task_id == "shifter-jobs/pulumi-provisioner-range-provision-abc123"
        call_kwargs = batch_api.create_namespaced_job.call_args.kwargs
        assert call_kwargs["namespace"] == "shifter-jobs"
        job = call_kwargs["body"]
        assert job.metadata.generate_name.startswith("pulumi-provisioner-range-provision-")
        assert job.spec.template.spec.service_account_name == "shifter-provisioner"
        assert job.spec.template.spec.automount_service_account_token is False
        assert job.spec.template.spec.containers[0].image == "us-central1-docker.pkg.dev/test/provisioner:latest"
        assert job.spec.template.spec.containers[0].args == ["range", "provision", "--range-id", "42"]
        assert job.spec.template.spec.containers[0].image_pull_policy == "Always"
        assert job.spec.backoff_limit == 1
        assert job.spec.ttl_seconds_after_finished == 900

    def test_provisioner_job_is_pinned_to_the_exclusive_provisioner_pool(self) -> None:
        # #1711: provisioner Jobs SSH-drive range hosts and probe the OpenVPN
        # gateway, so they must run on the tainted provisioner node pool to source
        # from the provisioner pod range the range VPC's management ingress admits.
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="pulumi-provisioner-range-provision-abc123")
        )
        client = _make_fake_k8s_client()
        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, MagicMock(), client, _ApiException))

        runner.run_task(
            task_definition="us-central1-docker.pkg.dev/test/provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision", "--range-id", "42"],
            container_name="pulumi-provisioner",
            env_overrides={"CLOUD_PROVIDER": "gcp"},
        )

        pod_spec = batch_api.create_namespaced_job.call_args.kwargs["body"].spec.template.spec
        assert pod_spec.node_selector == {"node-restriction.kubernetes.io/shifter-pool": "provisioner"}
        toleration = pod_spec.tolerations[0]
        assert (toleration.key, toleration.operator, toleration.value, toleration.effect) == (
            "dedicated",
            "Equal",
            "provisioner",
            "NoSchedule",
        )

    def test_requires_namespace(self) -> None:
        runner = GCPTaskRunner()

        with pytest.raises(CloudTaskError, match="namespace"):
            runner.run_task(
                task_definition="image:latest",
                cluster="",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
            )

    def test_task_identity_uses_create_or_observe_job_name(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job.side_effect = _ApiException(404)
        expected_name = build_idempotent_job_name("pulumi-provisioner", "intent-1")
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name=expected_name))
        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(
            return_value=(batch_api, MagicMock(), _make_fake_k8s_client(), _ApiException)
        )

        task_id = runner.run_task(
            task_definition="provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision", "--request-id", "11111111-1111-1111-1111-111111111111"],
            container_name="pulumi-provisioner",
            task_identity="intent-1",
        )

        job = batch_api.create_namespaced_job.call_args.kwargs["body"]
        assert job.metadata.name
        assert job.metadata.annotations["shifter.dev/task-identity"] == "intent-1"
        assert not hasattr(job.metadata, "generate_name")
        assert batch_api.read_namespaced_job.call_args.kwargs["_request_timeout"] == 30
        assert batch_api.create_namespaced_job.call_args.kwargs["_request_timeout"] == 30
        assert task_id == f"shifter-jobs/{job.metadata.name}"

    def test_redelivery_observes_existing_idempotent_job(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job.return_value = _observed_job(
            task_identity="intent-1",
            command=["range", "provision", "--request-id", "11111111-1111-1111-1111-111111111111"],
        )
        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(
            return_value=(batch_api, MagicMock(), _make_fake_k8s_client(), _ApiException)
        )

        task_id = runner.run_task(
            task_definition="provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision", "--request-id", "11111111-1111-1111-1111-111111111111"],
            container_name="pulumi-provisioner",
            task_identity="intent-1",
        )

        assert task_id.startswith("shifter-jobs/pulumi-provisioner-")
        batch_api.create_namespaced_job.assert_not_called()

    def test_redelivery_rejects_reserved_name_with_mismatched_intent(self) -> None:
        batch_api = MagicMock()
        observed = _observed_job(task_identity="other-intent")
        observed.metadata.name = build_idempotent_job_name("pulumi-provisioner", "intent-1")
        batch_api.read_namespaced_job.return_value = observed
        core_api = MagicMock()
        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(
            return_value=(batch_api, core_api, _make_fake_k8s_client(), _ApiException)
        )

        with pytest.raises(CloudTaskError, match="reserved provisioner launch identity"):
            runner.run_task(
                task_definition="provisioner:latest",
                cluster="shifter-jobs",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
                task_identity="intent-1",
            )

        batch_api.create_namespaced_job.assert_not_called()
        batch_api.delete_namespaced_job.assert_not_called()
        core_api.delete_namespaced_secret.assert_not_called()

    def test_observed_job_patch_failure_preserves_accepted_objects(self) -> None:
        task_identity = "11111111-1111-1111-1111-111111111111"
        secret_name = GCPTaskRunner._build_secret_name("pulumi-provisioner", task_identity)
        batch_api = MagicMock()
        batch_api.read_namespaced_job.return_value = _observed_job(
            task_identity=task_identity,
            secret_name=secret_name,
        )
        core_api = MagicMock()
        core_api.create_namespaced_secret.side_effect = _ApiException(409)
        core_api.patch_namespaced_secret.side_effect = [None, RuntimeError("temporary API failure")]
        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(
            return_value=(batch_api, core_api, _make_fake_k8s_client(), _ApiException)
        )

        with pytest.raises(CloudTaskError, match="ownerReference"):
            runner.run_task(
                task_definition="provisioner:latest",
                cluster="shifter-jobs",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
                env_overrides={"DB_PASSWORD": "supersecret"},
                task_identity=task_identity,
            )

        assert core_api.patch_namespaced_secret.call_count == 2
        batch_api.delete_namespaced_job.assert_not_called()
        core_api.delete_namespaced_secret.assert_not_called()

    def test_redelivery_rejects_job_referencing_another_intents_secret(self) -> None:
        task_identity = "11111111-1111-1111-1111-111111111111"
        batch_api = MagicMock()
        batch_api.read_namespaced_job.return_value = _observed_job(
            task_identity=task_identity,
            secret_name="pulumi-provisioner-secrets-ffffffffffffffff",
        )
        core_api = MagicMock()
        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(
            return_value=(batch_api, core_api, _make_fake_k8s_client(), _ApiException)
        )

        with pytest.raises(CloudTaskError, match="reserved provisioner launch identity"):
            runner.run_task(
                task_definition="provisioner:latest",
                cluster="shifter-jobs",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
                env_overrides={"DB_PASSWORD": "supersecret"},
                task_identity=task_identity,
            )

        batch_api.create_namespaced_job.assert_not_called()
        core_api.delete_namespaced_secret.assert_not_called()


class TestGCPTaskRunnerProvisionerContract:
    """Provisioner-only pod and cross-provider contract behavior."""

    def test_job_locks_down_runtime_writable_surface(self, settings) -> None:
        """Issue #1103: provisioner Jobs must run with read-only root filesystem and a
        single dedicated writable workspace volume. Without this, a process compromise
        inside a provisioner Job (already non-root after #950) could still tamper with
        the container's writable layer or with /app — keeping `/app` immutable closes
        that gap. The Job factory is the only enforcement point because Jobs are
        created dynamically (kube-linter does not see them)."""
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "shifter-provisioner"
        settings.ENGINE_TASK_IMAGE_PULL_POLICY = "Always"
        settings.ENGINE_TASK_BACKOFF_LIMIT = 0
        settings.ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED = 3600

        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="job-xyz"))
        core_api = MagicMock()
        client = _make_fake_k8s_client()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))

        runner.run_task(
            task_definition="us-central1-docker.pkg.dev/test/provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision", "--range-id", "42"],
            container_name="pulumi-provisioner",
        )

        job = batch_api.create_namespaced_job.call_args.kwargs["body"]
        container = job.spec.template.spec.containers[0]

        # Container security context — readOnlyRootFilesystem, runAsNonRoot,
        # and capability drop together implement the issue's contract.
        sc = container.security_context
        assert sc.read_only_root_filesystem is True
        assert sc.run_as_non_root is True
        assert sc.run_as_user == 1000
        assert sc.run_as_group == 1000
        assert sc.allow_privilege_escalation is False
        assert sc.capabilities.drop == ["ALL"]

        # Pod security context — seccompProfile=RuntimeDefault matches the
        # platform's existing worker-engine deployment baseline. fsGroup=1000
        # makes the kubelet chown the mounted emptyDir volumes to gid 1000 so
        # the non-root container can write to them — without it the volumes
        # come up root:root 700 and Terraform fails on first init.
        pod_sc = job.spec.template.spec.security_context
        assert pod_sc.seccomp_profile.type == "RuntimeDefault"
        assert pod_sc.fs_group == 1000
        assert pod_sc.fs_group_change_policy == "OnRootMismatch"

        # Writable surface is exactly four explicit volumes:
        # - workspace (terraform_base._stage_workspace target, issue #1103)
        # - /tmp (Python tempfile, kubectl temp kubeconfig, etc.)
        # - terraform plugin cache and pulumi home (HOME is read-only as a
        #   whole when we mount it that way, so the writable subdirs are
        #   explicit emptyDirs).
        volumes = {v.name: v for v in job.spec.template.spec.volumes}
        assert set(volumes.keys()) == {
            "provisioner-workspace",
            "tmp",
            "tf-plugin-cache",
            "pulumi-home",
        }
        # Workspace volume is memory-backed so terraform.tfvars.json (which can
        # carry secrets) does not persist on disk between Job restarts. The
        # size_limit caps node-memory pressure from a runaway plan log or
        # provider download — without it the volume could grow to 50% of node
        # memory by default.
        assert volumes["provisioner-workspace"].empty_dir.medium == "Memory"
        assert volumes["provisioner-workspace"].empty_dir.size_limit == "256Mi"

        mounts = {m.name: m.mount_path for m in container.volume_mounts}
        assert mounts == {
            "provisioner-workspace": "/var/run/provisioner/workspace",
            "tmp": "/tmp",  # noqa: S108 — Kubernetes mount path, not a tempfile API call
            "tf-plugin-cache": "/home/appuser/.terraform.d/plugin-cache",
            "pulumi-home": "/home/appuser/.pulumi",
        }

    def test_canonical_provisioner_job_satisfies_admission_policy(self, settings) -> None:
        """Drift guard for issue #1177.

        The ``restrict-provisioner-jobs`` ValidatingAdmissionPolicy admits a
        provisioner-SA Job only when it is the canonical builder output: a single
        container named ``pulumi-provisioner``, image equal to the runtime
        ENGINE_TASK_IMAGE, ``restartPolicy: Never``, and no extra (init)
        containers running as the privileged SA. If the builder ever diverges
        from that shape the policy would deny legitimate provisioning, so this
        test pins the builder to the same contract the policy enforces. The
        manifest-side of the contract is asserted in
        tests/platform/test_gcp_job_launcher_manifests.py.
        """
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "provisioner"

        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="job-1177"))
        core_api = MagicMock()
        client = _make_fake_k8s_client()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))

        image = "us-central1-docker.pkg.dev/test/shifter/pulumi-provisioner:sha-abc123"
        runner.run_task(
            task_definition=image,
            cluster="shifter-jobs",
            command=["range", "provision", "--range-id", "42"],
            container_name=PROVISIONER_CONTAINER_NAME,
        )

        pod_spec = batch_api.create_namespaced_job.call_args.kwargs["body"].spec.template.spec
        assert pod_spec.service_account_name == "provisioner"
        assert pod_spec.restart_policy == "Never"
        # The policy keys on a single provisioner container so no sidecar or
        # init container can run as the SA outside the pinned image.
        assert len(pod_spec.containers) == 1
        container = pod_spec.containers[0]
        assert container.name == PROVISIONER_CONTAINER_NAME
        assert container.image == image
        assert getattr(pod_spec, "init_containers", None) in (None, [])
        # The builder must keep the executable surface the policy pins: it sets
        # args only (never command, so the image entrypoint is forced), the args
        # start with an allowed resource family, and it never uses envFrom.
        assert getattr(container, "command", None) is None
        assert container.args[0] in ("range", "ngfw")
        assert getattr(container, "env_from", None) in (None, [])
        # Volumes are all emptyDir (the policy denies secret/configMap/hostPath
        # mounts into the privileged Pod).
        assert all(getattr(v, "empty_dir", None) is not None for v in pod_spec.volumes)

    def test_provisioner_container_name_lives_in_cloud_neutral_module(self) -> None:
        """The provisioner contract is cross-provider (AWS/ECS dispatch and GCP Job
        hardening both key off the same container name). It MUST live at the
        cloud-neutral ``shared.cloud`` layer rather than inside ``shared.cloud.gcp.*``,
        so AWS orchestration code does not have to import from the GCP module —
        which would couple AWS dispatch to a GCP-namespaced symbol and break the
        cloud abstraction the factory functions enforce."""
        import importlib

        cloud_module = importlib.import_module("shared.cloud")
        assert hasattr(cloud_module, "PROVISIONER_CONTAINER_NAME"), (
            "shared.cloud must export PROVISIONER_CONTAINER_NAME at the cloud-neutral layer"
        )
        # The GCP runner re-exports it for backward-compat / co-location with the
        # gating logic, but the source of truth is shared.cloud.
        from shared.cloud import PROVISIONER_CONTAINER_NAME as cloud_constant
        from shared.cloud.gcp import task_runner as gcp_module

        assert cloud_constant == gcp_module.PROVISIONER_CONTAINER_NAME
        assert gcp_module.PROVISIONER_CONTAINER_NAME is cloud_constant, (
            "GCP task_runner must re-export the cloud-neutral constant, not redefine it"
        )

    def test_provisioner_container_name_matches_ecs_task_definition(self) -> None:
        """The ECS task definition under platform/terraform/modules/engine-provisioner
        also has to carry the provisioner's container name. Terraform can't import the
        Python constant, so we lock in alignment with a structural assertion: the .tf
        file MUST contain `name = "<PROVISIONER_CONTAINER_NAME>"`. A future Python-side
        rename without a matching .tf update would fail this test."""
        from pathlib import Path

        from shared.cloud.gcp.task_runner import PROVISIONER_CONTAINER_NAME

        repo_root = Path(__file__).resolve().parents[5]
        tf_path = repo_root / "platform" / "terraform" / "modules" / "engine-provisioner" / "task_definition.tf"
        source = tf_path.read_text(encoding="utf-8")
        assert re.search(rf'\bname\s*=\s*"{re.escape(PROVISIONER_CONTAINER_NAME)}"', source), (
            f"task_definition.tf must reference the provisioner container name "
            f"{PROVISIONER_CONTAINER_NAME!r} that the GCP task runner gates hardening on; "
            "renaming one without the other would silently break ECS↔GCP alignment"
        )

    def test_provisioner_container_name_is_used_at_engine_dispatch_sites(self) -> None:
        """The hardening gate inside `_is_provisioner_task` keys on the cloud-neutral
        ``PROVISIONER_CONTAINER_NAME`` constant, and the engine dispatch sites in
        the ``shifter/shifter_platform/engine/ecs`` package MUST pass that exact
        constant when calling ``run_task``. Otherwise a rename of the constant would
        silently disable the issue #1103 hardening for production traffic. The engine
        layer imports from ``shared.cloud`` (cloud-neutral) — NOT from
        ``shared.cloud.gcp.*`` — to keep AWS dispatch decoupled from GCP modules."""
        import re
        from pathlib import Path

        from shared.cloud import PROVISIONER_CONTAINER_NAME

        # engine.ecs is a package (#685); scan every module in it so the contract
        # holds regardless of which submodule owns the import / dispatch sites.
        ecs_dir = Path(__file__).resolve().parents[3] / "engine" / "ecs"
        source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(ecs_dir.glob("*.py")))

        # The engine package must import the constant from the cloud-neutral layer.
        assert re.search(
            r"from shared\.cloud import [^\n]*\bPROVISIONER_CONTAINER_NAME\b",
            source,
        ), "engine/ecs must import PROVISIONER_CONTAINER_NAME from cloud-neutral shared.cloud"
        # And NOT from shared.cloud.gcp.* (which would break the cloud abstraction).
        assert (
            "from shared.cloud.gcp" not in source
            or "PROVISIONER_CONTAINER_NAME" not in source.split("from shared.cloud.gcp")[1].splitlines()[0]
        ), "engine/ecs must NOT import PROVISIONER_CONTAINER_NAME from shared.cloud.gcp.*"

        # Every run_task call site in the engine must dispatch with the
        # constant — no string literals like `"pulumi-provisioner"` allowed.
        run_task_calls = list(re.finditer(r"runner\.run_task\((.*?)\)", source, flags=re.DOTALL))
        assert run_task_calls, "engine/ecs must contain runner.run_task call sites"
        for match in run_task_calls:
            args = match.group(1)
            if "container_name" not in args:
                continue
            assert "container_name=PROVISIONER_CONTAINER_NAME" in args, (
                f"run_task call must dispatch with PROVISIONER_CONTAINER_NAME, got:\n{args}"
            )
            assert f'"{PROVISIONER_CONTAINER_NAME}"' not in args, (
                "run_task call must use the imported constant, not the string literal"
            )

    def test_non_provisioner_task_keeps_existing_contract(self, settings) -> None:
        """Issue #1103 hardening is provisioner-specific. Other tasks launched through
        the shared GCPTaskRunner (e.g. CMS experiment-executor) MUST keep their current
        contract — no readOnlyRootFilesystem, no provisioner-specific volume mounts —
        until the runner protocol grows a per-task runtime profile parameter. Forcing
        the provisioner mounts onto every shared-runner caller would either break image
        layouts that don't have those paths or hide other tasks' real security gaps."""
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "shifter-cms"
        settings.ENGINE_TASK_IMAGE_PULL_POLICY = "IfNotPresent"
        settings.ENGINE_TASK_BACKOFF_LIMIT = 0
        settings.ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED = 3600

        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="exp-job-7"))
        core_api = MagicMock()
        client = _make_fake_k8s_client()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))

        runner.run_task(
            task_definition="us-central1-docker.pkg.dev/test/experiment-executor:latest",
            cluster="shifter-jobs",
            command=["run", "--experiment-id", "42"],
            container_name="experiment-executor",
        )

        job = batch_api.create_namespaced_job.call_args.kwargs["body"]
        container = job.spec.template.spec.containers[0]
        # Provisioner-specific kwargs must NOT be set on a non-provisioner container.
        assert not hasattr(container, "security_context")
        assert not hasattr(container, "volume_mounts")
        # Pod-level provisioner-specific kwargs must NOT be set either.
        assert not hasattr(job.spec.template.spec, "security_context")
        assert not hasattr(job.spec.template.spec, "volumes")


class TestGCPTaskRunnerGetTaskStatus:
    """Job status mapping behavior."""

    def test_returns_running_status(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.return_value = SimpleNamespace(
            status=SimpleNamespace(
                active=1,
                failed=0,
                succeeded=0,
                start_time="2026-04-08T01:02:03Z",
                completion_time=None,
                conditions=[],
            )
        )
        core_api = MagicMock()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, SimpleNamespace(), _ApiException))

        result = runner.get_task_status("shifter-jobs", "shifter-jobs/pulumi-provisioner-range-provision-abc123")

        assert result is not None
        assert result["status"] == "RUNNING"
        assert result["desired_status"] == "RUNNING"
        assert result["task_id"] == "shifter-jobs/pulumi-provisioner-range-provision-abc123"

    def test_returns_succeeded_status(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.return_value = SimpleNamespace(
            status=SimpleNamespace(
                active=0,
                failed=0,
                succeeded=1,
                start_time="2026-04-08T01:02:03Z",
                completion_time="2026-04-08T01:05:03Z",
                conditions=[SimpleNamespace(type="Complete", message="Completed successfully", reason="Completed")],
            )
        )
        core_api = MagicMock()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, SimpleNamespace(), _ApiException))

        result = runner.get_task_status("shifter-jobs", "job-abc123")

        assert result is not None
        assert result["status"] == "SUCCEEDED"
        assert result["desired_status"] == "COMPLETED"
        assert result["stopped_reason"] == "Completed successfully"

    def test_returns_failed_status_with_pod_reason(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.return_value = SimpleNamespace(
            status=SimpleNamespace(
                active=0,
                failed=1,
                succeeded=0,
                start_time="2026-04-08T01:02:03Z",
                completion_time="2026-04-08T01:05:03Z",
                conditions=[],
            )
        )
        terminated = SimpleNamespace(message="container exited 1", reason="Error")
        pod = SimpleNamespace(
            status=SimpleNamespace(
                container_statuses=[
                    SimpleNamespace(state=SimpleNamespace(terminated=terminated)),
                ]
            )
        )
        core_api = MagicMock()
        core_api.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, SimpleNamespace(), _ApiException))

        result = runner.get_task_status("shifter-jobs", "job-abc123")

        assert result is not None
        assert result["status"] == "FAILED"
        assert result["stopped_reason"] == "container exited 1"

    def test_returns_none_on_missing_job(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.side_effect = _ApiException(status=404)
        core_api = MagicMock()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, SimpleNamespace(), _ApiException))

        assert runner.get_task_status("shifter-jobs", "job-abc123") is None
