"""Behavior tests for cms.services.initiate_upload.

Drives the real upload-initiation service against a real user and the real
quota / extension-validation / presigned-URL / upload-token stack. The presigned
URL is generated through the real ``cms.assets.s3`` helper and ``shared.cloud``
AWS adapter, mocked only at the ``boto3`` boundary; the issued upload token is
asserted by verifying it for real (proving the token carries the right payload),
instead of patching ``get_storage_used`` / ``validate_file_extension`` /
``generate_presigned_upload_url`` / ``generate_upload_token``.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model

from cms import services
from cms.assets.upload_token import verify_upload_token
from cms.exceptions import CMSError
from shared.constants import USER_CANNOT_BE_NONE

pytestmark = pytest.mark.django_db

User = get_user_model()

_MB = 1024 * 1024


@pytest.fixture
def user(db):
    return User.objects.create_user(username="upload@example.com", email="upload@example.com")


@pytest.fixture
def s3_presign(settings):
    """Patch ``boto3.client`` with a deterministic presigned-URL S3 client."""
    settings.AWS_S3_BUCKET_NAME = "test-bucket"
    settings.AGENT_UPLOAD_URL_EXPIRES = 900
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://s3.example/presigned"
    with patch("boto3.client", return_value=client):
        yield client


class TestInitiateUploadReturns:
    def test_returns_presigned_url_and_s3_key(self, user, s3_presign):
        result = services.initiate_upload(user, "Agent", "agent.msi", 1000)
        assert result["presigned_url"] == "https://s3.example/presigned"
        assert result["s3_key"].startswith(f"agents/{user.id}/")
        assert result["s3_key"].endswith("_agent.msi")

    def test_returns_verifiable_upload_token_with_payload(self, user, s3_presign):
        result = services.initiate_upload(user, "My Agent", "agent.msi", 5000)

        payload = verify_upload_token(result["upload_token"], user.id)
        assert payload["name"] == "My Agent"
        assert payload["filename"] == "agent.msi"
        assert payload["os_slug"] == "windows"
        assert payload["file_size"] == 5000
        assert payload["agent_type"] == "xdr"
        assert payload["s3_key"] == result["s3_key"]

    def test_expected_os_comes_from_extension(self, user, s3_presign):
        result = services.initiate_upload(user, "Agent", "agent.deb", 1000)
        assert result["expected_os"] == "linux-debian"

    def test_agent_type_is_carried_into_token(self, user, s3_presign):
        result = services.initiate_upload(user, "Agent", "agent.msi", 1000, agent_type="xdr_collector")
        payload = verify_upload_token(result["upload_token"], user.id)
        assert payload["agent_type"] == "xdr_collector"


class TestInitiateUploadUserValidation:
    def test_raises_typeerror_when_user_is_none(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.initiate_upload(None, "Agent", "agent.msi", 1000)

    def test_raises_typeerror_when_user_is_wrong_type(self):
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.initiate_upload("not a user", "Agent", "agent.msi", 1000)

    def test_raises_valueerror_when_user_is_unsaved(self):
        with pytest.raises(ValueError, match="user must be saved"):
            services.initiate_upload(User(username="unsaved"), "Agent", "agent.msi", 1000)


class TestInitiateUploadInputValidation:
    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_rejects_bad_name(self, user, name):
        with pytest.raises(ValueError, match="name cannot be"):
            services.initiate_upload(user, name, "agent.msi", 1000)

    @pytest.mark.parametrize("filename", [None, "", "   "])
    def test_rejects_bad_filename(self, user, filename):
        with pytest.raises(ValueError, match="filename cannot be"):
            services.initiate_upload(user, "Agent", filename, 1000)

    def test_rejects_none_file_size(self, user):
        with pytest.raises(TypeError, match="file_size cannot be None"):
            services.initiate_upload(user, "Agent", "agent.msi", None)

    def test_rejects_non_int_file_size(self, user):
        with pytest.raises(TypeError, match="file_size must be an int"):
            services.initiate_upload(user, "Agent", "agent.msi", "1000")

    @pytest.mark.parametrize("size", [0, -100])
    def test_rejects_non_positive_file_size(self, user, size):
        with pytest.raises(ValueError, match="file_size must be positive"):
            services.initiate_upload(user, "Agent", "agent.msi", size)


class TestInitiateUploadQuota:
    def test_raises_when_quota_exceeded(self, user, make_agent, settings):
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10
        make_agent(user, file_size_bytes=9 * _MB)
        with pytest.raises(CMSError, match="quota exceeded"):
            services.initiate_upload(user, "Agent", "agent.msi", 2 * _MB)

    def test_succeeds_when_under_quota(self, user, make_agent, settings, s3_presign):
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10
        make_agent(user, file_size_bytes=5 * _MB)
        result = services.initiate_upload(user, "Agent", "agent.msi", 4 * _MB)
        assert "presigned_url" in result

    def test_succeeds_when_quota_exactly_met(self, user, make_agent, settings, s3_presign):
        settings.AGENT_USER_STORAGE_QUOTA_MB = 10
        make_agent(user, file_size_bytes=5 * _MB)
        result = services.initiate_upload(user, "Agent", "agent.msi", 5 * _MB)
        assert "presigned_url" in result


class TestInitiateUploadFailures:
    def test_raises_on_invalid_extension(self, user):
        with pytest.raises(CMSError, match="not allowed"):
            services.initiate_upload(user, "Agent", "agent.exe", 1000)

    def test_raises_when_presign_fails(self, user, s3_presign):
        s3_presign.generate_presigned_url.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "boom"}}, "PutObject"
        )
        with pytest.raises(CMSError, match="Failed to initiate upload"):
            services.initiate_upload(user, "Agent", "agent.msi", 1000)
