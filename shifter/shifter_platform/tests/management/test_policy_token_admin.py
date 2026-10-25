"""Full policy admins can revoke others' personal credentials without issuing them."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from management import personal_credentials
from shared.api_tokens.models import ApiToken
from shared.models import AuditLog
from tests.workspaces.test_account_policy_admin import Provider, _actor

pytestmark = pytest.mark.django_db


def test_service_admin_lists_safe_metadata_and_revokes_another_humans_token():
    owner = get_user_model().objects.create_user(username="token-owner")
    token, _raw = ApiToken.create_token(
        name="Automation",
        scopes=["authorization:account.read"],
        created_by=owner,
        expires_at=timezone.now() + timedelta(days=1),
    )
    actor = _actor("service", actions=frozenset({"installation.revoke_personal_tokens"}))
    page = personal_credentials.admin_list_personal_tokens(actor, Provider(), token.principal_uuid)
    assert page["count"] == 1
    personal_credentials.admin_revoke_personal_token(actor, Provider(), token.credential_uuid)
    personal_credentials.admin_revoke_personal_token(actor, Provider(), token.credential_uuid)
    token.refresh_from_db()
    assert token.revoked_at is not None
    assert AuditLog.objects.filter(
        actor_principal_uuid=actor.principal.uuid, entity_type="apikey", action="delete"
    ).exists()


def test_revocation_denial_preserves_library_credential():
    owner = get_user_model().objects.create_user(username="token-owner")
    token, _raw = ApiToken.create_token(
        name="Automation",
        scopes=["authorization:account.read"],
        created_by=owner,
        expires_at=timezone.now() + timedelta(days=1),
    )
    actor = _actor("service", actions=frozenset({"installation.revoke_personal_tokens"}))
    with pytest.raises(ValueError):
        personal_credentials.admin_revoke_personal_token(actor, Provider(allowed=False), token.credential_uuid)
    token.refresh_from_db()
    assert token.revoked_at is None
