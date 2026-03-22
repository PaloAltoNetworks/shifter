"""Base class for AWS cloud adapters.

Provides shared boto3 client creation logic used by all AWS adapters.
"""

from __future__ import annotations

import os
from typing import Any

import boto3


class BaseAWSAdapter:
    """Base class providing shared AWS client creation.

    Subclasses set ``_service_name`` to the AWS service identifier
    (e.g. ``"s3"``, ``"ssm"``, ``"secretsmanager"``).
    """

    _service_name: str

    def _get_client(self) -> Any:
        region: str = os.environ.get("AWS_REGION", "us-east-2")
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client(self._service_name, region_name=region, endpoint_url=endpoint_url)
