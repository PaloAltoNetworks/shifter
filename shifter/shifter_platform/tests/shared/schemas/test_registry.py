"""Tests for shared.schemas.registry."""

import pytest

from shared.schemas.registry import (
    LEGACY_DOTTED_PATH_TO_SLUG,
    UnknownSpecSlugError,
    get_model_for_slug,
    resolve_catalog_slug,
)


def test_get_model_for_catalog_slugs():
    from shared.schemas import DeploymentProfileSpec, InstanceSpec, NGFWAppSpec, SCMCredentialSpec

    assert get_model_for_slug("credential.scm") is SCMCredentialSpec
    assert get_model_for_slug("credential.deployment_profile") is DeploymentProfileSpec
    assert get_model_for_slug("instance.panw-ngfw") is InstanceSpec
    assert get_model_for_slug("app.panw-ngfw") is NGFWAppSpec


def test_get_model_for_persisted_blob_slugs():
    from shared.schemas import InstanceSpec, NGFWAppSpec, RangeSpec, SubnetSpec

    assert get_model_for_slug("range_spec") is RangeSpec
    assert get_model_for_slug("instance_spec") is InstanceSpec
    assert get_model_for_slug("subnet_spec") is SubnetSpec
    assert get_model_for_slug("ngfw_app_spec") is NGFWAppSpec


def test_unknown_slug_raises():
    with pytest.raises(UnknownSpecSlugError):
        get_model_for_slug("does.not.exist")


def test_resolve_catalog_slug_from_legacy_path():
    assert resolve_catalog_slug("shared.schemas.SCMCredentialSpec") == "credential.scm"
    assert resolve_catalog_slug("shared.schemas.DeploymentProfileSpec") == "credential.deployment_profile"
    assert resolve_catalog_slug("shared.schemas.range.InstanceSpec") == "instance.panw-ngfw"
    assert resolve_catalog_slug("shared.schemas.app.NGFWAppSpec") == "app.panw-ngfw"


def test_legacy_path_map_covers_seed_migration_paths():
    seed_paths = {
        "shared.schemas.SCMCredentialSpec",
        "shared.schemas.DeploymentProfileSpec",
        "shared.schemas.range.InstanceSpec",
        "shared.schemas.app.NGFWAppSpec",
    }
    assert seed_paths <= set(LEGACY_DOTTED_PATH_TO_SLUG)
