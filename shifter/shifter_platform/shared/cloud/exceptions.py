"""Provider-agnostic cloud exceptions.

All cloud adapter errors inherit from CloudError so callers can catch
provider-specific failures without knowing which provider is active.
"""


class CloudError(Exception):
    """Base exception for all cloud provider operations.

    ``code`` optionally carries a stable, machine-readable classification (e.g. the
    ADR-039 ``identity-or-policy`` / ``prerequisite`` classes) so callers can
    distinguish a permanent policy denial from an operational failure without
    parsing the human-readable message (issue #1348).
    """

    code: str = ""


class CloudProviderNotImplementedError(CloudError):
    """Raised when a requested cloud provider/capability has no adapter.

    The supported-backend list is derived from the ``installation`` registry --
    the single source of truth for backends -- rather than a hardcoded literal
    (PLAT-2005). ``capability`` is set when the failure is a backend that is
    registered but does not declare the requested cloud capability.
    """

    def __init__(self, provider: str, capability: object | None = None) -> None:
        from installation.registry import KNOWN_BACKENDS

        supported = ", ".join(sorted(KNOWN_BACKENDS))
        scope = f" for capability '{getattr(capability, 'name', capability)}'" if capability is not None else ""
        super().__init__(f"Cloud provider '{provider}' is not implemented{scope}. Supported providers: {supported}")
        self.provider = provider
        self.capability = capability


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
