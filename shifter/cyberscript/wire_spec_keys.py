"""Canonical JSON keys the ECS provisioner dict-walks on persisted range specs.

Schema-aligned keys must exist on the cyberscript Pydantic models. Runtime keys
are assigned during provisioning and are intentionally not part of the DSL
kernel; they are listed here so renames fail contract tests instead of shipping
silently across the process boundary.
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
