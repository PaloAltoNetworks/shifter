"""Tests for NGFW management views (list, detail, wizard, deprovision).

Follows TDD methodology - tests written first, implementation follows.
"""

import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from mission_control.models import (
    NGFWDeploymentProfile,
    Range,
    SCMCredential,
    UserNGFW,
)

User = get_user_model()


def get_authenticated_client(user):
    """Create a client with OIDC session data set to avoid SessionRefresh redirects."""
    client = Client()
    client.force_login(user)
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()
    return client


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def user(db):
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def user2(db):
    return User.objects.create_user(username="other@example.com", email="other@example.com")


@pytest.fixture
def deployment_profile(user, db):
    """Create a deployment profile for testing."""
    return NGFWDeploymentProfile.objects.create(
        user=user,
        name="Test Deployment Profile",
        authcode="D1234567",
    )


@pytest.fixture
def scm_credential(user, db):
    """Create an SCM credential for testing."""
    return SCMCredential.objects.create(
        user=user,
        name="Test SCM Credential",
        scm_folder_name="test-folder",
        scm_pin_id="pin-123",
        scm_pin_value="secret-pin-value",
        sls_region="americas",
    )


@pytest.fixture
def user_ngfw(user, deployment_profile, scm_credential, db):
    """Create a UserNGFW for testing."""
    return UserNGFW.objects.create(
        user=user,
        name="Test NGFW",
        deployment_profile=deployment_profile,
        scm_credential=scm_credential,
        status=UserNGFW.Status.READY,
    )


@pytest.fixture
def provisioned_ngfw(user, deployment_profile, scm_credential, db):
    """Create a fully provisioned UserNGFW with AWS resources."""
    return UserNGFW.objects.create(
        user=user,
        name="Provisioned NGFW",
        deployment_profile=deployment_profile,
        scm_credential=scm_credential,
        status=UserNGFW.Status.ACTIVE,
        instance_id="i-1234567890abcdef0",
        mgmt_eni_id="eni-mgmt123",
        data_eni_id="eni-data456",
        management_ip="10.0.1.100",
        dataplane_ip="10.0.2.100",
        gwlb_arn="arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/gwy/test-gwlb/abc123",
        target_group_arn="arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/test-tg/def456",
        gwlb_service_name="com.amazonaws.vpce.us-east-1.vpce-svc-abc123",
        serial_number="001234567890",
        device_cert_status="valid",
        xdr_configured=True,
        provisioned_at=timezone.now(),
    )


# -----------------------------------------------------------------------------
# NGFW List View Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWListView:
    """Tests for the NGFW list view at /mission-control/assets/ngfw/."""

    def test_requires_login(self, client, db):
        """Unauthenticated users should be redirected to login."""
        response = client.get(reverse("mission_control:ngfw_list"))
        assert response.status_code == 302
        assert "/oidc/authenticate/" in response.url or "login" in response.url.lower()

    def test_requires_get(self, user, db):
        """POST requests should return 405 Method Not Allowed."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:ngfw_list"))
        assert response.status_code == 405

    def test_renders_list_with_no_ngfws(self, user, db):
        """Empty state should be shown when user has no NGFWs."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_list"))

        assert response.status_code == 200
        assert response.context["page_title"] == "NGFWs"
        assert response.context["active_nav"] == "ngfw"
        assert len(response.context["ngfws"]) == 0

    def test_renders_list_with_ngfws(self, user, user_ngfw, db):
        """NGFWs should be listed when user has them."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_list"))

        assert response.status_code == 200
        assert len(response.context["ngfws"]) == 1
        assert response.context["ngfws"][0].name == "Test NGFW"

    def test_shows_status_badges(self, user, user_ngfw, db):
        """NGFWs in context should have accessible status attributes."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_list"))

        assert response.status_code == 200
        ngfws = list(response.context["ngfws"])
        assert len(ngfws) == 1
        # Verify status is accessible and correct
        assert ngfws[0].status == UserNGFW.Status.READY
        assert ngfws[0].get_status_display() == "Ready"

    def test_excludes_deleted_ngfws(self, user, user_ngfw, db):
        """Soft-deleted NGFWs should not appear in the list."""
        # Soft delete the NGFW
        user_ngfw.deleted_at = timezone.now()
        user_ngfw.save()

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_list"))

        assert response.status_code == 200
        assert len(response.context["ngfws"]) == 0

    def test_excludes_other_users_ngfws(self, user, user2, deployment_profile, db):
        """User should only see their own NGFWs, not other users'."""
        # Create NGFW for user1 (the requesting user)
        UserNGFW.objects.create(
            user=user,
            name="User1 NGFW",
            deployment_profile=deployment_profile,
            status=UserNGFW.Status.READY,
        )

        # Create deployment profile and NGFW for user2
        dp2 = NGFWDeploymentProfile.objects.create(
            user=user2,
            name="User2 Deployment Profile",
            authcode="D7654321",
        )
        UserNGFW.objects.create(
            user=user2,
            name="User2 NGFW",
            deployment_profile=dp2,
            status=UserNGFW.Status.READY,
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_list"))

        assert response.status_code == 200
        # User should see exactly 1 NGFW (their own)
        ngfws = list(response.context["ngfws"])
        assert len(ngfws) == 1
        assert ngfws[0].name == "User1 NGFW"
        assert ngfws[0].user_id == user.id


# -----------------------------------------------------------------------------
# NGFW Detail View Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWDetailView:
    """Tests for the NGFW detail view at /mission-control/assets/ngfw/<id>/."""

    def test_requires_login(self, client, user_ngfw, db):
        """Unauthenticated users should be redirected to login."""
        response = client.get(reverse("mission_control:ngfw_detail", args=[user_ngfw.id]))
        assert response.status_code == 302

    def test_requires_get(self, user, user_ngfw, db):
        """POST requests should return 405 Method Not Allowed."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:ngfw_detail", args=[user_ngfw.id]))
        assert response.status_code == 405

    def test_404_for_nonexistent(self, user, db):
        """Non-existent NGFW ID should return 404."""
        client = get_authenticated_client(user)
        # Use dynamic non-existent ID instead of magic number
        max_id = UserNGFW.objects.order_by("-id").values_list("id", flat=True).first() or 0
        nonexistent_id = max_id + 1
        response = client.get(reverse("mission_control:ngfw_detail", args=[nonexistent_id]))
        assert response.status_code == 404

    def test_404_for_other_users_ngfw(self, user, user2, deployment_profile, db):
        """User should not be able to view another user's NGFW."""
        # Create deployment profile for user2
        dp2 = NGFWDeploymentProfile.objects.create(
            user=user2,
            name="User2 Deployment Profile",
            authcode="D7654321",
        )
        other_ngfw = UserNGFW.objects.create(
            user=user2,
            name="Other User NGFW",
            deployment_profile=dp2,
            status=UserNGFW.Status.READY,
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_detail", args=[other_ngfw.id]))
        assert response.status_code == 404

    def test_renders_detail(self, user, user_ngfw, db):
        """Detail view should render with correct context."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_detail", args=[user_ngfw.id]))

        assert response.status_code == 200
        assert response.context["page_title"] == "Test NGFW"
        assert response.context["active_nav"] == "ngfw"
        assert response.context["ngfw"].id == user_ngfw.id

    def test_shows_aws_resources(self, user, provisioned_ngfw, db):
        """AWS resource info should be displayed."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_detail", args=[provisioned_ngfw.id]))

        assert response.status_code == 200
        content = response.content.decode()
        assert "i-1234567890abcdef0" in content  # Instance ID
        assert "10.0.1.100" in content  # Management IP

    def test_shows_panos_info(self, user, provisioned_ngfw, db):
        """PAN-OS info (serial number, device cert) should be displayed."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_detail", args=[provisioned_ngfw.id]))

        assert response.status_code == 200
        content = response.content.decode()
        assert "001234567890" in content  # Serial number

    def test_shows_linked_ranges(self, user, provisioned_ngfw, db):
        """Ranges linked to this NGFW should be displayed."""
        from mission_control.models import AgentConfig, OperatingSystem

        # Create an agent and range linked to this NGFW
        windows_os = OperatingSystem.objects.get(slug="windows")
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test Agent",
            s3_key="agents/1/test.msi",
            original_filename="test.msi",
            file_size_bytes=1000,
            sha256_hash="test",
        )
        Range.objects.create(
            user=user,
            agent=agent,
            ngfw=provisioned_ngfw,
            status=Range.Status.READY,
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_detail", args=[provisioned_ngfw.id]))

        assert response.status_code == 200
        assert len(response.context["linked_ranges"]) == 1


# -----------------------------------------------------------------------------
# NGFW Wizard View Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWWizardView:
    """Tests for the NGFW setup wizard at /mission-control/assets/ngfw/setup/."""

    def test_requires_login(self, client, db):
        """Unauthenticated users should be redirected to login."""
        response = client.get(reverse("mission_control:ngfw_wizard"))
        assert response.status_code == 302

    def test_requires_get(self, user, db):
        """POST requests should return 405 Method Not Allowed."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:ngfw_wizard"))
        assert response.status_code == 405

    def test_renders_wizard(self, user, db):
        """Wizard should render with correct context."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_wizard"))

        assert response.status_code == 200
        assert response.context["page_title"] == "Setup NGFW"
        assert response.context["active_nav"] == "ngfw"

    def test_lists_scm_credentials(self, user, scm_credential, db):
        """User's SCM credentials should be available in context."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_wizard"))

        assert response.status_code == 200
        assert len(response.context["scm_credentials"]) == 1
        assert response.context["scm_credentials"][0].name == "Test SCM Credential"

    def test_lists_deployment_profiles(self, user, deployment_profile, db):
        """User's deployment profiles should be available in context."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_wizard"))

        assert response.status_code == 200
        assert len(response.context["deployment_profiles"]) == 1
        assert response.context["deployment_profiles"][0].name == "Test Deployment Profile"

    def test_excludes_expired_credentials(self, user, db):
        """Expired credentials should not be listed."""
        # Create expired SCM credential
        SCMCredential.objects.create(
            user=user,
            name="Expired Credential",
            scm_folder_name="expired-folder",
            scm_pin_id="pin-expired",
            scm_pin_value="expired-value",
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_wizard"))

        assert response.status_code == 200
        # Expired credential should not appear
        cred_names = [c.name for c in response.context["scm_credentials"]]
        assert "Expired Credential" not in cred_names


# -----------------------------------------------------------------------------
# NGFW Deprovision View Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWDeprovisionView:
    """Tests for the NGFW deprovision confirmation at /mission-control/assets/ngfw/<id>/deprovision/."""

    def test_requires_login(self, client, user_ngfw, db):
        """Unauthenticated users should be redirected to login."""
        response = client.get(reverse("mission_control:ngfw_deprovision", args=[user_ngfw.id]))
        assert response.status_code == 302

    def test_requires_get(self, user, user_ngfw, db):
        """POST requests should return 405 (use API endpoint for actual deprovision)."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:ngfw_deprovision", args=[user_ngfw.id]))
        assert response.status_code == 405

    def test_renders_confirmation(self, user, user_ngfw, db):
        """Deprovision confirmation should render."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_deprovision", args=[user_ngfw.id]))

        assert response.status_code == 200
        assert response.context["ngfw"].id == user_ngfw.id
        content = response.content.decode()
        # Warning text should appear
        assert "deactivate" in content.lower() or "deprovision" in content.lower()

    def test_shows_linked_ranges_warning(self, user, provisioned_ngfw, db):
        """Warning should show linked ranges."""
        from mission_control.models import AgentConfig, OperatingSystem

        # Create a range linked to this NGFW
        windows_os = OperatingSystem.objects.get(slug="windows")
        agent = AgentConfig.objects.create(
            user=user,
            os=windows_os,
            name="Test Agent",
            s3_key="agents/1/test.msi",
            original_filename="test.msi",
            file_size_bytes=1000,
            sha256_hash="test",
        )
        Range.objects.create(
            user=user,
            agent=agent,
            ngfw=provisioned_ngfw,
            status=Range.Status.READY,
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_deprovision", args=[provisioned_ngfw.id]))

        assert response.status_code == 200
        assert len(response.context["linked_ranges"]) == 1

    def test_404_for_other_users_ngfw(self, user, user2, db):
        """User should not be able to deprovision another user's NGFW."""
        dp2 = NGFWDeploymentProfile.objects.create(
            user=user2,
            name="User2 Deployment Profile",
            authcode="D7654321",
        )
        other_ngfw = UserNGFW.objects.create(
            user=user2,
            name="Other User NGFW",
            deployment_profile=dp2,
            status=UserNGFW.Status.READY,
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:ngfw_deprovision", args=[other_ngfw.id]))
        assert response.status_code == 404


# -----------------------------------------------------------------------------
# NGFW Provision API Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWProvisionAPI:
    """Tests for the NGFW provision API at POST /mission-control/api/ngfw/."""

    def test_requires_login(self, client, db):
        """Unauthenticated users should be redirected or get 401."""
        response = client.post(reverse("mission_control:api_ngfw_provision"))
        assert response.status_code in [302, 401, 403]

    def test_requires_post(self, user, db):
        """GET requests should return 405 Method Not Allowed."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_provision"))
        assert response.status_code == 405

    def test_validates_required_fields(self, user, deployment_profile, db):
        """Missing required fields should return 400 with specific field errors."""
        client = get_authenticated_client(user)

        # Test completely empty body
        response = client.post(
            reverse("mission_control:api_ngfw_provision"),
            data={},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data or "errors" in data

        # Test missing name field
        response = client.post(
            reverse("mission_control:api_ngfw_provision"),
            data={
                "deployment_profile_id": deployment_profile.id,
                "registration_method": "otp",
                "otp_value": "123456",
                "otp_folder": "folder",
                "sls_region": "americas",
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "name" in str(data).lower() or "error" in data

        # Test missing deployment_profile_id
        response = client.post(
            reverse("mission_control:api_ngfw_provision"),
            data={
                "name": "Test NGFW",
                "registration_method": "otp",
                "otp_value": "123456",
                "otp_folder": "folder",
                "sls_region": "americas",
            },
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_creates_ngfw_record(self, user, deployment_profile, db):
        """Valid request should create a UserNGFW record and return its ID."""
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:api_ngfw_provision"),
            data={
                "name": "New NGFW",
                "deployment_profile_id": deployment_profile.id,
                "registration_method": "otp",
                "otp_value": "123456",
                "otp_folder": "my-folder",
                "sls_region": "americas",
            },
            content_type="application/json",
        )
        assert response.status_code == 201

        # Verify database record was created
        assert UserNGFW.objects.filter(name="New NGFW", user=user).exists()
        ngfw = UserNGFW.objects.get(name="New NGFW", user=user)

        # Verify response contains correct data
        data = response.json()
        assert "id" in data
        assert data["id"] == ngfw.id
        assert "name" in data
        assert data["name"] == "New NGFW"

    def test_creates_with_scm_credential(self, user, deployment_profile, scm_credential, db):
        """Can provision using existing SCM credential (PIN method)."""
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:api_ngfw_provision"),
            data={
                "name": "PIN NGFW",
                "deployment_profile_id": deployment_profile.id,
                "registration_method": "pin",
                "scm_credential_id": scm_credential.id,
            },
            content_type="application/json",
        )
        assert response.status_code == 201
        ngfw = UserNGFW.objects.get(name="PIN NGFW")
        assert ngfw.scm_credential_id == scm_credential.id

    def test_400_for_invalid_deployment_profile_id(self, user, db):
        """Invalid deployment_profile_id should return 400."""
        client = get_authenticated_client(user)
        # Use ID that doesn't exist
        max_id = NGFWDeploymentProfile.objects.order_by("-id").values_list("id", flat=True).first() or 0
        response = client.post(
            reverse("mission_control:api_ngfw_provision"),
            data={
                "name": "Test NGFW",
                "deployment_profile_id": max_id + 999,
                "registration_method": "otp",
                "otp_value": "123456",
                "otp_folder": "folder",
                "sls_region": "americas",
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data or "deployment_profile" in str(data).lower()

    def test_400_for_invalid_scm_credential_id(self, user, deployment_profile, db):
        """Invalid scm_credential_id should return 400."""
        client = get_authenticated_client(user)
        # Use ID that doesn't exist
        max_id = SCMCredential.objects.order_by("-id").values_list("id", flat=True).first() or 0
        response = client.post(
            reverse("mission_control:api_ngfw_provision"),
            data={
                "name": "Test NGFW",
                "deployment_profile_id": deployment_profile.id,
                "registration_method": "pin",
                "scm_credential_id": max_id + 999,
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data or "scm_credential" in str(data).lower()


# -----------------------------------------------------------------------------
# NGFW List API Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWListAPI:
    """Tests for the NGFW list API at GET /mission-control/api/ngfw/list/."""

    def test_requires_login(self, client, db):
        """Unauthenticated users should be redirected or get 401."""
        response = client.get(reverse("mission_control:api_ngfw_list"))
        assert response.status_code in [302, 401, 403]

    def test_requires_get(self, user, db):
        """POST requests should return 405 Method Not Allowed."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_list"))
        assert response.status_code == 405

    def test_returns_empty_list(self, user, db):
        """Should return empty list when user has no NGFWs."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_list"))

        assert response.status_code == 200
        data = response.json()
        assert "ngfws" in data
        assert data["ngfws"] == []

    def test_returns_user_ngfws(self, user, user_ngfw, db):
        """Should return user's NGFWs with id, name, status."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_list"))

        assert response.status_code == 200
        data = response.json()
        assert "ngfws" in data
        assert len(data["ngfws"]) == 1
        ngfw_data = data["ngfws"][0]
        assert ngfw_data["id"] == user_ngfw.id
        assert ngfw_data["name"] == "Test NGFW"
        assert ngfw_data["status"] == "ready"

    def test_excludes_other_users_ngfws(self, user, user2, deployment_profile, db):
        """Should not return other user's NGFWs."""
        # Create NGFW for user1
        UserNGFW.objects.create(
            user=user,
            name="User1 NGFW",
            deployment_profile=deployment_profile,
            status=UserNGFW.Status.READY,
        )

        # Create deployment profile and NGFW for user2
        dp2 = NGFWDeploymentProfile.objects.create(
            user=user2,
            name="User2 Deployment Profile",
            authcode="D7654321",
        )
        UserNGFW.objects.create(
            user=user2,
            name="User2 NGFW",
            deployment_profile=dp2,
            status=UserNGFW.Status.READY,
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_list"))

        assert response.status_code == 200
        data = response.json()
        assert len(data["ngfws"]) == 1
        assert data["ngfws"][0]["name"] == "User1 NGFW"

    def test_excludes_deleted_ngfws(self, user, user_ngfw, db):
        """Should not return soft-deleted NGFWs."""
        # Soft delete the NGFW
        user_ngfw.deleted_at = timezone.now()
        user_ngfw.save()

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_list"))

        assert response.status_code == 200
        data = response.json()
        assert data["ngfws"] == []


# -----------------------------------------------------------------------------
# NGFW Status API Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWStatusAPI:
    """Tests for the NGFW status API at GET /mission-control/api/ngfw/<id>/status/."""

    def test_requires_login(self, client, user_ngfw, db):
        """Unauthenticated users should be redirected or get 401."""
        response = client.get(reverse("mission_control:api_ngfw_status", args=[user_ngfw.id]))
        assert response.status_code in [302, 401, 403]

    def test_returns_status(self, user, user_ngfw, db):
        """Should return current NGFW status."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_status", args=[user_ngfw.id]))

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "ready"

    def test_returns_provisioning_progress(self, user, deployment_profile, db):
        """Should return progress for provisioning NGFWs."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="Provisioning NGFW",
            deployment_profile=deployment_profile,
            status=UserNGFW.Status.PROVISIONING,
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_status", args=[ngfw.id]))

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "provisioning"

    def test_404_for_other_users_ngfw(self, user, user2, db):
        """User should not see another user's NGFW status."""
        dp2 = NGFWDeploymentProfile.objects.create(
            user=user2,
            name="User2 Profile",
            authcode="D7654321",
        )
        other_ngfw = UserNGFW.objects.create(
            user=user2,
            name="Other NGFW",
            deployment_profile=dp2,
            status=UserNGFW.Status.READY,
        )

        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_status", args=[other_ngfw.id]))
        assert response.status_code == 404


# -----------------------------------------------------------------------------
# NGFW Start API Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWStartAPI:
    """Tests for the NGFW start API at POST /mission-control/api/ngfw/<id>/start/."""

    def test_requires_login(self, client, user_ngfw, db):
        """Unauthenticated users should be redirected or get 401."""
        response = client.post(reverse("mission_control:api_ngfw_start", args=[user_ngfw.id]))
        assert response.status_code in [302, 401, 403]

    def test_requires_post(self, user, user_ngfw, db):
        """GET requests should return 405 Method Not Allowed."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_start", args=[user_ngfw.id]))
        assert response.status_code == 405

    def test_starts_stopped_ngfw(self, user, deployment_profile, db):
        """Should start a stopped NGFW - transitions to running state."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="Stopped NGFW",
            deployment_profile=deployment_profile,
            status=UserNGFW.Status.STOPPED,
            instance_id="i-123456",
        )

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_start", args=[ngfw.id]))

        assert response.status_code == 200
        ngfw.refresh_from_db()
        # Status should be ACTIVE (sync implementation) or STARTING (async implementation)
        assert ngfw.status in [UserNGFW.Status.ACTIVE, UserNGFW.Status.STARTING]
        # For sync implementation, verify final state
        if ngfw.status == UserNGFW.Status.ACTIVE:
            assert ngfw.status != UserNGFW.Status.STOPPED  # Not still stopped

    def test_starts_ready_ngfw(self, user, user_ngfw, db):
        """Should start a ready NGFW - transitions to running state."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_start", args=[user_ngfw.id]))

        assert response.status_code == 200
        user_ngfw.refresh_from_db()
        # Status should be ACTIVE (sync implementation) or STARTING (async implementation)
        assert user_ngfw.status in [UserNGFW.Status.ACTIVE, UserNGFW.Status.STARTING]

    def test_400_for_already_active(self, user, provisioned_ngfw, db):
        """Starting an already active NGFW should return 400."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_start", args=[provisioned_ngfw.id]))

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_400_for_provisioning_ngfw(self, user, deployment_profile, db):
        """Cannot start an NGFW that is still provisioning."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="Provisioning NGFW",
            deployment_profile=deployment_profile,
            status=UserNGFW.Status.PROVISIONING,
        )

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_start", args=[ngfw.id]))

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_404_for_other_users_ngfw(self, user, user2, db):
        """User should not be able to start another user's NGFW."""
        dp2 = NGFWDeploymentProfile.objects.create(
            user=user2,
            name="User2 Profile",
            authcode="D7654321",
        )
        other_ngfw = UserNGFW.objects.create(
            user=user2,
            name="Other NGFW",
            deployment_profile=dp2,
            status=UserNGFW.Status.STOPPED,
        )

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_start", args=[other_ngfw.id]))
        assert response.status_code == 404


# -----------------------------------------------------------------------------
# NGFW Stop API Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWStopAPI:
    """Tests for the NGFW stop API at POST /mission-control/api/ngfw/<id>/stop/."""

    def test_requires_login(self, client, user_ngfw, db):
        """Unauthenticated users should be redirected or get 401."""
        response = client.post(reverse("mission_control:api_ngfw_stop", args=[user_ngfw.id]))
        assert response.status_code in [302, 401, 403]

    def test_requires_post(self, user, user_ngfw, db):
        """GET requests should return 405 Method Not Allowed."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_stop", args=[user_ngfw.id]))
        assert response.status_code == 405

    def test_stops_active_ngfw(self, user, provisioned_ngfw, db):
        """Should stop an active NGFW - transitions to stopped state."""
        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_stop", args=[provisioned_ngfw.id]))

        assert response.status_code == 200
        provisioned_ngfw.refresh_from_db()
        # Status should be STOPPED (sync implementation) or STOPPING (async implementation)
        assert provisioned_ngfw.status in [UserNGFW.Status.STOPPED, UserNGFW.Status.STOPPING]
        # Verify it's no longer ACTIVE
        assert provisioned_ngfw.status != UserNGFW.Status.ACTIVE

    def test_400_for_already_stopped(self, user, deployment_profile, db):
        """Stopping an already stopped NGFW should return 400."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="Stopped NGFW",
            deployment_profile=deployment_profile,
            status=UserNGFW.Status.STOPPED,
        )

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_stop", args=[ngfw.id]))

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_400_for_provisioning_ngfw(self, user, deployment_profile, db):
        """Cannot stop an NGFW that is still provisioning."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="Provisioning NGFW",
            deployment_profile=deployment_profile,
            status=UserNGFW.Status.PROVISIONING,
        )

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_stop", args=[ngfw.id]))

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_404_for_other_users_ngfw(self, user, user2, db):
        """User should not be able to stop another user's NGFW."""
        dp2 = NGFWDeploymentProfile.objects.create(
            user=user2,
            name="User2 Profile",
            authcode="D7654321",
        )
        other_ngfw = UserNGFW.objects.create(
            user=user2,
            name="Other NGFW",
            deployment_profile=dp2,
            status=UserNGFW.Status.ACTIVE,
        )

        client = get_authenticated_client(user)
        response = client.post(reverse("mission_control:api_ngfw_stop", args=[other_ngfw.id]))
        assert response.status_code == 404


# -----------------------------------------------------------------------------
# NGFW Deprovision API Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestNGFWDeprovisionAPI:
    """Tests for the NGFW deprovision API at POST /mission-control/api/ngfw/<id>/deprovision/."""

    def test_requires_login(self, client, user_ngfw, db):
        """Unauthenticated users should be redirected or get 401."""
        response = client.post(reverse("mission_control:api_ngfw_deprovision", args=[user_ngfw.id]))
        assert response.status_code in [302, 401, 403]

    def test_requires_post(self, user, user_ngfw, db):
        """GET requests should return 405 Method Not Allowed."""
        client = get_authenticated_client(user)
        response = client.get(reverse("mission_control:api_ngfw_deprovision", args=[user_ngfw.id]))
        assert response.status_code == 405

    def test_requires_confirmation(self, user, user_ngfw, db):
        """Deprovision should require name confirmation."""
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:api_ngfw_deprovision", args=[user_ngfw.id]),
            data={},
            content_type="application/json",
        )

        # Should fail without confirmation
        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_wrong_confirmation_rejected(self, user, user_ngfw, db):
        """Deprovision should reject wrong name confirmation."""
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:api_ngfw_deprovision", args=[user_ngfw.id]),
            data={"confirm_name": "Wrong Name"},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_deprovisions_ngfw(self, user, user_ngfw, db):
        """Should deprovision NGFW with correct confirmation."""
        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:api_ngfw_deprovision", args=[user_ngfw.id]),
            data={"confirm_name": "Test NGFW"},
            content_type="application/json",
        )

        assert response.status_code == 200
        user_ngfw.refresh_from_db()
        assert user_ngfw.status == UserNGFW.Status.DEPROVISIONING

    def test_404_for_other_users_ngfw(self, user, user2, db):
        """User should not be able to deprovision another user's NGFW."""
        dp2 = NGFWDeploymentProfile.objects.create(
            user=user2,
            name="User2 Profile",
            authcode="D7654321",
        )
        other_ngfw = UserNGFW.objects.create(
            user=user2,
            name="Other NGFW",
            deployment_profile=dp2,
            status=UserNGFW.Status.READY,
        )

        client = get_authenticated_client(user)
        response = client.post(
            reverse("mission_control:api_ngfw_deprovision", args=[other_ngfw.id]),
            data={"confirm_name": "Other NGFW"},
            content_type="application/json",
        )
        assert response.status_code == 404
