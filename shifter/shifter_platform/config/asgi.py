"""
ASGI config for Shifter platform.

Configures Django Channels for:
- WebSocket support (terminal SSH connections, range status updates)

Background status processing is handled by SQS workers (run_worker management command).
"""

import os
import sys
from pathlib import Path

# Add shifter/ to path so 'cyberscript' package is importable
SHIFTER_DIR = Path(__file__).resolve().parent.parent.parent
if str(SHIFTER_DIR) not in sys.path:
    sys.path.insert(0, str(SHIFTER_DIR))

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Initialize Django ASGI application early to ensure AppRegistry is populated
django_asgi_app = get_asgi_application()

# Import routing after Django setup
from cms.experiments.routing import websocket_urlpatterns as experiment_ws_urlpatterns  # noqa: E402
from mission_control.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns + experiment_ws_urlpatterns))
        ),
    }
)
