"""Tests for CMS Credential and CredentialType models."""

from datetime import timedelta

import pytest
from django.utils import timezone


@pytest.fixture
def scm_credential_type(db):
    """Get or create SCM credential type."""
    from cms.models import CredentialType

    cred_type, _ = CredentialType.objects.get_or_create(
        slug="scm",
        defaults={
            "name": "SCM Registration",
            "spec_class": "shared.schemas.SCMCredentialSpec",
        },
    )
    return cred_type


@pytest.fixture
def deployment_profile_type(db):
    """Get or create deployment profile credential type."""
    from cms.models import CredentialType

    cred_type, _ = CredentialType.objects.get_or_create(
        slug="deployment_profile",
        defaults={
            "name": "NGFW Deployment Profile",
            "spec_class": "shared.schemas.DeploymentProfileSpec",
        },
    )
    return cred_type


@pytest.mark.django_db
class TestCredentialType:
    """Tests for the CredentialType model."""

    def test_create_credential_type(self, db):
        """CredentialType can be created with required fields."""
        from cms.models import CredentialType

        cred_type = CredentialType.objects.create(
            name="Test Type",
            slug="test",
            spec_class="shared.schemas.SCMCredentialSpec",
        )

        assert cred_type.name == "Test Type"
        assert cred_type.slug == "test"
        assert cred_type.spec_class == "shared.schemas.SCMCredentialSpec"

    def test_get_spec_class_loads_scm_spec(self, scm_credential_type):
        """get_spec_class() should load SCMCredentialSpec."""
        from shared.schemas import SCMCredentialSpec

        spec_class = scm_credential_type.get_spec_class()
        assert spec_class is SCMCredentialSpec

    def test_get_spec_class_loads_deployment_profile_spec(self, deployment_profile_type):
        """get_spec_class() should load DeploymentProfileSpec."""
        from shared.schemas import DeploymentProfileSpec

        spec_class = deployment_profile_type.get_spec_class()
        assert spec_class is DeploymentProfileSpec

    def test_validate_data_validates_scm_data(self, scm_credential_type):
        """validate_data() should validate SCM credential data."""
        data = {
            "name": "My SCM Cred",
            "user_id": 1,
            "scm_folder_name": "folder",
            "scm_pin_id": "PIN123",
            "scm_pin_value": "secret",
            "sls_region": "americas",
        }

        validated = scm_credential_type.validate_data(data)

        assert validated["name"] == "My SCM Cred"
        assert validated["scm_folder_name"] == "folder"
        assert validated["sls_region"] == "americas"

    def test_validate_data_validates_deployment_profile_data(self, deployment_profile_type):
        """validate_data() should validate deployment profile data."""
        data = {
            "name": "My Profile",
            "user_id": 1,
            "authcode": "D1234567",
        }

        validated = deployment_profile_type.validate_data(data)

        assert validated["name"] == "My Profile"
        assert validated["authcode"] == "D1234567"

    def test_validate_data_raises_on_invalid_data(self, scm_credential_type):
        """validate_data() should raise ValidationError on invalid data."""
        from pydantic import ValidationError

        data = {"name": "Missing fields"}  # Missing required SCM fields

        with pytest.raises(ValidationError):
            scm_credential_type.validate_data(data)


@pytest.mark.django_db
class TestCredential:
    """Tests for the Credential model."""

    def test_create_credential_with_type(self, django_user_model, scm_credential_type):
        """Credential can be created with a CredentialType FK."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="testuser",
            email="test@test.com",
            password="test",
        )

        cred = Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=scm_credential_type,
            data={
                "scm_folder_name": "folder",
                "scm_pin_id": "PIN123",
                "scm_pin_value": "secret",
                "sls_region": "americas",
            },
        )

        assert cred.name == "My Credential"
        assert cred.credential_type == scm_credential_type
        assert cred.credential_type.slug == "scm"
        assert cred.data["scm_folder_name"] == "folder"

    def test_is_deleted_property(self, django_user_model, deployment_profile_type):
        """is_deleted reflects deleted_at state."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="deletedtest",
            email="deleted@test.com",
            password="test",
        )

        # Not deleted
        cred = Credential.objects.create(
            user=user,
            name="Not Deleted",
            credential_type=deployment_profile_type,
            data={"authcode": "D1234567"},
        )
        assert cred.is_deleted is False

        # Deleted
        cred.deleted_at = timezone.now()
        assert cred.is_deleted is True

    def test_is_expired_property(self, django_user_model, deployment_profile_type):
        """is_expired reflects expires_at state."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="expiredtest",
            email="expired@test.com",
            password="test",
        )

        cred = Credential(
            user=user,
            name="Test Expiration",
            credential_type=deployment_profile_type,
            data={},
        )

        # No expiration
        assert cred.is_expired is False

        # Expired
        cred.expires_at = timezone.now() - timedelta(days=1)
        assert cred.is_expired is True

    def test_expires_soon_property(self, django_user_model, deployment_profile_type):
        """expires_soon is True only within 30 days of non-expired credential."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="soontest",
            email="soon@test.com",
            password="test",
        )

        cred = Credential(
            user=user,
            name="Test Expires Soon",
            credential_type=deployment_profile_type,
            data={},
        )

        # No expiration - not expiring soon
        assert cred.expires_soon is False

        # Already expired - not "expiring soon"
        cred.expires_at = timezone.now() - timedelta(days=1)
        assert cred.expires_soon is False

        # Expiring within 30 days - expires soon
        cred.expires_at = timezone.now() + timedelta(days=15)
        assert cred.expires_soon is True

        # Expiring beyond 30 days - not expiring soon
        cred.expires_at = timezone.now() + timedelta(days=60)
        assert cred.expires_soon is False

    def test_unique_name_per_user_constraint(self, django_user_model, deployment_profile_type):
        """User cannot have two active credentials with the same name."""
        from django.db import IntegrityError

        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="uniquetest",
            email="unique@test.com",
            password="test",
        )

        Credential.objects.create(
            user=user,
            name="Duplicate Name",
            credential_type=deployment_profile_type,
            data={},
        )

        with pytest.raises(IntegrityError):
            Credential.objects.create(
                user=user,
                name="Duplicate Name",
                credential_type=deployment_profile_type,
                data={},
            )

    def test_deleted_credential_allows_same_name(self, django_user_model, deployment_profile_type):
        """Deleted credential should allow creating new one with same name."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="deletedname",
            email="deletedname@test.com",
            password="test",
        )

        # Create and soft-delete
        cred1 = Credential.objects.create(
            user=user,
            name="Reusable Name",
            credential_type=deployment_profile_type,
            data={},
        )
        cred1.deleted_at = timezone.now()
        cred1.save()

        # Should succeed - name is reusable after soft delete
        cred2 = Credential.objects.create(
            user=user,
            name="Reusable Name",
            credential_type=deployment_profile_type,
            data={},
        )

        assert cred2.name == "Reusable Name"
        assert cred2.is_deleted is False
