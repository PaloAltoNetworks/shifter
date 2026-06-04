"""Tests for experiment notification registration and publishing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cms.experiments.notifications import (
    _experiment_id_from_topic,
    _experiment_status_payload,
    _run_status_payload,
    experiment_topic,
    publish_experiment_run_status_notification,
    register_experiment_notifications,
)


@pytest.fixture(autouse=True)
def clear_notification_registry():
    """Keep notification registrations isolated between tests."""
    from shared.notifications import clear_notification_registry

    clear_notification_registry()
    yield
    clear_notification_registry()


def test_register_experiment_notifications_authorizes_staff_owner() -> None:
    """Experiment topics use the existing staff-owner access rule."""
    register_experiment_notifications()
    staff_owner = MagicMock(id=7, is_staff=True, is_authenticated=True)

    with patch("cms.experiments.notifications.Experiment.objects.filter") as mock_filter:
        mock_filter.return_value.exists.return_value = True

        from shared.notifications import authorize_subscription

        assert authorize_subscription(staff_owner, experiment_topic(100)) is True

    mock_filter.assert_called_once_with(pk=100, user=staff_owner)


def test_register_experiment_notifications_rejects_non_staff() -> None:
    """Experiment topics remain staff-only like the existing status socket."""
    register_experiment_notifications()
    non_staff = MagicMock(id=7, is_staff=False, is_authenticated=True)

    from shared.notifications import authorize_subscription

    assert authorize_subscription(non_staff, experiment_topic(100)) is False


def test_register_experiment_notifications_rejects_invalid_topics() -> None:
    """Experiment subscription authorization rejects malformed experiment topics."""
    register_experiment_notifications()
    staff_owner = MagicMock(id=7, is_staff=True, is_authenticated=True)

    from shared.notifications import authorize_subscription

    assert authorize_subscription(staff_owner, "range:100") is False
    assert authorize_subscription(staff_owner, "experiment:not-int") is False
    assert authorize_subscription(staff_owner, "experiment:0") is False


def test_experiment_id_from_topic_rejects_non_experiment_topic() -> None:
    """Topic parsing only accepts experiment notification topics."""
    assert _experiment_id_from_topic("range:100") is None


def test_notification_payload_projectors_return_browser_safe_fields() -> None:
    """Registered payload handlers strip unneeded source fields."""
    assert _run_status_payload(
        {
            "experiment_id": 100,
            "run_id": 5,
            "run_number": 2,
            "status": "completed",
            "unsafe": "drop",
        }
    ) == {
        "experiment_id": 100,
        "run_id": 5,
        "run_number": 2,
        "status": "completed",
        "error_message": "",
    }
    assert _experiment_status_payload(
        {
            "experiment_id": 100,
            "status": "failed",
            "unsafe": "drop",
        }
    ) == {
        "experiment_id": 100,
        "status": "failed",
    }


def test_publish_experiment_run_status_notification_projects_safe_payload() -> None:
    """Experiment publishers pass only the browser-safe payload to shared notifications."""
    with patch("cms.experiments.notifications.publish_notification") as mock_publish:
        publish_experiment_run_status_notification(
            experiment_id=100,
            recipient_id=7,
            run_id=5,
            run_number=2,
            status="completed",
            error_message="",
        )

    mock_publish.assert_called_once_with(
        "experiment.run_status",
        topic=experiment_topic(100),
        payload={
            "experiment_id": 100,
            "run_id": 5,
            "run_number": 2,
            "status": "completed",
            "error_message": "",
        },
        recipient_ids=[7],
        event_id=None,
    )
