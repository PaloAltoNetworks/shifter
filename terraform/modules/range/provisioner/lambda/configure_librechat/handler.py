"""
Configure LibreChat Lambda - Sets up LibreChat user/routing for the range.

Input: { "range_id": "uuid" }
Output: { "range_id": "uuid", "chat_url": "https://..." }

NOTE: This is a stub implementation. Full LibreChat configuration will be
added when the multi-tenant LibreChat architecture is finalized.
"""

import logging
import os
import sys
from datetime import datetime, timezone

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import get_db_connection, get_range, update_range

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    """
    Configure LibreChat for the range user.

    TODO: Implement full LibreChat integration:
    - Create user in LibreChat (if not exists)
    - Configure MCP server routing to this range's victim
    - Generate chat URL with pre-configured context

    For now, this updates status to ready with a placeholder URL.
    """
    range_id = event["range_id"]
    logger.info(f"Configuring LibreChat for range {range_id} (stub)")

    # Get configuration from environment
    librechat_base_url = os.environ.get("LIBRECHAT_BASE_URL", "https://chat.example.com")

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

        # Check if already configured (idempotent)
        if range_data["chat_url"]:
            logger.info(f"LibreChat already configured: {range_data['chat_url']}")
            return {
                "range_id": range_id,
                "chat_url": range_data["chat_url"],
            }

        # Stub: Generate placeholder chat URL
        # In the future, this will:
        # 1. Provision LibreChat user
        # 2. Configure MCP routing
        # 3. Return real chat URL

        chat_url = f"{librechat_base_url}/c/range-{range_id[:8]}"
        logger.info(f"Generated chat URL: {chat_url}")

        # Update database - mark as ready
        update_range(
            conn,
            range_id,
            chat_url=chat_url,
            status="ready",
            ready_at=datetime.now(timezone.utc),
        )
        logger.info(f"Range {range_id} marked as ready")

        return {
            "range_id": range_id,
            "chat_url": chat_url,
        }

    finally:
        conn.close()
