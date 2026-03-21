"""Pytest fixtures and helpers for CMS tests.

Provides shared model builders and fixtures used across CMS test modules.
"""

import pytest
from django.db.models.base import ModelState
from django.utils import timezone

from cms.models import Credential, CredentialType

# -----------------------------------------------------------------------------
# In-memory model builders (no DB required)
# -----------------------------------------------------------------------------


@pytest.fixture
def credential_type_obj():
    """Create a CredentialType instance in memory (no DB)."""
    ct = CredentialType(
        name="Deployment Profile",
        slug="deployment_profile",
        spec_class="shared.schemas.DeploymentProfileSpec",
    )
    ct.pk = 1
    ct.id = 1
    return ct


@pytest.fixture
def scm_credential_type_obj():
    """Create an SCM CredentialType instance in memory (no DB)."""
    ct = CredentialType(
        name="SCM Credential",
        slug="scm",
        spec_class="shared.schemas.SCMCredentialSpec",
    )
    ct.pk = 2
    ct.id = 2
    return ct


def make_credential(credential_type_obj, pk=1, **overrides):
    """Build a Credential instance in memory using _id fields to bypass FK checks.

    Uses __new__ + manual __dict__ population to avoid Django's FK descriptor
    type-checking (which rejects MagicMock users). The _state object is
    initialized manually to keep FK cache access working.
    """
    cred = Credential.__new__(Credential)
    cred._state = ModelState()
    # Set fields directly to avoid FK descriptor type checks
    cred.__dict__["name"] = overrides.get("name", "My Credential")
    cred.__dict__["user_id"] = overrides.get("user_id", 1)
    cred.__dict__["credential_type_id"] = credential_type_obj.pk
    cred.__dict__["data"] = overrides.get("data", {"authcode": "D1234567"})
    cred.__dict__["deleted_at"] = overrides.get("deleted_at")
    cred.__dict__["expires_at"] = overrides.get("expires_at")
    cred.__dict__["created_at"] = overrides.get("created_at", timezone.now())
    # Cache the FK object so descriptor access works without DB
    cred._state.fields_cache["credential_type"] = credential_type_obj
    cred.pk = pk
    cred.id = pk
    return cred
