"""Bound credential-chain HTTP before constructing an AWS service client."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import boto3


def bounded_aws_session(region: str, *, proxy: str | None = None) -> boto3.Session:
    """Apply transport bounds to implicit web-identity refresh as well as STS.

    A Config on the final STS client alone does not reach the credential
    resolver's internally created AssumeRoleWithWebIdentity client. Session
    defaults do, including its unsigned request configuration merge.
    """
    import boto3
    from botocore.config import Config
    from botocore.session import Session

    session = Session()
    session.set_config_variable("region", region)
    session.set_config_variable("sts_regional_endpoints", "regional")
    session.set_config_variable("metadata_service_timeout", 2)
    session.set_config_variable("metadata_service_num_attempts", 1)
    session.set_default_client_config(
        Config(
            connect_timeout=2,
            read_timeout=2,
            retries={"total_max_attempts": 1},
            proxies={"https": proxy} if proxy else {},
        )
    )
    return boto3.Session(botocore_session=session)
