"""AWS (EKS) provisioner Job env-forwarding contract (#1826).

The fail-closed provisioner admission policy pins each literal env entry of a
provisioner Job to the platform-runtime ConfigMap, and it pins ``DB_USER`` to the
dedicated ``PROVISIONER_DB_USER`` value. The launcher entrypoint switches its own
``DB_USER`` to the RDS IAM runtime user for the outbox connection, so the
forwarder must source the Job's ``DB_USER`` from ``PROVISIONER_DB_USER`` (which is
never switched) rather than the launcher's live ``DB_USER`` -- otherwise every
provisioner Job is denied.
"""

from __future__ import annotations

import os
from unittest.mock import patch

# The launcher process env after entrypoint hydration: DB_USER has been switched
# to the RDS IAM runtime user, while PROVISIONER_DB_USER carries the provisioner's
# dedicated RDS IAM role unchanged (the value the admission policy expects).
AWS_ENV = {
    "CLOUD_PROVIDER": "aws",
    "ENVIRONMENT": "development",
    "AWS_REGION": "us-east-2",
    "DB_HOST": "dev-portal-db.example.us-east-2.rds.amazonaws.com",
    "DB_PORT": "5432",
    "DB_NAME": "shifter",
    "DB_USER": "portal_runtime",
    "PROVISIONER_DB_USER": "provisioner_lambda",
    "STATE_BUCKET_URL": "s3://dev-range-pulumi-state-000000000000",
}


class TestAwsProvisionerEnvOverrides:
    def test_returns_none_for_non_aws(self, settings):
        from engine.ecs import _get_aws_provisioner_env_overrides

        settings.CLOUD_PROVIDER = "gcp"
        assert _get_aws_provisioner_env_overrides() is None

    def test_db_user_sourced_from_provisioner_identity(self, settings):
        from engine.ecs import _get_aws_provisioner_env_overrides

        settings.CLOUD_PROVIDER = "aws"
        with patch.dict(os.environ, AWS_ENV, clear=False):
            overrides = _get_aws_provisioner_env_overrides()

        assert overrides is not None
        # The Job connects as the dedicated provisioner RDS IAM role, not the
        # launcher's switched runtime user.
        assert overrides["DB_USER"] == AWS_ENV["PROVISIONER_DB_USER"]
        assert overrides["DB_USER"] != AWS_ENV["DB_USER"]
        # The shared portal database endpoint is forwarded unchanged.
        assert overrides["DB_HOST"] == AWS_ENV["DB_HOST"]
        assert overrides["DB_NAME"] == AWS_ENV["DB_NAME"]
        assert overrides["DB_PORT"] == AWS_ENV["DB_PORT"]
