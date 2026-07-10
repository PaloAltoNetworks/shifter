"""Provider-agnostic cloud exceptions.

All cloud adapter errors inherit from CloudError so callers can catch
provider-specific failures without knowing which provider is active.
"""


class CloudError(Exception):
    """Base exception for all cloud provider operations."""


class CloudProviderNotImplementedError(CloudError):
    """Raised when a requested cloud provider has no adapter."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"Cloud provider '{provider}' is not implemented. Supported providers: aws, gcp")
        self.provider = provider


class CloudStorageError(CloudError):
    """Error during object storage operations."""


class ObjectPreconditionError(CloudStorageError):
    """Raised when a conditional storage operation fails its precondition.

    Signals that a copy/write was refused because the source object no longer
    matches the expected identity (ETag/generation) or the destination already
    exists. This is a security signal for upload finalization — the validated
    bytes changed between check and use — not a transient error to retry
    silently. Subclasses ``CloudStorageError`` so existing broad handlers still
    catch it, while callers that care can distinguish the precondition failure.
    """


class CloudTaskError(CloudError):
    """Error during task/container orchestration operations."""


class CloudQueueError(CloudError):
    """Error during queue operations."""


class CloudSecretsError(CloudError):
    """Error during secrets retrieval operations."""


class CloudEventBusError(CloudError):
    """Error during event bus publish operations."""
