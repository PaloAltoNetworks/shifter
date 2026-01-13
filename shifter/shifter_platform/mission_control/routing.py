"""WebSocket URL routing for mission_control app."""

from django.urls import re_path

from mission_control.consumers import NGFWStatusConsumer, RangeStatusConsumer, SSHConsumer

websocket_urlpatterns = [
    re_path(r"ws/terminal/(?P<instance_uuid>[a-f0-9-]+)/$", SSHConsumer.as_asgi()),
    re_path(r"ws/range-status/(?P<request_id>[a-f0-9-]+)/$", RangeStatusConsumer.as_asgi()),
    re_path(r"ws/ngfw-status/(?P<app_id>[a-f0-9-]+)/$", NGFWStatusConsumer.as_asgi()),
]
