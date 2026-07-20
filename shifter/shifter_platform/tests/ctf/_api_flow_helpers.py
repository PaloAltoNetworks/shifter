"""Shared helpers for the CTF API integration-flow tests.

Not a test module (underscore prefix keeps pytest from collecting it).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django.urls import reverse

if TYPE_CHECKING:
    from django.test import Client

JSON = "application/json"


def call_json(client: Client, method: str, name: str, *, kwargs=None, body=None, query=""):
    """Call a named CTF route with an optional JSON body and return the response.

    A bare ``name`` (e.g. ``"api_event_list"``) is resolved against the canonical
    ``v1:ctf`` API namespace. Pass a fully-qualified name (containing a ``:``) to
    target a specific namespace, e.g. the legacy ``"ctf:api_scoreboard"`` route
    intentionally retained outside ``/api/v1`` (issue #1328).
    """
    route = name if ":" in name else f"v1:ctf:{name}"
    url = reverse(route, kwargs=kwargs or {}) + query
    fn = getattr(client, method)
    if body is None:
        return fn(url)
    return fn(url, data=json.dumps(body), content_type=JSON)
