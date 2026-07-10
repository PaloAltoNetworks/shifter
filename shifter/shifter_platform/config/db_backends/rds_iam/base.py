"""PostgreSQL backend that authenticates with an AWS RDS IAM token.

This wraps the stock ``django.db.backends.postgresql`` backend and, on every
new connection, mints a short-lived (15-minute) RDS IAM authentication token
and uses it as the database password. The running portal therefore holds no
long-lived database password: the credential is the IAM principal of the
instance role, and ``generate_db_auth_token`` is a local SigV4 signing
operation (no network round-trip) so minting one per connection is cheap.

Everything except credential acquisition is inherited from the postgresql
backend. SSL is enforced by the connection ``OPTIONS`` (``sslmode``) configured
in ``config.settings``; RDS rejects IAM authentication over an unencrypted
connection, so a missing/looser ``sslmode`` fails at the database, not here.

The DB user (``DB_USER``) and host (``DB_HOST``) come from the connection
settings; the AWS region comes from ``DB_IAM_REGION`` or the standard
``AWS_REGION`` / ``AWS_DEFAULT_REGION`` environment variables.
"""

from __future__ import annotations

import os
import threading

import boto3
from botocore.client import BaseClient
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.postgresql import base

# boto3 clients are thread-safe and cache instance-role credentials (which the
# SDK refreshes automatically), so one client per region is reused across
# connections rather than constructed per connect.
_clients: dict[str, BaseClient] = {}
_clients_lock = threading.Lock()


def _resolve_region() -> str:
    """Return the AWS region used to sign IAM tokens, failing loud if unset."""
    region = (
        os.environ.get("DB_IAM_REGION") or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or ""
    ).strip()
    if not region:
        raise ImproperlyConfigured("RDS IAM authentication requires an AWS region; set DB_IAM_REGION or AWS_REGION.")
    return region


def _rds_client(region: str) -> BaseClient:
    """Return a cached boto3 RDS client for ``region`` (created once per region)."""
    client = _clients.get(region)
    if client is None:
        with _clients_lock:
            client = _clients.get(region)
            if client is None:
                client = boto3.client("rds", region_name=region)
                _clients[region] = client
    return client


def generate_iam_auth_token(host: str, port: int, user: str, region: str) -> str:
    """Return a fresh RDS IAM auth token for ``user`` on ``host``."""
    return _rds_client(region).generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user, Region=region)


class DatabaseWrapper(base.DatabaseWrapper):
    """PostgreSQL wrapper that injects an RDS IAM token as the password."""

    def get_connection_params(self) -> dict[str, object]:
        params = super().get_connection_params()
        host = params.get("host")
        user = params.get("user")
        if not host or not user:
            raise ImproperlyConfigured("RDS IAM authentication requires DB_HOST and DB_USER to be set.")
        port = int(params.get("port") or 5432)
        params["password"] = generate_iam_auth_token(host, port, user, _resolve_region())
        return params
