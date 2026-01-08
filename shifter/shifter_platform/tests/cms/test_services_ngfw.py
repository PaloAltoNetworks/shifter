"""CMS NGFW service tests.

Tests for create_ngfw service function:
- Inputs: user, name, deployment_profile_id, registration_method, etc.
- Outputs: NGFWAppRef with ngfw_id
- Side effects: creates NGFW record, calls hydrate_ngfw, calls engine
- Errors: validation errors, credential not found
- Logging: info on creation
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.exceptions import CMSError
from cms.models import NGFW, Credential, CredentialType
from shared.enums import InstanceStatus

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="test@example.com", email="test@example.com"
    )


@pytest.fixture
def deployment_profile_type(db):
    """Create deployment profile credential type."""
    return CredentialType.objects.create(
        name="Deployment Profile",
        slug="deployment_profile",
        spec_class="shared.schemas.DeploymentProfileSpec",
    )


@pytest.fixture
def scm_credential_type(db):
    """Create SCM credential type."""
    return CredentialType.objects.create(
        name="SCM Credential",
        slug="scm",
        spec_class="shared.schemas.SCMCredentialSpec",
    )


@pytest.fixture
def deployment_profile(user, deployment_profile_type, db):
    """Create a deployment profile credential for testing."""
    return Credential.objects.create(
        user=user,
        name="Test Deployment Profile",
        credential_type=deployment_profile_type,
        data={"authcode": "D1234567"},
    )


@pytest.fixture
def scm_credential(user, scm_credential_type, db):
    """Create an SCM credential for testing."""
    return Credential.objects.create(
        user=user,
        name="Test SCM Credential",
        credential_type=scm_credential_type,
        data={
            "scm_folder_name": "test-folder",
            "scm_pin_id": "pin-123",
            "scm_pin_value": "secret-pin-value",
            "sls_region": "americas",
        },
    )


@pytest.mark.django_db
class TestCreateNgfw:
    """Tests for create_ngfw() service function."""

    # -------------------------------------------------------------------------
    # Happy path - PIN registration
    # -------------------------------------------------------------------------

    def test_creates_ngfw_record(self, user, deployment_profile, scm_credential):
        """create_ngfw creates an NGFW model record."""
        with patch("engine.create_ngfw"):
            services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="pin",
                scm_credential_id=scm_credential.id,
            )

        ngfw = NGFW.objects.get(user=user)
        assert ngfw.name == "My NGFW"
        assert ngfw.status == InstanceStatus.PROVISIONING.value

    def test_returns_ngfw_app_ref(self, user, deployment_profile, scm_credential):
        """create_ngfw returns NGFWAppRef with ngfw_id."""
        with patch("engine.create_ngfw"):
            result = services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="pin",
                scm_credential_id=scm_credential.id,
            )

        assert result.ngfw_id is not None
        assert result.user_id == user.id

    def test_calls_engine_with_hydrated_request(
        self, user, deployment_profile, scm_credential
    ):
        """create_ngfw calls engine.create_ngfw with hydrated credential data."""
        with patch("engine.create_ngfw") as mock_engine:
            services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="pin",
                scm_credential_id=scm_credential.id,
            )

            mock_engine.assert_called_once()
            hydrated = mock_engine.call_args[0][0]
            # Verify hydration: InstanceSpec with nested NGFWAppSpec
            assert hydrated.role == "ngfw"
            assert hydrated.ngfw_app is not None
            assert hydrated.ngfw_app.authcode == "D1234567"
            assert hydrated.ngfw_app.scm_folder_name == "test-folder"
            assert hydrated.ngfw_app.registration_method == "pin"

    # -------------------------------------------------------------------------
    # Happy path - OTP registration
    # -------------------------------------------------------------------------

    def test_creates_ngfw_for_otp_registration(self, user, deployment_profile):
        """create_ngfw works with OTP registration method."""
        with patch("engine.create_ngfw"):
            result = services.create_ngfw(
                user=user,
                name="OTP NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="otp",
                otp_value="OTP123456",
                otp_folder="my-folder",
            )

        ngfw = NGFW.objects.get(id=result.ngfw_id)
        assert ngfw.name == "OTP NGFW"

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_when_user_is_none(self, deployment_profile, scm_credential):
        """create_ngfw raises TypeError when user is None."""
        with pytest.raises(TypeError):
            services.create_ngfw(
                user=None,
                name="My NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="pin",
                scm_credential_id=scm_credential.id,
            )

    def test_raises_when_name_empty(self, user, deployment_profile, scm_credential):
        """create_ngfw raises ValueError when name is empty."""
        with pytest.raises(ValueError, match="name is required"):
            services.create_ngfw(
                user=user,
                name="",
                deployment_profile_id=deployment_profile.id,
                registration_method="pin",
                scm_credential_id=scm_credential.id,
            )

    def test_raises_when_deployment_profile_not_found(self, user, scm_credential):
        """create_ngfw raises CMSError when deployment profile doesn't exist."""
        with pytest.raises(CMSError, match="Deployment profile not found"):
            services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=99999,
                registration_method="pin",
                scm_credential_id=scm_credential.id,
            )

    def test_raises_when_registration_method_invalid(self, user, deployment_profile):
        """create_ngfw raises ValueError for invalid registration_method."""
        with pytest.raises(ValueError, match="'pin' or 'otp'"):
            services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="invalid",
            )

    def test_raises_when_pin_missing_scm_credential(self, user, deployment_profile):
        """create_ngfw raises ValueError when PIN lacks scm_credential_id."""
        with pytest.raises(ValueError, match="scm_credential_id is required"):
            services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="pin",
                scm_credential_id=None,
            )

    def test_raises_when_otp_missing_value(self, user, deployment_profile):
        """create_ngfw raises ValueError when OTP lacks otp_value."""
        with pytest.raises(ValueError, match="otp_value and otp_folder are required"):
            services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="otp",
                otp_value=None,
                otp_folder="folder",
            )

    # -------------------------------------------------------------------------
    # Credential ownership
    # -------------------------------------------------------------------------

    def test_raises_when_deployment_profile_wrong_user(
        self, user, deployment_profile_type, scm_credential
    ):
        """create_ngfw raises CMSError when deployment profile owned by other user."""
        other_user = User.objects.create_user(
            username="other@example.com", email="other@example.com"
        )
        other_profile = Credential.objects.create(
            user=other_user,
            name="Other Profile",
            credential_type=deployment_profile_type,
            data={"authcode": "OTHER123"},
        )

        with pytest.raises(CMSError, match="Deployment profile not found"):
            services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=other_profile.id,
                registration_method="pin",
                scm_credential_id=scm_credential.id,
            )

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_info_on_creation(
        self, user, deployment_profile, scm_credential, caplog
    ):
        """create_ngfw logs info when NGFW is created."""
        import logging

        with (
            patch("engine.create_ngfw"),
            caplog.at_level(logging.INFO, logger="cms.services"),
        ):
            services.create_ngfw(
                user=user,
                name="My NGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="pin",
                scm_credential_id=scm_credential.id,
            )

        assert "NGFW" in caplog.text or "ngfw" in caplog.text
