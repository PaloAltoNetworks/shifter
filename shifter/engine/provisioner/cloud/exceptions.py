"""Provider-agnostic cloud exceptions for the provisioner.

Mirrors shared/cloud/exceptions.py but without Django dependency.
"""


class CloudError(Exception):
    """Base exception for all cloud provider operations."""


class CloudProviderNotImplementedError(CloudError):
    """Raised when a requested cloud provider has no adapter or adapter is a stub."""

    def __init__(self, provider: str, service: str = "") -> None:
        if service:
            msg = (
                f"GCP {service} adapter is not yet implemented. "
                f"This is a stub for the AWS→GCP migration. "
                f"Implement cloud/gcp/{service.lower().replace(' ', '_')}.py to enable."
            )
        else:
            msg = f"Cloud provider '{provider}' is not implemented. Supported: aws. Planned: gcp"
        super().__init__(msg)
        self.provider = provider
        self.service = service


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
