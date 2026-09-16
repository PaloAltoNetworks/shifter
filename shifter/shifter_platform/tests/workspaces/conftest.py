"""Workspace-test fixtures that stop at external system boundaries."""

from __future__ import annotations

from queue import Queue
from unittest.mock import patch

import pytest


@pytest.fixture
def recorded_workspace_email():
    """Record delivery at Django's SMTP-message boundary.

    Invitation tests drive the real rendering, transaction.on_commit callback,
    async dispatcher, and shared email service. Only the third-party SMTP
    message object is replaced, per ADR-019-R1.
    """
    deliveries: Queue = Queue()

    class RecordingMessage:
        def __init__(self, subject=None, body=None, from_email=None, to=None, **kwargs):
            self.subject = subject
            self.body = body
            self.from_email = from_email
            self.to = to
            self.alternatives: list[tuple[str, str]] = []

        def attach_alternative(self, content, mimetype):
            self.alternatives.append((content, mimetype))

        def send(self):
            deliveries.put(self)
            return 1

    with patch("django.core.mail.EmailMultiAlternatives", RecordingMessage):
        yield deliveries
