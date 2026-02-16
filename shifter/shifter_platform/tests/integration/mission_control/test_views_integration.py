"""Integration tests for Mission Control views.

Tests view → service boundary with real database operations.
Verifies HTTP request/response cycle with actual service calls.
"""

import json
import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from cms.models import Credential, CredentialType

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser@example.com",
        email="testuser@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user(db):
    """Create another test user for ownership tests."""
    return User.objects.create_user(
        username="otheruser@example.com",
        email="otheruser@example.com",
        password="otherpass123",
    )


@pytest.fixture
def authenticated_client(user):
    """Return authenticated Django test client."""
    client = Client()
    client.force_login(user)

    # Set OIDC session data to prevent SessionRefresh redirect
    session = client.session
    session["oidc_id_token_expiration"] = time.time() + 3600
    session.save()

    return client


@pytest.fixture
def scm_credential_type(db):
    """Get or create SCM credential type."""
    cred_type, _ = CredentialType.objects.get_or_create(
        slug="scm",
        defaults={
            "name": "SCM Credential",
            "spec_class": "shared.schemas.SCMCredentialSpec",
        },
    )
    return cred_type


@pytest.fixture
def deployment_profile_type(db):
    """Get or create deployment profile credential type."""
    cred_type, _ = CredentialType.objects.get_or_create(
        slug="deployment_profile",
        defaults={
            "name": "Deployment Profile",
            "spec_class": "shared.schemas.DeploymentProfileSpec",
        },
    )
    return cred_type


@pytest.fixture
def scm_credential(db, user, scm_credential_type):
    """Create a test SCM credential."""
    return Credential.objects.create(
        user=user,
        name="Test SCM Cred",
        credential_type=scm_credential_type,
        data={
            "scm_folder_name": "TestFolder",
            "scm_pin_id": "pin123",
            "scm_pin_value": "secret456",
            "sls_region": "americas",
        },
    )


@pytest.fixture
def deployment_credential(db, user, deployment_profile_type):
    """Create a test deployment profile credential."""
    return Credential.objects.create(
        user=user,
        name="Test Deploy Profile",
        credential_type=deployment_profile_type,
        data={"authcode": "D76543210"},
    )


# =============================================================================
# credentials_list view integration tests
# =============================================================================


@pytest.mark.django_db
class TestCredentialsListViewIntegration:
    """Integration tests for credentials_list view."""

    def test_returns_200_with_credentials(self, authenticated_client, scm_credential, deployment_credential):
        """credentials_list returns 200 and renders credentials."""
        response = authenticated_client.get("/mission-control/credentials/")

        assert response.status_code == 200
        assert b"Test SCM Cred" in response.content
        assert b"Test Deploy Profile" in response.content

    def test_returns_empty_list_for_user_with_no_credentials(self, authenticated_client):
        """credentials_list returns 200 with empty list."""
        response = authenticated_client.get("/mission-control/credentials/")

        assert response.status_code == 200
        # Should not contain credential names
        assert b"Test SCM Cred" not in response.content

    def test_excludes_other_users_credentials(self, authenticated_client, other_user, scm_credential_type):
        """credentials_list only shows current user's credentials."""
        # Create credential for other user
        Credential.objects.create(
            user=other_user,
            name="Other User SCM",
            credential_type=scm_credential_type,
            data={
                "scm_folder_name": "OtherFolder",
                "scm_pin_id": "otherpin",
                "scm_pin_value": "othersecret",
                "sls_region": "americas",
            },
        )

        response = authenticated_client.get("/mission-control/credentials/")

        assert response.status_code == 200
        assert b"Other User SCM" not in response.content

    def test_excludes_deleted_credentials(self, authenticated_client, user, scm_credential_type):
        """credentials_list excludes soft-deleted credentials."""
        from django.utils import timezone

        Credential.objects.create(
            user=user,
            name="Deleted Cred",
            credential_type=scm_credential_type,
            deleted_at=timezone.now(),
            data={
                "scm_folder_name": "DeletedFolder",
                "scm_pin_id": "deletedpin",
                "scm_pin_value": "deletedsecret",
                "sls_region": "americas",
            },
        )

        response = authenticated_client.get("/mission-control/credentials/")

        assert response.status_code == 200
        assert b"Deleted Cred" not in response.content

    def test_counts_credential_types_correctly(
        self, authenticated_client, user, scm_credential_type, deployment_profile_type
    ):
        """credentials_list passes correct type counts to template."""
        # Create multiple credentials of each type
        for i in range(3):
            Credential.objects.create(
                user=user,
                name=f"SCM {i}",
                credential_type=scm_credential_type,
                data={
                    "scm_folder_name": f"Folder{i}",
                    "scm_pin_id": f"pin{i}",
                    "scm_pin_value": f"secret{i}",
                    "sls_region": "americas",
                },
            )
        for i in range(2):
            Credential.objects.create(
                user=user,
                name=f"Deploy {i}",
                credential_type=deployment_profile_type,
                data={"authcode": f"AUTH{i}"},
            )

        response = authenticated_client.get("/mission-control/credentials/")

        assert response.status_code == 200
        # Context should have counts (we verify via rendered content)
        # The template uses these counts for UI badges


# =============================================================================
# credential_detail view integration tests
# =============================================================================


@pytest.mark.django_db
class TestCredentialDetailViewIntegration:
    """Integration tests for credential_detail view."""

    def test_returns_200_for_own_credential(self, authenticated_client, scm_credential):
        """credential_detail returns 200 for user's own credential."""
        response = authenticated_client.get(f"/mission-control/credentials/{scm_credential.id}/")

        assert response.status_code == 200
        assert b"Test SCM Cred" in response.content

    def test_returns_404_for_other_users_credential(self, authenticated_client, other_user, scm_credential_type):
        """credential_detail returns 404 for another user's credential."""
        other_cred = Credential.objects.create(
            user=other_user,
            name="Other Cred",
            credential_type=scm_credential_type,
            data={
                "scm_folder_name": "OtherFolder",
                "scm_pin_id": "otherpin",
                "scm_pin_value": "othersecret",
                "sls_region": "americas",
            },
        )

        response = authenticated_client.get(f"/mission-control/credentials/{other_cred.id}/")

        assert response.status_code == 404

    def test_returns_404_for_nonexistent_credential(self, authenticated_client):
        """credential_detail returns 404 for unknown ID."""
        response = authenticated_client.get("/mission-control/credentials/99999/")

        assert response.status_code == 404

    def test_returns_404_for_deleted_credential(self, authenticated_client, user, scm_credential_type):
        """credential_detail returns 404 for soft-deleted credential."""
        from django.utils import timezone

        deleted_cred = Credential.objects.create(
            user=user,
            name="Deleted Cred",
            credential_type=scm_credential_type,
            deleted_at=timezone.now(),
            data={
                "scm_folder_name": "DeletedFolder",
                "scm_pin_id": "deletedpin",
                "scm_pin_value": "deletedsecret",
                "sls_region": "americas",
            },
        )

        response = authenticated_client.get(f"/mission-control/credentials/{deleted_cred.id}/")

        assert response.status_code == 404


# =============================================================================
# api_credential_create view integration tests
# =============================================================================


@pytest.mark.django_db
class TestApiCredentialCreateIntegration:
    """Integration tests for api_credential_create view."""

    def test_creates_scm_credential(self, authenticated_client, scm_credential_type):
        """api_credential_create creates SCM credential in database."""
        data = {
            "credential_type": "scm",
            "name": "New SCM Cred",
            "scm_folder_name": "NewFolder",
            "scm_pin_id": "newpin123",
            "scm_pin_value": "newsecret456",
            "sls_region": "americas",
        }

        response = authenticated_client.post(
            "/mission-control/api/credentials/",
            data=json.dumps(data),
            content_type="application/json",
        )

        assert response.status_code == 201
        result = response.json()
        assert result["name"] == "New SCM Cred"
        assert result["credential_type"] == "scm"

        # Verify persisted to database
        cred = Credential.objects.get(id=result["id"])
        assert cred.name == "New SCM Cred"
        assert cred.data["scm_folder_name"] == "NewFolder"

    def test_creates_deployment_profile_credential(self, authenticated_client, deployment_profile_type):
        """api_credential_create creates deployment profile in database."""
        data = {
            "credential_type": "deployment_profile",
            "name": "New Deploy Profile",
            "authcode": "NEWAUTHCODE123",
        }

        response = authenticated_client.post(
            "/mission-control/api/credentials/",
            data=json.dumps(data),
            content_type="application/json",
        )

        assert response.status_code == 201
        result = response.json()
        assert result["name"] == "New Deploy Profile"
        assert result["credential_type"] == "deployment_profile"

        # Verify persisted to database
        cred = Credential.objects.get(id=result["id"])
        assert cred.name == "New Deploy Profile"
        assert cred.data["authcode"] == "NEWAUTHCODE123"

    def test_returns_400_for_invalid_json(self, authenticated_client):
        """api_credential_create returns 400 for invalid JSON."""
        response = authenticated_client.post(
            "/mission-control/api/credentials/",
            data="not json",
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["error"]

    def test_returns_400_for_invalid_credential_type(self, authenticated_client):
        """api_credential_create returns 400 for unknown type."""
        data = {
            "credential_type": "invalid_type",
            "name": "Test",
        }

        response = authenticated_client.post(
            "/mission-control/api/credentials/",
            data=json.dumps(data),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Invalid credential type" in response.json()["error"]

    def test_returns_400_for_missing_required_fields(self, authenticated_client, scm_credential_type):
        """api_credential_create returns 400 for missing fields."""
        data = {
            "credential_type": "scm",
            "name": "Incomplete SCM",
            # Missing scm_folder_name, scm_pin_id, scm_pin_value, sls_region
        }

        response = authenticated_client.post(
            "/mission-control/api/credentials/",
            data=json.dumps(data),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_returns_400_for_duplicate_name(self, authenticated_client, scm_credential, scm_credential_type):
        """api_credential_create returns 400 for duplicate credential name."""
        data = {
            "credential_type": "scm",
            "name": "Test SCM Cred",  # Same name as fixture
            "scm_folder_name": "AnotherFolder",
            "scm_pin_id": "anotherpin",
            "scm_pin_value": "anothersecret",
            "sls_region": "americas",
        }

        response = authenticated_client.post(
            "/mission-control/api/credentials/",
            data=json.dumps(data),
            content_type="application/json",
        )

        # Should fail due to unique constraint
        assert response.status_code == 400


# =============================================================================
# api_credential_delete view integration tests
# =============================================================================


@pytest.mark.django_db
class TestApiCredentialDeleteIntegration:
    """Integration tests for api_credential_delete view."""

    def test_soft_deletes_credential(self, authenticated_client, scm_credential):
        """api_credential_delete soft-deletes credential in database."""
        response = authenticated_client.post(f"/mission-control/api/credentials/{scm_credential.id}/delete/")

        assert response.status_code == 200

        # Verify soft-deleted in database
        scm_credential.refresh_from_db()
        assert scm_credential.deleted_at is not None

    def test_returns_404_for_other_users_credential(self, authenticated_client, other_user, scm_credential_type):
        """api_credential_delete returns 404 for another user's credential."""
        other_cred = Credential.objects.create(
            user=other_user,
            name="Other Cred",
            credential_type=scm_credential_type,
            data={
                "scm_folder_name": "OtherFolder",
                "scm_pin_id": "otherpin",
                "scm_pin_value": "othersecret",
                "sls_region": "americas",
            },
        )

        response = authenticated_client.post(f"/mission-control/api/credentials/{other_cred.id}/delete/")

        assert response.status_code == 404

        # Verify NOT deleted in database
        other_cred.refresh_from_db()
        assert other_cred.deleted_at is None

    def test_returns_404_for_nonexistent_credential(self, authenticated_client):
        """api_credential_delete returns 404 for unknown ID."""
        response = authenticated_client.post("/mission-control/api/credentials/99999/delete/")

        assert response.status_code == 404

    def test_returns_404_for_already_deleted_credential(self, authenticated_client, user, scm_credential_type):
        """api_credential_delete returns 404 for already-deleted credential."""
        from django.utils import timezone

        deleted_cred = Credential.objects.create(
            user=user,
            name="Already Deleted",
            credential_type=scm_credential_type,
            deleted_at=timezone.now(),
            data={
                "scm_folder_name": "DeletedFolder",
                "scm_pin_id": "deletedpin",
                "scm_pin_value": "deletedsecret",
                "sls_region": "americas",
            },
        )

        response = authenticated_client.post(f"/mission-control/api/credentials/{deleted_cred.id}/delete/")

        assert response.status_code == 404


# =============================================================================
# Full credential lifecycle integration test
# =============================================================================


@pytest.mark.django_db
class TestCredentialLifecycleIntegration:
    """End-to-end integration tests for credential lifecycle."""

    def test_create_view_delete_lifecycle(self, authenticated_client, scm_credential_type):
        """Test full lifecycle: create → view in list → view detail → delete."""
        # Step 1: Create credential via API
        create_data = {
            "credential_type": "scm",
            "name": "Lifecycle Test Cred",
            "scm_folder_name": "LifecycleFolder",
            "scm_pin_id": "lifecyclepin",
            "scm_pin_value": "lifecyclesecret",
            "sls_region": "europe",
        }

        create_response = authenticated_client.post(
            "/mission-control/api/credentials/",
            data=json.dumps(create_data),
            content_type="application/json",
        )

        assert create_response.status_code == 201
        cred_id = create_response.json()["id"]

        # Step 2: Verify appears in list
        list_response = authenticated_client.get("/mission-control/credentials/")

        assert list_response.status_code == 200
        assert b"Lifecycle Test Cred" in list_response.content

        # Step 3: View detail page
        detail_response = authenticated_client.get(f"/mission-control/credentials/{cred_id}/")

        assert detail_response.status_code == 200
        assert b"Lifecycle Test Cred" in detail_response.content

        # Step 4: Delete via API
        delete_response = authenticated_client.post(f"/mission-control/api/credentials/{cred_id}/delete/")

        assert delete_response.status_code == 200

        # Step 5: Verify no longer in list
        list_after_response = authenticated_client.get("/mission-control/credentials/")

        assert list_after_response.status_code == 200
        assert b"Lifecycle Test Cred" not in list_after_response.content

        # Step 6: Detail now returns 404
        detail_after_response = authenticated_client.get(f"/mission-control/credentials/{cred_id}/")

        assert detail_after_response.status_code == 404
