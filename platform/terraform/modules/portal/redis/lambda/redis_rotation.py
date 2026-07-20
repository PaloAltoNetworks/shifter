"""Secrets Manager rotation Lambda for the portal Redis AUTH token (#159).

Implements the four-step Secrets Manager rotation protocol for the ElastiCache
replication-group AUTH token that backs the portal Django Channels layer.

The ElastiCache ``ROTATE`` update strategy keeps the *previous* token valid
alongside the new one, so the running portal (which hydrates ``REDIS_PASSWORD``
at container start) is never locked out mid-rotation. ``finishSecret`` promotes
the new token to ``AWSCURRENT`` and triggers an ASG instance refresh so the
portal restarts and picks it up; the previous token is superseded at the next
rotation. Pure ``boto3`` + stdlib (no vendored dependencies): the test step
speaks RESP ``AUTH`` over TLS directly.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import ssl
import string

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Matches the bootstrap token charset (random_password special = false): the
# ElastiCache AUTH-token charset is printable ASCII; alphanumeric stays safely
# inside it and avoids shell/JSON-escaping hazards.
_TOKEN_ALPHABET = string.ascii_letters + string.digits
_TOKEN_LENGTH = 64


def _new_token() -> str:
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))


def _pending_token(sm, arn: str, version: str) -> str:
    payload = sm.get_secret_value(SecretId=arn, VersionId=version, VersionStage="AWSPENDING")
    return json.loads(payload["SecretString"])["password"]


def handler(event, context):  # noqa: ARG001 - Lambda signature
    """Secrets Manager rotation entry point."""
    arn = event["SecretId"]
    version = event["ClientRequestToken"]
    step = event["Step"]

    sm = boto3.client("secretsmanager")
    metadata = sm.describe_secret(SecretId=arn)
    if not metadata.get("RotationEnabled", False):
        raise ValueError(f"Secret {arn} is not enabled for rotation")

    stages = metadata["VersionIdsToStages"]
    if version not in stages:
        raise ValueError(f"Version {version} has no stage for secret {arn}")
    if "AWSCURRENT" in stages[version]:
        logger.info("Version %s already AWSCURRENT; nothing to do", version)
        return
    if "AWSPENDING" not in stages[version]:
        raise ValueError(f"Version {version} not AWSPENDING for secret {arn}")

    dispatch = {
        "createSecret": _create_secret,
        "setSecret": _set_secret,
        "testSecret": _test_secret,
        "finishSecret": _finish_secret,
    }
    if step not in dispatch:
        raise ValueError(f"Unknown rotation step: {step}")
    dispatch[step](sm, arn, version)


def _create_secret(sm, arn: str, version: str) -> None:
    """Stage a freshly generated AUTH token as AWSPENDING (idempotent)."""
    sm.get_secret_value(SecretId=arn, VersionStage="AWSCURRENT")
    try:
        sm.get_secret_value(SecretId=arn, VersionId=version, VersionStage="AWSPENDING")
        logger.info("AWSPENDING already populated for %s", version)
    except sm.exceptions.ResourceNotFoundException:
        sm.put_secret_value(
            SecretId=arn,
            ClientRequestToken=version,
            SecretString=json.dumps({"password": _new_token()}),
            VersionStages=["AWSPENDING"],
        )
        logger.info("Created AWSPENDING token for %s", version)


def _set_secret(sm, arn: str, version: str) -> None:
    """Apply the pending token to ElastiCache with the ROTATE strategy."""
    token = _pending_token(sm, arn, version)
    group_id = os.environ["REPLICATION_GROUP_ID"]
    elasticache = boto3.client("elasticache")
    # ROTATE: the previous token stays valid alongside the new one, so the
    # running portal is not locked out before its restart.
    elasticache.modify_replication_group(
        ReplicationGroupId=group_id,
        AuthToken=token,
        AuthTokenUpdateStrategy="ROTATE",
        ApplyImmediately=True,
    )
    # Bound the waiter inside the Lambda timeout (set to 900s in rotation.tf):
    # 40 attempts * 15s = 600s, leaving headroom over a slow ElastiCache modify
    # rather than relying on the SDK default that can outlive the function.
    elasticache.get_waiter("replication_group_available").wait(
        ReplicationGroupId=group_id,
        WaiterConfig={"Delay": 15, "MaxAttempts": 40},
    )
    logger.info("Applied ROTATE auth-token update to %s", group_id)


def _test_secret(sm, arn: str, version: str) -> None:
    """Verify the pending token authenticates against Redis over TLS."""
    token = _pending_token(sm, arn, version)
    host = os.environ["REDIS_HOST"]
    port = int(os.environ.get("REDIS_PORT", "6379"))
    _redis_auth_check(host, port, token)
    logger.info("Pending token authenticated against %s:%d", host, port)


def _finish_secret(sm, arn: str, version: str) -> None:
    """Promote the pending token to AWSCURRENT and restart consumers.

    The consumer refresh runs on every invocation, including a retry where the
    promotion already happened on a prior attempt: ElastiCache ROTATE keeps only
    the two newest tokens, so a consumer that never rehydrates loses auth at the
    next rotation. Treating the refresh as a required, idempotent finish step
    (rather than fire-and-forget after the stage move) keeps a failed refresh
    retryable instead of silently completing rotation.
    """
    metadata = sm.describe_secret(SecretId=arn)
    current = next(
        (vid for vid, stages in metadata["VersionIdsToStages"].items() if "AWSCURRENT" in stages),
        None,
    )
    if current == version:
        logger.info("Version %s already AWSCURRENT", version)
    else:
        sm.update_secret_version_stage(
            SecretId=arn,
            VersionStage="AWSCURRENT",
            MoveToVersionId=version,
            RemoveFromVersionId=current,
        )
        logger.info("Promoted %s to AWSCURRENT", version)
    _trigger_instance_refresh()


def _redis_auth_check(host: str, port: int, token: str) -> None:
    """Open a TLS connection and verify a RESP AUTH succeeds."""
    context = ssl.create_default_context()
    # Disallow TLS 1.0/1.1 (ElastiCache in-transit encryption supports 1.2+).
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((host, port), timeout=5) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            tls.sendall(b"AUTH " + token.encode() + b"\r\n")
            response = tls.recv(128)
    if not response.startswith(b"+OK"):
        raise ValueError(f"Redis AUTH test failed: {response!r}")


def _trigger_instance_refresh() -> None:
    """Roll the portal ASG so containers hydrate the new token (idempotent).

    Rotation is only scheduled where a refreshable ASG exists (enable_auth_rotation
    in rotation.tf), so ASG_NAME is normally set; the empty guard is defensive. An
    already-running refresh is treated as success — the rehydration this rotation
    needs is already in flight.
    """
    asg_name = os.environ.get("ASG_NAME", "").strip()
    if not asg_name:
        logger.warning("ASG_NAME unset; consumers must be restarted manually to pick up the new token")
        return
    autoscaling = boto3.client("autoscaling")
    try:
        autoscaling.start_instance_refresh(
            AutoScalingGroupName=asg_name,
            Preferences={"MinHealthyPercentage": 50},
        )
        logger.info("Triggered instance refresh on %s", asg_name)
    except autoscaling.exceptions.InstanceRefreshInProgressException:
        logger.info("Instance refresh already in progress on %s; rehydration in flight", asg_name)
