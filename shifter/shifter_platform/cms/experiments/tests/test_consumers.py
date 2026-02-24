"""Tests for WebSocket consumer authentication, hydration, and broadcasting."""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser, User

from cms.experiments.consumers import ExperimentStatusConsumer
from cms.experiments.models import Experiment, ExperimentRun
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


@pytest.mark.django_db(transaction=True)
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
        user = await database_sync_to_async(User.objects.create_user)(
            username="ws_nonstaf", password=TEST_PASSWORD, is_staff=False
        )
        communicator = _build_communicator(999, user=user)
        connected, code = await communicator.connect()
        assert connected is False
        assert code == 4003

    async def test_rejects_non_owner(self):
        owner = await database_sync_to_async(User.objects.create_user)(
            username="ws_owner", password=TEST_PASSWORD, is_staff=True
        )
        other = await database_sync_to_async(User.objects.create_user)(
            username="ws_other", password=TEST_PASSWORD, is_staff=True
        )
        exp = await database_sync_to_async(Experiment.objects.create)(
            user=owner, name="Owner Only", scenario_id="basic"
        )
        communicator = _build_communicator(exp.pk, user=other)
        connected, code = await communicator.connect()
        assert connected is False
        assert code == 4004

    async def test_accepts_owner(self):
        user = await database_sync_to_async(User.objects.create_user)(
            username="ws_accepted", password=TEST_PASSWORD, is_staff=True
        )
        exp = await database_sync_to_async(Experiment.objects.create)(
            user=user, name="Accept Test", scenario_id="basic"
        )
        communicator = _build_communicator(exp.pk, user=user)
        connected, _ = await communicator.connect()
        assert connected is True
        await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestConsumerHydration:
    """5.4: Test hydration on connect (initial state sent correctly)."""

    async def test_hydrate_message_on_connect(self):
        user = await database_sync_to_async(User.objects.create_user)(
            username="ws_hydrate", password=TEST_PASSWORD, is_staff=True
        )
        exp = await database_sync_to_async(Experiment.objects.create)(
            user=user, name="Hydrate Test", scenario_id="basic", status=ExperimentStatus.RUNNING.value
        )
        await database_sync_to_async(ExperimentRun.objects.create)(
            experiment=exp, run_number=1, status=RunStatus.PROVISIONING.value
        )
        await database_sync_to_async(ExperimentRun.objects.create)(
            experiment=exp, run_number=2, status=RunStatus.PENDING.value
        )

        communicator = _build_communicator(exp.pk, user=user)
        connected, _ = await communicator.connect()
        assert connected is True

        # First message should be hydration
        response = await communicator.receive_json_from(timeout=3)
        assert response["type"] == "hydrate"
        assert response["experiment_id"] == exp.pk
        assert response["experiment_status"] == ExperimentStatus.RUNNING.value
        assert len(response["runs"]) == 2
        assert response["runs"][0]["run_number"] == 1
        assert response["runs"][0]["status"] == RunStatus.PROVISIONING.value
        assert response["runs"][1]["run_number"] == 2
        assert response["runs"][1]["status"] == RunStatus.PENDING.value

        await communicator.disconnect()

    async def test_hydrate_empty_runs(self):
        user = await database_sync_to_async(User.objects.create_user)(
            username="ws_empty", password=TEST_PASSWORD, is_staff=True
        )
        exp = await database_sync_to_async(Experiment.objects.create)(user=user, name="Empty Runs", scenario_id="basic")

        communicator = _build_communicator(exp.pk, user=user)
        connected, _ = await communicator.connect()
        assert connected is True

        response = await communicator.receive_json_from(timeout=3)
        assert response["type"] == "hydrate"
        assert response["runs"] == []

        await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestConsumerBroadcast:
    """5.5: Test broadcast reception (run status updates delivered to connected clients)."""

    async def test_receives_run_status_broadcast(self):
        user = await database_sync_to_async(User.objects.create_user)(
            username="ws_bcast", password=TEST_PASSWORD, is_staff=True
        )
        exp = await database_sync_to_async(Experiment.objects.create)(
            user=user, name="Broadcast Test", scenario_id="basic", status=ExperimentStatus.RUNNING.value
        )

        communicator = _build_communicator(exp.pk, user=user)
        connected, _ = await communicator.connect()
        assert connected is True

        # Consume the hydration message
        await communicator.receive_json_from(timeout=3)

        # Send a run_status broadcast to the group
        from channels.layers import get_channel_layer

        from cms.experiments.consumers import experiment_event_group

        channel_layer = get_channel_layer()
        group = experiment_event_group(exp.pk)
        await channel_layer.group_send(
            group,
            {
                "type": "experiment.run_status",
                "run_id": 42,
                "run_number": 1,
                "status": "executing_victims",
                "error_message": "",
            },
        )

        # Receive the broadcast
        response = await communicator.receive_json_from(timeout=3)
        assert response["type"] == "run_status"
        assert response["run_id"] == 42
        assert response["run_number"] == 1
        assert response["status"] == "executing_victims"

        await communicator.disconnect()

    async def test_receives_experiment_status_broadcast(self):
        user = await database_sync_to_async(User.objects.create_user)(
            username="ws_expstat", password=TEST_PASSWORD, is_staff=True
        )
        exp = await database_sync_to_async(Experiment.objects.create)(
            user=user, name="Exp Status Broadcast", scenario_id="basic", status=ExperimentStatus.RUNNING.value
        )

        communicator = _build_communicator(exp.pk, user=user)
        connected, _ = await communicator.connect()
        assert connected is True

        # Consume the hydration message
        await communicator.receive_json_from(timeout=3)

        # Send an experiment_status broadcast
        from channels.layers import get_channel_layer

        from cms.experiments.consumers import experiment_event_group

        channel_layer = get_channel_layer()
        group = experiment_event_group(exp.pk)
        await channel_layer.group_send(
            group,
            {
                "type": "experiment.status",
                "experiment_id": exp.pk,
                "status": "completed",
            },
        )

        response = await communicator.receive_json_from(timeout=3)
        assert response["type"] == "experiment_status"
        assert response["experiment_id"] == exp.pk
        assert response["status"] == "completed"

        await communicator.disconnect()
