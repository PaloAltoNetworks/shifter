"""Tests for shared WebSocket notification infrastructure."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.utils import timezone

from shared.models import WebSocketNotification


@pytest.fixture(autouse=True)
def clear_notification_registry():
    """Keep notification registrations isolated between tests."""
    from shared.notifications import clear_notification_registry

    clear_notification_registry()
    yield
    clear_notification_registry()


@pytest.fixture
def user(db):
    """Create a test user."""
    return get_user_model().objects.create_user(username="owner@example.com", email="owner@example.com")


def _register_experiment_type() -> None:
    from shared.notifications import register_notification_type

    register_notification_type(
        name="experiment.run_status",
        topic_prefix="experiment:",
        can_subscribe=lambda _user, _topic: True,
        payload_handler=lambda payload: {
            "run_id": payload["run_id"],
            "status": payload["status"],
        },
    )


def test_register_notification_type_validates_contract() -> None:
    """Registry entries validate names, topics, and callables."""
    from shared.notifications import register_notification_type

    registration = register_notification_type(
        name="experiment.status",
        topic_prefix="experiment:",
        can_subscribe=lambda _user, _topic: True,
    )

    assert registration.payload_handler({"status": "running"}) == {"status": "running"}
    assert (
        register_notification_type(
            name="experiment.status",
            topic_prefix="experiment:",
            can_subscribe=lambda _user, _topic: False,
        )
        is registration
    )
    with pytest.raises(ValueError):
        register_notification_type(
            name="Experiment",
            topic_prefix="experiment:",
            can_subscribe=lambda _user, _topic: True,
        )
    with pytest.raises(ValueError):
        register_notification_type(
            name="experiment.status",
            topic_prefix="not valid",
            can_subscribe=lambda _user, _topic: True,
        )
    with pytest.raises(TypeError):
        register_notification_type(name="experiment.status", topic_prefix="experiment:", can_subscribe=True)
    with pytest.raises(TypeError):
        register_notification_type(
            name="experiment.status",
            topic_prefix="experiment:",
            can_subscribe=lambda _user, _topic: True,
            payload_handler=True,
            replace=True,
        )


def test_authorize_subscription_handles_invalid_and_failing_authorizers(caplog) -> None:
    """Authorization failures deny access without breaking the socket path."""
    from shared.notifications import authorize_subscription, register_notification_type

    authenticated = MagicMock(is_authenticated=True, id=7)
    unauthenticated = MagicMock(is_authenticated=False, id=8)

    def failing_authorizer(_user, _topic):
        raise RuntimeError("boom")

    register_notification_type(
        name="experiment.status",
        topic_prefix="experiment:",
        can_subscribe=failing_authorizer,
    )

    assert authorize_subscription(unauthenticated, "experiment:100") is False
    assert authorize_subscription(authenticated, "not valid") is False
    assert authorize_subscription(authenticated, "experiment:100") is False
    assert "notification authorizer failed" in caplog.text


def test_publish_notification_validates_registration_and_event_id(user) -> None:
    """Publish rejects unknown contracts and accepts string event ids."""
    from shared.notifications import publish_notification

    with pytest.raises(ValueError, match="unknown notification type"):
        publish_notification(
            "experiment.status",
            topic="experiment:100",
            payload={},
            recipient_ids=[user.id],
        )

    _register_experiment_type()
    with pytest.raises(ValueError, match="not valid for notification type"):
        publish_notification(
            "experiment.run_status",
            topic="range:100",
            payload={"run_id": 7, "status": "running"},
            recipient_ids=[user.id],
        )

    with patch("shared.notifications.get_channel_layer", return_value=None):
        [notification] = publish_notification(
            "experiment.run_status",
            topic="experiment:100",
            payload={"run_id": 7, "status": "running"},
            recipient_ids=[user.id, user.id],
            event_id="12345678-1234-5678-1234-567812345678",
        )

    assert str(notification.event_id) == "12345678-1234-5678-1234-567812345678"
    assert WebSocketNotification.objects.count() == 1


@pytest.mark.django_db
def test_publish_notification_generates_event_id_when_not_supplied(user):
    """Publish generates an idempotency key when the source event has no id."""
    from shared.notifications import publish_notification

    _register_experiment_type()

    with patch("shared.notifications.get_channel_layer", return_value=None):
        [notification] = publish_notification(
            "experiment.run_status",
            topic="experiment:100",
            payload={"run_id": 7, "status": "running"},
            recipient_ids=[user.id],
        )

    assert isinstance(notification.event_id, UUID)


@pytest.mark.django_db
def test_publish_notification_persists_and_fans_out(user):
    """Publishing stores a per-recipient row and sends to the user/topic group."""
    from shared.notifications import publish_notification

    _register_experiment_type()
    event_id = uuid4()

    with (
        patch("shared.notifications.get_channel_layer") as mock_get_channel_layer,
        patch("shared.notifications.async_to_sync") as mock_async_to_sync,
    ):
        mock_channel_layer = MagicMock()
        mock_get_channel_layer.return_value = mock_channel_layer
        mock_send = MagicMock()
        mock_async_to_sync.return_value = mock_send

        notifications = publish_notification(
            "experiment.run_status",
            topic="experiment:100",
            payload={"run_id": 7, "status": "running", "unsafe": "drop"},
            recipient_ids=[user.id],
            event_id=event_id,
        )

    assert [notification.recipient_id for notification in notifications] == [user.id]
    stored = WebSocketNotification.objects.get()
    assert stored.notification_type == "experiment.run_status"
    assert stored.topic == "experiment:100"
    assert stored.event_id == event_id
    assert stored.payload == {"run_id": 7, "status": "running"}
    mock_async_to_sync.assert_called_once_with(mock_channel_layer.group_send)
    group_name, event = mock_send.call_args.args
    assert group_name.startswith(f"notify_u{user.id}_")
    assert event["type"] == "notification.dispatch"
    assert event["notification_id"] == stored.id


@pytest.mark.django_db
def test_publish_notification_is_idempotent_per_recipient_topic_type_and_event(user):
    """Duplicate source events do not enqueue duplicate missed notifications."""
    from shared.notifications import publish_notification

    _register_experiment_type()
    event_id = UUID("12345678-1234-5678-1234-567812345678")

    with patch("shared.notifications.get_channel_layer", return_value=None):
        first = publish_notification(
            "experiment.run_status",
            topic="experiment:100",
            payload={"run_id": 7, "status": "running"},
            recipient_ids=[user.id],
            event_id=event_id,
        )
        second = publish_notification(
            "experiment.run_status",
            topic="experiment:100",
            payload={"run_id": 7, "status": "running"},
            recipient_ids=[user.id],
            event_id=event_id,
        )

    assert first[0].id == second[0].id
    assert WebSocketNotification.objects.count() == 1
    assert str(WebSocketNotification.objects.get()) == f"experiment.run_status:experiment:100:{user.id}"


@pytest.mark.django_db
def test_publish_notification_handles_concurrent_insert_race(user):
    """A uniqueness race falls back to the row created by the competing transaction."""
    from shared.notifications import publish_notification

    _register_experiment_type()
    event_id = UUID("12345678-1234-5678-1234-567812345678")
    existing = WebSocketNotification.objects.create(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        event_id=event_id,
        payload={"run_id": 7, "status": "running"},
        expires_at=timezone.now() + timedelta(days=1),
    )

    with (
        patch("shared.notifications.WebSocketNotification.objects.get_or_create", side_effect=IntegrityError),
        patch("shared.notifications.WebSocketNotification.objects.get", return_value=existing) as mock_get,
        patch("shared.notifications.get_channel_layer", return_value=None),
    ):
        [notification] = publish_notification(
            "experiment.run_status",
            topic="experiment:100",
            payload={"run_id": 7, "status": "running"},
            recipient_ids=[user.id],
            event_id=event_id,
        )

    assert notification == existing
    mock_get.assert_called_once_with(
        recipient_id=user.id,
        topic="experiment:100",
        notification_type="experiment.run_status",
        event_id=event_id,
    )


@pytest.mark.django_db
def test_pending_notifications_exclude_delivered_and_expired(user, settings):
    """Replay queries only return undelivered, unexpired rows for the topic."""
    from shared.notifications import pending_notifications_for

    settings.WEBSOCKET_NOTIFICATION_MAX_REPLAY = 10
    now = timezone.now()
    WebSocketNotification.objects.create(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"status": "running"},
        expires_at=now + timedelta(days=1),
    )
    WebSocketNotification.objects.create(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"status": "delivered"},
        delivered_at=now,
        expires_at=now + timedelta(days=1),
    )
    WebSocketNotification.objects.create(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"status": "expired"},
        expires_at=now - timedelta(seconds=1),
    )

    pending = pending_notifications_for(user.id, "experiment:100")

    assert [notification.payload for notification in pending] == [{"status": "running"}]


@pytest.mark.django_db
def test_prune_notifications_management_command_removes_expired_rows(user):
    """The operational cleanup command deletes expired notification rows."""
    now = timezone.now()
    expired = WebSocketNotification.objects.create(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"status": "expired"},
        expires_at=now - timedelta(seconds=1),
    )
    active = WebSocketNotification.objects.create(
        recipient=user,
        notification_type="experiment.run_status",
        topic="experiment:100",
        payload={"status": "active"},
        expires_at=now + timedelta(days=1),
    )

    out = StringIO()
    call_command("prune_notifications", stdout=out)

    assert not WebSocketNotification.objects.filter(pk=expired.pk).exists()
    assert WebSocketNotification.objects.filter(pk=active.pk).exists()
    assert "Deleted 1 expired WebSocket notification" in out.getvalue()
