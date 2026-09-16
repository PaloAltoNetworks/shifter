"""Canonical JSON keys the ECS provisioner dict-walks on persisted range specs.

Schema-aligned keys describe the archived persisted envelope reader. Runtime
keys are assigned during cleanup and are listed here so renames fail contract
tests instead of shipping silently across the process boundary.
"""

from __future__ import annotations

RANGE_SPEC_TOP_LEVEL_SCHEMA_KEYS = frozenset({"subnets", "ngfw"})

SUBNET_SCHEMA_KEYS = frozenset({"name", "uuid", "instances", "connected_to"})
SUBNET_RUNTIME_KEYS = frozenset({"cidr", "provider_metadata"})

INSTANCE_SCHEMA_KEYS = frozenset(
    {
        "name",
        "uuid",
        "role",
        "os_type",
        "agent",
        "join_domain",
        "ami_key",
        "instance_type",
    }
)
INSTANCE_RUNTIME_KEYS = frozenset({"asset_type"})

AGENT_SCHEMA_KEYS = frozenset({"s3_key", "filename", "sha256"})

__all__ = [
    "AGENT_SCHEMA_KEYS",
    "INSTANCE_RUNTIME_KEYS",
    "INSTANCE_SCHEMA_KEYS",
    "RANGE_SPEC_TOP_LEVEL_SCHEMA_KEYS",
    "SUBNET_RUNTIME_KEYS",
    "SUBNET_SCHEMA_KEYS",
]
