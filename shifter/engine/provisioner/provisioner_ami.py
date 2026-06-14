"""AMI ID resolution for the Shifter Engine provisioner.

Resolves AMI IDs from SSM Parameter Store at runtime, with a per-invocation
cache so repeated lookups for the same type do not re-hit the API.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_AMI_SSM_PARAMS = {
    "kali": "/shifter/ami/kali",
    "victim": "/shifter/ami/ubuntu",
    "windows": "/shifter/ami/windows",
    "dc": "/shifter/ami/dc",
}

# Cache for SSM AMI lookups (cleared per invocation, avoids repeated API calls)
_ami_cache: dict[str, str] = {}


def get_ami_id(ami_type: str) -> str:
    """Get AMI ID from SSM Parameter Store at runtime.

    This ensures the provisioner always uses the latest AMI IDs without
    requiring a Terraform apply or ECS task definition update.

    Known types ('kali', 'victim', 'windows', 'dc') use legacy SSM paths.
    Custom ami_key values resolve to /shifter/ami/<ami_key>.

    Args:
        ami_type: Known type or custom ami_key (e.g. 'kali', 'windows').

    Returns:
        AMI ID string

    Raises:
        ValueError: If SSM parameter not found.
    """
    if ami_type in _ami_cache:
        return _ami_cache[ami_type]

    # Known types use legacy SSM paths; custom keys construct path directly
    param_path = _AMI_SSM_PARAMS.get(ami_type)
    if not param_path:
        param_path = f"/shifter/ami/{ami_type}"

    try:
        from cloud import get_config_store

        store = get_config_store()
        ami_id = store.get_parameter(param_path)
        logger.info("Fetched %s AMI from SSM %s: %s", ami_type, param_path, ami_id)
        _ami_cache[ami_type] = ami_id
        return ami_id
    except Exception as e:
        # No fallback - fail fast to surface IAM/config issues immediately
        raise ValueError(f"Failed to get {ami_type} AMI ID from SSM parameter {param_path}: {e}") from e
