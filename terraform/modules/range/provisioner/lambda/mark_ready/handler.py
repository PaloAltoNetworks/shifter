"""
Mark Ready Lambda - Sets range status to 'ready' and assigns chat_url.

Input: { "range_id": int }
Output: { "range_id": int, "status": "ready", "chat_url": "https://..." }

Called at the end of successful provisioning to:
1. Set status to 'ready'
2. Set ready_at timestamp
3. Set chat_url for MCP access
"""

import logging
import os
import sys
from datetime import datetime, timezone

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import (
    get_db_connection,
    get_env,
    get_range,
    update_range,
    validate_env_vars,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Required environment variables for this Lambda
REQUIRED_ENV_VARS = [
    "DB_HOST",
    "DB_NAME",
    "CHAT_BASE_URL",
]


def handler(event: dict, context) -> dict:
    """
    Mark a range as ready and set its chat URL.

    1. Validate range exists and is in provisioning state
    2. Set status to 'ready'
    3. Set ready_at timestamp
    4. Set chat_url using base URL from config
    """
    # Validate required environment variables early
    validate_env_vars(REQUIRED_ENV_VARS)

    range_id = event["range_id"]
    logger.info(f"Marking range {range_id} as ready")

    # Get chat base URL from environment
    chat_base_url = get_env("CHAT_BASE_URL")

    # Connect to database
    conn = get_db_connection()
    try:
        # Get range details
        range_data = get_range(conn, range_id)
        if not range_data:
            raise ValueError(f"Range {range_id} not found")

        # Validate range is in provisioning state
        if range_data["status"] != "provisioning":
            raise ValueError(
                f"Range {range_id} is not in provisioning state: {range_data['status']}"
            )

        # Validate all required resources exist
        if not range_data["subnet_id"]:
            raise ValueError(f"Range {range_id} missing subnet_id")
        if not range_data["kali_instance_id"]:
            raise ValueError(f"Range {range_id} missing kali_instance_id")
        if not range_data["kali_ssh_key_secret_arn"]:
            raise ValueError(f"Range {range_id} missing kali_ssh_key_secret_arn")

        # Construct chat URL
        # The chat URL points to OpenWebUI on the chat subdomain
        chat_url = f"{chat_base_url.rstrip('/')}?range={range_id}"

        # Update range to ready state
        now = datetime.now(timezone.utc)
        update_range(
            conn,
            range_id,
            status="ready",
            ready_at=now,
            chat_url=chat_url,
        )
        logger.info(f"Range {range_id} marked as ready with chat_url: {chat_url}")

        return {
            "range_id": range_id,
            "status": "ready",
            "chat_url": chat_url,
        }

    finally:
        conn.close()
