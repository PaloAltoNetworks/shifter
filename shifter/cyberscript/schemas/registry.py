"""Stable slug registry for cyberscript Pydantic schema classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

LEGACY_DOTTED_PATH_TO_SLUG: dict[str, str] = {
    "shared.schemas.SCMCredentialSpec": "credential.scm",
    "shared.schemas.DeploymentProfileSpec": "credential.deployment_profile",
    "shared.schemas.range.InstanceSpec": "instance.panw-ngfw",
    "shared.schemas.app.NGFWAppSpec": "app.panw-ngfw",
}


class UnknownSpecSlugError(LookupError):
    """Raised when a slug is not registered."""


def _build_registry() -> dict[str, type[BaseModel]]:
    from .app import NGFWAppSpec
    from .credentials import DeploymentProfileSpec, SCMCredentialSpec
    from .ctf import CTFRangeSpec
    from .range import InstanceSpec, RangeSpec
    from .subnet import SubnetSpec

    return {
        "credential.scm": SCMCredentialSpec,
        "credential.deployment_profile": DeploymentProfileSpec,
        "instance.panw-ngfw": InstanceSpec,
        "app.panw-ngfw": NGFWAppSpec,
        "range_spec": RangeSpec,
        "ctf_range_spec": CTFRangeSpec,
        "instance_spec": InstanceSpec,
        "subnet_spec": SubnetSpec,
        "ngfw_app_spec": NGFWAppSpec,
    }


_REGISTRY: dict[str, type[BaseModel]] | None = None


def _registry() -> dict[str, type[BaseModel]]:
    global _REGISTRY  # noqa: PLW0603
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def get_model_for_slug(slug: str) -> type[BaseModel]:
    """Return the Pydantic model class for a stable schema slug."""
    try:
        return _registry()[slug]
    except KeyError as exc:
        raise UnknownSpecSlugError(f"Unknown schema slug: {slug}") from exc


def resolve_catalog_slug(dotted_path: str) -> str:
    """Map a legacy catalog ``spec_class`` dotted path to its slug."""
    try:
        return LEGACY_DOTTED_PATH_TO_SLUG[dotted_path]
    except KeyError as exc:
        raise UnknownSpecSlugError(f"Unknown legacy spec_class path: {dotted_path}") from exc
