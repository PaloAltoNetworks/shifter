"""Shared botocore client configuration for request-adjacent AWS clients.

Secrets Manager reads happen on (or one hop off) the portal request path, so a
stalled endpoint must fail fast instead of hanging on botocore's long default
connect/read timeouts — a single slow call otherwise head-of-line-blocks an ASGI
worker (#929). This module is the single place that timeout/retry policy lives so
adapters stop hand-rolling raw ``boto3.client(...)`` shapes.

Other request-adjacent AWS adapters should adopt this helper rather than invent
their own constants. It is intentionally scoped to Secrets Manager: the SQS
consumer relies on long-poll ``WaitTimeSeconds`` (a short read timeout would
break it) and large S3 transfers need their own, longer, read timeouts, so those
adapters supply their own values when they adopt the pattern.
"""

from __future__ import annotations

from botocore.config import Config
from django.conf import settings

_DEFAULT_CONNECT_TIMEOUT_SECONDS = 2
_DEFAULT_READ_TIMEOUT_SECONDS = 5
_DEFAULT_MAX_ATTEMPTS = 2


def secrets_client_config() -> Config:
    """Return a botocore ``Config`` with bounded timeouts for Secrets Manager.

    ``max_attempts`` is the total attempt count (first try + retries) in
    botocore's ``standard`` retry mode. Values are clamped to a sane minimum so
    a misconfigured ``0`` never disables the bound entirely.
    """
    connect_timeout = max(
        1, int(getattr(settings, "AWS_SECRETS_CONNECT_TIMEOUT_SECONDS", _DEFAULT_CONNECT_TIMEOUT_SECONDS))
    )
    read_timeout = max(1, int(getattr(settings, "AWS_SECRETS_READ_TIMEOUT_SECONDS", _DEFAULT_READ_TIMEOUT_SECONDS)))
    max_attempts = max(1, int(getattr(settings, "AWS_SECRETS_MAX_ATTEMPTS", _DEFAULT_MAX_ATTEMPTS)))
    return Config(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries={"max_attempts": max_attempts, "mode": "standard"},
    )
