"""WebSocket URL routing for mission_control app."""

from django.urls import re_path

from mission_control.consumers import SSHConsumer

websocket_urlpatterns = [
    re_path(r"ws/terminal/(?P<range_id>\d+)/(?P<instance>kali|victim)/$", SSHConsumer.as_asgi()),
]
