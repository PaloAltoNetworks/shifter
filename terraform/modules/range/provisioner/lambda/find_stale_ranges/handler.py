"""
Find Stale Ranges Lambda - Identifies ranges stuck in transitional states.

Input: {} (no input required)
Output: { "stale_ranges": [{"range_id": "uuid", "status": "...", "reason": "..."}] }

Called by EventBridge on a schedule to find ranges that need cleanup:
- PROVISIONING for more than 1 hour
- DESTROYING for more than 30 minutes

TODO: See issue #204 - rethink this to scan AWS resources first, then reconcile with DB.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import get_db_connection, validate_env_vars

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Thresholds for stale detection
PROVISIONING_TIMEOUT_MINUTES = 60  # 1 hour
DESTROYING_TIMEOUT_MINUTES = 30  # 30 minutes

# Required environment variables for this Lambda
REQUIRED_ENV_VARS = [
    "DB_HOST",
    "DB_NAME",
]


def handler(event: dict, context) -> dict:
    """
    Find ranges that are stuck in transitional states.

    Returns list of stale ranges with their IDs and reasons.
    """
    # Validate required environment variables early
    validate_env_vars(REQUIRED_ENV_VARS)

    logger.info("Checking for stale ranges")

    stale_ranges = []

    # Connect to database
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)

        with conn.cursor() as cur:
            # Find ranges stuck in PROVISIONING
            provisioning_cutoff = now - timedelta(minutes=PROVISIONING_TIMEOUT_MINUTES)
            cur.execute(
                """
                SELECT id, status, created_at, updated_at
                FROM mission_control_range
                WHERE status = 'provisioning'
                  AND updated_at < %s
                """,
                (provisioning_cutoff,),
            )

            for row in cur.fetchall():
                range_id, status, created_at, updated_at = row
                stale_ranges.append({
                    "range_id": str(range_id),
                    "status": status,
                    "reason": f"Stuck in provisioning since {updated_at}",
                    "minutes_stale": int((now - updated_at).total_seconds() / 60),
                })
                logger.warning(
                    f"Found stale provisioning range: {range_id}, "
                    f"last updated {updated_at}"
                )

            # Find ranges stuck in DESTROYING
            destroying_cutoff = now - timedelta(minutes=DESTROYING_TIMEOUT_MINUTES)
            cur.execute(
                """
                SELECT id, status, created_at, updated_at
                FROM mission_control_range
                WHERE status = 'destroying'
                  AND updated_at < %s
                """,
                (destroying_cutoff,),
            )

            for row in cur.fetchall():
                range_id, status, created_at, updated_at = row
                stale_ranges.append({
                    "range_id": str(range_id),
                    "status": status,
                    "reason": f"Stuck in destroying since {updated_at}",
                    "minutes_stale": int((now - updated_at).total_seconds() / 60),
                })
                logger.warning(
                    f"Found stale destroying range: {range_id}, "
                    f"last updated {updated_at}"
                )

        logger.info(f"Found {len(stale_ranges)} stale ranges")

        return {
            "stale_ranges": stale_ranges,
            "checked_at": now.isoformat(),
        }

    finally:
        conn.close()
