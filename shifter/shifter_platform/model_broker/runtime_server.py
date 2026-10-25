"""Signal-driven admission and transport drain for the standalone broker."""

from types import FrameType
from typing import TYPE_CHECKING, cast

import uvicorn

if TYPE_CHECKING:
    from model_broker.server import BrokerApplication


class DrainingServer(uvicorn.Server):
    """Notify the application before Uvicorn waits for active HTTP tasks."""

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        cast("BrokerApplication", self.config.app).begin_drain()
        super().handle_exit(sig, frame)
