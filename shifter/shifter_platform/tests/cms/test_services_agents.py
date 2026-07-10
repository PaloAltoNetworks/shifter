"""Behavior tests for the cms.services agent entrypoints.

Drives ``list_agents`` / ``get_agent`` / ``create_agent`` / ``delete_agent``
against real ``AgentConfig`` / ``OperatingSystem`` / ``AuditLog`` rows (delete
runs the real S3 helper through the ``shared.cloud`` AWS adapter, mocked at the
``boto3`` boundary), instead of patching ``AgentConfig.objects`` /
``active_for_user`` / ``get_agent`` / ``assets_create_agent`` /
``assets_delete_agent``.

Impossible-state defensive tests from the old mock-coupled suite (model returns
None / a non-AgentConfig / a list of dicts; "unexpected" DB exceptions) are
dropped: the real ORM cannot produce those returns, and the generic re-raise
path is not domain behavior.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms import services
from cms.assets.services import AssetError
from cms.exceptions import CMSError
from cms.models import AgentConfig

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="svc-agents@example.com", email="svc-agents@example.com")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="svc-agents-other@example.com", email="svc-agents-other@example.com")


@pytest.fixture
def s3_client(settings):
    """Patch ``boto3.client`` at the boundary so the real delete helper proceeds."""
    settings.AWS_S3_BUCKET_NAME = "test-bucket"
    client = MagicMock()
    with patch("boto3.client", return_value=client):
        yield client


class TestListAgents:
    def test_returns_empty_when_no_agents(self, user):
        assert services.list_agents(user) == []

    def test_returns_projection_dicts(self, user, make_agent, windows_os):
        make_agent(user, name="Agent A", file_size_bytes=10 * 1024 * 1024)
        result = services.list_agents(user)

        assert len(result) == 1
        row = result[0]
        assert row["name"] == "Agent A"
        assert row["os_slug"] == "windows"
        assert row["os_name"] == windows_os.name
        assert row["original_filename"] == "agent.msi"
        assert isinstance(row["file_size_mb"], (int, float))
        assert row["created_at"] is not None

    def test_excludes_other_users_agents(self, user, other_user, make_agent):
        make_agent(user, name="Mine")
        make_agent(other_user, name="Theirs")
        assert [r["name"] for r in services.list_agents(user)] == ["Mine"]

    def test_excludes_soft_deleted_agents(self, user, make_agent):
        make_agent(user, name="Active")
        deleted = make_agent(user, name="Gone")
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at"])
        assert [r["name"] for r in services.list_agents(user)] == ["Active"]

    def test_raises_on_invalid_user(self):
        with pytest.raises((TypeError, ValueError)):
            services.list_agents(None)
        with pytest.raises((TypeError, ValueError)):
            services.list_agents(User(username="unsaved"))


class TestGetAgent:
    def test_returns_agent_when_found_and_owned(self, user, make_agent):
        agent = make_agent(user, name="Mine")
        result = services.get_agent(user, agent.id)
        assert result.pk == agent.pk
        assert result.name == "Mine"

    def test_raises_when_agent_not_found(self, user):
        with pytest.raises(CMSError):
            services.get_agent(user, 999999)

    def test_raises_when_owned_by_other_user(self, user, other_user, make_agent):
        agent = make_agent(other_user)
        with pytest.raises(CMSError):
            services.get_agent(user, agent.id)

    def test_raises_when_agent_is_soft_deleted(self, user, make_agent):
        agent = make_agent(user)
        agent.deleted_at = timezone.now()
        agent.save(update_fields=["deleted_at"])
        with pytest.raises(CMSError):
            services.get_agent(user, agent.id)

    def test_validates_user(self):
        with pytest.raises((TypeError, ValueError)):
            services.get_agent(None, 42)
        with pytest.raises((TypeError, ValueError)):
            services.get_agent(User(username="unsaved"), 42)

    @pytest.mark.parametrize("agent_id", [None, "not-an-id", -1])
    def test_validates_agent_id(self, user, agent_id):
        with pytest.raises((TypeError, ValueError)):
            services.get_agent(user, agent_id)


class TestCreateAgent:
    def test_creates_and_returns_persisted_agent(self, user, windows_os):
        agent = services.create_agent(
            user,
            name="Created",
            s3_key="agents/test/created.msi",
            filename="created.msi",
            os_slug="windows",
            file_size=1000,
            sha256="abc123",
        )
        assert isinstance(agent, AgentConfig)
        persisted = AgentConfig.objects.get(pk=agent.pk)
        assert persisted.name == "Created"
        assert persisted.os == windows_os
        assert persisted.user_id == user.id

    def test_passes_upload_method_through(self, user, windows_os):
        from risk_register.models import AuditLog

        agent = services.create_agent(
            user,
            name="Created",
            s3_key="agents/test/created.msi",
            filename="created.msi",
            os_slug="windows",
            file_size=1000,
            sha256="abc123",
            upload_method="presigned",
        )
        row = AuditLog.objects.get(
            entity_type=AuditLog.EntityType.AGENT, entity_id=agent.id, action=AuditLog.Action.CREATE
        )
        assert row.new_state["upload_method"] == "presigned"

    def test_propagates_asset_error_on_invalid_os(self, user):
        with pytest.raises(AssetError, match="not found"):
            services.create_agent(
                user,
                name="Bad OS",
                s3_key="agents/test/bad.msi",
                filename="bad.msi",
                os_slug="nonexistent-os",
                file_size=1000,
                sha256="abc123",
            )

    def test_validates_user(self):
        kwargs = {
            "name": "Test",
            "s3_key": "agents/test/agent.msi",
            "filename": "agent.msi",
            "os_slug": "windows",
            "file_size": 1000,
            "sha256": "abc123",
        }
        with pytest.raises((TypeError, ValueError)):
            services.create_agent(None, **kwargs)
        with pytest.raises((TypeError, ValueError)):
            services.create_agent(User(username="unsaved"), **kwargs)


class TestDeleteAgent:
    def test_soft_deletes_owned_agent(self, user, make_agent, s3_client):
        agent = make_agent(user)
        assert services.delete_agent(user, agent.id) is None

        agent.refresh_from_db()
        assert agent.deleted_at is not None

    def test_raises_when_agent_not_found(self, user):
        with pytest.raises(CMSError):
            services.delete_agent(user, 999999)

    def test_raises_when_not_owner(self, user, other_user, make_agent):
        agent = make_agent(other_user)
        with pytest.raises(CMSError):
            services.delete_agent(user, agent.id)

    def test_propagates_asset_error_when_s3_fails(self, user, make_agent, s3_client):
        agent = make_agent(user)
        s3_client.delete_object.side_effect = ClientError({"Error": {"Code": "500", "Message": "boom"}}, "DeleteObject")
        with pytest.raises(AssetError):
            services.delete_agent(user, agent.id)

        agent.refresh_from_db()
        assert agent.deleted_at is None

    def test_validates_user(self):
        with pytest.raises((TypeError, ValueError)):
            services.delete_agent(None, 42)
        with pytest.raises((TypeError, ValueError)):
            services.delete_agent(User(username="unsaved"), 42)

    @pytest.mark.parametrize("agent_id", [None, "not-an-id", -1])
    def test_validates_agent_id(self, user, agent_id):
        with pytest.raises((TypeError, ValueError)):
            services.delete_agent(user, agent_id)
