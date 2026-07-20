"""Tests for provisioner cloud abstraction exceptions."""

from cloud.exceptions import (
    CloudConfigStoreError,
    CloudDBAuthError,
    CloudError,
    CloudEventBusError,
    CloudProviderNotImplementedError,
    CloudSecretsError,
    CloudStorageError,
    ObjectPreconditionError,
)


class TestExceptionHierarchy:
    """All cloud exceptions inherit from CloudError."""

    def test_all_inherit_from_cloud_error(self):
        assert issubclass(CloudEventBusError, CloudError)
        assert issubclass(CloudConfigStoreError, CloudError)
        assert issubclass(CloudDBAuthError, CloudError)
        assert issubclass(CloudStorageError, CloudError)
        assert issubclass(CloudSecretsError, CloudError)
        assert issubclass(CloudProviderNotImplementedError, CloudError)

    def test_object_precondition_error_is_a_cloud_storage_error(self):
        assert issubclass(ObjectPreconditionError, CloudStorageError)
        assert issubclass(ObjectPreconditionError, CloudError)

    def test_cloud_error_inherits_from_exception(self):
        assert issubclass(CloudError, Exception)

    def test_provider_not_implemented_error(self):
        err = CloudProviderNotImplementedError("gcp")
        assert "gcp" in str(err)
        assert err.provider == "gcp"

    def test_provider_list_is_derived_from_the_installation_registry(self):
        """Sorted ``installation.registry.KNOWN_BACKENDS`` ('aws', 'gcp') must
        appear verbatim -- the message is no longer a hardcoded literal."""
        err = CloudProviderNotImplementedError("azure")
        assert "Supported providers: aws, gcp" in str(err)

    def test_capability_defaults_to_none(self):
        err = CloudProviderNotImplementedError("aws")
        assert err.capability is None

    def test_capability_is_named_in_message_and_stored(self):
        from installation.contract import BackendCapability

        err = CloudProviderNotImplementedError("aws", BackendCapability.EVENT_BUS)
        assert "aws" in str(err)
        assert "EVENT_BUS" in str(err)
        assert err.capability is BackendCapability.EVENT_BUS

    def test_capability_without_name_attribute_is_rendered_directly(self):
        """A plain (non-enum) capability value falls back to ``str()`` via getattr's default."""
        err = CloudProviderNotImplementedError("aws", "custom-capability")
        assert "custom-capability" in str(err)
