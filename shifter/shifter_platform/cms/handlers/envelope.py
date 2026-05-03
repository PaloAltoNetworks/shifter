"""SNS/SQS envelope unwrapping for CMS event handlers."""

from __future__ import annotations

import json


def parse_sns_message(message: str | dict) -> dict:
    """Unwrap SNS envelope to get event payload.

    SNS wraps messages in an envelope with a "Message" key containing
    the actual event payload as a JSON string.

    Args:
        message: Either a dict (SNS envelope or direct event) or
                 a JSON string representation of either.

    Returns:
        The parsed event payload as a dict.
    """
    body = json.loads(message) if isinstance(message, str) else message

    if "Message" in body:
        return json.loads(body["Message"])

    return body
