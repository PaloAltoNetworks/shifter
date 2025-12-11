"""
Create Kali Lambda - Sets up Kali attack container/instance for the range.

Input: { "range_id": "uuid" }
Output: { "range_id": "uuid", "kali_info": "..." }

NOTE: This is a stub implementation. Full Kali provisioning will be added
when the Kali container/ECS architecture is finalized.
"""

import logging
import os
import sys

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import get_db_connection, get_range, update_range

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    """
    Set up Kali attack environment for the range.

    TODO: Implement full Kali provisioning:
    - ECS task or EC2 instance
    - Configure SSH access to victim
    - Set up MCP server connection

    For now, this is a pass-through stub.
    """
    range_id = event["range_id"]
    logger.info(f"Creating Kali environment for range {range_id} (stub)")

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

        # Stub: Just log and pass through
        # In the future, this will:
        # 1. Create ECS task or EC2 for Kali
        # 2. Configure networking to victim
        # 3. Store connection info in database

        logger.info(f"Kali setup complete for range {range_id} (stub - no actual resources created)")

        return {
            "range_id": range_id,
            "kali_info": "stub",
        }

    finally:
        conn.close()
