"""Provider-agnostic cloud exceptions for the provisioner.

Mirrors shared/cloud/exceptions.py but without Django dependency.
"""


class CloudError(Exception):
    """Base exception for all cloud provider operations."""


class CloudProviderNotImplementedError(CloudError):
    """Raised when a requested cloud provider has no adapter."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"Cloud provider '{provider}' is not implemented. Supported providers: aws, gcp")
        self.provider = provider


class CloudEventBusError(CloudError):
    """Error during event publishing operations."""


class CloudConfigStoreError(CloudError):
    """Error during config/parameter retrieval operations."""


class CloudDBAuthError(CloudError):
    """Error during database auth token generation."""


class CloudStorageError(CloudError):
    """Error during object storage operations."""


class CloudSecretsError(CloudError):
    """Error during secrets retrieval operations."""


class CloudNetworkInventoryError(CloudError):
    """Error during network inventory or subnet exhaustion alert operations."""
