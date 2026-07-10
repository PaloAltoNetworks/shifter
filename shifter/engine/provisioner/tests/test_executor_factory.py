"""Tests for provider-routed guest executor selection."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from executors.factory import (
    build_guest_execution_context,
    get_setup_document_name,
    get_ssh_username,
)


class TestGuestExecutorFactoryHelpers:
    """Pure helper tests."""

    def test_get_setup_document_name_maps_windows_to_powershell(self):
        assert get_setup_document_name("windows") == "AWS-RunPowerShellScript"

    def test_get_setup_document_name_maps_linux_to_shell(self):
        assert get_setup_document_name("ubuntu") == "AWS-RunShellScript"

    def test_get_ssh_username_maps_known_os_types(self):
        assert get_ssh_username("kali", "attacker") == "kali"
        assert get_ssh_username("amazon-linux", "victim") == "ec2-user"
        assert get_ssh_username("windows", "victim") == "Administrator"
        assert get_ssh_username("ubuntu", "dc") == "Administrator"


class TestBuildGuestExecutionContext:
    """Provider-aware setup transport selection."""

    def test_aws_uses_ssm_instance_target(self, mocker, monkeypatch):
        monkeypatch.delenv("CLOUD_PROVIDER", raising=False)
        mock_executor_cls = mocker.patch("executors.factory.SSMExecutor")
        mock_executor = mock_executor_cls.return_value

        context = build_guest_execution_context({"instance_id": "i-1234567890", "os": "ubuntu", "role": "victim"})

        assert context.executor is mock_executor
        assert context.target == "i-1234567890"
        assert context.document_name == "AWS-RunShellScript"
        assert context.transport_name == "ssm"
        mock_executor_cls.assert_called_once_with()
        context.close()
        mock_executor.close.assert_called_once_with()

    def _gcp_instance(self, **overrides):
        data = {
            "instance_id": "range-vm-1",
            "private_ip": "10.200.2.10",
            "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
            "gdc_namespace": "range-7",
            "gdc_nad_name": "range-7-core",
            "os": "windows",
            "role": "victim",
        }
        data.update(overrides)
        return data

    def _patch_gcp_deps(self, mocker, monkeypatch, key_material="PRIVATE KEY"):
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        monkeypatch.setenv("GDC_SETUP_RUNNER_IMAGE", "registry.example/runner:latest")
        secret_reader = mocker.Mock(return_value=key_material)
        # The range-cluster Kubernetes client factory is injected, so the real
        # RangePodSSHExecutor is built (and asserted via observable state) without
        # reaching a live cluster -- no first-party internal patching needed.
        kube_builder = mocker.Mock(return_value=("CORE_API", "CLIENT_MODULE", RuntimeError))
        return secret_reader, kube_builder

    def test_gcp_uses_in_range_pod_transport(self, mocker, monkeypatch):
        from executors.range_pod_ssh_executor import RangePodSSHExecutor

        secret_reader, kube_builder = self._patch_gcp_deps(mocker, monkeypatch)

        context = build_guest_execution_context(
            self._gcp_instance(),
            kube_clients_builder=kube_builder,
            secret_reader=secret_reader,
        )

        assert isinstance(context.executor, RangePodSSHExecutor)
        assert context.target == "10.200.2.10"
        assert context.document_name == "AWS-RunPowerShellScript"
        assert context.transport_name == "range-pod-ssh"
        secret_reader.assert_called_once_with("projects/test/secrets/range-vm-1-key")
        kube_builder.assert_called_once_with()

        executor = context.executor
        assert executor._core_api == "CORE_API"
        assert executor._client_module == "CLIENT_MODULE"
        assert executor._api_exception is RuntimeError
        assert executor._namespace == "range-7"
        assert executor._network_name == "range-7-core"
        assert executor._runner_image == "registry.example/runner:latest"
        assert executor._private_key_material == "PRIVATE KEY"
        assert executor._username == "Administrator"
        # Windows guest: no host key, so the known_hosts seam stays inert.
        assert executor._known_hosts_path is None

    def test_gcp_gce_output_uses_direct_ssh_transport(self, mocker, monkeypatch):
        from executors.guest_ssh_executor import GuestSSHExecutor

        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        secret_reader = mocker.Mock(return_value="PRIVATE KEY")

        context = build_guest_execution_context(
            {
                "asset_type": "gce_vm",
                "private_ip": "10.50.2.2",
                "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
                "ssh_username": "kali",
                "os": "kali",
                "role": "attacker",
            },
            secret_reader=secret_reader,
        )

        assert isinstance(context.executor, GuestSSHExecutor)
        assert context.target == "10.50.2.2"
        assert context.document_name == "AWS-RunShellScript"
        assert context.transport_name == "ssh"
        assert context.executor._username == "kali"
        assert context.executor._port == 22
        assert context.executor._known_hosts_path is None
        secret_reader.assert_called_once_with("projects/test/secrets/range-vm-1-key")
        context.close()

    def test_gce_output_threads_host_mgmt_ssh_port(self, mocker, monkeypatch):
        """A Docker-host guest drives its host sshd on the management port."""
        from executors.guest_ssh_executor import GuestSSHExecutor

        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        secret_reader = mocker.Mock(return_value="PRIVATE KEY")

        context = build_guest_execution_context(
            {
                "asset_type": "gce_vm",
                "private_ip": "10.50.2.3",
                "ssh_key_secret_arn": "projects/test/secrets/polaris-host-key",
                # Participant user is "kali" (container); the provisioner drives
                # the host sshd as "ubuntu" on the management port.
                "ssh_username": "kali",
                "gcp_host_ssh_username": "ubuntu",
                "gcp_host_ssh_port": 2222,
                "os": "kali",
                "role": "attacker",
            },
            secret_reader=secret_reader,
        )

        assert isinstance(context.executor, GuestSSHExecutor)
        assert context.executor._username == "ubuntu"
        assert context.executor._port == 2222
        context.close()

    @pytest.mark.parametrize("metadata", [{"gcp_instance_name": "range-vm-1"}, {"gcp_zone": "us-central1-b"}])
    def test_gcp_gce_output_detects_compute_metadata_without_asset_type(self, metadata, mocker, monkeypatch):
        from executors.guest_ssh_executor import GuestSSHExecutor

        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        secret_reader = mocker.Mock(return_value="PRIVATE KEY")
        instance_data = {
            "private_ip": "10.50.2.3",
            "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
            "os": "ubuntu",
            "role": "victim",
            **metadata,
        }

        context = build_guest_execution_context(instance_data, secret_reader=secret_reader)

        assert isinstance(context.executor, GuestSSHExecutor)
        assert context.target == "10.50.2.3"
        assert context.transport_name == "ssh"
        assert context.executor._username == "ubuntu"
        secret_reader.assert_called_once_with("projects/test/secrets/range-vm-1-key")
        context.close()

    def test_gcp_gce_output_uses_default_secret_reader(self, mocker, monkeypatch):
        from executors.guest_ssh_executor import GuestSSHExecutor

        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        secrets = mocker.Mock()
        secrets.get_secret.return_value = "PRIVATE KEY"
        mocker.patch("executors.factory.get_secrets_store", return_value=secrets)

        context = build_guest_execution_context(
            {
                "asset_type": "gce_vm",
                "private_ip": "10.50.2.3",
                "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
                "os": "ubuntu",
                "role": "victim",
            }
        )

        assert isinstance(context.executor, GuestSSHExecutor)
        assert context.transport_name == "ssh"
        secrets.get_secret.assert_called_once_with("projects/test/secrets/range-vm-1-key")
        context.close()

    def test_gcp_uses_default_range_kube_client_builder(self, mocker, monkeypatch):
        from executors.range_pod_ssh_executor import RangePodSSHExecutor

        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        monkeypatch.setenv("GDC_ACCESS_SECRET_ID", "projects/test/secrets/gdc-access")
        monkeypatch.setenv("GDC_SETUP_RUNNER_IMAGE", "registry.example/runner:latest")
        secrets = mocker.Mock()
        secrets.get_secret.return_value = "PRIVATE KEY"
        mocker.patch("executors.factory.get_secrets_store", return_value=secrets)
        secretmanager_module = ModuleType("google.cloud.secretmanager")
        secretmanager_client = mocker.Mock()
        secretmanager_client.access_secret_version.return_value = SimpleNamespace(
            payload=SimpleNamespace(
                data=b"""
        {
          "cluster_id": "cluster1",
          "region": "us-central1",
          "vxlan_cidr": "10.200.0.0/24",
          "kubeconfig": "apiVersion: v1\\nclusters: []\\ncontexts: []\\ncurrent-context: ''\\nusers: []\\n"
        }
        """
            )
        )
        secretmanager_module.SecretManagerServiceClient = mocker.Mock(return_value=secretmanager_client)
        client_module = ModuleType("kubernetes.client")
        client_module.CoreV1Api = mocker.Mock(return_value="CORE_API")
        client_module.Configuration = mocker.Mock(return_value="CONFIG")
        client_module.ApiClient = mocker.Mock(return_value="API_CLIENT")
        exceptions_module = ModuleType("kubernetes.client.exceptions")
        exceptions_module.ApiException = RuntimeError
        config_module = ModuleType("kubernetes.config")
        loader = mocker.Mock()
        config_module.kube_config = SimpleNamespace(KubeConfigLoader=mocker.Mock(return_value=loader))
        kubernetes_module = ModuleType("kubernetes")
        kubernetes_module.client = client_module
        kubernetes_module.config = config_module
        monkeypatch.setitem(sys.modules, "kubernetes", kubernetes_module)
        monkeypatch.setitem(sys.modules, "kubernetes.client", client_module)
        monkeypatch.setitem(sys.modules, "kubernetes.client.exceptions", exceptions_module)
        monkeypatch.setitem(sys.modules, "kubernetes.config", config_module)
        monkeypatch.setitem(sys.modules, "google", ModuleType("google"))
        monkeypatch.setitem(sys.modules, "google.cloud", ModuleType("google.cloud"))
        monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", secretmanager_module)

        context = build_guest_execution_context(self._gcp_instance(os="ubuntu"))

        assert isinstance(context.executor, RangePodSSHExecutor)
        assert context.executor._core_api == "CORE_API"
        assert context.executor._client_module is client_module
        assert context.executor._api_exception is RuntimeError
        client_module.CoreV1Api.assert_called_once_with("API_CLIENT")
        client_module.ApiClient.assert_called_once_with(configuration="CONFIG")
        loader.load_and_set.assert_called_once_with("CONFIG")
        secretmanager_client.access_secret_version.assert_called_once_with(
            request={"name": "projects/test/secrets/gdc-access/versions/latest"}
        )
        secrets.get_secret.assert_called_once_with("projects/test/secrets/range-vm-1-key")

    def test_gcp_forwards_guest_host_key_for_known_hosts(self, mocker, monkeypatch):
        # The Ed25519 host key the provisioner installed via cloud-init flows to
        # the executor so it can seed the runner's known_hosts (D31).
        secret_reader, kube_builder = self._patch_gcp_deps(mocker, monkeypatch)

        context = build_guest_execution_context(
            self._gcp_instance(gdc_host_public_key="ssh-ed25519 AAAAHOSTKEY guest", os="ubuntu"),
            kube_clients_builder=kube_builder,
            secret_reader=secret_reader,
        )

        executor = context.executor
        assert executor._known_hosts_path is not None
        assert executor._known_hosts_content == "10.200.2.10 ssh-ed25519 AAAAHOSTKEY guest\n"

    def test_gcp_prefers_explicit_ssh_username_from_instance_output(self, mocker, monkeypatch):
        secret_reader, kube_builder = self._patch_gcp_deps(mocker, monkeypatch)

        context = build_guest_execution_context(
            self._gcp_instance(ssh_username="custom-user", os="ubuntu"),
            kube_clients_builder=kube_builder,
            secret_reader=secret_reader,
        )

        assert context.executor._username == "custom-user"

    def test_gcp_runner_image_falls_back_to_engine_task_image(self, mocker, monkeypatch):
        secret_reader, kube_builder = self._patch_gcp_deps(mocker, monkeypatch)
        monkeypatch.delenv("GDC_SETUP_RUNNER_IMAGE", raising=False)
        monkeypatch.setenv("ENGINE_TASK_IMAGE", "registry.example/provisioner:sha")

        context = build_guest_execution_context(
            self._gcp_instance(),
            kube_clients_builder=kube_builder,
            secret_reader=secret_reader,
        )

        assert context.executor._runner_image == "registry.example/provisioner:sha"

    def test_gcp_requires_private_ip(self, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")

        try:
            build_guest_execution_context(
                {
                    "instance_id": "range-vm-1",
                    "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
                    "gdc_namespace": "range-7",
                    "gdc_nad_name": "range-7-core",
                    "os": "ubuntu",
                    "role": "victim",
                }
            )
        except ValueError as exc:
            assert "private_ip" in str(exc)
        else:
            raise AssertionError("Expected ValueError for missing private_ip")

    def test_gcp_requires_gdc_network_fields(self, mocker, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        monkeypatch.setenv("GDC_SETUP_RUNNER_IMAGE", "registry.example/runner:latest")
        secret_reader = mocker.Mock(return_value="PRIVATE KEY")

        with pytest.raises(ValueError, match="gdc_namespace"):
            build_guest_execution_context(
                {
                    "private_ip": "10.200.2.10",
                    "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
                    "os": "ubuntu",
                    "role": "victim",
                },
                secret_reader=secret_reader,
            )

    def test_gcp_requires_ssh_key_secret(self, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        with pytest.raises(ValueError, match="ssh_key_secret_arn"):
            build_guest_execution_context(
                {
                    "private_ip": "10.200.2.10",
                    "gdc_namespace": "range-7",
                    "gdc_nad_name": "range-7-core",
                    "os": "ubuntu",
                    "role": "victim",
                }
            )

    def test_gcp_requires_runner_image_env(self, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        monkeypatch.delenv("GDC_SETUP_RUNNER_IMAGE", raising=False)
        monkeypatch.delenv("ENGINE_TASK_IMAGE", raising=False)
        with pytest.raises(ValueError, match="GDC_SETUP_RUNNER_IMAGE"):
            build_guest_execution_context(
                {
                    "private_ip": "10.200.2.10",
                    "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
                    "gdc_namespace": "range-7",
                    "gdc_nad_name": "range-7-core",
                    "os": "ubuntu",
                    "role": "victim",
                }
            )

    def test_unknown_provider_currently_falls_back_to_ssm(self, mocker, monkeypatch):
        from executors.ssm_executor import SSMExecutor

        monkeypatch.setenv("CLOUD_PROVIDER", "gcq")
        session = mocker.Mock()
        session.client.side_effect = lambda service: f"{service}-client"
        mocker.patch("boto3.Session", return_value=session)

        context = build_guest_execution_context({"instance_id": "i-123", "os": "ubuntu", "role": "victim"})

        assert isinstance(context.executor, SSMExecutor)
        assert context.target == "i-123"
        assert context.transport_name == "ssm"
        assert context.executor._ssm_client == "ssm-client"
        assert context.executor._ec2_client == "ec2-client"


class TestBuildRangeKubeClients:
    """The default range-cluster Kubernetes client factory."""

    def test_requires_gdc_access_config(self, monkeypatch):
        # With no GDC_ACCESS_SECRET_ID configured, load_gdc_network_access_config
        # returns None and the builder refuses to proceed -- exercised through
        # the env-var boundary so no first-party internal is patched (ADR-019).
        monkeypatch.delenv("GDC_ACCESS_SECRET_ID", raising=False)
        from executors.factory import _build_range_kube_clients

        with pytest.raises(RuntimeError, match="GDC range access config"):
            _build_range_kube_clients()
