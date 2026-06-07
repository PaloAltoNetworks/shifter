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
from cms.models import AgentConfig
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


class TestCompleteUploadDependencies:
    """Dependency call tests for complete_upload()."""

    def test_calls_verify_upload_token_with_token_and_user_id(self, mock_user):
        """Service calls verify_upload_token with the token and user_id."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        verify_token_path = "cms.assets.upload_token.verify_upload_token"
        with (
            patch(verify_token_path, return_value=token_payload) as mock_verify,
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("cms.assets.s3.read_agent_header", return_value=_MSI_HEADER),
            patch("cms.assets.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(mock_user, "token123")
            mock_verify.assert_called_once_with("token123", mock_user.id)

    def test_calls_verify_s3_object_exists_with_s3_key(self, mock_user):
        """Service calls verify_s3_object_exists with s3_key from token."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch(
                "cms.assets.upload_token.verify_upload_token",
                return_value=token_payload,
            ),
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(1000, "etag")) as mock_verify_s3,
            patch("cms.assets.s3.read_agent_header", return_value=_MSI_HEADER),
            patch("cms.assets.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(mock_user, "token123")
            mock_verify_s3.assert_called_once_with("agents/1/abc_agent.msi")

    def test_calls_tag_s3_object_with_completed_tags(self, mock_user):
        """Service calls tag_s3_object with completion tags."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch(
                "cms.assets.upload_token.verify_upload_token",
                return_value=token_payload,
            ),
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("cms.assets.s3.read_agent_header", return_value=_MSI_HEADER),
            patch("cms.assets.s3.tag_s3_object") as mock_tag,
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(mock_user, "token123")
            mock_tag.assert_called_once_with("agents/1/abc_agent.msi", {"status": "completed"})

    def test_calls_create_agent_with_all_params(self, mock_user):
        """Service calls create_agent with all required params."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "My Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 5000,
            "agent_type": "xdr",
        }
        with (
            patch(
                "cms.assets.upload_token.verify_upload_token",
                return_value=token_payload,
            ),
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(5000, "etag")),
            patch("cms.assets.s3.read_agent_header", return_value=_MSI_HEADER),
            patch("cms.assets.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(mock_user, "token123")
            mock_create.assert_called_once_with(
                user=mock_user,
                spec=services.AgentUploadSpec(
                    name="My Agent",
                    s3_key="agents/1/abc_agent.msi",
                    filename="agent.msi",
                    os_slug="windows",
                    file_size=5000,
                    upload_method="presigned",
                    agent_type="xdr",
                ),
            )


class TestCompleteUploadReturns:
    """Return payload tests for complete_upload()."""

    def test_returns_created_agent(self, mock_user):
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
            patch(
                "cms.assets.upload_token.verify_upload_token",
                return_value=token_payload,
            ),
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("cms.assets.s3.read_agent_header", return_value=_MSI_HEADER),
            patch("cms.assets.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent", return_value=mock_agent),
        ):
            result = services.complete_upload(mock_user, "token123")
            assert result == mock_agent
            assert result.id == 42


class TestCompleteUploadTokenValidation:
    """User and upload-token validation tests for complete_upload()."""

    def test_raises_typeerror_when_user_is_none(self):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.complete_upload(None, "token123")

    def test_raises_typeerror_when_user_has_no_id_attribute(self):
        """Service raises TypeError when user has no id attribute."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.complete_upload("not a user", "token123")

    def test_raises_valueerror_when_user_id_is_none(self):
        """Service raises ValueError when user is unsaved."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.complete_upload(unsaved_user, "token123")

    def test_raises_valueerror_when_upload_token_is_none(self, mock_user):
        """Service raises ValueError when upload_token is None."""
        with pytest.raises(ValueError, match="upload_token cannot be None"):
            services.complete_upload(mock_user, None)

    def test_raises_valueerror_when_upload_token_is_empty(self, mock_user):
        """Service raises ValueError when upload_token is empty."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.complete_upload(mock_user, "")

    def test_raises_valueerror_when_upload_token_is_whitespace(self, mock_user):
        """Service raises ValueError when upload_token is only whitespace."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.complete_upload(mock_user, "   ")

    def test_raises_cmserror_on_invalid_token(self, mock_user):
        """Service raises CMSError when token is invalid."""
        from cms.exceptions import CMSError

        with (
            patch(
                "cms.assets.upload_token.verify_upload_token",
                side_effect=ValueError("Invalid token"),
            ),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.complete_upload(mock_user, "bad_token")

    def test_raises_cmserror_on_expired_token(self, mock_user):
        """Service raises CMSError when token is expired."""
        from cms.exceptions import CMSError

        with (
            patch(
                "cms.assets.upload_token.verify_upload_token",
                side_effect=ValueError("Token expired"),
            ),
            pytest.raises(CMSError, match="Invalid upload token"),
        ):
            services.complete_upload(mock_user, "expired_token")


class TestCompleteUploadObjectValidation:
    """S3 object validation tests for complete_upload()."""

    def test_raises_cmserror_when_s3_object_not_found(self, mock_user):
        """Service raises CMSError when S3 object doesn't exist."""
        from cms.assets.s3 import S3Error
        from cms.exceptions import CMSError

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch(
                "cms.assets.upload_token.verify_upload_token",
                return_value=token_payload,
            ),
            patch(
                "cms.assets.s3.verify_s3_object_exists",
                side_effect=S3Error("Object not found"),
            ),
            pytest.raises(CMSError, match="Upload not found"),
        ):
            services.complete_upload(mock_user, "token123")

    def test_raises_cmserror_when_file_size_mismatch(self, mock_user):
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
            patch(
                "cms.assets.upload_token.verify_upload_token",
                return_value=token_payload,
            ),
            patch(
                "cms.assets.s3.verify_s3_object_exists",
                return_value=(5000, "etag"),  # Wrong size
            ),
            pytest.raises(CMSError, match="size mismatch"),
        ):
            services.complete_upload(mock_user, "token123")


class TestCompleteUploadHeaderValidation:
    """File-header inspection and no-leak tests for complete_upload()."""

    def test_reads_object_header_after_size_verify(self, mock_user):
        """Service reads the object header via the cloud seam before tagging."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        msi_magic = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])
        with (
            patch("cms.assets.upload_token.verify_upload_token", return_value=token_payload),
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("cms.assets.s3.read_agent_header", return_value=msi_magic + b"\x00" * 16) as mock_read,
            patch("cms.assets.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent") as mock_create,
        ):
            mock_create.return_value = Mock(spec=AgentConfig, id=42)
            services.complete_upload(mock_user, "token123")
            mock_read.assert_called_once()
            args, _ = mock_read.call_args
            assert args[0] == "agents/1/abc_agent.msi"

    def test_magic_byte_mismatch_raises_and_deletes_object(self, mock_user):
        """Magic-byte mismatch must delete the object and skip tag + create_agent + audit."""
        from cms.exceptions import CMSError

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",  # .msi expects D0 CF 11 E0 ...
            "os_slug": "windows",
            "file_size": 1000,
        }
        # Header is ZIP magic, not MSI — mismatch.
        bogus_header = b"\x50\x4b\x03\x04" + b"\x00" * 16
        with (
            patch("cms.assets.upload_token.verify_upload_token", return_value=token_payload),
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("cms.assets.s3.read_agent_header", return_value=bogus_header),
            patch("cms.assets.s3.tag_s3_object") as mock_tag,
            patch("cms.assets.s3.delete_agent") as mock_delete,
            patch("cms.assets.services.create_agent") as mock_create,
            pytest.raises(CMSError, match="content"),
        ):
            services.complete_upload(mock_user, "token123")
        mock_delete.assert_called_once_with("agents/1/abc_agent.msi")
        mock_tag.assert_not_called()
        mock_create.assert_not_called()

    def test_rejection_log_does_not_leak_header_bytes_or_token(self, mock_user, caplog):
        from cms.exceptions import CMSError

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        leak = b"\x50\x4b\x03\x04S3CR3T-DO-NOT-LEAK"
        with (
            patch("cms.assets.upload_token.verify_upload_token", return_value=token_payload),
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch("cms.assets.s3.read_agent_header", return_value=leak),
            patch("cms.assets.s3.delete_agent"),
            patch("cms.assets.s3.tag_s3_object"),
            patch("cms.assets.services.create_agent"),
            caplog.at_level("WARNING", logger="cms.services"),
            pytest.raises(CMSError),
        ):
            services.complete_upload(mock_user, "token-S3CR3T-DO-NOT-LEAK")

        combined = " ".join(record.getMessage() for record in caplog.records)
        assert "S3CR3T-DO-NOT-LEAK" not in combined

    def test_header_read_failure_raises_cmserror(self, mock_user):
        """If reading the header fails, the service raises CMSError and does not finalize."""
        from cms.assets.s3 import S3Error
        from cms.exceptions import CMSError

        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        with (
            patch("cms.assets.upload_token.verify_upload_token", return_value=token_payload),
            patch("cms.assets.s3.verify_s3_object_exists", return_value=(1000, "etag")),
            patch(
                "cms.assets.s3.read_agent_header",
                side_effect=S3Error("range read failed"),
            ),
            patch("cms.assets.s3.tag_s3_object") as mock_tag,
            patch("cms.assets.services.create_agent") as mock_create,
            pytest.raises(CMSError),
        ):
            services.complete_upload(mock_user, "token123")
        mock_tag.assert_not_called()
        mock_create.assert_not_called()


class TestCompleteUploadFailurePropagation:
    """Unexpected failure propagation tests for complete_upload()."""

    def test_propagates_unexpected_exception(self, mock_user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch(
                "cms.assets.upload_token.verify_upload_token",
                side_effect=RuntimeError("Unexpected"),
            ),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.complete_upload(mock_user, "token123")
