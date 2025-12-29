"""Range serialization service.

This module handles serialization of Range objects to JSON-compatible dicts.
"""

from mission_control.models import Range


def range_to_dict(range_obj: Range) -> dict:
    """Serialize a Range object to JSON-compatible dict for client.

    Note: Sensitive fields are intentionally excluded:
    - victim_ip: internal infrastructure detail
    - kali_ip: internal infrastructure detail
    - ssh key ARNs: security-sensitive
    - subnet_index: internal infrastructure detail

    Args:
        range_obj: The Range object to serialize

    Returns:
        dict: JSON-serializable dictionary representation
    """
    return {
        "id": range_obj.id,
        "status": range_obj.status,
        "agent_id": range_obj.agent_id,
        "agent_name": range_obj.agent.name if range_obj.agent else None,
        "dc_agent_id": range_obj.dc_agent_id,
        "dc_agent_name": range_obj.dc_agent.name if range_obj.dc_agent else None,
        "chat_url": range_obj.chat_url,
        "error_message": range_obj.error_message,
        "created_at": range_obj.created_at.isoformat() if range_obj.created_at else None,
        "ready_at": range_obj.ready_at.isoformat() if range_obj.ready_at else None,
        "paused_at": range_obj.paused_at.isoformat() if range_obj.paused_at else None,
    }
