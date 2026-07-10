"""Behavior tests for cms.services.cancel_upload.

Drives the real cancel service against a real user and a real signed upload
token (round-tripped through ``generate_upload_token`` / ``verify_upload_token``),
with the best-effort S3 delete running through the real ``cms.assets.s3`` helper
and ``shared.cloud`` AWS adapter mocked only at the ``boto3`` boundary, instead
of patching ``verify_upload_token`` / ``delete_agent``.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from freezegun import freeze_time

from cms import services
from cms.assets.upload_token import generate_upload_token
from cms.exceptions import CMSError
from shared.constants import USER_CANNOT_BE_NONE

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cancel@example.com", email="cancel@example.com")


@pytest.fixture
def s3_delete(settings):
    """Patch ``boto3.client`` at the boundary; configure bucket + token expiry."""
    settings.AWS_S3_BUCKET_NAME = "test-bucket"
    settings.AGENT_UPLOAD_URL_EXPIRES = 900
    client = MagicMock()
    with patch("boto3.client", return_value=client):
        yield client


def _token(
    user, *, s3_key="agents/1/abc_agent.msi", name="Agent", filename="agent.msi", os_slug="windows", file_size=1000
):
    return generate_upload_token(
        user_id=user.id, s3_key=s3_key, name=name, filename=filename, os_slug=os_slug, file_size=file_size
    )


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "DeleteObject")


class TestCancelUpload:
    def test_returns_none_and_deletes_object(self, user, s3_delete):
        s3_key = f"agents/{user.id}/abc_agent.msi"
        result = services.cancel_upload(user, _token(user, s3_key=s3_key))

        assert result is None
        s3_delete.delete_object.assert_called_once()
        kwargs = s3_delete.delete_object.call_args.kwargs
        assert kwargs["Bucket"] == "test-bucket"
        assert kwargs["Key"] == s3_key


class TestCancelUploadUserValidation:
    def test_raises_typeerror_when_user_is_none(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.cancel_upload(None, "token123")

    def test_raises_typeerror_when_user_is_wrong_type(self):
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.cancel_upload("not a user", "token123")

    def test_raises_valueerror_when_user_is_unsaved(self):
        with pytest.raises(ValueError, match="user must be saved"):
            services.cancel_upload(User(username="unsaved"), "token123")


class TestCancelUploadTokenValidation:
    @pytest.mark.parametrize(
        "token,err", [(None, "cannot be None"), ("", "cannot be empty"), ("   ", "cannot be empty")]
    )
    def test_rejects_bad_token(self, user, token, err):
        with pytest.raises(ValueError, match=f"upload_token {err}"):
            services.cancel_upload(user, token)

    def test_raises_cmserror_on_invalid_token(self, user):
        with pytest.raises(CMSError, match="Invalid upload token"):
            services.cancel_upload(user, "not-a-valid-token")

    def test_raises_cmserror_on_expired_token(self, user, settings):
        settings.AGENT_UPLOAD_URL_EXPIRES = 60
        with freeze_time("2024-06-01T12:00:00Z") as frozen:
            token = _token(user)
            frozen.tick(timedelta(seconds=61))
            with pytest.raises(CMSError, match="Invalid upload token"):
                services.cancel_upload(user, token)


class TestCancelUploadBestEffortDelete:
    def test_succeeds_when_s3_delete_fails(self, user, s3_delete):
        s3_delete.delete_object.side_effect = _client_error("500")
        assert services.cancel_upload(user, _token(user)) is None

    def test_succeeds_when_s3_object_not_found(self, user, s3_delete):
        s3_delete.delete_object.side_effect = _client_error("404")
        assert services.cancel_upload(user, _token(user)) is None
