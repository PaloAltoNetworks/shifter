"""
Gunicorn configuration for Shifter platform.

Uses Uvicorn workers to serve the Django Channels ASGI application
with multiple worker processes, enabling multi-core utilization for
concurrent HTTP and WebSocket connections.
"""

import multiprocessing
import os

# ASGI application
wsgi_app = "config.asgi:application"

# Bind
bind = "0.0.0.0:8000"

# Worker configuration
# UvicornWorker: each worker runs an async event loop handling HTTP + WebSocket
worker_class = "uvicorn.workers.UvicornWorker"

# Worker count: override with WEB_WORKERS env var, or auto-detect from CPU cores.
# Formula: (2 * cores) + 1 is the Gunicorn recommendation for I/O-mixed workloads.
workers = int(os.environ.get("WEB_WORKERS", (2 * multiprocessing.cpu_count()) + 1))

# Timeouts
# Graceful timeout must be long enough for WebSocket connections (terminal SSH)
# to drain during a rolling restart.
graceful_timeout = 120
timeout = 120

# Keep-alive: slightly above ALB default (60s) to let the ALB close first,
# avoiding 502s from the ALB hitting a closed backend connection.
keepalive = 65

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Preload app for faster worker startup and shared memory
preload_app = False  # Disabled: Django Channels requires per-worker app init

# Forwarded headers - trust ALB's X-Forwarded-* headers
forwarded_allow_ips = "*"
