"""Unit tests for the operator-triggered Cognito rotation Lambda (#159)."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

import cognito_rotation
from cognito_rotation import handler

_BUNDLE = {
    "client_id": "old-client",
    "client_secret": "old-secret",
    "user_pool_id": "pool-1",
    "domain": "https://example.auth.us-east-2.amazoncognito.com",
    "issuer_url": "https://cognito-idp.us-east-2.amazonaws.com/pool-1",
}

_DESCRIBED = {
    "UserPoolClient": {
        "ClientId": "old-client",
        "ClientSecret": "old-secret",
        "ClientName": "dev-portal-client",
        "UserPoolId": "pool-1",
        "CallbackURLs": ["https://portal/oidc/callback/"],
        "LogoutURLs": ["https://portal/"],
        "AllowedOAuthFlows": ["code"],
        "AllowedOAuthScopes": ["openid", "email", "profile"],
        "AllowedOAuthFlowsUserPoolClient": True,
        "SupportedIdentityProviders": ["COGNITO"],
        "PreventUserExistenceErrors": "ENABLED",
        "CreationDate": "ignored",
    }
}


@pytest.fixture(autouse=True)
def clear_env():
    with patch.dict(os.environ, {"COGNITO_SECRET_ID": "cognito-arn"}, clear=True):
        yield


def _clients():
    sm = MagicMock()
    sm.get_secret_value.return_value = {"SecretString": json.dumps(_BUNDLE)}
    cognito = MagicMock()
    cognito.describe_user_pool_client.return_value = _DESCRIBED
    cognito.create_user_pool_client.return_value = {
        "UserPoolClient": {"ClientId": "new-client", "ClientSecret": "new-secret"}
    }
    autoscaling = MagicMock()
    return sm, cognito, autoscaling


def test_handler_creates_new_client_and_updates_bundle():
    sm, cognito, autoscaling = _clients()
    clients = {"secretsmanager": sm, "cognito-idp": cognito, "autoscaling": autoscaling}
    with patch("boto3.client", side_effect=lambda svc, **kw: clients[svc]), patch.dict(os.environ, {"ASG_NAME": "asg"}):
        result = handler({}, None)

    create = cognito.create_user_pool_client.call_args.kwargs
    assert create["GenerateSecret"] is True
    assert create["UserPoolId"] == "pool-1"
    assert create["CallbackURLs"] == ["https://portal/oidc/callback/"]
    assert create["PreventUserExistenceErrors"] == "ENABLED"
    # Identity/timestamp fields are not copied into the create call.
    assert "ClientId" not in create and "ClientSecret" not in create and "CreationDate" not in create
    assert create["ClientName"].startswith("dev-portal-client-rot-")

    written = json.loads(sm.put_secret_value.call_args.kwargs["SecretString"])
    assert written["client_id"] == "new-client"
    assert written["client_secret"] == "new-secret"
    # Non-client fields are preserved.
    assert written["user_pool_id"] == "pool-1"
    assert written["issuer_url"] == _BUNDLE["issuer_url"]

    assert result == {"new_client_id": "new-client", "previous_client_id": "old-client"}
    autoscaling.start_instance_refresh.assert_called_once()


def test_handler_skips_refresh_without_asg():
    sm, cognito, autoscaling = _clients()
    clients = {"secretsmanager": sm, "cognito-idp": cognito, "autoscaling": autoscaling}
    with patch("boto3.client", side_effect=lambda svc, **kw: clients[svc]):
        handler({}, None)
    autoscaling.start_instance_refresh.assert_not_called()


def test_trigger_refresh_tolerates_in_progress():
    autoscaling = MagicMock()
    autoscaling.exceptions.InstanceRefreshInProgressException = type("IRP", (Exception,), {})
    autoscaling.start_instance_refresh.side_effect = autoscaling.exceptions.InstanceRefreshInProgressException()
    with patch("boto3.client", return_value=autoscaling), patch.dict(os.environ, {"ASG_NAME": "asg"}):
        cognito_rotation._trigger_instance_refresh()  # must not raise
