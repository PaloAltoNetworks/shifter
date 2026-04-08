"""Provider-agnostic cloud exceptions.

All cloud adapter errors inherit from CloudError so callers can catch
provider-specific failures without knowing which provider is active.
"""


class CloudError(Exception):
    """Base exception for all cloud provider operations."""


class CloudProviderNotImplementedError(CloudError):
    """Raised when a requested cloud provider has no adapter or adapter is a stub."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"Cloud provider '{provider}' is not yet implemented. Supported: aws. Planned: gcp")
        self.provider = provider


class CloudStorageError(CloudError):
    """Error during object storage operations."""


class CloudTaskError(CloudError):
    """Error during task/container orchestration operations."""


class CloudQueueError(CloudError):
    """Error during queue operations."""


class CloudSecretsError(CloudError):
    """Error during secrets retrieval operations."""
