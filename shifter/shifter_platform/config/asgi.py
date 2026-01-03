"""
ASGI config for Shifter platform.

Configures Django Channels for:
- WebSocket support (terminal SSH connections, range status updates)
- Channel workers (Engine and CMS status consumers)
"""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ChannelNameRouter, ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Initialize Django ASGI application early to ensure AppRegistry is populated
django_asgi_app = get_asgi_application()

# Import routing after Django setup
from cms.routing import channel_routing as cms_channel_routing  # noqa: E402
from engine.routing import channel_routing as engine_channel_routing  # noqa: E402
from mission_control.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
        # Channel workers for background consumers
        "channel": ChannelNameRouter({
            **engine_channel_routing,
            **cms_channel_routing,
        }),
    }
)
