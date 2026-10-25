"""A QA service joins existing participation without becoming a human user."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from management.services import create_service_principal
from shared.authorization import AuthorizationDecision, CredentialCeiling, DecisionKind
from shared.credentials import CredentialContext


@pytest.mark.django_db
def test_temporary_resolver_confines_canonical_authorization_to_its_event(ctf_event_active, monkeypatch):
    from config.credential_scope import temporary_participant_credential
    from ctf.services.participant.accounts import create_participant_accounts
    from shared.authorization import AuthorizationContractError, AuthorizationRequest, TargetRef
    from shared.identity_scope import ResourceScope

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.pk, count=1)[0]
    credential = temporary_participant_credential(participant.user)
    target = TargetRef("event", participant.event_id)
    scope = ResourceScope("account", account_uuid=uuid4())
    assert credential.ceiling.target == target
    for action in ("event.read", "event.participate"):
        AuthorizationRequest(credential.principal, action, target, scope, credential.ceiling)
        with pytest.raises(AuthorizationContractError, match="credential ceiling"):
            AuthorizationRequest(
                credential.principal,
                action,
                TargetRef("event", uuid4()),
                scope,
                credential.ceiling,
            )


@pytest.mark.django_db
@pytest.mark.parametrize("ineligible", [{"status": "banned"}, {"status": "disqualified"}, {"registered_at": None}])
def test_service_participation_is_independent_and_obeys_live_event(
    ctf_event_active, monkeypatch, django_user_model, ineligible
):
    from ctf.services import admit_service_participant, participant_for_credential
    from management.services import principal_for_user
    from shared.authorization import port
    from workspaces.services import create_account

    account = create_account(
        kind="individual", name="Synthetic QA account", owner=principal_for_user(ctf_event_active.created_by)
    )
    from ctf.models import CTFEvent

    ctf_event_active = CTFEvent.objects.create(
        name="Synthetic QA event",
        created_by=ctf_event_active.created_by,
        scope_kind="account",
        account_id=account.id,
        status="active",
        scenario_id="synthetic",
        event_start=ctf_event_active.event_start,
        event_end=ctf_event_active.event_end,
    )
    operator = create_service_principal("operator")
    service = create_service_principal("qa")
    actor = CredentialContext(
        operator, "service", uuid4(), CredentialCeiling(frozenset({"event.manage_participants"})), frozenset()
    )
    credential = CredentialContext(
        service, "service", uuid4(), CredentialCeiling(frozenset({"event.participate"})), frozenset()
    )
    monkeypatch.setattr(
        port,
        "_provider_factory",
        lambda: SimpleNamespace(check=lambda request: AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed")),
    )
    administrator_with_play_ceiling = CredentialContext(
        operator,
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"event.manage_participants", "event.participate"})),
        frozenset(),
    )
    with pytest.raises(ValueError, match="Participation denied"):
        participant_for_credential(administrator_with_play_ceiling, ctf_event_active.pk)
    humans = django_user_model.objects.count()
    participant = admit_service_participant(actor, ctf_event_active.pk, service, name="QA participant")
    from shared.models import AuditLog

    audit = AuditLog.objects.get(context="service_participation")
    assert audit.actor_type == "principal"
    assert audit.actor_principal_uuid == operator.uuid
    assert "actor_principal" not in audit.new_state
    assert participant.user_id is None
    assert participant.principal_uuid == service.uuid
    assert django_user_model.objects.count() == humans
    assert participant_for_credential(credential, ctf_event_active.pk).pk == participant.pk
    monkeypatch.setattr(
        port,
        "_provider_factory",
        lambda: SimpleNamespace(
            check=lambda request: AuthorizationDecision(DecisionKind.EVALUATOR_ERROR, "evaluator_unavailable")
        ),
    )
    from ctf.exceptions import CTFError

    with pytest.raises(CTFError, match="authority unavailable"):
        participant_for_credential(credential, ctf_event_active.pk)
    monkeypatch.setattr(
        port,
        "_provider_factory",
        lambda: SimpleNamespace(check=lambda request: AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed")),
    )
    from ctf.exceptions import CTFPermissionError

    with pytest.raises(CTFPermissionError):
        participant_for_credential(credential, uuid4())
    for field, value in ineligible.items():
        setattr(participant, field, value)
    participant.save(update_fields=list(ineligible))
    with pytest.raises(ValueError):
        participant_for_credential(credential, ctf_event_active.pk)


@pytest.mark.django_db
def test_native_service_can_be_admitted_and_read_its_participant_projection_via_http(
    ctf_event_active, monkeypatch, settings
):
    from rest_framework.test import APIClient

    from config import service_identity
    from ctf.models import CTFEvent, CTFParticipant
    from management import services
    from management.models import Principal, ProviderBinding, ServiceCredentialAdmission
    from management.services import principal_for_user
    from shared.authorization import port
    from workspaces.services import create_account

    account = create_account(
        kind="individual", name="QA account", owner=principal_for_user(ctf_event_active.created_by)
    )
    event = CTFEvent.objects.create(
        name="QA event",
        created_by=ctf_event_active.created_by,
        scope_kind="account",
        account_id=account.id,
        status="active",
        scenario_id="synthetic",
        event_start=ctf_event_active.event_start,
        event_end=ctf_event_active.event_end,
    )
    service = create_service_principal("QA service", created_by=event.created_by)
    allowed = True
    monkeypatch.setattr(
        port,
        "_provider_factory",
        lambda: SimpleNamespace(
            check=lambda request: AuthorizationDecision(
                DecisionKind.ALLOWED if allowed else DecisionKind.DENIED,
                "policy_allowed" if allowed else "policy_denied",
            )
        ),
    )
    client = APIClient()
    client.force_login(event.created_by, backend="config.auth.PlatformModelBackend")
    admitted = client.post(
        f"/api/v1/ctf/events/{event.pk}/principal-participants/",
        {"principal_uuid": str(service.uuid), "name": "QA participant"},
        format="json",
    )
    assert admitted.status_code == 201
    from shared.models import AuditLog

    audit = AuditLog.objects.get(context="service_participation")
    assert audit.actor_type == "principal"
    assert audit.actor_principal_uuid == event.created_by.identity_principal.uuid
    participant_id = admitted.json()["participant_uuid"]
    assert CTFParticipant.objects.get(pk=participant_id).user_id is None
    client.logout()
    services.mark_user_deleted(event.created_by)

    settings.GCP_SERVICE_TOKEN_AUDIENCE = "https://portal.example.test"
    subject = "123456789012345678901"
    services.bind_principal_provider_identity(service, "https://accounts.google.com", subject)
    ServiceCredentialAdmission.objects.create(
        binding=ProviderBinding.objects.get(principal__uuid=service.uuid),
        audience=settings.GCP_SERVICE_TOKEN_AUDIENCE,
        scopes=["authorization:event.participate"],
    )
    claims = {
        "iss": "https://accounts.google.com",
        "sub": subject,
        "aud": settings.GCP_SERVICE_TOKEN_AUDIENCE,
        "email": "qa@synthetic.iam.gserviceaccount.com",
        "email_verified": True,
    }
    monkeypatch.setattr(service_identity.id_token, "verify_oauth2_token", lambda *args, **kwargs: claims)
    client.credentials(HTTP_AUTHORIZATION="Bearer header.payload.signature")
    path = f"/api/v1/ctf/me/events/{event.pk}/participant/"
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["participant"]["id"] == participant_id
    assert client.get(f"/api/v1/ctf/me/events/{uuid4()}/participant/").status_code == 403
    allowed = False
    assert client.get(path).status_code == 403
    allowed = True
    monkeypatch.setattr(
        port,
        "_provider_factory",
        lambda: SimpleNamespace(
            check=lambda request: AuthorizationDecision(DecisionKind.EVALUATOR_ERROR, "evaluator_unavailable")
        ),
    )
    assert client.get(path).status_code == 503
    monkeypatch.setattr(
        port,
        "_provider_factory",
        lambda: SimpleNamespace(check=lambda request: AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed")),
    )
    participant = CTFParticipant.objects.get(pk=participant_id)
    participant.registered_at = None
    participant.save(update_fields=["registered_at"])
    assert client.get(path).status_code == 403
    Principal.objects.filter(uuid=service.uuid).update(is_active=False)
    assert client.get(path).status_code == 401
