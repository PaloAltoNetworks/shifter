"""Upload session management.

This module handles the upload lock mechanism that prevents
concurrent uploads from the same user.
"""

import time
from typing import Any

# Upload lock timeout in seconds (fallback for browser crash, network loss)
UPLOAD_LOCK_TIMEOUT = 30


def check_upload_in_progress(session: dict[str, Any]) -> bool:
    """Check if user has an upload in progress (stored in session).

    Args:
        session: Django session object (or dict-like)

    Returns:
        bool: True if upload is in progress and lock is valid, False otherwise
    """
    lock_data = session.get("upload_lock")
    if not lock_data:
        return False

    # Auto-expire stale locks
    if time.time() - lock_data.get("started_at", 0) > UPLOAD_LOCK_TIMEOUT:
        set_upload_in_progress(session, False)
        return False

    return True


def set_upload_in_progress(session: dict[str, Any], in_progress: bool) -> None:
    """Set upload in progress flag in session.

    Args:
        session: Django session object (or dict-like)
        in_progress: True to set lock, False to clear it
    """
    if in_progress:
        session["upload_lock"] = {"started_at": time.time()}
    else:
        session.pop("upload_lock", None)
