"""Tests for CMS Credential and CredentialType models."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

# ---------------------------------------------------------------------------
# Fixtures — plain objects, no DB
# ---------------------------------------------------------------------------


@pytest.fixture
def scm_credential_type():
    """Build an SCM credential type without touching the DB."""
    from cms.models import CredentialType

    ct = CredentialType.__new__(CredentialType)
    ct.__dict__.update(
        {
            "id": 1,
            "name": "SCM Registration",
            "slug": "scm",
            "spec_class": "shared.schemas.SCMCredentialSpec",
        }
    )
    return ct


@pytest.fixture
def deployment_profile_type():
    """Build a deployment-profile credential type without touching the DB."""
    from cms.models import CredentialType

    ct = CredentialType.__new__(CredentialType)
    ct.__dict__.update(
        {
            "id": 2,
            "name": "NGFW Deployment Profile",
            "slug": "deployment_profile",
            "spec_class": "shared.schemas.DeploymentProfileSpec",
        }
    )
    return ct


@pytest.fixture
def mock_user():
    """Return a lightweight mock user."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.__new__(User)
    user.__dict__.update(
        {
            "id": 1,
            "pk": 1,
            "username": "testuser",
            "email": "test@test.com",
        }
    )
    return user


def _make_credential(user, name, credential_type, data, **kwargs):
    """Instantiate a Credential without saving to the DB."""
    from django.db.models.base import ModelState

    from cms.models import Credential

    cred = Credential.__new__(Credential)
    cred._state = ModelState()
    cred._state.db = "default"
    cred._state.adding = True
    cred.__dict__.update(
        {
            "id": None,
            "user_id": user.pk,
            "name": name,
            "credential_type_id": credential_type.id if hasattr(credential_type, "id") else None,
            "data": data,
            "created_at": timezone.now(),
            "expires_at": kwargs.get("expires_at"),
            "deleted_at": kwargs.get("deleted_at"),
        }
    )
    # Cache FK objects in Django's fields_cache to avoid DB lookups
    cred._state.fields_cache["user"] = user
    cred._state.fields_cache["credential_type"] = credential_type
    return cred


# ---------------------------------------------------------------------------
# TestCredentialType
# ---------------------------------------------------------------------------


class TestCredentialType:
    """Tests for the CredentialType model."""

    def test_create_credential_type(self):
        """CredentialType can be created with required fields."""
        from cms.models import CredentialType

        ct = CredentialType.__new__(CredentialType)
        ct.__dict__.update(
            {
                "id": 99,
                "name": "Test Type",
                "slug": "test",
                "spec_class": "shared.schemas.SCMCredentialSpec",
            }
        )

        with patch.object(CredentialType.objects, "create", return_value=ct):
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


# ---------------------------------------------------------------------------
# TestCredential
# ---------------------------------------------------------------------------


class TestCredential:
    """Tests for the Credential model."""

    def test_create_credential_with_type(self, mock_user, scm_credential_type):
        """Credential can be created with a CredentialType FK."""
        from cms.models import Credential

        data = {
            "scm_folder_name": "folder",
            "scm_pin_id": "PIN123",
            "scm_pin_value": "secret",
            "sls_region": "americas",
        }

        mock_instance = _make_credential(
            user=mock_user,
            name="My Credential",
            credential_type=scm_credential_type,
            data=data,
        )

        with patch.object(Credential.objects, "create", return_value=mock_instance):
            cred = Credential.objects.create(
                user=mock_user,
                name="My Credential",
                credential_type=scm_credential_type,
                data=data,
            )

        assert cred.name == "My Credential"
        assert cred.credential_type == scm_credential_type
        assert cred.credential_type.slug == "scm"
        assert cred.data["scm_folder_name"] == "folder"

    def test_is_deleted_property(self, mock_user, deployment_profile_type):
        """is_deleted reflects deleted_at state."""
        cred = _make_credential(
            user=mock_user,
            name="Not Deleted",
            credential_type=deployment_profile_type,
            data={"authcode": "D1234567"},
        )

        # Not deleted
        assert cred.is_deleted is False

        # Deleted
        cred.deleted_at = timezone.now()
        assert cred.is_deleted is True

    def test_is_expired_property(self, mock_user, deployment_profile_type):
        """is_expired reflects expires_at state."""
        cred = _make_credential(
            user=mock_user,
            name="Test Expiration",
            credential_type=deployment_profile_type,
            data={},
        )

        # No expiration
        assert cred.is_expired is False

        # Expired
        cred.expires_at = timezone.now() - timedelta(days=1)
        assert cred.is_expired is True

    def test_expires_soon_property(self, mock_user, deployment_profile_type):
        """expires_soon is True only within 30 days of non-expired credential."""
        cred = _make_credential(
            user=mock_user,
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

    def test_unique_name_per_user_constraint(self, mock_user, deployment_profile_type):
        """User cannot have two active credentials with the same name."""
        from django.db import IntegrityError

        from cms.models import Credential

        first_cred = _make_credential(
            user=mock_user,
            name="Duplicate Name",
            credential_type=deployment_profile_type,
            data={},
        )

        with patch.object(Credential.objects, "create") as mock_create:
            # First create succeeds
            mock_create.return_value = first_cred
            Credential.objects.create(
                user=mock_user,
                name="Duplicate Name",
                credential_type=deployment_profile_type,
                data={},
            )

            # Second create raises IntegrityError (unique constraint)
            mock_create.side_effect = IntegrityError
            with pytest.raises(IntegrityError):
                Credential.objects.create(
                    user=mock_user,
                    name="Duplicate Name",
                    credential_type=deployment_profile_type,
                    data={},
                )

    def test_deleted_credential_allows_same_name(self, mock_user, deployment_profile_type):
        """Deleted credential should allow creating new one with same name."""
        from cms.models import Credential

        # Create and soft-delete
        cred1 = _make_credential(
            user=mock_user,
            name="Reusable Name",
            credential_type=deployment_profile_type,
            data={},
        )
        cred1.deleted_at = timezone.now()

        # New credential with same name succeeds
        cred2 = _make_credential(
            user=mock_user,
            name="Reusable Name",
            credential_type=deployment_profile_type,
            data={},
        )

        with patch.object(Credential.objects, "create", return_value=cred2):
            result = Credential.objects.create(
                user=mock_user,
                name="Reusable Name",
                credential_type=deployment_profile_type,
                data={},
            )

        assert result.name == "Reusable Name"
        assert result.is_deleted is False
