"""Tests for cloud abstraction exceptions."""

from shared.cloud.exceptions import (
    CloudError,
    CloudProviderNotImplementedError,
    CloudQueueError,
    CloudSecretsError,
    CloudStorageError,
    CloudTaskError,
)


class TestExceptionHierarchy:
    """All cloud exceptions inherit from CloudError."""

    def test_cloud_error_is_base(self):
        assert issubclass(CloudStorageError, CloudError)
        assert issubclass(CloudTaskError, CloudError)
        assert issubclass(CloudQueueError, CloudError)
        assert issubclass(CloudSecretsError, CloudError)
        assert issubclass(CloudProviderNotImplementedError, CloudError)

    def test_cloud_error_inherits_from_exception(self):
        assert issubclass(CloudError, Exception)

    def test_exceptions_carry_message(self):
        err = CloudStorageError("upload failed")
        assert str(err) == "upload failed"

    def test_provider_not_implemented_error(self):
        err = CloudProviderNotImplementedError("gcp")
        assert "gcp" in str(err)
