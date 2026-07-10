"""Tests for cms.models module - CMS Django models.

Tests the Django model layer:
- Model structure (fields, constraints, relationships)
- Model properties and methods (in-memory, no DB)
- Model behavior (real DB: create, ordering, uniqueness, cascade, PROTECT)

Property/structure tests build in-memory instances; behavior tests that depend
on ORM semantics (uniqueness, cascade, PROTECT, ordering) run against a real DB
rather than patching ``Credential.objects`` / ``CredentialType.objects``.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from cms.models import Credential, CredentialType

from .conftest import make_credential

User = get_user_model()


def _real_ct():
    """Get or create a real (saved) deployment-profile CredentialType."""
    ct, _ = CredentialType.objects.get_or_create(
        slug="deployment_profile",
        defaults={"name": "Deployment Profile", "spec_slug": "credential.deployment_profile"},
    )
    return ct


def _real_cred(user, name, *, ct=None, deleted_at=None):
    cred = Credential.objects.create(
        user=user, name=name, credential_type=ct or _real_ct(), data={"authcode": "D1234567"}
    )
    if deleted_at is not None:
        cred.deleted_at = deleted_at
        cred.save(update_fields=["deleted_at"])
    return cred


def _user(suffix):
    return User.objects.create_user(username=f"cred-{suffix}@e.com", email=f"cred-{suffix}@e.com")


# -----------------------------------------------------------------------------
# CatalogBase Tests (in-memory via the credential_type_obj fixture)
# -----------------------------------------------------------------------------


class TestCatalogBase:
    """Tests for CatalogBase abstract model (via CredentialType)."""

    def test_str_returns_name(self, credential_type_obj):
        assert str(credential_type_obj) == "Deployment Profile"

    def test_get_spec_class_loads_pydantic_model(self, credential_type_obj):
        from shared.schemas import DeploymentProfileSpec

        assert credential_type_obj.get_spec_class() is DeploymentProfileSpec

    def test_validate_data_returns_validated_dict(self, credential_type_obj):
        result = credential_type_obj.validate_data({"name": "Test Cred", "user_id": 1, "authcode": "D1234567"})
        assert isinstance(result, dict)
        assert result["name"] == "Test Cred"
        assert result["authcode"] == "D1234567"

    def test_validate_data_raises_on_invalid_data(self, credential_type_obj):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            credential_type_obj.validate_data({"name": "Test", "user_id": 1})  # Missing authcode


# -----------------------------------------------------------------------------
# Credential model properties (in-memory)
# -----------------------------------------------------------------------------


class TestCredentialProperties:
    def test_str_returns_name(self, credential_type_obj):
        cred = make_credential(credential_type_obj, name="My Test Credential")
        assert str(cred) == "My Test Credential"

    @pytest.mark.parametrize(
        "deleted_at,expected",
        [pytest.param(None, False, id="not-deleted"), pytest.param("now", True, id="deleted")],
    )
    def test_is_deleted(self, credential_type_obj, deleted_at, expected):
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
        expires_at = None if expires_at_offset is None else timezone.now() + expires_at_offset
        cred = make_credential(credential_type_obj, expires_at=expires_at)
        assert cred.expires_soon is expected


# -----------------------------------------------------------------------------
# Credential model behavior (real DB)
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCredentialModel:
    def test_create_credential(self):
        user = _user("create")
        ct = _real_ct()
        result = Credential.objects.create(
            user=user, name="My Credential", credential_type=ct, data={"authcode": "D1234567"}
        )

        persisted = Credential.objects.get(pk=result.pk)
        assert persisted.user_id == user.id
        assert persisted.name == "My Credential"
        assert persisted.credential_type == ct
        assert persisted.data == {"authcode": "D1234567"}
        assert persisted.deleted_at is None

    def test_ordering_by_created_at_descending(self):
        user = _user("order")
        first = _real_cred(user, "First")
        Credential.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(hours=1))
        _real_cred(user, "Second")

        names = [c.name for c in Credential.objects.filter(user=user)]
        assert names == ["Second", "First"]  # newest first (Meta.ordering = -created_at)


@pytest.mark.django_db
class TestCredentialUniqueness:
    def test_duplicate_name_same_user_rejected(self):
        user = _user("dup")
        _real_cred(user, "My Credential")
        with pytest.raises(IntegrityError), transaction.atomic():
            _real_cred(user, "My Credential")

    def test_same_name_different_users_allowed(self):
        _real_cred(_user("u1"), "My Credential")
        result = _real_cred(_user("u2"), "My Credential")
        assert result.id is not None

    def test_deleted_credential_allows_same_name(self):
        user = _user("softdel")
        _real_cred(user, "My Credential", deleted_at=timezone.now())
        result = _real_cred(user, "My Credential")
        assert result.id is not None
        assert result.deleted_at is None


@pytest.mark.django_db
class TestCredentialRelationships:
    def test_credential_deleted_when_user_deleted(self):
        user = _user("cascade")
        cred = _real_cred(user, "Temp Cred")
        cred_id = cred.id
        user.delete()
        assert not Credential.all_objects.filter(id=cred_id).exists()

    def test_credential_protected_when_type_deleted(self):
        user = _user("protect")
        ct = CredentialType.objects.create(
            name="Protected Type", slug="protected_test_type", spec_slug="credential.deployment_profile"
        )
        _real_cred(user, "Using Type", ct=ct)
        with pytest.raises(ProtectedError), transaction.atomic():
            ct.delete()


@pytest.mark.django_db
class TestCredentialType:
    def test_slug_unique(self):
        CredentialType.objects.create(
            name="Unique Test Type", slug="unique_test_slug_x", spec_slug="credential.deployment_profile"
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            CredentialType.objects.create(
                name="Another Test Type", slug="unique_test_slug_x", spec_slug="credential.deployment_profile"
            )
