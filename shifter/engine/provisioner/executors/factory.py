"""Provider-routed guest setup executor selection."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cloud import get_secrets_store
from executors.base import Executor
from executors.ssm_executor import SSMExecutor

_LINUX_DOCUMENT = "AWS-RunShellScript"
_WINDOWS_DOCUMENT = "AWS-RunPowerShellScript"
_WINDOWS_OS_TYPES = {"windows"}
_SSH_USER_BY_OS = {
    "amazon-linux": "ec2-user",
    "kali": "kali",
    "ubuntu": "ubuntu",
    "windows": "Administrator",
}


def _get_provider() -> str:
    return os.environ.get("CLOUD_PROVIDER", "aws")


def get_setup_document_name(os_type: str) -> str:
    """Return the document/shell family for the guest OS."""
    return _WINDOWS_DOCUMENT if os_type in _WINDOWS_OS_TYPES else _LINUX_DOCUMENT


def get_ssh_username(os_type: str, role: str) -> str:
    """Resolve the SSH username for the guest OS."""
    if role == "dc":
        return "Administrator"
    return _SSH_USER_BY_OS.get(os_type, "ubuntu")


@dataclass
class GuestExecutionContext:
    """Resolved remote execution context for guest setup."""

    executor: Executor
    target: str
    document_name: str
    transport_name: str

    def wait_for_ready(self, timeout_seconds: int) -> bool:
        return self.executor.wait_for_ready(
            self.target,
            timeout_seconds=timeout_seconds,
            document_name=self.document_name,
        )

    def close(self) -> None:
        close = getattr(self.executor, "close", None)
        if callable(close):
            close()


def build_guest_execution_context(
    instance_data: dict[str, Any],
    *,
    provider: str | None = None,
    os_type: str | None = None,
    role: str | None = None,
    kube_clients_builder: Callable[[], tuple[Any, Any, type]] | None = None,
    secret_reader: Callable[[str], str] | None = None,
) -> GuestExecutionContext:
    """Resolve the transport, target, and shell family for guest setup.

    ``kube_clients_builder`` and ``secret_reader`` inject cloud boundaries for
    tests while production uses the live Kubernetes and Secret Manager clients.
    """
    resolved_provider = provider or _get_provider()
    resolved_os_type = os_type or instance_data.get("os", "")
    resolved_role = role or instance_data.get("role", "")
    document_name = get_setup_document_name(resolved_os_type)

    if resolved_provider == "gcp":
        if _is_gce_instance_output(instance_data):
            return _build_gce_execution_context(
                instance_data,
                resolved_os_type,
                resolved_role,
                document_name,
                secret_reader=secret_reader,
            )
        return _build_gcp_execution_context(
            instance_data,
            resolved_os_type,
            resolved_role,
            document_name,
            kube_clients_builder=kube_clients_builder or _build_range_kube_clients,
            secret_reader=secret_reader,
        )

    target = instance_data.get("instance_id", "")
    if not target:
        raise ValueError("AWS guest execution requires instance_id in instance output")

    return GuestExecutionContext(
        executor=SSMExecutor(),
        target=target,
        document_name=document_name,
        transport_name="ssm",
    )


def _is_gce_instance_output(instance_data: dict[str, Any]) -> bool:
    """Return True for Compute Engine range-cell guest output records."""
    return (
        instance_data.get("asset_type") == "gce_vm"
        or bool(instance_data.get("gcp_instance_name"))
        or bool(instance_data.get("gcp_zone"))
    )


def _build_gce_execution_context(
    instance_data: dict[str, Any],
    os_type: str,
    role: str,
    document_name: str,
    *,
    secret_reader: Callable[[str], str] | None,
) -> GuestExecutionContext:
    """Build direct private-SSH execution for a GCE range-cell guest."""
    from executors.guest_ssh_executor import GuestSSHExecutor

    target = instance_data.get("private_ip", "")
    if not target:
        raise ValueError("GCE guest execution requires private_ip in instance output")
    secret_id = instance_data.get("ssh_key_secret_arn", "")
    if not secret_id:
        raise ValueError("GCE guest execution requires ssh_key_secret_arn in instance output")
    private_key = (secret_reader or get_secrets_store().get_secret)(secret_id)
    # Provisioner guest setup drives the host sshd, which for Docker-host guests
    # (e.g. the Polaris range host) is a different user + port than the
    # participant-facing service on :22. Prefer the host access fields, falling
    # back to the participant username for native single-service guests.
    username = (
        instance_data.get("gcp_host_ssh_username")
        or instance_data.get("ssh_username")
        or instance_data.get("ssh_user")
        or get_ssh_username(os_type, role)
    )
    executor = GuestSSHExecutor(
        private_key=private_key,
        username=username,
        port=int(instance_data.get("gcp_host_ssh_port") or GuestSSHExecutor.DEFAULT_SSH_PORT),
        host_public_key=instance_data.get("gcp_host_public_key", ""),
        known_hosts_host=target,
    )
    return GuestExecutionContext(
        executor=executor,
        target=target,
        document_name=document_name,
        transport_name="ssh",
    )


def _build_range_kube_clients() -> tuple[Any, Any, type]:
    """Build (CoreV1Api, kubernetes client module, ApiException) for the range cluster."""
    from config import load_gdc_network_access_config
    from gdc_range_networks import _build_kube_api_client, _import_kubernetes_modules

    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range access config (GDC_ACCESS_SECRET_ID) is required for guest setup")
    _unused, client_module, _config, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    core_api = client_module.CoreV1Api(api_client)
    return core_api, client_module, api_exception


def _require_instance_value(instance_data: dict[str, Any], key: str, message: str) -> str:
    """Return a required string value from provisioner instance output."""
    value = str(instance_data.get(key, "") or "")
    if not value:
        raise ValueError(message)
    return value


def _resolve_gdc_network_name(instance_data: dict[str, Any]) -> str:
    """Return the GDC network attachment name from provisioner output."""
    return str(instance_data.get("gdc_nad_name", "") or instance_data.get("gdc_network_name", "") or "")


def _resolve_gdc_setup_runner_image() -> str:
    """Return the runner image used for in-cluster guest setup."""
    runner_image = os.environ.get("GDC_SETUP_RUNNER_IMAGE", "") or os.environ.get("ENGINE_TASK_IMAGE", "")
    if not runner_image:
        raise ValueError("GDC guest setup requires GDC_SETUP_RUNNER_IMAGE (or ENGINE_TASK_IMAGE) to be set")
    return runner_image


def _build_gcp_execution_context(
    instance_data: dict[str, Any],
    os_type: str,
    role: str,
    document_name: str,
    *,
    kube_clients_builder: Callable[[], tuple[Any, Any, type]],
    secret_reader: Callable[[str], str] | None,
) -> GuestExecutionContext:
    """Build the in-range-cluster guest setup transport for a GDC VM Runtime guest.

    GDC range VMs live on an isolated L2 segment unreachable from the platform
    plane, so guest setup runs from a pod inside the range cluster attached to
    the range NAD (see RangePodSSHExecutor).
    """
    from executors.range_pod_ssh_executor import RangePodSSHExecutor

    target = _require_instance_value(
        instance_data, "private_ip", "GCP guest execution requires private_ip in instance output"
    )
    secret_id = _require_instance_value(
        instance_data, "ssh_key_secret_arn", "GCP guest execution requires ssh_key_secret_arn in instance output"
    )
    namespace = _require_instance_value(
        instance_data, "gdc_namespace", "GCP guest execution requires gdc_namespace in instance output"
    )
    network_name = _resolve_gdc_network_name(instance_data)
    if not namespace or not network_name:
        raise ValueError("GCP guest execution requires gdc_namespace and gdc_nad_name in instance output")

    runner_image = _resolve_gdc_setup_runner_image()
    private_key = (secret_reader or get_secrets_store().get_secret)(secret_id)
    username = instance_data.get("ssh_username") or instance_data.get("ssh_user") or get_ssh_username(os_type, role)
    # Host key the provisioner installed on the guest via cloud-init (Linux
    # only); seeds the runner's known_hosts so StrictHostKeyChecking=yes
    # validates against a key obtained over a trusted side channel. Empty for
    # Windows guests (cloudbase-init has no ssh_keys module), which leaves the
    # known_hosts seam inert.
    host_public_key = instance_data.get("gdc_host_public_key", "")
    core_api, client_module, api_exception = kube_clients_builder()
    executor = RangePodSSHExecutor(
        core_api=core_api,
        client_module=client_module,
        api_exception=api_exception,
        namespace=namespace,
        network_name=network_name,
        runner_image=runner_image,
        private_key=private_key,
        username=username,
        host_public_key=host_public_key,
        known_hosts_host=target,
    )
    return GuestExecutionContext(
        executor=executor,
        target=target,
        document_name=document_name,
        transport_name="range-pod-ssh",
    )
