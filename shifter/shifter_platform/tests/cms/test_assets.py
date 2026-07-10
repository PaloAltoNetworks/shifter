"""Behavior tests for cms.assets.services.

Drives the real asset services against real ``AgentConfig`` / ``OperatingSystem``
/ ``AuditLog`` rows instead of patching ``AgentConfig`` / ``OperatingSystem`` /
``audit_log`` / ``s3_delete``. The delete path runs the real ``cms.assets.s3``
helper and the ``shared.cloud`` AWS adapter, mocked only at the ``boto3``
boundary (with ``AWS_S3_BUCKET_NAME`` set so the real "not configured" guard is
not tripped).
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model

from cms.assets.services import (
    AgentUploadSpec,
    AssetError,
    create_agent,
    delete_agent,
    get_storage_used,
)
from cms.models import AgentConfig, AgentType, OperatingSystem
from risk_register.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="assets@example.com", email="assets@example.com")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="assets-other@example.com", email="assets-other@example.com")


@pytest.fixture
def linux_os(db):
    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="linux-debian", defaults={"name": "Linux (Debian/Ubuntu)", "extensions": [".deb"]}
    )
    return os_obj


@pytest.fixture
def s3_client(settings):
    """Patch ``boto3.client`` at the boundary with a deterministic S3 client.

    Configures the bucket so the real s3 helper proceeds to the (mocked) AWS
    SDK call. Yields the boto3 client mock so tests can assert the call or
    drive a failure via ``side_effect``.
    """
    settings.AWS_S3_BUCKET_NAME = "test-bucket"
    client = MagicMock()
    with patch("boto3.client", return_value=client):
        yield client


def _spec(**overrides) -> AgentUploadSpec:
    fields = {
        "name": "New Agent",
        "s3_key": "agents/1/new.msi",
        "filename": "new.msi",
        "os_slug": "windows",
        "file_size": 2048,
        "sha256": "newhash123",
    }
    fields.update(overrides)
    return AgentUploadSpec(**fields)


# -----------------------------------------------------------------------------
# get_storage_used()
# -----------------------------------------------------------------------------


class TestGetStorageUsed:
    def test_returns_zero_for_no_agents(self, user):
        assert get_storage_used(user) == 0

    def test_returns_zero_for_user_with_no_agents_even_when_others_have(self, user, other_user, make_agent):
        make_agent(other_user, file_size_bytes=4096)
        assert get_storage_used(user) == 0

    def test_sums_active_agent_sizes(self, user, make_agent):
        make_agent(user, file_size_bytes=1024)
        make_agent(user, file_size_bytes=2048)
        assert get_storage_used(user) == 1024 + 2048

    def test_excludes_deleted_agents(self, user, make_agent):
        from django.utils import timezone

        make_agent(user, file_size_bytes=1024)
        deleted = make_agent(user, file_size_bytes=2048)
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at"])
        assert get_storage_used(user) == 1024

    def test_only_counts_own_agents(self, user, other_user, make_agent):
        make_agent(user, file_size_bytes=1024)
        make_agent(other_user, file_size_bytes=4096)
        assert get_storage_used(user) == 1024

    def test_returns_integer(self, user, make_agent):
        make_agent(user, file_size_bytes=1024)
        assert isinstance(get_storage_used(user), int)


# -----------------------------------------------------------------------------
# create_agent()
# -----------------------------------------------------------------------------


class TestCreateAgent:
    def test_creates_agent_record(self, user, windows_os):
        agent = create_agent(user, _spec(name="New Agent", os_slug="windows", file_size=2048, sha256="newhash123"))

        assert agent.pk is not None
        persisted = AgentConfig.objects.get(pk=agent.pk)
        assert persisted.user_id == user.id
        assert persisted.name == "New Agent"
        assert persisted.s3_key == "agents/1/new.msi"
        assert persisted.original_filename == "new.msi"
        assert persisted.os == windows_os
        assert persisted.file_size_bytes == 2048
        assert persisted.sha256_hash == "newhash123"
        assert persisted.deleted_at is None

    def test_creates_agent_record_with_linux_os(self, user, linux_os):
        agent = create_agent(user, _spec(name="Linux Agent", filename="linux.sh", os_slug="linux-debian"))
        assert agent.os == linux_os

    def test_logs_activity(self, user, windows_os):
        agent = create_agent(user, _spec(name="Logged Agent", filename="logged.msi"))

        row = AuditLog.objects.get(
            entity_type=AuditLog.EntityType.AGENT, entity_id=agent.id, action=AuditLog.Action.CREATE
        )
        assert row.new_state["name"] == "Logged Agent"
        assert row.new_state["filename"] == "logged.msi"
        assert row.actor_id == user.id

    def test_logs_upload_method_when_provided(self, user, windows_os):
        agent = create_agent(user, _spec(name="Presigned Agent", upload_method="presigned"))
        row = AuditLog.objects.get(
            entity_type=AuditLog.EntityType.AGENT, entity_id=agent.id, action=AuditLog.Action.CREATE
        )
        assert row.new_state["upload_method"] == "presigned"

    def test_raises_for_invalid_os_slug(self, user):
        with pytest.raises(AssetError, match="not found"):
            create_agent(user, _spec(os_slug="nonexistent-os"))

    def test_raises_for_invalid_agent_type(self, user, windows_os):
        with pytest.raises(AssetError, match="Invalid agent type"):
            create_agent(user, _spec(agent_type="bogus-type"))

    def test_no_record_persisted_on_invalid_os(self, user):
        with pytest.raises(AssetError):
            create_agent(user, _spec(name="Orphan", os_slug="nonexistent-os"))
        assert not AgentConfig.objects.filter(name="Orphan").exists()

    def test_returns_agent_object(self, user, windows_os):
        result = create_agent(user, _spec(name="Return Test"))
        assert isinstance(result, AgentConfig)
        assert result.agent_type == AgentType.XDR


# -----------------------------------------------------------------------------
# delete_agent()
# -----------------------------------------------------------------------------


class TestDeleteAgent:
    def test_soft_deletes_agent(self, user, make_agent, s3_client):
        agent = make_agent(user)
        delete_agent(agent)

        agent.refresh_from_db()
        assert agent.deleted_at is not None

    def test_does_not_hard_delete(self, user, make_agent, s3_client):
        agent = make_agent(user)
        delete_agent(agent)

        # Row still present (soft delete) but excluded from the active manager.
        assert AgentConfig.all_objects.filter(pk=agent.pk).exists()
        assert not AgentConfig.objects.filter(pk=agent.pk).exists()

    def test_calls_s3_delete_with_correct_key(self, user, make_agent, s3_client):
        agent = make_agent(user)
        delete_agent(agent)

        s3_client.delete_object.assert_called_once()
        kwargs = s3_client.delete_object.call_args.kwargs
        assert kwargs["Bucket"] == "test-bucket"
        assert kwargs["Key"] == agent.s3_key

    def test_logs_activity(self, user, make_agent, s3_client):
        agent = make_agent(user)
        delete_agent(agent)

        row = AuditLog.objects.get(
            entity_type=AuditLog.EntityType.AGENT, entity_id=agent.id, action=AuditLog.Action.DELETE
        )
        assert row.previous_state["name"] == agent.name
        assert row.actor_id == user.id

    def test_raises_if_s3_delete_fails(self, user, make_agent, s3_client):
        agent = make_agent(user)
        s3_client.delete_object.side_effect = ClientError({"Error": {"Code": "500", "Message": "boom"}}, "DeleteObject")
        with pytest.raises(AssetError, match="storage"):
            delete_agent(agent)

    def test_agent_not_soft_deleted_if_s3_fails(self, user, make_agent, s3_client):
        agent = make_agent(user)
        s3_client.delete_object.side_effect = ClientError({"Error": {"Code": "500", "Message": "boom"}}, "DeleteObject")
        with pytest.raises(AssetError):
            delete_agent(agent)

        agent.refresh_from_db()
        assert agent.deleted_at is None
        assert AgentConfig.objects.filter(pk=agent.pk).exists()


# -----------------------------------------------------------------------------
# AssetError
# -----------------------------------------------------------------------------


class TestAssetError:
    def test_is_exception(self):
        assert isinstance(AssetError("Test error"), Exception)

    def test_message_accessible_via_str(self):
        assert str(AssetError("Test message")) == "Test message"

    def test_can_be_raised_and_caught(self):
        with pytest.raises(AssetError):
            raise AssetError("Test")
