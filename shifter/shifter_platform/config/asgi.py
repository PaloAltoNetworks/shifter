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

# Log resolved settings posture once per portal process (#849, #948). The
# production portal runs Gunicorn with PORTAL_WEB_WORKERS Uvicorn workers
# (entrypoint.sh, #174), so this module is imported once per worker process and
# each worker serves both HTTP and WebSocket and consumes CHANNEL_LAYERS;
# logging is configured by get_asgi_application() above. An invalid/
# redis-without-host posture already fails closed at settings import.
from config._posture import log_settings_posture  # noqa: E402

log_settings_posture(os.environ)

# Start the per-worker portal capacity metrics emitter (#940). This module is
# imported once per Uvicorn worker process, so each worker gets exactly one
# daemon emitter. The factory is fully fail-soft: when metrics are disabled, the
# NamePrefix is missing, or the CloudWatch client cannot be built it returns None
# and worker boot continues. Kept module-global so the worker holds a reference
# for the process lifetime (the thread is a daemon and needs no explicit join).
from django.conf import settings  # noqa: E402

from config.capacity_metrics import build_emitter_from_config  # noqa: E402

portal_capacity_emitter = build_emitter_from_config(
    enabled=settings.PORTAL_CAPACITY_METRICS_ENABLED,
    name_prefix=settings.PORTAL_CAPACITY_NAME_PREFIX,
    interval_seconds=settings.PORTAL_CAPACITY_METRICS_INTERVAL_SECONDS,
    soft_concurrency=settings.PORTAL_WORKER_SOFT_CONCURRENCY,
    terminal_max_sessions=settings.TERMINAL_MAX_SESSIONS,
)

# Import routing after Django setup
from mission_control.routing import websocket_urlpatterns  # noqa: E402
from shared.routing import websocket_urlpatterns as shared_ws_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns + shared_ws_urlpatterns))
        ),
    }
)
