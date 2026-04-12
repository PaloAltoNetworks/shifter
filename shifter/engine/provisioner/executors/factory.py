"""Provider-routed guest setup executor selection."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from cloud import get_secrets_store
from executors.base import Executor
from executors.guest_ssh_executor import GuestSSHExecutor
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
) -> GuestExecutionContext:
    """Resolve the transport, target, and shell family for guest setup."""
    resolved_provider = provider or _get_provider()
    resolved_os_type = os_type or instance_data.get("os", "")
    resolved_role = role or instance_data.get("role", "")
    document_name = get_setup_document_name(resolved_os_type)

    if resolved_provider == "gcp":
        target = instance_data.get("private_ip", "")
        if not target:
            raise ValueError("GCP guest execution requires private_ip in instance output")

        secret_id = instance_data.get("ssh_key_secret_arn", "")
        if not secret_id:
            raise ValueError("GCP guest execution requires ssh_key_secret_arn in instance output")

        private_key = get_secrets_store().get_secret(secret_id)
        username = (
            instance_data.get("ssh_username")
            or instance_data.get("ssh_user")
            or get_ssh_username(
                resolved_os_type,
                resolved_role,
            )
        )
        executor = GuestSSHExecutor(
            private_key=private_key,
            username=username,
        )
        return GuestExecutionContext(
            executor=executor,
            target=target,
            document_name=document_name,
            transport_name="ssh",
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
