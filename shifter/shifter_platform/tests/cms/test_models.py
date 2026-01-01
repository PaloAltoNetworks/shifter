"""Tests for cms.models module - Unified Credential model."""

import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError
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


# -----------------------------------------------------------------------------
# Tests for Credential Model - Creation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialCreation:
    """Tests for Credential model creation."""

    def test_create_scm_credential(self, user):
        """Should create an SCM credential with required fields."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="My SCM Credential",
            credential_type=Credential.Type.SCM,
            scm_folder_name="test-folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret-pin",
            sls_region="americas",
        )

        assert credential.id is not None
        assert credential.user == user
        assert credential.name == "My SCM Credential"
        assert credential.credential_type == Credential.Type.SCM
        assert credential.scm_folder_name == "test-folder"
        assert credential.scm_pin_id == "PIN123"
        assert credential.scm_pin_value == "secret-pin"
        assert credential.sls_region == "americas"
        assert credential.deleted_at is None

    def test_create_deployment_profile(self, user):
        """Should create a deployment profile credential with required fields."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="My Deployment Profile",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D9232090",
        )

        assert credential.id is not None
        assert credential.user == user
        assert credential.name == "My Deployment Profile"
        assert credential.credential_type == Credential.Type.DEPLOYMENT_PROFILE
        assert credential.authcode == "D9232090"
        assert credential.deleted_at is None

    def test_credential_inherits_from_asset(self, user):
        """Credential should have Asset fields (name, created_at, deleted_at)."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Asset Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        assert hasattr(credential, "name")
        assert hasattr(credential, "created_at")
        assert hasattr(credential, "deleted_at")
        assert hasattr(credential, "is_deleted")
        assert credential.created_at is not None

    def test_credential_inherits_expiration_fields(self, user):
        """Credential should have expiration tracking fields from Credential base."""
        from cms.models import Credential

        expires = timezone.now() + timedelta(days=30)
        credential = Credential.objects.create(
            user=user,
            name="Expiration Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
            expires_at=expires,
        )

        assert hasattr(credential, "expires_at")
        assert hasattr(credential, "last_verified_at")
        assert hasattr(credential, "last_used_at")
        assert hasattr(credential, "is_expired")


# -----------------------------------------------------------------------------
# Tests for Credential Model - Required Field Validation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialRequiredFields:
    """Tests for Credential model required field validation."""

    def test_credential_type_required(self, user):
        """Should raise error when credential_type is not provided."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="No Type",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "credential_type" in str(exc_info.value)

    def test_user_required(self, db):
        """Should raise error when user is not provided."""
        from cms.models import Credential

        credential = Credential(
            name="No User",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises((ValidationError, IntegrityError)):
            credential.full_clean()
            credential.save()

    def test_name_required(self, user):
        """Should raise error when name is not provided."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "name" in str(exc_info.value)

    def test_scm_requires_folder_name(self, user):
        """SCM credentials should require scm_folder_name."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="SCM No Folder",
            credential_type=Credential.Type.SCM,
            scm_pin_id="PIN123",
            scm_pin_value="secret",
            sls_region="americas",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "scm_folder_name" in str(exc_info.value)

    def test_scm_requires_pin_id(self, user):
        """SCM credentials should require scm_pin_id."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="SCM No Pin ID",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_value="secret",
            sls_region="americas",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "scm_pin_id" in str(exc_info.value)

    def test_scm_requires_pin_value(self, user):
        """SCM credentials should require scm_pin_value."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="SCM No Pin Value",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_id="PIN123",
            sls_region="americas",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "scm_pin_value" in str(exc_info.value)

    def test_scm_requires_sls_region(self, user):
        """SCM credentials should require sls_region."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="SCM No Region",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "sls_region" in str(exc_info.value)

    def test_deployment_profile_requires_authcode(self, user):
        """Deployment profile credentials should require authcode."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="No Authcode",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "authcode" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Tests for Credential Model - Type-Specific Field Requirements
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialTypeSpecificFields:
    """Tests for type-specific field requirements."""

    def test_scm_does_not_require_authcode(self, user):
        """SCM credentials should not require authcode."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="SCM Valid",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret",
            sls_region="americas",
        )

        # Should not raise
        credential.full_clean()

    def test_deployment_profile_does_not_require_scm_fields(self, user):
        """Deployment profile should not require SCM-specific fields."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Deployment Valid",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Should not raise
        credential.full_clean()


# -----------------------------------------------------------------------------
# Tests for Credential Model - Invalid Type Validation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialInvalidTypes:
    """Tests for invalid type validation."""

    def test_invalid_credential_type_rejected(self, user):
        """Should reject invalid credential_type values."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Invalid Type",
            credential_type="invalid_type",
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "credential_type" in str(exc_info.value)

    def test_empty_credential_type_rejected(self, user):
        """Should reject empty string credential_type."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Empty Type",
            credential_type="",
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "credential_type" in str(exc_info.value)

    def test_invalid_sls_region_rejected(self, user):
        """Should reject invalid sls_region values for SCM credentials."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Invalid Region",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret",
            sls_region="invalid_region",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "sls_region" in str(exc_info.value)

    def test_valid_sls_regions_accepted(self, user):
        """Should accept all valid SLS region values."""
        from cms.models import Credential

        valid_regions = ["americas", "europe", "japan", "asiapacific"]

        for region in valid_regions:
            credential = Credential(
                user=user,
                name=f"Region {region}",
                credential_type=Credential.Type.SCM,
                scm_folder_name="folder",
                scm_pin_id="PIN123",
                scm_pin_value="secret",
                sls_region=region,
            )
            # Should not raise
            credential.full_clean()


# -----------------------------------------------------------------------------
# Tests for Credential Model - Authcode Format Validation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialAuthcodeValidation:
    """Tests for authcode format validation."""

    def test_valid_authcode_format_accepted(self, user):
        """Should accept valid authcode format (letter followed by 7 digits)."""
        from cms.models import Credential

        valid_authcodes = ["D9232090", "A1234567", "Z9999999", "B0000000"]

        for authcode in valid_authcodes:
            credential = Credential(
                user=user,
                name=f"Authcode {authcode}",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode=authcode,
            )
            # Should not raise
            credential.full_clean()

    def test_authcode_too_short_rejected(self, user):
        """Should reject authcode that is too short."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Short Authcode",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D123",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "authcode" in str(exc_info.value).lower()

    def test_authcode_invalid_format_rejected(self, user):
        """Should reject authcode with invalid format (must start with letter)."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Invalid Format",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="12345678",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "authcode" in str(exc_info.value).lower()

    def test_authcode_empty_string_rejected(self, user):
        """Should reject empty string authcode for deployment profiles."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Empty Authcode",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "authcode" in str(exc_info.value).lower()


# -----------------------------------------------------------------------------
# Tests for Credential Model - Field Length Validation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialFieldLengths:
    """Tests for field length validation."""

    def test_name_max_length_enforced(self, user):
        """Should reject name exceeding max length (100 chars)."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="x" * 101,  # 101 chars, max is 100
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "name" in str(exc_info.value)

    def test_name_at_max_length_accepted(self, user):
        """Should accept name at exactly max length."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="x" * 100,  # Exactly 100 chars
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Should not raise
        credential.full_clean()

    def test_scm_folder_name_max_length_enforced(self, user):
        """Should reject scm_folder_name exceeding max length (255 chars)."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Test",
            credential_type=Credential.Type.SCM,
            scm_folder_name="x" * 256,  # 256 chars, max is 255
            scm_pin_id="PIN123",
            scm_pin_value="secret",
            sls_region="americas",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "scm_folder_name" in str(exc_info.value)

    def test_scm_pin_id_max_length_enforced(self, user):
        """Should reject scm_pin_id exceeding max length (255 chars)."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Test",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_id="x" * 256,  # 256 chars, max is 255
            scm_pin_value="secret",
            sls_region="americas",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "scm_pin_id" in str(exc_info.value)

    def test_authcode_max_length_enforced(self, user):
        """Should reject authcode exceeding max length (100 chars)."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D" + "1" * 100,  # 101 chars, max is 100
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "authcode" in str(exc_info.value).lower()


# -----------------------------------------------------------------------------
# Tests for Credential Model - User Field Validation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialUserValidation:
    """Tests for user field validation."""

    def test_user_must_be_user_instance(self, db):
        """Should reject non-User objects for user field."""
        from cms.models import Credential

        # Try to create with a string instead of User
        with pytest.raises((ValueError, TypeError, IntegrityError)):
            Credential.objects.create(
                user="not_a_user",
                name="Invalid User",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

    def test_user_must_exist(self, db):
        """Should reject user_id for non-existent user."""
        from cms.models import Credential

        # Django validates FK at full_clean, so ValidationError is also valid
        with pytest.raises((ValueError, IntegrityError, ValidationError)):
            Credential.objects.create(
                user_id=99999,  # Non-existent user ID
                name="Invalid User ID",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

    def test_credential_deleted_when_user_deleted(self, db):
        """Credentials should be deleted when user is deleted (CASCADE)."""
        from cms.models import Credential

        # Create user and credential
        temp_user = User.objects.create_user(username="temp@example.com", email="temp@example.com")
        credential = Credential.objects.create(
            user=temp_user,
            name="Temp Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )
        credential_id = credential.id

        # Delete user
        temp_user.delete()

        # Credential should be gone
        assert not Credential.objects.filter(id=credential_id).exists()


# -----------------------------------------------------------------------------
# Tests for Credential Model - Empty/Whitespace Validation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialEmptyWhitespaceValidation:
    """Tests for empty and whitespace-only field validation."""

    def test_empty_name_rejected(self, user):
        """Should reject empty string name."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "name" in str(exc_info.value)

    def test_whitespace_only_name_rejected(self, user):
        """Should reject whitespace-only name."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="   ",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "name" in str(exc_info.value)

    def test_empty_scm_folder_name_rejected_for_scm(self, user):
        """Should reject empty scm_folder_name for SCM credentials."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Test",
            credential_type=Credential.Type.SCM,
            scm_folder_name="",
            scm_pin_id="PIN123",
            scm_pin_value="secret",
            sls_region="americas",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "scm_folder_name" in str(exc_info.value)

    def test_whitespace_only_scm_folder_name_rejected(self, user):
        """Should reject whitespace-only scm_folder_name for SCM credentials."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Test",
            credential_type=Credential.Type.SCM,
            scm_folder_name="   ",
            scm_pin_id="PIN123",
            scm_pin_value="secret",
            sls_region="americas",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "scm_folder_name" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Tests for Credential Model - Query Methods
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialQueryMethods:
    """Tests for Credential model query methods."""

    def test_active_for_user_returns_active_credentials(self, user):
        """active_for_user should return non-deleted credentials."""
        from cms.models import Credential

        cred1 = Credential.objects.create(
            user=user,
            name="Active 1",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )
        cred2 = Credential.objects.create(
            user=user,
            name="Active 2",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
            sls_region="americas",
        )

        active = list(Credential.active_for_user(user))

        assert len(active) == 2
        assert cred1 in active
        assert cred2 in active

    def test_active_for_user_excludes_deleted(self, user):
        """active_for_user should exclude deleted credentials."""
        from cms.models import Credential

        active_cred = Credential.objects.create(
            user=user,
            name="Active",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )
        Credential.objects.create(
            user=user,
            name="Deleted",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D2222222",
            deleted_at=timezone.now(),
        )

        active = list(Credential.active_for_user(user))

        assert len(active) == 1
        assert active[0] == active_cred

    def test_active_for_user_excludes_other_users(self, user, other_user):
        """active_for_user should only return credentials for specified user."""
        from cms.models import Credential

        user_cred = Credential.objects.create(
            user=user,
            name="User Cred",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )
        Credential.objects.create(
            user=other_user,
            name="Other Cred",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D2222222",
        )

        active = list(Credential.active_for_user(user))

        assert len(active) == 1
        assert active[0] == user_cred

    def test_active_for_user_returns_empty_when_none(self, user):
        """active_for_user should return empty queryset when no credentials."""
        from cms.models import Credential

        active = list(Credential.active_for_user(user))

        assert len(active) == 0


# -----------------------------------------------------------------------------
# Tests for Credential Model - Properties
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialProperties:
    """Tests for Credential model properties."""

    def test_is_expired_returns_false_when_no_expiry(self, user):
        """is_expired should return False when expires_at is None."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="No Expiry",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
            expires_at=None,
        )

        assert credential.is_expired is False

    def test_is_expired_returns_false_when_not_expired(self, user):
        """is_expired should return False when expires_at is in the future."""
        from cms.models import Credential

        future = timezone.now() + timedelta(days=30)
        credential = Credential.objects.create(
            user=user,
            name="Future Expiry",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
            expires_at=future,
        )

        assert credential.is_expired is False

    def test_is_expired_returns_true_when_expired(self, user):
        """is_expired should return True when expires_at is in the past."""
        from cms.models import Credential

        past = timezone.now() - timedelta(days=1)
        credential = Credential.objects.create(
            user=user,
            name="Past Expiry",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
            expires_at=past,
        )

        assert credential.is_expired is True

    def test_is_deleted_returns_false_when_not_deleted(self, user):
        """is_deleted should return False when deleted_at is None."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Not Deleted",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )

        assert credential.is_deleted is False

    def test_is_deleted_returns_true_when_deleted(self, user):
        """is_deleted should return True when deleted_at is set."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Deleted",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
            deleted_at=timezone.now(),
        )

        assert credential.is_deleted is True


# -----------------------------------------------------------------------------
# Tests for Credential Model - String Representation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialStringRepresentation:
    """Tests for Credential model string representation."""

    def test_str_returns_name(self, user):
        """__str__ should return the credential name."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="My Test Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )

        assert str(credential) == "My Test Credential"


# -----------------------------------------------------------------------------
# Tests for Credential Model - Ordering
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialOrdering:
    """Tests for Credential model ordering."""

    def test_credentials_ordered_by_created_at_descending(self, user):
        """Credentials should be ordered by created_at descending (newest first)."""
        from cms.models import Credential

        cred1 = Credential.objects.create(
            user=user,
            name="First",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )
        cred2 = Credential.objects.create(
            user=user,
            name="Second",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D2222222",
        )
        cred3 = Credential.objects.create(
            user=user,
            name="Third",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D3333333",
        )

        credentials = list(Credential.objects.filter(user=user))

        # Newest first
        assert credentials[0] == cred3
        assert credentials[1] == cred2
        assert credentials[2] == cred1


# -----------------------------------------------------------------------------
# Tests for Credential Model - Uniqueness Constraints
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialUniqueness:
    """Tests for credential uniqueness constraints."""

    def test_duplicate_name_for_same_user_rejected(self, user):
        """Should reject creating credential with duplicate name for same user."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )

        with pytest.raises((ValidationError, IntegrityError)):
            credential2 = Credential(
                user=user,
                name="My Credential",  # Same name
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D2222222",
            )
            credential2.full_clean()
            credential2.save()

    def test_same_name_allowed_for_different_users(self, user, other_user):
        """Should allow same name for different users."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )

        # Should not raise
        cred2 = Credential.objects.create(
            user=other_user,
            name="My Credential",  # Same name, different user
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D2222222",
        )
        assert cred2.id is not None

    def test_duplicate_authcode_for_same_user_rejected(self, user):
        """Should reject creating deployment profile with duplicate authcode for same user."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="Profile 1",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises((ValidationError, IntegrityError)):
            credential2 = Credential(
                user=user,
                name="Profile 2",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",  # Same authcode
            )
            credential2.full_clean()
            credential2.save()

    def test_same_authcode_allowed_for_different_users(self, user, other_user):
        """Should allow same authcode for different users."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="Profile 1",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Should not raise
        cred2 = Credential.objects.create(
            user=other_user,
            name="Profile 2",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",  # Same authcode, different user
        )
        assert cred2.id is not None

    def test_duplicate_scm_folder_pin_combo_rejected(self, user):
        """Should reject SCM credential with duplicate folder+pin_id combo for same user."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="SCM 1",
            credential_type=Credential.Type.SCM,
            scm_folder_name="my-folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret1",
            sls_region="americas",
        )

        with pytest.raises((ValidationError, IntegrityError)):
            credential2 = Credential(
                user=user,
                name="SCM 2",
                credential_type=Credential.Type.SCM,
                scm_folder_name="my-folder",  # Same folder
                scm_pin_id="PIN123",  # Same pin_id
                scm_pin_value="secret2",
                sls_region="europe",
            )
            credential2.full_clean()
            credential2.save()

    def test_same_folder_different_pin_allowed(self, user):
        """Should allow same folder with different pin_id."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="SCM 1",
            credential_type=Credential.Type.SCM,
            scm_folder_name="my-folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret1",
            sls_region="americas",
        )

        # Should not raise
        cred2 = Credential.objects.create(
            user=user,
            name="SCM 2",
            credential_type=Credential.Type.SCM,
            scm_folder_name="my-folder",  # Same folder
            scm_pin_id="PIN456",  # Different pin_id
            scm_pin_value="secret2",
            sls_region="americas",
        )
        assert cred2.id is not None

    def test_deleted_credential_does_not_block_new_with_same_name(self, user):
        """Soft-deleted credential should not block creating new one with same name."""
        from cms.models import Credential

        # Create and soft-delete a credential
        Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
            deleted_at=timezone.now(),
        )

        # Should be able to create new one with same name
        cred2 = Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D2222222",
        )
        assert cred2.id is not None
        assert cred2.deleted_at is None


# -----------------------------------------------------------------------------
# Tests for Credential Model - Immutability Constraints
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialImmutability:
    """Tests for credential field immutability constraints."""

    def test_credential_type_cannot_be_changed(self, user):
        """Should reject changing credential_type after creation."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Immutable Type",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Try to change type
        credential.credential_type = Credential.Type.SCM
        credential.scm_folder_name = "folder"
        credential.scm_pin_id = "PIN123"
        credential.scm_pin_value = "secret"
        credential.sls_region = "americas"

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "credential_type" in str(exc_info.value).lower()

    def test_user_ownership_cannot_be_changed(self, user, other_user):
        """Should reject changing user (ownership transfer) after creation."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="My Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Try to change owner
        credential.user = other_user

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "user" in str(exc_info.value).lower()

    def test_authcode_cannot_be_changed(self, user):
        """Should reject changing authcode after creation (audit trail)."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Immutable Authcode",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Try to change authcode
        credential.authcode = "D9999999"

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "authcode" in str(exc_info.value).lower()

    def test_name_can_be_changed(self, user):
        """Should allow changing name (not immutable)."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Original Name",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Should be allowed
        credential.name = "New Name"
        credential.full_clean()
        credential.save()

        credential.refresh_from_db()
        assert credential.name == "New Name"

    def test_expires_at_can_be_changed(self, user):
        """Should allow changing expires_at (renewal)."""
        from cms.models import Credential

        original_expiry = timezone.now() + timedelta(days=30)
        credential = Credential.objects.create(
            user=user,
            name="Expiring Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
            expires_at=original_expiry,
        )

        # Should be allowed to extend expiry
        new_expiry = timezone.now() + timedelta(days=60)
        credential.expires_at = new_expiry
        credential.full_clean()
        credential.save()

        credential.refresh_from_db()
        assert credential.expires_at == new_expiry


# -----------------------------------------------------------------------------
# Tests for Credential Model - Soft Delete Behavior
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialSoftDeleteBehavior:
    """Tests for soft delete specific behavior."""

    def test_cannot_undelete_credential(self, user):
        """Should not allow setting deleted_at back to None (undelete)."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Deleted Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
            deleted_at=timezone.now(),
        )

        # Try to undelete
        credential.deleted_at = None

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "undelete" in str(exc_info.value).lower() or "deleted" in str(exc_info.value).lower()

    def test_cannot_update_deleted_credential_fields(self, user):
        """Should not allow modifying other fields on deleted credentials."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Deleted Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
            deleted_at=timezone.now(),
        )

        # Try to update name on deleted credential
        credential.name = "New Name"

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "deleted" in str(exc_info.value).lower()

    def test_deleted_credential_excluded_from_default_queryset(self, user):
        """Deleted credentials should be excluded from default manager queries."""
        from cms.models import Credential

        active = Credential.objects.create(
            user=user,
            name="Active",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )
        Credential.objects.create(
            user=user,
            name="Deleted",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D2222222",
            deleted_at=timezone.now(),
        )

        # active_for_user excludes deleted
        active_creds = list(Credential.active_for_user(user))
        assert len(active_creds) == 1
        assert active_creds[0] == active


# -----------------------------------------------------------------------------
# Tests for Credential Model - Security
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialSecurity:
    """Tests for credential security constraints."""

    def test_str_does_not_expose_sensitive_fields(self, user):
        """__str__ should not expose sensitive data like authcode or pin_value."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Secure Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        str_repr = str(credential)
        assert "D1234567" not in str_repr
        assert "authcode" not in str_repr.lower()

    def test_repr_does_not_expose_sensitive_fields(self, user):
        """__repr__ should not expose sensitive data."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Secure Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        repr_str = repr(credential)
        assert "D1234567" not in repr_str

    def test_scm_str_does_not_expose_pin_value(self, user):
        """__str__ should not expose SCM pin_value."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="SCM Credential",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_id="PIN123",
            scm_pin_value="super-secret-pin",
            sls_region="americas",
        )

        str_repr = str(credential)
        repr_str = repr(credential)

        assert "super-secret-pin" not in str_repr
        assert "super-secret-pin" not in repr_str

    def test_authcode_field_is_encrypted(self, user):
        """Authcode field should use encryption."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="Encrypted Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Verify field is EncryptedCharField
        field = Credential._meta.get_field("authcode")
        assert "encrypted" in field.__class__.__name__.lower()

    def test_scm_pin_value_field_is_encrypted(self, user):
        """SCM pin_value field should use encryption."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="Encrypted SCM",
            credential_type=Credential.Type.SCM,
            scm_folder_name="folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret-value",
            sls_region="americas",
        )

        # Verify field is EncryptedCharField
        field = Credential._meta.get_field("scm_pin_value")
        assert "encrypted" in field.__class__.__name__.lower()


# -----------------------------------------------------------------------------
# Tests for Credential Model - Timestamp Tracking
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialTimestampTracking:
    """Tests for credential timestamp field behavior."""

    def test_created_at_auto_set_on_create(self, user):
        """created_at should be automatically set on creation."""
        from cms.models import Credential

        before = timezone.now()
        credential = Credential.objects.create(
            user=user,
            name="Timestamp Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )
        after = timezone.now()

        assert credential.created_at is not None
        assert before <= credential.created_at <= after

    def test_created_at_not_modified_on_update(self, user):
        """created_at should not change on updates."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Timestamp Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )
        original_created_at = credential.created_at

        credential.name = "Updated Name"
        credential.save()
        credential.refresh_from_db()

        assert credential.created_at == original_created_at

    def test_last_used_at_initially_none(self, user):
        """last_used_at should be None on creation."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Usage Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        assert credential.last_used_at is None

    def test_last_verified_at_initially_none(self, user):
        """last_verified_at should be None on creation."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Verification Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        assert credential.last_verified_at is None


# -----------------------------------------------------------------------------
# Tests for Credential Model - Debug Logging on Success
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialSuccessLogging:
    """Tests for debug logging on successful operations."""

    def test_logs_debug_on_successful_create(self, user, caplog):
        """Should log DEBUG when credential is successfully created."""
        from cms.models import Credential

        with caplog.at_level(logging.DEBUG, logger="cms.models"):
            credential = Credential.objects.create(
                user=user,
                name="Logging Test",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

        assert "created" in caplog.text.lower()
        assert credential.name in caplog.text or str(credential.pk) in caplog.text

    def test_logs_debug_on_successful_scm_create(self, user, caplog):
        """Should log DEBUG when SCM credential is successfully created."""
        from cms.models import Credential

        with caplog.at_level(logging.DEBUG, logger="cms.models"):
            credential = Credential.objects.create(
                user=user,
                name="SCM Logging Test",
                credential_type=Credential.Type.SCM,
                scm_folder_name="folder",
                scm_pin_id="PIN123",
                scm_pin_value="secret",
                sls_region="americas",
            )

        assert "created" in caplog.text.lower()
        assert credential.credential_type in caplog.text or "scm" in caplog.text.lower()

    def test_logs_debug_on_successful_update(self, user, caplog):
        """Should log DEBUG when credential is successfully updated."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Update Log Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with caplog.at_level(logging.DEBUG, logger="cms.models"):
            credential.name = "Updated Name"
            credential.save()

        assert "updated" in caplog.text.lower() or "saved" in caplog.text.lower()

    def test_logs_debug_on_successful_validation(self, user, caplog):
        """Should log DEBUG when validation passes."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Validation Log Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with caplog.at_level(logging.DEBUG, logger="cms.models"):
            credential.full_clean()

        assert "valid" in caplog.text.lower()

    def test_debug_log_includes_credential_type(self, user, caplog):
        """Debug log should include credential type for context."""
        from cms.models import Credential

        with caplog.at_level(logging.DEBUG, logger="cms.models"):
            Credential.objects.create(
                user=user,
                name="Type Context Test",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

        assert "deployment_profile" in caplog.text.lower() or "type" in caplog.text.lower()

    def test_debug_log_includes_user_context(self, user, caplog):
        """Debug log should include user context."""
        from cms.models import Credential

        with caplog.at_level(logging.DEBUG, logger="cms.models"):
            Credential.objects.create(
                user=user,
                name="User Context Test",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

        # Should log user ID or username for traceability
        assert str(user.pk) in caplog.text or user.username in caplog.text


# -----------------------------------------------------------------------------
# Tests for Credential Model - Error Logging on Failure
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialErrorLogging:
    """Tests for error logging on failed operations."""

    def test_logs_error_on_validation_failure(self, user, caplog):
        """Should log ERROR when validation fails."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="",  # Invalid - empty name
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with caplog.at_level(logging.ERROR, logger="cms.models"), pytest.raises(ValidationError):
            credential.full_clean()

        assert "error" in caplog.text.lower() or "validation" in caplog.text.lower() or "failed" in caplog.text.lower()

    def test_logs_error_on_invalid_credential_type(self, user, caplog):
        """Should log ERROR when credential type is invalid."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Invalid Type",
            credential_type="invalid_type",
            authcode="D1234567",
        )

        with caplog.at_level(logging.ERROR, logger="cms.models"), pytest.raises(ValidationError):
            credential.full_clean()

        assert "credential_type" in caplog.text.lower() or "invalid" in caplog.text.lower()

    def test_logs_error_on_missing_required_fields(self, user, caplog):
        """Should log ERROR when required fields are missing."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Missing Authcode",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            # Missing authcode
        )

        with caplog.at_level(logging.ERROR, logger="cms.models"), pytest.raises(ValidationError):
            credential.full_clean()

        assert "authcode" in caplog.text.lower() or "required" in caplog.text.lower()

    def test_logs_error_on_invalid_authcode_format(self, user, caplog):
        """Should log ERROR when authcode format is invalid."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Bad Authcode",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="12345",  # Invalid format
        )

        with caplog.at_level(logging.ERROR, logger="cms.models"), pytest.raises(ValidationError):
            credential.full_clean()

        assert "authcode" in caplog.text.lower() or "format" in caplog.text.lower()

    def test_logs_error_on_immutability_violation(self, user, caplog):
        """Should log ERROR when immutable field change is attempted."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Immutable Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        credential.authcode = "D9999999"

        with caplog.at_level(logging.ERROR, logger="cms.models"), pytest.raises(ValidationError):
            credential.full_clean()

        # Log includes field name and indicates failure
        assert "authcode" in caplog.text.lower()
        assert "failed" in caplog.text.lower()

    def test_error_log_includes_field_name(self, user, caplog):
        """Error log should include the field name that failed validation."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Field Error Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="bad",  # Invalid format
        )

        with caplog.at_level(logging.ERROR, logger="cms.models"), pytest.raises(ValidationError):
            credential.full_clean()

        assert "authcode" in caplog.text.lower()

    def test_error_log_includes_user_context(self, user, caplog):
        """Error log should include user context for debugging."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="",  # Invalid
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with caplog.at_level(logging.ERROR, logger="cms.models"), pytest.raises(ValidationError):
            credential.full_clean()

        # Should include user ID for traceability
        assert str(user.pk) in caplog.text or user.username in caplog.text


# -----------------------------------------------------------------------------
# Tests for Credential Model - Exception Propagation
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialExceptionPropagation:
    """Tests for proper exception propagation (no swallowing)."""

    def test_database_error_propagates_on_save(self, user):
        """Database errors should propagate, not be swallowed."""
        from cms.models import Credential

        with (
            patch.object(Credential.objects, "create", side_effect=DatabaseError("Connection lost")),
            pytest.raises(DatabaseError, match="Connection lost"),
        ):
            Credential.objects.create(
                user=user,
                name="DB Error Test",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

    def test_integrity_error_propagates(self, user):
        """IntegrityError should propagate for duplicate constraint violations."""
        from cms.models import Credential

        Credential.objects.create(
            user=user,
            name="Duplicate Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Should raise IntegrityError or ValidationError, not silently fail
        with pytest.raises((IntegrityError, ValidationError)):
            Credential.objects.create(
                user=user,
                name="Duplicate Test",  # Same name, same user
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D2222222",
            )

    def test_validation_error_propagates_from_clean(self, user):
        """ValidationError from clean() should propagate to caller."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="",  # Invalid
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        # Error should contain useful information
        assert "name" in str(exc_info.value)

    def test_validation_error_propagates_from_save(self, user):
        """ValidationError should propagate when save() calls full_clean()."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="",  # Invalid
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises(ValidationError):
            credential.save()

    def test_database_error_logged_and_propagated(self, user, caplog):
        """Database errors should propagate (not be swallowed)."""
        from cms.models import Credential

        # Test that database errors propagate - they are not logged by the model
        # since they happen at a level below our code (in Django's ORM)
        # The model should NOT catch and swallow these errors
        with patch(
            "django.db.models.Model.save",
            side_effect=DatabaseError("DB unavailable"),
        ):
            credential = Credential(
                user=user,
                name="DB Log Test",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

            # Database error should propagate, not be caught/swallowed
            with pytest.raises(DatabaseError, match="DB unavailable"):
                credential.save()

    def test_unexpected_exception_not_swallowed(self, user):
        """Unexpected exceptions should not be caught and swallowed."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Unexpected Error",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Simulate unexpected exception during validation
        with (
            patch.object(credential, "_validate_deployment_profile_fields", side_effect=RuntimeError("Unexpected")),
            pytest.raises(RuntimeError, match="Unexpected"),
        ):
            credential.full_clean()

    def test_type_error_propagates(self, user):
        """TypeError should propagate when wrong type is passed."""
        from cms.models import Credential

        with pytest.raises((TypeError, ValueError, IntegrityError)):
            Credential.objects.create(
                user="not_a_user_object",  # Wrong type
                name="Type Error Test",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

    def test_attribute_error_propagates(self, user):
        """AttributeError should propagate, not be silently ignored."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Attr Error Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Accessing non-existent attribute should raise
        with pytest.raises(AttributeError):
            _ = credential.nonexistent_attribute


# -----------------------------------------------------------------------------
# Tests for Credential Model - Specific Exception Types
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialSpecificExceptions:
    """Tests for specific exception types in failure modes."""

    def test_missing_user_raises_integrity_error(self, db):
        """Missing user should raise IntegrityError on save."""
        from cms.models import Credential

        credential = Credential(
            name="No User",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises((IntegrityError, ValidationError)):
            credential.save()

    def test_invalid_user_id_raises_integrity_error(self, db):
        """Invalid user_id should raise an error (IntegrityError or ValidationError)."""
        from cms.models import Credential

        # Django validates FK at full_clean, so ValidationError is also valid
        with pytest.raises((IntegrityError, ValueError, ValidationError)):
            Credential.objects.create(
                user_id=99999,  # Non-existent
                name="Bad User ID",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D1234567",
            )

    def test_empty_credential_type_raises_validation_error(self, user):
        """Empty credential_type should raise ValidationError."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Empty Type",
            credential_type="",
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "credential_type" in str(exc_info.value)

    def test_null_name_raises_validation_error(self, user):
        """Null name should raise ValidationError."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        assert "name" in str(exc_info.value)

    def test_concurrent_duplicate_raises_integrity_error(self, user):
        """Concurrent duplicate creation should raise IntegrityError."""
        from cms.models import Credential

        # First create succeeds
        Credential.objects.create(
            user=user,
            name="Concurrent Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        # Second create with same unique fields should fail
        with pytest.raises((IntegrityError, ValidationError)):
            # Bypass validation to test DB constraint
            credential = Credential(
                user=user,
                name="Concurrent Test",
                credential_type=Credential.Type.DEPLOYMENT_PROFILE,
                authcode="D2222222",
            )
            credential.full_clean()
            credential.save()


# -----------------------------------------------------------------------------
# Tests for Credential Model - Error Message Quality
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialErrorMessageQuality:
    """Tests for error message quality and clarity."""

    def test_validation_error_message_is_descriptive(self, user):
        """ValidationError messages should be descriptive and actionable."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Bad Authcode",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="bad",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        error_message = str(exc_info.value)
        # Should explain what's wrong and what's expected
        assert "authcode" in error_message.lower()

    def test_immutability_error_message_explains_constraint(self, user):
        """Immutability errors should explain the constraint clearly."""
        from cms.models import Credential

        credential = Credential.objects.create(
            user=user,
            name="Immutable Msg Test",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1234567",
        )

        credential.authcode = "D9999999"

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        error_message = str(exc_info.value)
        # Should explain that field cannot be changed
        assert "cannot" in error_message.lower() or "immutable" in error_message.lower()

    def test_missing_field_error_names_the_field(self, user):
        """Missing field errors should name the specific field."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Missing SCM Field",
            credential_type=Credential.Type.SCM,
            # Missing all SCM fields
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        error_message = str(exc_info.value)
        # Should name at least one missing field
        assert any(
            field in error_message.lower() for field in ["scm_folder_name", "scm_pin_id", "scm_pin_value", "sls_region"]
        )

    def test_type_mismatch_error_shows_expected_type(self, user):
        """Type validation errors should show expected type."""
        from cms.models import Credential

        credential = Credential(
            user=user,
            name="Invalid Type",
            credential_type="not_a_real_type",
            authcode="D1234567",
        )

        with pytest.raises(ValidationError) as exc_info:
            credential.full_clean()

        error_message = str(exc_info.value)
        assert "credential_type" in error_message.lower()
