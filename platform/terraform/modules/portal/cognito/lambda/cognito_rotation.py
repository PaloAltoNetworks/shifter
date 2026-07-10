"""Operator-triggered Cognito client-secret rotation Lambda (#159).

Cognito has no API to rotate an app client's secret in place, so rotation is a
blue/green client replacement: this function creates a *new* user-pool client
that copies the current client's configuration, writes the new client_id /
client_secret into the OIDC secret bundle, and refreshes the portal ASG so
containers rehydrate ``OIDC_RP_CLIENT_ID`` / ``OIDC_RP_CLIENT_SECRET``.

It is invoked on demand by an operator (``aws lambda invoke``), not on a
schedule: a scheduled EventBridge reminder (rotation.tf) emails the admin when
rotation is due. The previous client is left in place so in-flight logins keep
working; the operator retires it after the new client has drained in (see the
runbook). Pure boto3 + stdlib.
"""

from __future__ import annotations

import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Fields returned by DescribeUserPoolClient that CreateUserPoolClient also
# accepts. The client secret is generated fresh (GenerateSecret=True), and
# identity fields (ClientId/ClientSecret/Name/UserPoolId/timestamps) are set
# explicitly, so they are intentionally excluded from the copy.
_COPIED_CLIENT_FIELDS = (
    "RefreshTokenValidity",
    "AccessTokenValidity",
    "IdTokenValidity",
    "TokenValidityUnits",
    "ReadAttributes",
    "WriteAttributes",
    "ExplicitAuthFlows",
    "SupportedIdentityProviders",
    "CallbackURLs",
    "LogoutURLs",
    "DefaultRedirectURI",
    "AllowedOAuthFlows",
    "AllowedOAuthScopes",
    "AllowedOAuthFlowsUserPoolClient",
    "PreventUserExistenceErrors",
    "EnableTokenRevocation",
    "EnablePropagateAdditionalUserContextData",
    "AuthSessionValidity",
)


def handler(event, context):  # noqa: ARG001 - Lambda signature
    """Rotate the Cognito app client (blue/green) and return the new client id."""
    secret_id = os.environ["COGNITO_SECRET_ID"]
    sm = boto3.client("secretsmanager")
    bundle = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])

    user_pool_id = bundle["user_pool_id"]
    old_client_id = bundle["client_id"]

    cognito = boto3.client("cognito-idp")
    new_client = _create_replacement_client(cognito, user_pool_id, old_client_id)

    # Preserve the non-client fields (pool, domain, issuer); swap the credential.
    bundle["client_id"] = new_client["ClientId"]
    bundle["client_secret"] = new_client["ClientSecret"]
    sm.put_secret_value(SecretId=secret_id, SecretString=json.dumps(bundle))
    logger.info("Wrote new Cognito client %s to the secret bundle", new_client["ClientId"])

    _trigger_instance_refresh()

    # old_client_id is returned (not deleted) so the operator can retire it after
    # the new client has drained in. The secret value is never returned/logged.
    return {"new_client_id": new_client["ClientId"], "previous_client_id": old_client_id}


def _create_replacement_client(cognito, user_pool_id: str, old_client_id: str) -> dict:
    described = cognito.describe_user_pool_client(UserPoolId=user_pool_id, ClientId=old_client_id)[
        "UserPoolClient"
    ]
    params = {key: described[key] for key in _COPIED_CLIENT_FIELDS if key in described}
    params["UserPoolId"] = user_pool_id
    params["GenerateSecret"] = True
    base_name = described.get("ClientName", "portal-client").split("-rot-")[0]
    params["ClientName"] = f"{base_name}-rot-{int(time.time())}"
    return cognito.create_user_pool_client(**params)["UserPoolClient"]


def _trigger_instance_refresh() -> None:
    """Roll the portal ASG so containers hydrate the new client (idempotent)."""
    asg_name = os.environ.get("ASG_NAME", "").strip()
    if not asg_name:
        logger.warning("ASG_NAME unset; restart the portal manually to pick up the new client")
        return
    autoscaling = boto3.client("autoscaling")
    try:
        autoscaling.start_instance_refresh(
            AutoScalingGroupName=asg_name,
            Preferences={"MinHealthyPercentage": 50},
        )
        logger.info("Triggered instance refresh on %s", asg_name)
    except autoscaling.exceptions.InstanceRefreshInProgressException:
        logger.info("Instance refresh already in progress on %s", asg_name)
