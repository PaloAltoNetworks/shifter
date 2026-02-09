"""WebSocket URL routing for experiments app."""

from django.urls import re_path

from cms.experiments.consumers import ExperimentStatusConsumer

websocket_urlpatterns = [
    re_path(r"ws/experiment-status/(?P<experiment_id>\d+)/$", ExperimentStatusConsumer.as_asgi()),
]
