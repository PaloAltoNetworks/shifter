"""Webhook delivery obeys the CTF pinned-destination egress boundary."""

from uuid import uuid4

import pytest


def test_webhook_loopback_destination_never_reaches_transport(monkeypatch):
    from ctf.services import webhook

    statuses = []
    monkeypatch.setattr(webhook.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(webhook, "_delivery_is_current", lambda *_args: True)
    monkeypatch.setattr(webhook, "_record_delivery", lambda _pk, status: statuses.append(status))
    monkeypatch.setattr("requests.post", lambda *_args, **_kwargs: pytest.fail("unsafe outbound request"))

    webhook._deliver_with_retries(uuid4(), "https://127.0.0.1/hook", "", b"{}")

    assert statuses == ["failed:blocked_destination"]


def test_webhook_uses_validated_pinned_ip_and_never_follows_redirect(monkeypatch):
    from ctf.services import webhook
    from ctf.validators import _ssrf

    statuses = []
    connections = []

    class FakeConnection:
        def request(self, method, path, *, body, headers):
            assert method == "POST"
            assert path == "/hook?phase=one"
            assert body == b"{}"
            assert headers["Content-Type"] == "application/json"

        def getresponse(self):
            return type("Response", (), {"status": 302})()

        def close(self):
            pass

    def build_connection(**kwargs):
        connections.append(kwargs)
        return FakeConnection()

    monkeypatch.setattr(_ssrf, "_resolve_and_validate", lambda hostname, port: ["8.8.8.8"])
    monkeypatch.setattr(_ssrf, "_build_https_connection", build_connection)
    monkeypatch.setattr(webhook.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(webhook, "_delivery_is_current", lambda *_args: True)
    monkeypatch.setattr(webhook, "_record_delivery", lambda _pk, status: statuses.append(status))
    monkeypatch.setattr("requests.post", lambda *_args, **_kwargs: pytest.fail("unvalidated outbound request"))

    webhook._deliver_with_retries(uuid4(), "https://hooks.example.test/hook?phase=one", "", b"{}")

    assert len(connections) == 3
    assert all(item["hostname"] == "hooks.example.test" and item["pinned_ip"] == "8.8.8.8" for item in connections)
    assert statuses == ["failed:302"]


@pytest.mark.django_db
def test_webhook_creation_rejects_private_destination(ctf_event):
    from ctf.exceptions import CTFValidationError
    from ctf.models import CTFWebhook
    from ctf.services.webhook import create_event_webhook

    with pytest.raises(CTFValidationError):
        create_event_webhook(
            ctf_event,
            url="https://127.0.0.1/hook",
            secret="",
            subscribed_events=["flag_solve"],
            actor_id=ctf_event.created_by_id,
        )
    assert not CTFWebhook.objects.filter(event=ctf_event).exists()


@pytest.mark.django_db
def test_revoked_or_changed_webhook_cancels_queued_delivery(ctf_event, monkeypatch):
    from ctf.models import CTFWebhook
    from ctf.services import webhook

    hook = CTFWebhook.objects.create(
        event=ctf_event,
        url="https://hooks.example.test/one",
        secret="synthetic-key",
        subscribed_events=["flag_solve"],
    )
    monkeypatch.setattr(webhook, "_post_pinned", lambda *_args: pytest.fail("revoked send reached transport"))
    monkeypatch.setattr(webhook.time, "sleep", lambda _seconds: None)

    hook.active = False
    hook.save(update_fields=["active"])
    webhook._deliver_with_retries(hook.pk, hook.url, hook.secret, b"{}", "flag_solve")
    hook.refresh_from_db()
    assert hook.last_status == "failed:revoked"

    hook.active = True
    hook.url = "https://hooks.example.test/two"
    hook.save(update_fields=["active", "url"])
    webhook._deliver_with_retries(hook.pk, "https://hooks.example.test/one", hook.secret, b"{}", "flag_solve")
    hook.refresh_from_db()
    assert hook.last_status == "failed:revoked"

    hook.subscribed_events = ["event_state_change"]
    hook.save(update_fields=["subscribed_events"])
    webhook._deliver_with_retries(hook.pk, hook.url, hook.secret, b"{}", "flag_solve")
    hook.refresh_from_db()
    assert hook.last_status == "failed:revoked"
