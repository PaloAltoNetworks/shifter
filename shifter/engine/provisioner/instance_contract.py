"""Provider-neutral image-contract fields on realized instance outputs."""

from __future__ import annotations

from collections.abc import Mapping


def instance_field(instance: Mapping[str, object], name: str) -> object:
    """Read a provider-neutral instance field, falling back to its legacy ``gcp_`` key.

    GCE outputs recorded before the neutral keys existed carry only the
    ``gcp_``-prefixed names; native EC2 outputs carry only the neutral ones.
    """
    if name in instance:
        return instance[name]
    return instance.get(f"gcp_{name}")


__all__ = ["instance_field"]
