"""Channel routing for Engine app."""

from shared.channels.groups import CHANNEL_ENGINE_STATUS

from .consumers import EngineRangeStatusConsumer

# Channel name router for background workers
channel_routing = {
    CHANNEL_ENGINE_STATUS: EngineRangeStatusConsumer.as_asgi(),
}
