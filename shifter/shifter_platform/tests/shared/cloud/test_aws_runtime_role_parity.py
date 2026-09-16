"""Single-source backstop for the AWS provisioner-Job env contract (#1826).

``installation.runtime_inventory.AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS`` is the
authoritative key set the standalone AWS (EKS) provisioner Job receives (it is the
published bundle contract). The platform task runner consumes that same set as
``engine.ecs._AWS_PROVISIONER_ENV_KEYS`` — it does not maintain a second copy, so
the two cannot drift. This test pins that single-source relationship: if someone
reintroduces a separate platform-side list, the identity check fails.
"""

from __future__ import annotations

from installation.runtime_inventory import AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS

from engine.ecs import _AWS_PROVISIONER_ENV_KEYS


def test_forwarding_list_is_single_sourced_from_the_installation_contract() -> None:
    assert _AWS_PROVISIONER_ENV_KEYS is AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS, (
        "engine.ecs._AWS_PROVISIONER_ENV_KEYS must be the installation bundle contract "
        "AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS itself, not a separate copy"
    )


def test_forwarding_list_has_no_duplicate_keys() -> None:
    assert len(_AWS_PROVISIONER_ENV_KEYS) == len(set(_AWS_PROVISIONER_ENV_KEYS))
