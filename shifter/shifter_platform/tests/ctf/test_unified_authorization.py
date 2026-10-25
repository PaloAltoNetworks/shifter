"""S5 CTF policy seam: principal authority is independent of event creator."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from ctf.exceptions import CTFPermissionError
from management.services import create_service_principal
from shared.authorization import AuthorizationDecision, CredentialCeiling, DecisionKind, TargetRef
from shared.credentials import CredentialContext


@pytest.mark.django_db
def test_service_administrator_uses_live_event_policy_and_exact_scope(ctf_event_active, monkeypatch):
    from ctf.models import CTFEvent
    from ctf.services.unified_authorization import require_event_action, require_event_creation
    from management.services import principal_for_user
    from shared.authorization import port
    from workspaces.services import create_account

    account = create_account(
        kind="individual", name="Personal CTF account", owner=principal_for_user(ctf_event_active.created_by)
    )
    event = CTFEvent.objects.create(
        name="Personal CTF event",
        created_by=ctf_event_active.created_by,
        scope_kind="account",
        account_id=account.id,
        scenario_id="synthetic",
        event_start=ctf_event_active.event_start,
        event_end=ctf_event_active.event_end,
    )
    service = create_service_principal("CTF administrator")
    credential = CredentialContext(
        service,
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"event.manage_staff", "account.create_event"})),
        frozenset(),
    )
    requests = []
    allowed = True

    def check(request):
        requests.append(request)
        return AuthorizationDecision(
            DecisionKind.ALLOWED if allowed else DecisionKind.DENIED,
            "policy_allowed" if allowed else "policy_denied",
        )

    monkeypatch.setattr(port, "_provider_factory", lambda: SimpleNamespace(check=check))
    require_event_action(credential, event.pk, "event.manage_staff")
    assert requests[-1].target == TargetRef("event", event.pk)
    assert requests[-1].scope.account_uuid == account.uuid
    assert requests[-1].scope.organization_uuid is None
    assert requests[-1].scope.workspace_uuid is None
    assert requests[-1].principal == service
    placement = require_event_creation(credential, TargetRef("account", account.uuid))
    assert placement.account_uuid == account.uuid
    assert placement.organization_uuid is None
    assert requests[-1].action == "account.create_event"
    assert requests[-1].target == TargetRef("account", account.uuid)
    allowed = False
    with pytest.raises(CTFPermissionError):
        require_event_action(credential, event.pk, "event.manage_staff")
    with pytest.raises(CTFPermissionError):
        require_event_action(credential, uuid4(), "event.manage_staff")

    def unavailable(_request):
        raise RuntimeError("provider secret must stay private")

    monkeypatch.setattr(port, "_provider_factory", lambda: SimpleNamespace(check=unavailable))
    from ctf.exceptions import CTFError

    with pytest.raises(CTFError, match="authority unavailable") as failed:
        require_event_action(credential, event.pk, "event.manage_staff")
    assert "secret" not in str(failed.value)


@pytest.mark.django_db
def test_temporary_participant_cannot_use_event_administration(ctf_event_active):
    from config.credential_scope import temporary_participant_credential
    from ctf.services.participant.accounts import create_participant_accounts
    from ctf.services.unified_authorization import require_event_action

    participant = create_participant_accounts(ctf_event_active.pk, count=1)[0]
    credential = temporary_participant_credential(participant.user)
    with pytest.raises(CTFPermissionError):
        require_event_action(credential, participant.event_id, "event.manage_staff")


@pytest.mark.django_db
def test_service_creation_uses_business_parent_ancestry(monkeypatch):
    from ctf.services.unified_authorization import require_event_creation
    from shared.authorization import port
    from workspaces.models import Organization, Workspace
    from workspaces.services import create_account

    account = create_account(kind="team", name="Business event account")
    organization = Organization.objects.get(account_id=account.id, is_default=True)
    workspace = Workspace.objects.get(organization=organization, is_default=True)
    service = create_service_principal("Event creator")
    credential = CredentialContext(
        service,
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"organization.create_event", "workspace.create_event"})),
        frozenset(),
    )
    seen = []

    def check(request):
        seen.append(request)
        return AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed")

    monkeypatch.setattr(port, "_provider_factory", lambda: SimpleNamespace(check=check))
    for target in (TargetRef("organization", organization.uuid), TargetRef("workspace", workspace.uuid)):
        scope = require_event_creation(credential, target)
        assert scope.account_uuid == account.uuid
        assert scope.organization_uuid == organization.uuid
        assert scope.workspace_uuid == (workspace.uuid if target.type == "workspace" else None)
        assert seen[-1].target == target
    with pytest.raises(CTFPermissionError):
        require_event_creation(credential, TargetRef("account", account.uuid))
    with pytest.raises(CTFPermissionError):
        require_event_creation(credential, TargetRef("account", uuid4()))


@pytest.mark.django_db
def test_business_event_cannot_claim_a_direct_account_parent(ctf_event_active, monkeypatch):
    from ctf.models import CTFEvent
    from ctf.services.unified_authorization import require_event_action
    from shared.authorization import port
    from workspaces.services import create_account

    account = create_account(kind="team", name="Business account")
    event = CTFEvent.objects.create(
        name="Invalid placement",
        created_by=ctf_event_active.created_by,
        scope_kind="account",
        account_id=account.id,
        scenario_id="synthetic",
        event_start=ctf_event_active.event_start,
        event_end=ctf_event_active.event_end,
    )
    service = create_service_principal("Administrator")
    credential = CredentialContext(
        service, "service", uuid4(), CredentialCeiling(frozenset({"event.manage_config"})), frozenset()
    )
    checked = []

    def check(request):
        checked.append(request)
        return AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed")

    monkeypatch.setattr(port, "_provider_factory", lambda: SimpleNamespace(check=check))

    with pytest.raises(CTFPermissionError):
        require_event_action(credential, event.pk, "event.manage_config")
    assert checked == []
