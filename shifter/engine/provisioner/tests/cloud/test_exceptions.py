"""Tests for provisioner cloud abstraction exceptions."""

from cloud.exceptions import (
    CloudConfigStoreError,
    CloudDBAuthError,
    CloudError,
    CloudEventBusError,
    CloudProviderNotImplementedError,
    CloudSecretsError,
    CloudStorageError,
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

    def test_cloud_error_inherits_from_exception(self):
        assert issubclass(CloudError, Exception)

    def test_provider_not_implemented_error(self):
        err = CloudProviderNotImplementedError("gcp")
        assert "gcp" in str(err)
        assert err.provider == "gcp"
