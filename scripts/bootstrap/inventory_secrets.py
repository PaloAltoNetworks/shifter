"""Resolve the shared secret-reference convention at the consumer boundary."""

from __future__ import annotations

import os

from installation.deployment_inventory_types import SecretReference

from inventory_bootstrap import invalid, private_command, private_json


def resolve_secret(reference: SecretReference, *, repository: str, environment: str) -> str:
    """Return a private value; callers must use stdin or a protected file.

    Environment values must already be injected by the authorized execution
    Environment or explicitly supplied by an operator. GitHub cannot read back
    stored Actions secrets, so there is deliberately no fallback API fetch.
    """
    if reference.store == "github-environment":
        if (reference.repository, reference.environment) != (repository, environment):
            raise invalid("execution secret scope does not match the consumer")
        value = os.environ.get(reference.resource, "")
    elif reference.store == "gcp-secret-manager":
        value = private_command(["gcloud", "secrets", "versions", "access", reference.resource])
    else:
        region = reference.resource.split(":")[3]
        value = private_json(
            [
                "aws",
                "secretsmanager",
                "get-secret-value",
                "--region",
                region,
                "--secret-id",
                reference.resource,
                "--query",
                "SecretString",
                "--output",
                "json",
            ]
        )
    if not isinstance(value, str) or not value or len(value.encode()) > 65536 or "\x00" in value:
        raise invalid("required secret is absent or exceeds the consumer limit")
    return value
