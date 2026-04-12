"""Tests for provider-routed guest executor selection."""

from __future__ import annotations

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

    def test_gcp_uses_private_ip_and_secret_manager_key(self, mocker, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")

        mock_store = mocker.Mock()
        mock_store.get_secret.return_value = "PRIVATE KEY"
        mocker.patch("executors.factory.get_secrets_store", return_value=mock_store)
        mock_executor_cls = mocker.patch("executors.factory.GuestSSHExecutor")
        mock_executor = mock_executor_cls.return_value

        context = build_guest_execution_context(
            {
                "instance_id": "range-vm-1",
                "private_ip": "10.50.1.10",
                "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
                "os": "windows",
                "role": "victim",
            }
        )

        assert context.executor is mock_executor
        assert context.target == "10.50.1.10"
        assert context.document_name == "AWS-RunPowerShellScript"
        assert context.transport_name == "ssh"
        mock_store.get_secret.assert_called_once_with("projects/test/secrets/range-vm-1-key")
        mock_executor_cls.assert_called_once_with(private_key="PRIVATE KEY", username="Administrator")

        context.close()
        mock_executor.close.assert_called_once_with()

    def test_gcp_prefers_explicit_ssh_username_from_instance_output(self, mocker, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")

        mock_store = mocker.Mock()
        mock_store.get_secret.return_value = "PRIVATE KEY"
        mocker.patch("executors.factory.get_secrets_store", return_value=mock_store)
        mock_executor_cls = mocker.patch("executors.factory.GuestSSHExecutor")

        build_guest_execution_context(
            {
                "instance_id": "range-vm-1",
                "private_ip": "10.50.1.10",
                "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
                "ssh_username": "custom-user",
                "os": "ubuntu",
                "role": "victim",
            }
        )

        mock_executor_cls.assert_called_once_with(private_key="PRIVATE KEY", username="custom-user")

    def test_gcp_requires_private_ip(self, monkeypatch):
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")

        try:
            build_guest_execution_context(
                {
                    "instance_id": "range-vm-1",
                    "ssh_key_secret_arn": "projects/test/secrets/range-vm-1-key",
                    "os": "ubuntu",
                    "role": "victim",
                }
            )
        except ValueError as exc:
            assert "private_ip" in str(exc)
        else:
            raise AssertionError("Expected ValueError for missing private_ip")
