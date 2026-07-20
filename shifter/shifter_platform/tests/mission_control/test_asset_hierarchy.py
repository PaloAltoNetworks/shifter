"""Tests for the Asset/FileAsset abstract base classes.

Field presence, computed properties, and the inheritance chain are exercised on
in-memory ``AgentConfig`` instances (pure value logic). ``active_for_user`` is
exercised against the real database rather than mocking ``.objects.filter``.
"""

from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.models import AgentConfig, Asset, FileAsset, OperatingSystem

User = get_user_model()


def _make_os():
    return OperatingSystem(slug="windows", name="Windows", extensions=[".msi"])


def _make_user(**kwargs):
    defaults = {"id": 1, "username": "test@example.com", "email": "test@example.com"}
    defaults.update(kwargs)
    return User(**defaults)


def _make_agent(**overrides):
    defaults = {
        "id": 1,
        "user": _make_user(),
        "os": _make_os(),
        "name": "Test",
        "s3_key": "test/key.msi",
        "original_filename": "installer.msi",
        "file_size_bytes": 1024,
        "sha256_hash": "abc123",
        "deleted_at": None,
        "created_at": timezone.now(),
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestAssetAbstractBase:
    def test_asset_is_abstract(self):
        assert Asset._meta.abstract is True

    def test_has_name_field(self):
        assert _make_agent(name="Test Agent").name == "Test Agent"

    def test_has_created_at(self):
        agent = _make_agent(created_at=timezone.now())
        assert agent.created_at is not None
        assert (timezone.now() - agent.created_at).total_seconds() < 60

    def test_has_deleted_at_nullable(self):
        assert _make_agent(deleted_at=None).deleted_at is None

    def test_is_deleted_false_by_default(self):
        assert _make_agent(deleted_at=None).is_deleted is False

    def test_is_deleted_true_when_set(self):
        agent = _make_agent()
        agent.deleted_at = timezone.now()
        assert agent.is_deleted is True

    def test_active_for_user_excludes_deleted_and_other_users(self, db, make_agent, django_user_model):
        owner = django_user_model.objects.create_user(username="ah-owner@example.com", email="ah-owner@example.com")
        other = django_user_model.objects.create_user(username="ah-other@example.com", email="ah-other@example.com")
        active = make_agent(owner, name="Active")
        deleted = make_agent(owner, name="Deleted")
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at"])
        make_agent(other, name="Other")

        result = list(AgentConfig.active_for_user(owner))
        assert result == [active]


class TestFileAssetAbstractBase:
    def test_file_asset_is_abstract(self):
        assert FileAsset._meta.abstract is True

    def test_has_s3_key_field(self):
        assert _make_agent(s3_key="users/123/agents/installer.msi").s3_key == "users/123/agents/installer.msi"

    def test_has_original_filename_field(self):
        assert _make_agent(original_filename="XDR_Agent_7.5.1.msi").original_filename == "XDR_Agent_7.5.1.msi"

    def test_has_file_size_bytes_field(self):
        assert _make_agent(file_size_bytes=104857600).file_size_bytes == 104857600

    def test_has_sha256_hash_field(self):
        hash_value = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert _make_agent(sha256_hash=hash_value).sha256_hash == hash_value

    def test_file_size_mb_property(self):
        assert _make_agent(file_size_bytes=104857600).file_size_mb == 100.0

    def test_file_size_mb_rounds_correctly(self):
        assert _make_agent(file_size_bytes=54893568).file_size_mb == 52.4


class TestAgentConfigInheritsCorrectly:
    def test_subclass_of_file_asset(self):
        assert issubclass(AgentConfig, FileAsset)

    def test_subclass_of_asset(self):
        assert issubclass(AgentConfig, Asset)

    def test_has_os_field(self):
        os_obj = _make_os()
        agent = _make_agent(os=os_obj)
        assert agent.os == os_obj
        assert agent.os.name == "Windows"

    def test_user_related_name(self):
        field = AgentConfig._meta.get_field("user")
        assert field.remote_field.related_name == "cms_agents"

    def test_str_includes_name_and_os(self):
        assert str(_make_agent(name="My XDR Agent")) == "My XDR Agent (Windows)"

    def test_ordering_by_created_at_desc(self):
        assert AgentConfig._meta.ordering == ["-created_at"]
