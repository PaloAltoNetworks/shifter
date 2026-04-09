"""Cloud provider protocol definitions for the provisioner.

These protocols define the interface that each cloud provider adapter must
implement. Separate from the platform protocols because the provisioner
has no Django dependency and different cloud service needs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EventBus(Protocol):
    """Protocol for event publishing (SNS, Pub/Sub, etc.)."""

    def publish(
        self,
        topic_id: str,
        message: str,
        attributes: dict[str, str] | None = None,
    ) -> None: ...


@runtime_checkable
class ConfigStore(Protocol):
    """Protocol for configuration/parameter retrieval (SSM, etc.)."""

    def get_parameter(self, name: str) -> str: ...


@runtime_checkable
class DBAuth(Protocol):
    """Protocol for database authentication token generation (RDS IAM, Cloud SQL IAM, etc.)."""

    def generate_auth_token(
        self,
        hostname: str,
        port: int,
        username: str,
    ) -> str: ...


@runtime_checkable
class SecretsStore(Protocol):
    """Protocol for secrets retrieval (Secrets Manager, Secret Manager, etc.)."""

    def get_secret(self, secret_id: str) -> str: ...


@runtime_checkable
class ObjectStorage(Protocol):
    """Protocol for object storage operations in the provisioner context."""

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
    ) -> str: ...

    def object_exists(self, bucket: str, key: str) -> bool: ...

    def delete_object(self, bucket: str, key: str) -> None: ...


@runtime_checkable
class NetworkInventory(Protocol):
    """Protocol for network/subnet inventory and exhaustion alert publication."""

    def list_subnet_cidrs(self, network_id: str) -> list[str]: ...

    def publish_subnet_exhaustion_alarm(
        self,
        network_id: str,
        cidr_prefix: str,
        subnet_size: int,
    ) -> None: ...
