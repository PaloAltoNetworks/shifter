"""Tests for CMS abstract base models: Asset, FileAsset, CredentialBase.

These tests verify the abstract model hierarchy provides:
- Asset: Common fields (name, timestamps) and soft delete
- FileAsset: S3 file storage fields and computed properties
- CredentialBase: Expiration tracking for credential assets

Since abstract models cannot be instantiated directly, we test through
concrete test models or verify the class structure directly.
"""

import pytest
from django.db import models
from django.utils import timezone

# -----------------------------------------------------------------------------
# Test Asset Abstract Model
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssetAbstractModel:
    """Tests for Asset abstract base class."""

    def test_asset_can_be_imported_from_cms(self):
        """Asset should be importable from cms.models."""
        from cms.models import Asset

        assert Asset is not None

    def test_asset_is_abstract(self):
        """Asset model class should be abstract."""
        from cms.models import Asset

        assert Asset._meta.abstract is True

    def test_asset_has_name_field(self):
        """Asset should have a name CharField."""
        from cms.models import Asset

        field = Asset._meta.get_field("name")
        assert isinstance(field, models.CharField)
        assert field.max_length == 100

    def test_asset_has_created_at_field(self):
        """Asset should have a created_at DateTimeField with auto_now_add."""
        from cms.models import Asset

        field = Asset._meta.get_field("created_at")
        assert isinstance(field, models.DateTimeField)
        assert field.auto_now_add is True

    def test_asset_has_deleted_at_field(self):
        """Asset should have a deleted_at DateTimeField that is nullable."""
        from cms.models import Asset

        field = Asset._meta.get_field("deleted_at")
        assert isinstance(field, models.DateTimeField)
        assert field.null is True
        assert field.blank is True

    def test_asset_has_is_deleted_property(self):
        """Asset should have an is_deleted property."""
        from cms.models import Asset

        assert hasattr(Asset, "is_deleted")

    def test_asset_has_active_for_user_classmethod(self):
        """Asset should have an active_for_user classmethod."""
        from cms.models import Asset

        assert hasattr(Asset, "active_for_user")
        assert callable(Asset.active_for_user)


# -----------------------------------------------------------------------------
# Test FileAsset Abstract Model
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestFileAssetAbstractModel:
    """Tests for FileAsset abstract base class."""

    def test_file_asset_can_be_imported_from_cms(self):
        """FileAsset should be importable from cms.models."""
        from cms.models import FileAsset

        assert FileAsset is not None

    def test_file_asset_is_abstract(self):
        """FileAsset model class should be abstract."""
        from cms.models import FileAsset

        assert FileAsset._meta.abstract is True

    def test_file_asset_inherits_from_asset(self):
        """FileAsset should inherit from Asset."""
        from cms.models import Asset, FileAsset

        assert issubclass(FileAsset, Asset)

    def test_file_asset_has_s3_key_field(self):
        """FileAsset should have an s3_key CharField."""
        from cms.models import FileAsset

        field = FileAsset._meta.get_field("s3_key")
        assert isinstance(field, models.CharField)
        assert field.max_length == 500

    def test_file_asset_has_original_filename_field(self):
        """FileAsset should have an original_filename CharField."""
        from cms.models import FileAsset

        field = FileAsset._meta.get_field("original_filename")
        assert isinstance(field, models.CharField)
        assert field.max_length == 255

    def test_file_asset_has_file_size_bytes_field(self):
        """FileAsset should have a file_size_bytes PositiveBigIntegerField."""
        from cms.models import FileAsset

        field = FileAsset._meta.get_field("file_size_bytes")
        assert isinstance(field, models.PositiveBigIntegerField)

    def test_file_asset_has_sha256_hash_field(self):
        """FileAsset should have a sha256_hash CharField."""
        from cms.models import FileAsset

        field = FileAsset._meta.get_field("sha256_hash")
        assert isinstance(field, models.CharField)
        assert field.max_length == 64

    def test_file_asset_has_file_size_mb_property(self):
        """FileAsset should have a file_size_mb property."""
        from cms.models import FileAsset

        assert hasattr(FileAsset, "file_size_mb")


# -----------------------------------------------------------------------------
# Test CredentialBase Abstract Model
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialBaseAbstractModel:
    """Tests for CredentialBase abstract base class (credential with expiration)."""

    def test_credential_base_can_be_imported_from_cms(self):
        """CredentialBase should be importable from cms.models."""
        from cms.models import CredentialBase

        assert CredentialBase is not None

    def test_credential_base_is_abstract(self):
        """CredentialBase model class should be abstract."""
        from cms.models import CredentialBase

        assert CredentialBase._meta.abstract is True

    def test_credential_base_inherits_from_asset(self):
        """CredentialBase should inherit from Asset."""
        from cms.models import Asset, CredentialBase

        assert issubclass(CredentialBase, Asset)

    def test_credential_base_has_expires_at_field(self):
        """CredentialBase should have an expires_at DateTimeField."""
        from cms.models import CredentialBase

        field = CredentialBase._meta.get_field("expires_at")
        assert isinstance(field, models.DateTimeField)
        assert field.null is True
        assert field.blank is True

    def test_credential_base_has_last_verified_at_field(self):
        """CredentialBase should have a last_verified_at DateTimeField."""
        from cms.models import CredentialBase

        field = CredentialBase._meta.get_field("last_verified_at")
        assert isinstance(field, models.DateTimeField)
        assert field.null is True
        assert field.blank is True

    def test_credential_base_has_last_used_at_field(self):
        """CredentialBase should have a last_used_at DateTimeField."""
        from cms.models import CredentialBase

        field = CredentialBase._meta.get_field("last_used_at")
        assert isinstance(field, models.DateTimeField)
        assert field.null is True
        assert field.blank is True

    def test_credential_base_has_is_expired_property(self):
        """CredentialBase should have an is_expired property."""
        from cms.models import CredentialBase

        assert hasattr(CredentialBase, "is_expired")


# -----------------------------------------------------------------------------
# Test Asset Behavior Through Concrete Model
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssetBehavior:
    """Tests for Asset behavior through a concrete implementation.

    Uses cms.AgentConfig as the concrete model since it inherits from
    FileAsset which inherits from Asset.
    """

    @pytest.fixture
    def user(self):
        """Create a test user."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def operating_system(self):
        """Create an operating system for agents."""
        from cms.models import OperatingSystem

        os, _ = OperatingSystem.objects.get_or_create(
            slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
        )
        return os

    def test_is_deleted_returns_false_when_deleted_at_is_none(self, user, operating_system):
        """is_deleted should return False when deleted_at is None."""
        from cms.models import AgentConfig

        agent = AgentConfig.objects.create(
            user=user,
            name="Test Agent",
            os=operating_system,
            s3_key="agents/test.msi",
            original_filename="test.msi",
            file_size_bytes=1024,
        )

        assert agent.is_deleted is False

    def test_is_deleted_returns_true_when_deleted_at_is_set(self, user, operating_system):
        """is_deleted should return True when deleted_at is set."""
        from cms.models import AgentConfig

        agent = AgentConfig.objects.create(
            user=user,
            name="Test Agent",
            os=operating_system,
            s3_key="agents/test.msi",
            original_filename="test.msi",
            file_size_bytes=1024,
            deleted_at=timezone.now(),
        )

        assert agent.is_deleted is True

    def test_active_for_user_excludes_deleted_records(self, user, operating_system):
        """active_for_user should exclude soft-deleted records."""
        from cms.models import AgentConfig

        active = AgentConfig.objects.create(
            user=user,
            name="Active Agent",
            os=operating_system,
            s3_key="agents/active.msi",
            original_filename="active.msi",
            file_size_bytes=1024,
        )
        AgentConfig.objects.create(
            user=user,
            name="Deleted Agent",
            os=operating_system,
            s3_key="agents/deleted.msi",
            original_filename="deleted.msi",
            file_size_bytes=1024,
            deleted_at=timezone.now(),
        )

        result = list(AgentConfig.active_for_user(user))

        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_filters_by_user(self, user, operating_system):
        """active_for_user should only return records for the specified user."""
        from django.contrib.auth import get_user_model

        from cms.models import AgentConfig

        User = get_user_model()
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")

        AgentConfig.objects.create(
            user=user,
            name="User Agent",
            os=operating_system,
            s3_key="agents/user.msi",
            original_filename="user.msi",
            file_size_bytes=1024,
        )
        AgentConfig.objects.create(
            user=other_user,
            name="Other Agent",
            os=operating_system,
            s3_key="agents/other.msi",
            original_filename="other.msi",
            file_size_bytes=1024,
        )

        result = list(AgentConfig.active_for_user(user))

        assert len(result) == 1
        assert result[0].name == "User Agent"


# -----------------------------------------------------------------------------
# Test Credential Properties
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialProperties:
    """Tests for Credential model properties (is_expired, expires_soon)."""

    @pytest.fixture
    def user(self):
        """Create a test user."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def credential_type(self):
        """Create a credential type."""
        from cms.models import CredentialType

        return CredentialType.objects.create(
            name="Deployment Profile",
            slug="deployment_profile",
            spec_class="shared.schemas.DeploymentProfileSpec",
        )

    def test_is_expired_returns_false_when_expires_at_is_none(self, user, credential_type):
        """is_expired should return False when expires_at is None."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="No Expiry",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
            expires_at=None,
        )

        assert credential.is_expired is False

    def test_is_expired_returns_false_when_not_expired(self, user, credential_type):
        """is_expired should return False when expires_at is in the future."""
        from datetime import timedelta

        from cms.models import Credential

        future = timezone.now() + timedelta(days=30)
        credential = Credential.objects.create(
            user=user,
            name="Future Expiry",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
            expires_at=future,
        )

        assert credential.is_expired is False

    def test_is_expired_returns_true_when_expired(self, user, credential_type):
        """is_expired should return True when expires_at is in the past."""
        from datetime import timedelta

        from cms.models import Credential

        past = timezone.now() - timedelta(days=1)
        credential = Credential.objects.create(
            user=user,
            name="Past Expiry",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
            expires_at=past,
        )

        assert credential.is_expired is True
