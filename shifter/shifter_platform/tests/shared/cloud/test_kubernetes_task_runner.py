"""Tests for the provider-neutral Kubernetes task runner (#1824).

These exercise ``KubernetesTaskRunner`` directly with an injected
``KubernetesTaskProfile`` — no GCP adapter — to prove the extracted core is
genuinely provider-neutral: the injected profile drives the runner label,
service account, and which container gets provisioner hardening, and the neutral
package pulls in no GCP module and reads no Django settings.

The GCP adapter's behavior parity is covered by ``test_gcp_task_runner*.py``; here
we assert the core works standalone with arbitrary provider wiring.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import shared.cloud.kubernetes as k8s_pkg
from shared.cloud.exceptions import CloudTaskError
from shared.cloud.kubernetes import (
    KubernetesTaskProfile,
    KubernetesTaskRunner,
    ProvisionerHardeningProfile,
)
from shared.cloud.types import TaskInterruptDisposition
from tests.shared.cloud.test_gcp_task_runner import _ApiException, _make_fake_k8s_client, _observed_job

_HARDENED_CONTAINER = "neutral-provisioner"
_WRITABLE_MOUNTS = (
    ("workspace", "/var/run/workspace", "Memory", "128Mi"),
    ("tmp", "/tmp", None, None),  # noqa: S108 — Kubernetes mount path, not a tempfile API call
)


def _profile(*, service_account: str = "runtime-sa", label: str = "neutral", hardened: bool = True):
    return KubernetesTaskProfile(
        runner_label_value=label,
        service_account_name=service_account,
        image_pull_policy="Always",
        backoff_limit=2,
        ttl_seconds_after_finished=1200,
        hardening=(
            ProvisionerHardeningProfile(
                container_name=_HARDENED_CONTAINER,
                run_as_uid=1234,
                run_as_gid=1234,
                writable_mounts=_WRITABLE_MOUNTS,
            )
            if hardened
            else None
        ),
    )


def _runner(profile, batch_api: MagicMock, core_api: MagicMock) -> KubernetesTaskRunner:
    client = _make_fake_k8s_client()
    client.V1DeleteOptions = lambda **kwargs: SimpleNamespace(**kwargs)
    runner = KubernetesTaskRunner(profile)
    runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))
    return runner


class TestInjectedProfileDrivesJobShape:
    """The Job manifest reflects the injected profile, not any GCP constant."""

    def test_private_task_profile_binds_pull_auth_resources_and_deadline(self):
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="bounded-task"))
        core_api = MagicMock()
        client = _make_fake_k8s_client()
        client.V1ResourceRequirements = lambda **kwargs: SimpleNamespace(**kwargs)
        client.V1LocalObjectReference = lambda **kwargs: SimpleNamespace(**kwargs)
        profile = replace(
            _profile(service_account="private-adapter"),
            image_pull_secrets=("private-registry",),
            resource_requests={"cpu": "500m", "memory": "512Mi"},
            resource_limits={"cpu": "1", "memory": "1Gi", "ephemeral-storage": "2Gi"},
            active_deadline_seconds=1800,
        )
        runner = KubernetesTaskRunner(profile)
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))
        runner.run_task(
            task_definition="registry.example/private@sha256:" + "a" * 64,
            cluster="private-tasks",
            command=["00000000-0000-0000-0000-000000000001"],
            container_name=_HARDENED_CONTAINER,
        )
        job = batch_api.create_namespaced_job.call_args.kwargs["body"]
        pod = job.spec.template.spec
        assert [ref.name for ref in pod.image_pull_secrets] == ["private-registry"]
        assert pod.containers[0].resources.requests == profile.resource_requests
        assert pod.containers[0].resources.limits == profile.resource_limits
        assert job.spec.active_deadline_seconds == 1800
        assert pod.service_account_name == "private-adapter"
        assert pod.containers[0].security_context.read_only_root_filesystem

    def test_profile_values_applied_and_named_container_hardened(self) -> None:
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="job-neutral"))
        core_api = MagicMock()
        runner = _runner(_profile(service_account="runtime-sa", label="neutral"), batch_api, core_api)

        task_id = runner.run_task(
            task_definition="registry.example.com/provisioner:latest",
            cluster="tasks-ns",
            command=["range", "provision"],
            container_name=_HARDENED_CONTAINER,
        )

        assert task_id == "tasks-ns/job-neutral"
        job = batch_api.create_namespaced_job.call_args.kwargs["body"]
        pod_spec = job.spec.template.spec
        # Injected provider wiring, not a hardcoded "gcp" tag or GCP settings.
        assert job.metadata.labels["shifter.dev/task-runner"] == "neutral"
        assert pod_spec.service_account_name == "runtime-sa"
        assert job.spec.backoff_limit == 2
        assert job.spec.ttl_seconds_after_finished == 1200
        assert pod_spec.containers[0].image_pull_policy == "Always"
        # Profile's named container receives the #1103 hardening from its mounts/uid.
        container = pod_spec.containers[0]
        assert container.security_context.run_as_user == 1234
        assert container.security_context.read_only_root_filesystem is True
        assert pod_spec.automount_service_account_token is False
        assert {v.name for v in pod_spec.volumes} == {"workspace", "tmp"}
        assert {m.name: m.mount_path for m in container.volume_mounts} == {
            "workspace": "/var/run/workspace",
            "tmp": "/tmp",  # noqa: S108 — Kubernetes mount path assertion
        }

    def test_container_outside_profile_is_not_hardened(self) -> None:
        """Hardening is gated by the profile's container_name, so a different
        container launched through the same runner keeps the minimal contract."""
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="job-plain"))
        core_api = MagicMock()
        runner = _runner(_profile(), batch_api, core_api)

        runner.run_task(
            task_definition="registry.example.com/other:latest",
            cluster="tasks-ns",
            command=["run"],
            container_name="some-other-task",
        )

        pod_spec = batch_api.create_namespaced_job.call_args.kwargs["body"].spec.template.spec
        assert not hasattr(pod_spec.containers[0], "security_context")
        assert not hasattr(pod_spec, "volumes")
        assert not hasattr(pod_spec, "security_context")

    def test_no_hardening_profile_means_no_hardening_anywhere(self) -> None:
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="job-x"))
        core_api = MagicMock()
        runner = _runner(_profile(hardened=False), batch_api, core_api)

        runner.run_task(
            task_definition="img:latest",
            cluster="ns",
            command=["go"],
            container_name=_HARDENED_CONTAINER,
        )

        pod_spec = batch_api.create_namespaced_job.call_args.kwargs["body"].spec.template.spec
        assert not hasattr(pod_spec.containers[0], "security_context")

    def test_requires_namespace(self) -> None:
        runner = KubernetesTaskRunner(_profile())
        with pytest.raises(CloudTaskError, match="namespace"):
            runner.run_task(
                task_definition="img:latest",
                cluster="",
                command=["go"],
                container_name=_HARDENED_CONTAINER,
            )

    def test_callable_profile_is_resolved_per_call(self) -> None:
        """A provider adapter injects a factory so runtime settings are read at
        call time; the runner must resolve it on each run_task."""
        calls = {"n": 0}

        def factory() -> KubernetesTaskProfile:
            calls["n"] += 1
            return _profile(service_account=f"sa-{calls['n']}")

        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="j"))
        core_api = MagicMock()
        runner = KubernetesTaskRunner(factory)
        runner._load_kubernetes_api = MagicMock(
            return_value=(batch_api, core_api, _make_fake_k8s_client(), _ApiException)
        )

        runner.run_task(task_definition="i:1", cluster="ns", command=["c"], container_name="t")
        runner.run_task(task_definition="i:1", cluster="ns", command=["c"], container_name="t")
        sas = [
            c.kwargs["body"].spec.template.spec.service_account_name
            for c in batch_api.create_namespaced_job.call_args_list
        ]
        assert sas == ["sa-1", "sa-2"]


class TestSensitiveEnvProjection:
    """Sensitive env goes through a per-Job Secret + secretKeyRef, label from profile."""

    def test_sensitive_env_routes_through_secret_with_profile_label(self) -> None:
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="job-s", uid="uid-s")
        )
        core_api = MagicMock()
        runner = _runner(_profile(label="neutral"), batch_api, core_api)

        runner.run_task(
            task_definition="img:latest",
            cluster="ns",
            command=["run"],
            container_name=_HARDENED_CONTAINER,
            env_overrides={"DB_PASSWORD": "supersecret", "DB_HOST": "db.example.com"},
        )

        secret_body = core_api.create_namespaced_secret.call_args.kwargs["body"]
        assert set(secret_body.string_data.keys()) == {"DB_PASSWORD"}
        assert secret_body.metadata.labels["shifter.dev/task-runner"] == "neutral"
        env_by_name = {
            e.name: e
            for e in batch_api.create_namespaced_job.call_args.kwargs["body"].spec.template.spec.containers[0].env
        }
        assert getattr(env_by_name["DB_PASSWORD"], "value", None) is None
        assert env_by_name["DB_PASSWORD"].value_from.secret_key_ref.name == secret_body.metadata.name
        assert env_by_name["DB_HOST"].value == "db.example.com"

    def test_secret_owner_referenced_to_job(self) -> None:
        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="job-owner", uid="uid-owner")
        )
        core_api = MagicMock()
        runner = _runner(_profile(), batch_api, core_api)

        runner.run_task(
            task_definition="img:latest",
            cluster="ns",
            command=["run"],
            container_name=_HARDENED_CONTAINER,
            env_overrides={"DB_PASSWORD": "p"},
        )

        owner = core_api.patch_namespaced_secret.call_args.kwargs["body"]["metadata"]["ownerReferences"][0]
        assert owner["kind"] == "Job"
        assert owner["name"] == "job-owner"
        assert owner["uid"] == "uid-owner"


class TestStatusAndInterrupt:
    def test_status_maps_running(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.return_value = SimpleNamespace(
            status=SimpleNamespace(active=1, failed=0, succeeded=0, start_time="t", completion_time=None, conditions=[])
        )
        runner = _runner(_profile(), batch_api, MagicMock())
        result = runner.get_task_status("ns", "ns/job-1")
        assert result is not None
        assert result["status"] == "RUNNING"
        assert result["task_id"] == "ns/job-1"

    def test_interrupt_matching_intent_foreground_deletes(self) -> None:
        task_identity = "11111111-1111-1111-1111-111111111111"
        observed = _observed_job(task_identity=task_identity, image="img:1", command=["c"], service_account_name="sa")
        # _observed_job builds a "pulumi-provisioner"-named job; align identity fields.
        job_name = observed.metadata.name
        batch_api = MagicMock()
        batch_api.read_namespaced_job.return_value = observed
        core_api = MagicMock()
        core_api.list_namespaced_pod.return_value = SimpleNamespace(items=[])
        runner = _runner(_profile(), batch_api, core_api)

        disposition = runner.interrupt_task(
            "ns",
            f"ns/{job_name}",
            {
                "task_identity": task_identity,
                "image": "img:1",
                "command": ["c"],
                "container_name": "pulumi-provisioner",
                "service_account_name": "sa",
            },
        )

        assert disposition == TaskInterruptDisposition.TERMINAL_ABSENT
        assert batch_api.delete_namespaced_job.call_args.kwargs["body"].propagation_policy == "Foreground"


class TestNeutralPackageHasNoProviderCoupling:
    """Structural gate for the #1824 acceptance criterion: the shared runner has
    no GCP imports and reads no Django settings — provider wiring is injected."""

    def _package_modules(self) -> list[Path]:
        pkg_dir = Path(k8s_pkg.__file__).resolve().parent
        return sorted(pkg_dir.glob("*.py"))

    def test_no_gcp_or_aws_or_django_imports_in_neutral_package(self) -> None:
        offenders: list[str] = []
        for module_path in self._package_modules():
            tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    if (
                        name == "django"
                        or name.startswith("django.")
                        or name.startswith("shared.cloud.gcp")
                        or name.startswith("shared.cloud.aws")
                    ):
                        offenders.append(f"{module_path.name}: {name}")
        assert not offenders, f"neutral kubernetes package must not couple to provider/settings: {offenders}"
