"""Tests for CMS Credential model."""

import pytest


@pytest.mark.django_db
class TestCredential:
    """Tests for the cms.Credential model."""

    def test_scm_credential_type_works(self, django_user_model):
        """SCM credential type should work in cms.Credential."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="migrationtest",
            email="migration@test.com",
            password="test",
        )

        # Create SCM-type credential
        new_cred = Credential.objects.create(
            user=user,
            name="New SCM Cred",
            credential_type=Credential.Type.SCM,
            scm_folder_name="new-folder",
            scm_pin_id="PIN456",
            scm_pin_value="new-secret",
            sls_region="europe",
        )

        assert new_cred.credential_type == "scm"
        assert new_cred.scm_folder_name == "new-folder"
        assert new_cred.scm_pin_id == "PIN456"
        assert new_cred.sls_region == "europe"

    def test_deployment_profile_type_works(self, django_user_model):
        """Deployment profile credential type should work in cms.Credential."""
        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="migrationtest2",
            email="migration2@test.com",
            password="test",
        )

        # Create deployment profile type credential
        new_cred = Credential.objects.create(
            user=user,
            name="New Profile",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D7654321",
        )

        assert new_cred.credential_type == "deployment_profile"
        assert new_cred.authcode == "D7654321"

    def test_credential_fields_preserved(self, django_user_model):
        """All credential fields should be preserved."""
        from django.utils import timezone

        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="fieldtest",
            email="fields@test.com",
            password="test",
        )

        now = timezone.now()

        # Create credential with all fields populated
        cred = Credential.objects.create(
            user=user,
            name="Full Credential",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D9999999",
            expires_at=now,
            last_verified_at=now,
            last_used_at=now,
        )

        # Reload and verify
        loaded = Credential.objects.get(pk=cred.pk)
        assert loaded.name == "Full Credential"
        assert loaded.authcode == "D9999999"
        assert loaded.expires_at is not None
        assert loaded.last_verified_at is not None
        assert loaded.last_used_at is not None

    def test_soft_deleted_credentials_work(self, django_user_model):
        """Soft-deleted credentials should work correctly."""
        from django.utils import timezone

        from cms.models import Credential

        user = django_user_model.objects.create_user(
            username="deletedtest",
            email="deleted@test.com",
            password="test",
        )

        # Create and soft-delete a credential
        cred = Credential.objects.create(
            user=user,
            name="Deleted Cred",
            credential_type=Credential.Type.DEPLOYMENT_PROFILE,
            authcode="D1111111",
        )
        cred.deleted_at = timezone.now()
        cred.save()

        # Verify it exists but is marked deleted
        loaded = Credential.objects.get(pk=cred.pk)
        assert loaded.deleted_at is not None
        assert loaded.is_deleted is True
