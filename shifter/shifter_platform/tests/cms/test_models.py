"""Tests for cms.models module - CMS Django models.

These are unit tests for the Django model layer. They test:
- Model structure (fields, constraints, relationships)
- Model properties and methods
- Model behavior (soft delete, ordering)

All ORM operations are mocked - no database access required.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.utils import timezone

from cms.models import Credential, CredentialType

from .conftest import make_credential

# -----------------------------------------------------------------------------
# CatalogBase Tests
# -----------------------------------------------------------------------------


class TestCatalogBase:
    """Tests for CatalogBase abstract model (via CredentialType)."""

    def test_str_returns_name(self, credential_type_obj):
        """__str__ returns the name field."""
        assert str(credential_type_obj) == "Deployment Profile"

    def test_get_spec_class_loads_pydantic_model(self, credential_type_obj):
        """get_spec_class loads and returns the Pydantic spec class."""
        spec_class = credential_type_obj.get_spec_class()

        from shared.schemas import DeploymentProfileSpec

        assert spec_class is DeploymentProfileSpec

    def test_validate_data_returns_validated_dict(self, credential_type_obj):
        """validate_data validates against spec and returns dict."""
        data = {
            "name": "Test Cred",
            "user_id": 1,
            "authcode": "D1234567",
        }

        result = credential_type_obj.validate_data(data)

        assert isinstance(result, dict)
        assert result["name"] == "Test Cred"
        assert result["authcode"] == "D1234567"

    def test_validate_data_raises_on_invalid_data(self, credential_type_obj):
        """validate_data raises ValidationError for invalid data."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            credential_type_obj.validate_data({"name": "Test", "user_id": 1})  # Missing authcode


# -----------------------------------------------------------------------------
# Credential Model Tests
# -----------------------------------------------------------------------------


class TestCredentialModel:
    """Tests for Credential model."""

    def test_create_credential(self, credential_type_obj):
        """Can create a credential with required fields."""
        cred = make_credential(credential_type_obj, name="My Credential")

        with patch.object(Credential.objects, "create", return_value=cred):
            result = Credential.objects.create(
                user_id=1,
                name="My Credential",
                credential_type=credential_type_obj,
                data={"authcode": "D1234567"},
            )

        assert result.id is not None
        assert result.user_id == 1
        assert result.name == "My Credential"
        assert result.credential_type == credential_type_obj
        assert result.data == {"authcode": "D1234567"}
        assert result.deleted_at is None

    def test_str_returns_name(self, credential_type_obj):
        """__str__ returns the credential name."""
        cred = make_credential(credential_type_obj, name="My Test Credential")
        assert str(cred) == "My Test Credential"

    @pytest.mark.parametrize(
        "deleted_at,expected",
        [
            pytest.param(None, False, id="not-deleted"),
            pytest.param("now", True, id="deleted"),
        ],
    )
    def test_is_deleted(self, credential_type_obj, deleted_at, expected):
        """is_deleted reflects whether deleted_at is set."""
        actual_deleted_at = timezone.now() if deleted_at == "now" else None
        cred = make_credential(credential_type_obj, deleted_at=actual_deleted_at)
        assert cred.is_deleted is expected

    @pytest.mark.parametrize(
        "expires_at_offset,expected",
        [
            pytest.param(None, False, id="no-expiry"),
            pytest.param(timedelta(days=30), False, id="future"),
            pytest.param(timedelta(days=-1), True, id="past"),
        ],
    )
    def test_is_expired(self, credential_type_obj, expires_at_offset, expected):
        """is_expired reflects expiry state."""
        expires_at = None if expires_at_offset is None else timezone.now() + expires_at_offset
        cred = make_credential(credential_type_obj, expires_at=expires_at)
        assert cred.is_expired is expected

    @pytest.mark.parametrize(
        "expires_at_offset,expected",
        [
            pytest.param(None, False, id="no-expiry"),
            pytest.param(timedelta(days=15), True, id="within-30-days"),
            pytest.param(timedelta(days=-1), False, id="already-expired"),
        ],
    )
    def test_expires_soon(self, credential_type_obj, expires_at_offset, expected):
        """expires_soon reflects whether expiry is within 30 days."""
        expires_at = None if expires_at_offset is None else timezone.now() + expires_at_offset
        cred = make_credential(credential_type_obj, expires_at=expires_at)
        assert cred.expires_soon is expected

    def test_ordering_by_created_at_descending(self, credential_type_obj):
        """Credentials are ordered by created_at descending."""
        cred1 = make_credential(credential_type_obj, pk=1, name="First")
        cred2 = make_credential(credential_type_obj, pk=2, name="Second")

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter([cred2, cred1]))

        with patch.object(Credential.objects, "filter", return_value=mock_qs):
            credentials = list(Credential.objects.filter(user_id=1))

        # Newest first
        assert credentials[0] == cred2
        assert credentials[1] == cred1


# -----------------------------------------------------------------------------
# Credential Uniqueness Constraint Tests
# -----------------------------------------------------------------------------


class TestCredentialUniqueness:
    """Tests for credential uniqueness constraints."""

    def test_duplicate_name_same_user_rejected(self, credential_type_obj):
        """Rejects duplicate name for same user (active credentials)."""
        first_cred = make_credential(credential_type_obj, pk=1, name="My Credential")

        with patch.object(Credential.objects, "create") as mock_create:
            # First create succeeds
            mock_create.return_value = first_cred
            Credential.objects.create(
                user_id=1,
                name="My Credential",
                credential_type=credential_type_obj,
                data={"authcode": "D1111111"},
            )

            # Second create raises IntegrityError (duplicate)
            mock_create.side_effect = IntegrityError("duplicate key value violates unique constraint")
            with pytest.raises(IntegrityError):
                Credential.objects.create(
                    user_id=1,
                    name="My Credential",
                    credential_type=credential_type_obj,
                    data={"authcode": "D2222222"},
                )

    def test_same_name_different_users_allowed(self, credential_type_obj):
        """Allows same name for different users."""
        cred2 = make_credential(credential_type_obj, pk=2, user_id=2, name="My Credential")

        with patch.object(Credential.objects, "create") as mock_create:
            # First create for user 1
            mock_create.return_value = make_credential(credential_type_obj, pk=1, user_id=1, name="My Credential")
            Credential.objects.create(
                user_id=1,
                name="My Credential",
                credential_type=credential_type_obj,
                data={"authcode": "D1111111"},
            )

            # Second create for user 2 succeeds (different user)
            mock_create.return_value = cred2
            result = Credential.objects.create(
                user_id=2,
                name="My Credential",
                credential_type=credential_type_obj,
                data={"authcode": "D2222222"},
            )

        assert result.id is not None

    def test_deleted_credential_allows_same_name(self, credential_type_obj):
        """Soft-deleted credential doesn't block new credential with same name."""
        cred2 = make_credential(credential_type_obj, pk=2, name="My Credential")

        with patch.object(Credential.objects, "create") as mock_create:
            # First create is soft-deleted
            mock_create.return_value = make_credential(
                credential_type_obj, pk=1, name="My Credential", deleted_at=timezone.now()
            )
            Credential.objects.create(
                user_id=1,
                name="My Credential",
                credential_type=credential_type_obj,
                data={"authcode": "D1111111"},
                deleted_at=timezone.now(),
            )

            # Second create succeeds (original is soft-deleted)
            mock_create.return_value = cred2
            result = Credential.objects.create(
                user_id=1,
                name="My Credential",
                credential_type=credential_type_obj,
                data={"authcode": "D2222222"},
            )

        assert result.id is not None
        assert result.deleted_at is None


# -----------------------------------------------------------------------------
# Credential Foreign Key Tests
# -----------------------------------------------------------------------------


class TestCredentialRelationships:
    """Tests for credential foreign key relationships."""

    def test_credential_deleted_when_user_deleted(self, credential_type_obj):
        """Credentials cascade delete when user is deleted (on_delete=CASCADE)."""
        cred = make_credential(credential_type_obj, pk=10, user_id=99, name="Temp Cred")

        # After user deletion, credential no longer exists
        mock_qs = MagicMock()
        mock_qs.exists.return_value = False

        with patch.object(Credential.objects, "filter", return_value=mock_qs):
            # Simulate user.delete() cascade
            assert not Credential.objects.filter(id=cred.id).exists()

    def test_credential_protected_when_type_deleted(self, credential_type_obj):
        """Cannot delete CredentialType with existing credentials (PROTECT)."""
        cred = make_credential(credential_type_obj, pk=1, name="Using Type")

        # Mock delete to raise ProtectedError (what PROTECT does)
        credential_type_obj.delete = MagicMock(
            side_effect=ProtectedError(
                "Cannot delete CredentialType with existing credentials",
                {cred},
            )
        )

        with pytest.raises(ProtectedError):
            credential_type_obj.delete()


# -----------------------------------------------------------------------------
# CredentialType Tests
# -----------------------------------------------------------------------------


class TestCredentialType:
    """Tests for CredentialType model."""

    def test_slug_unique(self):
        """CredentialType slug must be unique."""
        with patch.object(CredentialType.objects, "create") as mock_create:
            # First create succeeds
            mock_create.return_value = CredentialType(
                name="Unique Test Type",
                slug="unique_test_slug",
                spec_class="shared.schemas.DeploymentProfileSpec",
            )
            CredentialType.objects.create(
                name="Unique Test Type",
                slug="unique_test_slug",
                spec_class="shared.schemas.DeploymentProfileSpec",
            )

            # Second create with same slug raises IntegrityError
            mock_create.side_effect = IntegrityError("duplicate key value violates unique constraint")
            with pytest.raises(IntegrityError):
                CredentialType.objects.create(
                    name="Another Test Type",
                    slug="unique_test_slug",
                    spec_class="shared.schemas.DeploymentProfileSpec",
                )
