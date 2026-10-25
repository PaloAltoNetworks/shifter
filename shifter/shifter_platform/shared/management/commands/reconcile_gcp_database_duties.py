"""Deployment-owner native SQL duty bootstrap; credentials stay in the driver."""

import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from psycopg import Error as PostgresError

from shared.gcp_native_identity import validate_native_identity
from shared.gcp_native_identity.database_duties import reconcile_application_duties, reconcile_policy_owner


class Command(BaseCommand):
    """Reconcile native database duties under the separate deployment owner."""

    help = "Reconcile GCP PostgreSQL duties after migrations under the separate deployment owner."

    def handle(self, *args, **options) -> None:
        if connection.vendor != "postgresql" or os.environ.get("CLOUD_PROVIDER") != "gcp":
            raise CommandError("GCP database duty reconciliation requires PostgreSQL and the GCP deployment owner")
        if os.environ.get("DB_AUTH_MODE", "password") != "password":
            raise CommandError("Runtime native database logins cannot administer database duties")
        try:
            users = json.loads(os.environ.get("GCP_DATABASE_IAM_USERS_JSON", "{}"))
            if users:
                native = validate_native_identity(
                    {
                        "enabled": True,
                        "openfga_enabled": "openfga-runtime" in users,
                        "instance_connection_name": os.environ.get("CLOUD_SQL_INSTANCE_CONNECTION_NAME", ""),
                        "database_users": users,
                    },
                    project_id=os.environ.get("GCP_PROJECT_ID", ""),
                    service_accounts={key: value + ".gserviceaccount.com" for key, value in users.items()},
                )
                users = native.database_users
            with transaction.atomic(), connection.cursor() as cursor:
                reconcile_application_duties(cursor, users)
            reconcile_policy_owner(connection.get_connection_params(), users)
        except (ValueError, TypeError, AttributeError, DatabaseError, PostgresError):
            raise CommandError(
                "GCP SQL duty reconciliation failed; verify the deployment owner's SQL authority and native role grants"
            ) from None
        self.stdout.write("GCP database duties reconciled")
