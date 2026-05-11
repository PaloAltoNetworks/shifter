"""Tests for cms.services credential functions.

Tests the credential service layer that returns Pydantic schema projections.
Uses real database objects via Django's test client infrastructure.
"""

import json

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone

from cms import services
from cms.credential_encryption import ENCRYPTED_VALUE_PREFIX
from cms.exceptions import CMSError
from cms.models import Credential, CredentialType
from shared.schemas import (
    CredentialRef,
    DeploymentProfileContext,
    SCMCredentialContext,
)


def get_raw_credential_data(credential_id: int) -> dict:
    """Read credential data directly from the database, bypassing model decryption."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT data FROM cms_credential WHERE id = %s", [credential_id])
        raw_data = cursor.fetchone()[0]
    return json.loads(raw_data) if isinstance(raw_data, str) else raw_data


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user(db):
    """Create another test user for ownership tests."""
    return User.objects.create_user(
        username="otheruser",
        email="other@example.com",
        password="otherpass123",
    )


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
        name="Test SCM",
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
        name="Test Deployment",
        credential_type=deployment_profile_type,
        data={"authcode": "D76543210"},
    )


# =============================================================================
# create_credential tests
# =============================================================================


@pytest.mark.django_db
class TestCreateCredential:
    """Tests for create_credential service function."""

    def test_create_scm_credential_returns_ref(self, user, scm_credential_type):
        """create_credential returns CredentialRef for SCM type."""
        result = services.create_credential(
            user=user,
            credential_type_slug="scm",
            name="My SCM Cred",
            scm_folder_name="MyFolder",
            scm_pin_id="pin999",
            scm_pin_value="secret999",
            sls_region="europe",
        )

        assert isinstance(result, CredentialRef)
        assert result.credential_id > 0
        assert result.user_id == user.id
        assert result.is_deleted is False

    def test_create_deployment_credential_returns_ref(self, user, deployment_profile_type):
        """create_credential returns CredentialRef for deployment profile type."""
        result = services.create_credential(
            user=user,
            credential_type_slug="deployment_profile",
            name="My Deployment",
            authcode="AUTH123456",
        )

        assert isinstance(result, CredentialRef)
        assert result.credential_id > 0
        assert result.user_id == user.id
        assert result.is_deleted is False

    def test_create_credential_persists_data(self, user, scm_credential_type):
        """create_credential persists credential data to database."""
        result = services.create_credential(
            user=user,
            credential_type_slug="scm",
            name="Persisted SCM",
            scm_folder_name="PersistFolder",
            scm_pin_id="persistpin",
            scm_pin_value="persistsecret",
            sls_region="japan",
        )

        # Verify persisted to database
        cred = Credential.objects.get(id=result.credential_id)
        assert cred.name == "Persisted SCM"
        assert cred.user == user
        assert cred.data["scm_folder_name"] == "PersistFolder"
        assert cred.data["scm_pin_id"] == "persistpin"
        assert cred.data["scm_pin_value"] == "persistsecret"
        assert cred.data["sls_region"] == "japan"

    def test_create_scm_credential_encrypts_pin_at_rest(self, user, scm_credential_type):
        """SCM PIN values are encrypted in raw database JSON."""
        secret = "pin-secret-at-rest"

        result = services.create_credential(
            user=user,
            credential_type_slug="scm",
            name="Encrypted SCM",
            scm_folder_name="EncryptedFolder",
            scm_pin_id="encryptedpin",
            scm_pin_value=secret,
            sls_region="americas",
        )

        raw_data = get_raw_credential_data(result.credential_id)
        assert raw_data["scm_pin_value"] != secret
        assert raw_data["scm_pin_value"].startswith(ENCRYPTED_VALUE_PREFIX)

        cred = Credential.objects.get(id=result.credential_id)
        assert cred.data["scm_pin_value"] == secret

    def test_create_deployment_credential_encrypts_authcode_at_rest(self, user, deployment_profile_type):
        """Deployment profile authcodes are encrypted in raw database JSON."""
        secret = "AUTHCODE-SECRET"

        result = services.create_credential(
            user=user,
            credential_type_slug="deployment_profile",
            name="Encrypted Deployment",
            authcode=secret,
        )

        raw_data = get_raw_credential_data(result.credential_id)
        assert raw_data["authcode"] != secret
        assert raw_data["authcode"].startswith(ENCRYPTED_VALUE_PREFIX)

        cred = Credential.objects.get(id=result.credential_id)
        assert cred.data["authcode"] == secret

    def test_create_credential_with_expires_at(self, user, scm_credential_type):
        """create_credential accepts optional expires_at parameter."""
        expires = timezone.now() + timezone.timedelta(days=30)
        result = services.create_credential(
            user=user,
            credential_type_slug="scm",
            name="Expiring SCM",
            scm_folder_name="ExpFolder",
            scm_pin_id="exppin",
            scm_pin_value="expsecret",
            sls_region="americas",
            expires_at=expires,
        )

        cred = Credential.objects.get(id=result.credential_id)
        assert cred.expires_at is not None

    def test_create_credential_none_user_raises_type_error(self, scm_credential_type):
        """create_credential with None user raises TypeError."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.create_credential(
                user=None,
                credential_type_slug="scm",
                name="Test",
                scm_folder_name="Folder",
                scm_pin_id="pin",
                scm_pin_value="secret",
                sls_region="americas",
            )

    def test_create_credential_invalid_user_type_raises_type_error(self, scm_credential_type):
        """create_credential with non-User object raises TypeError."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.create_credential(
                user="not_a_user",
                credential_type_slug="scm",
                name="Test",
                scm_folder_name="Folder",
                scm_pin_id="pin",
                scm_pin_value="secret",
                sls_region="americas",
            )

    def test_create_credential_unsaved_user_raises_value_error(self, scm_credential_type):
        """create_credential with unsaved user raises ValueError."""
        unsaved_user = User(username="unsaved")
        with pytest.raises(ValueError, match="must be saved"):
            services.create_credential(
                user=unsaved_user,
                credential_type_slug="scm",
                name="Test",
                scm_folder_name="Folder",
                scm_pin_id="pin",
                scm_pin_value="secret",
                sls_region="americas",
            )

    def test_create_credential_invalid_type_slug_raises_cms_error(self, user):
        """create_credential with unknown type slug raises CMSError."""
        with pytest.raises(CMSError, match="not found"):
            services.create_credential(
                user=user,
                credential_type_slug="unknown_type",
                name="Test",
            )

    def test_create_credential_none_type_slug_raises_value_error(self, user):
        """create_credential with None type slug raises ValueError."""
        with pytest.raises(ValueError, match="cannot be None"):
            services.create_credential(
                user=user,
                credential_type_slug=None,
                name="Test",
            )

    def test_create_credential_missing_name_raises_value_error(self, user, scm_credential_type):
        """create_credential without name raises ValueError."""
        with pytest.raises(ValueError, match="name is required"):
            services.create_credential(
                user=user,
                credential_type_slug="scm",
                scm_folder_name="Folder",
                scm_pin_id="pin",
                scm_pin_value="secret",
                sls_region="americas",
            )


# =============================================================================
# delete_credential tests
# =============================================================================


@pytest.mark.django_db
class TestDeleteCredential:
    """Tests for delete_credential service function."""

    def test_delete_credential_returns_ref_with_is_deleted_true(self, user, scm_credential):
        """delete_credential returns CredentialRef with is_deleted=True."""
        result = services.delete_credential(user=user, credential_id=scm_credential.id)

        assert isinstance(result, CredentialRef)
        assert result.credential_id == scm_credential.id
        assert result.user_id == user.id
        assert result.is_deleted is True

    def test_delete_credential_soft_deletes_in_database(self, user, scm_credential):
        """delete_credential sets deleted_at in database."""
        services.delete_credential(user=user, credential_id=scm_credential.id)

        scm_credential.refresh_from_db()
        assert scm_credential.deleted_at is not None

    def test_delete_credential_not_found_raises_cms_error(self, user):
        """delete_credential with non-existent ID raises CMSError."""
        with pytest.raises(CMSError, match="not found"):
            services.delete_credential(user=user, credential_id=99999)

    def test_delete_credential_wrong_owner_raises_cms_error(self, other_user, scm_credential):
        """delete_credential for credential owned by another user raises CMSError."""
        with pytest.raises(CMSError, match="not found"):
            services.delete_credential(user=other_user, credential_id=scm_credential.id)

    def test_delete_credential_already_deleted_raises_cms_error(self, user, scm_credential):
        """delete_credential for already-deleted credential raises CMSError."""
        # Delete once
        services.delete_credential(user=user, credential_id=scm_credential.id)

        # Try to delete again
        with pytest.raises(CMSError, match="not found"):
            services.delete_credential(user=user, credential_id=scm_credential.id)

    def test_delete_credential_none_user_raises_type_error(self, scm_credential):
        """delete_credential with None user raises TypeError."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.delete_credential(user=None, credential_id=scm_credential.id)

    def test_delete_credential_none_id_raises_type_error(self, user):
        """delete_credential with None credential_id raises TypeError."""
        with pytest.raises(TypeError, match="credential_id cannot be None"):
            services.delete_credential(user=user, credential_id=None)

    def test_delete_credential_invalid_id_type_raises_type_error(self, user):
        """delete_credential with non-int credential_id raises TypeError."""
        with pytest.raises(TypeError, match="credential_id must be an int"):
            services.delete_credential(user=user, credential_id="not_an_int")

    def test_delete_credential_negative_id_raises_value_error(self, user):
        """delete_credential with negative credential_id raises ValueError."""
        with pytest.raises(ValueError, match="must be non-negative"):
            services.delete_credential(user=user, credential_id=-1)


# =============================================================================
# list_credentials tests
# =============================================================================


@pytest.mark.django_db
class TestListCredentials:
    """Tests for list_credentials service function."""

    def test_list_credentials_returns_list_of_contexts(self, user, scm_credential, deployment_credential):
        """list_credentials returns list of CredentialContext objects."""
        result = services.list_credentials(user=user)

        assert isinstance(result, list)
        assert len(result) == 2

        # Each item is a typed context
        types = {type(ctx) for ctx in result}
        assert SCMCredentialContext in types
        assert DeploymentProfileContext in types

    def test_list_credentials_scm_context_has_correct_fields(self, user, scm_credential):
        """list_credentials returns SCMCredentialContext with correct fields."""
        result = services.list_credentials(user=user)

        scm_ctx = next(ctx for ctx in result if isinstance(ctx, SCMCredentialContext))

        assert scm_ctx.credential_id == scm_credential.id
        assert scm_ctx.name == scm_credential.name
        assert scm_ctx.user_id == user.id
        assert scm_ctx.credential_type == "scm"
        assert scm_ctx.scm_folder_name == "TestFolder"
        assert scm_ctx.scm_pin_id == "pin123"
        assert scm_ctx.sls_region == "americas"
        # Secret (scm_pin_value) should NOT be in context
        assert not hasattr(scm_ctx, "scm_pin_value")

    def test_list_credentials_deployment_context_has_masked_authcode(self, user, deployment_credential):
        """list_credentials returns DeploymentProfileContext with masked authcode."""
        result = services.list_credentials(user=user)

        dp_ctx = next(ctx for ctx in result if isinstance(ctx, DeploymentProfileContext))

        assert dp_ctx.credential_id == deployment_credential.id
        assert dp_ctx.name == deployment_credential.name
        assert dp_ctx.credential_type == "deployment_profile"
        # Authcode should be masked (first 5 chars + ***)
        assert dp_ctx.authcode_masked == "D7654***"
        # Full authcode should NOT be in context
        assert not hasattr(dp_ctx, "authcode")

    def test_list_credentials_excludes_deleted(self, user, scm_credential, deployment_credential):
        """list_credentials excludes soft-deleted credentials."""
        # Delete one credential
        services.delete_credential(user=user, credential_id=scm_credential.id)

        result = services.list_credentials(user=user)

        assert len(result) == 1
        assert result[0].credential_id == deployment_credential.id

    def test_list_credentials_empty_for_user_with_no_credentials(self, user):
        """list_credentials returns empty list for user with no credentials."""
        result = services.list_credentials(user=user)

        assert result == []

    def test_list_credentials_only_returns_own_credentials(
        self, user, other_user, scm_credential, deployment_profile_type
    ):
        """list_credentials only returns credentials for the specified user."""
        # Create credential for other user
        Credential.objects.create(
            user=other_user,
            name="Other User Cred",
            credential_type=deployment_profile_type,
            data={"authcode": "OTHERAUTH"},
        )

        result = services.list_credentials(user=user)

        assert len(result) == 1
        assert result[0].credential_id == scm_credential.id

    def test_list_credentials_none_user_raises_type_error(self):
        """list_credentials with None user raises TypeError."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.list_credentials(user=None)

    def test_list_credentials_invalid_user_type_raises_type_error(self):
        """list_credentials with non-User object raises TypeError."""
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.list_credentials(user="not_a_user")

    def test_list_credentials_unsaved_user_raises_value_error(self):
        """list_credentials with unsaved user raises ValueError."""
        unsaved_user = User(username="unsaved")
        with pytest.raises(ValueError, match="must be saved"):
            services.list_credentials(user=unsaved_user)


# =============================================================================
# get_credential tests
# =============================================================================


@pytest.mark.django_db
class TestGetCredential:
    """Tests for get_credential service function."""

    def test_get_credential_returns_scm_context(self, user, scm_credential):
        """get_credential returns SCMCredentialContext for SCM credential."""
        result = services.get_credential(user=user, credential_id=scm_credential.id)

        assert isinstance(result, SCMCredentialContext)
        assert result.credential_id == scm_credential.id
        assert result.name == scm_credential.name
        assert result.credential_type == "scm"
        assert result.scm_folder_name == "TestFolder"
        assert result.scm_pin_id == "pin123"
        assert result.sls_region == "americas"

    def test_get_credential_returns_deployment_context(self, user, deployment_credential):
        """get_credential returns DeploymentProfileContext for deployment credential."""
        result = services.get_credential(user=user, credential_id=deployment_credential.id)

        assert isinstance(result, DeploymentProfileContext)
        assert result.credential_id == deployment_credential.id
        assert result.name == deployment_credential.name
        assert result.credential_type == "deployment_profile"
        assert result.authcode_masked == "D7654***"

    def test_get_credential_excludes_secrets(self, user, scm_credential):
        """get_credential context does not include secret values."""
        result = services.get_credential(user=user, credential_id=scm_credential.id)

        # Verify no secret attributes
        assert not hasattr(result, "scm_pin_value")
        result_dict = result.model_dump()
        assert "scm_pin_value" not in result_dict

    def test_get_credential_not_found_raises_cms_error(self, user):
        """get_credential with non-existent ID raises CMSError."""
        with pytest.raises(CMSError, match="not found"):
            services.get_credential(user=user, credential_id=99999)

    def test_get_credential_wrong_owner_raises_cms_error(self, other_user, scm_credential):
        """get_credential for credential owned by another user raises CMSError."""
        with pytest.raises(CMSError, match="not found"):
            services.get_credential(user=other_user, credential_id=scm_credential.id)

    def test_get_credential_deleted_raises_cms_error(self, user, scm_credential):
        """get_credential for soft-deleted credential raises CMSError."""
        scm_credential.deleted_at = timezone.now()
        scm_credential.save()

        with pytest.raises(CMSError, match="not found"):
            services.get_credential(user=user, credential_id=scm_credential.id)

    def test_get_credential_none_user_raises_type_error(self, scm_credential):
        """get_credential with None user raises TypeError."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.get_credential(user=None, credential_id=scm_credential.id)

    def test_get_credential_none_id_raises_type_error(self, user):
        """get_credential with None credential_id raises TypeError."""
        with pytest.raises(TypeError, match="credential_id cannot be None"):
            services.get_credential(user=user, credential_id=None)

    def test_get_credential_invalid_id_type_raises_type_error(self, user):
        """get_credential with non-int credential_id raises TypeError."""
        with pytest.raises(TypeError, match="credential_id must be an int"):
            services.get_credential(user=user, credential_id="not_an_int")

    def test_get_credential_negative_id_raises_value_error(self, user):
        """get_credential with negative credential_id raises ValueError."""
        with pytest.raises(ValueError, match="must be non-negative"):
            services.get_credential(user=user, credential_id=-1)


# =============================================================================
# Integration tests - full lifecycle
# =============================================================================


@pytest.mark.django_db
class TestCredentialLifecycle:
    """Integration tests for complete credential lifecycle."""

    def test_create_list_get_delete_scm_credential(self, user, scm_credential_type):
        """Test full lifecycle: create -> list -> get -> delete for SCM credential."""
        # Create
        create_result = services.create_credential(
            user=user,
            credential_type_slug="scm",
            name="Lifecycle SCM",
            scm_folder_name="LifecycleFolder",
            scm_pin_id="lifecyclepin",
            scm_pin_value="lifecyclesecret",
            sls_region="asiapacific",
        )
        assert isinstance(create_result, CredentialRef)
        cred_id = create_result.credential_id

        # List - should include the new credential
        list_result = services.list_credentials(user=user)
        assert len(list_result) == 1
        assert list_result[0].credential_id == cred_id
        assert isinstance(list_result[0], SCMCredentialContext)

        # Get - should return the credential
        get_result = services.get_credential(user=user, credential_id=cred_id)
        assert get_result.credential_id == cred_id
        assert get_result.name == "Lifecycle SCM"
        assert get_result.scm_folder_name == "LifecycleFolder"

        # Delete
        delete_result = services.delete_credential(user=user, credential_id=cred_id)
        assert delete_result.is_deleted is True

        # List - should be empty now
        list_after = services.list_credentials(user=user)
        assert len(list_after) == 0

        # Get - should raise error
        with pytest.raises(CMSError, match="not found"):
            services.get_credential(user=user, credential_id=cred_id)

    def test_create_list_get_delete_deployment_credential(self, user, deployment_profile_type):
        """Test full lifecycle for deployment profile credential."""
        # Create
        create_result = services.create_credential(
            user=user,
            credential_type_slug="deployment_profile",
            name="Lifecycle Deploy",
            authcode="LIFECYCLEAUTH123",
        )
        cred_id = create_result.credential_id

        # List
        list_result = services.list_credentials(user=user)
        assert len(list_result) == 1
        assert isinstance(list_result[0], DeploymentProfileContext)

        # Get
        get_result = services.get_credential(user=user, credential_id=cred_id)
        assert get_result.name == "Lifecycle Deploy"
        assert get_result.authcode_masked == "LIFEC***"

        # Delete
        delete_result = services.delete_credential(user=user, credential_id=cred_id)
        assert delete_result.is_deleted is True

    def test_multiple_credentials_different_types(self, user, scm_credential_type, deployment_profile_type):
        """Test managing multiple credentials of different types."""
        # Create SCM credential
        scm_ref = services.create_credential(
            user=user,
            credential_type_slug="scm",
            name="Multi SCM",
            scm_folder_name="MultiFolder",
            scm_pin_id="multipin",
            scm_pin_value="multisecret",
            sls_region="americas",
        )

        # Create deployment profile
        dp_ref = services.create_credential(
            user=user,
            credential_type_slug="deployment_profile",
            name="Multi Deploy",
            authcode="MULTIAUTH",
        )

        # List should have both
        credentials = services.list_credentials(user=user)
        assert len(credentials) == 2

        # Verify types
        types = {type(c) for c in credentials}
        assert SCMCredentialContext in types
        assert DeploymentProfileContext in types

        # Delete SCM
        services.delete_credential(user=user, credential_id=scm_ref.credential_id)

        # List should have only deployment
        credentials_after = services.list_credentials(user=user)
        assert len(credentials_after) == 1
        assert credentials_after[0].credential_id == dp_ref.credential_id
