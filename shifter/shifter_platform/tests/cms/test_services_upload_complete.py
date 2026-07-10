"""Behavior tests for cms.services.complete_upload.

Drives the real completion service against a real user, a real signed upload
token, and the full verify -> header-inspect -> tag -> create_agent stack. S3 is
exercised through the real ``cms.assets.s3`` helper and ``shared.cloud`` AWS
adapter, mocked only at the ``boto3`` boundary; the created agent is asserted
against the persisted ``AgentConfig`` / ``AuditLog`` rows, instead of patching
``verify_upload_token`` / ``verify_s3_object_exists`` / ``read_agent_header`` /
``tag_s3_object`` / ``create_agent``.
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
from cms.models import AgentConfig
from risk_register.models import AuditLog
from shared.constants import USER_CANNOT_BE_NONE

pytestmark = pytest.mark.django_db

User = get_user_model()

# MSI / OLE compound-document magic so header inspection passes for `.msi` tokens.
_MSI_HEADER = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1]) + b"\x00" * 16
# ZIP magic — a mismatch for a `.msi` declared format.
_ZIP_HEADER = b"\x50\x4b\x03\x04" + b"\x00" * 16


@pytest.fixture
def user(db):
    return User.objects.create_user(username="complete@example.com", email="complete@example.com")


@pytest.fixture
def s3_complete(settings):
    """Patch ``boto3.client`` with an S3 client whose head/get/tag/delete succeed.

    Defaults: object is 1000 bytes (matches the default token), and the header
    is valid MSI magic. Tests override per-operation via the returned mock.
    """
    settings.AWS_S3_BUCKET_NAME = "test-bucket"
    settings.AGENT_UPLOAD_URL_EXPIRES = 900
    client = MagicMock()
    client.head_object.return_value = {"ContentLength": 1000, "ETag": '"etag"'}
    body = MagicMock()
    body.read.return_value = _MSI_HEADER
    client.get_object.return_value = {"Body": body}
    with patch("boto3.client", return_value=client):
        yield client


def _token(
    user, *, s3_key=None, name="Agent", filename="agent.msi", os_slug="windows", file_size=1000, agent_type="xdr"
):
    return generate_upload_token(
        user_id=user.id,
        s3_key=s3_key or f"agents/{user.id}/abc_agent.msi",
        name=name,
        filename=filename,
        os_slug=os_slug,
        file_size=file_size,
        agent_type=agent_type,
    )


class TestCompleteUploadSuccess:
    def test_creates_and_returns_persisted_agent(self, user, windows_os, s3_complete):
        staging_key = f"agents/{user.id}/abc_agent.msi"
        agent = services.complete_upload(user, _token(user, s3_key=staging_key, name="My Agent", file_size=1000))

        assert isinstance(agent, AgentConfig)
        persisted = AgentConfig.objects.get(pk=agent.pk)
        assert persisted.name == "My Agent"
        assert persisted.os == windows_os
        # Persist the immutable install key, never the mutable staging key (#1181).
        install_key = s3_complete.copy_object.call_args.kwargs["Key"]
        assert persisted.s3_key == install_key
        assert persisted.s3_key != staging_key
        assert persisted.file_size_bytes == 1000
        assert persisted.user_id == user.id

    def test_audit_records_presigned_upload_method(self, user, windows_os, s3_complete):
        agent = services.complete_upload(user, _token(user))
        row = AuditLog.objects.get(
            entity_type=AuditLog.EntityType.AGENT, entity_id=agent.id, action=AuditLog.Action.CREATE
        )
        assert row.new_state["upload_method"] == "presigned"

    def test_tags_install_key_completed_not_staging_key(self, user, windows_os, s3_complete):
        staging_key = f"agents/{user.id}/abc_agent.msi"
        services.complete_upload(user, _token(user, s3_key=staging_key))

        # HEAD/validation runs against the staging key; the completed tag lands on
        # the immutable install key (the copy destination), not the staging key.
        assert s3_complete.head_object.call_args.kwargs["Key"] == staging_key
        install_key = s3_complete.copy_object.call_args.kwargs["Key"]
        tag_kwargs = s3_complete.put_object_tagging.call_args.kwargs
        assert tag_kwargs["Key"] == install_key
        assert tag_kwargs["Key"] != staging_key
        assert tag_kwargs["Tagging"] == {"TagSet": [{"Key": "status", "Value": "completed"}]}


def _precondition_client_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}},
        "CopyObject",
    )


class TestCompleteUploadImmutableFinalization:
    """Issue #1181: the installed bytes must be the bytes CMS validated."""

    def test_changed_object_between_validation_and_install_is_rejected(self, user, windows_os, s3_complete):
        # Object passes size + header validation, but the conditional install copy
        # fails its source precondition — the validated bytes changed (or the
        # presigned PUT overwrote them) between check and use.
        s3_complete.copy_object.side_effect = _precondition_client_error()

        with pytest.raises(CMSError):
            services.complete_upload(user, _token(user))

        s3_complete.put_object_tagging.assert_not_called()
        assert AgentConfig.objects.count() == 0

    def test_conditional_copy_binds_to_validated_identity_and_fresh_destination(self, user, windows_os, s3_complete):
        staging_key = f"agents/{user.id}/abc_agent.msi"
        services.complete_upload(user, _token(user, s3_key=staging_key))

        copy_kwargs = s3_complete.copy_object.call_args.kwargs
        assert copy_kwargs["CopySource"] == {"Bucket": "test-bucket", "Key": staging_key}
        assert copy_kwargs["CopySourceIfMatch"] == "etag"  # the ETag captured at HEAD
        assert copy_kwargs["Key"].startswith(f"agents/{user.id}/installed/")

    def test_staging_object_is_cleaned_up_after_successful_install(self, user, windows_os, s3_complete):
        staging_key = f"agents/{user.id}/abc_agent.msi"
        services.complete_upload(user, _token(user, s3_key=staging_key))

        deleted_keys = [call.kwargs["Key"] for call in s3_complete.delete_object.call_args_list]
        assert staging_key in deleted_keys

    def test_staging_cleanup_failure_does_not_fail_completion(self, user, windows_os, s3_complete):
        s3_complete.delete_object.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "boom"}}, "DeleteObject"
        )
        agent = services.complete_upload(user, _token(user))
        assert AgentConfig.objects.filter(pk=agent.pk).exists()


class TestCompleteUploadUserAndTokenValidation:
    def test_raises_typeerror_when_user_is_none(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.complete_upload(None, "token123")

    def test_raises_typeerror_when_user_is_wrong_type(self):
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.complete_upload("not a user", "token123")

    def test_raises_valueerror_when_user_is_unsaved(self):
        with pytest.raises(ValueError, match="user must be saved"):
            services.complete_upload(User(username="unsaved"), "token123")

    @pytest.mark.parametrize(
        "token,err", [(None, "cannot be None"), ("", "cannot be empty"), ("   ", "cannot be empty")]
    )
    def test_rejects_bad_token(self, user, token, err):
        with pytest.raises(ValueError, match=f"upload_token {err}"):
            services.complete_upload(user, token)

    def test_raises_cmserror_on_invalid_token(self, user):
        with pytest.raises(CMSError, match="Invalid upload token"):
            services.complete_upload(user, "not-a-valid-token")

    def test_raises_cmserror_on_expired_token(self, user, settings):
        settings.AGENT_UPLOAD_URL_EXPIRES = 60
        with freeze_time("2024-06-01T12:00:00Z") as frozen:
            token = _token(user)
            frozen.tick(timedelta(seconds=61))
            with pytest.raises(CMSError, match="Invalid upload token"):
                services.complete_upload(user, token)


class TestCompleteUploadObjectValidation:
    def test_raises_when_s3_object_not_found(self, user, s3_complete):
        s3_complete.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )
        with pytest.raises(CMSError, match="Upload not found"):
            services.complete_upload(user, _token(user))

    def test_raises_on_file_size_mismatch(self, user, s3_complete):
        s3_complete.head_object.return_value = {"ContentLength": 5000, "ETag": '"etag"'}
        with pytest.raises(CMSError, match="size mismatch"):
            services.complete_upload(user, _token(user, file_size=1000))


class TestCompleteUploadHeaderInspection:
    def test_magic_byte_mismatch_deletes_object_and_aborts(self, user, s3_complete):
        s3_complete.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=_ZIP_HEADER))}
        s3_key = f"agents/{user.id}/abc_agent.msi"

        with pytest.raises(CMSError, match="content"):
            services.complete_upload(user, _token(user, s3_key=s3_key, filename="agent.msi"))

        s3_complete.delete_object.assert_called_once()
        assert s3_complete.delete_object.call_args.kwargs["Key"] == s3_key
        s3_complete.put_object_tagging.assert_not_called()
        assert AgentConfig.objects.count() == 0

    def test_header_read_failure_raises_and_does_not_finalize(self, user, s3_complete):
        s3_complete.get_object.side_effect = ClientError({"Error": {"Code": "500", "Message": "boom"}}, "GetObject")

        with pytest.raises(CMSError, match="inspection"):
            services.complete_upload(user, _token(user))

        s3_complete.put_object_tagging.assert_not_called()
        assert AgentConfig.objects.count() == 0

    def test_rejection_log_does_not_leak_header_bytes(self, user, s3_complete, caplog):
        leak = b"\x50\x4b\x03\x04S3CR3T-DO-NOT-LEAK"
        s3_complete.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=leak))}

        with caplog.at_level("WARNING", logger="cms.services"), pytest.raises(CMSError):
            services.complete_upload(user, _token(user, filename="agent.msi"))

        combined = " ".join(record.getMessage() for record in caplog.records)
        assert "S3CR3T-DO-NOT-LEAK" not in combined
