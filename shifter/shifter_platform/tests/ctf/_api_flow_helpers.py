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
    """Call a named CTF route with an optional JSON body and return the response."""
    url = reverse(f"ctf:{name}", kwargs=kwargs or {}) + query
    fn = getattr(client, method)
    if body is None:
        return fn(url)
    return fn(url, data=json.dumps(body), content_type=JSON)
