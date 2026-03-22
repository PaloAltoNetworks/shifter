"""Tests for WebSocket consumer authentication, hydration, and broadcasting.

All ORM operations are mocked -- no database access.
These tests verify the consumer logic by mocking the internal DB helper methods.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser

from cms.experiments.consumers import ExperimentStatusConsumer
from cms.experiments.schemas import ExperimentStatus, RunStatus

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


def _build_communicator(experiment_id: int, user=None):
    """Build a WebsocketCommunicator with the given user in scope."""
    communicator = WebsocketCommunicator(
        ExperimentStatusConsumer.as_asgi(),
        f"/ws/experiment-status/{experiment_id}/",
    )
    communicator.scope["url_route"] = {"kwargs": {"experiment_id": str(experiment_id)}}
    communicator.scope["user"] = user
    return communicator


def _make_staff_user(pk=1):
    """Create a mock staff user."""
    user = MagicMock()
    user.pk = pk
    user.is_staff = True
    user.is_authenticated = True
    user.is_anonymous = False
    # Make isinstance(user, AnonymousUser) return False
    user.__class__ = type("User", (), {})
    return user


def _make_non_staff_user(pk=2):
    """Create a mock non-staff user."""
    user = MagicMock()
    user.pk = pk
    user.is_staff = False
    user.is_authenticated = True
    user.is_anonymous = False
    user.__class__ = type("User", (), {})
    return user


@pytest.mark.asyncio
class TestConsumerAuthentication:
    """5.3: Test consumer authentication (reject unauthenticated, reject non-owner)."""

    async def test_rejects_anonymous_user(self):
        communicator = _build_communicator(999, user=AnonymousUser())
        connected, code = await communicator.connect()
        assert connected is False
        assert code == 4001

    async def test_rejects_no_user(self):
        communicator = _build_communicator(999, user=None)
        connected, code = await communicator.connect()
        assert connected is False
        assert code == 4001

    async def test_rejects_non_staff_user(self):
        user = _make_non_staff_user()
        communicator = _build_communicator(999, user=user)
        connected, code = await communicator.connect()
        assert connected is False
        assert code == 4003

    async def test_rejects_non_owner(self):
        _make_staff_user(pk=1)
        other = _make_staff_user(pk=2)

        # Patch the consumer's _get_experiment to return None (not owner)
        with patch.object(ExperimentStatusConsumer, "_get_experiment", new_callable=AsyncMock, return_value=None):
            communicator = _build_communicator(100, user=other)
            connected, code = await communicator.connect()
            assert connected is False
            assert code == 4004

    async def test_accepts_owner(self):
        user = _make_staff_user(pk=1)
        mock_experiment = MagicMock()
        mock_experiment.status = ExperimentStatus.DRAFT.value

        with (
            patch.object(
                ExperimentStatusConsumer, "_get_experiment", new_callable=AsyncMock, return_value=mock_experiment
            ),
            patch.object(ExperimentStatusConsumer, "_get_runs", new_callable=AsyncMock, return_value=[]),
        ):
            communicator = _build_communicator(100, user=user)
            connected, _ = await communicator.connect()
            assert connected is True
            await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestConsumerHydration:
    """5.4: Test hydration on connect (initial state sent correctly)."""

    async def test_hydrate_message_on_connect(self):
        user = _make_staff_user(pk=1)
        mock_experiment = MagicMock()
        mock_experiment.status = ExperimentStatus.RUNNING.value

        mock_runs = [
            {"run_id": 1, "run_number": 1, "status": RunStatus.PROVISIONING.value, "error_message": ""},
            {"run_id": 2, "run_number": 2, "status": RunStatus.PENDING.value, "error_message": ""},
        ]

        with (
            patch.object(
                ExperimentStatusConsumer, "_get_experiment", new_callable=AsyncMock, return_value=mock_experiment
            ),
            patch.object(ExperimentStatusConsumer, "_get_runs", new_callable=AsyncMock, return_value=mock_runs),
        ):
            communicator = _build_communicator(100, user=user)
            connected, _ = await communicator.connect()
            assert connected is True

            response = await communicator.receive_json_from(timeout=3)
            assert response["type"] == "hydrate"
            assert response["experiment_id"] == 100
            assert response["experiment_status"] == ExperimentStatus.RUNNING.value
            assert len(response["runs"]) == 2
            assert response["runs"][0]["run_number"] == 1
            assert response["runs"][0]["status"] == RunStatus.PROVISIONING.value
            assert response["runs"][1]["run_number"] == 2
            assert response["runs"][1]["status"] == RunStatus.PENDING.value

            await communicator.disconnect()

    async def test_hydrate_empty_runs(self):
        user = _make_staff_user(pk=1)
        mock_experiment = MagicMock()
        mock_experiment.status = ExperimentStatus.DRAFT.value

        with (
            patch.object(
                ExperimentStatusConsumer, "_get_experiment", new_callable=AsyncMock, return_value=mock_experiment
            ),
            patch.object(ExperimentStatusConsumer, "_get_runs", new_callable=AsyncMock, return_value=[]),
        ):
            communicator = _build_communicator(100, user=user)
            connected, _ = await communicator.connect()
            assert connected is True

            response = await communicator.receive_json_from(timeout=3)
            assert response["type"] == "hydrate"
            assert response["runs"] == []

            await communicator.disconnect()


@pytest.mark.asyncio
class TestConsumerBroadcast:
    """5.5: Test broadcast reception (run status updates delivered to connected clients)."""

    async def test_receives_run_status_broadcast(self):
        """Verify experiment_run_status handler sends correct JSON to client."""
        consumer = ExperimentStatusConsumer()
        consumer.send = AsyncMock()

        await consumer.experiment_run_status(
            {
                "type": "experiment.run_status",
                "run_id": 42,
                "run_number": 1,
                "status": "executing_victims",
                "error_message": "",
            }
        )

        import json

        consumer.send.assert_called_once()
        response = json.loads(consumer.send.call_args[1]["text_data"])
        assert response["type"] == "run_status"
        assert response["run_id"] == 42
        assert response["run_number"] == 1
        assert response["status"] == "executing_victims"

    async def test_receives_experiment_status_broadcast(self):
        """Verify experiment_status handler sends correct JSON to client."""
        consumer = ExperimentStatusConsumer()
        consumer.send = AsyncMock()

        await consumer.experiment_status(
            {
                "type": "experiment.status",
                "experiment_id": 100,
                "status": "completed",
            }
        )

        import json

        consumer.send.assert_called_once()
        response = json.loads(consumer.send.call_args[1]["text_data"])
        assert response["type"] == "experiment_status"
        assert response["experiment_id"] == 100
        assert response["status"] == "completed"
