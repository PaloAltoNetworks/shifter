"""Parity backstop between the installation GCP runtime-role manifest and the platform
task runner's forwarding list (#729).

``installation.runtime_inventory_gcp.GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS`` declares which
generated GCP runtime-env keys the standalone provisioner Job receives, so the backend
bundle can publish accurate per-key ``process_roles`` (portal/worker for every key, plus
provisioner for the forwarded subset). The installation package is standalone and cannot
import the Django platform, so that set is maintained as data. This test — which lives in
the platform suite, where both modules are importable — fails if it drifts from the
authoritative forwarding list ``engine.ecs._GCP_PROVISIONER_ENV_KEYS``.
"""

from __future__ import annotations

from installation.runtime_inventory_gcp import (
    GCP_GENERATED_RUNTIME_ENV_KEYS,
    GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS,
    GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS,
)

from engine.ecs import _GCP_PROVISIONER_ENV_KEYS


def test_forwarded_manifest_matches_task_runner_intersected_with_generated_keys() -> None:
    generated = set(GCP_GENERATED_RUNTIME_ENV_KEYS) | set(GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS)
    expected = set(_GCP_PROVISIONER_ENV_KEYS) & generated
    assert expected == GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS, (
        "installation.runtime_inventory_gcp.GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS has drifted from "
        "engine.ecs._GCP_PROVISIONER_ENV_KEYS ∩ the generated GCP key set; update the installation manifest"
    )


def test_forwarded_manifest_is_a_subset_of_the_generated_keys() -> None:
    generated = set(GCP_GENERATED_RUNTIME_ENV_KEYS) | set(GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS)
    assert generated >= GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS
