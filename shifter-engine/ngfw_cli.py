"""NGFW CLI for UserNGFW lifecycle operations.

This module provides CLI entry points for NGFW operations:
- provision: Create NGFW stack with Pulumi
- deprovision: Destroy NGFW stack with Pulumi
- start: Start stopped NGFW instance
- stop: Stop running NGFW instance
- add-route: Add GWLB endpoint and route for a range
- remove-route: Remove GWLB endpoint and route
"""

import argparse
import sys
from typing import Optional


def create_ngfw_parser() -> argparse.ArgumentParser:
    """Create argument parser for NGFW CLI.

    Returns:
        ArgumentParser configured for NGFW operations.
    """
    parser = argparse.ArgumentParser(
        description="NGFW lifecycle operations for UserNGFW stack"
    )

    subparsers = parser.add_subparsers(dest="operation", required=True)

    # provision command
    provision_parser = subparsers.add_parser(
        "provision",
        help="Provision a new NGFW stack"
    )
    provision_parser.add_argument(
        "--user-ngfw-id",
        type=int,
        required=True,
        help="Database ID of the UserNGFW record"
    )

    # deprovision command
    deprovision_parser = subparsers.add_parser(
        "deprovision",
        help="Deprovision an existing NGFW stack"
    )
    deprovision_parser.add_argument(
        "--user-ngfw-id",
        type=int,
        required=True,
        help="Database ID of the UserNGFW record"
    )

    # start command
    start_parser = subparsers.add_parser(
        "start",
        help="Start a stopped NGFW instance"
    )
    start_parser.add_argument(
        "--user-ngfw-id",
        type=int,
        required=True,
        help="Database ID of the UserNGFW record"
    )

    # stop command
    stop_parser = subparsers.add_parser(
        "stop",
        help="Stop a running NGFW instance"
    )
    stop_parser.add_argument(
        "--user-ngfw-id",
        type=int,
        required=True,
        help="Database ID of the UserNGFW record"
    )

    # add-route command
    add_route_parser = subparsers.add_parser(
        "add-route",
        help="Add GWLB endpoint and route for a range"
    )
    add_route_parser.add_argument(
        "--user-ngfw-id",
        type=int,
        required=True,
        help="Database ID of the UserNGFW record"
    )
    add_route_parser.add_argument(
        "--subnet-id",
        type=str,
        required=True,
        help="Subnet ID where endpoint will be created"
    )

    # remove-route command
    remove_route_parser = subparsers.add_parser(
        "remove-route",
        help="Remove GWLB endpoint and route"
    )
    remove_route_parser.add_argument(
        "--user-ngfw-id",
        type=int,
        required=True,
        help="Database ID of the UserNGFW record"
    )
    remove_route_parser.add_argument(
        "--endpoint-id",
        type=str,
        required=True,
        help="VPC endpoint ID to remove"
    )

    return parser


def dispatch_operation(operation: str, **kwargs) -> None:
    """Dispatch to the appropriate operation handler.

    Args:
        operation: The operation name (provision, start, stop, etc.)
        **kwargs: Operation-specific arguments

    Raises:
        ValueError: If operation is not recognized
    """
    handlers = {
        "provision": handle_provision,
        "deprovision": handle_deprovision,
        "start": handle_start,
        "stop": handle_stop,
        "add-route": handle_add_route,
        "remove-route": handle_remove_route,
    }

    handler = handlers.get(operation)
    if handler is None:
        raise ValueError(f"Unknown operation: {operation}")

    handler(**kwargs)


def handle_provision(user_ngfw_id: int) -> None:
    """Handle NGFW provision operation.

    Args:
        user_ngfw_id: Database ID of the UserNGFW record
    """
    print(f"Provisioning NGFW for user_ngfw_id={user_ngfw_id}")
    # TODO: Implement Pulumi stack creation
    # 1. Load UserNGFW record from database
    # 2. Run Pulumi up with UserNGFWStack
    # 3. Run ngfw_provision plan
    # 4. Run gwlb_setup plan
    # 5. Update database with outputs


def handle_deprovision(user_ngfw_id: int) -> None:
    """Handle NGFW deprovision operation.

    Args:
        user_ngfw_id: Database ID of the UserNGFW record
    """
    print(f"Deprovisioning NGFW for user_ngfw_id={user_ngfw_id}")
    # TODO: Implement Pulumi stack destruction
    # 1. Load UserNGFW record from database
    # 2. Run ngfw_deprovision plan (license deactivation)
    # 3. Run Pulumi destroy
    # 4. Update database


def handle_start(user_ngfw_id: int) -> None:
    """Handle NGFW start operation.

    Args:
        user_ngfw_id: Database ID of the UserNGFW record
    """
    print(f"Starting NGFW for user_ngfw_id={user_ngfw_id}")
    # TODO: Implement EC2 start
    # 1. Load UserNGFW record from database
    # 2. Run ngfw_start plan
    # 3. Update database status


def handle_stop(user_ngfw_id: int) -> None:
    """Handle NGFW stop operation.

    Args:
        user_ngfw_id: Database ID of the UserNGFW record
    """
    print(f"Stopping NGFW for user_ngfw_id={user_ngfw_id}")
    # TODO: Implement EC2 stop
    # 1. Load UserNGFW record from database
    # 2. Run ngfw_stop plan
    # 3. Update database status


def handle_add_route(user_ngfw_id: int, subnet_id: str) -> None:
    """Handle add-route operation.

    Args:
        user_ngfw_id: Database ID of the UserNGFW record
        subnet_id: Subnet ID where endpoint will be created
    """
    print(f"Adding route for user_ngfw_id={user_ngfw_id} in subnet={subnet_id}")
    # TODO: Implement route addition
    # 1. Load UserNGFW record from database
    # 2. Run gwlb_add_route plan
    # 3. Store endpoint_id in database


def handle_remove_route(user_ngfw_id: int, endpoint_id: str) -> None:
    """Handle remove-route operation.

    Args:
        user_ngfw_id: Database ID of the UserNGFW record
        endpoint_id: VPC endpoint ID to remove
    """
    print(f"Removing route for user_ngfw_id={user_ngfw_id} endpoint={endpoint_id}")
    # TODO: Implement route removal
    # 1. Load UserNGFW record from database
    # 2. Run gwlb_remove_route plan
    # 3. Update database


def main() -> None:
    """Main entry point for NGFW CLI."""
    parser = create_ngfw_parser()
    args = parser.parse_args()

    # Extract operation-specific kwargs
    kwargs = {"user_ngfw_id": args.user_ngfw_id}

    if args.operation == "add-route":
        kwargs["subnet_id"] = args.subnet_id
    elif args.operation == "remove-route":
        kwargs["endpoint_id"] = args.endpoint_id

    try:
        dispatch_operation(args.operation, **kwargs)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
