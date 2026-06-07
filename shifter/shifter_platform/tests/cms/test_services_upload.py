"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

from unittest.mock import Mock, patch

import pytest

from cms import services
from shared.constants import USER_CANNOT_BE_NONE

# MSI magic prefix used to make every happy-path complete_upload test pass the
# server-side header inspection added in issue #696.
_MSI_HEADER = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1]) + b"\x00" * 16


@pytest.fixture
def mock_user():
    user = Mock()
    user.pk = 42
    user.id = 42
    user.email = "test@example.com"
    return user


class TestInitiateUploadDependencies:
    """Dependency call tests for initiate_upload()."""

    def test_calls_get_storage_used_with_user(self, mock_user):
        """Service calls get_storage_used to check quota."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0) as mock_storage,
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(
                "cms.assets.s3.generate_presigned_upload_url",
                return_value=("url", "key"),
            ),
            patch("cms.assets.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(mock_user, "Agent", "agent.msi", 1000)
            mock_storage.assert_called_once_with(mock_user)

    def test_calls_validate_file_extension_with_filename(self, mock_user):
        """Service calls validate_file_extension with the filename."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(
                "cms.assets.s3.generate_presigned_upload_url",
                return_value=("url", "key"),
            ),
            patch("cms.assets.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(mock_user, "Agent", "agent.msi", 1000)
            mock_validate.assert_called_once_with("agent.msi")

    def test_calls_generate_presigned_url_with_user_and_filename(self, mock_user):
        """Service calls generate_presigned_upload_url with user_id and filename."""
        presign_path = "cms.assets.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("url", "key")) as mock_presign,
            patch("cms.assets.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(mock_user, "Agent", "agent.msi", 1000)
            mock_presign.assert_called_once_with(user_id=mock_user.id, filename="agent.msi")

    def test_calls_generate_upload_token_with_all_params(self, mock_user):
        """Service calls generate_upload_token with all required params."""
        presign_path = "cms.assets.s3.generate_presigned_upload_url"
        token_path = "cms.assets.upload_token.generate_upload_token"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("presigned_url", "s3_key")),
            patch(token_path, return_value="token") as mock_token,
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(mock_user, "My Agent", "agent.msi", 5000)
            mock_token.assert_called_once_with(
                user_id=mock_user.id,
                s3_key="s3_key",
                name="My Agent",
                filename="agent.msi",
                os_slug="windows",
                file_size=5000,
                agent_type="xdr",
            )


class TestInitiateUploadReturns:
    """Return payload tests for initiate_upload()."""

    def test_returns_dict_with_presigned_url(self, mock_user):
        """Service returns dict containing presigned_url."""
        presign_url = "https://s3.example.com/upload"
        presign_path = "cms.assets.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=(presign_url, "key")),
            patch("cms.assets.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(mock_user, "Agent", "agent.msi", 1000)
            assert result["presigned_url"] == presign_url

    def test_returns_dict_with_s3_key(self, mock_user):
        """Service returns dict containing s3_key."""
        s3_key = "agents/1/abc123_agent.msi"
        presign_path = "cms.assets.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("url", s3_key)),
            patch("cms.assets.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(mock_user, "Agent", "agent.msi", 1000)
            assert result["s3_key"] == s3_key

    def test_returns_dict_with_upload_token(self, mock_user):
        """Service returns dict containing upload_token."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(
                "cms.assets.s3.generate_presigned_upload_url",
                return_value=("url", "key"),
            ),
            patch(
                "cms.assets.upload_token.generate_upload_token",
                return_value="signed_token_abc123",
            ),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(mock_user, "Agent", "agent.msi", 1000)
            assert result["upload_token"] == "signed_token_abc123"

    def test_returns_dict_with_expected_os(self, mock_user):
        """Service returns dict containing expected_os from file format."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(
                "cms.assets.s3.generate_presigned_upload_url",
                return_value=("url", "key"),
            ),
            patch("cms.assets.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="linux-debian")
            result = services.initiate_upload(mock_user, "Agent", "agent.deb", 1000)
            assert result["expected_os"] == "linux-debian"


class TestInitiateUploadUserValidation:
    """User validation tests for initiate_upload()."""

    def test_raises_typeerror_when_user_is_none(self):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.initiate_upload(None, "Agent", "agent.msi", 1000)

    def test_raises_typeerror_when_user_has_no_id_attribute(self):
        """Service raises TypeError when user has no id attribute."""
        invalid_user = "not a user"
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.initiate_upload(invalid_user, "Agent", "agent.msi", 1000)

    def test_raises_valueerror_when_user_id_is_none(self):
        """Service raises ValueError when user is unsaved (id=None)."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.initiate_upload(unsaved_user, "Agent", "agent.msi", 1000)


class TestInitiateUploadInputValidation:
    """Name, filename, and size validation tests for initiate_upload()."""

    def test_raises_valueerror_when_name_is_none(self, mock_user):
        """Service raises ValueError when name is None."""
        with pytest.raises(ValueError, match="name cannot be None"):
            services.initiate_upload(mock_user, None, "agent.msi", 1000)

    def test_raises_valueerror_when_name_is_empty(self, mock_user):
        """Service raises ValueError when name is empty string."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            services.initiate_upload(mock_user, "", "agent.msi", 1000)

    def test_raises_valueerror_when_name_is_whitespace(self, mock_user):
        """Service raises ValueError when name is only whitespace."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            services.initiate_upload(mock_user, "   ", "agent.msi", 1000)

    def test_raises_valueerror_when_filename_is_none(self, mock_user):
        """Service raises ValueError when filename is None."""
        with pytest.raises(ValueError, match="filename cannot be None"):
            services.initiate_upload(mock_user, "Agent", None, 1000)

    def test_raises_valueerror_when_filename_is_empty(self, mock_user):
        """Service raises ValueError when filename is empty string."""
        with pytest.raises(ValueError, match="filename cannot be empty"):
            services.initiate_upload(mock_user, "Agent", "", 1000)

    def test_raises_valueerror_when_filename_is_whitespace(self, mock_user):
        """Service raises ValueError when filename is only whitespace."""
        with pytest.raises(ValueError, match="filename cannot be empty"):
            services.initiate_upload(mock_user, "Agent", "   ", 1000)

    def test_raises_typeerror_when_file_size_is_none(self, mock_user):
        """Service raises TypeError when file_size is None."""
        with pytest.raises(TypeError, match="file_size cannot be None"):
            services.initiate_upload(mock_user, "Agent", "agent.msi", None)

    def test_raises_typeerror_when_file_size_is_string(self, mock_user):
        """Service raises TypeError when file_size is not an int."""
        with pytest.raises(TypeError, match="file_size must be an int"):
            services.initiate_upload(mock_user, "Agent", "agent.msi", "1000")

    def test_raises_valueerror_when_file_size_is_zero(self, mock_user):
        """Service raises ValueError when file_size is zero."""
        with pytest.raises(ValueError, match="file_size must be positive"):
            services.initiate_upload(mock_user, "Agent", "agent.msi", 0)

    def test_raises_valueerror_when_file_size_is_negative(self, mock_user):
        """Service raises ValueError when file_size is negative."""
        with pytest.raises(ValueError, match="file_size must be positive"):
            services.initiate_upload(mock_user, "Agent", "agent.msi", -100)


class TestInitiateUploadFailures:
    """Downstream failure tests for initiate_upload()."""

    def test_raises_cmserror_when_quota_exceeded(self, mock_user, settings):
        """Service raises CMSError when storage quota would be exceeded."""
        from cms.exceptions import CMSError

        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 9 * 1024 * 1024  # 9 MB used
        new_file_size = 2 * 1024 * 1024  # 2 MB new file

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            pytest.raises(CMSError, match="quota exceeded"),
        ):
            services.initiate_upload(mock_user, "Agent", "agent.msi", new_file_size)

    def test_succeeds_when_quota_not_exceeded(self, mock_user, settings):
        """Service succeeds when storage quota is not exceeded."""
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 5 * 1024 * 1024  # 5 MB used
        new_file_size = 4 * 1024 * 1024  # 4 MB new file (under 10 MB total)

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(
                "cms.assets.s3.generate_presigned_upload_url",
                return_value=("url", "key"),
            ),
            patch("cms.assets.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(mock_user, "Agent", "agent.msi", new_file_size)
            assert "presigned_url" in result

    def test_succeeds_when_quota_exactly_met(self, mock_user, settings):
        """Service succeeds when storage quota is exactly met."""
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 5 * 1024 * 1024  # 5 MB used
        new_file_size = 5 * 1024 * 1024  # 5 MB new file (exactly 10 MB total)

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(
                "cms.assets.s3.generate_presigned_upload_url",
                return_value=("url", "key"),
            ),
            patch("cms.assets.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(mock_user, "Agent", "agent.msi", new_file_size)
            assert "presigned_url" in result

    def test_raises_cmserror_on_invalid_extension(self, mock_user):
        """Service raises CMSError when file extension is not allowed."""
        from cms.assets.validation import ValidationError
        from cms.exceptions import CMSError

        validation_path = "cms.assets.validation.validate_file_extension"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch(validation_path, side_effect=ValidationError("Extension not allowed")),
            pytest.raises(CMSError, match="Extension not allowed"),
        ):
            services.initiate_upload(mock_user, "Agent", "agent.exe", 1000)

    def test_raises_cmserror_on_s3_error(self, mock_user):
        """Service raises CMSError when S3 presigned URL generation fails."""
        from cms.assets.s3 import S3Error
        from cms.exceptions import CMSError

        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("cms.assets.validation.validate_file_extension") as mock_validate,
            patch(
                "cms.assets.s3.generate_presigned_upload_url",
                side_effect=S3Error("S3 unavailable"),
            ),
            pytest.raises(CMSError, match="Failed to initiate upload"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(mock_user, "Agent", "agent.msi", 1000)

    def test_propagates_unexpected_exception(self, mock_user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch(
                "cms.assets.services.get_storage_used",
                side_effect=RuntimeError("Unexpected"),
            ),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.initiate_upload(mock_user, "Agent", "agent.msi", 1000)
