"""Container entrypoint for Shifter Engine.

This module is the main entry point when running the Shifter Engine container.
It handles:
- Database connection via RDS IAM authentication
- Range status updates in the Django database
- Terraform-based provisioning and destruction
"""

import logging
import os

from ngfw_runtime_ops import run_ngfw_operation
from ngfw_terraform import run_ngfw_terraform
from terraform_ops import run_range_terraform

logger = logging.getLogger(__name__)

_ENVIRONMENT_LOG = "Environment: %s"


if __name__ == "__main__":
    from logging_config import configure_logging

    configure_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Shifter Engine for provisioning cyber ranges and NGFW operations")
    subparsers = parser.add_subparsers(dest="resource", required=True, help="Resource type")

    # --operation-id is optional and carries the ADR-043 canonical operation
    # generation (#1834). The engine appends it as a trailing
    # `--operation-id <uuid>` pair only on the remote/drainer dispatch path
    # (engine.launch_intents.command_from_payload); local-dev runs never carry
    # it, so it must never be required here.
    _operation_id_help = "ADR-043 canonical operation generation UUID (absent on local-dev runs)"

    range_parser = subparsers.add_parser("range", help="Range lifecycle operations")
    range_parser.add_argument(
        "operation",
        choices=["provision", "destroy", "pause", "resume", "splice-check", "splice-repair"],
        help=(
            "Operation to perform: provision, destroy, pause, resume, or safely "
            "check/repair the Polaris splice credential"
        ),
    )
    range_parser.add_argument(
        "--request-id",
        type=str,
        required=True,
        dest="request_id",
        help="UUID of the Request for this Range",
    )
    range_parser.add_argument(
        "--operation-id",
        type=str,
        default=None,
        dest="operation_id",
        help=_operation_id_help,
    )

    raes_range_parser = subparsers.add_parser(
        "raes-range", help="RAES-native range lifecycle operations (serialized RAES plan)"
    )
    raes_range_parser.add_argument(
        "operation",
        choices=["provision", "destroy", "activate"],
        help=(
            "Operation to perform: provision (create), destroy (teardown), or "
            "activate (hand a claimed warm generation to its claimant, #28)"
        ),
    )
    raes_range_parser.add_argument(
        "--request-id",
        type=str,
        required=True,
        dest="request_id",
        help="UUID of the Request for this RAES range",
    )
    raes_range_parser.add_argument(
        "--operation-id",
        type=str,
        default=None,
        dest="operation_id",
        help=_operation_id_help,
    )

    ngfw_parser = subparsers.add_parser("ngfw", help="NGFW runtime operations")
    ngfw_parser.add_argument(
        "operation",
        choices=["provision", "deprovision", "start", "stop"],
        help="NGFW operation to perform",
    )
    ngfw_parser.add_argument(
        "--request-id",
        type=str,
        required=True,
        dest="request_id",
        help="UUID of the Request for this NGFW",
    )
    ngfw_parser.add_argument(
        "--ec2-instance-id",
        type=str,
        help="EC2 instance ID (for start/stop)",
    )
    ngfw_parser.add_argument(
        "--operation-id",
        type=str,
        default=None,
        dest="operation_id",
        help=_operation_id_help,
    )

    args = parser.parse_args()

    if args.resource == "raes-range":
        from raes_range_ops import (
            run_raes_range_activate,
            run_raes_range_destroy,
            run_raes_range_provision,
        )

        logger.info("Starting RAES range %s for request_id=%s", args.operation, args.request_id)
        logger.info(_ENVIRONMENT_LOG, os.environ.get("ENVIRONMENT", "unknown"))
        if args.operation == "provision":
            run_raes_range_provision(args.request_id, operation_id=args.operation_id)
        elif args.operation == "activate":
            run_raes_range_activate(args.request_id, operation_id=args.operation_id)
        else:
            run_raes_range_destroy(args.request_id, operation_id=args.operation_id)
        logger.info("Completed RAES range %s for request_id=%s", args.operation, args.request_id)

    elif args.resource == "ngfw":
        logger.info("Starting NGFW %s for request_id=%s", args.operation, args.request_id)
        logger.info(_ENVIRONMENT_LOG, os.environ.get("ENVIRONMENT", "unknown"))

        if args.operation in ("provision", "deprovision"):
            tf_op = "up" if args.operation == "provision" else "destroy"
            run_ngfw_terraform(tf_op, args.request_id, operation_id=args.operation_id)
        else:
            kwargs: dict[str, str] = {}
            if args.ec2_instance_id:
                kwargs["ec2_instance_id"] = args.ec2_instance_id
            run_ngfw_operation(args.operation, args.request_id, operation_id=args.operation_id, **kwargs)

        logger.info("Completed NGFW %s for request_id=%s", args.operation, args.request_id)

    elif args.resource == "range":
        request_id = args.request_id
        tf_op = "up" if args.operation == "provision" else "destroy"

        logger.info("Starting range %s for request_id=%s", args.operation, request_id)
        logger.info(_ENVIRONMENT_LOG, os.environ.get("ENVIRONMENT", "unknown"))

        if args.operation in ("provision", "destroy"):
            run_range_terraform(tf_op, request_id, operation_id=args.operation_id)
        elif args.operation == "pause":
            from range_ops import run_range_pause

            run_range_pause(request_id, operation_id=args.operation_id)
        elif args.operation == "resume":
            from range_ops import run_range_resume

            run_range_resume(request_id, operation_id=args.operation_id)
        else:
            from polaris_splice_credentials import run_request_polaris_splice_credential_operation

            result = run_request_polaris_splice_credential_operation(
                request_id,
                repair=args.operation == "splice-repair",
            )
            logger.info("Polaris splice credential status: %s", result.status)

        logger.info("Completed range %s for request_id=%s", args.operation, request_id)
