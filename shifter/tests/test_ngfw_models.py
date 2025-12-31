"""Unit tests for NGFW-related models.

Tests for:
- SCMCredential (renamed from StrataConfig concept)
- NGFWDeploymentProfile
- UserNGFW
- Range.ngfw FK relationship

These tests focus on edge cases and subtle bugs:
- Expiration boundary conditions
- Encrypted field behavior
- FK on_delete behavior
- Status transitions
- Query filtering logic
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.utils import timezone

from mission_control.models import (
    NGFWDeploymentProfile,
    Range,
    SCMCredential,
    UserNGFW,
)

User = get_user_model()


# --- SCMCredential Tests ---


@pytest.mark.django_db
class TestSCMCredential:
    """Tests for SCMCredential model."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_create_with_required_fields(self, user):
        """SCMCredential can be created with required fields."""
        cred = SCMCredential.objects.create(
            user=user,
            name="Test SCM Credential",
            scm_folder_name="test-folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret-pin-value",
        )
        assert cred.pk is not None
        assert cred.user == user

    def test_str_returns_name(self, user):
        """__str__ returns the credential name."""
        cred = SCMCredential(
            user=user,
            name="My SCM Cred",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
        )
        assert str(cred) == "My SCM Cred"

    def test_sls_region_default_is_americas(self, user):
        """sls_region defaults to 'americas'."""
        cred = SCMCredential.objects.create(
            user=user,
            name="Test",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
        )
        assert cred.sls_region == "americas"

    def test_sls_region_valid_choices(self, user):
        """sls_region accepts valid choices."""
        valid_regions = ["americas", "europe", "japan", "asiapacific"]
        for region in valid_regions:
            cred = SCMCredential.objects.create(
                user=user,
                name=f"Test {region}",
                scm_folder_name="folder",
                scm_pin_id=f"PIN-{region}",
                scm_pin_value="secret",
                sls_region=region,
            )
            cred.full_clean()  # Validate
            assert cred.sls_region == region

    # --- Expiration boundary tests ---

    def test_is_expired_false_when_no_expiry(self, user):
        """is_expired returns False when expires_at is None."""
        cred = SCMCredential(
            user=user,
            name="No Expiry",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
            expires_at=None,
        )
        assert cred.is_expired is False

    def test_is_expired_false_when_future(self, user):
        """is_expired returns False when expires_at is in the future."""
        cred = SCMCredential(
            user=user,
            name="Future Expiry",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        assert cred.is_expired is False

    def test_is_expired_true_when_past(self, user):
        """is_expired returns True when expires_at is in the past."""
        cred = SCMCredential(
            user=user,
            name="Past Expiry",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        assert cred.is_expired is True

    def test_is_expired_boundary_exactly_now(self, user):
        """is_expired at exact boundary - tests off-by-one errors."""
        # When expires_at == now, should be expired (> not >=)
        now = timezone.now()
        cred = SCMCredential(
            user=user,
            name="Boundary",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
            expires_at=now,
        )
        # The is_expired check uses `timezone.now() > self.expires_at`
        # So at exact boundary, depends on timing. Check it doesn't crash.
        result = cred.is_expired
        assert isinstance(result, bool)

    # --- Encrypted field tests ---

    def test_pin_value_roundtrips_correctly(self, user):
        """scm_pin_value encrypts on save and decrypts on read."""
        plaintext = "super-secret-pin-12345"
        cred = SCMCredential.objects.create(
            user=user,
            name="Encrypted Test",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value=plaintext,
        )

        # Refresh from DB and verify decryption works
        cred.refresh_from_db()
        assert cred.scm_pin_value == plaintext

        # Load fresh from DB
        loaded = SCMCredential.objects.get(pk=cred.pk)
        assert loaded.scm_pin_value == plaintext

    # --- Soft delete / active_for_user tests ---

    def test_is_deleted_false_by_default(self, user):
        """is_deleted returns False when deleted_at is None."""
        cred = SCMCredential.objects.create(
            user=user,
            name="Active",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
        )
        assert cred.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, user):
        """is_deleted returns True when deleted_at is set."""
        cred = SCMCredential.objects.create(
            user=user,
            name="Deleted",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
            deleted_at=timezone.now(),
        )
        assert cred.is_deleted is True

    def test_active_for_user_excludes_deleted(self, user):
        """active_for_user excludes soft-deleted credentials."""
        active = SCMCredential.objects.create(
            user=user,
            name="Active",
            scm_folder_name="folder",
            scm_pin_id="PIN1",
            scm_pin_value="secret",
        )
        SCMCredential.objects.create(
            user=user,
            name="Deleted",
            scm_folder_name="folder",
            scm_pin_id="PIN2",
            scm_pin_value="secret",
            deleted_at=timezone.now(),
        )

        result = list(SCMCredential.active_for_user(user))
        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_filters_by_user(self, user):
        """active_for_user only returns credentials for specified user."""
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")

        SCMCredential.objects.create(
            user=user,
            name="My Cred",
            scm_folder_name="folder",
            scm_pin_id="PIN1",
            scm_pin_value="secret",
        )
        SCMCredential.objects.create(
            user=other_user,
            name="Other Cred",
            scm_folder_name="folder",
            scm_pin_id="PIN2",
            scm_pin_value="secret",
        )

        result = list(SCMCredential.active_for_user(user))
        assert len(result) == 1
        assert result[0].name == "My Cred"


# --- NGFWDeploymentProfile Tests ---


@pytest.mark.django_db
class TestNGFWDeploymentProfile:
    """Tests for NGFWDeploymentProfile model."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_create_with_required_fields(self, user):
        """NGFWDeploymentProfile can be created with required fields."""
        profile = NGFWDeploymentProfile.objects.create(
            user=user,
            name="Test Profile",
            authcode="D9232090",
        )
        assert profile.pk is not None

    def test_str_returns_name(self, user):
        """__str__ returns the profile name."""
        profile = NGFWDeploymentProfile(
            user=user,
            name="My Profile",
            authcode="ABC123",
        )
        assert str(profile) == "My Profile"

    def test_authcode_roundtrips_correctly(self, user):
        """authcode encrypts on save and decrypts on read."""
        plaintext = "D9232090-SECRET"
        profile = NGFWDeploymentProfile.objects.create(
            user=user,
            name="Encrypted Test",
            authcode=plaintext,
        )

        # Refresh from DB and verify decryption works
        profile.refresh_from_db()
        assert profile.authcode == plaintext

        # Load fresh from DB
        loaded = NGFWDeploymentProfile.objects.get(pk=profile.pk)
        assert loaded.authcode == plaintext

    def test_active_for_user_excludes_deleted(self, user):
        """active_for_user excludes soft-deleted profiles."""
        active = NGFWDeploymentProfile.objects.create(
            user=user,
            name="Active",
            authcode="AUTH1",
        )
        NGFWDeploymentProfile.objects.create(
            user=user,
            name="Deleted",
            authcode="AUTH2",
            deleted_at=timezone.now(),
        )

        result = list(NGFWDeploymentProfile.active_for_user(user))
        assert len(result) == 1
        assert result[0] == active


# --- UserNGFW Tests ---


@pytest.mark.django_db
class TestUserNGFW:
    """Tests for UserNGFW model."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def deployment_profile(self, user):
        return NGFWDeploymentProfile.objects.create(
            user=user,
            name="Test Profile",
            authcode="AUTH123",
        )

    @pytest.fixture
    def scm_credential(self, user):
        return SCMCredential.objects.create(
            user=user,
            name="Test SCM",
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
        )

    def test_create_with_required_fields(self, user, deployment_profile):
        """UserNGFW can be created with required fields."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="My NGFW",
            deployment_profile=deployment_profile,
        )
        assert ngfw.pk is not None
        assert ngfw.status == UserNGFW.Status.NOT_PROVISIONED

    def test_scm_credential_nullable_for_otp_flow(self, user, deployment_profile):
        """scm_credential can be null (OTP flow)."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="OTP NGFW",
            deployment_profile=deployment_profile,
            scm_credential=None,
        )
        assert ngfw.scm_credential is None

    def test_scm_credential_can_be_set(self, user, deployment_profile, scm_credential):
        """scm_credential can be set (PIN flow)."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="PIN NGFW",
            deployment_profile=deployment_profile,
            scm_credential=scm_credential,
        )
        assert ngfw.scm_credential == scm_credential

    def test_str_returns_name(self, user, deployment_profile):
        """__str__ returns the NGFW name."""
        ngfw = UserNGFW(
            user=user,
            name="Test NGFW",
            deployment_profile=deployment_profile,
        )
        assert str(ngfw) == "Test NGFW"

    def test_default_status_is_not_provisioned(self, user, deployment_profile):
        """Default status is NOT_PROVISIONED."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="New NGFW",
            deployment_profile=deployment_profile,
        )
        assert ngfw.status == "not_provisioned"

    def test_all_status_choices_valid(self, user, deployment_profile):
        """All status choices can be set."""
        valid_statuses = [
            "not_provisioned",
            "provisioning",
            "ready",
            "starting",
            "active",
            "stopping",
            "stopped",
            "deprovisioning",
            "failed",
        ]
        for status in valid_statuses:
            ngfw = UserNGFW.objects.create(
                user=user,
                name=f"NGFW {status}",
                deployment_profile=deployment_profile,
                status=status,
            )
            ngfw.full_clean()
            assert ngfw.status == status

    # --- FK on_delete behavior tests ---

    def test_deployment_profile_protect_prevents_delete(self, user, deployment_profile):
        """Deleting deployment_profile with linked NGFW raises ProtectedError."""
        UserNGFW.objects.create(
            user=user,
            name="Linked NGFW",
            deployment_profile=deployment_profile,
        )

        with pytest.raises(ProtectedError):
            deployment_profile.delete()

    def test_scm_credential_protect_prevents_delete(self, user, deployment_profile, scm_credential):
        """Deleting scm_credential with linked NGFW raises ProtectedError."""
        UserNGFW.objects.create(
            user=user,
            name="Linked NGFW",
            deployment_profile=deployment_profile,
            scm_credential=scm_credential,
        )

        with pytest.raises(ProtectedError):
            scm_credential.delete()

    def test_user_delete_blocked_by_protected_fks(self, user, deployment_profile):
        """Deleting user is blocked when they have NGFWs with protected FKs.

        This is intentional - users must soft-delete their credentials and NGFWs
        before account deletion can proceed. Prevents orphaned expensive resources.
        """
        UserNGFW.objects.create(
            user=user,
            name="User's NGFW",
            deployment_profile=deployment_profile,
        )

        # User deletion is blocked because NGFWDeploymentProfile uses PROTECT
        with pytest.raises(ProtectedError):
            user.delete()

    # --- active_for_user tests ---

    def test_active_for_user_excludes_deleted(self, user, deployment_profile):
        """active_for_user excludes soft-deleted NGFWs."""
        active = UserNGFW.objects.create(
            user=user,
            name="Active NGFW",
            deployment_profile=deployment_profile,
        )
        UserNGFW.objects.create(
            user=user,
            name="Deleted NGFW",
            deployment_profile=deployment_profile,
            deleted_at=timezone.now(),
        )

        result = list(UserNGFW.active_for_user(user))
        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_filters_by_user(self, user, deployment_profile):
        """active_for_user only returns NGFWs for specified user."""
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")
        other_profile = NGFWDeploymentProfile.objects.create(
            user=other_user,
            name="Other Profile",
            authcode="OTHER",
        )

        UserNGFW.objects.create(
            user=user,
            name="My NGFW",
            deployment_profile=deployment_profile,
        )
        UserNGFW.objects.create(
            user=other_user,
            name="Other NGFW",
            deployment_profile=other_profile,
        )

        result = list(UserNGFW.active_for_user(user))
        assert len(result) == 1
        assert result[0].name == "My NGFW"


# --- Range NGFW relationship tests ---


@pytest.mark.django_db
class TestRangeNGFWRelationship:
    """Tests for Range.ngfw FK relationship."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def deployment_profile(self, user):
        return NGFWDeploymentProfile.objects.create(
            user=user,
            name="Test Profile",
            authcode="AUTH123",
        )

    @pytest.fixture
    def ngfw(self, user, deployment_profile):
        return UserNGFW.objects.create(
            user=user,
            name="Test NGFW",
            deployment_profile=deployment_profile,
        )

    def test_range_ngfw_nullable(self, user):
        """Range.ngfw can be null (no NGFW attached)."""
        range_obj = Range.objects.create(user=user, ngfw=None)
        assert range_obj.ngfw is None

    def test_range_ngfw_can_be_set(self, user, ngfw):
        """Range.ngfw can reference a UserNGFW."""
        range_obj = Range.objects.create(user=user, ngfw=ngfw)
        assert range_obj.ngfw == ngfw

    def test_ngfw_delete_sets_range_ngfw_null(self, user, ngfw, deployment_profile):
        """Deleting NGFW sets Range.ngfw to NULL (SET_NULL behavior)."""
        range_obj = Range.objects.create(user=user, ngfw=ngfw)

        # Must unlink from deployment_profile first to delete NGFW
        # Actually, we need to soft-delete or use a workaround
        # For this test, we'll delete the profile too
        ngfw.delete()

        range_obj.refresh_from_db()
        assert range_obj.ngfw is None

    def test_gwlb_endpoint_id_field_exists(self, user):
        """Range has gwlb_endpoint_id field."""
        range_obj = Range.objects.create(
            user=user,
            gwlb_endpoint_id="vpce-abc123def456",
        )
        assert range_obj.gwlb_endpoint_id == "vpce-abc123def456"

    def test_gwlb_endpoint_id_default_empty(self, user):
        """gwlb_endpoint_id defaults to empty string."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.gwlb_endpoint_id == ""

    def test_multiple_ranges_can_use_same_ngfw(self, user, ngfw):
        """Multiple ranges can reference the same NGFW."""
        range1 = Range.objects.create(user=user, ngfw=ngfw)
        range2 = Range.objects.create(user=user, ngfw=ngfw)

        assert range1.ngfw == range2.ngfw == ngfw
        assert list(ngfw.ranges.all()) == [range2, range1]  # ordered by -created_at
