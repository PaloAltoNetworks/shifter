"""Guacamole session identity for isolated CTF accounts (issue #1740).

Isolated temporary CTF participant accounts (issue #1206) are created with a
blank ``email``. The Guacamole JSON-auth username must fall back to the unique
``range-<hex>`` username, otherwise Guacamole rejects the token exchange with
``400 "The username must not be blank."`` and the participant cannot reach their
range box.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from mission_control.views._guacamole import _resolve_and_build_rdp_url, guacamole_identity

User = get_user_model()

_CONN_INFO = {
    "connection_name": "dc01",
    "private_ip": "10.1.2.56",
    "host": "10.1.2.56",
    "os_type": "windows",
    "rdp_username": "Administrator",
    "rdp_password": "secret-password",
    "ssh_key": None,
}
_GUAC_SETTINGS = ("signing-secret", "https://example/guacamole", None)


def test_guacamole_identity_prefers_email_when_present():
    user = User(username="range-abcd1234", email="player@example.com")
    assert guacamole_identity(user) == "player@example.com"


def test_guacamole_identity_falls_back_to_username_when_email_blank():
    # Isolated CTF accounts carry a blank email; the unique username is the identity.
    user = User(username="range-abcd1234", email="")
    assert guacamole_identity(user) == "range-abcd1234"


def test_rdp_url_build_uses_nonblank_identity_for_email_less_account(monkeypatch):
    """The RDP flow must hand Guacamole a non-blank username for a blank-email account.

    Reverting the fix to ``user.email`` makes the captured username blank and
    this assertion fails, so the test guards the enforcement (issue #1740).
    """
    user = User(username="range-abcd1234", email="")
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "mission_control.views._guacamole._resolve_rdp_conn",
        lambda _user, _instance_uuid: dict(_CONN_INFO),
    )

    def _fake_create(req):
        captured["username"] = req.username
        return "https://example/guacamole/#/client/abc?token=t"

    monkeypatch.setattr("mission_control.guacamole.create_guacamole_rdp_url", _fake_create)

    url = _resolve_and_build_rdp_url(user=user, instance_uuid="inst-uuid", guac_settings=_GUAC_SETTINGS)

    assert captured["username"] == "range-abcd1234"
    assert captured["username"], "Guacamole username must never be blank"
    assert url.startswith("https://example/guacamole/#/client/")
