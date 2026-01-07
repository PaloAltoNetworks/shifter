"""Tests for cms.models module - CMS Django models.

These are unit tests for the Django model layer. They test:
- Model structure (fields, constraints, relationships)
- Model properties and methods
- Model behavior (soft delete, ordering)

For integration tests of services that use these models,
see tests/integration/cms/.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def other_user(db):
    """Create another test user."""
    return User.objects.create_user(username="other@example.com", email="other@example.com")


@pytest.fixture
def credential_type(db):
    """Create a deployment profile credential type."""
    from cms.models import CredentialType

    return CredentialType.objects.create(
        name="Deployment Profile",
        slug="deployment_profile",
        spec_class="shared.schemas.DeploymentProfileSpec",
    )


@pytest.fixture
def scm_credential_type(db):
    """Create an SCM credential type."""
    from cms.models import CredentialType

    return CredentialType.objects.create(
        name="SCM Credential",
        slug="scm",
        spec_class="shared.schemas.SCMCredentialSpec",
    )


# -----------------------------------------------------------------------------
# CatalogBase Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCatalogBase:
    """Tests for CatalogBase abstract model (via CredentialType)."""

    def test_str_returns_name(self, credential_type):
        """__str__ returns the name field."""
        assert str(credential_type) == "Deployment Profile"

    def test_get_spec_class_loads_pydantic_model(self, credential_type):
        """get_spec_class loads and returns the Pydantic spec class."""
        spec_class = credential_type.get_spec_class()

        from shared.schemas import DeploymentProfileSpec

        assert spec_class is DeploymentProfileSpec

    def test_validate_data_returns_validated_dict(self, credential_type):
        """validate_data validates against spec and returns dict."""
        data = {
            "name": "Test Cred",
            "user_id": 1,
            "authcode": "D1234567",
        }

        result = credential_type.validate_data(data)

        assert isinstance(result, dict)
        assert result["name"] == "Test Cred"
        assert result["authcode"] == "D1234567"

    def test_validate_data_raises_on_invalid_data(self, credential_type):
        """validate_data raises ValidationError for invalid data."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            credential_type.validate_data({"name": "Test", "user_id": 1})  # Missing authcode


# -----------------------------------------------------------------------------
# Credential Model Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialModel:
    """Tests for Credential model."""

    def test_create_credential(self, user, credential_type):
        """Can create a credential with required fields."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
        )

        assert credential.id is not None
        assert credential.user == user
        assert credential.name == "My Credential"
        assert credential.credential_type == credential_type
        assert credential.data == {"authcode": "D1234567"}
        assert credential.deleted_at is None

    def test_str_returns_name(self, user, credential_type):
        """__str__ returns the credential name."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="My Test Credential",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
        )

        assert str(credential) == "My Test Credential"

    def test_is_deleted_false_when_deleted_at_none(self, user, credential_type):
        """is_deleted returns False when deleted_at is None."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Active",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
        )

        assert credential.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, user, credential_type):
        """is_deleted returns True when deleted_at is set."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Deleted",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
            deleted_at=timezone.now(),
        )

        assert credential.is_deleted is True

    def test_is_expired_false_when_no_expiry(self, user, credential_type):
        """is_expired returns False when expires_at is None."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="No Expiry",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
        )

        assert credential.is_expired is False

    def test_is_expired_false_when_future(self, user, credential_type):
        """is_expired returns False when expires_at is in the future."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Future",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
            expires_at=timezone.now() + timedelta(days=30),
        )

        assert credential.is_expired is False

    def test_is_expired_true_when_past(self, user, credential_type):
        """is_expired returns True when expires_at is in the past."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Expired",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
            expires_at=timezone.now() - timedelta(days=1),
        )

        assert credential.is_expired is True

    def test_expires_soon_false_when_no_expiry(self, user, credential_type):
        """expires_soon returns False when expires_at is None."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="No Expiry",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
        )

        assert credential.expires_soon is False

    def test_expires_soon_true_within_30_days(self, user, credential_type):
        """expires_soon returns True when expires_at is within 30 days."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Soon",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
            expires_at=timezone.now() + timedelta(days=15),
        )

        assert credential.expires_soon is True

    def test_expires_soon_false_when_already_expired(self, user, credential_type):
        """expires_soon returns False when already expired."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Expired",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
            expires_at=timezone.now() - timedelta(days=1),
        )

        assert credential.expires_soon is False

    def test_ordering_by_created_at_descending(self, user, credential_type):
        """Credentials are ordered by created_at descending."""
        from cms.models import Credential

        cred1 = Credential.objects.create(
            user=user,
            name="First",
            credential_type=credential_type,
            data={"authcode": "D1111111"},
        )
        cred2 = Credential.objects.create(
            user=user,
            name="Second",
            credential_type=credential_type,
            data={"authcode": "D2222222"},
        )

        credentials = list(Credential.objects.filter(user=user))

        # Newest first
        assert credentials[0] == cred2
        assert credentials[1] == cred1


# -----------------------------------------------------------------------------
# Credential Uniqueness Constraint Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialUniqueness:
    """Tests for credential uniqueness constraints."""

    def test_duplicate_name_same_user_rejected(self, user, credential_type):
        """Rejects duplicate name for same user (active credentials)."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=credential_type,
            data={"authcode": "D1111111"},
        )

        with pytest.raises(IntegrityError):
            Credential.objects.create(
                user=user,
                name="My Credential",  # Duplicate
                credential_type=credential_type,
                data={"authcode": "D2222222"},
            )

    def test_same_name_different_users_allowed(self, user, other_user, credential_type):
        """Allows same name for different users."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=credential_type,
            data={"authcode": "D1111111"},
        )

        cred2 = Credential.objects.create(
            user=other_user,
            name="My Credential",  # Same name, different user
            credential_type=credential_type,
            data={"authcode": "D2222222"},
        )

        assert cred2.id is not None

    def test_deleted_credential_allows_same_name(self, user, credential_type):
        """Soft-deleted credential doesn't block new credential with same name."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=credential_type,
            data={"authcode": "D1111111"},
            deleted_at=timezone.now(),  # Soft deleted
        )

        cred2 = Credential.objects.create(
            user=user,
            name="My Credential",  # Same name, but original is deleted
            credential_type=credential_type,
            data={"authcode": "D2222222"},
        )

        assert cred2.id is not None
        assert cred2.deleted_at is None


# -----------------------------------------------------------------------------
# Credential Foreign Key Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialRelationships:
    """Tests for credential foreign key relationships."""

    def test_credential_deleted_when_user_deleted(self, credential_type):
        """Credentials cascade delete when user is deleted."""
        from cms.models import Credential

        temp_user = User.objects.create_user(username="temp@example.com", email="temp@example.com")
        credential = Credential.objects.create(
            user=temp_user,
            name="Temp Cred",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
        )
        cred_id = credential.id

        temp_user.delete()

        assert not Credential.objects.filter(id=cred_id).exists()

    def test_credential_protected_when_type_deleted(self, user, credential_type):
        """Cannot delete CredentialType with existing credentials (PROTECT)."""
        from django.db.models import ProtectedError

        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="Using Type",
            credential_type=credential_type,
            data={"authcode": "D1234567"},
        )

        with pytest.raises(ProtectedError):
            credential_type.delete()


# -----------------------------------------------------------------------------
# CredentialType Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialType:
    """Tests for CredentialType model."""

    def test_slug_unique(self, credential_type):
        """CredentialType slug must be unique."""
        from cms.models import CredentialType

        with pytest.raises(IntegrityError):
            CredentialType.objects.create(
                name="Another Profile",
                slug="deployment_profile",  # Duplicate slug
                spec_class="shared.schemas.DeploymentProfileSpec",
            )
