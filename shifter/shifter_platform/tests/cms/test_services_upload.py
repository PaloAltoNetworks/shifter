"""CMS service interface tests.

Tests service-level behavior only:
- Expected behavior / return values
- Logging (debug and error levels)
- Exception handling
- Input validation (service's responsibility)

Does NOT re-test model behavior (filtering, field validation, etc).
"""

import logging
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.models import OperatingSystem
from mission_control.models import AgentConfig

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def agent(user, db):
    """Create an agent for testing."""
    os = OperatingSystem.objects.get(slug="windows")
    return AgentConfig.objects.create(
        user=user,
        name="Test Agent",
        os=os,
        s3_key="agents/test/agent.msi",
        original_filename="agent.msi",
        file_size_bytes=1000,
        sha256_hash="abc123",
    )


@pytest.mark.django_db
class TestInitiateUpload:
    """Tests for initiate_upload() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates inputs (user, name, filename, file_size)
    - Checks storage quota
    - Validates file extension
    - Generates presigned URL via S3 service
    - Generates upload token
    - Returns dict with presigned_url, s3_key, upload_token, expected_os
    - Logs appropriately
    """

    # --- Service calls dependencies correctly ---

    def test_calls_get_storage_used_with_user(self, user):
        """Service calls get_storage_used to check quota."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0) as mock_storage,
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
            mock_storage.assert_called_once_with(user)

    def test_calls_validate_file_extension_with_filename(self, user):
        """Service calls validate_file_extension with the filename."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
            mock_validate.assert_called_once_with("agent.msi")

    def test_calls_generate_presigned_url_with_user_and_filename(self, user):
        """Service calls generate_presigned_upload_url with user_id and filename."""
        presign_path = "mission_control.services.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("url", "key")) as mock_presign,
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
            mock_presign.assert_called_once_with(user_id=user.id, filename="agent.msi")

    def test_calls_generate_upload_token_with_all_params(self, user):
        """Service calls generate_upload_token with all required params."""
        presign_path = "mission_control.services.s3.generate_presigned_upload_url"
        token_path = "mission_control.services.upload_token.generate_upload_token"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("presigned_url", "s3_key")),
            patch(token_path, return_value="token") as mock_token,
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "My Agent", "agent.msi", 5000)
            mock_token.assert_called_once_with(
                user_id=user.id,
                s3_key="s3_key",
                name="My Agent",
                filename="agent.msi",
                os_slug="windows",
                file_size=5000,
            )

    # --- Service returns correct dict ---

    def test_returns_dict_with_presigned_url(self, user):
        """Service returns dict containing presigned_url."""
        presign_url = "https://s3.example.com/upload"
        presign_path = "mission_control.services.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=(presign_url, "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", 1000)
            assert result["presigned_url"] == presign_url

    def test_returns_dict_with_s3_key(self, user):
        """Service returns dict containing s3_key."""
        s3_key = "agents/1/abc123_agent.msi"
        presign_path = "mission_control.services.s3.generate_presigned_upload_url"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch(presign_path, return_value=("url", s3_key)),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", 1000)
            assert result["s3_key"] == s3_key

    def test_returns_dict_with_upload_token(self, user):
        """Service returns dict containing upload_token."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="signed_token_abc123"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", 1000)
            assert result["upload_token"] == "signed_token_abc123"

    def test_returns_dict_with_expected_os(self, user):
        """Service returns dict containing expected_os from file format."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="linux-debian")
            result = services.initiate_upload(user, "Agent", "agent.deb", 1000)
            assert result["expected_os"] == "linux-debian"

    # --- Input validation - user ---

    def test_raises_typeerror_when_user_is_none(self, db):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.initiate_upload(None, "Agent", "agent.msi", 1000)

    def test_raises_typeerror_when_user_has_no_id_attribute(self, db):
        """Service raises TypeError when user has no id attribute."""
        invalid_user = "not a user"
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.initiate_upload(invalid_user, "Agent", "agent.msi", 1000)

    def test_raises_valueerror_when_user_id_is_none(self, db):
        """Service raises ValueError when user is unsaved (id=None)."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.initiate_upload(unsaved_user, "Agent", "agent.msi", 1000)

    # --- Input validation - name ---

    def test_raises_valueerror_when_name_is_none(self, user):
        """Service raises ValueError when name is None."""
        with pytest.raises(ValueError, match="name cannot be None"):
            services.initiate_upload(user, None, "agent.msi", 1000)

    def test_raises_valueerror_when_name_is_empty(self, user):
        """Service raises ValueError when name is empty string."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            services.initiate_upload(user, "", "agent.msi", 1000)

    def test_raises_valueerror_when_name_is_whitespace(self, user):
        """Service raises ValueError when name is only whitespace."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            services.initiate_upload(user, "   ", "agent.msi", 1000)

    # --- Input validation - filename ---

    def test_raises_valueerror_when_filename_is_none(self, user):
        """Service raises ValueError when filename is None."""
        with pytest.raises(ValueError, match="filename cannot be None"):
            services.initiate_upload(user, "Agent", None, 1000)

    def test_raises_valueerror_when_filename_is_empty(self, user):
        """Service raises ValueError when filename is empty string."""
        with pytest.raises(ValueError, match="filename cannot be empty"):
            services.initiate_upload(user, "Agent", "", 1000)

    def test_raises_valueerror_when_filename_is_whitespace(self, user):
        """Service raises ValueError when filename is only whitespace."""
        with pytest.raises(ValueError, match="filename cannot be empty"):
            services.initiate_upload(user, "Agent", "   ", 1000)

    # --- Input validation - file_size ---

    def test_raises_typeerror_when_file_size_is_none(self, user):
        """Service raises TypeError when file_size is None."""
        with pytest.raises(TypeError, match="file_size cannot be None"):
            services.initiate_upload(user, "Agent", "agent.msi", None)

    def test_raises_typeerror_when_file_size_is_string(self, user):
        """Service raises TypeError when file_size is not an int."""
        with pytest.raises(TypeError, match="file_size must be an int"):
            services.initiate_upload(user, "Agent", "agent.msi", "1000")

    def test_raises_valueerror_when_file_size_is_zero(self, user):
        """Service raises ValueError when file_size is zero."""
        with pytest.raises(ValueError, match="file_size must be positive"):
            services.initiate_upload(user, "Agent", "agent.msi", 0)

    def test_raises_valueerror_when_file_size_is_negative(self, user):
        """Service raises ValueError when file_size is negative."""
        with pytest.raises(ValueError, match="file_size must be positive"):
            services.initiate_upload(user, "Agent", "agent.msi", -100)

    # --- Quota validation ---

    def test_raises_cmserror_when_quota_exceeded(self, user, settings):
        """Service raises CMSError when storage quota would be exceeded."""
        from cms.exceptions import CMSError

        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 9 * 1024 * 1024  # 9 MB used
        new_file_size = 2 * 1024 * 1024  # 2 MB new file

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            pytest.raises(CMSError, match="quota exceeded"),
        ):
            services.initiate_upload(user, "Agent", "agent.msi", new_file_size)

    def test_succeeds_when_quota_not_exceeded(self, user, settings):
        """Service succeeds when storage quota is not exceeded."""
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 5 * 1024 * 1024  # 5 MB used
        new_file_size = 4 * 1024 * 1024  # 4 MB new file (under 10 MB total)

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", new_file_size)
            assert "presigned_url" in result

    def test_succeeds_when_quota_exactly_met(self, user, settings):
        """Service succeeds when storage quota is exactly met."""
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10  # 10 MB quota
        current_usage = 5 * 1024 * 1024  # 5 MB used
        new_file_size = 5 * 1024 * 1024  # 5 MB new file (exactly 10 MB total)

        with (
            patch("cms.assets.services.get_storage_used", return_value=current_usage),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            result = services.initiate_upload(user, "Agent", "agent.msi", new_file_size)
            assert "presigned_url" in result

    # --- File extension validation ---

    def test_raises_cmserror_on_invalid_extension(self, user):
        """Service raises CMSError when file extension is not allowed."""
        from cms.exceptions import CMSError
        from mission_control.services.validation import ValidationError

        validation_path = "mission_control.services.validation.validate_file_extension"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch(validation_path, side_effect=ValidationError("Extension not allowed")),
            pytest.raises(CMSError, match="Extension not allowed"),
        ):
            services.initiate_upload(user, "Agent", "agent.exe", 1000)

    # --- S3 error handling ---

    def test_raises_cmserror_on_s3_error(self, user):
        """Service raises CMSError when S3 presigned URL generation fails."""
        from cms.exceptions import CMSError
        from mission_control.services.s3 import S3Error

        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", side_effect=S3Error("S3 unavailable")),
            pytest.raises(CMSError, match="Failed to initiate upload"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on success with file info."""
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch("mission_control.services.validation.validate_file_extension") as mock_validate,
            patch("mission_control.services.s3.generate_presigned_upload_url", return_value=("url", "key")),
            patch("mission_control.services.upload_token.generate_upload_token", return_value="token"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            mock_validate.return_value = Mock(os_slug="windows")
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
        assert "agent.msi" in caplog.text or "success" in caplog.text.lower()

    def test_logs_error_on_quota_exceeded(self, user, caplog, settings):
        """Service logs error when quota is exceeded."""
        from cms.exceptions import CMSError

        settings.AGENT_USER_STORAGE_QUOTA_MB = 1
        with (
            patch("cms.assets.services.get_storage_used", return_value=2 * 1024 * 1024),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
        assert "quota" in caplog.text.lower() or "exceeded" in caplog.text.lower()

    def test_logs_error_on_validation_failure(self, user, caplog):
        """Service logs error when file extension validation fails."""
        from cms.exceptions import CMSError
        from mission_control.services.validation import ValidationError

        validation_path = "mission_control.services.validation.validate_file_extension"
        with (
            patch("cms.assets.services.get_storage_used", return_value=0),
            patch(validation_path, side_effect=ValidationError("Invalid extension")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.initiate_upload(user, "Agent", "agent.exe", 1000)
        assert "error" in caplog.text.lower() or "extension" in caplog.text.lower()

    def test_logs_error_on_input_validation_failure(self, user, caplog):
        """Service logs error when input validation fails."""
        with (
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(ValueError),
        ):
            services.initiate_upload(user, "", "agent.msi", 1000)
        assert "error" in caplog.text.lower() or "name" in caplog.text.lower()

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch("cms.assets.services.get_storage_used", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.initiate_upload(user, "Agent", "agent.msi", 1000)


@pytest.mark.django_db
class TestCompleteUpload:
    """Tests for complete_upload() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates inputs (user, upload_token, sha256)
    - Verifies upload token
    - Verifies S3 object exists
    - Tags S3 object as completed
    - Creates agent record
    - Returns created agent
    - Logs appropriately
    """

    # --- Service calls dependencies correctly ---

    def test_calls_verify_upload_token_with_token_and_user_id(self, user):
        """Service calls verify_upload_token with the token and user_id."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        verify_token_path = "mission_control.services.upload_token.verify_upload_token"
        with (
            patch(verify_token_path, return_value=token_payload) as mock_verify,
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
            mock_verify.assert_called_once_with("token123", user.id)

    def test_calls_verify_s3_object_exists_with_s3_key(self, user):
        """Service calls verify_s3_object_exists with s3_key from token."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")) as mock_verify_s3,
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
            mock_verify_s3.assert_called_once_with("agents/1/abc_agent.msi")

    def test_calls_tag_s3_object_with_completed_tags(self, user):
        """Service calls tag_s3_object with completion tags."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object") as mock_tag,
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
            mock_tag.assert_called_once_with("agents/1/abc_agent.msi", {"status": "completed"})

    def test_calls_create_agent_with_all_params(self, user):
        """Service calls create_agent with all required params."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "My Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 5000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(5000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
            mock_create.assert_called_once_with(
                user=user,
                name="My Agent",
                s3_key="agents/1/abc_agent.msi",
                filename="agent.msi",
                os_slug="windows",
                file_size=5000,
                sha256="sha256hash",
                upload_method="presigned",
            )

    # --- Service returns agent ---

    def test_returns_created_agent(self, user):
        """Service returns the agent created by create_agent."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        mock_agent = Mock(spec=AgentConfig, id=42, name="Agent")
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent", return_value=mock_agent),
        ):
            result = services.complete_upload(user, "token123", "sha256hash")
            assert result == mock_agent
            assert result.id == 42

    # --- Input validation - user ---

    def test_raises_typeerror_when_user_is_none(self, db):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.complete_upload(None, "token123", "sha256hash")

    def test_raises_typeerror_when_user_has_no_id_attribute(self, db):
        """Service raises TypeError when user has no id attribute."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.complete_upload("not a user", "token123", "sha256hash")

    def test_raises_valueerror_when_user_id_is_none(self, db):
        """Service raises ValueError when user is unsaved."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.complete_upload(unsaved_user, "token123", "sha256hash")

    # --- Input validation - upload_token ---

    def test_raises_valueerror_when_upload_token_is_none(self, user):
        """Service raises ValueError when upload_token is None."""
        with pytest.raises(ValueError, match="upload_token cannot be None"):
            services.complete_upload(user, None, "sha256hash")

    def test_raises_valueerror_when_upload_token_is_empty(self, user):
        """Service raises ValueError when upload_token is empty."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.complete_upload(user, "", "sha256hash")

    def test_raises_valueerror_when_upload_token_is_whitespace(self, user):
        """Service raises ValueError when upload_token is only whitespace."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.complete_upload(user, "   ", "sha256hash")

    # --- Input validation - sha256 ---

    def test_raises_valueerror_when_sha256_is_none(self, user):
        """Service raises ValueError when sha256 is None."""
        with pytest.raises(ValueError, match="sha256 cannot be None"):
            services.complete_upload(user, "token123", None)

    def test_raises_valueerror_when_sha256_is_empty(self, user):
        """Service raises ValueError when sha256 is empty."""
        with pytest.raises(ValueError, match="sha256 cannot be empty"):
            services.complete_upload(user, "token123", "")

    def test_raises_valueerror_when_sha256_is_whitespace(self, user):
        """Service raises ValueError when sha256 is only whitespace."""
        with pytest.raises(ValueError, match="sha256 cannot be empty"):
            services.complete_upload(user, "token123", "   ")

    # --- Token verification errors ---

    def test_raises_cmserror_on_invalid_token(self, user):
        """Service raises CMSError when token is invalid."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Invalid token")),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.complete_upload(user, "bad_token", "sha256hash")

    def test_raises_cmserror_on_expired_token(self, user):
        """Service raises CMSError when token is expired."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Token expired")),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.complete_upload(user, "expired_token", "sha256hash")

    # --- S3 verification errors ---

    def test_raises_cmserror_when_s3_object_not_found(self, user):
        """Service raises CMSError when S3 object doesn't exist."""
        from cms.exceptions import CMSError
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", side_effect=S3Error("Object not found")),
            pytest.raises(CMSError, match="Upload not found"),
        ):
            services.complete_upload(user, "token123", "sha256hash")

    def test_raises_cmserror_when_file_size_mismatch(self, user):
        """Service raises CMSError when S3 object size doesn't match token."""
        from cms.exceptions import CMSError

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(5000, "etag")),  # Wrong size
            pytest.raises(CMSError, match="size mismatch"),
        ):
            services.complete_upload(user, "token123", "sha256hash")

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on success with agent info."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("mission_control.services.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(user, "token123", "sha256hash")
        assert "42" in caplog.text or "completed" in caplog.text.lower()

    def test_logs_error_on_invalid_token(self, user, caplog):
        """Service logs error when token verification fails."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Invalid")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.complete_upload(user, "bad_token", "sha256hash")
        assert "error" in caplog.text.lower() or "token" in caplog.text.lower()

    def test_logs_error_on_s3_verification_failure(self, user, caplog):
        """Service logs error when S3 verification fails."""
        from cms.exceptions import CMSError
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.verify_s3_object_exists", side_effect=S3Error("Not found")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.complete_upload(user, "token123", "sha256hash")
        assert "error" in caplog.text.lower() or "s3" in caplog.text.lower()

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.complete_upload(user, "token123", "sha256hash")


@pytest.mark.django_db
class TestCancelUpload:
    """Tests for cancel_upload() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates inputs (user, upload_token)
    - Verifies upload token
    - Deletes S3 object
    - Returns None on success
    - Logs appropriately
    """

    # --- Service calls dependencies correctly ---

    def test_calls_verify_upload_token_with_token_and_user_id(self, user):
        """Service calls verify_upload_token with the token and user_id."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        verify_token_path = "mission_control.services.upload_token.verify_upload_token"
        with (
            patch(verify_token_path, return_value=token_payload) as mock_verify,
            patch("mission_control.services.s3.delete_agent"),
        ):
            services.cancel_upload(user, "token123")
            mock_verify.assert_called_once_with("token123", user.id)

    def test_calls_delete_agent_with_s3_key(self, user):
        """Service calls delete_agent with s3_key from token."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        verify_token_path = "mission_control.services.upload_token.verify_upload_token"
        with (
            patch(verify_token_path, return_value=token_payload),
            patch("mission_control.services.s3.delete_agent") as mock_delete,
        ):
            services.cancel_upload(user, "token123")
            mock_delete.assert_called_once_with("agents/1/abc_agent.msi")

    # --- Service returns None ---

    def test_returns_none_on_success(self, user):
        """Service returns None on successful cancellation."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent"),
        ):
            result = services.cancel_upload(user, "token123")
            assert result is None

    # --- Input validation - user ---

    def test_raises_typeerror_when_user_is_none(self, db):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.cancel_upload(None, "token123")

    def test_raises_typeerror_when_user_has_no_id_attribute(self, db):
        """Service raises TypeError when user has no id attribute."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.cancel_upload("not a user", "token123")

    def test_raises_valueerror_when_user_id_is_none(self, db):
        """Service raises ValueError when user is unsaved."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.cancel_upload(unsaved_user, "token123")

    # --- Input validation - upload_token ---

    def test_raises_valueerror_when_upload_token_is_none(self, user):
        """Service raises ValueError when upload_token is None."""
        with pytest.raises(ValueError, match="upload_token cannot be None"):
            services.cancel_upload(user, None)

    def test_raises_valueerror_when_upload_token_is_empty(self, user):
        """Service raises ValueError when upload_token is empty."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.cancel_upload(user, "")

    def test_raises_valueerror_when_upload_token_is_whitespace(self, user):
        """Service raises ValueError when upload_token is only whitespace."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.cancel_upload(user, "   ")

    # --- Token verification errors ---

    def test_raises_cmserror_on_invalid_token(self, user):
        """Service raises CMSError when token is invalid."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Invalid token")),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.cancel_upload(user, "bad_token")

    def test_raises_cmserror_on_expired_token(self, user):
        """Service raises CMSError when token is expired."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Token expired")),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.cancel_upload(user, "expired_token")

    # --- S3 delete errors (should be ignored) ---

    def test_succeeds_when_s3_delete_fails(self, user):
        """Service succeeds even when S3 delete fails (best effort cleanup)."""
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent", side_effect=S3Error("Delete failed")),
        ):
            # Should not raise - S3 delete is best effort
            result = services.cancel_upload(user, "token123")
            assert result is None

    def test_succeeds_when_s3_object_not_found(self, user):
        """Service succeeds when S3 object doesn't exist (already deleted)."""
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent", side_effect=S3Error("Object not found")),
        ):
            # Should not raise - object may have never been uploaded
            result = services.cancel_upload(user, "token123")
            assert result is None

    # --- Logging ---

    def test_logs_debug_on_entry(self, user, caplog):
        """Service logs debug on entry with user info."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.cancel_upload(user, "token123")
        assert str(user.id) in caplog.text

    def test_logs_debug_on_success(self, user, caplog):
        """Service logs debug on success."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent"),
            caplog.at_level(logging.DEBUG, logger="cms.services"),
        ):
            services.cancel_upload(user, "token123")
        assert "cancelled" in caplog.text.lower() or "cancel" in caplog.text.lower()

    def test_logs_warning_on_s3_delete_failure(self, user, caplog):
        """Service logs warning when S3 delete fails."""
        from mission_control.services.s3 import S3Error

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("mission_control.services.upload_token.verify_upload_token", return_value=token_payload),
            patch("mission_control.services.s3.delete_agent", side_effect=S3Error("Delete failed")),
            caplog.at_level(logging.WARNING, logger="cms.services"),
        ):
            services.cancel_upload(user, "token123")
        assert "warning" in caplog.text.lower() or "failed" in caplog.text.lower() or "s3" in caplog.text.lower()

    def test_logs_error_on_invalid_token(self, user, caplog):
        """Service logs error when token verification fails."""
        from cms.exceptions import CMSError

        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=ValueError("Invalid")),
            caplog.at_level(logging.ERROR, logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.cancel_upload(user, "bad_token")
        assert "error" in caplog.text.lower() or "token" in caplog.text.lower()

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch("mission_control.services.upload_token.verify_upload_token", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.cancel_upload(user, "token123")
