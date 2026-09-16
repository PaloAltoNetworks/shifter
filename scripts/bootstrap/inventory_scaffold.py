"""Generate private execution checks from the validated common deployment record."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from installation.deployment_inventory_types import DeploymentRecord

from inventory_bootstrap import invalid, write_private

AUTH_ACTION = "google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093"
CHECKOUT_ACTION = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"


def scaffold_checks(record: DeploymentRecord, output: Path) -> None:
    """Emit non-destructive checks; application deployment remains a separate consumer.

    Every job uses an exact environment/ref/workflow tuple. The caller reviews
    and commits these files to the private execution repository before bootstrap.
    Existing files are never replaced. Reusable-workflow callers must supply
    their own reviewed wrapper because a probe cannot claim that workflow's ID.
    """
    if record.gcp is None:
        raise invalid("execution check scaffolding currently supports the GCP consumer")
    if output.exists():
        raise invalid("scaffold output must be a new directory")
    workflows: dict[str, dict[str, Any]] = {}
    for contexts in record.execution.purposes.values():
        for context in contexts:
            if context.reusable_workflow:
                raise invalid("scaffold requires direct workflow contexts; preserve reusable callers separately")
            workflow = workflows.setdefault(
                context.workflow,
                {
                    "name": "Deployment identity checks",
                    "on": {"workflow_dispatch": {}},
                    "permissions": {"contents": "read", "id-token": "write"},
                    "jobs": {},
                },
            )
            job_id = "check_" + str(len(workflow["jobs"]))
            auth = {
                "workload_identity_provider": "${{ vars.GCP_WIF_PROVIDER }}",
                "service_account": "${{ vars.GCP_SERVICE_ACCOUNT }}",
                "token_format": "access_token",  # nosec B105 - action format enum, not a credential
                "create_credentials_file": False,
                "access_token_lifetime": "300s",  # nosec B105 - token duration, not a credential
            }
            workflow["jobs"][job_id] = {
                "if": "${{ github.ref == '" + context.ref + "' }}",
                "runs-on": record.installation.deployment.name,
                "environment": context.environment,
                "timeout-minutes": 10,
                "steps": [
                    {
                        "name": "Verify pinned product access",
                        "uses": CHECKOUT_ACTION,
                        "with": {
                            "repository": record.product.repository,
                            "ref": record.product.revision,
                            "persist-credentials": False,
                        },
                    },
                    {"name": "Verify allowed purpose", "uses": AUTH_ACTION, "with": auth},
                    {
                        "name": "Reject alternate audience",
                        "id": "audience",
                        "uses": AUTH_ACTION,
                        "continue-on-error": True,
                        "with": {**auth, "audience": "shifter-denied-audience"},
                    },
                    {
                        "name": "Reject other purpose",
                        "id": "purpose",
                        "uses": AUTH_ACTION,
                        "continue-on-error": True,
                        "with": {**auth, "service_account": "${{ vars.GCP_DENIED_SERVICE_ACCOUNT }}"},
                    },
                    {
                        "name": "Assert denied exchanges",
                        "shell": "bash",
                        "env": {
                            "AUDIENCE_OUTCOME": "${{ steps.audience.outcome }}",
                            "PURPOSE_OUTCOME": "${{ steps.purpose.outcome }}",
                        },
                        "run": 'test "$AUDIENCE_OUTCOME" = failure\ntest "$PURPOSE_OUTCOME" = failure\n',
                    },
                ],
            }
    output.mkdir(mode=0o700, parents=True)
    destination = output / ".github/workflows"
    destination.mkdir(mode=0o700, parents=True)
    write_private(
        output / ".github/actionlint.yaml",
        yaml.safe_dump(
            {
                "self-hosted-runner": {"labels": [record.installation.deployment.name]},
            }
        ),
    )
    for name, workflow in workflows.items():
        write_private(destination / name, yaml.safe_dump(workflow, sort_keys=False))
