"""
Resource tagging utilities for provisioner Lambda functions.

All provisioned resources MUST be tagged for:
- Audit trail
- Cost allocation
- Cleanup of orphaned resources
- IAM conditions
"""

from datetime import datetime, timezone


def get_resource_tags(
    range_id: str,
    user_id: str,
    environment: str = "prod",
) -> list[dict]:
    """
    Generate standard tags for provisioned AWS resources.

    Args:
        range_id: UUID of the range
        user_id: ID of the user who owns the range
        environment: Environment name (prod, dev, etc.)

    Returns:
        List of tag dicts in AWS format [{"Key": "...", "Value": "..."}]
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    return [
        {"Key": "shifter:range_id", "Value": str(range_id)},
        {"Key": "shifter:user_id", "Value": str(user_id)},
        {"Key": "shifter:created_at", "Value": timestamp},
        {"Key": "Project", "Value": "shifter"},
        {"Key": "Environment", "Value": environment},
        {"Key": "ManagedBy", "Value": "provisioner-lambda"},
    ]


def get_resource_tags_dict(
    range_id: str,
    user_id: str,
    environment: str = "prod",
) -> dict[str, str]:
    """
    Generate standard tags as a simple dict (for some AWS APIs).

    Args:
        range_id: UUID of the range
        user_id: ID of the user who owns the range
        environment: Environment name (prod, dev, etc.)

    Returns:
        Dict of tag key-value pairs
    """
    tags = get_resource_tags(range_id, user_id, environment)
    return {tag["Key"]: tag["Value"] for tag in tags}
