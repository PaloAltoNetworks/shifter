"""Personal credential mutations enforce current policy and session ownership."""

from types import SimpleNamespace

import pytest
from django.utils import timezone

from shared.api_tokens.models import ApiToken
from shared.authorization import ACTION_CATALOG, AuthorizationDecision, CredentialCeiling, DecisionKind, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope

pytestmark = pytest.mark.django_db


def test_owner_can_revoke_after_grant_loss_but_cannot_issue_or_rotate(django_user_model, monkeypatch):
    from management import personal_credentials, services
    from shared.authorization import port

    user = django_user_model.objects.create_user(username="token-owner")
    actor = CredentialContext(
        principal=services.principal_for_user(user),
        kind="session",
        credential_uuid=user.identity_principal.uuid,
        ceiling=CredentialCeiling(frozenset(action.code for action in ACTION_CATALOG)),
        scopes=frozenset(),
    )
    allowed = True
    provider = SimpleNamespace(
        check=lambda request: AuthorizationDecision(
            DecisionKind.ALLOWED if allowed else DecisionKind.DENIED,
            "policy_allowed" if allowed else "policy_denied",
        )
    )
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    kwargs = {
        "actor": actor,
        "user": user,
        "name": "Personal automation",
        "scopes": ["authorization:installation.read_audit"],
        "expires_at": timezone.now() + timezone.timedelta(hours=1),
        "target": TargetRef("installation"),
        "scope": ResourceScope("installation"),
    }
    token, raw = personal_credentials.issue_personal_token(**kwargs)
    assert ApiToken.authenticate(raw) == token
    allowed = False
    with pytest.raises(ValueError):
        personal_credentials.issue_personal_token(**kwargs)
    with pytest.raises(ValueError):
        personal_credentials.rotate_personal_token(token.credential_uuid, **kwargs)
    personal_credentials.revoke_own_token(actor, user, token.credential_uuid)
    assert ApiToken.authenticate(raw) is None


def test_bearer_cannot_issue_personal_credentials(django_user_model):
    from management import personal_credentials, services

    user = django_user_model.objects.create_user(username="no-recursive-mint")
    actor = CredentialContext(
        principal=services.principal_for_user(user),
        kind="personal",
        credential_uuid=user.identity_principal.uuid,
        ceiling=CredentialCeiling(frozenset(action.code for action in ACTION_CATALOG)),
        scopes=frozenset(),
    )
    with pytest.raises(ValueError):
        personal_credentials.issue_personal_token(
            actor=actor,
            user=user,
            name="Forbidden",
            scopes=["authorization:installation.read_audit"],
            expires_at=timezone.now() + timezone.timedelta(hours=1),
            target=TargetRef("installation"),
            scope=ResourceScope("installation"),
        )
    assert not ApiToken.objects.exists()
