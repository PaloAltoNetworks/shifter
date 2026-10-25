"""The authenticated client must enforce strict auth and scope imported cookies."""

import httpx
import pytest

from event_load_harness.auth import Actor, AuthError
from event_load_harness.auth_http import (
    _attach_cookies,
    _dev_login,
    _identity_platform_login,
    build_client,
    make_authenticator,
)


def test_build_client_disables_automatic_redirects():
    client = build_client("https://dev.example.com", 10.0)
    assert client.follow_redirects is False


def test_imported_cookies_are_scoped_to_target_host():
    # Hostless cookies could be forwarded to an off-origin redirect target; scoping
    # them to the configured host prevents that leak.
    client = build_client("https://dev.example.com", 10.0)
    _attach_cookies(client, "sessionid=abc; csrftoken=xyz", "https://dev.example.com")
    jar = list(client.cookies.jar)
    assert {c.name for c in jar} == {"sessionid", "csrftoken"}
    assert all(c.domain.lstrip(".") == "dev.example.com" for c in jar)


async def test_strict_auth_rejects_session_cookie_actor_before_network_access():
    authenticate = make_authenticator(require_identity_platform=True)
    actor = Actor(
        label="actor-0001",
        email="participant@example.invalid",
        session_cookie="sessionid=replayed",
    )

    with pytest.raises(AuthError, match="does not accept session cookies"):
        await authenticate("https://dev.example.invalid", actor)


@pytest.mark.parametrize(
    ("missing_field", "actor_kwargs"),
    [
        ("password", {"totp_secret": "totp", "api_key": "api"}),
        ("totp_secret", {"password": "password", "api_key": "api"}),
        ("api_key", {"password": "password", "totp_secret": "totp"}),
    ],
)
async def test_identity_platform_login_rejects_each_missing_credential(missing_field, actor_kwargs):
    def reject_network(_request):
        raise AssertionError("credential validation must happen before network access")

    actor = Actor(label="actor-0001", email="participant@example.invalid", **actor_kwargs)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject_network)) as client:
        with pytest.raises(AuthError, match="requires password, totp_secret, and api_key"):
            await _identity_platform_login(client, actor, timeout=1.0)

    assert getattr(actor, missing_field) is None


async def test_dev_login_http_failure_is_rejected():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, headers={"set-cookie": "csrftoken=csrf; Path=/"})
        return httpx.Response(403)

    actor = Actor(label="actor-0001", email="participant@example.invalid")
    async with httpx.AsyncClient(
        base_url="https://dev.example.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(AuthError, match=r"dev-login failed.*HTTP 403"):
            await _dev_login(client, actor, "/dev-login/")

    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[1].headers["X-CSRFToken"] == "csrf"
