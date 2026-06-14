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


if __name__ == "__main__":
    from logging_config import configure_logging

    configure_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Shifter Engine for provisioning cyber ranges and NGFW operations")
    subparsers = parser.add_subparsers(dest="resource", required=True, help="Resource type")

    range_parser = subparsers.add_parser("range", help="Range lifecycle operations")
    range_parser.add_argument(
        "operation",
        choices=["provision", "destroy", "pause", "resume"],
        help="Operation to perform: provision (create), destroy (teardown), pause, or resume",
    )
    range_parser.add_argument(
        "--request-id",
        type=str,
        required=True,
        dest="request_id",
        help="UUID of the Request for this Range",
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

    args = parser.parse_args()

    if args.resource == "ngfw":
        logger.info("Starting NGFW %s for request_id=%s", args.operation, args.request_id)
        logger.info("Environment: %s", os.environ.get("ENVIRONMENT", "unknown"))

        if args.operation in ("provision", "deprovision"):
            tf_op = "up" if args.operation == "provision" else "destroy"
            run_ngfw_terraform(tf_op, args.request_id)
        else:
            kwargs: dict[str, str] = {}
            if args.ec2_instance_id:
                kwargs["ec2_instance_id"] = args.ec2_instance_id
            run_ngfw_operation(args.operation, args.request_id, **kwargs)

        logger.info("Completed NGFW %s for request_id=%s", args.operation, args.request_id)

    elif args.resource == "range":
        request_id = args.request_id
        tf_op = "up" if args.operation == "provision" else "destroy"

        logger.info("Starting range %s for request_id=%s", args.operation, request_id)
        logger.info("Environment: %s", os.environ.get("ENVIRONMENT", "unknown"))

        if args.operation in ("provision", "destroy"):
            run_range_terraform(tf_op, request_id)
        elif args.operation == "pause":
            from range_ops import run_range_pause

            run_range_pause(request_id)
        elif args.operation == "resume":
            from range_ops import run_range_resume

            run_range_resume(request_id)

        logger.info("Completed range %s for request_id=%s", args.operation, request_id)
