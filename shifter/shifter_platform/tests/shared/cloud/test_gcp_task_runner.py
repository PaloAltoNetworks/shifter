"""Tests for the GKE-native GCP task runner."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.gcp.task_runner import GCPTaskRunner


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
        assert job.spec.template.spec.containers[0].image == "us-central1-docker.pkg.dev/test/provisioner:latest"
        assert job.spec.template.spec.containers[0].args == ["range", "provision", "--range-id", "42"]
        assert job.spec.template.spec.containers[0].image_pull_policy == "Always"
        assert job.spec.backoff_limit == 1
        assert job.spec.ttl_seconds_after_finished == 900

    def test_requires_namespace(self) -> None:
        runner = GCPTaskRunner()

        with pytest.raises(CloudTaskError, match="namespace"):
            runner.run_task(
                task_definition="image:latest",
                cluster="",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
            )

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
        `shifter/shifter_platform/engine/ecs.py` MUST pass that exact constant when
        calling ``run_task``. Otherwise a rename of the constant would silently
        disable the issue #1103 hardening for production traffic. The engine layer
        imports from ``shared.cloud`` (cloud-neutral) — NOT from
        ``shared.cloud.gcp.*`` — to keep AWS dispatch decoupled from GCP modules."""
        import re
        from pathlib import Path

        from shared.cloud import PROVISIONER_CONTAINER_NAME

        ecs_path = Path(__file__).resolve().parents[3] / "engine" / "ecs.py"
        source = ecs_path.read_text(encoding="utf-8")

        # The engine module must import the constant from the cloud-neutral layer.
        assert re.search(
            r"from shared\.cloud import [^\n]*\bPROVISIONER_CONTAINER_NAME\b",
            source,
        ), "engine/ecs.py must import PROVISIONER_CONTAINER_NAME from cloud-neutral shared.cloud"
        # And NOT from shared.cloud.gcp.* (which would break the cloud abstraction).
        assert (
            "from shared.cloud.gcp" not in source
            or "PROVISIONER_CONTAINER_NAME" not in source.split("from shared.cloud.gcp")[1].splitlines()[0]
        ), "engine/ecs.py must NOT import PROVISIONER_CONTAINER_NAME from shared.cloud.gcp.*"

        # Every run_task call site in the engine must dispatch with the
        # constant — no string literals like `"pulumi-provisioner"` allowed.
        run_task_calls = list(re.finditer(r"runner\.run_task\((.*?)\)", source, flags=re.DOTALL))
        assert run_task_calls, "engine/ecs.py must contain runner.run_task call sites"
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


class TestGCPTaskRunnerSensitiveEnv:
    """Issue #1185 — sensitive env vars must flow through Secret refs,
    not literal value= entries on the Pod spec.

    These tests assert the full Secret-then-Job-then-patchOwnerRef
    sequence, that sensitive keys never appear as ``value=`` anywhere
    in the Job spec, and that the Secret is cleaned up when Job
    creation fails after Secret creation.
    """

    def _make_runner(self, batch_api: MagicMock, core_api: MagicMock) -> GCPTaskRunner:
        client = _make_fake_k8s_client()
        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))
        return runner

    def _set_baseline_settings(self, settings: Any) -> None:
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "shifter-provisioner"
        settings.ENGINE_TASK_IMAGE_PULL_POLICY = "IfNotPresent"
        settings.ENGINE_TASK_BACKOFF_LIMIT = 0
        settings.ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED = 3600

    def test_sensitive_env_routes_through_secret_key_ref(self, settings) -> None:
        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="provisioner-abc123", uid="job-uid-xyz")
        )
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        runner.run_task(
            task_definition="provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision"],
            container_name="pulumi-provisioner",
            env_overrides={
                "DB_PASSWORD": "supersecret",
                "FIELD_ENCRYPTION_KEY": "key-material",
                "DC_DOMAIN_PASSWORD": "domain-pass",
                # Non-sensitive — stays literal.
                "DB_HOST": "rds.example.com",
                "CLOUD_PROVIDER": "gcp",
                # Secret Manager *id* — pointer, not material. Stays literal.
                "GDC_ACCESS_SECRET_ID": "projects/x/secrets/y",
            },
        )

        # Secret is created BEFORE the Job submission.
        assert core_api.create_namespaced_secret.call_count == 1
        secret_call = core_api.create_namespaced_secret.call_args.kwargs
        assert secret_call["namespace"] == "shifter-jobs"
        secret_body = secret_call["body"]
        assert secret_body.kind == "Secret"
        assert secret_body.type == "Opaque"
        # Sensitive values land in string_data; non-sensitive do not.
        assert set(secret_body.string_data.keys()) == {
            "DB_PASSWORD",
            "FIELD_ENCRYPTION_KEY",
            "DC_DOMAIN_PASSWORD",
        }
        assert secret_body.string_data["DB_PASSWORD"] == "supersecret"
        secret_name = secret_body.metadata.name
        assert secret_name.startswith("pulumi-provisioner-secrets-")

        # Job env list: sensitive keys use valueFrom.secret_key_ref;
        # non-sensitive keys keep literal value=.
        job = batch_api.create_namespaced_job.call_args.kwargs["body"]
        env_list = job.spec.template.spec.containers[0].env
        env_by_name = {e.name: e for e in env_list}

        for sensitive_key in ("DB_PASSWORD", "FIELD_ENCRYPTION_KEY", "DC_DOMAIN_PASSWORD"):
            entry = env_by_name[sensitive_key]
            # No literal value= on a sensitive entry.
            assert getattr(entry, "value", None) is None, f"{sensitive_key} leaked as literal value="
            ref = entry.value_from.secret_key_ref
            assert ref.name == secret_name
            assert ref.key == sensitive_key

        for plain_key, plain_value in (
            ("DB_HOST", "rds.example.com"),
            ("CLOUD_PROVIDER", "gcp"),
            ("GDC_ACCESS_SECRET_ID", "projects/x/secrets/y"),
        ):
            entry = env_by_name[plain_key]
            assert entry.value == plain_value
            assert getattr(entry, "value_from", None) is None

    def test_no_sensitive_values_means_no_secret_is_created(self, settings) -> None:
        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="job-1", uid="u"))
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        runner.run_task(
            task_definition="provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision"],
            container_name="pulumi-provisioner",
            env_overrides={"DB_HOST": "x", "CLOUD_PROVIDER": "gcp"},
        )

        core_api.create_namespaced_secret.assert_not_called()
        core_api.patch_namespaced_secret.assert_not_called()

    def test_secret_is_owner_referenced_to_job_after_creation(self, settings) -> None:
        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="job-abc", uid="uid-job-abc")
        )
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        runner.run_task(
            task_definition="provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision"],
            container_name="pulumi-provisioner",
            env_overrides={"DB_PASSWORD": "p"},
        )

        assert core_api.patch_namespaced_secret.call_count == 1
        patch_call = core_api.patch_namespaced_secret.call_args.kwargs
        assert patch_call["namespace"] == "shifter-jobs"
        owner_refs = patch_call["body"]["metadata"]["ownerReferences"]
        assert len(owner_refs) == 1
        owner = owner_refs[0]
        assert owner["kind"] == "Job"
        assert owner["apiVersion"] == "batch/v1"
        assert owner["name"] == "job-abc"
        assert owner["uid"] == "uid-job-abc"
        assert owner["controller"] is True
        assert owner["blockOwnerDeletion"] is True

    def test_secret_is_cleaned_up_when_job_creation_fails(self, settings) -> None:
        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.create_namespaced_job.side_effect = RuntimeError("apiserver said no")
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        with pytest.raises(CloudTaskError):
            runner.run_task(
                task_definition="provisioner:latest",
                cluster="shifter-jobs",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
                env_overrides={"DB_PASSWORD": "p"},
            )

        # Created the Secret first, then attempted Job, then cleaned up.
        assert core_api.create_namespaced_secret.call_count == 1
        assert core_api.delete_namespaced_secret.call_count == 1
        del_call = core_api.delete_namespaced_secret.call_args.kwargs
        assert del_call["namespace"] == "shifter-jobs"

    def test_owner_ref_patch_failure_unwinds_job_and_secret(self, settings) -> None:
        """Codex review #1180 cycle 1 finding 6: ownerReference
        installation is part of the success contract. If the patch
        fails, the run is rolled back (both Job and Secret deleted)
        and CloudTaskError is raised — instead of silently leaving
        an orphan Secret with sensitive payload."""
        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="job-x", uid="uid-x")
        )
        core_api = MagicMock()
        core_api.patch_namespaced_secret.side_effect = RuntimeError("patch denied")
        runner = self._make_runner(batch_api, core_api)

        with pytest.raises(CloudTaskError, match="ownerReference"):
            runner.run_task(
                task_definition="provisioner:latest",
                cluster="shifter-jobs",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
                env_overrides={"DB_PASSWORD": "p"},
            )

        batch_api.delete_namespaced_job.assert_called_once()
        del_job_kwargs = batch_api.delete_namespaced_job.call_args.kwargs
        assert del_job_kwargs["name"] == "job-x"
        core_api.delete_namespaced_secret.assert_called_once()

    def test_missing_job_uid_unwinds_job_and_secret(self, settings) -> None:
        """Job creation response omits a uid we can use as
        ownerReference target → treat as a hard failure: unwind both
        objects so we don't ship an orphan Secret."""
        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="job-x")  # NOTE: no uid
        )
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        with pytest.raises(CloudTaskError, match="uid"):
            runner.run_task(
                task_definition="provisioner:latest",
                cluster="shifter-jobs",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
                env_overrides={"DB_PASSWORD": "p"},
            )

        batch_api.delete_namespaced_job.assert_called_once()
        core_api.delete_namespaced_secret.assert_called_once()
        core_api.patch_namespaced_secret.assert_not_called()

    def test_missing_job_name_deletes_orphan_secret(self, settings) -> None:
        """If the apiserver returns a Job with no usable name, the
        Secret we created earlier must still be cleaned up."""
        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name=""))
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        with pytest.raises(CloudTaskError, match="Job name"):
            runner.run_task(
                task_definition="provisioner:latest",
                cluster="shifter-jobs",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
                env_overrides={"DB_PASSWORD": "p"},
            )

        core_api.delete_namespaced_secret.assert_called_once()

    def test_no_sensitive_key_appears_as_literal_value_on_any_pod_field(self, settings) -> None:
        """Regression: a future _build_env refactor that accidentally
        emits `value=` for a sensitive key would silently break the
        whole point of #1185. This test pins the invariant across
        every known sensitive name."""
        from shared.cloud.sensitive_env import SENSITIVE_NAMES

        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="j", uid="u"))
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        env_overrides = {key: f"value-of-{key}" for key in SENSITIVE_NAMES}
        env_overrides["DB_HOST"] = "rds.example.com"

        runner.run_task(
            task_definition="provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision"],
            container_name="pulumi-provisioner",
            env_overrides=env_overrides,
        )

        job = batch_api.create_namespaced_job.call_args.kwargs["body"]
        for entry in job.spec.template.spec.containers[0].env:
            if entry.name in SENSITIVE_NAMES:
                assert getattr(entry, "value", None) is None, f"Sensitive name {entry.name} emitted as literal value="
