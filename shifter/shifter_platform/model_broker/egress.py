"""Explicit broker-only proxy configuration; participant requests cannot set it."""

import os
import re


def provider_proxy() -> str | None:
    """Select the fixed internal CONNECT tunnel; provider TLS remains end-to-end."""
    value = os.environ.get("MODEL_PROVIDER_PROXY", "")
    if not value:
        return None
    if not re.fullmatch(r"http://model-provider-egress\.[a-z0-9-]{1,63}\.svc:3128", value):
        raise ValueError("invalid provider egress service")
    return value
