"""Shared HTTP/socket session admission and bounded provider revocation."""

from types import SimpleNamespace

import pytest
from django.contrib.auth import BACKEND_SESSION_KEY

from config import identity_platform


@pytest.mark.django_db
def test_session_revalidates_provider_without_retaining_raw_proof(django_user_model, monkeypatch, settings):
    from config.session_credentials import establish_identity_session, validate_session

    settings.IDENTITY_SESSION_RECHECK_SECONDS = 60
    settings.IDENTITY_PLATFORM_PROJECT_ID = "example"
    user = django_user_model.objects.create_user(username="session-human")
    from management.services import bind_provider_identity

    bind_provider_identity(user, "https://securetoken.google.com/example", "subject")
    session = {BACKEND_SESSION_KEY: "config.identity_platform.IdentityPlatformBackend"}
    claims = {"iss": "https://securetoken.google.com/example", "sub": "subject", "auth_time": 100}
    establish_identity_session(session, claims, now=100)
    assert "id_token" not in session["identity_assurance"]
    monkeypatch.setattr(
        identity_platform,
        "provider_user_state",
        lambda subject: SimpleNamespace(
            disabled=False,
            email_verified=True,
            tokens_valid_after_timestamp=0,
        ),
    )
    assert validate_session(user, session, now=159)
    assert validate_session(user, session, now=160)
    monkeypatch.setattr(
        identity_platform,
        "provider_user_state",
        lambda subject: SimpleNamespace(
            disabled=False,
            email_verified=True,
            tokens_valid_after_timestamp=161000,
        ),
    )
    assert not validate_session(user, session, now=220)

    def unavailable(subject):
        raise ConnectionError("Provider unavailable")

    monkeypatch.setattr(identity_platform, "provider_user_state", unavailable)
    assert not validate_session(user, session, now=221)


@pytest.mark.django_db
def test_session_denies_disabled_principal_and_missing_assurance(django_user_model):
    from config.session_credentials import validate_session

    user = django_user_model.objects.create_user(username="disabled-session")
    assert not validate_session(user, {BACKEND_SESSION_KEY: "config.identity_platform.IdentityPlatformBackend"})
    principal = user.identity_principal
    principal.is_active = False
    principal.save(update_fields=["is_active"])
    assert not validate_session(user, {})


@pytest.mark.django_db
def test_open_socket_cannot_keep_using_a_logged_out_session(client, django_user_model):
    from config.session_credentials import validate_socket_session

    user = django_user_model.objects.create_user(username="socket-human")
    client.force_login(user, backend="config.auth.PlatformModelBackend")
    scope = {"session": client.session}
    assert validate_socket_session(scope)
    client.logout()
    assert not validate_socket_session(scope)


@pytest.mark.django_db
@pytest.mark.parametrize("now", [1901, 28900])
def test_idle_and_absolute_session_expiration_deny(django_user_model, settings, now):
    from config.session_credentials import establish_identity_session, validate_session

    settings.IDENTITY_PLATFORM_PROJECT_ID = "example"
    user = django_user_model.objects.create_user(username="expired-human")
    session = {BACKEND_SESSION_KEY: "config.identity_platform.IdentityPlatformBackend"}
    establish_identity_session(
        session, {"iss": "https://securetoken.google.com/example", "sub": "subject", "auth_time": 100}, now=100
    )
    assert not validate_session(user, session, now=now)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_socket_boundary_closes_once_when_logout_precedes_server_messages(client, django_user_model):
    from channels.db import database_sync_to_async

    from config.websocket_auth import CredentialSessionWebSocketBoundary

    user = await database_sync_to_async(django_user_model.objects.create_user)(username="live-socket")
    await database_sync_to_async(client.force_login)(user, backend="config.auth.PlatformModelBackend")
    session = await database_sync_to_async(lambda: client.session)()
    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "websocket.connect"}

    async def application(scope, receive, send):
        await receive()
        await send({"type": "websocket.accept"})
        await database_sync_to_async(client.logout)()
        await send({"type": "websocket.send", "text": "must not be delivered"})
        await send({"type": "websocket.send", "text": "must not be delivered either"})

    await CredentialSessionWebSocketBoundary(application)({"session": session}, receive, send)
    assert messages == [{"type": "websocket.accept"}, {"type": "websocket.close", "code": 4001}]
