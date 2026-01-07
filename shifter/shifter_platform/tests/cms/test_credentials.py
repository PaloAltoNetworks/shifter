"""Tests for CMS Credential and CredentialType models."""

from datetime import timedelta

import pytest
from django.utils import timezone


@pytest.fixture
def scm_credential_type(db):
    """Create SCM credential type."""
    from cms.models import CredentialType

    return CredentialType.objects.create(
        name="SCM Registration",
        slug="scm",
        spec_class="shared.schemas.SCMCredentialSpec",
    )


@pytest.fixture
def deployment_profile_type(db):
    """Create deployment profile credential type."""
    from cms.models import CredentialType

    return CredentialType.objects.create(
        name="NGFW Deployment Profile",
        slug="deployment_profile",
        spec_class="shared.schemas.DeploymentProfileSpec",
    )


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
        assert cred.data["scm_folder_name"] == "folder"

    def test_credential_type_slug_accessible(self, django_user_model, scm_credential_type):
        """Credential type slug should be accessible via FK."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="slugtest",
            email="slug@test.com",
            password="test",
        )

        cred = Credential.objects.create(
            user=user,
            name="Slug Test",
            credential_type=scm_credential_type,
            data={},
        )

        assert cred.credential_type.slug == "scm"

    def test_is_deleted_false_by_default(self, django_user_model, deployment_profile_type):
        """is_deleted should be False when deleted_at is None."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="deletedtest",
            email="deleted@test.com",
            password="test",
        )

        cred = Credential.objects.create(
            user=user,
            name="Not Deleted",
            credential_type=deployment_profile_type,
            data={"authcode": "D1234567"},
        )

        assert cred.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, django_user_model, deployment_profile_type):
        """is_deleted should be True when deleted_at is set."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="deletedtest2",
            email="deleted2@test.com",
            password="test",
        )

        cred = Credential.objects.create(
            user=user,
            name="Deleted",
            credential_type=deployment_profile_type,
            data={"authcode": "D1234567"},
            deleted_at=timezone.now(),
        )

        assert cred.is_deleted is True

    def test_is_expired_false_when_no_expiration(self, django_user_model, deployment_profile_type):
        """is_expired should be False when expires_at is None."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="expiredtest",
            email="expired@test.com",
            password="test",
        )

        cred = Credential(
            user=user,
            name="No Expiration",
            credential_type=deployment_profile_type,
            data={},
        )

        assert cred.is_expired is False

    def test_is_expired_true_when_past(self, django_user_model, deployment_profile_type):
        """is_expired should be True when expires_at is in the past."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="expiredtest2",
            email="expired2@test.com",
            password="test",
        )

        cred = Credential(
            user=user,
            name="Expired",
            credential_type=deployment_profile_type,
            data={},
            expires_at=timezone.now() - timedelta(days=1),
        )

        assert cred.is_expired is True

    def test_expires_soon_false_when_no_expiration(self, django_user_model, deployment_profile_type):
        """expires_soon should be False when expires_at is None."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="soontest",
            email="soon@test.com",
            password="test",
        )

        cred = Credential(
            user=user,
            name="No Expiration",
            credential_type=deployment_profile_type,
            data={},
        )

        assert cred.expires_soon is False

    def test_expires_soon_false_when_already_expired(self, django_user_model, deployment_profile_type):
        """expires_soon should be False when already expired."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="soontest2",
            email="soon2@test.com",
            password="test",
        )

        cred = Credential(
            user=user,
            name="Already Expired",
            credential_type=deployment_profile_type,
            data={},
            expires_at=timezone.now() - timedelta(days=1),
        )

        assert cred.is_expired is True
        assert cred.expires_soon is False

    def test_expires_soon_true_within_30_days(self, django_user_model, deployment_profile_type):
        """expires_soon should be True when expiring within 30 days."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="soontest3",
            email="soon3@test.com",
            password="test",
        )

        cred = Credential(
            user=user,
            name="Expiring Soon",
            credential_type=deployment_profile_type,
            data={},
            expires_at=timezone.now() + timedelta(days=15),
        )

        assert cred.is_expired is False
        assert cred.expires_soon is True

    def test_expires_soon_false_beyond_30_days(self, django_user_model, deployment_profile_type):
        """expires_soon should be False when expiring beyond 30 days."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="soontest4",
            email="soon4@test.com",
            password="test",
        )

        cred = Credential(
            user=user,
            name="Expiring Far",
            credential_type=deployment_profile_type,
            data={},
            expires_at=timezone.now() + timedelta(days=60),
        )

        assert cred.is_expired is False
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
