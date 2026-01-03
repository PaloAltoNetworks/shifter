"""Channel routing for CMS app."""

from shared.channels.groups import CHANNEL_CMS_STATUS

from .consumers import CMSRangeStatusConsumer

# Channel name router for background workers
channel_routing = {
    CHANNEL_CMS_STATUS: CMSRangeStatusConsumer.as_asgi(),
}
