"""Unit tests for the Redis AUTH rotation Lambda (#159)."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

import redis_rotation
from redis_rotation import handler


@pytest.fixture(autouse=True)
def clear_env():
    with patch.dict(os.environ, {}, clear=True):
        yield


def _metadata(version, stage):
    return {"RotationEnabled": True, "VersionIdsToStages": {version: [stage]}}


def test_token_charset_and_length():
    token = redis_rotation._new_token()
    assert len(token) == redis_rotation._TOKEN_LENGTH
    assert token.isalnum()


def test_rotation_not_enabled_raises():
    sm = MagicMock()
    sm.describe_secret.return_value = {"RotationEnabled": False, "VersionIdsToStages": {}}
    with patch("boto3.client", return_value=sm), pytest.raises(ValueError, match="not enabled"):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "createSecret"}, None)


def test_already_current_is_noop():
    sm = MagicMock()
    sm.describe_secret.return_value = _metadata("v1", "AWSCURRENT")
    with patch("boto3.client", return_value=sm):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "finishSecret"}, None)
    sm.update_secret_version_stage.assert_not_called()


def test_unknown_step_raises():
    sm = MagicMock()
    sm.describe_secret.return_value = _metadata("v1", "AWSPENDING")
    with patch("boto3.client", return_value=sm), pytest.raises(ValueError, match="Unknown rotation step"):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "bogus"}, None)


def test_create_secret_stages_pending_when_absent():
    sm = MagicMock()
    sm.describe_secret.return_value = _metadata("v1", "AWSPENDING")
    sm.exceptions.ResourceNotFoundException = type("RNF", (Exception,), {})
    sm.get_secret_value.side_effect = [{"SecretString": "{}"}, sm.exceptions.ResourceNotFoundException()]
    with patch("boto3.client", return_value=sm):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "createSecret"}, None)
    put = sm.put_secret_value.call_args.kwargs
    assert put["VersionStages"] == ["AWSPENDING"]
    assert len(json.loads(put["SecretString"])["password"]) == redis_rotation._TOKEN_LENGTH


def test_set_secret_uses_rotate_strategy():
    sm = MagicMock()
    sm.describe_secret.return_value = _metadata("v1", "AWSPENDING")
    sm.get_secret_value.return_value = {"SecretString": json.dumps({"password": "newtoken"})}
    elasticache = MagicMock()

    def fake_client(service, **kwargs):
        return {"secretsmanager": sm, "elasticache": elasticache}[service]

    with patch("boto3.client", side_effect=fake_client), patch.dict(os.environ, {"REPLICATION_GROUP_ID": "p-redis"}):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "setSecret"}, None)
    modify = elasticache.modify_replication_group.call_args.kwargs
    assert modify["AuthTokenUpdateStrategy"] == "ROTATE"
    assert modify["AuthToken"] == "newtoken"
    assert modify["ReplicationGroupId"] == "p-redis"
    # The waiter must block until ElastiCache finishes the ROTATE, or finishSecret
    # could promote AWSCURRENT before the new token is live.
    elasticache.get_waiter.assert_called_with("replication_group_available")
    elasticache.get_waiter.return_value.wait.assert_called_once()


def test_test_secret_authenticates_pending_token_over_network():
    # Drive the full testSecret step through the real _redis_auth_check, mocking
    # only the socket/ssl boundary (ADR-019: do not patch first-party internals),
    # and assert the pending token is sent to the configured host/port.
    sm = MagicMock()
    sm.describe_secret.return_value = _metadata("v1", "AWSPENDING")
    sm.get_secret_value.return_value = {"SecretString": json.dumps({"password": "pendtoken"})}
    tls = MagicMock()
    tls.recv.return_value = b"+OK\r\n"
    ctx = MagicMock()
    ctx.wrap_socket.return_value.__enter__.return_value = tls
    env = {"REDIS_HOST": "redis.internal", "REDIS_PORT": "6380"}
    with (
        patch("boto3.client", return_value=sm),
        patch.dict(os.environ, env),
        patch("ssl.create_default_context", return_value=ctx),
        patch("socket.create_connection") as connect,
    ):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "testSecret"}, None)
    connect.assert_called_once_with(("redis.internal", 6380), timeout=5)
    tls.sendall.assert_called_once_with(b"AUTH pendtoken\r\n")


def test_redis_auth_check_accepts_ok():
    tls = MagicMock()
    tls.recv.return_value = b"+OK\r\n"
    ctx = MagicMock()
    ctx.wrap_socket.return_value.__enter__.return_value = tls
    with patch("ssl.create_default_context", return_value=ctx), patch("socket.create_connection"):
        redis_rotation._redis_auth_check("host", 6379, "tok")  # must not raise


def test_finish_secret_promotes_and_refreshes_asg():
    sm = MagicMock()
    # describe_secret: first call (guard) v1 is AWSPENDING; second (finish) shows current=v0.
    sm.describe_secret.side_effect = [
        _metadata("v1", "AWSPENDING"),
        {"VersionIdsToStages": {"v0": ["AWSCURRENT"], "v1": ["AWSPENDING"]}},
    ]
    autoscaling = MagicMock()

    def fake_client(service, **kwargs):
        return {"secretsmanager": sm, "autoscaling": autoscaling}[service]

    with patch("boto3.client", side_effect=fake_client), patch.dict(os.environ, {"ASG_NAME": "portal-asg"}):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "finishSecret"}, None)
    stage = sm.update_secret_version_stage.call_args.kwargs
    assert stage["MoveToVersionId"] == "v1"
    assert stage["RemoveFromVersionId"] == "v0"
    autoscaling.start_instance_refresh.assert_called_once()


def test_finish_secret_skips_refresh_without_asg_name():
    sm = MagicMock()
    sm.describe_secret.side_effect = [
        _metadata("v1", "AWSPENDING"),
        {"VersionIdsToStages": {"v0": ["AWSCURRENT"], "v1": ["AWSPENDING"]}},
    ]
    autoscaling = MagicMock()

    def fake_client(service, **kwargs):
        return {"secretsmanager": sm, "autoscaling": autoscaling}[service]

    with patch("boto3.client", side_effect=fake_client):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "finishSecret"}, None)
    autoscaling.start_instance_refresh.assert_not_called()


def test_finish_secret_refreshes_even_when_already_current():
    # A retry after a failed refresh: promotion already happened, but the refresh
    # must still run so consumers rehydrate before the next ROTATE drops the old token.
    sm = MagicMock()
    sm.describe_secret.side_effect = [
        _metadata("v1", "AWSPENDING"),
        {"VersionIdsToStages": {"v1": ["AWSCURRENT"]}},
    ]
    autoscaling = MagicMock()

    def fake_client(service, **kwargs):
        return {"secretsmanager": sm, "autoscaling": autoscaling}[service]

    with patch("boto3.client", side_effect=fake_client), patch.dict(os.environ, {"ASG_NAME": "portal-asg"}):
        handler({"SecretId": "arn", "ClientRequestToken": "v1", "Step": "finishSecret"}, None)
    sm.update_secret_version_stage.assert_not_called()
    autoscaling.start_instance_refresh.assert_called_once()


def test_trigger_refresh_tolerates_in_progress():
    autoscaling = MagicMock()
    autoscaling.exceptions.InstanceRefreshInProgressException = type("IRP", (Exception,), {})
    autoscaling.start_instance_refresh.side_effect = autoscaling.exceptions.InstanceRefreshInProgressException()
    with patch("boto3.client", return_value=autoscaling), patch.dict(os.environ, {"ASG_NAME": "portal-asg"}):
        redis_rotation._trigger_instance_refresh()  # must not raise


def test_redis_auth_check_rejects_non_ok():
    tls = MagicMock()
    tls.recv.return_value = b"-WRONGPASS invalid"
    ctx = MagicMock()
    ctx.wrap_socket.return_value.__enter__.return_value = tls
    with (
        patch("ssl.create_default_context", return_value=ctx),
        patch("socket.create_connection"),
        pytest.raises(ValueError, match="AUTH test failed"),
    ):
        redis_rotation._redis_auth_check("host", 6379, "tok")
