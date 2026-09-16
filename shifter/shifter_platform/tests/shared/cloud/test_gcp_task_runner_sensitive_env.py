"""Sensitive-environment lifecycle tests for the GKE-native task runner."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

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


class _SensitiveEnvTestBase:
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


class TestGCPTaskRunnerSensitiveEnv(_SensitiveEnvTestBase):
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

    def test_ambiguous_create_reconciles_accepted_job_before_secret_cleanup(self, settings) -> None:
        self._set_baseline_settings(settings)
        task_identity = "11111111-1111-1111-1111-111111111111"
        observed_secret_name = GCPTaskRunner._build_secret_name("pulumi-provisioner", task_identity)
        observed = _observed_job(
            task_identity=task_identity,
            secret_name=observed_secret_name,
            service_account_name="shifter-provisioner",
        )
        batch_api = MagicMock()
        batch_api.read_namespaced_job.side_effect = [_ApiException(404), observed]
        batch_api.create_namespaced_job.side_effect = TimeoutError("ambiguous response")
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        task_id = runner.run_task(
            task_definition="provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision"],
            container_name="pulumi-provisioner",
            env_overrides={"DB_PASSWORD": "supersecret"},
            task_identity=task_identity,
        )

        assert task_id.startswith("shifter-jobs/pulumi-provisioner-")
        core_api.delete_namespaced_secret.assert_not_called()
        assert core_api.patch_namespaced_secret.call_args.kwargs["name"] == observed_secret_name
        batch_api.delete_namespaced_job.assert_not_called()

    def test_ambiguous_create_preserves_secret_when_job_is_not_yet_observable(self, settings) -> None:
        self._set_baseline_settings(settings)
        batch_api = MagicMock()
        batch_api.read_namespaced_job.side_effect = [_ApiException(404), _ApiException(404)]
        batch_api.create_namespaced_job.side_effect = TimeoutError("ambiguous response")
        core_api = MagicMock()
        runner = self._make_runner(batch_api, core_api)

        with pytest.raises(CloudTaskError):
            runner.run_task(
                task_definition="provisioner:latest",
                cluster="shifter-jobs",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
                env_overrides={"DB_PASSWORD": "supersecret"},
                task_identity="intent-ambiguous",
            )

        core_api.create_namespaced_secret.assert_called_once()
        core_api.delete_namespaced_secret.assert_not_called()

    def test_retry_recovers_deterministic_secret_after_ambiguous_create(self, settings) -> None:
        self._set_baseline_settings(settings)
        task_identity = "11111111-1111-1111-1111-111111111111"
        expected_job_name = build_idempotent_job_name("pulumi-provisioner", task_identity)
        batch_api = MagicMock()
        batch_api.read_namespaced_job.side_effect = _ApiException(404)
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name=expected_job_name, uid="job-uid")
        )
        core_api = MagicMock()
        core_api.create_namespaced_secret.side_effect = _ApiException(409)
        runner = self._make_runner(batch_api, core_api)

        runner.run_task(
            task_definition="provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision"],
            container_name="pulumi-provisioner",
            env_overrides={"DB_PASSWORD": "supersecret"},
            task_identity=task_identity,
        )

        expected_secret_name = runner._build_secret_name("pulumi-provisioner", task_identity)
        assert core_api.patch_namespaced_secret.call_args_list[0].kwargs["name"] == expected_secret_name
        recovery_body = core_api.patch_namespaced_secret.call_args_list[0].kwargs["body"]
        assert recovery_body["metadata"]["ownerReferences"] == []
        assert recovery_body["stringData"] == {"DB_PASSWORD": "supersecret"}
        assert core_api.patch_namespaced_secret.call_args_list[1].kwargs["name"] == expected_secret_name

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


class TestGCPTaskRunnerSensitiveEnvLifecycle(_SensitiveEnvTestBase):
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
