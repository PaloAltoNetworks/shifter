"""WebSocket consumer for experiment status updates.

Follows the RangeStatusConsumer pattern from mission_control.consumers.
Clients connect to receive real-time run/experiment status changes.
"""

from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from experiments.models import Experiment, ExperimentRun

logger = logging.getLogger(__name__)


def experiment_event_group(experiment_id: int | str) -> str:
    """Return the channel group name for an experiment."""
    return f"experiment_{experiment_id}"


class ExperimentStatusConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for streaming experiment and run status updates.

    Clients connect to ws/experiment-status/<experiment_id>/ to receive
    real-time status updates for runs within that experiment.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.experiment_id: int | None = None
        self.group_name: str | None = None

    async def connect(self):
        """Authenticate user and join experiment channel group."""
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser):
            await self.close(code=4001)
            return

        if not user.is_staff:
            await self.close(code=4003)
            return

        self.experiment_id = int(self.scope["url_route"]["kwargs"]["experiment_id"])

        # Verify ownership
        experiment = await self._get_experiment(user, self.experiment_id)
        if experiment is None:
            await self.close(code=4004)
            return

        self.group_name = experiment_event_group(self.experiment_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Hydrate client with current state
        runs = await self._get_runs(self.experiment_id)
        await self.send(text_data=json.dumps({
            "type": "hydrate",
            "experiment_id": self.experiment_id,
            "experiment_status": experiment.status,
            "runs": runs,
        }))

    async def disconnect(self, close_code):
        """Leave channel group on disconnect."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def experiment_run_status(self, event):
        """Handle run status update broadcast."""
        await self.send(text_data=json.dumps({
            "type": "run_status",
            "run_id": event.get("run_id"),
            "run_number": event.get("run_number"),
            "status": event.get("status"),
            "error_message": event.get("error_message", ""),
        }))

    async def experiment_status(self, event):
        """Handle experiment-level status update broadcast."""
        await self.send(text_data=json.dumps({
            "type": "experiment_status",
            "experiment_id": event.get("experiment_id"),
            "status": event.get("status"),
        }))

    @database_sync_to_async
    def _get_experiment(self, user, experiment_id: int) -> Experiment | None:
        """Get experiment, verifying ownership."""
        try:
            return Experiment.objects.get(pk=experiment_id, user=user)
        except Experiment.DoesNotExist:
            return None

    @database_sync_to_async
    def _get_runs(self, experiment_id: int) -> list[dict]:
        """Get current run statuses for hydration."""
        runs = ExperimentRun.objects.filter(
            experiment_id=experiment_id,
        ).order_by("run_number").values(
            "pk", "run_number", "status", "error_message",
        )
        return [
            {
                "run_id": r["pk"],
                "run_number": r["run_number"],
                "status": r["status"],
                "error_message": r["error_message"] or "",
            }
            for r in runs
        ]
