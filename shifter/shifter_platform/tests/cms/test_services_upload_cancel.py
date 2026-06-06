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


class TestCancelUpload:
    """Tests for cancel_upload() service function.

    Tests SERVICE behavior with mocked dependencies:
    - Validates inputs (user, upload_token)
    - Verifies upload token
    - Deletes S3 object
    - Returns None on success
    """

    # --- Service calls dependencies correctly ---

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
            patch("cms.assets.s3.delete_agent"),
        ):
            services.cancel_upload(mock_user, "token123")
            mock_verify.assert_called_once_with("token123", mock_user.id)

    def test_calls_delete_agent_with_s3_key(self, mock_user):
        """Service calls delete_agent with s3_key from token."""
        token_payload = {
            "s3_key": "agents/1/abc_agent.msi",
            "name": "Agent",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
        }
        verify_token_path = "cms.assets.upload_token.verify_upload_token"
        with (
            patch(verify_token_path, return_value=token_payload),
            patch("cms.assets.s3.delete_agent") as mock_delete,
        ):
            services.cancel_upload(mock_user, "token123")
            mock_delete.assert_called_once_with("agents/1/abc_agent.msi")

    # --- Service returns None ---

    def test_returns_none_on_success(self, mock_user):
        """Service returns None on successful cancellation."""
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
            patch("cms.assets.s3.delete_agent"),
        ):
            result = services.cancel_upload(mock_user, "token123")
            assert result is None

    # --- Input validation - user ---

    def test_raises_typeerror_when_user_is_none(self):
        """Service raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.cancel_upload(None, "token123")

    def test_raises_typeerror_when_user_has_no_id_attribute(self):
        """Service raises TypeError when user has no id attribute."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.cancel_upload("not a user", "token123")

    def test_raises_valueerror_when_user_id_is_none(self):
        """Service raises ValueError when user is unsaved."""
        unsaved_user = Mock()
        unsaved_user.id = None
        with pytest.raises(ValueError, match="user must be saved"):
            services.cancel_upload(unsaved_user, "token123")

    # --- Input validation - upload_token ---

    def test_raises_valueerror_when_upload_token_is_none(self, mock_user):
        """Service raises ValueError when upload_token is None."""
        with pytest.raises(ValueError, match="upload_token cannot be None"):
            services.cancel_upload(mock_user, None)

    def test_raises_valueerror_when_upload_token_is_empty(self, mock_user):
        """Service raises ValueError when upload_token is empty."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.cancel_upload(mock_user, "")

    def test_raises_valueerror_when_upload_token_is_whitespace(self, mock_user):
        """Service raises ValueError when upload_token is only whitespace."""
        with pytest.raises(ValueError, match="upload_token cannot be empty"):
            services.cancel_upload(mock_user, "   ")

    # --- Token verification errors ---

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
            services.cancel_upload(mock_user, "bad_token")

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
            services.cancel_upload(mock_user, "expired_token")

    # --- S3 delete errors (should be ignored) ---

    def test_succeeds_when_s3_delete_fails(self, mock_user):
        """Service succeeds even when S3 delete fails (best effort cleanup)."""
        from cms.assets.s3 import S3Error

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
                "cms.assets.s3.delete_agent",
                side_effect=S3Error("Delete failed"),
            ),
        ):
            # Should not raise - S3 delete is best effort
            result = services.cancel_upload(mock_user, "token123")
            assert result is None

    def test_succeeds_when_s3_object_not_found(self, mock_user):
        """Service succeeds when S3 object doesn't exist (already deleted)."""
        from cms.assets.s3 import S3Error

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
                "cms.assets.s3.delete_agent",
                side_effect=S3Error("Object not found"),
            ),
        ):
            # Should not raise - object may have never been uploaded
            result = services.cancel_upload(mock_user, "token123")
            assert result is None

    # --- Error propagation ---

    def test_propagates_unexpected_exception(self, mock_user):
        """Service propagates unexpected exceptions from dependencies."""
        with (
            patch(
                "cms.assets.upload_token.verify_upload_token",
                side_effect=RuntimeError("Unexpected"),
            ),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            services.cancel_upload(mock_user, "token123")
