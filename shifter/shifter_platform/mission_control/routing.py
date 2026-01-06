"""WebSocket URL routing for mission_control app."""

from django.urls import re_path

from mission_control.consumers import RangeStatusConsumer, SSHConsumer

websocket_urlpatterns = [
    re_path(r"ws/terminal/(?P<instance_uuid>[a-f0-9-]+)/$", SSHConsumer.as_asgi()),
    re_path(r"ws/range-status/(?P<range_id>\d+)/$", RangeStatusConsumer.as_asgi()),
]
