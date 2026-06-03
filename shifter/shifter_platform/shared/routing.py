"""WebSocket URL routing for shared platform notifications."""

from django.urls import re_path

from shared.consumers import SharedNotificationConsumer

websocket_urlpatterns = [
    re_path(r"ws/notifications/$", SharedNotificationConsumer.as_asgi()),
]
